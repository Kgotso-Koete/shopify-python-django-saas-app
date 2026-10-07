"""
Tests for webhook dispatch mode (sync vs celery).

With SHOPIFY_WEBHOOK_DISPATCH=sync, the handler runs inline in the web request.
With SHOPIFY_WEBHOOK_DISPATCH=celery, the handler is enqueued as a Celery task
and the view returns 200 immediately.
"""

import base64
import hashlib
import hmac
import json

import pytest
from django.conf import settings
from django.test import Client
from unittest.mock import patch

from apps.shopify.models import ShopifyShop, ShopifyWebhookDelivery

pytestmark = pytest.mark.django_db

WEBHOOK_URL = "/api/shopify/webhooks/"


def _webhook_hmac(body: bytes, secret: str) -> str:
    """Compute the base64 HMAC-SHA256 that Shopify sends in X-Shopify-Hmac-Sha256."""
    return base64.b64encode(hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()).decode("utf-8")


def _post_webhook(client, topic, payload, shop_domain, webhook_id):
    """POST a valid webhook to the endpoint."""
    body = json.dumps(payload).encode("utf-8")
    computed_hmac = _webhook_hmac(body, settings.SHOPIFY_API_SECRET)

    return client.post(
        WEBHOOK_URL,
        data=body,
        content_type="application/json",
        HTTP_X_SHOPIFY_TOPIC=topic,
        HTTP_X_SHOPIFY_SHOP_DOMAIN=shop_domain,
        HTTP_X_SHOPIFY_WEBHOOK_ID=webhook_id,
        HTTP_X_SHOPIFY_API_VERSION=settings.SHOPIFY_API_VERSION,
        HTTP_X_SHOPIFY_HMAC_SHA256=computed_hmac,
    )


class TestSyncDispatch:
    """When SHOPIFY_WEBHOOK_DISPATCH=sync, handlers run inline."""

    def test_sync_dispatch_calls_handler_inline(self, client, monkeypatch):
        """With sync dispatch, the handler is called directly in the view, not via Celery."""
        monkeypatch.setattr(settings, "SHOPIFY_WEBHOOK_DISPATCH", "sync")

        # Create a shop for app/uninstalled to act on
        ShopifyShop.objects.create(
            shop_domain="sync-shop.myshopify.com",
            access_token="acc_sync",
            refresh_token="ref_sync",
            scopes="read_products",
        )

        # Patch the Celery task to make sure it is NOT called
        with patch("apps.shopify.webhooks.process_shopify_webhook") as mock_task:
            response = _post_webhook(
                client,
                topic="app/uninstalled",
                payload={"shop_domain": "sync-shop.myshopify.com"},
                shop_domain="sync-shop.myshopify.com",
                webhook_id="dispatch-sync-1",
            )
            assert response.status_code == 200
            # The Celery task was NOT called (sync mode runs the handler inline)
            mock_task.delay.assert_not_called()

        # The handler ran inline: tokens are wiped
        shop = ShopifyShop.objects.get(shop_domain="sync-shop.myshopify.com")
        assert shop.access_token_encrypted == ""
        assert shop.uninstalled_at is not None


class TestCeleryDispatch:
    """When SHOPIFY_WEBHOOK_DISPATCH=celery, handlers are enqueued."""

    def test_celery_dispatch_enqueues_task(self, client, monkeypatch):
        """With celery dispatch, the view returns 200 immediately and enqueues the task."""
        monkeypatch.setattr(settings, "SHOPIFY_WEBHOOK_DISPATCH", "celery")

        ShopifyShop.objects.create(
            shop_domain="celery-shop.myshopify.com",
            access_token="acc_celery",
            refresh_token="ref_celery",
            scopes="read_products",
        )

        with patch("apps.shopify.webhooks.process_shopify_webhook") as mock_task:
            response = _post_webhook(
                client,
                topic="app/uninstalled",
                payload={"shop_domain": "celery-shop.myshopify.com"},
                shop_domain="celery-shop.myshopify.com",
                webhook_id="dispatch-celery-1",
            )
            assert response.status_code == 200

            # The delivery was recorded
            delivery = ShopifyWebhookDelivery.objects.get(webhook_id="dispatch-celery-1")

            # The Celery task WAS called with the delivery id
            mock_task.delay.assert_called_once_with(delivery.id)

        # The handler did NOT run inline: tokens are still present
        shop = ShopifyShop.objects.get(shop_domain="celery-shop.myshopify.com")
        assert shop.access_token_encrypted != ""
