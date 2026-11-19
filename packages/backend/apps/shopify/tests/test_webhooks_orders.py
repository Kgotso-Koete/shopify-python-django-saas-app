"""
Tests for the order webhooks, orders/create and orders/paid (WhatsApp plan phase 4, Step 4.3b,
decisions 3, 4 and 5).

- an order delivery is recorded like the other topics, but keeps only what the app uses: the order's
  id, its name (#1001), total, currency, financial status, and the note attributes an app asked to
  keep (decisions 4 and 22, POPIA's minimality); the customer, addresses, lines and the status page
  link (decision 23) are never stored
- note attributes no app asked for are dropped, since any app on the store can write them
- the same short order goes to order_created and order_paid, whether the handler runs in the request
  or in the Celery task, which reads it back from the delivery row
- other topics are stored whole, as before
- a delivery for a store we don't have sends nothing

Kind of test: integration (agents.md section 2.5). Why: posts go through the real route with Django's
test client, against the test database; Shopify is simulated by HMAC-signed posts, and in Celery mode
the task's `delay` is patched and the task is then run directly.
"""

import base64
import hashlib
import hmac
import json
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from django.conf import settings

from apps.shopify.models import ShopifyShop, ShopifyWebhookDelivery

pytestmark = pytest.mark.django_db

WEBHOOK_URL = "/api/shopify/webhooks/"
SHOP_DOMAIN = "orders-shop.myshopify.com"
KEPT_KEY = "_test_checkout"

# The fields of Shopify's order payload the app keeps, as Shopify names them.
KEPT = {
    "id": 820982911946154508,
    "name": "#9999",
    "total_price": "199.00",
    "currency": "ZAR",
    "financial_status": "pending",
}
# Some of what else an order delivery carries: never stored. The status page link opens the customer's
# order to whoever holds it, and the app asks Shopify for a fresh one when needed (decision 23).
NOT_KEPT = {
    "order_status_url": "https://orders-shop.myshopify.com/1/orders/abc/authenticate?key=xyz",
    "email": "buyer@example.com",
    "phone": "+27820000000",
    "customer": {"id": 115310627314723954, "first_name": "Thandi", "email": "buyer@example.com"},
    "shipping_address": {"address1": "1 Long Street", "city": "Cape Town"},
    "line_items": [{"id": 1, "title": "Snowboard", "quantity": 1, "price": "199.00"}],
    "note": "Leave at the gate",
}
OUR_ATTRIBUTE = {"name": KEPT_KEY, "value": "wachk_abc"}
ANOTHER_APPS_ATTRIBUTE = {"name": "gift_message", "value": "Happy birthday Thandi"}

ORDER_DELIVERY = {**KEPT, **NOT_KEPT, "note_attributes": [OUR_ATTRIBUTE, ANOTHER_APPS_ATTRIBUTE]}
SHORT_ORDER = {**KEPT, "note_attributes": [OUR_ATTRIBUTE]}


def _webhook_hmac(body: bytes, secret: str) -> str:
    """Compute the base64 HMAC-SHA256 that Shopify sends in X-Shopify-Hmac-Sha256."""
    return base64.b64encode(hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()).decode("utf-8")


def _post_webhook(client, topic, payload, webhook_id, shop_domain=SHOP_DOMAIN):
    """POST a validly signed webhook to the endpoint."""
    body = json.dumps(payload).encode("utf-8")
    return client.post(
        WEBHOOK_URL,
        data=body,
        content_type="application/json",
        HTTP_X_SHOPIFY_TOPIC=topic,
        HTTP_X_SHOPIFY_SHOP_DOMAIN=shop_domain,
        HTTP_X_SHOPIFY_WEBHOOK_ID=webhook_id,
        HTTP_X_SHOPIFY_API_VERSION=settings.SHOPIFY_API_VERSION,
        HTTP_X_SHOPIFY_HMAC_SHA256=_webhook_hmac(body, settings.SHOPIFY_API_SECRET),
    )


@contextmanager
def listening(signal_name):
    """Collects what apps.shopify's `signal_name` sends while the block runs."""
    # Imported here, not at the top, so a missing signal fails each test instead of the whole file.
    from apps.shopify import signals

    signal = getattr(signals, signal_name)
    received = []

    def receiver(sender, **kwargs):
        received.append((kwargs["shop"], kwargs["order"]))

    signal.connect(receiver, weak=False)
    try:
        yield received
    finally:
        signal.disconnect(receiver)


@pytest.fixture(autouse=True)
def sync_dispatch(monkeypatch):
    monkeypatch.setattr(settings, "SHOPIFY_WEBHOOK_DISPATCH", "sync")


@pytest.fixture(autouse=True)
def keep_our_attribute():
    """An app asks to keep its note attribute, as apps.whatsapp_shop does for its checkout code."""
    from apps.shopify import payloads

    payloads.keep_note_attribute(KEPT_KEY)


@pytest.fixture
def shop():
    return ShopifyShop.objects.create(
        shop_domain=SHOP_DOMAIN, access_token="acc_orders", refresh_token="ref_orders", scopes="read_products"
    )


@pytest.mark.story("WA.D7.SY.J1.A1")
class TestWhatIsStored:
    @pytest.mark.parametrize("topic", ["orders/create", "orders/paid"])
    def test_an_order_delivery_keeps_only_what_the_app_uses(self, client, shop, topic):
        response = _post_webhook(client, topic, ORDER_DELIVERY, webhook_id=f"order-{topic}")

        assert response.status_code == 200
        delivery = ShopifyWebhookDelivery.objects.get(webhook_id=f"order-{topic}")
        assert delivery.topic == topic
        assert delivery.shop_domain == SHOP_DOMAIN
        assert delivery.payload == SHORT_ORDER

    def test_a_field_the_delivery_lacks_stays_out(self, client, shop):
        payload = {key: value for key, value in ORDER_DELIVERY.items() if key != "total_price"}

        _post_webhook(client, "orders/create", payload, webhook_id="order-no-total")

        stored = ShopifyWebhookDelivery.objects.get(webhook_id="order-no-total").payload
        assert "total_price" not in stored
        assert stored["name"] == "#9999"

    def test_an_order_with_none_of_the_kept_attributes_keeps_an_empty_list(self, client, shop):
        payload = {**ORDER_DELIVERY, "note_attributes": [ANOTHER_APPS_ATTRIBUTE]}

        _post_webhook(client, "orders/create", payload, webhook_id="order-other-attributes")

        stored = ShopifyWebhookDelivery.objects.get(webhook_id="order-other-attributes").payload
        assert stored["note_attributes"] == []

    def test_other_topics_are_stored_whole(self, client, shop):
        payload = {"shop_domain": SHOP_DOMAIN, "customer": {"id": 1, "phone": "+27820000000"}, "orders_to_redact": [2]}

        _post_webhook(client, "customers/redact", payload, webhook_id="redact-whole")

        assert ShopifyWebhookDelivery.objects.get(webhook_id="redact-whole").payload == payload

    def test_a_retried_order_delivery_is_recorded_once(self, client, shop):
        with listening("order_created") as received:
            _post_webhook(client, "orders/create", ORDER_DELIVERY, webhook_id="order-retried")
            _post_webhook(client, "orders/create", ORDER_DELIVERY, webhook_id="order-retried")

        assert ShopifyWebhookDelivery.objects.filter(webhook_id="order-retried").count() == 1
        assert len(received) == 1


@pytest.mark.story("WA.D5.SC.J1.A2")
class TestTheSignals:
    def test_orders_create_sends_order_created_with_the_short_order(self, client, shop):
        with listening("order_created") as created, listening("order_paid") as paid:
            _post_webhook(client, "orders/create", ORDER_DELIVERY, webhook_id="order-created-1")

        assert created == [(shop, SHORT_ORDER)]
        assert paid == []

    def test_orders_paid_sends_order_paid_with_the_short_order(self, client, shop):
        with listening("order_created") as created, listening("order_paid") as paid:
            _post_webhook(client, "orders/paid", ORDER_DELIVERY, webhook_id="order-paid-1")

        assert paid == [(shop, SHORT_ORDER)]
        assert created == []

    def test_a_store_we_dont_have_sends_nothing(self, client):
        with listening("order_created") as created:
            response = _post_webhook(
                client,
                "orders/create",
                ORDER_DELIVERY,
                webhook_id="order-unknown-shop",
                shop_domain="nobody.myshopify.com",
            )

        assert response.status_code == 200
        assert created == []


@pytest.mark.story("WA.D5.SC.J1.A2")
class TestInCelery:
    @pytest.mark.parametrize(
        ("topic", "signal_name"), [("orders/create", "order_created"), ("orders/paid", "order_paid")]
    )
    def test_the_task_sends_the_short_order_it_reads_back(self, client, shop, monkeypatch, topic, signal_name):
        monkeypatch.setattr(settings, "SHOPIFY_WEBHOOK_DISPATCH", "celery")
        with patch("apps.shopify.webhooks.process_shopify_webhook") as task:
            with listening(signal_name) as received:
                _post_webhook(client, topic, ORDER_DELIVERY, webhook_id=f"celery-{topic}")
            assert received == []
        delivery = ShopifyWebhookDelivery.objects.get(webhook_id=f"celery-{topic}")
        task.delay.assert_called_once_with(delivery.id)

        from apps.shopify.tasks import process_shopify_webhook

        with listening(signal_name) as received:
            process_shopify_webhook(delivery.id)

        assert received == [(shop, SHORT_ORDER)]
