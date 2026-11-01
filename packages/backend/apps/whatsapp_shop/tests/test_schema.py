"""
Tests for apps/whatsapp_shop/schema.py, the WhatsApp page's API for which store each external
number sells from (plan Step 2.1b, decision 5, user story 25). The rules are in services.py
(test_store_channels.py); these tests cover who may ask, which organization's numbers and stores
they reach, and what reaches the browser.

- whatsAppStorefronts lists each external number with its store, or none; it needs whatsapp.view
- whatsAppEligibleStores and chooseWhatsAppStore are for the picker; they need whatsapp.manage
- another organization's numbers and stores never appear, and read as "not found"
- a store disconnected from the organization is no number's store any more (Step 2.8, finding 22)

Kind of test: integration (agents.md section 2.5). Why: queries and mutations go through the real
GraphQL schema, permissions and test database; nothing is faked.
"""

import pytest
from graphql_relay import to_global_id

from apps.multitenancy.constants import TenantType, TenantUserRole
from apps.multitenancy.models import OrganizationRolePermission
from apps.multitenancy.tests.factories import TenantFactory, TenantMembershipFactory
from apps.shopify.models import ShopifyShop
from apps.users.tests.factories import UserFactory
from apps.whatsapp.tests.factories import ExternalAccountFactory, InternalAccountFactory

from .. import services

pytestmark = pytest.mark.django_db

STOREFRONT_SCOPES = "read_products,unauthenticated_read_product_listings,unauthenticated_write_checkouts"

STOREFRONTS = """
query($tenantId: ID!) {
  whatsAppStorefronts(tenantId: $tenantId) { accountId shopDomain }
}
"""

ELIGIBLE_STORES = """
query($tenantId: ID!) {
  whatsAppEligibleStores(tenantId: $tenantId)
}
"""

CHOOSE = """
mutation($input: ChooseWhatsAppStoreInput!) {
  chooseWhatsAppStore(input: $input) { storefront { accountId shopDomain } }
}
"""

STOREFRONT_MODES = """
query($tenantId: ID!) {
  whatsAppStorefronts(tenantId: $tenantId) { accountId conversationMode }
}
"""

SET_MODE = """
mutation($input: SetWhatsAppStorefrontModeInput!) {
  setWhatsAppStorefrontMode(input: $input) { storefront { accountId shopDomain conversationMode } }
}
"""


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


def store(tenant, domain, scopes=STOREFRONT_SCOPES):
    return ShopifyShop.objects.create(shop_domain=domain, tenant=tenant, scopes=scopes)


def choose_input(organization, account, domain):
    return {"tenantId": tenant_id(organization), "accountId": str(account.id), "shopDomain": domain}


def problem(response):
    """The user-facing error, keyed by field or non_field_errors (common/graphql/views.py)."""
    error = response["errors"][0]
    assert error["message"] == "GraphQlValidationError"
    return error["extensions"]


class TestListingStorefronts:
    def test_a_member_sees_each_external_number_with_its_store(self, graphene_client, organization):
        act_as(graphene_client, organization, TenantUserRole.MEMBER)
        selling = ExternalAccountFactory(tenant=organization)
        waiting = ExternalAccountFactory(tenant=organization)
        InternalAccountFactory(tenant=organization)
        store(organization, "acme.myshopify.com")
        services.choose_store(tenant=organization, account_id=str(selling.pk), shop_domain="acme.myshopify.com")

        response = graphene_client.query(STOREFRONTS, variable_values={"tenantId": tenant_id(organization)})

        assert "errors" not in response
        # External numbers only, the internal one never sells; no store chosen is null.
        assert response["data"]["whatsAppStorefronts"] == [
            {"accountId": str(selling.id), "shopDomain": "acme.myshopify.com"},
            {"accountId": str(waiting.id), "shopDomain": None},
        ]

    def test_another_organizations_numbers_are_not_listed(self, graphene_client, organization):
        act_as(graphene_client, organization, TenantUserRole.MEMBER)
        ExternalAccountFactory()

        response = graphene_client.query(STOREFRONTS, variable_values={"tenantId": tenant_id(organization)})

        assert response["data"]["whatsAppStorefronts"] == []

    def test_a_store_disconnected_from_the_organization_is_no_numbers_store(self, graphene_client, organization):
        # Step 2.8, finding 22: the number shows no store, and no mode, until one is chosen again.
        act_as(graphene_client, organization, TenantUserRole.MEMBER)
        number = ExternalAccountFactory(tenant=organization)
        shop = store(organization, "acme.myshopify.com")
        services.choose_store(tenant=organization, account_id=str(number.pk), shop_domain="acme.myshopify.com")
        shop.tenant = TenantFactory(type=TenantType.ORGANIZATION)
        shop.save(update_fields=["tenant"])

        response = graphene_client.query(
            "query($tenantId: ID!) { whatsAppStorefronts(tenantId: $tenantId) { shopDomain conversationMode } }",
            variable_values={"tenantId": tenant_id(organization)},
        )

        assert response["data"]["whatsAppStorefronts"] == [{"shopDomain": None, "conversationMode": None}]

    def test_a_member_without_whatsapp_view_is_refused(self, graphene_client, organization):
        act_as(graphene_client, organization, TenantUserRole.MEMBER)
        OrganizationRolePermission.objects.filter(
            role__tenant=organization,
            role__system_role_type=TenantUserRole.MEMBER,
            permission__code="whatsapp.view",
        ).delete()

        response = graphene_client.query(STOREFRONTS, variable_values={"tenantId": tenant_id(organization)})

        assert "permission" in response["errors"][0]["message"].lower()


class TestEligibleStores:
    def test_an_admin_gets_the_stores_a_number_can_sell_from(self, graphene_client, organization):
        act_as(graphene_client, organization, TenantUserRole.ADMIN)
        store(organization, "acme.myshopify.com")
        store(organization, "read-only.myshopify.com", scopes="read_products")
        store(TenantFactory(type=TenantType.ORGANIZATION), "theirs.myshopify.com")

        response = graphene_client.query(ELIGIBLE_STORES, variable_values={"tenantId": tenant_id(organization)})

        assert response["data"]["whatsAppEligibleStores"] == ["acme.myshopify.com"]

    def test_a_member_cant_list_them(self, graphene_client, organization):
        # Only the picker uses this list, and only whatsapp.manage sees the picker.
        act_as(graphene_client, organization, TenantUserRole.MEMBER)
        store(organization, "acme.myshopify.com")

        response = graphene_client.query(ELIGIBLE_STORES, variable_values={"tenantId": tenant_id(organization)})

        assert "permission" in response["errors"][0]["message"].lower()


class TestChoosingAStore:
    def test_an_admin_chooses_the_store_a_number_sells_from(self, graphene_client, organization):
        act_as(graphene_client, organization, TenantUserRole.ADMIN)
        number = ExternalAccountFactory(tenant=organization)
        chosen = store(organization, "acme.myshopify.com")

        response = graphene_client.mutate(
            CHOOSE, variable_values={"input": choose_input(organization, number, "acme.myshopify.com")}
        )

        assert "errors" not in response
        assert response["data"]["chooseWhatsAppStore"]["storefront"] == {
            "accountId": str(number.id),
            "shopDomain": "acme.myshopify.com",
        }
        assert services.store_for(number) == chosen

    def test_a_member_cant_choose(self, graphene_client, organization):
        # Members have whatsapp.view only (plan D16).
        act_as(graphene_client, organization, TenantUserRole.MEMBER)
        number = ExternalAccountFactory(tenant=organization)
        store(organization, "acme.myshopify.com")

        response = graphene_client.mutate(
            CHOOSE, variable_values={"input": choose_input(organization, number, "acme.myshopify.com")}
        )

        assert "permission" in response["errors"][0]["message"].lower()
        assert services.store_for(number) is None

    def test_a_store_that_cant_sell_on_whatsapp_is_refused_under_its_field(self, graphene_client, organization):
        act_as(graphene_client, organization, TenantUserRole.ADMIN)
        number = ExternalAccountFactory(tenant=organization)
        store(organization, "read-only.myshopify.com", scopes="read_products")

        response = graphene_client.mutate(
            CHOOSE, variable_values={"input": choose_input(organization, number, "read-only.myshopify.com")}
        )

        details = problem(response)["shop_domain"][0]
        assert details["code"] == "store_not_eligible"
        assert "Shopify page" in details["message"]

    def test_another_organizations_number_is_not_found(self, graphene_client, organization):
        act_as(graphene_client, organization, TenantUserRole.ADMIN)
        theirs = ExternalAccountFactory(tenant=TenantFactory(type=TenantType.ORGANIZATION))
        store(organization, "acme.myshopify.com")

        response = graphene_client.mutate(
            CHOOSE, variable_values={"input": choose_input(organization, theirs, "acme.myshopify.com")}
        )

        assert problem(response)["non_field_errors"][0]["code"] == "not_found"


class TestTheMode:
    """Menus or the assistant for a number's customers (WhatsApp plan phase 2, decision 2)."""

    def selling(self, organization):
        number = ExternalAccountFactory(tenant=organization)
        store(organization, "acme.myshopify.com")
        services.choose_store(tenant=organization, account_id=str(number.pk), shop_domain="acme.myshopify.com")
        return number

    def set_mode(self, graphene_client, organization, number, mode):
        variables = {"input": {"tenantId": tenant_id(organization), "accountId": str(number.id), "mode": mode}}
        return graphene_client.mutate(SET_MODE, variable_values=variables)

    def test_each_number_shows_its_mode_null_while_no_store_is_chosen(self, graphene_client, organization):
        act_as(graphene_client, organization, TenantUserRole.MEMBER)
        selling = self.selling(organization)
        waiting = ExternalAccountFactory(tenant=organization)

        response = graphene_client.query(STOREFRONT_MODES, variable_values={"tenantId": tenant_id(organization)})

        assert response["data"]["whatsAppStorefronts"] == [
            {"accountId": str(selling.id), "conversationMode": "WHATSAPP_FORM"},
            {"accountId": str(waiting.id), "conversationMode": None},
        ]

    def test_an_admin_sets_the_assistant(self, graphene_client, organization):
        act_as(graphene_client, organization, TenantUserRole.ADMIN)
        number = self.selling(organization)

        response = self.set_mode(graphene_client, organization, number, "AGENTIC")

        assert "errors" not in response
        assert response["data"]["setWhatsAppStorefrontMode"]["storefront"] == {
            "accountId": str(number.id),
            "shopDomain": "acme.myshopify.com",
            "conversationMode": "AGENTIC",
        }

    def test_a_member_cant_set_it(self, graphene_client, organization):
        act_as(graphene_client, organization, TenantUserRole.MEMBER)
        number = self.selling(organization)

        response = self.set_mode(graphene_client, organization, number, "AGENTIC")

        assert "permission" in response["errors"][0]["message"].lower()
        assert number.storefront_channel.conversation_mode == "WHATSAPP_FORM"

    def test_a_number_with_no_store_chosen_says_so(self, graphene_client, organization):
        act_as(graphene_client, organization, TenantUserRole.ADMIN)
        number = ExternalAccountFactory(tenant=organization)

        response = self.set_mode(graphene_client, organization, number, "AGENTIC")

        assert problem(response)["non_field_errors"][0]["code"] == "no_store"

    def test_a_number_whose_store_was_disconnected_says_so(self, graphene_client, organization):
        # Step 2.8, finding 22.
        act_as(graphene_client, organization, TenantUserRole.ADMIN)
        number = self.selling(organization)
        ShopifyShop.objects.filter(shop_domain="acme.myshopify.com").update(tenant=None)

        response = self.set_mode(graphene_client, organization, number, "AGENTIC")

        assert problem(response)["non_field_errors"][0]["code"] == "no_store"


def test_a_number_serving_both_is_listed_with_its_store(graphene_client, organization):
    # One number for the team and the customers (plan Step 2.7) sells too, so it's listed.
    act_as(graphene_client, organization, TenantUserRole.MEMBER)
    shared = InternalAccountFactory(tenant=organization, purpose="INTERNAL_AND_EXTERNAL_COMMUNICATIONS")

    response = graphene_client.query(STOREFRONTS, variable_values={"tenantId": tenant_id(organization)})

    assert response["data"]["whatsAppStorefronts"] == [{"accountId": str(shared.id), "shopDomain": None}]
