"""
Tests for apps/whatsapp/services/accounts.py: connecting an organization's number with the form,
sending it a test message, and disconnecting it (plan Step 1.5e, user story 11). The GraphQL API
on top of these, with its permission checks, is Step 1.5f.

The maintainer's decisions (plan Step 1.5, 2026-10-17):
- the test message is sent directly, so the admin sees Meta's answer in the form
- disconnecting wipes the secrets and keeps the history; reconnecting in the same organization
  reuses the row
- a number with a row in another organization is refused, even after that one disconnected it

Since Step 1.17 the form says what the number is for: the organization's internal communications
number, of which it has one, or an external communications number. Since Step 1.18 every number is
on our one Meta app: the form takes no App secret, and connecting subscribes our app to the number's
WhatsApp Business account, so its messages reach our webhook.

Meta's references: checking a number,
https://developers.facebook.com/documentation/business-messaging/whatsapp/business-phone-numbers/phone-numbers.md
subscribing an app to a WhatsApp Business account,
https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/onboarding-customers-as-a-tech-provider.md
and template messages,
https://developers.facebook.com/documentation/business-messaging/whatsapp/templates/overview.md

Kind of test: integration (agents.md section 2.5). Why: the service saves and reads accounts in the
test database; Meta's HTTP is mocked.
"""

from datetime import datetime, timezone

import pytest
import requests

from apps.multitenancy.constants import TenantType
from apps.multitenancy.tests.factories import TenantFactory

from .. import registry
from ..constants import AccountPurpose, ConnectionMethod, MessageDirection
from ..models import WhatsAppAccount, WhatsAppContact, WhatsAppIdentity, WhatsAppMessage
from ..services import accounts
from ..services.accounts import AccountError
from .factories import ContactFactory, ExternalAccountFactory, InternalAccountFactory, MessageFactory, link_member
from .fakes import meta_error, meta_response

INTERNAL = AccountPurpose.INTERNAL_COMMUNICATIONS
EXTERNAL = AccountPurpose.EXTERNAL_COMMUNICATIONS

pytestmark = pytest.mark.django_db

PHONE_NUMBER_ID = "100000000000777"
WABA_ID = "200000000000777"
ACCESS_TOKEN = "EAAGacme-access-token"
NOW = datetime(2026, 10, 17, 9, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def graph_api_version(settings):
    settings.WHATSAPP_GRAPH_API_VERSION = "v26.0"


@pytest.fixture
def organization():
    return TenantFactory(type=TenantType.ORGANIZATION)


@pytest.fixture
def meta_get(mocker):
    """Meta's answer to "tell me about this phone number id": known, with its verified business name."""
    return mocker.patch(
        "apps.whatsapp.client.requests.get",
        return_value=meta_response(200, {"display_phone_number": "+27 83 000 0777", "verified_name": "Acme Store"}),
    )


@pytest.fixture(autouse=True)
def meta_subscribe(mocker):
    """Meta's answer to subscribing our app to a WhatsApp Business account: done."""
    return mocker.patch("apps.whatsapp.client.requests.post", return_value=meta_response(200, {"success": True}))


@pytest.fixture
def meta_post(mocker):
    """Meta's answer to a send: accepted, with the new message's id."""
    return mocker.patch(
        "apps.whatsapp.client.requests.post",
        return_value=meta_response(200, {"contacts": [{"wa_id": "27831234567"}], "messages": [{"id": "wamid.TEST1"}]}),
    )


def connect(organization, **overrides):
    """Connect a number for `organization` with the form's fields, as the admin typed them."""
    fields = {
        "purpose": EXTERNAL,
        "phone_number_id": PHONE_NUMBER_ID,
        "waba_id": WABA_ID,
        "access_token": ACCESS_TOKEN,
    }
    return accounts.connect_account(tenant=organization, **{**fields, **overrides})


class TestConnecting:
    def test_meta_is_asked_about_the_number_with_the_typed_token_first(self, organization, meta_get):
        connect(organization)

        assert meta_get.call_args.args[0] == f"https://graph.facebook.com/v26.0/{PHONE_NUMBER_ID}"
        assert meta_get.call_args.kwargs["headers"]["Authorization"] == f"Bearer {ACCESS_TOKEN}"

    @pytest.mark.parametrize("purpose", [INTERNAL, EXTERNAL])
    def test_the_account_is_saved_for_the_organization_with_what_meta_said(
        self, organization, meta_get, freezer, purpose
    ):
        freezer.move_to(NOW)

        account = connect(organization, purpose=purpose).account

        account = WhatsAppAccount.objects.get(pk=account.pk)
        assert account.purpose == purpose
        assert account.tenant == organization
        assert account.phone_number_id == PHONE_NUMBER_ID
        assert account.waba_id == WABA_ID
        # From Meta, not typed: the number as WhatsApp shows it, and the business name it verified.
        assert account.display_phone_number == "+27 83 000 0777"
        assert account.verified_name == "Acme Store"
        assert account.connection_method == ConnectionMethod.MANUAL
        assert account.is_active is True
        # The form's proofs (user story 11): Meta accepted the credentials, and our app is subscribed
        # to the number's WhatsApp Business account, both now (Step 1.18).
        assert account.credentials_verified_at == NOW
        assert account.subscribed_at == NOW

    def test_the_access_token_is_stored_encrypted(self, organization, meta_get):
        account = WhatsAppAccount.objects.get(pk=connect(organization).account.pk)

        assert account.access_token == ACCESS_TOKEN
        assert ACCESS_TOKEN not in account.access_token_encrypted


class TestSubscribingOurApp:
    """Step 1.18: Meta sends a WhatsApp Business account's webhooks to the apps it subscribed."""

    def test_our_app_is_subscribed_to_the_numbers_business_account_with_the_typed_token(
        self, organization, meta_get, meta_subscribe
    ):
        connect(organization)

        assert meta_subscribe.call_args.args[0] == f"https://graph.facebook.com/v26.0/{WABA_ID}/subscribed_apps"
        assert meta_subscribe.call_args.kwargs["headers"]["Authorization"] == f"Bearer {ACCESS_TOKEN}"

    def test_meta_refusing_the_subscription_saves_nothing(self, organization, meta_get, meta_subscribe):
        # 100: e.g. a WhatsApp Business account id this token can't see.
        meta_subscribe.return_value = meta_error(100)

        with pytest.raises(AccountError) as raised:
            connect(organization)

        assert raised.value.code == "meta_refused"
        assert WhatsAppAccount.objects.count() == 0

    def test_the_number_is_checked_before_subscribing(self, organization, meta_get, meta_subscribe):
        meta_get.return_value = meta_error(190, status=401)

        with pytest.raises(AccountError):
            connect(organization)

        meta_subscribe.assert_not_called()

    def test_the_typed_values_are_trimmed(self, organization, meta_get):
        # Pasted values often carry a space or a line break.
        account = connect(
            organization, phone_number_id=f" {PHONE_NUMBER_ID}\n", access_token=f"{ACCESS_TOKEN} "
        ).account

        assert account.phone_number_id == PHONE_NUMBER_ID
        assert WhatsAppAccount.objects.get(pk=account.pk).access_token == ACCESS_TOKEN

    @pytest.mark.parametrize("field", ["phone_number_id", "waba_id", "access_token"])
    def test_every_field_is_required_and_meta_isnt_asked_without_it(self, organization, meta_get, field):
        with pytest.raises(AccountError) as raised:
            connect(organization, **{field: "  "})

        assert raised.value.code == "required"
        assert raised.value.field == field
        meta_get.assert_not_called()
        assert WhatsAppAccount.objects.count() == 0

    def test_a_purpose_that_isnt_one_is_refused(self, organization, meta_get):
        with pytest.raises(AccountError) as raised:
            connect(organization, purpose="PLATFORM")

        assert raised.value.code == "invalid_purpose"
        meta_get.assert_not_called()


class TestOneInternalNumberPerOrganization:
    """Step 1.17: the team texts one number, so a second one is refused before Meta is asked."""

    def test_a_second_internal_number_is_refused(self, organization, meta_get):
        InternalAccountFactory(tenant=organization)

        with pytest.raises(AccountError) as raised:
            connect(organization, purpose=INTERNAL)

        assert raised.value.code == "internal_number_exists"
        # Since Step 2.7 the first can also change whom it serves, instead of being disconnected.
        assert "change or disconnect" in str(raised.value)
        meta_get.assert_not_called()

    def test_after_disconnecting_the_first_another_can_be_connected(self, organization, meta_get):
        InternalAccountFactory(tenant=organization, is_active=False)

        account = connect(organization, purpose=INTERNAL).account

        assert WhatsAppAccount.objects.internal_for(organization) == account

    def test_reconnecting_the_same_internal_number_refreshes_it(self, organization, meta_get):
        first = connect(organization, purpose=INTERNAL)

        second = connect(organization, purpose=INTERNAL, access_token="EAAGnew-token")

        assert second.account.pk == first.account.pk

    def test_another_external_number_is_fine(self, organization, meta_get):
        ExternalAccountFactory(tenant=organization)

        connect(organization, purpose=EXTERNAL)

        assert organization.whatsapp_accounts.count() == 2

    @pytest.mark.parametrize("existing, wanted", [(EXTERNAL, INTERNAL), (INTERNAL, EXTERNAL)])
    def test_a_number_already_connected_for_the_other_purpose_is_refused(
        self, organization, meta_get, existing, wanted
    ):
        # One number for both is a later step (plan Step 2.7); until then, it's one or the other.
        connect(organization, purpose=existing)

        with pytest.raises(AccountError) as raised:
            connect(organization, purpose=wanted)

        assert raised.value.code == "connected_for_the_other_purpose"
        assert WhatsAppAccount.objects.get(phone_number_id=PHONE_NUMBER_ID).purpose == existing


class TestTheHandlerHearsAboutIt:
    """The app that answers a purpose's numbers can set a new one up, e.g. publish its forms (D9)."""

    @pytest.fixture
    def handler(self, mocker):
        handler = mocker.Mock(spec=["on_connected"])
        mocker.patch.dict(registry._handlers, {INTERNAL: handler}, clear=True)
        return handler

    def test_it_is_told_once_the_account_is_saved(
        self, organization, meta_get, handler, django_capture_on_commit_callbacks
    ):
        with django_capture_on_commit_callbacks(execute=False) as callbacks:
            account = connect(organization, purpose=INTERNAL).account
        handler.on_connected.assert_not_called()

        for callback in callbacks:
            callback()

        handler.on_connected.assert_called_once_with(account)

    def test_a_purpose_without_a_handler_needs_none(
        self, organization, meta_get, handler, django_capture_on_commit_callbacks
    ):
        with django_capture_on_commit_callbacks(execute=True):
            connect(organization, purpose=EXTERNAL)

        handler.on_connected.assert_not_called()

    def test_a_handler_without_the_hook_is_left_alone(
        self, organization, meta_get, mocker, django_capture_on_commit_callbacks
    ):
        mocker.patch.dict(registry._handlers, {INTERNAL: object()}, clear=True)

        with django_capture_on_commit_callbacks(execute=True):
            account = connect(organization, purpose=INTERNAL).account

        assert account.is_active


class TestMetaSaysNo:
    @pytest.mark.parametrize(
        "answer, code",
        [
            (meta_error(190, status=401), "token_rejected"),  # the access token is wrong or expired
            (meta_error(100), "meta_refused"),  # an id that isn't a phone number id this token can see
        ],
        ids=["token-rejected", "unknown-id"],
    )
    def test_nothing_is_saved_and_the_error_says_why(self, organization, meta_get, answer, code):
        meta_get.return_value = answer

        with pytest.raises(AccountError) as raised:
            connect(organization)

        assert raised.value.code == code
        # The message is shown in the form; it never repeats the token.
        assert ACCESS_TOKEN not in str(raised.value)
        assert WhatsAppAccount.objects.count() == 0

    def test_meta_out_of_reach_asks_to_try_again(self, organization, meta_get):
        meta_get.side_effect = requests.Timeout("timed out")

        with pytest.raises(AccountError) as raised:
            connect(organization)

        assert raised.value.code == "try_again_later"
        assert WhatsAppAccount.objects.count() == 0


class TestOneOrganizationPerNumber:
    @pytest.mark.parametrize("factory", [InternalAccountFactory, ExternalAccountFactory])
    def test_a_number_connected_to_another_organization_is_refused_before_asking_meta(
        self, organization, meta_get, factory
    ):
        factory(phone_number_id=PHONE_NUMBER_ID)

        with pytest.raises(AccountError) as raised:
            connect(organization)

        assert raised.value.code == "already_connected"
        meta_get.assert_not_called()

    def test_a_number_another_organization_disconnected_is_still_refused(self, organization, meta_get):
        # Its row holds that organization's customers' messages; the operator frees it in the admin.
        ExternalAccountFactory(phone_number_id=PHONE_NUMBER_ID, is_active=False)

        with pytest.raises(AccountError) as raised:
            connect(organization)

        assert raised.value.code == "already_connected"

    def test_reconnecting_in_the_same_organization_reuses_the_row_with_fresh_credentials(self, organization, meta_get):
        first = connect(organization)
        accounts.disconnect_account(tenant=organization, account_id=first.account.pk)

        second = connect(organization, access_token="EAAGnew-token")

        assert second.account.pk == first.account.pk
        account = WhatsAppAccount.objects.get(pk=second.account.pk)
        assert account.is_active is True
        assert account.access_token == "EAAGnew-token"


class TestDisconnecting:
    def test_disconnecting_wipes_the_secrets_and_deletes_the_conversations(self, organization, meta_get):
        # Plan Step 2.8, finding 17 (replacing Step 1.5's choice to keep them): numbers are recycled,
        # so a disconnected number's history must never reach whoever gets the number next.
        account = ExternalAccountFactory(tenant=organization)
        contact = ContactFactory(account=account)
        MessageFactory(contact=contact)
        member = ContactFactory(account=account, wa_id="27000002002")
        link_member(member)

        accounts.disconnect_account(tenant=organization, account_id=account.pk)

        account = WhatsAppAccount.objects.get(pk=account.pk)
        assert account.is_active is False
        assert account.access_token_encrypted == ""
        # The contacts go, and with them their messages, conversations and phone links.
        assert not WhatsAppContact.objects.filter(account=account).exists()
        assert not WhatsAppMessage.objects.filter(contact__account=account).exists()
        assert not WhatsAppIdentity.objects.filter(account=account).exists()

    def test_another_numbers_conversations_are_kept(self, organization, meta_get):
        disconnected = ExternalAccountFactory(tenant=organization)
        other = ExternalAccountFactory(tenant=organization)
        kept = ContactFactory(account=other)
        MessageFactory(contact=kept)

        accounts.disconnect_account(tenant=organization, account_id=disconnected.pk)

        assert kept.messages.count() == 1

    def test_an_internal_number_can_be_disconnected_too(self, organization, meta_get):
        account = connect(organization, purpose=INTERNAL).account

        accounts.disconnect_account(tenant=organization, account_id=account.pk)

        assert WhatsAppAccount.objects.internal_for(organization) is None

    def test_another_organizations_number_is_not_found(self, organization, meta_get):
        theirs = ExternalAccountFactory()

        with pytest.raises(AccountError) as raised:
            accounts.disconnect_account(tenant=organization, account_id=theirs.pk)

        # "Not found", not "not allowed": nobody learns which numbers other organizations have.
        assert raised.value.code == "not_found"
        assert WhatsAppAccount.objects.get(pk=theirs.pk).is_active is True


class TestTheTestMessage:
    def test_meta_s_hello_world_template_goes_to_the_typed_number(self, organization, meta_get, meta_post, settings):
        settings.WHATSAPP_SEND_BACKEND = "META"
        account = ExternalAccountFactory(tenant=organization)

        wamid = accounts.send_test_message(tenant=organization, account_id=account.pk, to="083 123 4567")

        assert wamid == "wamid.TEST1"
        body = meta_post.call_args.kwargs["json"]
        # The number typed in any common format is sent as international digits (D19).
        assert body["to"] == "27831234567"
        assert body["template"]["name"] == "hello_world"

    def test_with_the_log_backend_nothing_reaches_meta(self, organization, meta_get, meta_post, settings):
        settings.WHATSAPP_SEND_BACKEND = "LOG"
        account = ExternalAccountFactory(tenant=organization)

        wamid = accounts.send_test_message(tenant=organization, account_id=account.pk, to="083 123 4567")

        assert wamid.startswith("log.")
        meta_post.assert_not_called()

    def test_a_number_that_cant_be_one_is_refused_with_the_reason(self, organization, meta_get, meta_post):
        account = ExternalAccountFactory(tenant=organization)

        with pytest.raises(AccountError) as raised:
            accounts.send_test_message(tenant=organization, account_id=account.pk, to="call me")

        assert raised.value.code == "invalid_phone_number"
        assert "phone number" in str(raised.value)
        meta_post.assert_not_called()

    def test_meta_refusing_it_is_shown_with_meta_s_code(self, organization, meta_get, meta_post, settings):
        settings.WHATSAPP_SEND_BACKEND = "META"
        account = ExternalAccountFactory(tenant=organization)
        # 131026: undeliverable, e.g. the number isn't on WhatsApp.
        meta_post.return_value = meta_error(131026)

        with pytest.raises(AccountError) as raised:
            accounts.send_test_message(tenant=organization, account_id=account.pk, to="083 123 4567")

        assert raised.value.code == "meta_refused"
        assert "131026" in str(raised.value)

    def test_a_disconnected_number_cant_send(self, organization, meta_get, meta_post):
        account = ExternalAccountFactory(tenant=organization)
        accounts.disconnect_account(tenant=organization, account_id=account.pk)

        with pytest.raises(AccountError) as raised:
            accounts.send_test_message(tenant=organization, account_id=account.pk, to="083 123 4567")

        assert raised.value.code == "not_connected"

    def test_another_organizations_number_is_not_found(self, organization, meta_post):
        theirs = InternalAccountFactory()

        with pytest.raises(AccountError) as raised:
            accounts.send_test_message(tenant=organization, account_id=theirs.pk, to="083 123 4567")

        assert raised.value.code == "not_found"


class TestStatus:
    def test_the_last_message_received_is_the_newest_inbound_one(self, organization, meta_get, freezer):
        account = ExternalAccountFactory(tenant=organization)
        contact = ContactFactory(account=account)
        freezer.move_to(NOW)
        MessageFactory(contact=contact)
        freezer.move_to(datetime(2026, 10, 17, 10, 0, tzinfo=timezone.utc))
        latest = MessageFactory(contact=contact)
        # Our own replies don't count: the proof is a message that reached us.
        freezer.move_to(datetime(2026, 10, 17, 11, 0, tzinfo=timezone.utc))
        MessageFactory(contact=contact, direction=MessageDirection.OUTBOUND, wamid="")

        assert accounts.last_message_received_at(account) == latest.created_at

    def test_a_number_that_never_received_anything_has_none(self, organization, meta_get):
        assert accounts.last_message_received_at(connect(organization).account) is None
