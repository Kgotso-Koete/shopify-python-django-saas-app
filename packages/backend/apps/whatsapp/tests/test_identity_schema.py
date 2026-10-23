"""
Tests for the profile page's WhatsApp GraphQL fields in apps/whatsapp/schema.py (plan Step 1.7c,
user stories 1 and 3, Step 1.17): whatsAppLinks, startWhatsAppLink, updateWhatsAppConversationMode
and disconnectWhatsApp.

- they act only on the logged-in user; there's no argument naming anyone else
- since Step 1.17 a user links once per organization, on its internal communications number, so
  each field names the organization; only the user's own organizations are reachable
- the number comes back masked, with only its last four digits
- someone who isn't logged in is refused

Kind of test: integration (agents.md section 2.5). Why: queries and mutations go through the real
GraphQL schema and test database; nothing is faked.
"""

import pytest
from graphql_relay import to_global_id

from apps.multitenancy.constants import TenantType, TenantUserRole
from apps.multitenancy.tests.factories import TenantFactory, TenantMembershipFactory
from apps.users.tests.factories import UserFactory

from ..models import WhatsAppIdentity
from .factories import ContactFactory, ExternalAccountFactory, InternalAccountFactory

pytestmark = pytest.mark.django_db

NUMBER = "27831234567"

LINKS = """
query {
  whatsAppLinks {
    tenantId organizationName internalNumber linked maskedNumber conversationMode linkedAt
  }
}
"""
START = """
mutation($input: StartWhatsAppLinkInput!) {
  startWhatsAppLink(input: $input) { code link maskedNumber expiresAt }
}
"""
MODE = """
mutation($input: UpdateWhatsAppConversationModeInput!) {
  updateWhatsAppConversationMode(input: $input) { link { linked conversationMode } }
}
"""
DISCONNECT = """
mutation($input: DisconnectWhatsAppInput!) {
  disconnectWhatsApp(input: $input) { link { linked } }
}
"""


@pytest.fixture
def user(graphene_client):
    user = UserFactory()
    graphene_client.force_authenticate(user)
    return user


@pytest.fixture
def acme(user):
    tenant = TenantFactory(type=TenantType.ORGANIZATION, name="Acme")
    TenantMembershipFactory(user=user, tenant=tenant, role=TenantUserRole.MEMBER)
    return tenant


@pytest.fixture
def internal(acme):
    return InternalAccountFactory(tenant=acme, display_phone_number="+27 00 000 0000")


@pytest.fixture
def linked(internal, user):
    contact = ContactFactory(account=internal, wa_id=NUMBER)
    return WhatsAppIdentity.objects.create(user=user, contact=contact, account=internal)


def tenant_id(tenant):
    return to_global_id("TenantType", tenant.id)


def problem(response):
    error = response["errors"][0]
    assert error["message"] == "GraphQlValidationError"
    return error["extensions"]


class TestTheLinks:
    def test_a_linked_user_sees_their_masked_number_and_mode_per_organization(self, graphene_client, acme, linked):
        response = graphene_client.query(LINKS)

        assert "errors" not in response
        [shown] = response["data"]["whatsAppLinks"]
        assert shown["tenantId"] == tenant_id(acme)
        assert shown["organizationName"] == "Acme"
        assert shown["internalNumber"] == "+27 00 000 0000"
        assert shown["linked"] is True
        assert shown["maskedNumber"] == "*******4567"
        # No mode saved: the default applies (user story 3).
        assert shown["conversationMode"] is None
        assert shown["linkedAt"] is not None
        assert NUMBER not in str(response)

    def test_an_organization_the_user_isnt_linked_on_shows_that(self, graphene_client, acme, internal):
        response = graphene_client.query(LINKS)

        [shown] = response["data"]["whatsAppLinks"]
        assert shown["linked"] is False
        assert shown["maskedNumber"] is None

    def test_only_the_users_organizations_with_an_internal_number_are_listed(self, graphene_client, user, acme):
        # Acme has only an external number; Beta isn't the user's; Gamma has one and is theirs.
        ExternalAccountFactory(tenant=acme)
        InternalAccountFactory(tenant=TenantFactory(type=TenantType.ORGANIZATION, name="Beta"))
        gamma = TenantFactory(type=TenantType.ORGANIZATION, name="Gamma")
        TenantMembershipFactory(user=user, tenant=gamma)
        InternalAccountFactory(tenant=gamma)

        response = graphene_client.query(LINKS)

        assert [shown["organizationName"] for shown in response["data"]["whatsAppLinks"]] == ["Gamma"]

    def test_another_users_link_is_never_shown(self, graphene_client, internal, user):
        WhatsAppIdentity.objects.create(
            user=UserFactory(), contact=ContactFactory(account=internal, wa_id=NUMBER), account=internal
        )

        response = graphene_client.query(LINKS)

        assert response["data"]["whatsAppLinks"][0]["linked"] is False

    def test_someone_not_logged_in_is_refused(self, graphene_client):
        response = graphene_client.query(LINKS)

        assert "errors" in response


class TestStartingALink:
    def test_the_code_and_the_link_come_back_with_the_number_masked(self, graphene_client, acme, internal):
        response = graphene_client.mutate(
            START, variable_values={"input": {"tenantId": tenant_id(acme), "phoneNumber": "083 123 4567"}}
        )

        assert "errors" not in response
        started = response["data"]["startWhatsAppLink"]
        assert len(started["code"]) == 6
        assert started["link"] == f"https://wa.me/27000000000?text=link%20{started['code']}"
        assert started["maskedNumber"] == "*******4567"
        assert started["expiresAt"] is not None

    def test_a_number_that_cant_be_one_is_shown_on_the_field(self, graphene_client, acme, internal):
        response = graphene_client.mutate(
            START, variable_values={"input": {"tenantId": tenant_id(acme), "phoneNumber": "call me"}}
        )

        assert problem(response)["phone_number"][0]["code"] == "invalid_phone_number"

    def test_another_organization_is_not_found(self, graphene_client, user):
        beta = InternalAccountFactory().tenant

        response = graphene_client.mutate(
            START, variable_values={"input": {"tenantId": tenant_id(beta), "phoneNumber": NUMBER}}
        )

        assert problem(response)["non_field_errors"][0]["code"] == "not_found"


class TestTheMode:
    def test_a_linked_user_chooses_the_ai_assistant_for_one_organization(self, graphene_client, acme, linked):
        response = graphene_client.mutate(
            MODE, variable_values={"input": {"tenantId": tenant_id(acme), "mode": "AGENTIC"}}
        )

        assert response["data"]["updateWhatsAppConversationMode"]["link"] == {
            "linked": True,
            "conversationMode": "AGENTIC",
        }
        linked.refresh_from_db()
        assert linked.conversation_mode == "AGENTIC"

    def test_a_user_who_isnt_linked_there_cant_choose_a_mode(self, graphene_client, acme, internal):
        response = graphene_client.mutate(
            MODE, variable_values={"input": {"tenantId": tenant_id(acme), "mode": "AGENTIC"}}
        )

        assert problem(response)["non_field_errors"][0]["code"] == "not_linked"


class TestDisconnecting:
    def test_disconnecting_removes_only_the_users_own_link_on_that_number(
        self, graphene_client, acme, internal, linked
    ):
        other = WhatsAppIdentity.objects.create(
            user=UserFactory(), contact=ContactFactory(account=internal, wa_id="27839999999"), account=internal
        )

        response = graphene_client.mutate(DISCONNECT, variable_values={"input": {"tenantId": tenant_id(acme)}})

        assert response["data"]["disconnectWhatsApp"]["link"] == {"linked": False}
        assert not WhatsAppIdentity.objects.filter(pk=linked.pk).exists()
        assert WhatsAppIdentity.objects.filter(pk=other.pk).exists()
