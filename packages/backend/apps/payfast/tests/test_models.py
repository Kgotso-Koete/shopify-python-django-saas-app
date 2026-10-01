"""
Tests for apps/payfast/models.py, mainly PayFastSubscription.effective_plan: the plan a tenant
actually has right now. It is computed on read, so a cancelled subscription downgrades to the free
plan at the end of its paid period without a scheduled job having to run first (plan section 2).
"""

import datetime
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.finances import constants as finance_constants
from ..models import PayFastSubscription

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("payfast_backend")]

FREE = finance_constants.FREE_PLAN.name
MONTHLY = finance_constants.MONTHLY_PLAN.name


def hours(n):
    return datetime.timedelta(hours=n)


class TestDefaults:
    def test_new_subscription_is_on_the_free_plan(self, tenant):
        # With PAYMENT_BACKEND=payfast, creating the tenant created its subscription (apps.finances.signals).
        subscription = PayFastSubscription.objects.get(tenant=tenant)

        assert subscription.plan == FREE
        assert subscription.status == PayFastSubscription.Status.ACTIVE
        assert subscription.amount == Decimal("0.00")
        assert subscription.effective_plan() == FREE
        assert subscription.can_activate_trial
        assert not subscription.has_card

    def test_subscriber_is_the_tenant(self, pay_fast_subscription):
        # apps.finances.notifications.CustomerEmail reads `customer.subscriber`, so exposing the tenant
        # as `subscriber` lets PayFast reuse the Stripe emails unchanged.
        assert pay_fast_subscription.subscriber == pay_fast_subscription.tenant


class TestEffectivePlan:
    def test_active_paid_subscription_has_its_plan(self, pay_fast_subscription_factory):
        subscription = pay_fast_subscription_factory(monthly=True, current_period_end=timezone.now() + hours(24))

        assert subscription.effective_plan() == MONTHLY
        assert subscription.has_card

    def test_cancelled_at_period_end_keeps_the_plan_until_the_period_ends(self, pay_fast_subscription_factory):
        period_end = timezone.now() + hours(24)
        subscription = pay_fast_subscription_factory(
            monthly=True, cancel_at_period_end=True, current_period_end=period_end
        )

        assert subscription.effective_plan(now=period_end - hours(1)) == MONTHLY
        assert subscription.effective_plan(now=period_end) == FREE

    def test_cancelled_status_is_free(self, pay_fast_subscription_factory):
        subscription = pay_fast_subscription_factory(
            monthly=True, status=PayFastSubscription.Status.CANCELLED, current_period_end=timezone.now() + hours(24)
        )

        assert subscription.effective_plan() == FREE

    def test_past_due_keeps_the_plan_during_the_grace_period_only(self, pay_fast_subscription_factory):
        # PayFast retries failed charges itself for a while (https://developers.payfast.co.za/docs#recurring_billing),
        # so the customer keeps access for PAST_DUE_GRACE_DAYS after the unpaid renewal date.
        period_end = timezone.now()
        subscription = pay_fast_subscription_factory(
            monthly=True, status=PayFastSubscription.Status.PAST_DUE, current_period_end=period_end
        )
        grace = datetime.timedelta(days=PayFastSubscription.PAST_DUE_GRACE_DAYS)

        assert subscription.effective_plan(now=period_end + grace - hours(1)) == MONTHLY
        assert subscription.effective_plan(now=period_end + grace) == FREE

    def test_trialing_subscription_has_its_plan(self, pay_fast_subscription_factory):
        trial_end = timezone.now() + datetime.timedelta(days=7)
        subscription = pay_fast_subscription_factory(
            monthly=True, status=PayFastSubscription.Status.TRIALING, trial_end=trial_end, current_period_end=trial_end
        )

        assert subscription.effective_plan() == MONTHLY
        assert subscription.is_trialing


class TestTrialEligibility:
    def test_a_used_trial_cannot_be_activated_again(self, pay_fast_subscription_factory):
        # Same rule as Stripe's apps.finances.utils.customer_can_activate_trial: one trial per tenant.
        assert not pay_fast_subscription_factory(has_used_trial=True).can_activate_trial
