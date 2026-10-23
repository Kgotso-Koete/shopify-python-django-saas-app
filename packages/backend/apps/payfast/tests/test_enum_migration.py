"""
Tests for the data migration that rewrites the PayFast app's stored enum values to their member names
(PayFast plan section 14, agents.md section 5.3b): "active" becomes "ACTIVE", "subscription" becomes
"SUBSCRIPTION", "complete" becomes "COMPLETE", and the frequency codes 3 and 6 become "MONTHLY" and
"ANNUAL", with a reverse that restores the old values. PayFast is released, so this runs on production
data: the reverse matters.

The functions are called directly, as the WhatsApp app's test_enum_migration.py does, and never with
transaction=True (agents.md section 2.6). The test database is fully migrated, so the frequency columns
are already text and hold the old codes as "3" and "6", as they will just after the migration's type
change.

Kind of test: integration (agents.md section 2.5). Why: rows in the test database are rewritten by the
migration's own functions; nothing is faked.
"""

import importlib

import pytest
from django.apps import apps as django_apps
from django.db import migrations

from ..models import PayFastCheckout, PayFastPayment, PayFastSubscription

pytestmark = pytest.mark.django_db

migration = importlib.import_module("apps.payfast.migrations.0004_enum_values_are_member_names")


@pytest.fixture
def old_rows(pay_fast_subscription_factory, pay_fast_checkout_factory, pay_fast_payment_factory):
    """A subscription, a checkout and a payment, with the values stored before section 14."""
    subscription = pay_fast_subscription_factory(monthly=True)
    checkout = pay_fast_checkout_factory()
    payment = pay_fast_payment_factory()
    # .update() writes the raw values, as the old code stored them.
    PayFastSubscription.objects.filter(pk=subscription.pk).update(status="trialing", frequency="3")
    PayFastCheckout.objects.filter(pk=checkout.pk).update(kind="subscription", status="complete", frequency="6")
    PayFastPayment.objects.filter(pk=payment.pk).update(kind="donation")
    return subscription, checkout, payment


def stored(subscription, checkout, payment):
    return (
        PayFastSubscription.objects.filter(pk=subscription.pk).values_list("status", "frequency").get(),
        PayFastCheckout.objects.filter(pk=checkout.pk).values_list("kind", "status", "frequency").get(),
        PayFastPayment.objects.filter(pk=payment.pk).values_list("kind", flat=True).get(),
    )


def test_old_values_become_member_names(old_rows):
    migration.store_member_names(django_apps, None)

    assert stored(*old_rows) == (("TRIALING", "MONTHLY"), ("SUBSCRIPTION", "COMPLETE", "ANNUAL"), "DONATION")


def test_the_reverse_restores_the_old_values(old_rows):
    migration.store_member_names(django_apps, None)

    migration.store_old_values(django_apps, None)

    assert stored(*old_rows) == (("trialing", "3"), ("subscription", "complete", "6"), "donation")


def test_a_free_plans_empty_frequency_stays_empty(pay_fast_subscription_factory):
    # The free plan has no billing frequency (constants.plan_prices), stored as NULL.
    subscription = pay_fast_subscription_factory()

    migration.store_member_names(django_apps, None)

    subscription.refresh_from_db()
    assert subscription.frequency is None


def test_payfasts_own_payment_status_is_left_as_received(pay_fast_payment_factory):
    # COMPLETE or CANCELLED, as PayFast sent it: not one of our enums (plan section 14).
    payment = pay_fast_payment_factory(payment_status="CANCELLED")

    migration.store_member_names(django_apps, None)

    payment.refresh_from_db()
    assert payment.payment_status == "CANCELLED"


def test_the_frequency_columns_become_text_before_the_rows_change():
    # The names don't fit in an integer column; going back, the codes are cast to integers after the
    # reverse has put them back.
    kinds = [type(operation) for operation in migration.Migration.operations]

    assert kinds.index(migrations.AlterField) < kinds.index(migrations.RunPython)
