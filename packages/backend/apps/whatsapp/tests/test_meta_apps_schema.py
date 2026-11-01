"""
Tests for the WhatsApp page's GraphQL API for an organization's own Meta apps (plan Step 2.9): the
"Your Meta apps" card, the connect form's choice of app, and each number's app. The rules are in
services/meta_apps.py (test_meta_apps.py); these tests cover who may ask, which organization's apps
they reach, and what reaches the browser.

- whatsAppMetaApps and every Meta app mutation need whatsapp.manage; the list gives each app's
  webhook address and verify token, to paste into Meta, and never its App secret
- each number says which app it's on: none for this service's app
- another organization's app is "not found", the same answer as a missing one

Kind of test: integration (agents.md section 2.5). Why: queries and mutations go through the real
GraphQL schema, permissions and test database; Meta's HTTP, called when a number connects, is mocked.
"""

import pytest
from graphql_relay import to_global_id

from apps.multitenancy.constants import TenantType, TenantUserRole
from apps.multitenancy.tests.factories import TenantFactory, TenantMembershipFactory
from apps.users.tests.factories import UserFactory

from ..models import MetaApp
from .factories import ExternalAccountFactory, MetaAppFactory
from .fakes import meta_response

pytestmark = pytest.mark.django_db

APP_ID = "1234567890123456"
APP_SECRET = "0123456789abcdef0123456789abcdef"

META_APPS = """
query($tenantId: ID!) {
  whatsAppMetaApps(tenantId: $tenantId) { id appId webhookUrl verifyToken createdAt }
}
"""

REGISTER = """
mutation($input: RegisterWhatsAppMetaAppInput!) {
  registerWhatsAppMetaApp(input: $input) { metaApp { id appId webhookUrl verifyToken } }
}
"""

UPDATE_SECRET = """
mutation($input: UpdateWhatsAppMetaAppSecretInput!) {
  updateWhatsAppMetaAppSecret(input: $input) { metaApp { id } }
}
"""

REGENERATE = """
mutation($input: RegenerateWhatsAppMetaAppVerifyTokenInput!) {
  regenerateWhatsAppMetaAppVerifyToken(input: $input) { metaApp { id verifyToken } }
}
"""

REMOVE = """
mutation($input: RemoveWhatsAppMetaAppInput!) {
  removeWhatsAppMetaApp(input: $input) { ok }
}
"""

SET_NUMBER_APP = """
mutation($input: SetWhatsAppNumberMetaAppInput!) {
  setWhatsAppNumberMetaApp(input: $input) { account { id metaAppId } }
}
"""

CONNECT = """
mutation($input: ConnectWhatsAppAccountInput!) {
  connectWhatsAppAccount(input: $input) { account { id metaAppId } }
}
"""


@pytest.fixture(autouse=True)
def whatsapp_settings(settings, mocker):
    settings.WHATSAPP_GRAPH_API_VERSION = "v26.0"
    settings.API_URL = "https://api.example.com"
    mocker.patch(
        "apps.whatsapp.client.requests.get",
        return_value=meta_response(200, {"display_phone_number": "+27 83 000 0777", "verified_name": "Acme"}),
    )
    mocker.patch("apps.whatsapp.client.requests.post", return_value=meta_response(200, {"success": True}))


@pytest.fixture
def organization():
    return TenantFactory(type=TenantType.ORGANIZATION)


def act_as(graphene_client, organization, role):
    """Log in as a new user with `role` in `organization`, working in that organization."""
    user = UserFactory()
    TenantMembershipFactory(user=user, tenant=organization, role=role)
    graphene_client.force_authenticate(user)
    graphene_client.set_tenant_dependent_context(organization, role)
    return user


def tenant_id(organization):
    return to_global_id("TenantType", organization.id)


def problem(response):
    """The user-facing error, keyed by field or non_field_errors (common/graphql/views.py)."""
    error = response["errors"][0]
    assert error["message"] == "GraphQlValidationError"
    return error["extensions"]


def refused_for_permission(response):
    return "permission" in response["errors"][0]["message"].lower()


class TestListing:
    def test_an_admin_sees_each_apps_address_and_token_never_its_secret(self, graphene_client, organization):
        act_as(graphene_client, organization, TenantUserRole.ADMIN)
        app = MetaAppFactory(tenant=organization, app_id=APP_ID, app_secret=APP_SECRET)
        MetaAppFactory()

        response = graphene_client.query(META_APPS, variable_values={"tenantId": tenant_id(organization)})

        assert "errors" not in response
        [listed] = response["data"]["whatsAppMetaApps"]
        assert listed["id"] == str(app.id)
        assert listed["appId"] == APP_ID
        assert listed["webhookUrl"] == f"https://api.example.com/api/whatsapp/webhook/{app.public_id}/"
        assert listed["verifyToken"] == app.verify_token
        assert APP_SECRET not in str(response)
        assert app.app_secret_encrypted not in str(response)

    def test_a_member_cant_list_them(self, graphene_client, organization):
        act_as(graphene_client, organization, TenantUserRole.MEMBER)
        MetaAppFactory(tenant=organization)

        response = graphene_client.query(META_APPS, variable_values={"tenantId": tenant_id(organization)})

        assert refused_for_permission(response)


class TestRegistering:
    def test_an_admin_registers_an_app_and_gets_its_address_and_token(self, graphene_client, organization):
        act_as(graphene_client, organization, TenantUserRole.ADMIN)
        variables = {"input": {"tenantId": tenant_id(organization), "appId": APP_ID, "appSecret": APP_SECRET}}

        response = graphene_client.mutate(REGISTER, variable_values=variables)

        assert "errors" not in response
        app = MetaApp.objects.get(tenant=organization)
        assert response["data"]["registerWhatsAppMetaApp"]["metaApp"] == {
            "id": str(app.id),
            "appId": APP_ID,
            "webhookUrl": f"https://api.example.com/api/whatsapp/webhook/{app.public_id}/",
            "verifyToken": app.verify_token,
        }

    def test_an_app_another_organization_has_is_refused_under_its_field(self, graphene_client, organization):
        act_as(graphene_client, organization, TenantUserRole.ADMIN)
        MetaAppFactory(app_id=APP_ID)
        variables = {"input": {"tenantId": tenant_id(organization), "appId": APP_ID, "appSecret": APP_SECRET}}

        response = graphene_client.mutate(REGISTER, variable_values=variables)

        [error] = problem(response)["app_id"]
        assert error == {
            "message": "This Meta app is already connected to another organization.",
            "code": "already_connected",
        }

    def test_a_member_cant_register_one(self, graphene_client, organization):
        act_as(graphene_client, organization, TenantUserRole.MEMBER)
        variables = {"input": {"tenantId": tenant_id(organization), "appId": APP_ID, "appSecret": APP_SECRET}}

        assert refused_for_permission(graphene_client.mutate(REGISTER, variable_values=variables))
        assert not MetaApp.objects.exists()


class TestChanging:
    def app_input(self, organization, app, **more):
        return {"input": {"tenantId": tenant_id(organization), "metaAppId": str(app.id), **more}}

    def test_an_admin_updates_the_secret(self, graphene_client, organization):
        act_as(graphene_client, organization, TenantUserRole.ADMIN)
        app = MetaAppFactory(tenant=organization)

        response = graphene_client.mutate(
            UPDATE_SECRET, variable_values=self.app_input(organization, app, appSecret="a-new-secret")
        )

        assert "errors" not in response
        app.refresh_from_db()
        assert app.app_secret == "a-new-secret"

    def test_an_admin_regenerates_the_token(self, graphene_client, organization):
        act_as(graphene_client, organization, TenantUserRole.ADMIN)
        app = MetaAppFactory(tenant=organization)
        old = app.verify_token

        response = graphene_client.mutate(REGENERATE, variable_values=self.app_input(organization, app))

        app.refresh_from_db()
        assert response["data"]["regenerateWhatsAppMetaAppVerifyToken"]["metaApp"]["verifyToken"] == app.verify_token
        assert app.verify_token != old

    def test_an_admin_removes_an_unused_app(self, graphene_client, organization):
        act_as(graphene_client, organization, TenantUserRole.ADMIN)
        app = MetaAppFactory(tenant=organization)

        response = graphene_client.mutate(REMOVE, variable_values=self.app_input(organization, app))

        assert response["data"]["removeWhatsAppMetaApp"] == {"ok": True}
        assert not MetaApp.objects.exists()

    def test_removing_one_a_number_uses_says_which(self, graphene_client, organization):
        act_as(graphene_client, organization, TenantUserRole.ADMIN)
        app = MetaAppFactory(tenant=organization)
        ExternalAccountFactory(tenant=organization, meta_app=app, display_phone_number="+27 83 000 0001")

        response = graphene_client.mutate(REMOVE, variable_values=self.app_input(organization, app))

        [error] = problem(response)["non_field_errors"]
        assert error == {"message": "Disconnect its numbers first: +27 83 000 0001.", "code": "app_in_use"}

    def test_another_organizations_app_is_not_found(self, graphene_client, organization):
        act_as(graphene_client, organization, TenantUserRole.ADMIN)

        response = graphene_client.mutate(REMOVE, variable_values=self.app_input(organization, MetaAppFactory()))

        assert problem(response)["non_field_errors"][0]["code"] == "app_not_found"
        assert MetaApp.objects.exists()

    @pytest.mark.parametrize(
        ("mutation", "more"),
        [(UPDATE_SECRET, {"appSecret": "x"}), (REGENERATE, {}), (REMOVE, {})],
        ids=["update secret", "regenerate", "remove"],
    )
    def test_a_member_cant_change_one(self, graphene_client, organization, mutation, more):
        act_as(graphene_client, organization, TenantUserRole.MEMBER)
        app = MetaAppFactory(tenant=organization)

        assert refused_for_permission(
            graphene_client.mutate(mutation, variable_values=self.app_input(organization, app, **more))
        )


class TestANumbersApp:
    def test_each_number_says_which_app_its_on(self, graphene_client, organization):
        act_as(graphene_client, organization, TenantUserRole.MEMBER)
        app = MetaAppFactory(tenant=organization)
        on_it = ExternalAccountFactory(tenant=organization, meta_app=app)
        on_ours = ExternalAccountFactory(tenant=organization)

        response = graphene_client.query(
            "query($tenantId: ID!) { whatsAppAccounts(tenantId: $tenantId) { id metaAppId } }",
            variable_values={"tenantId": tenant_id(organization)},
        )

        assert response["data"]["whatsAppAccounts"] == [
            {"id": str(on_it.id), "metaAppId": str(app.id)},
            {"id": str(on_ours.id), "metaAppId": None},
        ]

    def test_an_admin_connects_a_number_on_the_organizations_app(self, graphene_client, organization):
        act_as(graphene_client, organization, TenantUserRole.ADMIN)
        app = MetaAppFactory(tenant=organization)
        variables = {
            "input": {
                "tenantId": tenant_id(organization),
                "purpose": "EXTERNAL_COMMUNICATIONS",
                "phoneNumberId": "100000000000777",
                "wabaId": "200000000000777",
                "accessToken": "EAAGacme-access-token",
                "metaAppId": str(app.id),
            }
        }

        response = graphene_client.mutate(CONNECT, variable_values=variables)

        assert "errors" not in response
        assert response["data"]["connectWhatsAppAccount"]["account"]["metaAppId"] == str(app.id)

    def test_an_admin_changes_a_numbers_app_and_back(self, graphene_client, organization):
        act_as(graphene_client, organization, TenantUserRole.ADMIN)
        app = MetaAppFactory(tenant=organization)
        number = ExternalAccountFactory(tenant=organization)
        base = {"tenantId": tenant_id(organization), "accountId": str(number.id)}

        moved = graphene_client.mutate(SET_NUMBER_APP, variable_values={"input": {**base, "metaAppId": str(app.id)}})
        back = graphene_client.mutate(SET_NUMBER_APP, variable_values={"input": {**base, "metaAppId": None}})

        assert moved["data"]["setWhatsAppNumberMetaApp"]["account"] == {"id": str(number.id), "metaAppId": str(app.id)}
        assert back["data"]["setWhatsAppNumberMetaApp"]["account"] == {"id": str(number.id), "metaAppId": None}

    def test_another_organizations_app_is_not_found_under_its_field(self, graphene_client, organization):
        act_as(graphene_client, organization, TenantUserRole.ADMIN)
        number = ExternalAccountFactory(tenant=organization)
        variables = {
            "input": {
                "tenantId": tenant_id(organization),
                "accountId": str(number.id),
                "metaAppId": str(MetaAppFactory().id),
            }
        }

        response = graphene_client.mutate(SET_NUMBER_APP, variable_values=variables)

        assert problem(response)["meta_app_id"][0]["code"] == "app_not_found"

    def test_a_member_cant_change_a_numbers_app(self, graphene_client, organization):
        act_as(graphene_client, organization, TenantUserRole.MEMBER)
        number = ExternalAccountFactory(tenant=organization)
        app = MetaAppFactory(tenant=organization)
        variables = {
            "input": {"tenantId": tenant_id(organization), "accountId": str(number.id), "metaAppId": str(app.id)}
        }

        assert refused_for_permission(graphene_client.mutate(SET_NUMBER_APP, variable_values=variables))
        number.refresh_from_db()
        assert number.meta_app is None
