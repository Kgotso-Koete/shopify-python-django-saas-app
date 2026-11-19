"""
Order updates on WhatsApp (plan phase 4, Step 4.3c, decisions 3, 4, 5, 7 and 21; user story WA.D5.SC.J1.A2):
receivers of apps.shopify's order_created and order_paid, connected in apps.py.

- **The order finds its chat** by the cart's `_whatsapp_checkout` code (checkouts.py), among the
  checkouts of the store that sent it. An order without a code, with an unknown one, or another
  store's, is not this app's.
- **One order per code:** the first order a code arrives on is kept on its checkout; a later order
  carrying the same code (decision 21: the code stays on the browser's cart) is ignored.
- **"Received, awaiting payment", then "paid"** (decision 3): orders/create of an unpaid order (EFT and
  other manual methods) sends the first, orders/paid the second, and an order paid at once gets only
  "paid". Each stage is queued at most once, however often or in whatever order Shopify sends its
  webhooks: the checkout's row is locked while it's decided, and the stage's message is kept on it.
- **A stage counts as sent only once Meta accepts its message** (Step 4.7, user story WA.D5.SY.J1.A1): a
  passing failure is retried for up to an hour by the send queue, and without a worker these webhooks run
  its sweep too; a message that still fails is on the business's list to send again (WA.D3.OM.J2.A3).
- **The chat forgets the cart** (decision 7) when its order arrives, if it's still the customer's open
  cart, so the next Add to cart starts a new cart with a new code. Done on either webhook, since
  Shopify doesn't promise their order.
- **Within the 24-hour window, a normal message** (decision 6) with the order's details as Shopify has them when
  it's sent (Step 4.7, decision 30; agents.md section 5.3d): its items, total, and payment and delivery status,
  asked of the Admin API at protected customer data level 1. When Shopify can't be asked (busy, a store to
  reconnect, an order without its id), the message says what the webhook carries, the number and total, so the
  customer still hears.
- **After the window, the one update template** (templates.py, decision 30), the last resort: the store and the
  order number, with an Order details quick-reply button, whose tap brings the customer back into the window
  for the details (menus.py). Until Meta approves it, Meta refuses the message and it's recorded as failed with
  Meta's code.

The checkout keeps only the order's id and each stage's message (decision 4); the details are never stored, and
no link to the order is made (decision 30 replaced decision 23's View order link).
"""

import logging
from decimal import Decimal, InvalidOperation

import requests
from django.db import transaction
from django.utils import timezone

from apps.shopify.client import ShopifyAPIError, ShopifyAuthError
from apps.shopify.orders import order_details
from apps.shopify.products import ShopifyReconnectRequired, ShopifyTryAgainLater
from apps.whatsapp.builders import text_reply
from apps.whatsapp.services import outbox, window

from .checkouts import CHECKOUT_ATTRIBUTE
from .models import StoreCheckout, StoreCustomer
from .templates import order_template

logger = logging.getLogger(__name__)

# Shopify's financial_status of an order that is paid in full.
PAID = "paid"
# An order's lines listed in one message; a longer order says how many more it holds.
LINES_SHOWN = 10

# Shopify's display statuses in plain words; one not listed shows as Shopify names it, more readably.
# https://shopify.dev/docs/api/admin-graphql/latest/enums/OrderDisplayFinancialStatus
PAYMENT_WORDS = {
    "PENDING": "Awaiting payment",
    "AUTHORIZED": "Authorized",
    "PAID": "Paid",
    "PARTIALLY_PAID": "Partly paid",
    "PARTIALLY_REFUNDED": "Partly refunded",
    "REFUNDED": "Refunded",
    "VOIDED": "Voided",
    "EXPIRED": "Expired",
}
# https://shopify.dev/docs/api/admin-graphql/latest/enums/OrderDisplayFulfillmentStatus
DELIVERY_WORDS = {
    "UNFULFILLED": "Not shipped yet",
    "OPEN": "Not shipped yet",
    "IN_PROGRESS": "Being prepared",
    "SCHEDULED": "Scheduled",
    "ON_HOLD": "On hold",
    "PENDING_FULFILLMENT": "Being prepared",
    "PARTIALLY_FULFILLED": "Partly shipped",
    "FULFILLED": "Shipped",
    "RESTOCKED": "Restocked",
}
SHOPIFY_FAILURES = (ShopifyReconnectRequired, ShopifyTryAgainLater, ShopifyAPIError, ShopifyAuthError)
NOT_AVAILABLE_TEXT = "That order isn't available any more. Send *menu* for the main menu."
# The same words the store's menus use when Shopify can't be reached (menus.py).
UNREACHABLE_TEXT = "The shop can't be reached right now. Please try again in a few minutes."


def on_order_created(sender, shop, order, **kwargs):
    _update(shop, order, paid=order.get("financial_status") == PAID)
    _sweep_once_committed()


def on_order_paid(sender, shop, order, **kwargs):
    _update(shop, order, paid=True)
    _sweep_once_committed()


def _sweep_once_committed() -> None:
    """
    Without a worker, Shopify's order webhooks also retry messages a passing failure left queued (Step 4.7,
    user story WA.D5.SY.J1.A1), once their own work is committed; with a worker, this does nothing.
    """
    transaction.on_commit(outbox.sweep_if_due)


@transaction.atomic
def _update(shop, order: dict, *, paid: bool) -> None:
    code = _code(order)
    if not code:
        return
    checkout = (
        StoreCheckout.objects.select_for_update(of=("self",))
        .select_related("store_customer__contact")
        .filter(code=code, shop=shop)
        .first()
    )
    if checkout is None:
        return
    order_id = order.get("id")
    if checkout.order_id is not None and checkout.order_id != order_id:
        logger.info("Order id=%s carries checkout id=%s's code, already used; ignored.", order_id, checkout.pk)
        return
    checkout.order_id = order_id
    _forget_cart(checkout)

    # A stage with a message is under way: queued, sent, or failed and on the business's list to send
    # again (Step 4.7, user stories WA.D5.SY.J1.A1 and WA.D3.OM.J2.A3), so a retried webhook queues nothing.
    # "Received" is never sent after "paid".
    stage_field = "paid_message" if paid else "received_message"
    already_queued = checkout.paid_message_id is not None or getattr(checkout, f"{stage_field}_id") is not None
    contact = checkout.store_customer.contact
    if not already_queued:
        messages = stage_messages(checkout, contact, order, paid=paid)
        # The stage's own message is the first; it counts as sent once Meta accepts it.
        setattr(checkout, stage_field, outbox.queue_messages(contact, messages)[0])
    checkout.save(update_fields=["order_id", "received_message", "paid_message", "updated_at"])


def stage_messages(checkout: StoreCheckout, contact, order: dict, *, paid: bool, details: dict | None = None) -> list:
    """
    The stage's update as it should go now: while the customer's 24-hour window is open, a normal message with
    the order's details, asked of Shopify unless `details` already holds them (Send again, failed_updates.py,
    asks first); otherwise the update template. `order` is what the webhook carries, said when Shopify can't be
    asked.
    """
    if not window.is_open(contact):
        return [_template(checkout, contact, order)]
    if details is None and checkout.order_id is not None:
        details = live_details(checkout)
    headline = _headline(order.get("name") or (details or {}).get("name") or "", paid=paid)
    if details is None:
        return text_reply(f"{headline}{_total(order)}")
    return text_reply(details_text(headline, details))


def details_reply(contact, code: str) -> list[dict]:
    """
    The answer to a tap on the update template's Order details button (Step 4.7, decision 30): the order of the
    contact's own checkout `code`, as Shopify has it now. Another customer's code, an unknown one, a checkout
    with no order yet and an order Shopify no longer has all get the same answer, so nobody learns which exist.
    """
    checkout = StoreCheckout.objects.select_related("shop").filter(code=code, store_customer__contact=contact).first()
    if checkout is None or checkout.order_id is None:
        return text_reply(NOT_AVAILABLE_TEXT)
    try:
        details = order_details(checkout.shop, checkout.order_id)
    except (*SHOPIFY_FAILURES, requests.RequestException) as error:
        logger.warning("Checkout id=%s: Shopify's order couldn't be had (%s).", checkout.pk, type(error).__name__)
        return text_reply(UNREACHABLE_TEXT)
    if details is None:
        return text_reply(NOT_AVAILABLE_TEXT)
    return text_reply(details_text(f"Order {details['name']}", details))


def live_details(checkout: StoreCheckout) -> dict | None:
    """The checkout's order as Shopify has it now, or None when Shopify can't be asked or no longer has it."""
    try:
        return order_details(checkout.shop, checkout.order_id)
    except (*SHOPIFY_FAILURES, requests.RequestException) as error:
        # Ids and the error's kind only: Shopify's reply may hold the order's details.
        logger.warning("Checkout id=%s: Shopify's order couldn't be had (%s).", checkout.pk, type(error).__name__)
        return None


def details_text(headline: str, details: dict) -> str:
    """
    An order's details, under `headline`: each line's quantity and title, the total, and the payment and
    delivery status, or that it's cancelled. Shared by the updates and the Order details reply (menus.py).
    """
    lines = [headline]
    shown = details["lines"][:LINES_SHOWN]
    lines += [f"{line['quantity']} × {line['title']}" for line in shown]
    if len(details["lines"]) > len(shown):
        lines.append(f"…and {len(details['lines']) - len(shown)} more")
    lines.append(f"Total: {_money(details['total_price'], details['currency'])}")
    if details["cancelled"]:
        lines.append("Cancelled")
    else:
        payment = PAYMENT_WORDS.get(details["financial_status"], _readable(details["financial_status"]))
        delivery = DELIVERY_WORDS.get(details["fulfillment_status"], _readable(details["fulfillment_status"]))
        lines.append(f"Payment: {payment} · Delivery: {delivery}")
    return "\n".join(lines)


def _code(order: dict) -> str:
    """The order's `_whatsapp_checkout` code, or an empty string if it carries none."""
    for attribute in order.get("note_attributes") or []:
        if attribute.get("name") == CHECKOUT_ATTRIBUTE:
            return str(attribute.get("value") or "")
    return ""


def _forget_cart(checkout: StoreCheckout) -> None:
    """Clear the store customer's open cart if it's still the one this checkout's order came from."""
    StoreCustomer.objects.filter(
        pk=checkout.store_customer_id, cart_id=checkout.cart_id, cart_shop_id=checkout.shop_id
    ).update(cart_id="", cart_shop=None, updated_at=timezone.now())


def _headline(number: str, *, paid: bool) -> str:
    return f"Order {number} is paid." if paid else f"Order {number} received, awaiting payment."


def _template(checkout: StoreCheckout, contact, order: dict) -> dict:
    """The update template, for after the window (decision 6). Meta refuses an empty blank, so each has a fallback."""
    return order_template(
        store=contact.account.verified_name or checkout.shop.shop_domain,
        number=order.get("name") or f"#{checkout.order_id}",
        code=checkout.code,
    )


def _money(amount, currency) -> str:
    """Shopify's amount ("1025.0") with its currency, to two decimals ("USD 1025.00"), never rounded otherwise."""
    try:
        shown = f"{Decimal(str(amount)):.2f}"
    except (InvalidOperation, ValueError):
        shown = str(amount)
    return f"{currency} {shown}" if currency else shown


def _readable(status: str) -> str:
    """A Shopify status this app has no words for, such as "ON_HOLD", as "On hold"."""
    return status.replace("_", " ").capitalize() if status else "Unknown"


def _total(order: dict) -> str:
    total, currency = order.get("total_price"), order.get("currency")
    if not total:
        return ""
    return f" Total: {currency} {total}." if currency else f" Total: {total}."
