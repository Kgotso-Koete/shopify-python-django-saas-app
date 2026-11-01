"""
Tests for an organization's features (WhatsApp plan Step 3.2, phase 3 decisions 1, 6 and 7, user
story 26): one answer, the same under PayFast and Stripe.

- the plan that applies now (apps.finances.billing.effective_plan), then what that plan includes,
  from the catalog
- PayFast first, as `PayFastSubscription.effective_plan()` reads it: free, trialing a paid plan,
  paying, cancelled, and a renewal overdue within and past its 7-day grace
- Stripe kept equal: the active schedule's current phase names the plan, and the customer's
  subscription must still be one Stripe bills (active, trialing, or past_due while Stripe retries)
- with PLAN_ENTITLEMENTS_ENABLED off, the default, every organization has every feature
- a user's personal workspace follows the same rule as an organization

Kind of test: integration (agents.md section 2.5). Why: organizations, subscriptions and the
catalog's rows are in the test database; Stripe's objects are dj-stripe's copies, made with
apps.finances' factories, so Stripe itself is never called.
"""

import datetime

import pytest
from django.utils import timezone
from djstripe.enums import SubscriptionStatus

from apps.multitenancy.constants import TenantType
from apps.multitenancy.tests.factories import TenantFactory
from apps.payfast.models import PayFastSubscription
from apps.payfast.tests.factories import PayFastSubscriptionFactory

pytestmark = pytest.mark.django_db

BOTH = {"SHOPIFY", "WHATSAPP"}


def features_of(tenant):
    from apps.entitlements import services

    return services.features_for(tenant)


@pytest.fixture(autouse=True)
def plans_decide(settings):
    settings.PLAN_ENTITLEMENTS_ENABLED = True


class TestWithPayFast:
    @pytest.fixture(autouse=True)
    def payfast(self, settings):
        settings.PAYMENT_BACKEND = settings.PAYMENT_BACKEND_PAYFAST

    @pytest.fixture
    def acme(self):
        return TenantFactory(type=TenantType.ORGANIZATION, name="Acme")

    def test_the_free_plan_has_neither(self, acme):
        assert features_of(acme) == set()

    def test_a_trial_of_a_paid_plan_has_both(self, acme):
        PayFastSubscriptionFactory(
            tenant=acme,
            plan="monthly_plan",
            status=PayFastSubscription.Status.TRIALING,
            trial_end=timezone.now() + datetime.timedelta(days=14),
        )

        assert features_of(acme) == BOTH

    def test_a_paying_organization_has_both(self, acme):
        PayFastSubscriptionFactory(tenant=acme, monthly=True)

        assert features_of(acme) == BOTH

    def test_a_cancelled_plan_has_neither(self, acme):
        PayFastSubscriptionFactory(tenant=acme, monthly=True, status=PayFastSubscription.Status.CANCELLED)

        assert features_of(acme) == set()

    def test_an_overdue_renewal_keeps_both_for_its_grace_then_neither(self, acme):
        overdue = PayFastSubscriptionFactory(
            tenant=acme,
            monthly=True,
            status=PayFastSubscription.Status.PAST_DUE,
            current_period_end=timezone.now() - datetime.timedelta(days=2),
        )
        assert features_of(acme) == BOTH

        overdue.current_period_end = timezone.now() - datetime.timedelta(days=8)
        overdue.save()
        assert features_of(acme) == set()

    def test_a_personal_workspace_follows_the_same_rule(self):
        personal = TenantFactory(type=TenantType.DEFAULT)
        assert features_of(personal) == set()

        PayFastSubscriptionFactory(tenant=personal, monthly=True)
        assert features_of(personal) == BOTH


class TestWithStripe:
    @pytest.fixture(autouse=True)
    def stripe(self, settings):
        settings.PAYMENT_BACKEND = settings.PAYMENT_BACKEND_STRIPE

    @pytest.fixture
    def acme(self):
        return TenantFactory(type=TenantType.ORGANIZATION, name="Acme")

    @pytest.fixture
    def customer(self, acme, customer_factory):
        return customer_factory(subscriber=acme)

    def on(self, customer, price, subscription_schedule_factory, **subscription):
        return subscription_schedule_factory(
            customer=customer, phases=[{"items": [{"price": price.id}], **subscription}]
        )

    def test_without_a_schedule_it_has_neither(self, acme, customer):
        assert features_of(acme) == set()

    def test_the_free_plan_has_neither(self, acme, customer, free_plan_price, subscription_schedule_factory):
        self.on(customer, free_plan_price, subscription_schedule_factory)

        assert features_of(acme) == set()

    def test_a_paying_organization_has_both(self, acme, customer, monthly_plan_price, subscription_schedule_factory):
        self.on(customer, monthly_plan_price, subscription_schedule_factory)

        assert features_of(acme) == BOTH

    def test_a_trial_of_a_paid_plan_has_both(self, acme, customer, yearly_plan_price, subscription_schedule_factory):
        self.on(customer, yearly_plan_price, subscription_schedule_factory, trialing=True)

        assert features_of(acme) == BOTH

    def test_an_overdue_renewal_keeps_both_while_stripe_retries(
        self, acme, customer, monthly_plan_price, subscription_schedule_factory
    ):
        self.on(customer, monthly_plan_price, subscription_schedule_factory, status=SubscriptionStatus.past_due)

        assert features_of(acme) == BOTH

    @pytest.mark.parametrize("status", [SubscriptionStatus.unpaid, SubscriptionStatus.canceled])
    def test_a_subscription_stripe_stopped_billing_has_neither(
        self, acme, customer, monthly_plan_price, subscription_schedule_factory, status
    ):
        self.on(customer, monthly_plan_price, subscription_schedule_factory, status=status)

        assert features_of(acme) == set()


class TestWithTheSettingOff:
    def test_every_organization_has_every_feature(self, settings):
        settings.PLAN_ENTITLEMENTS_ENABLED = False
        settings.PAYMENT_BACKEND = settings.PAYMENT_BACKEND_PAYFAST

        assert features_of(TenantFactory(type=TenantType.ORGANIZATION)) == BOTH


class TestOneFeature:
    def test_has_feature_answers_for_one(self, settings):
        from apps.entitlements import services
        from apps.entitlements.constants import Feature

        settings.PAYMENT_BACKEND = settings.PAYMENT_BACKEND_PAYFAST
        acme = TenantFactory(type=TenantType.ORGANIZATION)

        assert not services.has_feature(acme, Feature.WHATSAPP)
        PayFastSubscriptionFactory(tenant=acme, monthly=True)
        assert services.has_feature(acme, Feature.WHATSAPP)
