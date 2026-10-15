"""
Tests for the shopifyProducts GraphQL query (plan step 11, section 5.2 cases 5, 6 and 10).

fetch_products is replaced by a fake, so these tests cover only the GraphQL layer: who may ask,
which store they may ask about, and what reaches the browser. test_products.py covers the rest.
"""

import pytest
from graphql_relay import to_global_id

from apps.multitenancy.constants import TenantUserRole
from apps.multitenancy.tests.factories import TenantFactory, TenantMembershipFactory
from apps.shopify.models import ShopifyShop
from apps.shopify.products import ShopifyReconnectRequired, ShopifyTryAgainLater
from apps.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

STORE = "products-demo.myshopify.com"

QUERY = """
query($tenantId: ID!, $shopDomain: String!, $first: Int!, $after: String, $before: String) {
  shopifyProducts(tenantId: $tenantId, shopDomain: $shopDomain, first: $first, after: $after, before: $before) {
    products {
      id
      title
      handle
      status
      imageUrl
      imageAlt
      priceMin
      priceMax
      currencyCode
    }
    pageInfo {
      hasNextPage
      hasPreviousPage
      startCursor
      endCursor
    }
  }
}
"""

ONE_PAGE = {
    "products": [
        {
            "id": "gid://shopify/Product/1",
            "title": "Blue shirt",
            "handle": "blue-shirt",
            "status": "ACTIVE",
            "image_url": "https://cdn.shopify.com/blue-shirt.jpg",
            "image_alt": "A blue shirt",
            "price_min": "19.99",
            "price_max": "24.50",
            "currency_code": "ZAR",
        }
    ],
    "page_info": {
        "has_next_page": True,
        "has_previous_page": False,
        "start_cursor": "cursor-start",
        "end_cursor": "cursor-end",
    },
}


@pytest.fixture
def tenant():
    return TenantFactory()


@pytest.fixture
def member(graphene_client, tenant):
    # MEMBER has shopify.view by default (apps/shopify/permissions.py, migration 0003).
    user = UserFactory()
    TenantMembershipFactory(user=user, tenant=tenant, role=TenantUserRole.MEMBER)
    graphene_client.force_authenticate(user)
    graphene_client.set_tenant_dependent_context(tenant, TenantUserRole.MEMBER)
    return user


@pytest.fixture
def store(tenant):
    return ShopifyShop.objects.create(shop_domain=STORE, tenant=tenant, access_token="acc_secret_token")


@pytest.fixture
def fake_fetch(mocker):
    # Patched where the schema looks it up.
    return mocker.patch("apps.shopify.schema.fetch_products", return_value=ONE_PAGE)


def ask(graphene_client, tenant, shop_domain=STORE, **variables):
    return graphene_client.query(
        QUERY,
        variable_values={
            "tenantId": to_global_id("TenantType", tenant.id),
            "shopDomain": shop_domain,
            "first": 12,
            **variables,
        },
    )


def test_a_member_gets_a_page_of_products(graphene_client, tenant, member, store, fake_fetch):
    response = ask(graphene_client, tenant)

    assert "errors" not in response
    assert response["data"]["shopifyProducts"] == {
        "products": [
            {
                "id": "gid://shopify/Product/1",
                "title": "Blue shirt",
                "handle": "blue-shirt",
                "status": "ACTIVE",
                "imageUrl": "https://cdn.shopify.com/blue-shirt.jpg",
                "imageAlt": "A blue shirt",
                "priceMin": "19.99",
                "priceMax": "24.50",
                "currencyCode": "ZAR",
            }
        ],
        "pageInfo": {
            "hasNextPage": True,
            "hasPreviousPage": False,
            "startCursor": "cursor-start",
            "endCursor": "cursor-end",
        },
    }


def test_the_page_size_and_cursors_reach_fetch_products(graphene_client, tenant, member, store, fake_fetch):
    ask(graphene_client, tenant, first=12, after="cursor-end")

    fake_fetch.assert_called_once()
    assert [shop.pk for shop in fake_fetch.call_args.args] == [store.pk]
    assert fake_fetch.call_args.kwargs == {"first": 12, "after": "cursor-end", "before": None}


def test_a_member_without_shopify_view_is_refused(graphene_client, tenant, member, store, fake_fetch):
    from apps.multitenancy.models import OrganizationRolePermission

    OrganizationRolePermission.objects.filter(
        role__tenant=tenant, role__system_role_type=TenantUserRole.MEMBER, permission__code="shopify.view"
    ).delete()

    response = ask(graphene_client, tenant)

    assert "permission" in response["errors"][0]["message"].lower()
    fake_fetch.assert_not_called()


def problem(response):
    # User-facing errors are GraphQlValidationError, the repo's convention: the message is the class
    # name and the details are in extensions, as {"non_field_errors": [{"message": ..., "code": ...}]}
    # (common/graphql/views.py; the same shape as the PayFast errors).
    error = response["errors"][0]
    assert error["message"] == "GraphQlValidationError"
    return error["extensions"]["non_field_errors"][0]


def test_a_store_linked_to_another_organization_is_not_found(graphene_client, tenant, member, fake_fetch):
    ShopifyShop.objects.create(shop_domain="other-org.myshopify.com", tenant=TenantFactory())

    other = ask(graphene_client, tenant, shop_domain="other-org.myshopify.com")
    missing = ask(graphene_client, tenant, shop_domain="no-such-store.myshopify.com")

    # The same answer for both, so nobody can learn which stores other organizations have.
    assert problem(other) == {"message": "Store not found.", "code": "store_not_found"}
    assert problem(missing) == problem(other)
    fake_fetch.assert_not_called()


@pytest.mark.parametrize(
    "error, code",
    [
        pytest.param(ShopifyReconnectRequired(), "reconnect_required", id="reconnect"),
        pytest.param(ShopifyTryAgainLater(), "try_again_later", id="try_again"),
    ],
)
def test_store_problems_reach_the_browser_with_a_code(graphene_client, tenant, member, store, fake_fetch, error, code):
    fake_fetch.side_effect = error

    response = ask(graphene_client, tenant)

    assert problem(response) == {"message": str(error), "code": code}


def test_store_problems_survive_the_production_error_sanitizer(
    graphene_client, tenant, member, store, fake_fetch, settings
):
    # With DEBUG off, SanitizeErrorsMiddleware (common/graphql/security.py) turns any error it doesn't
    # know is safe into "An error occurred while processing your request." The test client doesn't add
    # it, so this test does, the way config/settings.py does.
    from common.graphql.security import SanitizeErrorsMiddleware

    settings.DEBUG = False
    graphene_client.execute_options["middleware"] = [SanitizeErrorsMiddleware()]
    fake_fetch.side_effect = ShopifyReconnectRequired()

    response = ask(graphene_client, tenant)

    assert problem(response)["code"] == "reconnect_required"


def test_no_token_reaches_the_browser(graphene_client, tenant, member, store, fake_fetch):
    response = ask(graphene_client, tenant)

    assert "acc_secret_token" not in str(response)
