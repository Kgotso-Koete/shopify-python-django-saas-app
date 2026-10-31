"""
Tests for one number for both the team and the customers, or two numbers kept apart (plan Step 2.7,
redesigned 2026-10-29, decisions 1 to 3).

- the third purpose, INTERNAL_AND_EXTERNAL_COMMUNICATIONS; an organization has one active number
  serving the team, internal or both, which the database keeps
- on a number serving both, a linked member gets the team's handler, "link <code>" still links, and
  anyone else gets the customers' handler; on a team-only number strangers still get nothing, and on
  a customers-only number members are customers (the wall holds both ways)
- linking and the profile page work on the number serving the team, whichever purpose it has
- connecting counts "both" as the team's number; a disconnected number reconnects with any purpose,
  and an active one is told to change its role on its row
- changing a connected number's role: the same one-team-number rule; leaving the team unlinks its
  members and forgets their conversations; joining the team sets the team's side up (on_connected);
  a disconnected number must be connected again first
- changeWhatsAppNumberPurpose needs whatsapp.manage

Kind of test: integration (agents.md section 2.5). Why: accounts, contacts, links and messages are
rows in the test database, routed through the real router; the two handlers are fakes that say which
one answered, Meta's HTTP is mocked, and the send task's Celery delay is patched.
"""

import pytest
from django.db import IntegrityError, transaction
from graphql_relay import to_global_id

from apps.multitenancy.constants import TenantType, TenantUserRole
from apps.multitenancy.tests.factories import TenantFactory, TenantMembershipFactory
from apps.users.tests.factories import UserFactory

from .. import registry
from ..builders import text_reply
from ..constants import AccountPurpose, ConversationMode, MessageDirection
from ..models import WhatsAppAccount, WhatsAppConversation, WhatsAppIdentity, WhatsAppMessage
from ..services import accounts, identity, router
from ..services.accounts import AccountError
from .factories import ContactFactory, ExternalAccountFactory, InternalAccountFactory, MessageFactory
from .fakes import meta_response

INTERNAL = AccountPurpose.INTERNAL_COMMUNICATIONS
EXTERNAL = AccountPurpose.EXTERNAL_COMMUNICATIONS

pytestmark = pytest.mark.django_db


def both():
    # Looked up here, not at the top, so a missing value fails each test instead of the whole file.
    return AccountPurpose.INTERNAL_AND_EXTERNAL_COMMUNICATIONS


class Handler:
    """Stands in for an app's handler: every screen says whose it is."""

    def __init__(self, name):
        self.name = name
        self.connected = []

    def answers(self, contact):
        return True

    def main_menu(self, turn):
        return text_reply(f"{self.name} MENU")

    def on_choice(self, turn, kind, data):
        return self.main_menu(turn)

    def on_free_text(self, turn, text):
        return self.main_menu(turn)

    def on_typed_answer(self, turn, kind, data, text):
        return self.main_menu(turn)

    def on_flow_reply(self, turn, response):
        return self.main_menu(turn)

    def on_connected(self, account):
        self.connected.append(account)


@pytest.fixture(autouse=True)
def setup(settings, mocker):
    settings.WHATSAPP_DEFAULT_CONVERSATION_MODE = ConversationMode.WHATSAPP_FORM
    settings.WHATSAPP_GRAPH_API_VERSION = "v26.0"
    settings.WEB_APP_URL = "https://app.example.com"
    mocker.patch("apps.whatsapp.tasks.send_queued_messages.delay")


@pytest.fixture
def team(mocker):
    handler = Handler("TEAM")
    mocker.patch.dict(registry._handlers, {INTERNAL: handler})
    return handler


@pytest.fixture
def shop(mocker):
    handler = Handler("SHOP")
    mocker.patch.dict(registry._handlers, {EXTERNAL: handler})
    return handler


@pytest.fixture
def acme():
    return TenantFactory(type=TenantType.ORGANIZATION, name="Acme")


@pytest.fixture
def shared(acme):
    """Acme's one number, for its team and its customers."""
    return InternalAccountFactory(tenant=acme, purpose=both())


def member_on(account, wa_id="27000001001"):
    """A member of the number's organization, with their phone linked on it."""
    user = UserFactory()
    TenantMembershipFactory(user=user, tenant=account.tenant)
    contact = ContactFactory(account=account, wa_id=wa_id)
    WhatsAppIdentity.objects.create(user=user, contact=contact, account=account)
    return user, contact


def replies(contact, text):
    message = MessageFactory(contact=contact, payload={"text": text, "action_id": "", "flow_response": {}})
    router.route(message.pk)
    rows = WhatsAppMessage.objects.filter(contact=contact, direction=MessageDirection.OUTBOUND).order_by("pk")
    texts = [row.payload["interactive"]["body"]["text"] for row in rows]
    rows.delete()
    return texts


class TestThePurpose:
    def test_there_are_three(self):
        assert AccountPurpose.values == [INTERNAL, EXTERNAL, both()]

    def test_which_serve_the_team_and_which_the_customers(self):
        assert AccountPurpose.serves_team(INTERNAL) and AccountPurpose.serves_team(both())
        assert not AccountPurpose.serves_team(EXTERNAL)
        assert AccountPurpose.serves_customers(EXTERNAL) and AccountPurpose.serves_customers(both())
        assert not AccountPurpose.serves_customers(INTERNAL)

    @pytest.mark.parametrize("second", [INTERNAL, "both"])
    def test_the_database_keeps_one_active_number_serving_the_team(self, acme, second):
        InternalAccountFactory(tenant=acme, purpose=both())

        with pytest.raises(IntegrityError), transaction.atomic():
            InternalAccountFactory(tenant=acme, purpose=both() if second == "both" else second)

    def test_the_team_number_is_the_one_serving_the_team(self, acme, shared):
        assert WhatsAppAccount.objects.internal_for(acme) == shared


class TestRouting:
    def test_a_linked_member_gets_the_team_on_a_shared_number(self, shared, team, shop):
        _, contact = member_on(shared)

        assert replies(contact, "hi") == ["TEAM MENU"]

    def test_anyone_else_is_a_customer_on_a_shared_number(self, shared, team, shop):
        assert replies(ContactFactory(account=shared), "hi") == ["SHOP MENU"]

    def test_a_link_command_still_links_on_a_shared_number(self, shared, team, shop):
        stranger = ContactFactory(account=shared, wa_id="27000001009")

        [answer] = replies(stranger, "link 123456")

        assert "didn't work" in answer

    def test_strangers_still_get_nothing_on_a_team_only_number(self, acme, team, shop):
        assert replies(ContactFactory(account=InternalAccountFactory(tenant=acme)), "hi") == []

    def test_members_are_customers_on_a_customers_only_number(self, acme, team, shop):
        # The wall: a link on a customers-only number, left from before, grants nothing.
        _, contact = member_on(ExternalAccountFactory(tenant=acme))

        assert replies(contact, "hi") == ["SHOP MENU"]


class TestLinking:
    def test_a_member_links_on_the_shared_number(self, acme, shared):
        user = UserFactory()
        TenantMembershipFactory(user=user, tenant=acme)
        started = identity.start_link(user, acme, "27000001001")
        sender = ContactFactory(account=shared, wa_id="27000001001")

        identity.handle_unlinked_message(sender, f"link {started.code}")

        assert WhatsAppIdentity.objects.get(user=user).account == shared


@pytest.fixture
def meta_get(mocker):
    return mocker.patch(
        "apps.whatsapp.client.requests.get",
        return_value=meta_response(200, {"display_phone_number": "+27 83 000 0777", "verified_name": "Acme Store"}),
    )


@pytest.fixture(autouse=True)
def meta_subscribe(mocker):
    return mocker.patch("apps.whatsapp.client.requests.post", return_value=meta_response(200, {"success": True}))


def connect(tenant, purpose, phone_number_id="100000000000777"):
    return accounts.connect_account(
        tenant=tenant, purpose=purpose, phone_number_id=phone_number_id, waba_id="200000000000777", access_token="t"
    ).account


class TestConnecting:
    def test_a_shared_number_counts_as_the_teams(self, acme, meta_get):
        InternalAccountFactory(tenant=acme)

        with pytest.raises(AccountError) as raised:
            connect(acme, both())

        assert raised.value.code == "internal_number_exists"

    def test_a_disconnected_number_reconnects_with_any_purpose(self, acme, meta_get):
        number = connect(acme, INTERNAL)
        accounts.disconnect_account(tenant=acme, account_id=number.pk)

        reconnected = connect(acme, both())

        assert reconnected.pk == number.pk
        assert reconnected.purpose == both()

    def test_an_active_number_is_told_to_change_its_role_on_its_row(self, acme, meta_get):
        connect(acme, INTERNAL)

        with pytest.raises(AccountError) as raised:
            connect(acme, EXTERNAL)

        assert raised.value.code == "connected_for_the_other_purpose"
        assert "Change" in str(raised.value)


class TestChangingTheRole:
    def change(self, acme, number, purpose):
        return accounts.change_purpose(tenant=acme, account_id=number.pk, purpose=purpose)

    def test_a_team_number_starts_serving_customers_too(self, acme, team, shop):
        number = InternalAccountFactory(tenant=acme)

        changed = self.change(acme, number, both())

        assert changed.purpose == both()
        # It already served the team, so the team's side needs no setting up again.
        assert team.connected == []

    def test_joining_the_team_sets_the_teams_side_up(self, acme, team, shop, django_capture_on_commit_callbacks):
        number = ExternalAccountFactory(tenant=acme)

        with django_capture_on_commit_callbacks(execute=True):
            self.change(acme, number, both())

        assert team.connected == [number]

    def test_leaving_the_team_unlinks_its_members_and_forgets_their_conversations(self, acme, shared, team, shop):
        user, contact = member_on(shared)
        WhatsAppConversation.objects.create(contact=contact, tenant=acme, state={"next_choice": 4, "choices": {}})

        self.change(acme, shared, EXTERNAL)

        assert not WhatsAppIdentity.objects.filter(user=user).exists()
        assert WhatsAppConversation.objects.get(contact=contact).state == {"next_choice": 4}
        # They're customers there from now on.
        assert replies(contact, "hi") == ["SHOP MENU"]

    def test_a_second_number_serving_the_team_is_refused(self, acme, team, shop):
        InternalAccountFactory(tenant=acme)
        number = ExternalAccountFactory(tenant=acme)

        with pytest.raises(AccountError) as raised:
            self.change(acme, number, both())

        assert raised.value.code == "internal_number_exists"
        number.refresh_from_db()
        assert number.purpose == EXTERNAL

    def test_a_disconnected_number_must_be_connected_again_first(self, acme):
        number = ExternalAccountFactory(tenant=acme, is_active=False)

        with pytest.raises(AccountError) as raised:
            self.change(acme, number, both())

        assert raised.value.code == "not_connected"

    def test_another_organizations_number_is_not_found(self, acme):
        theirs = ExternalAccountFactory()

        with pytest.raises(AccountError) as raised:
            self.change(acme, theirs, both())

        assert raised.value.code == "not_found"


CHANGE = """
mutation($input: ChangeWhatsAppNumberPurposeInput!) {
  changeWhatsAppNumberPurpose(input: $input) { account { id purpose } }
}
"""


class TestTheMutation:
    def act_as(self, graphene_client, acme, role):
        user = UserFactory()
        TenantMembershipFactory(user=user, tenant=acme, role=role)
        graphene_client.force_authenticate(user)
        graphene_client.set_tenant_dependent_context(acme, role)

    def change(self, graphene_client, acme, number):
        variables = {
            "input": {"tenantId": to_global_id("TenantType", acme.id), "accountId": str(number.id), "purpose": both()}
        }
        return graphene_client.mutate(CHANGE, variable_values=variables)

    def test_an_admin_changes_a_numbers_role(self, graphene_client, acme):
        self.act_as(graphene_client, acme, TenantUserRole.ADMIN)
        number = InternalAccountFactory(tenant=acme)

        response = self.change(graphene_client, acme, number)

        assert "errors" not in response
        assert response["data"]["changeWhatsAppNumberPurpose"]["account"] == {
            "id": str(number.id),
            "purpose": both(),
        }

    def test_a_member_cant(self, graphene_client, acme):
        self.act_as(graphene_client, acme, TenantUserRole.MEMBER)
        number = InternalAccountFactory(tenant=acme)

        response = self.change(graphene_client, acme, number)

        assert "permission" in response["errors"][0]["message"].lower()
        number.refresh_from_db()
        assert number.purpose == INTERNAL
