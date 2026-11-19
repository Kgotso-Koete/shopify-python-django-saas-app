"""
Celery tasks for the Shopify app.

Used when SHOPIFY_WEBHOOK_DISPATCH=celery: the webhook view records the delivery,
returns 200 immediately, and enqueues process_shopify_webhook to run the handler
asynchronously (plan section 3.6).

The handler runs through deliveries.handle, the one place that maps topics to handlers and marks a
delivery handled (WhatsApp plan Step 4.3e). A failure is retried with a growing delay; after the last
retry the delivery stays unhandled, for the sweep. Without a worker (CELERY_TASK_ALWAYS_EAGER) the
view never queues this task: it handles inline, so Shopify does the retrying (agents.md section 4.1).
"""

import logging

from config.celery import app as celery_app

logger = logging.getLogger(__name__)

# Retries wait 1, 2, 4, 8 and 16 minutes: about half an hour in all, before the sweep takes over.
MAX_RETRIES = 5
RETRY_DELAY_SECONDS = 60


@celery_app.task(bind=True, max_retries=MAX_RETRIES)
def process_shopify_webhook(self, webhook_delivery_id: int) -> None:
    """
    Process a Shopify webhook asynchronously.
    Called when SHOPIFY_WEBHOOK_DISPATCH=celery.

    Loads the delivery row and hands it to deliveries.handle, which runs its handler once.
    """
    from apps.shopify import deliveries
    from apps.shopify.models import ShopifyWebhookDelivery

    delivery = ShopifyWebhookDelivery.objects.filter(id=webhook_delivery_id).first()
    if delivery is None:
        logger.warning(
            "ShopifyWebhookDelivery with id=%s not found; skipping.",
            webhook_delivery_id,
        )
        return

    try:
        deliveries.handle(delivery)
    except Exception as error:
        if self.request.retries >= MAX_RETRIES:
            logger.warning(
                "Shopify webhook %s (%s) failed after every retry; left unhandled for the sweep.",
                delivery.webhook_id,
                delivery.topic,
            )
            return
        raise self.retry(exc=error, countdown=RETRY_DELAY_SECONDS * 2**self.request.retries)


@celery_app.task
def handle_pending_deliveries() -> dict:
    """
    The sweep for deliveries left unhandled (deliveries.handle_pending), scheduled by beat every 15
    minutes when Shopify is enabled. Without a worker, cron runs the shopify_handle_pending_deliveries
    command instead.
    """
    from apps.shopify import deliveries

    return deliveries.handle_pending()
