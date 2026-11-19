"""
Tests for asking Shopify for an order's details as they are now (WhatsApp plan Step 4.7, decision 30, user
story WA.D5.SC.J1.A2; agents.md section 5.3d): its number, items, total, payment and delivery status, and
whether it's cancelled, so an order update in the chat is built from Shopify's order, never a stored copy.

- the Admin API is asked for the order by its id, for protected customer data level 1 fields only: no name,
  email, phone or address, and not the order's status page, which needs level 2
- an order Shopify no longer has is None
- a store that must be reconnected, or Shopify throttling, raises the errors products.py raises

Kind of test: integration (agents.md section 2.5). Why: the store is a row in the test database; Shopify's
Admin API is faked at apps.shopify.orders's `admin_client_for`.
"""

import pytest

from apps.shopify.client import ShopifyRefreshTokenRejected, ShopifyThrottledError
from apps.shopify.models import ShopifyShop
from apps.shopify.products import ShopifyReconnectRequired, ShopifyTryAgainLater

pytestmark = [pytest.mark.django_db, pytest.mark.story("WA.D5.SC.J1.A2")]

SHOPIFY_ORDER = {
    "order": {
        "name": "#1006",
        "cancelledAt": None,
        "displayFinancialStatus": "PAID",
        "displayFulfillmentStatus": "UNFULFILLED",
        "totalPriceSet": {"shopMoney": {"amount": "1025.0", "currencyCode": "USD"}},
        "lineItems": {
            "nodes": [
                {"title": "The Collection Snowboard: Oxygen", "quantity": 1},
                {"title": "Wax", "quantity": 2},
            ]
        },
    }
}


def order_details(shop, order_id):
    # Imported here, not at the top, so a missing function fails each test instead of the whole file.
    from apps.shopify.orders import order_details

    return order_details(shop, order_id)


@pytest.fixture
def shop():
    return ShopifyShop.objects.create(shop_domain="details-shop.myshopify.com")


@pytest.fixture
def shopify(mocker):
    client = mocker.Mock()
    client.graphql.return_value = SHOPIFY_ORDER
    mocker.patch("apps.shopify.orders.admin_client_for", return_value=client)
    return client


def test_the_order_is_asked_for_by_its_id_and_given_back_plainly(shop, shopify):
    details = order_details(shop, 7579118731547)

    assert details == {
        "id": 7579118731547,
        "name": "#1006",
        "total_price": "1025.0",
        "currency": "USD",
        "financial_status": "PAID",
        "fulfillment_status": "UNFULFILLED",
        "cancelled": False,
        "lines": [
            {"title": "The Collection Snowboard: Oxygen", "quantity": 1},
            {"title": "Wax", "quantity": 2},
        ],
    }
    [call] = shopify.graphql.call_args_list
    assert call.kwargs["variables"] == {"id": "gid://shopify/Order/7579118731547"}


def test_only_level_1_fields_are_asked_for(shop, shopify):
    order_details(shop, 1)

    query = shopify.graphql.call_args.args[0]
    for level_2 in ("statusPageUrl", "customer", "email", "phone", "shippingAddress", "billingAddress"):
        assert level_2 not in query


def test_a_cancelled_order_says_so(shop, shopify):
    shopify.graphql.return_value = {"order": {**SHOPIFY_ORDER["order"], "cancelledAt": "2026-11-11T08:00:00Z"}}

    assert order_details(shop, 1)["cancelled"] is True


def test_an_order_shopify_no_longer_has_is_none(shop, shopify):
    shopify.graphql.return_value = {"order": None}

    assert order_details(shop, 1) is None


def test_a_store_to_reconnect_raises_without_asking(shop, shopify):
    shop.needs_reinstall = True
    shop.save(update_fields=["needs_reinstall"])

    with pytest.raises(ShopifyReconnectRequired):
        order_details(shop, 1)

    shopify.graphql.assert_not_called()


@pytest.mark.parametrize(
    ("raised", "expected"),
    [
        (ShopifyRefreshTokenRejected("rejected"), ShopifyReconnectRequired),
        (ShopifyThrottledError("busy"), ShopifyTryAgainLater),
    ],
)
def test_shopifys_refusals_raise_the_products_errors(shop, shopify, raised, expected):
    shopify.graphql.side_effect = raised

    with pytest.raises(expected):
        order_details(shop, 1)
