"""
Tests for apps/payfast/services.py: the PayFast subscription and donation lifecycle.

The rule throughout (plan section 2): PayFast behaves like the Stripe implementation wherever both APIs
allow it. Same plans, one trial per tenant, plan changes at the end of the period, cancellation at
the end of the period, the same emails. The PayFast API is always the `payfast_api` mock, so no
request leaves the test. ITN security checks are tested in test_itn.py; here `process_itn` receives
data that already passed them.
"""

import datetime
import uuid
from decimal import Decimal
from unittest import mock

import pytest
from django.db import connection
from django.utils import timezone

from apps.finances import constants as finance_constants
from apps.finances import notifications
from .. import constants, services, signature
from ..client import PayFastApiError
from ..itn import ItnRejected
from ..models import PayFastCheckout, PayFastPayment, PayFastSubscription

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("payfast_backend")]

FREE = finance_constants.FREE_PLAN.name
MONTHLY = finance_constants.MONTHLY_PLAN.name
YEARLY = finance_constants.YEARLY_PLAN.name
RETURN_URL = "https://app.example.com/en/tenant-1/subscriptions/payfast-return"
CANCEL_URL = "https://app.example.com/en/tenant-1/subscriptions/current-subscription/edit"
NOW = "2026-10-01 10:00:00"
NOW_DT = datetime.datetime(2026, 10, 1, 10, 0, tzinfo=datetime.timezone.utc)


def subscription_checkout(tenant, user, plan=MONTHLY):
    return services.create_subscription_checkout(
        tenant=tenant, user=user, plan_name=plan, return_url=RETURN_URL, cancel_url=CANCEL_URL
    )


def itn_data(**fields):
    """An ITN's fields (already verified), with realistic defaults for a completed payment."""
    return {
        "pf_payment_id": str(uuid.uuid4().int)[:9],
        "payment_status": "COMPLETE",
        "item_name": "Monthly plan",
        "amount_gross": "199.00",
        "amount_fee": "-4.58",
        "amount_net": "194.42",
        "merchant_id": "10000100",
        **fields,
    }


@pytest.fixture
def owner(user_factory):
    return user_factory()


@pytest.fixture
def paid_subscription(pay_fast_subscription_factory):
    """An active monthly subscription whose current period ends on 2026-10-31."""
    return pay_fast_subscription_factory(
        monthly=True,
        current_period_start=NOW_DT - datetime.timedelta(days=5),
        current_period_end=datetime.datetime(2026, 10, 31, 10, 0, tzinfo=datetime.timezone.utc),
    )


class TestInitializeTenant:
    def test_creates_a_free_subscription_once(self, tenant):
        first = services.initialize_tenant(tenant)
        second = services.initialize_tenant(tenant)

        assert first.pk == second.pk
        assert first.plan == FREE

    def test_get_subscription_creates_one_for_tenants_that_predate_payfast(self, tenant):
        PayFastSubscription.objects.filter(tenant=tenant).delete()

        assert services.get_subscription(tenant).plan == FREE


class TestSubscriptionCheckout:
    def test_first_checkout_is_a_free_trial(self, freezer, tenant, owner):
        # Trial parity with Stripe: SUBSCRIPTION_TRIAL_PERIOD_DAYS, once per tenant, card captured
        # at checkout. PayFast allows an R0.00 initial amount for exactly this
        # (https://developers.payfast.co.za/docs#subscriptions).
        freezer.move_to(NOW)

        form = subscription_checkout(tenant, owner)

        fields = form.fields
        assert form.action_url == "https://sandbox.payfast.co.za/eng/process"
        assert fields["amount"] == "0.00"
        assert fields["recurring_amount"] == "199.00"
        assert fields["billing_date"] == "2026-10-08"
        assert fields["subscription_type"] == "1"
        assert fields["frequency"] == "3"
        assert fields["cycles"] == "0"
        # We send our own trial-ending email (as Stripe does), so PayFast's buyer email is switched off.
        assert fields["subscription_notify_buyer"] == "false"
        checkout = PayFastCheckout.objects.get(m_payment_id=form.m_payment_id)
        assert checkout.is_trial
        assert checkout.amount == Decimal("0.00")
        assert checkout.created_by == owner

    def test_checkout_after_a_used_trial_charges_the_first_period(self, tenant, owner, pay_fast_subscription_factory):
        pay_fast_subscription_factory(tenant=tenant, has_used_trial=True)

        fields = subscription_checkout(tenant, owner, plan=YEARLY).fields

        assert fields["amount"] == "1990.00"
        assert fields["recurring_amount"] == "1990.00"
        assert fields["frequency"] == "6"
        # No billing_date: PayFast then bills from today, the initial payment being the first period.
        assert "billing_date" not in fields

    def test_form_is_signed_and_points_back_to_us(self, tenant, owner):
        form = subscription_checkout(tenant, owner)

        fields = dict(form.fields)
        received_signature = fields.pop("signature")
        assert received_signature == signature.checkout_signature(fields, "jt7NOE43FZPn")
        assert fields["merchant_id"] == "10000100"
        assert fields["merchant_key"] == "46f0cd694581a"
        assert fields["notify_url"] == "https://api.example.com/api/payfast/notify/"
        assert fields["m_payment_id"] == str(form.m_payment_id)
        # The return page polls this checkout's status, so it gets the id in the URL.
        assert fields["return_url"] == f"{RETURN_URL}?m={form.m_payment_id}"
        assert fields["cancel_url"] == CANCEL_URL
        assert fields["email_address"] == owner.email

    def test_free_or_unknown_plan_cannot_be_bought(self, tenant, owner):
        for plan in (FREE, "platinum_plan"):
            with pytest.raises(services.PayFastError):
                subscription_checkout(tenant, owner, plan=plan)


class TestDonationCheckout:
    def test_donation_is_a_once_off_payment(self, tenant, owner):
        form = services.create_donation_checkout(
            tenant=tenant, user=owner, amount="100", return_url=RETURN_URL, cancel_url=CANCEL_URL
        )

        assert form.fields["amount"] == "100.00"
        assert form.fields["item_name"] == "Donation"
        assert "subscription_type" not in form.fields
        checkout = PayFastCheckout.objects.get(m_payment_id=form.m_payment_id)
        assert checkout.kind == PayFastCheckout.Kind.DONATION

    def test_only_configured_amounts_are_accepted(self, tenant, owner):
        # Like Stripe's PaymentIntentSerializer.product ChoiceField: the client can't pick a price.
        with pytest.raises(services.PayFastError):
            services.create_donation_checkout(
                tenant=tenant, user=owner, amount="1", return_url=RETURN_URL, cancel_url=CANCEL_URL
            )


class TestProcessItnFirstSubscriptionPayment:
    def test_trial_checkout_starts_a_trialing_subscription(self, freezer, tenant, owner):
        freezer.move_to(NOW)
        form = subscription_checkout(tenant, owner)

        outcome = services.process_itn(
            itn_data(m_payment_id=str(form.m_payment_id), amount_gross="0.00", token="tok-1", billing_date="2026-10-08")
        )

        assert outcome == "processed"
        subscription = services.get_subscription(tenant)
        assert subscription.plan == MONTHLY
        assert subscription.status == PayFastSubscription.Status.TRIALING
        assert subscription.token == "tok-1"
        assert subscription.amount == Decimal("199.00")
        assert subscription.has_used_trial
        assert subscription.trial_end == NOW_DT + datetime.timedelta(days=7)
        assert subscription.current_period_end == subscription.trial_end
        assert PayFastCheckout.objects.get(m_payment_id=form.m_payment_id).status == PayFastCheckout.Status.COMPLETE

    def test_paid_checkout_starts_an_active_subscription_and_records_the_payment(
        self, freezer, tenant, owner, pay_fast_subscription_factory
    ):
        freezer.move_to(NOW)
        pay_fast_subscription_factory(tenant=tenant, has_used_trial=True)
        form = subscription_checkout(tenant, owner)

        services.process_itn(itn_data(m_payment_id=str(form.m_payment_id), pf_payment_id="555", token="tok-2"))

        subscription = services.get_subscription(tenant)
        assert subscription.status == PayFastSubscription.Status.ACTIVE
        assert subscription.current_period_end == datetime.datetime(2026, 11, 1, 10, 0, tzinfo=datetime.timezone.utc)
        payment = PayFastPayment.objects.get(pf_payment_id="555")
        assert payment.kind == PayFastPayment.Kind.SUBSCRIPTION
        assert payment.plan == MONTHLY
        assert payment.subscription == subscription
        assert payment.amount_gross == Decimal("199.00")

    def test_amount_other_than_expected_is_rejected(self, tenant, owner, pay_fast_subscription_factory):
        # Security check 3 (https://developers.payfast.co.za/docs#step_4_confirm_payment): the amount
        # must be the one WE expected, taken from our own checkout record, never from the ITN.
        pay_fast_subscription_factory(tenant=tenant, has_used_trial=True)
        form = subscription_checkout(tenant, owner)

        with pytest.raises(ItnRejected, match="amount"):
            services.process_itn(itn_data(m_payment_id=str(form.m_payment_id), amount_gross="1.00", token="t"))

        assert services.get_subscription(tenant).plan == FREE


class TestProcessItnRecurring:
    def test_renewal_moves_the_period_forward(self, paid_subscription):
        old_end = paid_subscription.current_period_end

        services.process_itn(itn_data(token=paid_subscription.token, pf_payment_id="777"))

        paid_subscription.refresh_from_db()
        assert paid_subscription.current_period_start == old_end
        assert paid_subscription.current_period_end == datetime.datetime(
            2026, 11, 30, 10, 0, tzinfo=datetime.timezone.utc
        )
        assert PayFastPayment.objects.get(pf_payment_id="777").plan == MONTHLY

    def test_first_charge_after_trial_makes_the_subscription_active(self, paid_subscription):
        paid_subscription.status = PayFastSubscription.Status.TRIALING
        paid_subscription.save()

        services.process_itn(itn_data(token=paid_subscription.token))

        paid_subscription.refresh_from_db()
        assert paid_subscription.status == PayFastSubscription.Status.ACTIVE

    def test_pending_plan_change_is_applied_on_the_next_charge(self, paid_subscription):
        paid_subscription.pending_plan = YEARLY
        paid_subscription.pending_amount = Decimal("1990.00")
        paid_subscription.save()

        services.process_itn(itn_data(token=paid_subscription.token, amount_gross="1990.00", pf_payment_id="888"))

        paid_subscription.refresh_from_db()
        assert paid_subscription.plan == YEARLY
        assert paid_subscription.amount == Decimal("1990.00")
        assert paid_subscription.frequency == constants.Frequency.ANNUAL
        assert paid_subscription.pending_plan == ""
        assert paid_subscription.current_period_end == datetime.datetime(
            2027, 10, 31, 10, 0, tzinfo=datetime.timezone.utc
        )
        assert PayFastPayment.objects.get(pf_payment_id="888").plan == YEARLY

    def test_renewal_clears_past_due(self, paid_subscription):
        paid_subscription.status = PayFastSubscription.Status.PAST_DUE
        paid_subscription.payment_failed_notified_at = timezone.now()
        paid_subscription.save()

        services.process_itn(itn_data(token=paid_subscription.token))

        paid_subscription.refresh_from_db()
        assert paid_subscription.status == PayFastSubscription.Status.ACTIVE
        assert paid_subscription.payment_failed_notified_at is None

    def test_renewal_with_wrong_amount_is_rejected(self, paid_subscription):
        with pytest.raises(ItnRejected, match="amount"):
            services.process_itn(itn_data(token=paid_subscription.token, amount_gross="5.00"))


class TestProcessItnCancelled:
    def test_cancellation_from_payfast_ends_the_subscription_at_period_end(self, paid_subscription):
        # A buyer or the merchant can cancel on PayFast's side; PayFast then sends payment_status=CANCELLED
        # (https://developers.payfast.co.za/docs#step_4_confirm_payment). Access lasts until the period ends.
        services.process_itn(itn_data(token=paid_subscription.token, payment_status="CANCELLED", amount_gross="0.00"))

        paid_subscription.refresh_from_db()
        assert paid_subscription.cancel_at_period_end
        assert paid_subscription.effective_plan() == MONTHLY
        assert not PayFastPayment.objects.filter(subscription=paid_subscription, payment_status="COMPLETE").exists()

    def test_cancellation_carrying_the_sign_up_payment_id_is_applied(self, paid_subscription):
        # Seen in the sandbox on 2026-10-02: a CANCELLED ITN carries the pf_payment_id of the
        # subscription's first (sign-up) ITN, so it must not be mistaken for a re-sent copy of it.
        services.process_itn(itn_data(token=paid_subscription.token, pf_payment_id="3424910", amount_gross="199.00"))

        outcome = services.process_itn(
            itn_data(token=paid_subscription.token, pf_payment_id="3424910", payment_status="CANCELLED")
        )

        assert outcome == "processed"
        paid_subscription.refresh_from_db()
        assert paid_subscription.cancel_at_period_end
        # The charge stays recorded once, as the charge it was.
        assert list(
            PayFastPayment.objects.filter(pf_payment_id="3424910").values_list("payment_status", flat=True)
        ) == ["COMPLETE"]

    def test_a_resent_cancellation_is_harmless(self, paid_subscription):
        data = itn_data(token=paid_subscription.token, pf_payment_id="3424911", payment_status="CANCELLED")
        services.process_itn(data)

        services.process_itn(data)

        paid_subscription.refresh_from_db()
        assert paid_subscription.cancel_at_period_end
        assert PayFastPayment.objects.filter(pf_payment_id="3424911").count() == 1


class TestProcessItnDonation:
    def test_donation_is_recorded(self, tenant, owner):
        form = services.create_donation_checkout(
            tenant=tenant, user=owner, amount="50", return_url=RETURN_URL, cancel_url=CANCEL_URL
        )

        services.process_itn(itn_data(m_payment_id=str(form.m_payment_id), amount_gross="50.00", pf_payment_id="999"))

        payment = PayFastPayment.objects.get(pf_payment_id="999")
        assert payment.kind == PayFastPayment.Kind.DONATION
        assert payment.tenant == tenant
        assert PayFastCheckout.objects.get(m_payment_id=form.m_payment_id).status == PayFastCheckout.Status.COMPLETE
        # A donation never touches the subscription.
        assert services.get_subscription(tenant).plan == FREE


class TestProcessItnSafety:
    def test_the_same_itn_twice_is_processed_once(self, paid_subscription):
        # PayFast re-sends an ITN until it gets a 200 (docs#step_4_confirm_payment), so repeats are normal.
        data = itn_data(token=paid_subscription.token, pf_payment_id="4242")
        services.process_itn(data)
        paid_subscription.refresh_from_db()
        period_end_after_first = paid_subscription.current_period_end

        assert services.process_itn(data) == "duplicate"

        paid_subscription.refresh_from_db()
        assert paid_subscription.current_period_end == period_end_after_first
        assert PayFastPayment.objects.filter(pf_payment_id="4242").count() == 1

    def test_itn_for_something_we_never_started_is_ignored(self):
        assert services.process_itn(itn_data(m_payment_id="not-ours", pf_payment_id="1")) == "ignored"
        assert not PayFastPayment.objects.exists()


class TestPlanChangeCheckout:
    """
    A paying tenant switches plan with a new PayFast subscription, not PayFast's update API (which
    fails in the sandbox; see the plan, section 10). The new subscription charges R0 now and starts billing
    when the current paid period ends, so the switch applies at period end, as on Stripe.
    """

    def test_switch_is_a_r0_checkout_billing_from_the_end_of_the_current_period(self, owner, paid_subscription):
        form = subscription_checkout(paid_subscription.tenant, owner, plan=YEARLY)

        fields = form.fields
        assert fields["amount"] == "0.00"
        assert fields["recurring_amount"] == "1990.00"
        assert fields["frequency"] == "6"
        assert fields["subscription_type"] == "1"
        # The paid period ends 2026-10-31, so that's when the new plan is first charged.
        assert fields["billing_date"] == "2026-10-31"
        checkout = PayFastCheckout.objects.get(m_payment_id=form.m_payment_id)
        assert checkout.replaces_token == paid_subscription.token
        assert not checkout.is_trial

    def test_switch_during_a_trial_bills_from_the_trial_end(self, owner, paid_subscription):
        trial_end = datetime.datetime(2026, 10, 8, 10, 0, tzinfo=datetime.timezone.utc)
        paid_subscription.status = PayFastSubscription.Status.TRIALING
        paid_subscription.trial_end = trial_end
        paid_subscription.current_period_end = trial_end
        paid_subscription.save()

        form = subscription_checkout(paid_subscription.tenant, owner, plan=YEARLY)

        assert form.fields["amount"] == "0.00"
        assert form.fields["billing_date"] == "2026-10-08"

    def test_current_plan_cannot_be_chosen_again(self, owner, paid_subscription):
        with pytest.raises(services.PayFastError, match="current plan"):
            subscription_checkout(paid_subscription.tenant, owner, plan=MONTHLY)

    def test_already_scheduled_plan_cannot_be_chosen_again(self, owner, paid_subscription):
        paid_subscription.pending_plan = YEARLY
        paid_subscription.save()

        with pytest.raises(services.PayFastError, match="scheduled"):
            subscription_checkout(paid_subscription.tenant, owner, plan=YEARLY)

    def test_cancelled_subscription_cannot_switch(self, owner, paid_subscription):
        paid_subscription.cancel_at_period_end = True
        paid_subscription.save()

        with pytest.raises(services.PayFastError, match="cancelled"):
            subscription_checkout(paid_subscription.tenant, owner, plan=YEARLY)


class TestProcessItnPlanChange:
    @pytest.fixture
    def switch_checkout(self, owner, paid_subscription):
        return subscription_checkout(paid_subscription.tenant, owner, plan=YEARLY)

    def switch_itn(self, switch_checkout, token="new-yearly-token"):
        return itn_data(
            m_payment_id=str(switch_checkout.m_payment_id),
            pf_payment_id="900",
            amount_gross="0.00",
            amount_fee="0.00",
            amount_net="0.00",
            token=token,
            billing_date="2026-10-31",
        )

    def test_new_subscription_is_scheduled_and_the_old_one_cancelled(
        self, paid_subscription, switch_checkout, payfast_api
    ):
        old_token = paid_subscription.token

        assert services.process_itn(self.switch_itn(switch_checkout)) == "processed"

        paid_subscription.refresh_from_db()
        # The current period is still the paid monthly one; yearly starts at its end.
        assert paid_subscription.plan == MONTHLY
        assert paid_subscription.pending_plan == YEARLY
        assert paid_subscription.pending_amount == Decimal("1990.00")
        assert paid_subscription.token == "new-yearly-token"
        assert paid_subscription.current_period_end == datetime.datetime(
            2026, 10, 31, 10, 0, tzinfo=datetime.timezone.utc
        )
        # Without this the customer would be charged by both subscriptions.
        payfast_api.cancel.assert_called_once_with(old_token)
        assert paid_subscription.superseded_token == ""
        assert PayFastCheckout.objects.get(m_payment_id=switch_checkout.m_payment_id).status == "complete"

    def test_first_charge_of_the_new_subscription_applies_the_new_plan(
        self, paid_subscription, switch_checkout, payfast_api
    ):
        services.process_itn(self.switch_itn(switch_checkout))

        services.process_itn(itn_data(token="new-yearly-token", amount_gross="1990.00", pf_payment_id="901"))

        paid_subscription.refresh_from_db()
        assert paid_subscription.plan == YEARLY
        assert paid_subscription.frequency == constants.Frequency.ANNUAL
        assert paid_subscription.pending_plan == ""
        assert paid_subscription.current_period_end == datetime.datetime(
            2027, 10, 31, 10, 0, tzinfo=datetime.timezone.utc
        )

    def test_the_old_subscriptions_cancellation_itn_is_ignored(self, paid_subscription, switch_checkout, payfast_api):
        old_token = paid_subscription.token
        services.process_itn(self.switch_itn(switch_checkout))

        # PayFast confirms the cancellation of the replaced subscription with its own ITN.
        services.process_itn(itn_data(token=old_token, payment_status="CANCELLED", amount_gross="0.00"))

        paid_subscription.refresh_from_db()
        assert not paid_subscription.cancel_at_period_end
        assert paid_subscription.pending_plan == YEARLY

    def test_charge_on_the_replaced_subscription_is_recorded_and_flagged(
        self, caplog, paid_subscription, switch_checkout, payfast_api
    ):
        # Plan section 12, issue 2. Until PayFast has cancelled the old subscription, it can still bill it.
        # The money is taken either way, so it must show in the history and be flagged for a refund.
        old_token = paid_subscription.token
        payfast_api.cancel.side_effect = PayFastApiError("boom")
        services.process_itn(self.switch_itn(switch_checkout))
        paid_subscription.refresh_from_db()
        period_end = paid_subscription.current_period_end

        outcome = services.process_itn(itn_data(token=old_token, pf_payment_id="950"))

        assert outcome == "processed"
        payment = PayFastPayment.objects.get(pf_payment_id="950")
        assert payment.subscription == paid_subscription
        assert payment.plan == MONTHLY
        # It pays for nothing new: the period and the scheduled switch are unchanged.
        paid_subscription.refresh_from_db()
        assert paid_subscription.current_period_end == period_end
        assert paid_subscription.pending_plan == YEARLY
        assert "refund" in caplog.text

    def test_charge_on_the_replaced_subscription_is_recorded_after_it_was_cancelled(
        self, paid_subscription, switch_checkout, payfast_api
    ):
        # The charge can also land just before our cancel call took effect, after superseded_token
        # was cleared; the completed plan-change checkout still links the old token to the tenant.
        old_token = paid_subscription.token
        services.process_itn(self.switch_itn(switch_checkout))

        assert services.process_itn(itn_data(token=old_token, pf_payment_id="951")) == "processed"

        assert PayFastPayment.objects.get(pf_payment_id="951").tenant == paid_subscription.tenant

    def test_cancellation_itn_for_the_replaced_subscription_ends_the_retries(
        self, paid_subscription, switch_checkout, payfast_api
    ):
        # If our cancel call failed but PayFast cancelled it anyway, its CANCELLED ITN settles it.
        old_token = paid_subscription.token
        payfast_api.cancel.side_effect = PayFastApiError("boom")
        services.process_itn(self.switch_itn(switch_checkout))

        services.process_itn(itn_data(token=old_token, payment_status="CANCELLED", amount_gross="0.00"))

        paid_subscription.refresh_from_db()
        assert paid_subscription.superseded_token == ""
        assert not paid_subscription.cancel_at_period_end

    def test_cancellation_of_the_replaced_subscription_with_its_sign_up_payment_id_ends_the_retries(
        self, paid_subscription, switch_checkout, payfast_api, pay_fast_payment_factory
    ):
        # The same as above, with the pf_payment_id PayFast really sends: the old subscription's first ITN's.
        old_token = paid_subscription.token
        pay_fast_payment_factory(tenant=paid_subscription.tenant, pf_payment_id="3424910", amount_gross=Decimal("0.00"))
        payfast_api.cancel.side_effect = PayFastApiError("boom")
        services.process_itn(self.switch_itn(switch_checkout))

        services.process_itn(
            itn_data(token=old_token, pf_payment_id="3424910", payment_status="CANCELLED", amount_gross="0.00")
        )

        paid_subscription.refresh_from_db()
        assert paid_subscription.superseded_token == ""

    def test_failed_cancellation_of_the_old_subscription_is_retried_daily(
        self, freezer, paid_subscription, switch_checkout, payfast_api
    ):
        old_token = paid_subscription.token
        payfast_api.cancel.side_effect = PayFastApiError("boom")

        services.process_itn(self.switch_itn(switch_checkout))

        paid_subscription.refresh_from_db()
        assert paid_subscription.superseded_token == old_token

        payfast_api.cancel.side_effect = None
        with mock.patch("common.emails.send_email"):
            services.run_daily_maintenance()

        paid_subscription.refresh_from_db()
        assert paid_subscription.superseded_token == ""
        assert payfast_api.cancel.call_args_list[-1] == mock.call(old_token)


@pytest.fixture
def api_called_outside_transactions(payfast_api):
    """
    Fails the test if a PayFast API call is made while a database transaction is open. PayFast sends its
    CANCELLED ITN before it answers a cancel call, and our ITN handler needs the subscription's row lock:
    a lock held across the call makes both wait until the call times out (seen in the sandbox on 2026-10-02).
    The test itself runs inside pytest-django's transaction, so only blocks opened beyond that count.
    """
    baseline = len(connection.atomic_blocks)
    calls = []

    def record(*args, **kwargs):
        calls.append(len(connection.atomic_blocks) - baseline)

    payfast_api.cancel.side_effect = record
    return calls


class TestPayFastApiIsCalledWithoutHoldingLocks:
    def test_cancel_subscription(self, paid_subscription, api_called_outside_transactions):
        services.cancel_subscription(tenant=paid_subscription.tenant)

        assert api_called_outside_transactions == [0]
        paid_subscription.refresh_from_db()
        assert paid_subscription.cancel_at_period_end

    def test_cancel_subscription_with_a_superseded_token(self, paid_subscription, api_called_outside_transactions):
        paid_subscription.superseded_token = "old-token"
        paid_subscription.save()

        services.cancel_subscription(tenant=paid_subscription.tenant)

        assert api_called_outside_transactions == [0, 0]

    def test_plan_change_cancels_the_old_subscription_after_committing(
        self, owner, paid_subscription, api_called_outside_transactions
    ):
        form = subscription_checkout(paid_subscription.tenant, owner, plan=YEARLY)

        services.process_itn(
            itn_data(m_payment_id=str(form.m_payment_id), amount_gross="0.00", token="new-yearly-token")
        )

        assert api_called_outside_transactions == [0]
        paid_subscription.refresh_from_db()
        assert paid_subscription.token == "new-yearly-token"
        assert paid_subscription.superseded_token == ""


class TestCancelSubscription:
    def test_cancel_stops_billing_now_but_keeps_access_until_period_end(self, paid_subscription, payfast_api):
        subscription = services.cancel_subscription(tenant=paid_subscription.tenant)

        payfast_api.cancel.assert_called_once_with(paid_subscription.token)
        assert subscription.cancel_at_period_end
        assert subscription.effective_plan() == MONTHLY

    def test_cancel_clears_a_pending_plan_change(self, paid_subscription, payfast_api):
        paid_subscription.pending_plan = YEARLY
        paid_subscription.save()

        assert services.cancel_subscription(tenant=paid_subscription.tenant).pending_plan == ""

    def test_free_tenant_has_nothing_to_cancel(self, tenant, payfast_api):
        with pytest.raises(services.PayFastError):
            services.cancel_subscription(tenant=tenant)
        payfast_api.cancel.assert_not_called()


class TestCancelTenantSubscriptionImmediately:
    def test_deleting_a_tenant_cancels_its_payfast_subscription(self, paid_subscription, payfast_api):
        services.cancel_tenant_subscription_immediately(paid_subscription.tenant)

        payfast_api.cancel.assert_called_once_with(paid_subscription.token)

    def test_deleting_a_tenant_also_cancels_a_superseded_subscription(self, paid_subscription, payfast_api):
        paid_subscription.superseded_token = "old-token"
        paid_subscription.save()

        services.cancel_tenant_subscription_immediately(paid_subscription.tenant)

        assert mock.call("old-token") in payfast_api.cancel.call_args_list
        assert mock.call(paid_subscription.token) in payfast_api.cancel.call_args_list

    def test_tenant_without_a_token_makes_no_api_call(self, tenant, payfast_api):
        services.cancel_tenant_subscription_immediately(tenant)

        payfast_api.cancel.assert_not_called()


class TestCardUpdateUrl:
    def test_card_update_url_uses_the_subscription_token(self, paid_subscription):
        url = services.card_update_url(paid_subscription, return_url="https://app.example.com/back")

        assert url.startswith(f"https://www.payfast.co.za/eng/recurring/update/{paid_subscription.token}?return=")

    def test_no_card_no_url(self, tenant):
        assert services.card_update_url(services.get_subscription(tenant), return_url="https://x.example") is None


@mock.patch("common.emails.send_email")
class TestDailyMaintenance:
    def test_trial_ending_soon_email_is_sent_once_three_days_before(
        self, send_email, freezer, pay_fast_subscription_factory, payfast_api
    ):
        # Stripe sends TrialExpiresSoonEmail from `customer.subscription.trial_will_end`, three days
        # before the trial ends. PayFast has no such event, so the daily task does it.
        freezer.move_to(NOW)
        trial_end = NOW_DT + datetime.timedelta(days=3)
        subscription = pay_fast_subscription_factory(
            monthly=True, status=PayFastSubscription.Status.TRIALING, trial_end=trial_end, current_period_end=trial_end
        )

        services.run_daily_maintenance()
        services.run_daily_maintenance()

        send_email.apply_async.assert_called_once_with(
            (
                subscription.tenant.email,
                notifications.TrialExpiresSoonEmail.name,
                {"expiry_date": "2026-10-04T10:00:00Z"},
                "en",
            )
        )

    def test_overdue_renewal_that_payfast_did_not_charge_becomes_past_due(
        self, send_email, freezer, paid_subscription, payfast_api
    ):
        # There is no failure ITN; PayFast retries and eventually locks the subscription
        # (https://developers.payfast.co.za/docs#recurring_billing). A renewal more than a day
        # overdue is checked with /fetch; if the run date hasn't moved on, the charge didn't happen.
        freezer.move_to("2026-11-02 10:00:00")
        payfast_api.fetch.return_value = {"status_text": "ACTIVE", "run_date": "2026-10-31T00:00:00+02:00"}

        services.run_daily_maintenance()
        services.run_daily_maintenance()

        paid_subscription.refresh_from_db()
        assert paid_subscription.status == PayFastSubscription.Status.PAST_DUE
        # Same email as Stripe's invoice.payment_failed handler, sent once.
        send_email.apply_async.assert_called_once_with(
            (paid_subscription.tenant.email, notifications.SubscriptionErrorEmail.name, None, "en")
        )

    def test_overdue_renewal_that_payfast_did_charge_catches_up(
        self, send_email, freezer, paid_subscription, payfast_api
    ):
        # The charge went through but its ITN never arrived: PayFast's run date has already moved on.
        freezer.move_to("2026-11-02 10:00:00")
        payfast_api.fetch.return_value = {"status_text": "ACTIVE", "run_date": "2026-11-30T00:00:00+02:00"}

        services.run_daily_maintenance()

        paid_subscription.refresh_from_db()
        assert paid_subscription.status == PayFastSubscription.Status.ACTIVE
        assert paid_subscription.current_period_end.date() == datetime.date(2026, 11, 30)
        send_email.apply_async.assert_not_called()

    def test_caught_up_renewal_records_the_charge(self, send_email, freezer, paid_subscription, payfast_api):
        # Plan section 12, issue 1: the charge happened, so it belongs in the transaction history even
        # though its ITN was lost. It is marked as caught up, since only /fetch vouched for it.
        freezer.move_to("2026-11-02 10:00:00")
        payfast_api.fetch.return_value = {"status_text": "ACTIVE", "run_date": "2026-11-30T00:00:00+02:00"}

        services.run_daily_maintenance()

        payment = PayFastPayment.objects.get(subscription=paid_subscription)
        assert payment.caught_up
        assert payment.kind == PayFastPayment.Kind.SUBSCRIPTION
        assert payment.plan == MONTHLY
        assert payment.amount_gross == Decimal("199.00")
        assert payment.payment_status == "COMPLETE"

    def test_caught_up_renewal_applies_a_pending_plan_change(self, send_email, freezer, paid_subscription, payfast_api):
        # The lost ITN may be the first charge of a plan switch: the switch must still happen.
        paid_subscription.pending_plan = YEARLY
        paid_subscription.pending_amount = Decimal("1990.00")
        paid_subscription.save()
        freezer.move_to("2026-11-02 10:00:00")
        payfast_api.fetch.return_value = {"status_text": "ACTIVE", "run_date": "2027-10-31T00:00:00+02:00"}

        services.run_daily_maintenance()

        paid_subscription.refresh_from_db()
        assert paid_subscription.plan == YEARLY
        assert paid_subscription.amount == Decimal("1990.00")
        assert paid_subscription.frequency == constants.Frequency.ANNUAL
        assert paid_subscription.pending_plan == ""
        assert paid_subscription.current_period_end.date() == datetime.date(2027, 10, 31)
        payment = PayFastPayment.objects.get(subscription=paid_subscription)
        assert payment.plan == YEARLY
        assert payment.amount_gross == Decimal("1990.00")

    def test_late_itn_after_a_catch_up_completes_the_record_without_renewing_twice(
        self, send_email, freezer, paid_subscription, payfast_api
    ):
        # PayFast keeps re-sending an ITN, so the "lost" one may still arrive after the catch-up.
        freezer.move_to("2026-11-02 10:00:00")
        payfast_api.fetch.return_value = {"status_text": "ACTIVE", "run_date": "2026-11-30T00:00:00+02:00"}
        services.run_daily_maintenance()

        assert services.process_itn(itn_data(token=paid_subscription.token, pf_payment_id="777")) == "processed"

        paid_subscription.refresh_from_db()
        assert paid_subscription.current_period_end.date() == datetime.date(2026, 11, 30)
        payment = PayFastPayment.objects.get(subscription=paid_subscription)
        assert payment.pf_payment_id == "777"
        assert payment.amount_fee == Decimal("-4.58")
        assert payment.caught_up

    def test_next_renewal_after_a_catch_up_whose_itn_never_came_still_renews(
        self, send_email, freezer, paid_subscription, payfast_api
    ):
        # If the lost ITN never arrives, next month's renewal ITN must not be taken for it.
        freezer.move_to("2026-11-02 10:00:00")
        payfast_api.fetch.return_value = {"status_text": "ACTIVE", "run_date": "2026-11-30T00:00:00+02:00"}
        services.run_daily_maintenance()

        freezer.move_to("2026-11-30 08:00:00")
        services.process_itn(itn_data(token=paid_subscription.token, pf_payment_id="778"))

        paid_subscription.refresh_from_db()
        assert paid_subscription.current_period_end.date() == datetime.date(2026, 12, 30)
        assert PayFastPayment.objects.filter(subscription=paid_subscription).count() == 2

    def test_payment_failed_email_is_sent_once_even_if_cancelling_the_trial_fails(
        self, send_email, freezer, paid_subscription, payfast_api
    ):
        # Plan section 12, issue 3: the cancel call fails, so the next daily run retries it, but the
        # customer must not get the "payment failed" email again.
        paid_subscription.status = PayFastSubscription.Status.TRIALING
        paid_subscription.save()
        freezer.move_to("2026-11-02 10:00:00")
        payfast_api.fetch.return_value = {"status_text": "ACTIVE", "run_date": "2026-10-31T00:00:00+02:00"}
        payfast_api.cancel.side_effect = PayFastApiError("boom")

        services.run_daily_maintenance()
        services.run_daily_maintenance()

        send_email.apply_async.assert_called_once()
        assert payfast_api.cancel.call_count == 2

    def test_failed_first_charge_after_a_trial_cancels_the_subscription(
        self, send_email, freezer, paid_subscription, payfast_api
    ):
        # Stripe parity: cancel_trial_subscription_on_payment_failure.
        paid_subscription.status = PayFastSubscription.Status.TRIALING
        paid_subscription.save()
        freezer.move_to("2026-11-02 10:00:00")
        payfast_api.fetch.return_value = {"status_text": "ACTIVE", "run_date": "2026-10-31T00:00:00+02:00"}

        services.run_daily_maintenance()

        paid_subscription.refresh_from_db()
        payfast_api.cancel.assert_called_once_with(paid_subscription.token)
        assert paid_subscription.status == PayFastSubscription.Status.CANCELLED
        assert paid_subscription.effective_plan() == FREE

    def test_subscription_cancelled_at_period_end_returns_to_the_free_plan(
        self, send_email, freezer, paid_subscription, payfast_api
    ):
        paid_subscription.cancel_at_period_end = True
        paid_subscription.save()
        freezer.move_to("2026-11-01 10:00:00")

        services.run_daily_maintenance()

        paid_subscription.refresh_from_db()
        assert paid_subscription.plan == FREE
        assert paid_subscription.token == ""
        assert not paid_subscription.cancel_at_period_end
        # The trial stays used: one trial per tenant, ever.
        assert paid_subscription.has_used_trial
        payfast_api.fetch.assert_not_called()

    def test_past_due_beyond_grace_is_cancelled_and_returns_to_free(
        self, send_email, freezer, paid_subscription, payfast_api
    ):
        paid_subscription.status = PayFastSubscription.Status.PAST_DUE
        paid_subscription.payment_failed_notified_at = timezone.now()
        paid_subscription.save()
        freezer.move_to("2026-11-08 10:00:00")  # 8 days after the unpaid renewal date

        services.run_daily_maintenance()

        paid_subscription.refresh_from_db()
        payfast_api.cancel.assert_called_once()
        assert paid_subscription.plan == FREE

    def test_one_failing_api_call_does_not_stop_the_others(
        self, send_email, freezer, pay_fast_subscription_factory, payfast_api
    ):
        period_end = datetime.datetime(2026, 10, 31, 10, 0, tzinfo=datetime.timezone.utc)
        first = pay_fast_subscription_factory(monthly=True, current_period_end=period_end)
        second = pay_fast_subscription_factory(monthly=True, current_period_end=period_end)
        freezer.move_to("2026-11-02 10:00:00")
        payfast_api.fetch.side_effect = [
            PayFastApiError("boom"),
            {"status_text": "ACTIVE", "run_date": "2026-10-31T00:00:00+02:00"},
        ]

        services.run_daily_maintenance()

        statuses = {s.pk: s.status for s in PayFastSubscription.objects.filter(pk__in=[first.pk, second.pk])}
        assert sorted(statuses.values()) == [PayFastSubscription.Status.ACTIVE, PayFastSubscription.Status.PAST_DUE]


class TestNextPeriodEnd:
    @pytest.mark.parametrize(
        "start, frequency, expected",
        [
            (datetime.datetime(2026, 1, 31, 9), constants.Frequency.MONTHLY, datetime.datetime(2026, 2, 28, 9)),
            (datetime.datetime(2026, 12, 15, 9), constants.Frequency.MONTHLY, datetime.datetime(2027, 1, 15, 9)),
            (datetime.datetime(2028, 2, 29, 9), constants.Frequency.ANNUAL, datetime.datetime(2029, 2, 28, 9)),
        ],
    )
    def test_months_and_years_are_calendar_based(self, start, frequency, expected):
        assert services.next_period_end(start, frequency) == expected
