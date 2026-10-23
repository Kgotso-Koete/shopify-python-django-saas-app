"""
Tests for the Shopify product operations in apps/whatsapp_saas/use_cases.py (plan Step 1.12b,
decision D10, user story 7).

Each checks what its GraphQL twin checks (shopifyShops and shopifyProducts in apps/shopify/schema.py):
membership plus shopify.view, and a store only of the selected organization. Products are read live
through apps.shopify's fetch_products, 7 to a page (D17), newest first (chosen on 2026-10-20 for
WhatsApp only), paged by Shopify's cursors and searched by its query.

Kind of test: integration (agents.md section 2.5). Why: organizations, permissions and stores are
rows in the test database; fetch_products, which calls Shopify's Admin API, is mocked.
"""

import pytest

from apps.multitenancy.constants import TenantType, TenantUserRole
from apps.multitenancy.models import OrganizationRolePermission, invalidate_user_permissions_cache
from apps.multitenancy.tests.factories import TenantFactory, TenantMembershipFactory
from apps.shopify.models import ShopifyShop
from apps.shopify.products import ShopifyReconnectRequired, ShopifyTryAgainLater
from apps.users.tests.factories import UserFactory

from .. import use_cases
from ..use_cases import PAGE_SIZE, UseCaseError

pytestmark = pytest.mark.django_db

PRODUCT = {
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


def page_of(products, *, has_next=False, has_previous=False):
    """What fetch_products returns."""
    return {
        "products": products,
        "page_info": {
            "has_next_page": has_next,
            "has_previous_page": has_previous,
            "start_cursor": "cursor-start",
            "end_cursor": "cursor-end",
        },
    }


@pytest.fixture
def fetch(mocker):
    return mocker.patch("apps.whatsapp_saas.use_cases.fetch_products", return_value=page_of([PRODUCT]))


@pytest.fixture
def user():
    return UserFactory()


@pytest.fixture
def organization(user):
    tenant = TenantFactory(type=TenantType.ORGANIZATION)
    TenantMembershipFactory(user=user, tenant=tenant, role=TenantUserRole.MEMBER)
    return tenant


@pytest.fixture
def store(organization):
    return ShopifyShop.objects.create(shop_domain="acme.myshopify.com", tenant=organization)


def without_shopify_view(user, tenant):
    OrganizationRolePermission.objects.filter(role__tenant=tenant, permission__code="shopify.view").delete()
    # Permissions are cached per user and organization; upstream's role editing clears it like this.
    invalidate_user_permissions_cache(user.id, tenant.id)


class TestStores:
    def test_the_organizations_stores_by_domain(self, user, organization, store):
        ShopifyShop.objects.create(shop_domain="acme-outlet.myshopify.com", tenant=organization)
        ShopifyShop.objects.create(shop_domain="someone-else.myshopify.com", tenant=TenantFactory())

        stores = use_cases.list_stores(user, organization)

        assert [shop.shop_domain for shop in stores] == ["acme-outlet.myshopify.com", "acme.myshopify.com"]

    def test_a_member_may_see_them_without_shopify_view_they_may_not(self, user, organization, store):
        assert use_cases.can_view_products(user, organization)
        without_shopify_view(user, organization)

        assert not use_cases.can_view_products(user, organization)
        with pytest.raises(UseCaseError) as error:
            use_cases.list_stores(user, organization)
        assert error.value.code == "permission_denied"

    def test_one_store_is_only_found_in_its_own_organization(self, user, organization, store):
        theirs = ShopifyShop.objects.create(shop_domain="someone-else.myshopify.com", tenant=TenantFactory())

        assert use_cases.get_store(user, organization, store.pk) == store
        with pytest.raises(UseCaseError) as error:
            use_cases.get_store(user, organization, theirs.pk)
        assert str(error.value) == "Store not found."

    def test_an_organization_the_user_isnt_in_is_not_found(self, user):
        stranger = TenantFactory(type=TenantType.ORGANIZATION)

        assert not use_cases.can_view_products(user, stranger)
        with pytest.raises(UseCaseError) as error:
            use_cases.list_stores(user, stranger)
        assert error.value.code == "not_found"


class TestProducts:
    def test_a_page_holds_seven_newest_first(self, user, organization, store, fetch):
        fetch.return_value = page_of([PRODUCT], has_next=True)

        page = use_cases.list_products(user, organization, store.pk)

        assert PAGE_SIZE == 7
        fetch.assert_called_once_with(store, first=7, after=None, before=None, query=None, newest_first=True)
        assert page.store == store
        assert page.products == [PRODUCT]
        assert (page.has_previous, page.has_next) == (False, True)
        assert (page.start_cursor, page.end_cursor) == ("cursor-start", "cursor-end")

    def test_the_cursors_and_search_go_to_shopify_as_given(self, user, organization, store, fetch):
        use_cases.list_products(user, organization, store.pk, after="cursor-end", query="shirt")
        assert fetch.call_args.kwargs == {
            "first": 7,
            "after": "cursor-end",
            "before": None,
            "query": "shirt",
            "newest_first": True,
        }

        use_cases.list_products(user, organization, store.pk, before="cursor-start")
        assert fetch.call_args.kwargs["before"] == "cursor-start"

    def test_another_organizations_store_is_not_found_and_shopify_isnt_asked(self, user, organization, fetch):
        theirs = ShopifyShop.objects.create(shop_domain="someone-else.myshopify.com", tenant=TenantFactory())

        with pytest.raises(UseCaseError) as error:
            use_cases.list_products(user, organization, theirs.pk)

        assert error.value.code == "not_found"
        assert str(error.value) == "Store not found."
        fetch.assert_not_called()

    def test_without_shopify_view_shopify_isnt_asked(self, user, organization, store, fetch):
        without_shopify_view(user, organization)

        with pytest.raises(UseCaseError) as error:
            use_cases.list_products(user, organization, store.pk)

        assert error.value.code == "permission_denied"
        fetch.assert_not_called()

    def test_a_store_that_must_be_reconnected_says_so_clearly(self, user, organization, store, fetch):
        fetch.side_effect = ShopifyReconnectRequired()

        with pytest.raises(UseCaseError) as error:
            use_cases.list_products(user, organization, store.pk)

        assert error.value.code == "reconnect_required"
        assert "reconnected" in str(error.value)

    def test_a_busy_shopify_asks_to_try_again(self, user, organization, store, fetch):
        fetch.side_effect = ShopifyTryAgainLater()

        with pytest.raises(UseCaseError) as error:
            use_cases.list_products(user, organization, store.pk)

        assert error.value.code == "try_again_later"
