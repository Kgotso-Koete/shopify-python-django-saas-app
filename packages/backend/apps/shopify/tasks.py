"""
Celery tasks for the Shopify app.

Used when SHOPIFY_WEBHOOK_DISPATCH=celery: the webhook view records the delivery,
returns 200 immediately, and enqueues process_shopify_webhook to run the handler
asynchronously (plan section 3.6).
"""

import logging

from config.celery import app as celery_app

from apps.shopify.constants import (
    TOPIC_APP_UNINSTALLED,
    TOPIC_CUSTOMERS_DATA_REQUEST,
    TOPIC_CUSTOMERS_REDACT,
    TOPIC_SHOP_REDACT,
)
from apps.shopify.services import (
    handle_customers_data_request,
    handle_customers_redact,
    handle_shop_redact,
    handle_uninstalled,
)

logger = logging.getLogger(__name__)

# Same mapping as webhooks.py's TOPIC_HANDLERS — duplicated here so the task
# module is self-contained and doesn't import from webhooks.py (which would
# create a circular import since webhooks.py imports from tasks.py).
TOPIC_HANDLERS = {
    TOPIC_APP_UNINSTALLED: handle_uninstalled,
    TOPIC_SHOP_REDACT: handle_shop_redact,
    TOPIC_CUSTOMERS_REDACT: handle_customers_redact,
    TOPIC_CUSTOMERS_DATA_REQUEST: handle_customers_data_request,
}


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def process_shopify_webhook(self, webhook_delivery_id: int) -> None:
    """
    Process a Shopify webhook asynchronously.
    Called when SHOPIFY_WEBHOOK_DISPATCH=celery.

    Loads the delivery row, looks up the handler by topic, and calls it.
    """
    from apps.shopify.models import ShopifyWebhookDelivery

    try:
        delivery = ShopifyWebhookDelivery.objects.get(id=webhook_delivery_id)
    except ShopifyWebhookDelivery.DoesNotExist:
        logger.warning(
            "ShopifyWebhookDelivery with id=%s not found; skipping.",
            webhook_delivery_id,
        )
        return

    handler = TOPIC_HANDLERS.get(delivery.topic)
    if handler:
        handler(delivery.shop_domain, delivery.payload)
