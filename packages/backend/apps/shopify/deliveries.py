"""
Handling a stored Shopify webhook delivery (WhatsApp plan Step 4.3e; section 14, open question 10).

The one place that maps a topic to its handler, used by the webhook view with sync dispatch and by
the Celery task with Celery dispatch. A delivery is marked handled in the same transaction as its
handler's work: if the handler fails, both are undone, the delivery stays unhandled, and its next
try runs the handler again. Each handler receives (shop_domain: str, payload: dict).
"""

import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.shopify.emails import ShopifyWebhooksUnhandledEmail

from apps.shopify.constants import (
    TOPIC_APP_UNINSTALLED,
    TOPIC_CUSTOMERS_DATA_REQUEST,
    TOPIC_CUSTOMERS_REDACT,
    TOPIC_ORDERS_CREATE,
    TOPIC_ORDERS_PAID,
    TOPIC_SHOP_REDACT,
)
from apps.shopify.models import ShopifyWebhookDelivery
from apps.shopify.services import (
    handle_customers_data_request,
    handle_customers_redact,
    handle_orders_create,
    handle_orders_paid,
    handle_shop_redact,
    handle_uninstalled,
)

logger = logging.getLogger(__name__)

# Topic → handler (Shopify plan section 3.5). Each does quick database work that fits inside
# Shopify's 5-second webhook timeout.
TOPIC_HANDLERS = {
    TOPIC_APP_UNINSTALLED: handle_uninstalled,
    TOPIC_SHOP_REDACT: handle_shop_redact,
    TOPIC_CUSTOMERS_REDACT: handle_customers_redact,
    TOPIC_CUSTOMERS_DATA_REQUEST: handle_customers_data_request,
    TOPIC_ORDERS_CREATE: handle_orders_create,
    TOPIC_ORDERS_PAID: handle_orders_paid,
}

# The sweep (handle_pending) takes a delivery left unhandled for longer than PENDING_AFTER, past the
# Celery task's retries (about half an hour, tasks.py), and gives up on one older than GIVE_UP_AFTER,
# past Shopify's own retries (48 hours), leaving it in the admin for a person to look at.
PENDING_AFTER = timedelta(minutes=45)
GIVE_UP_AFTER = timedelta(days=3)


def handle(delivery: ShopifyWebhookDelivery) -> None:
    """
    Run the delivery's handler, unless it's already handled, and mark it handled. A handler's error
    propagates, with its work and the mark undone. A topic with no handler is only marked handled, so
    nothing tries it again.
    """
    with transaction.atomic():
        # The row lock makes two tries at once (a Shopify retry while the first is still running, or the
        # sweep) run the handler once: the second waits, then sees it handled.
        row = ShopifyWebhookDelivery.objects.select_for_update().get(pk=delivery.pk)
        if row.handled_at is not None:
            return
        handler = TOPIC_HANDLERS.get(row.topic)
        if handler is None:
            logger.warning("Received webhook for unknown topic '%s' from shop '%s'.", row.topic, row.shop_domain)
        else:
            handler(row.shop_domain, row.payload)
        row.handled_at = timezone.now()
        row.save(update_fields=["handled_at", "updated_at"])
    delivery.handled_at = row.handled_at


def try_to_handle(delivery: ShopifyWebhookDelivery) -> bool:
    """
    Handle the delivery, keeping a failure's error on it for the operator instead of raising (user story
    WA.D7.OP.J2.A2); True when it's handled. Used by the sweep and by the admin's Handle again.
    """
    try:
        handle(delivery)
    except Exception as error:
        logger.warning(
            "Shopify webhook %s (%s) from '%s' still fails.",
            delivery.webhook_id,
            delivery.topic,
            delivery.shop_domain,
            exc_info=True,
        )
        # handle()'s transaction was undone, so the error is saved on its own.
        ShopifyWebhookDelivery.objects.filter(pk=delivery.pk).update(last_error=f"{type(error).__name__}: {error}")
        return False
    return True


def handle_pending() -> dict:
    """
    Handle the deliveries left unhandled between PENDING_AFTER and GIVE_UP_AFTER, oldest first. A
    failure is logged, kept on the delivery and counted, and the sweep goes on. Then the operator is emailed
    once about those it gave up on (report_given_up). Run by the shopify_handle_pending_deliveries command
    (cron, no worker needed) and by the beat task (agents.md section 4.1).
    """
    now = timezone.now()
    pending = ShopifyWebhookDelivery.objects.filter(
        handled_at__isnull=True,
        created_at__lte=now - PENDING_AFTER,
        created_at__gt=now - GIVE_UP_AFTER,
    ).order_by("created_at", "pk")
    counts = {"handled": 0, "failed": 0}
    for delivery in pending:
        counts["handled" if try_to_handle(delivery) else "failed"] += 1
    report_given_up(now)
    return counts


def report_given_up(now) -> None:
    """
    Email the operator, once, the deliveries still unhandled past GIVE_UP_AFTER that no email has named yet
    (user story WA.D7.OP.J2.A2). With no OPERATOR_EMAILS nothing is sent, and nothing is marked, so they're
    reported once an address is set.
    """
    if not settings.OPERATOR_EMAILS:
        return
    given_up = list(
        ShopifyWebhookDelivery.objects.filter(
            handled_at__isnull=True, reported_at__isnull=True, created_at__lte=now - GIVE_UP_AFTER
        ).order_by("created_at", "pk")
    )
    if not given_up:
        return
    ShopifyWebhooksUnhandledEmail(
        to=list(settings.OPERATOR_EMAILS),
        data={
            "deliveries": [
                {
                    "webhook_id": delivery.webhook_id,
                    "topic": delivery.topic,
                    "shop_domain": delivery.shop_domain,
                    "received_at": delivery.created_at,
                    "last_error": delivery.last_error,
                }
                for delivery in given_up
            ]
        },
    ).send()
    ShopifyWebhookDelivery.objects.filter(pk__in=[delivery.pk for delivery in given_up]).update(reported_at=now)
