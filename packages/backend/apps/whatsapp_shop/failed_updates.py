"""
Order updates WhatsApp couldn't deliver, and sending them again (WhatsApp plan Step 4.7, user story
WA.D3.OM.J2.A3, decided 2026-11-08), for the WhatsApp page.

- **Failed:** an order stage whose message is FAILED (a cause a person must fix, or a passing one that lasted
  past the send queue's hour, user story WA.D5.SY.J1.A1) or CANCELLED (it waited behind a message that
  failed). A "received" overtaken by "paid" isn't listed: "paid" says more.
- **Meta's reason in plain words,** from the message's error code.
- **Send again** asks Shopify for the order by its id and builds the update fresh (orders.stage_messages):
  a normal message while the customer's 24-hour window is open, otherwise the stage's template, since
  someone often fixes the cause hours later. The app keeps only the order's id (decision 4), so a store to
  reconnect, Shopify unreachable, or an order Shopify no longer has, is refused with the reason.

The organization and its permission are checked by the caller (schema.py).
"""

import logging
from dataclasses import dataclass

import requests
from django.db import models, transaction
from django.db.models import Q

from apps.shopify.client import ShopifyAPIError, ShopifyAuthError
from apps.shopify.orders import order_details
from apps.shopify.products import ShopifyReconnectRequired, ShopifyTryAgainLater
from apps.whatsapp.client import RETRYABLE_ERROR_CODES, TOKEN_REJECTED_ERROR_CODE, WINDOW_CLOSED_ERROR_CODE
from apps.whatsapp.constants import MessageStatus
from apps.whatsapp.services import outbox

from .models import StoreCheckout
from .orders import stage_messages

logger = logging.getLogger(__name__)

FAILED_STATUSES = (MessageStatus.FAILED, MessageStatus.CANCELLED)
# Meta's "message undeliverable": the phone isn't on WhatsApp, or its app can't take the message.
UNDELIVERABLE_ERROR_CODE = 131026


class OrderStage(models.TextChoices):
    """Which of an order's updates (decision 3); each value is its member's name (agents.md section 5.3b)."""

    RECEIVED = "RECEIVED", "Order received"
    PAID = "PAID", "Order paid"


class FailedUpdateError(Exception):
    """Send again refused, with the reason for the page and a `code` for the web app."""

    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class FailedUpdate:
    checkout: StoreCheckout
    stage: OrderStage
    message: object

    @property
    def reason(self) -> str:
        return reason_for(self.message)


def failed_updates(tenant) -> list[FailedUpdate]:
    """The organization's order stages whose message failed, the latest failure first."""
    checkouts = (
        StoreCheckout.objects.filter(store_customer__tenant=tenant)
        .filter(
            Q(paid_message__status__in=FAILED_STATUSES)
            | Q(received_message__status__in=FAILED_STATUSES, paid_message__isnull=True)
        )
        .select_related("received_message", "paid_message", "store_customer__contact__account")
    )
    updates = []
    for checkout in checkouts:
        if checkout.paid_message is not None:
            updates.append(FailedUpdate(checkout, OrderStage.PAID, checkout.paid_message))
        else:
            updates.append(FailedUpdate(checkout, OrderStage.RECEIVED, checkout.received_message))
    return sorted(updates, key=lambda update: update.message.updated_at, reverse=True)


def send_again(tenant, checkout_id, stage: str) -> StoreCheckout:
    """
    Send the organization's failed order update again, built fresh from the order Shopify has now; the stage
    keeps the new message. Raises FailedUpdateError with the reason when it can't.
    """
    paid = stage == OrderStage.PAID
    pk = _pk(checkout_id)
    with transaction.atomic():
        checkout = None
        if pk is not None:
            checkout = (
                StoreCheckout.objects.select_for_update(of=("self",))
                .select_related("shop", "store_customer__contact__account", "received_message", "paid_message")
                .filter(pk=pk, store_customer__tenant=tenant)
                .first()
            )
        if checkout is None:
            raise FailedUpdateError("That order update was not found.", "not_found")
        message = checkout.stage_message(paid=paid)
        overtaken = not paid and checkout.paid_message_id is not None
        if message is None or message.status not in FAILED_STATUSES or overtaken:
            raise FailedUpdateError("That order update didn't fail, so there's nothing to send again.", "not_failed")

        details = _order_from_shopify(checkout)
        contact = checkout.store_customer.contact
        messages = stage_messages(checkout, contact, details, paid=paid, details=details)
        stage_field = "paid_message" if paid else "received_message"
        setattr(checkout, stage_field, outbox.queue_messages(contact, messages)[0])
        checkout.save(update_fields=[stage_field, "updated_at"])
    return checkout


def reason_for(message) -> str:
    """Why Meta didn't deliver the message, in plain words, from its error code."""
    code = message.error_code
    if message.status == MessageStatus.CANCELLED:
        return "It was waiting behind another message to this customer that failed, so it wasn't sent."
    if code == TOKEN_REJECTED_ERROR_CODE:
        return (
            "Meta rejected the number's access token: it expired or was revoked. Connect the number again with a "
            "new token, then send this again."
        )
    if code is not None and 132000 <= code < 133000:
        return (
            "Meta hasn't approved the order template, or refused it. Its status is shown with the number; send "
            "this again once it's approved."
        )
    if code == WINDOW_CLOSED_ERROR_CODE:
        return "More than 24 hours had passed since the customer's last message, so only a template could be sent."
    if code == UNDELIVERABLE_ERROR_CODE:
        return (
            "WhatsApp couldn't deliver it to the customer's phone: the number may not be on WhatsApp, or their "
            "app may need updating."
        )
    if code is None or code in RETRYABLE_ERROR_CODES:
        return "Meta couldn't be reached, or stayed busy, for an hour of retries."
    return f"Meta refused it with error {code}; Meta's error codes page explains it."


def _order_from_shopify(checkout: StoreCheckout) -> dict:
    """The order's details as Shopify has them now (agents.md section 5.3d), or the reason they can't be had."""
    try:
        order = order_details(checkout.shop, checkout.order_id)
    except ShopifyReconnectRequired as error:
        raise FailedUpdateError(
            "The store must be reconnected on the Shopify page before this update can be sent.", "reconnect"
        ) from error
    except (ShopifyTryAgainLater, ShopifyAPIError, ShopifyAuthError, requests.RequestException) as error:
        # Ids and the error's kind only: Shopify's reply may hold the order's details.
        logger.warning("Checkout id=%s: Shopify's order couldn't be had (%s).", checkout.pk, type(error).__name__)
        raise FailedUpdateError("Shopify couldn't be reached just now. Please try again in a minute.", "try_again")
    if order is None:
        raise FailedUpdateError("Shopify no longer has this order, so its update can't be sent.", "order_gone")
    return order


def _pk(checkout_id):
    try:
        return int(checkout_id)
    except (TypeError, ValueError):
        return None
