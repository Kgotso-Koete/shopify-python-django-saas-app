"""
Shopify webhook endpoint.

One URL for every topic. The view validates the HMAC, deduplicates by
X-Shopify-Webhook-Id, and dispatches to the matching handler either inline
(SHOPIFY_WEBHOOK_DISPATCH=sync) or via a Celery task (=celery).

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

from apps.shopify.constants import (
    TOPIC_APP_UNINSTALLED,
    TOPIC_CUSTOMERS_DATA_REQUEST,
    TOPIC_CUSTOMERS_REDACT,
    TOPIC_SHOP_REDACT,
)
from apps.shopify.models import ShopifyWebhookDelivery
from apps.shopify.services import (
    handle_customers_data_request,
    handle_customers_redact,
    handle_shop_redact,
    handle_uninstalled,
)
from apps.shopify.tasks import process_shopify_webhook
from apps.shopify.verification import verify_webhook_hmac

logger = logging.getLogger(__name__)

# Topic → handler function mapping (plan section 3.5).
# Each handler receives (shop_domain: str, payload: dict) and does quick DB work
# that fits inside Shopify's 5-second webhook timeout.
TOPIC_HANDLERS = {
    TOPIC_APP_UNINSTALLED: handle_uninstalled,
    TOPIC_SHOP_REDACT: handle_shop_redact,
    TOPIC_CUSTOMERS_REDACT: handle_customers_redact,
    TOPIC_CUSTOMERS_DATA_REQUEST: handle_customers_data_request,
}


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

    # 3. Deduplicate by X-Shopify-Webhook-Id (plan section 1.5).
    #    An IntegrityError on webhook_id means we've already processed this delivery.
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
        # Duplicate delivery — return 200 so Shopify doesn't retry.
        return HttpResponse(status=200)

    # 4. Dispatch the handler
    handler = TOPIC_HANDLERS.get(topic)

    if handler is None:
        # Unknown topic: log a warning but still answer 200 so Shopify
        # doesn't retry something we'll never handle.
        logger.warning("Received webhook for unknown topic '%s' from shop '%s'.", topic, shop_domain)
        return HttpResponse(status=200)

    dispatch = getattr(settings, "SHOPIFY_WEBHOOK_DISPATCH", "sync")

    if dispatch == "celery":
        # Enqueue the handler for async processing; return 200 immediately.
        process_shopify_webhook.delay(delivery.id)
    else:
        # Default: run the handler inline in the web request.
        handler(shop_domain, payload)

    return HttpResponse(status=200)
