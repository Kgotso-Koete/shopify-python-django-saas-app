"""
Tests for the WhatsApp tab's GraphQL API in apps/whatsapp/schema.py (plan Step 1.5f, user story 11):
listing an organization's numbers with their status, connecting one with the form, sending a test
message and disconnecting. The work is done by services/accounts.py (test_accounts.py); these tests
cover who may ask, which organization's numbers they reach, and what reaches the browser.

- whatsAppAccounts needs whatsapp.view; the three mutations need whatsapp.manage (plan D16).
- Another organization's number is "not found", the same answer as a missing one.
- No secret ever reaches the browser.
- Since Step 1.17, each number says what it's for, so the tab's two forms each list their own.
- Since Step 1.18, connecting takes no App secret and returns no webhook details: every number is
  on our one Meta app, whose webhook the operator sets once.

Kind of test: integration (agents.md section 2.5). Why: queries and mutations go through the real
GraphQL schema, permissions and test database; Meta's HTTP is mocked.
"""

import pytest
from graphql_relay import to_global_id

from apps.multitenancy.constants import TenantType, TenantUserRole
from apps.multitenancy.models import OrganizationRolePermission
from apps.multitenancy.tests.factories import TenantFactory, TenantMembershipFactory
from apps.users.tests.factories import UserFactory

from ..models import WhatsAppAccount
from .factories import ContactFactory, ExternalAccountFactory, InternalAccountFactory, MessageFactory
from .fakes import meta_error, meta_response

pytestmark = pytest.mark.django_db

ACCESS_TOKEN = "EAAGacme-access-token"

ACCOUNTS = """
query($tenantId: ID!) {
  whatsAppAccounts(tenantId: $tenantId) {
    id
    purpose
    phoneNumberId
    wabaId
    displayPhoneNumber
    verifiedName
    connectionMethod
    isActive
    credentialsVerifiedAt
    subscribedAt
    lastMessageReceivedAt
  }
}
"""

CONNECT = """
mutation($input: ConnectWhatsAppAccountInput!) {
  connectWhatsAppAccount(input: $input) {
    account { id purpose phoneNumberId displayPhoneNumber verifiedName isActive subscribedAt }
  }
}
"""

SEND_TEST_MESSAGE = """
mutation($input: SendWhatsAppTestMessageInput!) {
  sendWhatsAppTestMessage(input: $input) { messageId }
}
"""

DISCONNECT = """
mutation($input: DisconnectWhatsAppAccountInput!) {
  disconnectWhatsAppAccount(input: $input) { account { id isActive } }
}
"""


@pytest.fixture(autouse=True)
def whatsapp_settings(settings):
    settings.WHATSAPP_GRAPH_API_VERSION = "v26.0"
    settings.WHATSAPP_SEND_BACKEND = "LOG"
    settings.API_URL = "https://api.example.com"


@pytest.fixture
def organization():
    return TenantFactory(type=TenantType.ORGANIZATION)


@pytest.fixture
def meta_get(mocker):
    """Meta knows the number: its display number and verified business name."""
    return mocker.patch(
        "apps.whatsapp.client.requests.get",
        return_value=meta_response(200, {"display_phone_number": "+27 83 000 0777", "verified_name": "Acme Store"}),
    )


@pytest.fixture(autouse=True)
def meta_subscribe(mocker):
    """Meta's answer to subscribing our app to the number's WhatsApp Business account: done."""
    return mocker.patch("apps.whatsapp.client.requests.post", return_value=meta_response(200, {"success": True}))


def act_as(graphene_client, organization, role):
    """Log in as a new user with `role` in `organization`, working in that organization."""
    user = UserFactory()
    TenantMembershipFactory(user=user, tenant=organization, role=role)
    graphene_client.force_authenticate(user)
    graphene_client.set_tenant_dependent_context(organization, role)
    return user


def tenant_id(organization):
    return to_global_id("TenantType", organization.id)


def connect_input(organization, **overrides):
    return {
        "tenantId": tenant_id(organization),
        "purpose": "EXTERNAL_COMMUNICATIONS",
        "phoneNumberId": "100000000000777",
        "wabaId": "200000000000777",
        "accessToken": ACCESS_TOKEN,
        **overrides,
    }


def problem(response):
    """
    The user-facing error, in the repo's convention (common/graphql/views.py): the message is
    "GraphQlValidationError" and the details are in extensions, keyed by field or non_field_errors.
    """
    error = response["errors"][0]
    assert error["message"] == "GraphQlValidationError"
    return error["extensions"]


class TestListingNumbers:
    def test_a_member_sees_the_organizations_numbers_and_their_status(self, graphene_client, organization):
        act_as(graphene_client, organization, TenantUserRole.MEMBER)
        account = ExternalAccountFactory(
            tenant=organization, phone_number_id="100000000000777", verified_name="Acme Store"
        )
        MessageFactory(contact=ContactFactory(account=account))

        response = graphene_client.query(ACCOUNTS, variable_values={"tenantId": tenant_id(organization)})

        assert "errors" not in response
        [listed] = response["data"]["whatsAppAccounts"]
        assert listed["id"] == str(account.id)
        assert listed["purpose"] == "EXTERNAL_COMMUNICATIONS"
        assert listed["phoneNumberId"] == "100000000000777"
        assert listed["verifiedName"] == "Acme Store"
        assert listed["connectionMethod"] == "MANUAL"
        assert listed["isActive"] is True
        # The form's three proofs (user story 11).
        assert listed["credentialsVerifiedAt"] is None
        assert listed["subscribedAt"] is None
        assert listed["lastMessageReceivedAt"] is not None

    def test_both_kinds_are_listed_each_with_its_purpose(self, graphene_client, organization):
        act_as(graphene_client, organization, TenantUserRole.MEMBER)
        internal = InternalAccountFactory(tenant=organization)
        external = ExternalAccountFactory(tenant=organization)

        response = graphene_client.query(ACCOUNTS, variable_values={"tenantId": tenant_id(organization)})

        assert [(listed["id"], listed["purpose"]) for listed in response["data"]["whatsAppAccounts"]] == [
            (str(internal.id), "INTERNAL_COMMUNICATIONS"),
            (str(external.id), "EXTERNAL_COMMUNICATIONS"),
        ]

    def test_another_organizations_numbers_are_not_listed(self, graphene_client, organization):
        act_as(graphene_client, organization, TenantUserRole.MEMBER)
        ExternalAccountFactory()

        response = graphene_client.query(ACCOUNTS, variable_values={"tenantId": tenant_id(organization)})

        assert response["data"]["whatsAppAccounts"] == []

    def test_no_secret_ever_reaches_the_browser(self, graphene_client, organization):
        act_as(graphene_client, organization, TenantUserRole.OWNER)
        ExternalAccountFactory(tenant=organization, access_token=ACCESS_TOKEN)

        response = graphene_client.query(ACCOUNTS, variable_values={"tenantId": tenant_id(organization)})

        assert ACCESS_TOKEN not in str(response)

    def test_a_member_without_whatsapp_view_is_refused(self, graphene_client, organization):
        act_as(graphene_client, organization, TenantUserRole.MEMBER)
        OrganizationRolePermission.objects.filter(
            role__tenant=organization,
            role__system_role_type=TenantUserRole.MEMBER,
            permission__code="whatsapp.view",
        ).delete()

        response = graphene_client.query(ACCOUNTS, variable_values={"tenantId": tenant_id(organization)})

        assert "permission" in response["errors"][0]["message"].lower()


class TestConnecting:
    def test_an_admin_connects_a_number_and_our_app_is_subscribed_to_it(self, graphene_client, organization, meta_get):
        act_as(graphene_client, organization, TenantUserRole.ADMIN)

        response = graphene_client.mutate(CONNECT, variable_values={"input": connect_input(organization)})

        assert "errors" not in response
        result = response["data"]["connectWhatsAppAccount"]
        assert result["account"]["phoneNumberId"] == "100000000000777"
        assert result["account"]["displayPhoneNumber"] == "+27 83 000 0777"
        assert result["account"]["verifiedName"] == "Acme Store"
        assert result["account"]["isActive"] is True
        assert result["account"]["subscribedAt"] is not None
        assert ACCESS_TOKEN not in str(response)

    def test_an_app_secret_is_no_longer_an_input(self, graphene_client, organization, meta_get):
        act_as(graphene_client, organization, TenantUserRole.ADMIN)

        response = graphene_client.mutate(
            CONNECT, variable_values={"input": connect_input(organization, appSecret="theirs")}
        )

        assert "appSecret" in response["errors"][0]["message"]
        assert WhatsAppAccount.objects.count() == 0

    def test_an_admin_connects_the_internal_number(self, graphene_client, organization, meta_get):
        act_as(graphene_client, organization, TenantUserRole.ADMIN)

        response = graphene_client.mutate(
            CONNECT, variable_values={"input": connect_input(organization, purpose="INTERNAL_COMMUNICATIONS")}
        )

        assert response["data"]["connectWhatsAppAccount"]["account"]["purpose"] == "INTERNAL_COMMUNICATIONS"
        assert WhatsAppAccount.objects.internal_for(organization).phone_number_id == "100000000000777"

    def test_a_second_internal_number_is_refused_with_the_reason(self, graphene_client, organization, meta_get):
        act_as(graphene_client, organization, TenantUserRole.ADMIN)
        InternalAccountFactory(tenant=organization)

        response = graphene_client.mutate(
            CONNECT, variable_values={"input": connect_input(organization, purpose="INTERNAL_COMMUNICATIONS")}
        )

        assert problem(response)["non_field_errors"][0]["code"] == "internal_number_exists"

    def test_a_member_cant_connect_a_number(self, graphene_client, organization, meta_get):
        # Members have whatsapp.view only (plan D16).
        act_as(graphene_client, organization, TenantUserRole.MEMBER)

        response = graphene_client.mutate(CONNECT, variable_values={"input": connect_input(organization)})

        assert "permission" in response["errors"][0]["message"].lower()
        meta_get.assert_not_called()
        assert WhatsAppAccount.objects.count() == 0

    def test_someone_outside_the_organization_cant_connect_a_number(self, graphene_client, organization, meta_get):
        act_as(graphene_client, TenantFactory(type=TenantType.ORGANIZATION), TenantUserRole.OWNER)
        # Working in their own organization, but naming another one in the input.
        graphene_client.set_tenant_dependent_context(organization, None)

        response = graphene_client.mutate(CONNECT, variable_values={"input": connect_input(organization)})

        assert "errors" in response
        meta_get.assert_not_called()
        assert WhatsAppAccount.objects.count() == 0

    def test_meta_rejecting_the_token_is_shown_on_the_token_field(self, graphene_client, organization, meta_get):
        act_as(graphene_client, organization, TenantUserRole.ADMIN)
        meta_get.return_value = meta_error(190, status=401)

        response = graphene_client.mutate(CONNECT, variable_values={"input": connect_input(organization)})

        assert problem(response)["access_token"][0]["code"] == "token_rejected"
        assert WhatsAppAccount.objects.count() == 0

    def test_a_number_connected_elsewhere_is_refused(self, graphene_client, organization, meta_get):
        act_as(graphene_client, organization, TenantUserRole.ADMIN)
        ExternalAccountFactory(phone_number_id="100000000000777")

        response = graphene_client.mutate(CONNECT, variable_values={"input": connect_input(organization)})

        assert problem(response)["phone_number_id"][0]["code"] == "already_connected"

    def test_errors_survive_the_production_error_sanitizer(self, graphene_client, organization, meta_get, settings):
        # With DEBUG off, SanitizeErrorsMiddleware hides any error it doesn't know is safe; the form
        # must still get Meta's reason (as test_schema_products.py checks for Shopify).
        from common.graphql.security import SanitizeErrorsMiddleware

        settings.DEBUG = False
        graphene_client.execute_options["middleware"] = [SanitizeErrorsMiddleware()]
        act_as(graphene_client, organization, TenantUserRole.ADMIN)
        meta_get.return_value = meta_error(190, status=401)

        response = graphene_client.mutate(CONNECT, variable_values={"input": connect_input(organization)})

        assert problem(response)["access_token"][0]["code"] == "token_rejected"


class TestTestMessage:
    def test_an_admin_sends_the_test_message(self, graphene_client, organization):
        act_as(graphene_client, organization, TenantUserRole.ADMIN)
        account = ExternalAccountFactory(tenant=organization)

        response = graphene_client.mutate(
            SEND_TEST_MESSAGE,
            variable_values={
                "input": {"tenantId": tenant_id(organization), "accountId": str(account.id), "to": "083 123 4567"}
            },
        )

        assert "errors" not in response
        # The LOG backend (the default) gives a fake id; with META it's Meta's.
        assert response["data"]["sendWhatsAppTestMessage"]["messageId"].startswith("log.")

    def test_a_number_that_cant_be_one_is_shown_on_the_to_field(self, graphene_client, organization):
        act_as(graphene_client, organization, TenantUserRole.ADMIN)
        account = ExternalAccountFactory(tenant=organization)

        response = graphene_client.mutate(
            SEND_TEST_MESSAGE,
            variable_values={
                "input": {"tenantId": tenant_id(organization), "accountId": str(account.id), "to": "call me"}
            },
        )

        assert problem(response)["to"][0]["code"] == "invalid_phone_number"

    def test_another_organizations_number_is_not_found(self, graphene_client, organization):
        act_as(graphene_client, organization, TenantUserRole.ADMIN)
        theirs = ExternalAccountFactory()

        response = graphene_client.mutate(
            SEND_TEST_MESSAGE,
            variable_values={
                "input": {"tenantId": tenant_id(organization), "accountId": str(theirs.id), "to": "083 123 4567"}
            },
        )

        assert problem(response)["non_field_errors"][0] == {
            "message": "WhatsApp number not found.",
            "code": "not_found",
        }


class TestDisconnecting:
    @pytest.mark.parametrize("factory", [InternalAccountFactory, ExternalAccountFactory])
    def test_an_admin_disconnects_a_number(self, graphene_client, organization, factory):
        act_as(graphene_client, organization, TenantUserRole.ADMIN)
        account = factory(tenant=organization)

        response = graphene_client.mutate(
            DISCONNECT, variable_values={"input": {"tenantId": tenant_id(organization), "accountId": str(account.id)}}
        )

        assert response["data"]["disconnectWhatsAppAccount"]["account"] == {"id": str(account.id), "isActive": False}
        assert WhatsAppAccount.objects.get(pk=account.pk).is_active is False

    def test_a_member_cant_disconnect_a_number(self, graphene_client, organization):
        act_as(graphene_client, organization, TenantUserRole.MEMBER)
        account = ExternalAccountFactory(tenant=organization)

        response = graphene_client.mutate(
            DISCONNECT, variable_values={"input": {"tenantId": tenant_id(organization), "accountId": str(account.id)}}
        )

        assert "permission" in response["errors"][0]["message"].lower()
        assert WhatsAppAccount.objects.get(pk=account.pk).is_active is True
