"""
Tests for the number troubleshooting tools' GraphQL operations in apps/whatsapp/schema.py (plan D18,
Step 1.5b, user story 23). The work is done by services/number_tools.py (test_number_tools.py); these
tests cover who may ask and which organization's numbers they reach.

- every operation, the status query included, needs whatsapp.manage (user story 23)
- another organization's number is "not found", the same answer as a missing one
- Meta's errors reach the form with their explanation

Kind of test: integration (agents.md section 2.5). Why: queries and mutations go through the real
GraphQL schema, permissions and test database; Meta's HTTP is mocked.
"""

import pytest
from graphql_relay import to_global_id

from apps.multitenancy.constants import TenantType, TenantUserRole
from apps.multitenancy.tests.factories import TenantFactory, TenantMembershipFactory
from apps.users.tests.factories import UserFactory

from .factories import ExternalAccountFactory
from .fakes import meta_error, meta_response

pytestmark = pytest.mark.django_db

STATUS = """
query($tenantId: ID!, $accountId: ID!) {
  whatsAppNumberStatus(tenantId: $tenantId, accountId: $accountId) {
    status codeVerificationStatus qualityRating nameStatus verifiedName displayPhoneNumber
  }
}
"""

REQUEST_CODE = """
mutation($input: RequestWhatsAppVerificationCodeInput!) { requestWhatsAppVerificationCode(input: $input) { ok } }
"""
VERIFY = """
mutation($input: VerifyWhatsAppNumberInput!) { verifyWhatsAppNumber(input: $input) { ok } }
"""
REGISTER = """
mutation($input: RegisterWhatsAppNumberInput!) { registerWhatsAppNumber(input: $input) { ok } }
"""
SUBSCRIBE = """
mutation($input: SubscribeWhatsAppAppInput!) { subscribeWhatsAppApp(input: $input) { ok } }
"""


@pytest.fixture(autouse=True)
def graph_api_version(settings):
    settings.WHATSAPP_GRAPH_API_VERSION = "v26.0"


@pytest.fixture
def organization():
    return TenantFactory(type=TenantType.ORGANIZATION)


@pytest.fixture
def account(organization):
    return ExternalAccountFactory(tenant=organization)


@pytest.fixture
def meta_post(mocker):
    return mocker.patch("apps.whatsapp.client.requests.post", return_value=meta_response(200, {"success": True}))


def act_as(graphene_client, organization, role):
    user = UserFactory()
    TenantMembershipFactory(user=user, tenant=organization, role=role)
    graphene_client.force_authenticate(user)
    graphene_client.set_tenant_dependent_context(organization, role)
    return user


def ids(organization, account):
    return {"tenantId": to_global_id("TenantType", organization.id), "accountId": str(account.id)}


def problem(response):
    error = response["errors"][0]
    assert error["message"] == "GraphQlValidationError"
    return error["extensions"]


class TestStatus:
    def test_an_admin_sees_meta_s_fields_as_they_are(self, graphene_client, organization, account, mocker):
        act_as(graphene_client, organization, TenantUserRole.ADMIN)
        mocker.patch(
            "apps.whatsapp.client.requests.get",
            return_value=meta_response(
                200,
                {
                    "status": "CONNECTED",
                    "code_verification_status": "VERIFIED",
                    "quality_rating": "GREEN",
                    "name_status": "APPROVED",
                    "verified_name": "Acme Store",
                    "display_phone_number": "+27 83 000 0777",
                },
            ),
        )

        response = graphene_client.query(STATUS, variable_values=ids(organization, account))

        assert "errors" not in response
        assert response["data"]["whatsAppNumberStatus"] == {
            "status": "CONNECTED",
            "codeVerificationStatus": "VERIFIED",
            "qualityRating": "GREEN",
            "nameStatus": "APPROVED",
            "verifiedName": "Acme Store",
            "displayPhoneNumber": "+27 83 000 0777",
        }

    def test_a_member_cant_ask(self, graphene_client, organization, account, mocker):
        # user story 23: the tools, the status included, need whatsapp.manage.
        get = mocker.patch("apps.whatsapp.client.requests.get")
        act_as(graphene_client, organization, TenantUserRole.MEMBER)

        response = graphene_client.query(STATUS, variable_values=ids(organization, account))

        assert "permission" in response["errors"][0]["message"].lower()
        get.assert_not_called()


class TestRepairs:
    @pytest.mark.parametrize(
        "mutation, extra",
        [
            (REQUEST_CODE, {"method": "SMS"}),
            (VERIFY, {"code": "123456"}),
            (REGISTER, {"pin": "654321"}),
            (SUBSCRIBE, {}),
        ],
        ids=["request-code", "verify", "register", "subscribe"],
    )
    def test_an_admin_runs_each_repair(self, graphene_client, organization, account, meta_post, mutation, extra):
        act_as(graphene_client, organization, TenantUserRole.ADMIN)

        response = graphene_client.mutate(mutation, variable_values={"input": {**ids(organization, account), **extra}})

        assert "errors" not in response
        assert list(response["data"].values())[0] == {"ok": True}
        meta_post.assert_called_once()

    @pytest.mark.parametrize(
        "mutation, extra",
        [
            (REQUEST_CODE, {"method": "SMS"}),
            (VERIFY, {"code": "123456"}),
            (REGISTER, {"pin": "654321"}),
            (SUBSCRIBE, {}),
        ],
        ids=["request-code", "verify", "register", "subscribe"],
    )
    def test_a_member_cant_run_any_repair(self, graphene_client, organization, account, meta_post, mutation, extra):
        act_as(graphene_client, organization, TenantUserRole.MEMBER)

        response = graphene_client.mutate(mutation, variable_values={"input": {**ids(organization, account), **extra}})

        assert "permission" in response["errors"][0]["message"].lower()
        meta_post.assert_not_called()

    def test_another_organizations_number_is_not_found(self, graphene_client, organization, meta_post):
        act_as(graphene_client, organization, TenantUserRole.ADMIN)
        theirs = ExternalAccountFactory()

        response = graphene_client.mutate(SUBSCRIBE, variable_values={"input": ids(organization, theirs)})

        assert problem(response)["non_field_errors"][0] == {
            "message": "WhatsApp number not found.",
            "code": "not_found",
        }
        meta_post.assert_not_called()

    def test_meta_s_error_reaches_the_form_with_its_explanation(
        self, graphene_client, organization, account, meta_post
    ):
        act_as(graphene_client, organization, TenantUserRole.ADMIN)
        meta_post.return_value = meta_error(133016)

        response = graphene_client.mutate(
            REGISTER, variable_values={"input": {**ids(organization, account), "pin": "654321"}}
        )

        error = problem(response)["non_field_errors"][0]
        assert error["code"] == "too_many_attempts"
        assert "72 hours" in error["message"]
        assert "654321" not in str(response)

    def test_a_bad_pin_is_shown_on_the_pin_field(self, graphene_client, organization, account, meta_post):
        act_as(graphene_client, organization, TenantUserRole.ADMIN)

        response = graphene_client.mutate(
            REGISTER, variable_values={"input": {**ids(organization, account), "pin": "12"}}
        )

        assert problem(response)["pin"][0]["code"] == "invalid_pin"
        meta_post.assert_not_called()
