"""
Shopify webhook endpoint.

One URL for every topic. The view validates the HMAC, deduplicates by
X-Shopify-Webhook-Id, and dispatches to the matching handler either inline
(SHOPIFY_WEBHOOK_DISPATCH=sync) or via a Celery task (=celery). A repeated id whose handler never
succeeded is handled again (deliveries.py, WhatsApp plan Step 4.3e). For the order topics it stores and
hands over only the fields the app uses (payloads.py, WhatsApp plan Step 4.3b).

Shape inspired by the blog post's "one endpoint, topic → handler dict"
(plan section 0.2).
"""

import json
import logging

from django.conf import settings
from django.db import IntegrityError, transaction
from django.http import (
    HttpResponse,
    HttpResponseNotAllowed,
)
from django.views.decorators.csrf import csrf_exempt

from apps.shopify import deliveries, payloads
from apps.shopify.models import ShopifyWebhookDelivery
from apps.shopify.tasks import process_shopify_webhook
from apps.shopify.verification import verify_webhook_hmac

logger = logging.getLogger(__name__)

# The topic → handler map lives in deliveries.py (WhatsApp plan Step 4.3e), shared with the Celery task.


@csrf_exempt
def webhook_view(request):
    """
    POST /api/shopify/webhooks/

    Receives all Shopify webhook deliveries. Not rate-limited: Shopify retries
    on failure and we must always accept valid deliveries (plan section 3.7).
    """
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    # 1. HMAC of raw body (missing or wrong → 401, required for compliance topics)
    raw_body = request.body
    provided_hmac = request.META.get("HTTP_X_SHOPIFY_HMAC_SHA256")

    if not verify_webhook_hmac(raw_body, provided_hmac, settings.SHOPIFY_API_SECRET):
        return HttpResponse("HMAC verification failed.", status=401)

    # 2. Parse headers and body
    topic = request.META.get("HTTP_X_SHOPIFY_TOPIC", "")
    shop_domain = request.META.get("HTTP_X_SHOPIFY_SHOP_DOMAIN", "")
    webhook_id = request.META.get("HTTP_X_SHOPIFY_WEBHOOK_ID", "")

    try:
        payload = json.loads(raw_body) if raw_body else {}
    except (json.JSONDecodeError, ValueError):
        payload = {}

    # Only what the app uses is stored, and handed to the handler (payloads.py, WhatsApp plan Step 4.3b).
    payload = payloads.trim(topic, payload)

    # 3. Deduplicate by X-Shopify-Webhook-Id (plan section 1.5).
    #    An IntegrityError on webhook_id means we've already received this delivery.
    #    The savepoint (transaction.atomic) is needed because Postgres aborts the whole
    #    transaction on any error; without it the IntegrityError poisons subsequent queries.
    try:
        with transaction.atomic():
            delivery = ShopifyWebhookDelivery.objects.create(
                webhook_id=webhook_id,
                topic=topic,
                shop_domain=shop_domain,
                payload=payload,
            )
    except IntegrityError:
        delivery = ShopifyWebhookDelivery.objects.get(webhook_id=webhook_id)
        if delivery.handled_at is not None:
            # Already handled — return 200 so Shopify doesn't retry.
            return HttpResponse(status=200)
        # Received before, but its handler never succeeded (WhatsApp plan Step 4.3e): handle it now.

    # 4. Dispatch the handler
    dispatch = getattr(settings, "SHOPIFY_WEBHOOK_DISPATCH", "sync")

    # Without a worker (CELERY_TASK_ALWAYS_EAGER), the task would run inside this request with its
    # retries ignored, and a failure would still answer 200; handling inline instead answers with an
    # error, so Shopify retries (WhatsApp plan Step 4.3e, agents.md section 4.1).
    queue = dispatch == "celery" and not settings.CELERY_TASK_ALWAYS_EAGER
    if queue and topic in deliveries.TOPIC_HANDLERS:
        # Enqueue the handler for async processing; return 200 immediately.
        try:
            process_shopify_webhook.delay(delivery.id)
        except Exception:
            # The queue is down. The delivery stays unhandled, and Shopify's retry queues it again.
            logger.exception("Shopify webhook %s (%s) couldn't be queued; Shopify will retry it.", webhook_id, topic)
            return HttpResponse("The webhook couldn't be queued; please retry.", status=500)
        return HttpResponse(status=200)

    # Default: run the handler inline in the web request. A topic with no handler is only marked
    # handled, so Shopify doesn't retry something we'll never handle.
    try:
        deliveries.handle(delivery)
    except Exception:
        # Any answer but 2xx makes Shopify send the delivery again; it's still unhandled, so that try
        # runs the handler again (WhatsApp plan Step 4.3e).
        logger.exception(
            "Shopify webhook %s (%s) from '%s' failed; Shopify will retry it.", webhook_id, topic, shop_domain
        )
        return HttpResponse("The webhook couldn't be handled; please retry.", status=500)

    return HttpResponse(status=200)
