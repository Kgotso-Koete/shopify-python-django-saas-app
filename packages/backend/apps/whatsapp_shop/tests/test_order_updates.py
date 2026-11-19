"""
Tests for the order updates a store customer gets on WhatsApp (plan phase 4, Step 4.3c, decisions 3, 4,
5, 7 and 21; user story WA.D5.SC.J1.A2): "Order #1001 received, awaiting payment", then "Order #1001 is paid", on
the number they shopped on, with the order's details as Shopify has them (Step 4.7, decision 30).

- an order finds its chat by the cart's `_whatsapp_checkout` code, in the store that sent it; an order
  without a code, with an unknown one, or another store's, gets nothing
- an unpaid order gets "received, awaiting payment", then "paid" when orders/paid comes; an order paid
  at once gets one "paid" message
- one message per order per stage, however often Shopify sends a webhook and in whatever order; a code
  matches one order only, so a later order with the same code (decision 21) gets nothing
- the order's id, and each stage's message (since Step 4.7), are kept on the checkout; never the order
- no order gets a link anyone holding it could open (decision 30 replaced decision 23's View order link)
- the chat forgets the cart when its order arrives, if it's still the open cart (decision 7)
- within 24 hours of the customer's last message, a normal message; after that, the stage's template
  (Step 4.7, decision 30), with the store and the order number, and an Order details button

Kind of test: integration (agents.md section 2.5). Why: the store, number, customer, their cart's code
and the messages queued for them are rows in the test database, and apps.shopify's signals are sent as
its webhook handlers send them (Step 4.3b); the send task's `delay` is patched, so nothing reaches Meta.
"""

from datetime import timedelta

import pytest
from django.urls import Resolver404, resolve
from django.utils import timezone

from apps.multitenancy.constants import TenantType
from apps.multitenancy.tests.factories import TenantFactory
from apps.shopify import signals
from apps.shopify.models import ShopifyShop
from apps.whatsapp.constants import MessageDirection
from apps.whatsapp.models import WhatsAppMessage
from apps.whatsapp.tests.factories import MessageFactory

from ..models import StoreCheckout, StoreCustomer
from .chat import Screen, customer_of, selling_number, store

pytestmark = pytest.mark.django_db

ATTRIBUTE = "_whatsapp_checkout"
CODE = "wachk_AAAAAAAAAAAAAAAAAAAAAA"
CART = "gid://shopify/Cart/abc"
# Since Step 4.7 (decision 30; agents.md section 5.3d) each update is built from the order as Shopify has it
# when it's sent: its items, total, and payment and delivery status.
RECEIVED = (
    "Order #1001 received, awaiting payment.\n"
    "1 × Acme Snowboard\n"
    "Total: ZAR 199.00\n"
    "Payment: Awaiting payment · Delivery: Not shipped yet"
)
PAID = "Order #1001 is paid.\n1 × Acme Snowboard\nTotal: ZAR 199.00\nPayment: Paid · Delivery: Not shipped yet"
# What the webhook alone says, when Shopify can't be asked.
RECEIVED_FROM_THE_WEBHOOK = "Order #1001 received, awaiting payment. Total: ZAR 199.00."
PAID_FROM_THE_WEBHOOK = "Order #1001 is paid. Total: ZAR 199.00."


@pytest.fixture(autouse=True)
def setup(mocker):
    mocker.patch("apps.whatsapp.tasks.send_queued_messages.delay")


@pytest.fixture(autouse=True)
def live_order(mocker):
    """
    Shopify's Admin API, faked: the order as Shopify has it now, unpaid until a test's paid() marks it paid,
    as orders/paid would find it.
    """
    order = {
        "name": "#1001",
        "cancelledAt": None,
        "displayFinancialStatus": "PENDING",
        "displayFulfillmentStatus": "UNFULFILLED",
        "totalPriceSet": {"shopMoney": {"amount": "199.0", "currencyCode": "ZAR"}},
        "lineItems": {"nodes": [{"title": "Acme Snowboard", "quantity": 1}]},
    }
    client = mocker.Mock()
    client.graphql.side_effect = lambda query, variables: {"order": dict(order)}
    mocker.patch("apps.shopify.orders.admin_client_for", return_value=client)
    return order


@pytest.fixture
def shop():
    return store(TenantFactory(type=TenantType.ORGANIZATION, name="Acme"))


@pytest.fixture
def customer(shop):
    contact = customer_of(selling_number(shop.tenant, shop))
    # They wrote just now, so the 24-hour window is open.
    MessageFactory(contact=contact)
    return contact


@pytest.fixture
def store_customer(customer, shop):
    """A store customer whose open cart is the one the code was made for."""
    return StoreCustomer.objects.create(contact=customer, tenant=shop.tenant, cart_id=CART, cart_shop=shop)


@pytest.fixture
def checkout(store_customer, shop):
    return StoreCheckout.objects.create(code=CODE, store_customer=store_customer, shop=shop, cart_id=CART)


def order(**fields):
    """The short order apps.shopify sends (Step 4.3b, decision 22)."""
    return {
        "id": 5001,
        "name": "#1001",
        "total_price": "199.00",
        "currency": "ZAR",
        "financial_status": "pending",
        "note_attributes": [{"name": ATTRIBUTE, "value": CODE}],
        **fields,
    }


def created(shop, **fields):
    signals.order_created.send(sender=ShopifyShop, shop=shop, order=order(**fields))


def paid(shop, live=None, **fields):
    if live is not None:
        # Shopify now has the order paid, as orders/paid would find it.
        live["displayFinancialStatus"] = "PAID"
    signals.order_paid.send(sender=ShopifyShop, shop=shop, order=order(financial_status="paid", **fields))


def sent(customer) -> list[Screen]:
    """The messages queued for the customer since the last call, oldest first."""
    rows = WhatsAppMessage.objects.filter(contact=customer, direction=MessageDirection.OUTBOUND).order_by("pk")
    screens = [Screen(row.payload) for row in rows]
    rows.delete()
    return screens


@pytest.mark.story("WA.D5.SC.J1.A2")
class TestTheMessages:
    def test_an_unpaid_order_gets_received_awaiting_payment_with_its_details_from_shopify(
        self, shop, customer, checkout
    ):
        created(shop)

        [message] = sent(customer)
        assert message.body == RECEIVED
        # No link to follow (decision 30): the details are in the message, and the way back is Main menu.
        assert message.link is None
        assert message.titles == ["Main menu"]

    def test_then_orders_paid_gets_paid(self, shop, customer, checkout, live_order):
        created(shop)
        sent(customer)

        paid(shop, live_order)

        [message] = sent(customer)
        assert message.body == PAID

    def test_an_order_paid_at_once_gets_one_paid_message(self, shop, customer, checkout, live_order):
        live_order["displayFinancialStatus"] = "PAID"
        created(shop, financial_status="paid")
        paid(shop, live_order)

        [message] = sent(customer)
        assert message.body == PAID

    def test_shopify_unreachable_sends_what_the_webhook_says(self, shop, customer, checkout, mocker):
        from apps.shopify.client import ShopifyThrottledError

        mocker.patch("apps.shopify.orders.admin_client_for").return_value.graphql.side_effect = ShopifyThrottledError(
            "busy"
        )

        created(shop)

        [message] = sent(customer)
        assert message.body == RECEIVED_FROM_THE_WEBHOOK

    def test_an_order_shopify_sent_without_its_id_gets_what_the_webhook_says(self, shop, customer, checkout):
        # Without the order's id there's nothing to ask Shopify for.
        created(shop, id=None)

        [message] = sent(customer)
        assert message.body == RECEIVED_FROM_THE_WEBHOOK

    def test_no_order_gets_a_link_anyone_could_open(self, shop, customer, checkout):
        # Decision 30 replaced decision 23's View order link: a link opens the order to whoever holds it, and the
        # details are in the chat now. No token is kept, and the old links' address leads nowhere.
        created(shop)
        paid(shop)

        assert "order_link_token" not in {field.name for field in StoreCheckout._meta.get_fields()}
        with pytest.raises(Resolver404):
            resolve("/api/whatsapp-shop/orders/an-old-link-token")

    def test_the_checkout_keeps_the_orders_id_and_each_stages_message(self, shop, customer, checkout):
        # Since Step 4.7 (user story WA.D5.SY.J1.A1) each stage keeps its message, and counts as sent only
        # once Meta accepts it (test_order_delivery.py), not when it's queued.
        created(shop)
        checkout.refresh_from_db()
        assert checkout.order_id == 5001
        assert checkout.received_message is not None
        assert checkout.paid_message is None

        paid(shop)

        checkout.refresh_from_db()
        assert checkout.paid_message is not None


@pytest.mark.story("WA.D5.SC.J1.A2")
class TestOncePerStage:
    def test_a_retried_orders_create_sends_once(self, shop, customer, checkout):
        created(shop)
        created(shop)

        assert [message.body for message in sent(customer)] == [RECEIVED]

    def test_a_retried_orders_paid_sends_once(self, shop, customer, checkout, live_order):
        paid(shop, live_order)
        paid(shop, live_order)

        assert [message.body for message in sent(customer)] == [PAID]

    def test_orders_paid_before_orders_create_sends_paid_only(self, shop, customer, checkout, live_order):
        paid(shop, live_order)
        created(shop)

        assert [message.body for message in sent(customer)] == [PAID]

    def test_a_later_order_with_the_same_code_gets_nothing(self, shop, customer, checkout):
        # Decision 21: the code stays on the browser's cart, so a later order can carry it again.
        created(shop)
        sent(customer)

        created(shop, id=5002, name="#1002")
        paid(shop, id=5002, name="#1002")

        assert sent(customer) == []
        checkout.refresh_from_db()
        assert checkout.order_id == 5001


@pytest.mark.story("WA.D5.SC.J1.A2")
class TestMatching:
    def test_an_order_without_a_code_gets_nothing(self, shop, customer, checkout):
        created(shop, note_attributes=[])

        assert sent(customer) == []

    def test_an_order_with_an_unknown_code_gets_nothing(self, shop, customer, checkout):
        created(shop, note_attributes=[{"name": ATTRIBUTE, "value": "wachk_unknown"}])

        assert sent(customer) == []

    def test_another_stores_order_with_the_code_gets_nothing(self, shop, customer, checkout):
        other = store(TenantFactory(type=TenantType.ORGANIZATION, name="Other"), domain="other.myshopify.com")

        created(other)
        paid(other)

        assert sent(customer) == []
        checkout.refresh_from_db()
        assert checkout.order_id is None


@pytest.mark.story("WA.D5.SC.J1.A3")
class TestForgettingTheCart:
    def test_the_order_forgets_the_open_cart_it_came_from(self, shop, customer, store_customer, checkout):
        created(shop)

        store_customer.refresh_from_db()
        assert store_customer.cart_id == ""
        assert store_customer.cart_shop is None

    def test_a_newer_open_cart_is_kept(self, shop, customer, store_customer, checkout):
        # The order came from a Buy now cart; the customer's open cart is another one.
        StoreCustomer.objects.filter(pk=store_customer.pk).update(cart_id="gid://shopify/Cart/open")

        created(shop)

        store_customer.refresh_from_db()
        assert store_customer.cart_id == "gid://shopify/Cart/open"
        assert store_customer.cart_shop == shop


def templates_sent(customer) -> list[dict]:
    """The template messages queued for the customer since the last call: each one's name, blanks and button."""
    rows = WhatsAppMessage.objects.filter(contact=customer, direction=MessageDirection.OUTBOUND).order_by("pk")
    sent_now = []
    for row in rows:
        template = row.payload["template"]
        body, button = template["components"]
        sent_now.append(
            {
                "name": template["name"],
                "language": template["language"]["code"],
                "body": [parameter["text"] for parameter in body["parameters"]],
                "button": (button["sub_type"], button["parameters"][0]),
            }
        )
    rows.delete()
    return sent_now


@pytest.mark.story("WA.D5.SC.J1.A2")
class TestTheWindow:
    """
    Decision 6: after 24 hours only a template can go. Since Step 4.7 (decision 30) it's one template for any
    stage, with the store and the order number, and an Order details button that brings the customer back
    into the window, where the details are sent live (test_order_details_button.py).
    """

    @pytest.fixture
    def window_closed(self, customer):
        WhatsAppMessage.objects.filter(contact=customer).update(sent_at=timezone.now() - timedelta(hours=25))

    def expected(self):
        return {
            "name": "shop_order_update",
            "language": "en",
            "body": ["Acme Outdoor", "#1001"],
            "button": ("quick_reply", {"type": "payload", "payload": f"order:{CODE}"}),
        }

    def test_after_24_hours_received_goes_as_the_template(self, shop, customer, checkout, window_closed):
        created(shop)

        checkout.refresh_from_db()
        assert templates_sent(customer) == [self.expected()]
        # The id read before templates_sent deleted the message.
        assert checkout.received_message_id is not None

    def test_after_24_hours_paid_goes_as_the_same_template(self, shop, customer, checkout, window_closed, live_order):
        created(shop)
        templates_sent(customer)

        paid(shop, live_order)

        checkout.refresh_from_db()
        assert templates_sent(customer) == [self.expected()]
        # The id read before templates_sent deleted the message.
        assert checkout.paid_message_id is not None

    def test_an_order_without_its_id_still_gets_the_template(self, shop, customer, checkout, window_closed):
        # The template needs only the order's number, which the webhook carries.
        created(shop, id=None)

        assert templates_sent(customer) == [self.expected()]
