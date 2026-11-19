"""
Tests for the Order details button on the update template (WhatsApp plan Step 4.7, decision 30, user story
WA.D5.SC.J1.A2): after the 24-hour window the update is a template, and tapping its Order details button is a
message from the customer, which opens a new window, so the store answers with the order's details as Shopify
has them now (agents.md section 5.3d), as a normal message.

- the tap's payload names the checkout (`order:<code>`); the details come from Shopify's Admin API, never a
  stored copy
- only the customer's own order: another customer's code, an unknown one, an order Shopify no longer has, and a
  checkout with no order yet all get the same "isn't available" answer, so nobody learns which orders exist
- Shopify busy or the store to reconnect gets "can't be reached right now"

Kind of test: integration (agents.md section 2.5). Why: the store, number, customers and checkouts are rows in
the test database, and the tap goes through the real router; Shopify's Admin API is faked at
apps.shopify.orders's `admin_client_for`, and the send task's `delay` is patched.
"""

import pytest

from apps.multitenancy.constants import TenantType
from apps.multitenancy.tests.factories import TenantFactory
from apps.shopify.client import ShopifyThrottledError
from apps.whatsapp.tests.factories import ContactFactory

from ..models import StoreCheckout, StoreCustomer
from .chat import customer_of, selling_number, send, store

pytestmark = [pytest.mark.django_db, pytest.mark.story("WA.D5.SC.J1.A2")]

CODE = "wachk_DDDDDDDDDDDDDDDDDDDDDD"
LIVE = {
    "name": "#1001",
    "cancelledAt": None,
    "displayFinancialStatus": "PAID",
    "displayFulfillmentStatus": "FULFILLED",
    "totalPriceSet": {"shopMoney": {"amount": "199.0", "currencyCode": "ZAR"}},
    "lineItems": {"nodes": [{"title": "Acme Snowboard", "quantity": 1}]},
}
DETAILS = "Order #1001\n1 × Acme Snowboard\nTotal: ZAR 199.00\nPayment: Paid · Delivery: Shipped"
NOT_AVAILABLE = "That order isn't available any more. Send *menu* for the main menu."


@pytest.fixture(autouse=True)
def setup(mocker):
    mocker.patch("apps.whatsapp.tasks.send_queued_messages.delay")


@pytest.fixture
def shopify(mocker):
    client = mocker.Mock()
    client.graphql.return_value = {"order": dict(LIVE)}
    mocker.patch("apps.shopify.orders.admin_client_for", return_value=client)
    return client


@pytest.fixture
def shop():
    return store(TenantFactory(type=TenantType.ORGANIZATION, name="Acme"))


@pytest.fixture
def customer(shop):
    return customer_of(selling_number(shop.tenant, shop))


def checkout_of(contact, shop, *, code=CODE, order_id=5001):
    store_customer, _ = StoreCustomer.objects.get_or_create(contact=contact, defaults={"tenant": shop.tenant})
    return StoreCheckout.objects.create(
        code=code, store_customer=store_customer, shop=shop, cart_id=f"gid://shopify/Cart/{code}", order_id=order_id
    )


def tap(customer, code=CODE):
    return send(customer, press=f"order:{code}")


def test_the_tap_answers_with_the_orders_details_from_shopify(shop, customer, shopify):
    checkout_of(customer, shop)

    [reply] = tap(customer)

    assert reply.body == DETAILS
    assert reply.titles == ["Main menu"]
    [call] = shopify.graphql.call_args_list
    assert call.kwargs["variables"] == {"id": "gid://shopify/Order/5001"}


def test_another_customers_order_isnt_available(shop, customer, shopify):
    someone_else = ContactFactory(account=customer.account, wa_id="27000001999")
    checkout_of(someone_else, shop)

    [reply] = tap(customer)

    assert reply.body == NOT_AVAILABLE
    shopify.graphql.assert_not_called()


def test_an_unknown_code_isnt_available(shop, customer, shopify):
    [reply] = tap(customer, code="wachk_unknown")

    assert reply.body == NOT_AVAILABLE


def test_a_checkout_without_an_order_yet_isnt_available(shop, customer, shopify):
    checkout_of(customer, shop, order_id=None)

    [reply] = tap(customer)

    assert reply.body == NOT_AVAILABLE
    shopify.graphql.assert_not_called()


def test_an_order_shopify_no_longer_has_isnt_available(shop, customer, shopify):
    checkout_of(customer, shop)
    shopify.graphql.return_value = {"order": None}

    [reply] = tap(customer)

    assert reply.body == NOT_AVAILABLE


def test_shopify_busy_says_to_try_again(shop, customer, shopify):
    checkout_of(customer, shop)
    shopify.graphql.side_effect = ShopifyThrottledError("busy")

    [reply] = tap(customer)

    assert reply.body == "The shop can't be reached right now. Please try again in a few minutes."
