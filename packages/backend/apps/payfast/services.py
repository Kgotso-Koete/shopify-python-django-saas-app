"""
The PayFast subscription and donation lifecycle: checkouts, ITN processing, plan changes,
cancellation, and the daily maintenance task.

Guiding rule (plan section 2): behave like the Stripe implementation wherever both APIs allow it, with the
same plans, one trial per tenant, plan changes and cancellations at the end of the period, and the
same emails. Where PayFast can't do something, the function says what it does instead.

Money flow in one picture:

    GraphQL mutation --create_*_checkout--> signed form fields --browser POST--> PayFast
    PayFast --ITN--> views.itn_view --itn.verify_itn--> process_itn --> models updated
"""

import calendar
import datetime
import logging
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Optional

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.finances import constants as finance_constants
from apps.finances import notifications
from . import constants, signature
from .client import PayFastApiClient, PayFastApiError
from .itn import ItnRejected
from .models import PayFastCheckout, PayFastPayment, PayFastSubscription

logger = logging.getLogger(__name__)

FREE_PLAN = finance_constants.FREE_PLAN.name

# Outcomes of process_itn, for logging and tests.
PROCESSED = "processed"
DUPLICATE = "duplicate"
IGNORED = "ignored"

# The Stripe `customer.subscription.trial_will_end` event fires three days before a trial ends.
TRIAL_REMINDER_LEAD_TIME = datetime.timedelta(days=3)
# How late a renewal ITN may be before the daily task asks PayFast what happened.
RENEWAL_ITN_GRACE = datetime.timedelta(days=1)

# Display names used as PayFast's item_name (shown to the buyer on PayFast's payment page).
ITEM_NAMES = {
    finance_constants.MONTHLY_PLAN.name: "Monthly plan",
    finance_constants.YEARLY_PLAN.name: "Yearly plan",
}
DONATION_ITEM_NAME = "Donation"


class PayFastError(Exception):
    """A request that can't be done in the tenant's current state; the message is safe to show a user."""


@dataclass(frozen=True)
class CheckoutForm:
    """What the browser needs to send the buyer to PayFast: POST `fields` to `action_url`."""

    action_url: str
    fields: dict
    m_payment_id: uuid.UUID


# --- Subscriptions -------------------------------------------------------------------------------


def get_subscription(tenant) -> PayFastSubscription:
    """The tenant's subscription, created on the free plan if it doesn't exist yet."""
    subscription, _ = PayFastSubscription.objects.get_or_create(tenant=tenant)
    return subscription


def initialize_tenant(tenant) -> PayFastSubscription:
    """Put a new tenant on the free plan (the PayFast counterpart of Stripe's initialize_tenant)."""
    return get_subscription(tenant)


def next_period_end(start: datetime.datetime, frequency: int) -> datetime.datetime:
    """The end of a billing period starting at `start`: one calendar month or year later."""
    months = 12 if frequency == constants.Frequency.ANNUAL else 1
    month_index = start.month - 1 + months
    year, month = start.year + month_index // 12, month_index % 12 + 1
    # Clamp the day, so 31 January + 1 month is 28 (or 29) February.
    day = min(start.day, calendar.monthrange(year, month)[1])
    return start.replace(year=year, month=month, day=day)


# --- Checkouts -----------------------------------------------------------------------------------


def create_subscription_checkout(*, tenant, user, plan_name: str, return_url: str, cancel_url: str) -> CheckoutForm:
    """
    Start buying a paid plan. The first purchase is a free trial of SUBSCRIPTION_TRIAL_PERIOD_DAYS:
    an R0.00 initial payment with the first charge on `billing_date`, so the card is captured now and
    nothing is charged until the trial ends (https://developers.payfast.co.za/docs#subscriptions).
    """
    subscription = get_subscription(tenant)
    try:
        plan = constants.get_paid_plan(plan_name)
    except constants.UnknownPlanError as error:
        raise PayFastError(f"{plan_name!r} is not a plan you can subscribe to.") from error
    if subscription.effective_plan() != FREE_PLAN:
        return _create_plan_change_checkout(subscription, plan, user, return_url, cancel_url)

    is_trial = subscription.can_activate_trial
    checkout = PayFastCheckout.objects.create(
        kind=PayFastCheckout.Kind.SUBSCRIPTION,
        tenant=tenant,
        created_by=user,
        plan=plan.name,
        amount=Decimal("0.00") if is_trial else plan.amount,
        recurring_amount=plan.amount,
        frequency=plan.frequency,
        is_trial=is_trial,
    )
    fields = {
        **_base_fields(checkout, user, return_url, cancel_url),
        "item_name": ITEM_NAMES[plan.name],
        # Pass-through for support; the ITN handler never trusts it (it reads the checkout instead).
        "custom_str1": plan.name,
        "subscription_type": "1",
        "recurring_amount": f"{plan.amount:.2f}",
        "frequency": str(plan.frequency),
        "cycles": "0",  # indefinite, like a Stripe subscription
        # We send TrialExpiresSoonEmail ourselves, like Stripe, so PayFast's own buyer email is off.
        "subscription_notify_buyer": "false",
    }
    if is_trial:
        trial_end = timezone.now() + datetime.timedelta(days=constants.trial_period_days())
        fields["billing_date"] = trial_end.date().isoformat()
    return _signed_form(checkout, fields)


def _create_plan_change_checkout(subscription, plan, user, return_url: str, cancel_url: str) -> CheckoutForm:
    """
    Switch a paying organisation to another paid plan with a new PayFast subscription: R0.00 now and
    the new plan's price from the day the current paid period (or trial) ends, so the switch applies
    at period end, as on Stripe, and nobody is charged twice for the same period. When PayFast
    confirms it, the old subscription is cancelled (see _complete_plan_change).

    PayFast's subscription update API isn't used: in the sandbox it fails with an HTML error page for
    every change (plan section 10), and a maintained Laravel PayFast package also switches plans this way.
    """
    if subscription.cancel_at_period_end:
        raise PayFastError("This subscription is cancelled; choose a new plan once it has ended.")
    if not subscription.token or subscription.current_period_end is None:
        raise PayFastError("This subscription isn't ready to change yet; try again shortly.")
    if plan.name == subscription.plan:
        raise PayFastError("This is already your current plan.")
    if plan.name == subscription.pending_plan:
        raise PayFastError("This plan is already scheduled for your next billing period.")

    checkout = PayFastCheckout.objects.create(
        kind=PayFastCheckout.Kind.SUBSCRIPTION,
        tenant=subscription.tenant,
        created_by=user,
        plan=plan.name,
        amount=Decimal("0.00"),
        recurring_amount=plan.amount,
        frequency=plan.frequency,
        replaces_token=subscription.token,
    )
    fields = {
        **_base_fields(checkout, user, return_url, cancel_url),
        "item_name": ITEM_NAMES[plan.name],
        "custom_str1": plan.name,
        "subscription_type": "1",
        "billing_date": subscription.current_period_end.date().isoformat(),
        "recurring_amount": f"{plan.amount:.2f}",
        "frequency": str(plan.frequency),
        "cycles": "0",
        "subscription_notify_buyer": "false",
    }
    return _signed_form(checkout, fields)


def create_donation_checkout(*, tenant, user, amount, return_url: str, cancel_url: str) -> CheckoutForm:
    """Start a once-off donation of one of the configured PAYFAST_DONATION_AMOUNTS."""
    try:
        amount = constants.to_amount(amount)
    except (InvalidOperation, ValueError, TypeError) as error:
        raise PayFastError("Choose one of the donation amounts.") from error
    if amount not in constants.donation_amounts():
        raise PayFastError("Choose one of the donation amounts.")

    checkout = PayFastCheckout.objects.create(
        kind=PayFastCheckout.Kind.DONATION, tenant=tenant, created_by=user, amount=amount
    )
    fields = {**_base_fields(checkout, user, return_url, cancel_url), "item_name": DONATION_ITEM_NAME}
    return _signed_form(checkout, fields)


def _base_fields(checkout: PayFastCheckout, user, return_url: str, cancel_url: str) -> dict:
    separator = "&" if "?" in return_url else "?"
    return {
        "merchant_id": settings.PAYFAST_MERCHANT_ID,
        "merchant_key": settings.PAYFAST_MERCHANT_KEY,
        # The return page polls the checkout's status until the ITN has landed, so it needs the id.
        "return_url": f"{return_url}{separator}m={checkout.m_payment_id}",
        "cancel_url": cancel_url,
        "notify_url": settings.PAYFAST_NOTIFY_URL,
        "email_address": getattr(user, "email", "") or "",
        "m_payment_id": str(checkout.m_payment_id),
        "amount": f"{checkout.amount:.2f}",
    }


def _signed_form(checkout: PayFastCheckout, fields: dict) -> CheckoutForm:
    fields = {key: value for key, value in fields.items() if value not in (None, "")}
    fields["signature"] = signature.checkout_signature(fields, settings.PAYFAST_PASSPHRASE)
    return CheckoutForm(action_url=constants.process_url(), fields=fields, m_payment_id=checkout.m_payment_id)


# --- ITN processing ------------------------------------------------------------------------------


def process_itn(data: dict) -> str:
    """
    Apply a verified ITN. `data` must already have passed itn.verify_itn (signature, source, server
    confirmation). This function does the remaining check, the amount, against what WE expected.

    Returns PROCESSED, DUPLICATE (an ITN PayFast re-sent) or IGNORED (not something we started).
    Raises ItnRejected if the amount isn't what we expected.
    """
    pf_payment_id = data.get("pf_payment_id") or ""
    payment_status = (data.get("payment_status") or "").upper()
    token = data.get("token") or ""

    with transaction.atomic():
        if pf_payment_id and PayFastPayment.objects.filter(pf_payment_id=pf_payment_id).exists():
            return DUPLICATE

        checkout = _find_checkout(data.get("m_payment_id"))
        subscription = PayFastSubscription.objects.select_for_update().filter(token=token).first() if token else None

        if payment_status == "CANCELLED":
            if subscription is None:
                return IGNORED
            _apply_cancelled_itn(subscription, data)
            return PROCESSED

        if payment_status != "COMPLETE":
            logger.warning("Ignoring PayFast ITN with payment_status %r", payment_status)
            return IGNORED

        if checkout is not None and checkout.status == PayFastCheckout.Status.PENDING:
            if checkout.kind == PayFastCheckout.Kind.DONATION:
                _complete_donation(checkout, data)
            else:
                _complete_subscription_checkout(checkout, token, data)
            return PROCESSED

        if subscription is not None:
            _renew(subscription, data)
            return PROCESSED

    logger.warning("Ignoring PayFast ITN %s: no matching checkout or subscription", pf_payment_id)
    return IGNORED


def _find_checkout(m_payment_id) -> Optional[PayFastCheckout]:
    try:
        checkout_id = uuid.UUID(str(m_payment_id))
    except ValueError:
        return None
    return PayFastCheckout.objects.select_for_update().filter(m_payment_id=checkout_id).first()


def _check_amount(expected: Decimal, data: dict):
    """PayFast's security check 3: the amount paid must be the amount we expected (to the cent)."""
    try:
        received = Decimal(data.get("amount_gross") or "0")
    except InvalidOperation as error:
        raise ItnRejected(f"invalid amount_gross {data.get('amount_gross')!r}") from error
    if abs(received - Decimal(expected)) > Decimal("0.01"):
        raise ItnRejected(f"amount {received} does not match expected {expected}")


def _record_payment(*, tenant, kind, data, subscription=None, plan="") -> None:
    if not data.get("pf_payment_id"):
        return

    def decimal_field(name):
        try:
            return Decimal(data.get(name) or "0")
        except InvalidOperation:
            return Decimal("0")

    PayFastPayment.objects.create(
        tenant=tenant,
        kind=kind,
        subscription=subscription,
        plan=plan,
        pf_payment_id=data["pf_payment_id"],
        m_payment_id=data.get("m_payment_id") or "",
        amount_gross=decimal_field("amount_gross"),
        amount_fee=decimal_field("amount_fee"),
        amount_net=decimal_field("amount_net"),
        payment_status=(data.get("payment_status") or "").upper(),
        item_name=(data.get("item_name") or "")[:100],
        raw=dict(data),
    )


def _complete_donation(checkout: PayFastCheckout, data: dict):
    _check_amount(checkout.amount, data)
    _record_payment(tenant=checkout.tenant, kind=PayFastPayment.Kind.DONATION, data=data)
    checkout.status = PayFastCheckout.Status.COMPLETE
    checkout.save(update_fields=["status", "updated_at"])


def _complete_subscription_checkout(checkout: PayFastCheckout, token: str, data: dict):
    _check_amount(checkout.amount, data)
    subscription = PayFastSubscription.objects.select_for_update().get(pk=get_subscription(checkout.tenant).pk)
    if checkout.replaces_token:
        _complete_plan_change(checkout, subscription, token, data)
        return
    now = timezone.now()

    subscription.plan = checkout.plan
    subscription.token = token
    subscription.amount = checkout.recurring_amount
    subscription.frequency = checkout.frequency
    subscription.pending_plan = ""
    subscription.pending_amount = None
    subscription.cancel_at_period_end = False
    subscription.payment_failed_notified_at = None
    subscription.trial_reminder_sent_at = None
    subscription.current_period_start = now
    if checkout.is_trial:
        subscription.status = PayFastSubscription.Status.TRIALING
        subscription.has_used_trial = True
        subscription.trial_end = now + datetime.timedelta(days=constants.trial_period_days())
        subscription.current_period_end = subscription.trial_end
    else:
        subscription.status = PayFastSubscription.Status.ACTIVE
        subscription.current_period_end = next_period_end(now, checkout.frequency)
    subscription.save()

    _record_payment(
        tenant=checkout.tenant,
        kind=PayFastPayment.Kind.SUBSCRIPTION,
        data=data,
        subscription=subscription,
        plan=checkout.plan,
    )
    checkout.status = PayFastCheckout.Status.COMPLETE
    checkout.save(update_fields=["status", "updated_at"])


def _complete_plan_change(checkout: PayFastCheckout, subscription: PayFastSubscription, token: str, data: dict):
    """
    The new subscription for a plan change is set up. The current paid period carries on unchanged;
    the new plan is "pending" and applies on the new subscription's first charge (in _renew), at the
    end of the period. The old subscription is cancelled now, so only the new one bills from then on.
    """
    subscription.token = token
    subscription.pending_plan = checkout.plan
    subscription.pending_amount = checkout.recurring_amount
    subscription.save()

    _record_payment(
        tenant=checkout.tenant,
        kind=PayFastPayment.Kind.SUBSCRIPTION,
        data=data,
        subscription=subscription,
        plan=checkout.plan,
    )
    checkout.status = PayFastCheckout.Status.COMPLETE
    checkout.save(update_fields=["status", "updated_at"])

    _cancel_superseded(subscription, checkout.replaces_token)


def _cancel_superseded(subscription: PayFastSubscription, old_token: str):
    """
    Cancel a subscription replaced by a plan change. If PayFast can't be reached, remember the token
    so the daily task retries; otherwise the customer would be billed by both subscriptions.
    The cancellation ITN that PayFast then sends for the old token matches no subscription and is ignored.
    """
    try:
        PayFastApiClient().cancel(old_token)
    except PayFastApiError:
        logger.exception("Could not cancel replaced PayFast subscription for %s; will retry", subscription.pk)
        subscription.superseded_token = old_token
    else:
        subscription.superseded_token = ""
    subscription.save(update_fields=["superseded_token", "updated_at"])


def _renew(subscription: PayFastSubscription, data: dict):
    """A recurring charge succeeded: apply any pending plan change and start the next period."""
    expected = subscription.pending_amount if subscription.pending_plan else subscription.amount
    _check_amount(expected, data)

    if subscription.pending_plan:
        subscription.plan = subscription.pending_plan
        subscription.amount = subscription.pending_amount
        subscription.frequency = constants.plan_prices()[subscription.pending_plan].frequency
        subscription.pending_plan = ""
        subscription.pending_amount = None

    start = subscription.current_period_end or timezone.now()
    subscription.current_period_start = start
    subscription.current_period_end = next_period_end(start, subscription.frequency)
    subscription.status = PayFastSubscription.Status.ACTIVE
    subscription.payment_failed_notified_at = None
    subscription.save()

    _record_payment(
        tenant=subscription.tenant,
        kind=PayFastPayment.Kind.SUBSCRIPTION,
        data=data,
        subscription=subscription,
        plan=subscription.plan,
    )


def _apply_cancelled_itn(subscription: PayFastSubscription, data: dict):
    """
    The subscription was cancelled on PayFast's side: by our own cancel call, by the buyer, or by
    the merchant in the PayFast dashboard. No more charges; the plan lasts until the period ends.
    """
    subscription.cancel_at_period_end = True
    subscription.pending_plan = ""
    subscription.pending_amount = None
    subscription.save()
    _record_payment(
        tenant=subscription.tenant, kind=PayFastPayment.Kind.SUBSCRIPTION, data=data, subscription=subscription
    )


# --- Cancellation --------------------------------------------------------------------------------


def cancel_subscription(*, tenant) -> PayFastSubscription:
    """
    Cancel a paid subscription. PayFast stops charging straight away; the plan lasts until the end
    of the current period, then the tenant is on the free plan (Stripe parity).
    """
    with transaction.atomic():
        subscription = PayFastSubscription.objects.select_for_update().get(pk=get_subscription(tenant).pk)
        if subscription.effective_plan() == FREE_PLAN or not subscription.token:
            raise PayFastError("There is no paid plan to cancel.")
        if not subscription.cancel_at_period_end:
            _call_api("cancel", subscription.token)
            subscription.cancel_at_period_end = True
        if subscription.superseded_token:
            _cancel_superseded(subscription, subscription.superseded_token)
        subscription.pending_plan = ""
        subscription.pending_amount = None
        subscription.save()
        return subscription


def cancel_tenant_subscription_immediately(tenant):
    """Used when a tenant is deleted: stop PayFast charging. API errors are logged, not raised."""
    subscription = PayFastSubscription.objects.filter(tenant=tenant).first()
    if subscription is None or not (subscription.token or subscription.superseded_token):
        return
    for token in filter(None, (subscription.superseded_token, subscription.token)):
        try:
            PayFastApiClient().cancel(token)
        except PayFastApiError:
            logger.exception("Could not cancel PayFast subscription for deleted tenant %s", tenant.pk)
    subscription.status = PayFastSubscription.Status.CANCELLED
    subscription.save(update_fields=["status", "updated_at"])


def card_update_url(subscription: PayFastSubscription, return_url: str) -> Optional[str]:
    """PayFast-hosted page for updating the card on file, or None if there's no subscription token."""
    if not subscription.token:
        return None
    return constants.card_update_url(subscription.token, return_url=return_url)


def _call_api(method_name: str, *args, **kwargs):
    """Call a PayFastApiClient method, turning API failures into a PayFastError a user can see."""
    try:
        return getattr(PayFastApiClient(), method_name)(*args, **kwargs)
    except PayFastApiError as error:
        logger.warning("PayFast API %s failed: %s", method_name, error)
        raise PayFastError("PayFast could not process the request. Please try again later.") from error


def reset_to_free_plan(subscription: PayFastSubscription):
    """Back to the free plan after a subscription has ended. The used trial stays used."""
    subscription.plan = FREE_PLAN
    subscription.status = PayFastSubscription.Status.ACTIVE
    subscription.token = ""
    subscription.amount = Decimal("0.00")
    subscription.frequency = None
    subscription.pending_plan = ""
    subscription.pending_amount = None
    subscription.current_period_start = None
    subscription.current_period_end = None
    subscription.trial_end = None
    subscription.cancel_at_period_end = False
    subscription.payment_failed_notified_at = None
    subscription.trial_reminder_sent_at = None
    subscription.save()


# --- Refunds (admin) -----------------------------------------------------------------------------


@dataclass(frozen=True)
class RefundOptions:
    """What PayFast says can be refunded for a payment (https://developers.payfast.co.za/api#refund-query)."""

    refundable: bool
    available: Decimal
    method: str  # PAYMENT_SOURCE, BANK_PAYOUT or NOT_AVAILABLE
    errors: tuple


def get_refund_options(payment: PayFastPayment) -> RefundOptions:
    """Ask PayFast how much of `payment` can still be refunded, and how. PayFast recommends this first."""
    response = PayFastApiClient().refund_query(payment.pf_payment_id) or {}
    return RefundOptions(
        refundable=response.get("status") == "REFUNDABLE",
        available=(Decimal(response.get("amount_available_for_refund") or 0) / 100).quantize(constants.CENTS),
        method=(response.get("refund_partial") or {}).get("method") or "NOT_AVAILABLE",
        errors=tuple(response.get("errors") or ()),
    )


def refund_payment(payment: PayFastPayment, *, amount: Decimal, reason: str) -> Decimal:
    """
    Refund `amount` (ZAR) of a payment to the card or account it came from. Bank-payout refunds (for
    EFT payments) need the buyer's bank details and are left to the PayFast dashboard.
    Returns the payment's new refunded total; raises PayFastError if the refund isn't possible.
    """
    try:
        options = get_refund_options(payment)
    except PayFastApiError as error:
        raise PayFastError("PayFast could not be reached. Please try again later.") from error
    if not options.refundable:
        raise PayFastError("; ".join(options.errors) or "PayFast says this payment can't be refunded.")
    if options.method != "PAYMENT_SOURCE":
        raise PayFastError("This payment must be refunded by bank payout; do it from the PayFast dashboard.")
    if amount <= 0 or amount > options.available:
        raise PayFastError(f"You can refund between 0.01 and {options.available} ZAR.")

    _call_api("refund_create", payment.pf_payment_id, amount=amount, reason=reason)
    payment.refunded_amount += amount
    payment.save(update_fields=["refunded_amount", "updated_at"])
    return payment.refunded_amount


# --- Daily maintenance ---------------------------------------------------------------------------


def run_daily_maintenance() -> dict:
    """
    Things PayFast has no event for, run once a day by apps.payfast.tasks.daily_maintenance:

    0. Retry cancelling subscriptions replaced by a plan change, if that failed when it happened.
    1. "Trial ends soon" emails, three days before the trial ends (Stripe's trial_will_end).
    2. Overdue renewals: PayFast sends no ITN when a charge fails, so a renewal more than a day
       overdue is checked with GET /fetch (https://developers.payfast.co.za/api#subscription-object-fetch).
    3. Subscriptions that have ended (cancelled at period end, or past due beyond the grace period)
       go back to the free plan.

    Each subscription is handled on its own, so one failing API call doesn't stop the rest.
    """
    now = timezone.now()
    counts = {"trial_reminders": 0, "renewals_checked": 0, "ended": 0, "superseded_cancelled": 0}

    for subscription in PayFastSubscription.objects.exclude(superseded_token=""):
        _cancel_superseded(subscription, subscription.superseded_token)
        counts["superseded_cancelled"] += not subscription.superseded_token

    for subscription in PayFastSubscription.objects.filter(
        status=PayFastSubscription.Status.TRIALING,
        cancel_at_period_end=False,
        trial_reminder_sent_at__isnull=True,
        trial_end__gt=now,
        trial_end__lte=now + TRIAL_REMINDER_LEAD_TIME,
    ):
        notifications.TrialExpiresSoonEmail(customer=subscription, data={"expiry_date": subscription.trial_end}).send()
        subscription.trial_reminder_sent_at = now
        subscription.save(update_fields=["trial_reminder_sent_at", "updated_at"])
        counts["trial_reminders"] += 1

    overdue = PayFastSubscription.objects.filter(
        status__in=[PayFastSubscription.Status.ACTIVE, PayFastSubscription.Status.TRIALING],
        cancel_at_period_end=False,
        current_period_end__lte=now - RENEWAL_ITN_GRACE,
    ).exclude(token="")
    for subscription in overdue.order_by("pk"):
        try:
            _check_overdue_renewal(subscription)
            counts["renewals_checked"] += 1
        except PayFastApiError:
            logger.exception("Could not check PayFast subscription %s", subscription.pk)

    for subscription in PayFastSubscription.objects.filter(cancel_at_period_end=True, current_period_end__lte=now):
        reset_to_free_plan(subscription)
        counts["ended"] += 1

    grace_start = now - datetime.timedelta(days=PayFastSubscription.PAST_DUE_GRACE_DAYS)
    for subscription in PayFastSubscription.objects.filter(
        status=PayFastSubscription.Status.PAST_DUE, current_period_end__lte=grace_start
    ):
        try:
            PayFastApiClient().cancel(subscription.token)
        except PayFastApiError:
            logger.exception("Could not cancel past-due PayFast subscription %s", subscription.pk)
            continue
        reset_to_free_plan(subscription)
        counts["ended"] += 1

    return counts


def _check_overdue_renewal(subscription: PayFastSubscription):
    """
    Ask PayFast about a renewal whose ITN hasn't arrived. If PayFast's next run date has moved past
    our period end, the charge happened and only the ITN was lost: catch up. Otherwise the charge is
    failing (PayFast is retrying it): mark it past due and send the payment-failed email once. A
    failed first charge after a trial cancels the subscription, as the Stripe webhook does.
    """
    remote = PayFastApiClient().fetch(subscription.token) or {}
    run_date = _parse_run_date(remote.get("run_date"))
    period_end = subscription.current_period_end

    if remote.get("status_text") == "ACTIVE" and run_date and run_date > period_end.date():
        logger.warning("PayFast renewal ITN missing for subscription %s; catching up", subscription.pk)
        subscription.current_period_start = period_end
        subscription.current_period_end = datetime.datetime.combine(run_date, period_end.timetz())
        subscription.status = PayFastSubscription.Status.ACTIVE
        subscription.save()
        return

    if subscription.payment_failed_notified_at is None:
        notifications.SubscriptionErrorEmail(customer=subscription).send()
        subscription.payment_failed_notified_at = timezone.now()

    if subscription.is_trialing:
        PayFastApiClient().cancel(subscription.token)
        subscription.status = PayFastSubscription.Status.CANCELLED
    else:
        subscription.status = PayFastSubscription.Status.PAST_DUE
    subscription.save()


def _parse_run_date(value) -> Optional[datetime.date]:
    """PayFast's run_date, e.g. "2026-11-30T00:00:00+02:00", as the calendar date PayFast means."""
    if not value:
        return None
    try:
        return datetime.datetime.fromisoformat(str(value)).date()
    except ValueError:
        try:
            return datetime.date.fromisoformat(str(value)[:10])
        except ValueError:
            return None
