"""
Tests for the Shopify Celery task: process_shopify_webhook.

Covers:
- The task calls the correct handler from deliveries.TOPIC_HANDLERS
- A missing delivery row is logged and doesn't crash

Kind of test: integration (agents.md section 2.5). Why: the task runs against delivery rows in the
test database; only one test patches the topic handlers.
"""

import pytest
from unittest.mock import patch, MagicMock

from apps.shopify.models import ShopifyWebhookDelivery

pytestmark = [pytest.mark.django_db, pytest.mark.story("WA.D7.SY.J1.A1")]


class TestProcessShopifyWebhookTask:
    """Test the process_shopify_webhook Celery task."""

    def test_task_calls_handler_for_known_topic(self):
        """The task loads the delivery, looks up the handler, and calls it."""
        from apps.shopify.tasks import process_shopify_webhook

        # Create a delivery row that the task will load
        delivery = ShopifyWebhookDelivery.objects.create(
            webhook_id="task-test-1",
            topic="app/uninstalled",
            shop_domain="task-shop.myshopify.com",
            payload={"shop_domain": "task-shop.myshopify.com"},
        )

        # Patch the handler so we can verify it's called without side effects. The map lives in
        # deliveries.py since WhatsApp plan Step 4.3e, shared with the webhook view.
        mock_handler = MagicMock()
        with patch.dict("apps.shopify.deliveries.TOPIC_HANDLERS", {"app/uninstalled": mock_handler}):
            process_shopify_webhook(delivery.id)

            mock_handler.assert_called_once_with(
                "task-shop.myshopify.com",
                {"shop_domain": "task-shop.myshopify.com"},
            )

    def test_task_does_not_crash_on_missing_delivery(self, caplog):
        """If the delivery row doesn't exist (deleted between enqueue and execution), log and return."""
        from apps.shopify.tasks import process_shopify_webhook
        import logging

        with caplog.at_level(logging.WARNING):
            # Should not raise
            process_shopify_webhook(999999)

        # A warning was logged about the missing delivery
        assert any("999999" in record.message for record in caplog.records)

    def test_task_skips_unknown_topic(self):
        """If the topic has no handler, the task returns without crashing."""
        from apps.shopify.tasks import process_shopify_webhook

        delivery = ShopifyWebhookDelivery.objects.create(
            webhook_id="task-unknown-1",
            topic="some/unknown_topic",
            shop_domain="task-shop.myshopify.com",
            payload={},
        )

        # Should not raise
        process_shopify_webhook(delivery.id)
