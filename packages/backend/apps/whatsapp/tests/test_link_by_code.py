"""
Tests for linking a member's phone with a code they receive on WhatsApp and type on the website (WhatsApp plan
phase 7, user story WA.D1.OM.J1.A3; decided 2026-11-09: WhatsApp only, no SMS, and the link completes when the
phone first writes).

- PHONE_VERIFICATION_CHANNEL chooses WHATSAPP_INBOUND (the default: "link <code>" sent from the phone, Step 1.7)
  or WHATSAPP_TEMPLATE; the startup check refuses any other value, SMS included
- with WHATSAPP_TEMPLATE, connecting a team number submits the authentication template (a fixed Meta wording
  with a copy-code button, its expiry the code's), and the command submits it to every team number
- starting a link sends the code from the organization's team number in that template, and the page is given
  no code and no link; Meta refusing is said plainly
- typing the code proves the number: a phone that has written to the team number before is linked at once;
  one that hasn't is linked when it first writes, its first message then answered as a member's, within
  WAITING_LINK_DAYS and while the user is still a member
- the GraphQL API: startWhatsAppLink says which channel it used, confirmWhatsAppLink takes the typed code, and
  a waiting link shows on the profile

Kind of test: integration (agents.md section 2.5). Why: users, numbers, contacts, codes and links are rows in
the test database, and the API goes through the real GraphQL schema; nothing reaches Meta: the send backend
is a fake that records what it's given, and Celery's delay is patched where queuing is checked. The settings
test is sanity: it reads settings in a fresh subprocess.
"""

from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone
from graphql_relay import to_global_id

from apps.multitenancy.constants import TenantType, TenantUserRole
from apps.multitenancy.models import TenantMembership
from apps.multitenancy.tests.factories import TenantFactory, TenantMembershipFactory
from apps.users.tests.factories import UserFactory

from ..builders import template_message
from ..client import PermanentSendError
from ..constants import AccountPurpose, SendBackend
from ..models import WhatsAppIdentity, WhatsAppTemplate
from ..services import accounts, identity
from ..services.identity import IdentityError
from .factories import ContactFactory, ExternalAccountFactory, InternalAccountFactory
from .test_checks import VALID_WHATSAPP_SETTINGS
from .utils import read_settings

pytestmark = [pytest.mark.django_db, pytest.mark.story("WA.D1.OM.J1.A3")]

NUMBER = "27831234567"


class FakeSender:
    """The send backend's part linking uses: records each template message, or raises `error`."""

    def __init__(self, error=None):
        self.sent = []
        self.error = error

    def send_message_to(self, account, to, message):
        if self.error is not None:
            raise self.error
        self.sent.append((account, to, message))
        return "wamid.LINK0001"


@pytest.fixture
def by_template(settings):
    settings.PHONE_VERIFICATION_CHANNEL = "WHATSAPP_TEMPLATE"
    settings.WHATSAPP_LINK_CODE_TTL_SECONDS = 600
    settings.WEB_APP_URL = "https://app.example.com"


@pytest.fixture
def acme():
    return TenantFactory(type=TenantType.ORGANIZATION, name="Acme")


@pytest.fixture
def team_number(acme):
    return InternalAccountFactory(tenant=acme, display_phone_number="+27 00 000 0000")


@pytest.fixture
def user(acme):
    user = UserFactory()
    TenantMembershipFactory(user=user, tenant=acme, role=TenantUserRole.MEMBER)
    return user


@pytest.fixture
def sender(mocker):
    fake = FakeSender()
    mocker.patch("apps.whatsapp.services.identity.send_backend", return_value=fake)
    return fake


def code_sent(fake):
    """The code in the one template message sent, read from its body, as the member reads it."""
    [(_account, _to, message)] = fake.sent
    return message["template"]["components"][0]["parameters"][0]["text"]


class TestTheSetting:
    def test_it_defaults_to_inbound_linking_and_reads_its_variable(self):
        assert read_settings(["PHONE_VERIFICATION_CHANNEL"], PHONE_VERIFICATION_CHANNEL=None) == {
            "PHONE_VERIFICATION_CHANNEL": "'WHATSAPP_INBOUND'"
        }
        assert read_settings(["PHONE_VERIFICATION_CHANNEL"], PHONE_VERIFICATION_CHANNEL="WHATSAPP_TEMPLATE") == {
            "PHONE_VERIFICATION_CHANNEL": "'WHATSAPP_TEMPLATE'"
        }

    @pytest.mark.parametrize("value", ["WHATSAPP_INBOUND", "WHATSAPP_TEMPLATE"])
    def test_the_check_accepts_both_whatsapp_channels(self, value):
        from ..checks import check_whatsapp_settings

        with override_settings(**VALID_WHATSAPP_SETTINGS, PHONE_VERIFICATION_CHANNEL=value):
            assert [error.id for error in check_whatsapp_settings(app_configs=None)] == []

    @pytest.mark.parametrize("value", ["SMS", "whatsapp_template", ""])
    def test_the_check_refuses_anything_else_sms_included(self, value):
        from ..checks import check_whatsapp_settings

        with override_settings(**VALID_WHATSAPP_SETTINGS, PHONE_VERIFICATION_CHANNEL=value):
            assert [error.id for error in check_whatsapp_settings(app_configs=None)] == ["whatsapp.E010"]


class TestTheTemplate:
    def test_it_is_an_authentication_template_with_a_copy_code_button_and_the_codes_expiry(self, by_template):
        template = identity.link_template()

        assert template["category"] == "AUTHENTICATION"
        assert template["language"] == "en"
        assert template["components"] == [
            {"type": "BODY", "add_security_recommendation": True},
            {"type": "FOOTER", "code_expiration_minutes": 10},
            {"type": "BUTTONS", "buttons": [{"type": "OTP", "otp_type": "COPY_CODE", "text": "Copy code"}]},
        ]

    def test_connecting_a_team_number_submits_it_in_a_task(
        self, by_template, team_number, mocker, django_capture_on_commit_callbacks
    ):
        delay = mocker.patch("apps.whatsapp.tasks.publish_link_template.delay")

        with django_capture_on_commit_callbacks(execute=True):
            accounts._set_up(team_number, [AccountPurpose.INTERNAL_COMMUNICATIONS])

        delay.assert_called_once_with(str(team_number.pk))

    def test_with_inbound_linking_nothing_is_submitted(
        self, settings, team_number, mocker, django_capture_on_commit_callbacks
    ):
        settings.PHONE_VERIFICATION_CHANNEL = "WHATSAPP_INBOUND"
        delay = mocker.patch("apps.whatsapp.tasks.publish_link_template.delay")

        with django_capture_on_commit_callbacks(execute=True):
            accounts._set_up(team_number, [AccountPurpose.INTERNAL_COMMUNICATIONS])

        delay.assert_not_called()

    def test_the_task_stores_it_for_a_team_number_only(self, by_template, team_number, settings):
        from ..tasks import publish_link_template

        settings.WHATSAPP_SEND_BACKEND = SendBackend.LOG
        customers_only = ExternalAccountFactory()

        publish_link_template(str(team_number.pk))
        publish_link_template(str(customers_only.pk))

        assert WhatsAppTemplate.objects.filter(waba_id=team_number.waba_id, name=identity.LINK_TEMPLATE).exists()
        assert not WhatsAppTemplate.objects.filter(waba_id=customers_only.waba_id).exists()

    def test_the_command_submits_it_to_every_active_team_number(self, by_template, team_number, settings):
        settings.WHATSAPP_SEND_BACKEND = SendBackend.LOG
        out = StringIO()

        call_command("whatsapp_publish_link_templates", stdout=out)

        assert WhatsAppTemplate.objects.filter(waba_id=team_number.waba_id, name=identity.LINK_TEMPLATE).exists()
        assert identity.LINK_TEMPLATE in out.getvalue()


class TestStartingALink:
    def test_the_code_is_sent_from_the_team_number_and_the_page_gets_none(
        self, by_template, acme, team_number, user, sender
    ):
        started = identity.start_link(user, acme, "083 123 4567")

        assert started.code == ""
        assert started.link == ""
        assert started.channel == "WHATSAPP_TEMPLATE"
        [(account, to, message)] = sender.sent
        assert (account, to) == (team_number, NUMBER)
        code = code_sent(sender)
        assert message == template_message(identity.LINK_TEMPLATE, language="en", body=[code], url_suffix=code)

    def test_meta_refusing_is_said_plainly(self, by_template, acme, team_number, user, mocker):
        mocker.patch(
            "apps.whatsapp.services.identity.send_backend",
            return_value=FakeSender(error=PermanentSendError(132001, "Meta error 132001: template does not exist")),
        )

        with pytest.raises(IdentityError) as raised:
            identity.start_link(user, acme, NUMBER)

        assert raised.value.code == "not_sent"
        assert "couldn't be sent" in str(raised.value)

    def test_inbound_linking_still_shows_the_code_and_the_link(self, settings, acme, team_number, user):
        settings.PHONE_VERIFICATION_CHANNEL = "WHATSAPP_INBOUND"

        started = identity.start_link(user, acme, NUMBER)

        assert started.code and started.link.startswith("https://wa.me/")
        assert started.channel == "WHATSAPP_INBOUND"


class TestTypingTheCode:
    def test_a_phone_that_wrote_before_is_linked_at_once(self, by_template, acme, team_number, user, sender):
        contact = ContactFactory(account=team_number, wa_id=NUMBER)
        identity.start_link(user, acme, NUMBER)

        result = identity.confirm_link(user, acme, NUMBER, code_sent(sender))

        assert result == identity.LINKED
        assert WhatsAppIdentity.objects.get(contact=contact).user == user

    def test_a_phone_that_never_wrote_is_linked_when_it_first_writes(
        self, by_template, acme, team_number, user, sender
    ):
        identity.start_link(user, acme, NUMBER)

        result = identity.confirm_link(user, acme, NUMBER, code_sent(sender))

        assert result == identity.WAITING
        assert not WhatsAppIdentity.objects.exists()
        contact = ContactFactory(account=team_number, wa_id=NUMBER)
        linked = identity.identity_for(contact)
        assert linked is not None and linked.user == user
        assert not identity.waiting_link_for(user, team_number)

    def test_a_wrong_code_links_nothing(self, by_template, acme, team_number, user, sender):
        identity.start_link(user, acme, NUMBER)
        wrong = "000000" if code_sent(sender) != "000000" else "111111"

        with pytest.raises(IdentityError) as raised:
            identity.confirm_link(user, acme, NUMBER, wrong)

        assert raised.value.code == "wrong_code"

    def test_another_users_code_links_nothing(self, by_template, acme, team_number, user, sender):
        identity.start_link(user, acme, NUMBER)
        someone_else = UserFactory()
        TenantMembershipFactory(user=someone_else, tenant=acme, role=TenantUserRole.MEMBER)

        with pytest.raises(IdentityError):
            identity.confirm_link(someone_else, acme, NUMBER, code_sent(sender))

    def test_a_code_sent_for_inbound_linking_doesnt_work_here(self, settings, acme, team_number, user):
        settings.PHONE_VERIFICATION_CHANNEL = "WHATSAPP_INBOUND"
        started = identity.start_link(user, acme, NUMBER)
        settings.PHONE_VERIFICATION_CHANNEL = "WHATSAPP_TEMPLATE"

        with pytest.raises(IdentityError):
            identity.confirm_link(user, acme, NUMBER, started.code)

    def test_a_waiting_link_past_its_days_completes_nothing(
        self, by_template, acme, team_number, user, sender, freezer
    ):
        identity.start_link(user, acme, NUMBER)
        identity.confirm_link(user, acme, NUMBER, code_sent(sender))
        freezer.move_to(timezone.now() + timedelta(days=identity.WAITING_LINK_DAYS, minutes=1))

        assert identity.identity_for(ContactFactory(account=team_number, wa_id=NUMBER)) is None

    def test_a_user_who_left_the_organization_isnt_linked_when_the_phone_writes(
        self, by_template, acme, team_number, user, sender
    ):
        identity.start_link(user, acme, NUMBER)
        identity.confirm_link(user, acme, NUMBER, code_sent(sender))
        TenantMembership.objects.filter(user=user, tenant=acme).delete()

        assert identity.identity_for(ContactFactory(account=team_number, wa_id=NUMBER)) is None
        assert not WhatsAppIdentity.objects.exists()


START = """
mutation($input: StartWhatsAppLinkInput!) {
  startWhatsAppLink(input: $input) { code link channel maskedNumber }
}
"""

CONFIRM = """
mutation($input: ConfirmWhatsAppLinkInput!) {
  confirmWhatsAppLink(input: $input) { waiting link { linked waiting maskedNumber } }
}
"""

LINKS = """
query { whatsAppLinks { organizationName linked waiting } }
"""


class TestTheApi:
    @pytest.fixture
    def logged_in(self, graphene_client, user):
        graphene_client.force_authenticate(user)
        return graphene_client

    def tenant_id(self, acme):
        return to_global_id("TenantType", str(acme.id))

    def test_starting_says_which_channel_and_gives_no_code(self, by_template, logged_in, acme, team_number, sender):
        response = logged_in.query(
            START, variable_values={"input": {"tenantId": self.tenant_id(acme), "phoneNumber": NUMBER}}
        )

        assert "errors" not in response, response
        assert response["data"]["startWhatsAppLink"] == {
            "code": "",
            "link": "",
            "channel": "WHATSAPP_TEMPLATE",
            "maskedNumber": "*******4567",
        }

    def test_the_typed_code_saves_a_waiting_link_shown_on_the_profile(
        self, by_template, logged_in, acme, team_number, sender
    ):
        logged_in.query(START, variable_values={"input": {"tenantId": self.tenant_id(acme), "phoneNumber": NUMBER}})

        response = logged_in.query(
            CONFIRM,
            variable_values={
                "input": {"tenantId": self.tenant_id(acme), "phoneNumber": NUMBER, "code": code_sent(sender)}
            },
        )

        assert "errors" not in response, response
        assert response["data"]["confirmWhatsAppLink"] == {
            "waiting": True,
            "link": {"linked": False, "waiting": True, "maskedNumber": "*******4567"},
        }
        assert logged_in.query(LINKS)["data"]["whatsAppLinks"] == [
            {"organizationName": "Acme", "linked": False, "waiting": True}
        ]

    def test_a_wrong_code_is_refused_under_the_code(self, by_template, logged_in, acme, team_number, sender):
        logged_in.query(START, variable_values={"input": {"tenantId": self.tenant_id(acme), "phoneNumber": NUMBER}})
        wrong = "000000" if code_sent(sender) != "000000" else "111111"

        response = logged_in.query(
            CONFIRM,
            variable_values={"input": {"tenantId": self.tenant_id(acme), "phoneNumber": NUMBER, "code": wrong}},
        )

        assert "code" in response["errors"][0]["extensions"]
