"""
Tests for the Shopify webhook endpoint (POST /api/shopify/webhooks/).

Covers:
- HMAC validation (wrong, missing → 401 for every topic)
- Deduplication via X-Shopify-Webhook-Id (duplicate → 200, no second effect)
- app/uninstalled: wipes tokens, sets uninstalled_at, keeps tenant link
- shop/redact: anonymizes shop row, redacts delivery payloads (tombstone)
- customers/redact and customers/data_request: answer 200 and record
- Unknown topic: answer 200 with a warning logged
- GET → 405
"""

import base64
import hashlib
import hmac
import json
import logging

import pytest
from django.conf import settings
from django.test import Client

from apps.shopify.models import ShopifyShop, ShopifyWebhookDelivery

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

WEBHOOK_URL = "/api/shopify/webhooks/"


def _webhook_hmac(body: bytes, secret: str) -> str:
    """Compute the base64 HMAC-SHA256 that Shopify sends in X-Shopify-Hmac-Sha256."""
    return base64.b64encode(hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()).decode("utf-8")


def _post_webhook(
    client: Client,
    topic: str,
    payload: dict,
    shop_domain: str = "test-shop.myshopify.com",
    webhook_id: str = "wh-unique-1",
    secret: str | None = None,
    hmac_override: str | None = None,
    omit_hmac: bool = False,
):
    """
    POST a webhook to the endpoint with the correct headers.
    If hmac_override is given, it replaces the computed HMAC.
    If omit_hmac is True, the X-Shopify-Hmac-Sha256 header is omitted entirely.
    """
    body = json.dumps(payload).encode("utf-8")
    if secret is None:
        secret = settings.SHOPIFY_API_SECRET

    headers = {
        "HTTP_X_SHOPIFY_TOPIC": topic,
        "HTTP_X_SHOPIFY_SHOP_DOMAIN": shop_domain,
        "HTTP_X_SHOPIFY_WEBHOOK_ID": webhook_id,
        "HTTP_X_SHOPIFY_API_VERSION": settings.SHOPIFY_API_VERSION,
    }

    if not omit_hmac:
        computed = _webhook_hmac(body, secret)
        headers["HTTP_X_SHOPIFY_HMAC_SHA256"] = hmac_override or computed

    return client.post(
        WEBHOOK_URL,
        data=body,
        content_type="application/json",
        **headers,
    )


# ---------------------------------------------------------------------------
# HMAC validation
# ---------------------------------------------------------------------------


class TestWebhookHMAC:
    """Wrong or missing HMAC must always return 401."""

    def test_missing_hmac_returns_401(self, client):
        response = _post_webhook(
            client,
            topic="app/uninstalled",
            payload={"shop_domain": "test.myshopify.com"},
            omit_hmac=True,
            webhook_id="hmac-missing-1",
        )
        assert response.status_code == 401

    def test_wrong_hmac_returns_401(self, client):
        response = _post_webhook(
            client,
            topic="app/uninstalled",
            payload={"shop_domain": "test.myshopify.com"},
            hmac_override="definitely-not-valid",
            webhook_id="hmac-wrong-1",
        )
        assert response.status_code == 401

    def test_wrong_hmac_on_compliance_topic_returns_401(self, client):
        """Compliance topics (customers/redact, etc.) also require valid HMAC."""
        for topic in ["customers/redact", "customers/data_request", "shop/redact"]:
            response = _post_webhook(
                client,
                topic=topic,
                payload={},
                hmac_override="bad",
                webhook_id=f"hmac-compliance-{topic}",
            )
            assert response.status_code == 401, f"Expected 401 for {topic} with bad HMAC"


class TestWebhookMethodNotAllowed:
    """The webhook endpoint only accepts POST."""

    def test_get_returns_405(self, client):
        response = client.get(WEBHOOK_URL)
        assert response.status_code == 405


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


class TestWebhookDeduplication:
    """Duplicate X-Shopify-Webhook-Id → 200, no second handler effect."""

    def test_duplicate_webhook_id_returns_200_no_second_effect(self, client):
        # Create a shop so app/uninstalled has something to act on
        shop = ShopifyShop.objects.create(
            shop_domain="dedup-shop.myshopify.com",
            access_token="acc_dedup",
            refresh_token="ref_dedup",
            scopes="read_products",
        )

        payload = {"shop_domain": "dedup-shop.myshopify.com"}

        # First delivery — should process
        response = _post_webhook(
            client,
            topic="app/uninstalled",
            payload=payload,
            shop_domain="dedup-shop.myshopify.com",
            webhook_id="dedup-test-1",
        )
        assert response.status_code == 200

        # Second delivery with the same webhook_id — still 200, but no second effect
        response = _post_webhook(
            client,
            topic="app/uninstalled",
            payload=payload,
            shop_domain="dedup-shop.myshopify.com",
            webhook_id="dedup-test-1",
        )
        assert response.status_code == 200

        # Only one delivery recorded
        assert ShopifyWebhookDelivery.objects.filter(webhook_id="dedup-test-1").count() == 1


# ---------------------------------------------------------------------------
# app/uninstalled
# ---------------------------------------------------------------------------


class TestAppUninstalled:
    """app/uninstalled wipes tokens, sets uninstalled_at, but keeps tenant."""

    def test_uninstalled_wipes_tokens_keeps_tenant(self, client):
        from apps.multitenancy.tests.factories import TenantFactory

        tenant = TenantFactory()
        shop = ShopifyShop.objects.create(
            shop_domain="uninstall-shop.myshopify.com",
            access_token="secret_access_token",
            refresh_token="secret_refresh_token",
            scopes="read_products",
            tenant=tenant,
        )

        payload = {"shop_domain": "uninstall-shop.myshopify.com"}
        response = _post_webhook(
            client,
            topic="app/uninstalled",
            payload=payload,
            shop_domain="uninstall-shop.myshopify.com",
            webhook_id="uninstall-1",
        )
        assert response.status_code == 200

        shop.refresh_from_db()
        # Tokens wiped
        assert shop.access_token_encrypted == ""
        assert shop.refresh_token_encrypted == ""
        # uninstalled_at set
        assert shop.uninstalled_at is not None
        # Tenant link kept (per plan decision D4 and section 2.8)
        assert shop.tenant_id == tenant.id


# ---------------------------------------------------------------------------
# shop/redact
# ---------------------------------------------------------------------------


class TestShopRedact:
    """
    shop/redact anonymizes the ShopifyShop row and redacts all delivery payloads
    for that shop (tombstone approach, per plan section 3.5).
    """

    def test_shop_redact_anonymizes_and_redacts_deliveries(self, client):
        shop = ShopifyShop.objects.create(
            shop_domain="redact-shop.myshopify.com",
            access_token="token_to_wipe",
            refresh_token="refresh_to_wipe",
            scopes="read_products",
        )

        # Pre-existing delivery for this shop (should be redacted)
        ShopifyWebhookDelivery.objects.create(
            webhook_id="earlier-delivery-1",
            topic="app/uninstalled",
            shop_domain="redact-shop.myshopify.com",
            payload={"some": "data"},
        )

        payload = {"shop_domain": "redact-shop.myshopify.com"}
        response = _post_webhook(
            client,
            topic="shop/redact",
            payload=payload,
            shop_domain="redact-shop.myshopify.com",
            webhook_id="redact-1",
        )
        assert response.status_code == 200

        shop.refresh_from_db()
        # Shop domain replaced with a hash (anonymized)
        assert shop.shop_domain != "redact-shop.myshopify.com"
        # Tokens wiped
        assert shop.access_token_encrypted == ""
        assert shop.refresh_token_encrypted == ""
        # Tenant nulled
        assert shop.tenant_id is None

        # All delivery payloads for the original shop domain are redacted to {}
        earlier = ShopifyWebhookDelivery.objects.get(webhook_id="earlier-delivery-1")
        assert earlier.payload == {}

        # The redact delivery's own payload is also redacted
        redact_delivery = ShopifyWebhookDelivery.objects.get(webhook_id="redact-1")
        assert redact_delivery.payload == {}


# ---------------------------------------------------------------------------
# customers/redact and customers/data_request
# ---------------------------------------------------------------------------


class TestCustomerComplianceWebhooks:
    """Both customers/* topics answer 200 and record the delivery."""

    def test_customers_redact_records_and_returns_200(self, client):
        payload = {
            "shop_domain": "customer-shop.myshopify.com",
            "customer": {"id": 123, "email": "customer@example.com"},
            "orders_to_redact": [456],
        }
        response = _post_webhook(
            client,
            topic="customers/redact",
            payload=payload,
            shop_domain="customer-shop.myshopify.com",
            webhook_id="cust-redact-1",
        )
        assert response.status_code == 200
        assert ShopifyWebhookDelivery.objects.filter(webhook_id="cust-redact-1").exists()

    def test_customers_data_request_records_and_returns_200(self, client):
        payload = {
            "shop_domain": "customer-shop.myshopify.com",
            "customer": {"id": 789, "email": "data@example.com"},
            "data_request": {"id": 1},
        }
        response = _post_webhook(
            client,
            topic="customers/data_request",
            payload=payload,
            shop_domain="customer-shop.myshopify.com",
            webhook_id="cust-data-1",
        )
        assert response.status_code == 200
        assert ShopifyWebhookDelivery.objects.filter(webhook_id="cust-data-1").exists()


# ---------------------------------------------------------------------------
# Unknown topic
# ---------------------------------------------------------------------------


class TestUnknownTopic:
    """An unknown topic is logged as a warning but still answered 200."""

    def test_unknown_topic_returns_200_and_logs_warning(self, client, caplog):
        payload = {"shop_domain": "unknown-shop.myshopify.com"}
        with caplog.at_level(logging.WARNING):
            response = _post_webhook(
                client,
                topic="orders/create",
                payload=payload,
                shop_domain="unknown-shop.myshopify.com",
                webhook_id="unknown-topic-1",
            )
        assert response.status_code == 200
        # The delivery is still recorded (for audit)
        assert ShopifyWebhookDelivery.objects.filter(webhook_id="unknown-topic-1").exists()
        # A warning was logged
        assert any("orders/create" in record.message for record in caplog.records)
