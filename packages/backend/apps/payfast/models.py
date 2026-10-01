"""
PayFast billing state, kept in our own database.

Unlike dj-stripe, which mirrors Stripe's objects, PayFast has no object API to mirror: we learn about
payments only from ITNs and the Subscriptions API. So these models hold what we need ourselves:

- PayFastSubscription: one per tenant; the tenant's plan, PayFast token and billing period.
- PayFastCheckout:     a checkout we started; the source of truth for who pays what when the ITN arrives.
- PayFastPayment:      one confirmed transaction (subscription charge or donation), from an ITN.

See docs/superpowers/plans/2026-09-30-payfast-payment-backend-plan.md section 3.2.
"""

import datetime
import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.finances import constants as finance_constants
from common.models import TimestampedMixin
from .constants import Frequency

PLAN_NAME_MAX_LENGTH = 32
AMOUNT_FIELD = {"max_digits": 10, "decimal_places": 2}


class PayFastSubscription(TimestampedMixin, models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        TRIALING = "trialing", "Trialing"
        # A renewal charge is overdue: PayFast is retrying it (it sends no failure notification).
        PAST_DUE = "past_due", "Past due"
        CANCELLED = "cancelled", "Cancelled"

    # How long a past-due subscription keeps its paid plan after the unpaid renewal date, while
    # PayFast retries the charge (https://developers.payfast.co.za/docs#recurring_billing).
    PAST_DUE_GRACE_DAYS = 7

    tenant = models.OneToOneField("multitenancy.Tenant", on_delete=models.CASCADE, related_name="payfast_subscription")
    # The plan currently paid for, using the plan names shared with Stripe (apps.finances.constants).
    plan = models.CharField(max_length=PLAN_NAME_MAX_LENGTH, default=finance_constants.FREE_PLAN.name)
    # A plan change waiting for the next charge, and its price (plan changes apply at period end).
    pending_plan = models.CharField(max_length=PLAN_NAME_MAX_LENGTH, blank=True, default="")
    pending_amount = models.DecimalField(null=True, blank=True, **AMOUNT_FIELD)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    # PayFast's id for the subscription, from the first ITN; needed for every API call.
    token = models.CharField(max_length=64, blank=True, default="", db_index=True)
    # The recurring amount in ZAR, as agreed at checkout (a later price change doesn't affect it).
    amount = models.DecimalField(default=Decimal("0.00"), **AMOUNT_FIELD)
    frequency = models.PositiveSmallIntegerField(null=True, blank=True, choices=Frequency.choices)
    current_period_start = models.DateTimeField(null=True, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    trial_end = models.DateTimeField(null=True, blank=True)
    # One trial per tenant, ever (Stripe parity: apps.finances.utils.customer_can_activate_trial).
    has_used_trial = models.BooleanField(default=False)
    # Set once the "trial ends soon" email has gone out, so the daily task sends it only once.
    trial_reminder_sent_at = models.DateTimeField(null=True, blank=True)
    # Set once the "payment failed" email has gone out for the current overdue renewal.
    payment_failed_notified_at = models.DateTimeField(null=True, blank=True)
    # Cancelled by the customer: no more charges, but the plan lasts until current_period_end.
    cancel_at_period_end = models.BooleanField(default=False)
    # The token of a subscription replaced by a plan change whose PayFast cancellation hasn't
    # succeeded yet; the daily task keeps retrying, so the customer is never billed twice.
    superseded_token = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        verbose_name = "PayFast subscription"

    def __str__(self):
        return f"{self.tenant} - {self.plan} ({self.status})"

    @property
    def subscriber(self):
        """
        The tenant, under the name dj-stripe uses. apps.finances.notifications.CustomerEmail reads
        `customer.subscriber`, so this lets PayFast send the Stripe emails unchanged.
        """
        return self.tenant

    @property
    def is_trialing(self) -> bool:
        return self.status == self.Status.TRIALING

    @property
    def can_activate_trial(self) -> bool:
        return not self.has_used_trial

    @property
    def has_card(self) -> bool:
        """PayFast holds the card; a token means there is a card on file for this subscription."""
        return bool(self.token)

    def effective_plan(self, now=None) -> str:
        """
        The plan the tenant has right now. Computed on read, so a cancelled or unpaid subscription
        downgrades to the free plan at the right moment even before the daily task tidies it up.
        """
        now = now or timezone.now()
        free = finance_constants.FREE_PLAN.name
        if self.plan == free or self.status == self.Status.CANCELLED:
            return free
        if self.cancel_at_period_end and self.current_period_end and now >= self.current_period_end:
            return free
        if (
            self.status == self.Status.PAST_DUE
            and self.current_period_end
            and now >= self.current_period_end + datetime.timedelta(days=self.PAST_DUE_GRACE_DAYS)
        ):
            return free
        return self.plan


class PayFastCheckout(TimestampedMixin, models.Model):
    """
    A PayFast checkout we started. When PayFast's ITN arrives, it is matched to this record by
    m_payment_id, and the tenant, plan and expected amount come from here, never from the ITN.
    """

    class Kind(models.TextChoices):
        SUBSCRIPTION = "subscription", "Subscription"
        DONATION = "donation", "Donation"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        COMPLETE = "complete", "Complete"

    m_payment_id = models.UUIDField(unique=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    tenant = models.ForeignKey("multitenancy.Tenant", on_delete=models.CASCADE, related_name="payfast_checkouts")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    plan = models.CharField(max_length=PLAN_NAME_MAX_LENGTH, blank=True, default="")  # empty for donations
    # The amount charged at checkout: 0.00 for a trial, the price otherwise, or the donation.
    amount = models.DecimalField(**AMOUNT_FIELD)
    # The subscription's recurring amount and frequency; empty for donations.
    recurring_amount = models.DecimalField(null=True, blank=True, **AMOUNT_FIELD)
    frequency = models.PositiveSmallIntegerField(null=True, blank=True, choices=Frequency.choices)
    is_trial = models.BooleanField(default=False)
    # For a plan change: the token of the subscription this checkout replaces (cancelled once the
    # new subscription is confirmed). Empty for a first subscription or a donation.
    replaces_token = models.CharField(max_length=64, blank=True, default="")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)

    class Meta:
        verbose_name = "PayFast checkout"

    def __str__(self):
        return f"{self.kind} {self.m_payment_id} ({self.status})"


class PayFastPayment(TimestampedMixin, models.Model):
    """One transaction PayFast confirmed through an ITN. Shown in the tenant's transaction history."""

    class Kind(models.TextChoices):
        SUBSCRIPTION = "subscription", "Subscription"
        DONATION = "donation", "Donation"

    tenant = models.ForeignKey("multitenancy.Tenant", on_delete=models.CASCADE, related_name="payfast_payments")
    kind = models.CharField(max_length=16, choices=Kind.choices)
    subscription = models.ForeignKey(
        PayFastSubscription, null=True, blank=True, on_delete=models.SET_NULL, related_name="payments"
    )
    # The plan this charge paid for, for the "{plan} plan" label in transaction history.
    plan = models.CharField(max_length=PLAN_NAME_MAX_LENGTH, blank=True, default="")
    # PayFast's transaction id. Unique, which makes processing a re-sent ITN a no-op.
    pf_payment_id = models.CharField(max_length=64, unique=True)
    m_payment_id = models.CharField(max_length=100, blank=True, default="", db_index=True)
    amount_gross = models.DecimalField(**AMOUNT_FIELD)
    amount_fee = models.DecimalField(default=Decimal("0.00"), **AMOUNT_FIELD)
    amount_net = models.DecimalField(default=Decimal("0.00"), **AMOUNT_FIELD)
    payment_status = models.CharField(max_length=16)  # COMPLETE or CANCELLED, as PayFast sent it
    item_name = models.CharField(max_length=100, blank=True, default="")
    refunded_amount = models.DecimalField(default=Decimal("0.00"), **AMOUNT_FIELD)
    # The full ITN payload, for support and audits.
    raw = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "PayFast payment"
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.pf_payment_id} {self.amount_gross} ({self.payment_status})"
