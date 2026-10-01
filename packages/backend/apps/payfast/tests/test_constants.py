"""
Tests for apps/payfast/constants.py: plan prices, donation amounts and PayFast URLs.

Plan identities (free_plan, monthly_plan, yearly_plan) are shared with the Stripe implementation
(apps/finances/constants.py); only the ZAR prices and PayFast frequencies are PayFast-specific.
"""

from decimal import Decimal

import pytest
from django.test import override_settings

from apps.finances import constants as finance_constants
from .. import constants

pytestmark = pytest.mark.django_db


class TestFrequency:
    def test_frequency_codes_match_payfast_docs(self):
        # https://developers.payfast.co.za/docs#subscriptions : 3 - Monthly, 6 - Annual
        assert constants.Frequency.MONTHLY == 3
        assert constants.Frequency.ANNUAL == 6


class TestPlanPrices:
    @override_settings(PAYFAST_MONTHLY_PRICE="249.50", PAYFAST_YEARLY_PRICE="2495.00")
    def test_paid_plans_use_prices_from_settings(self):
        plans = constants.plan_prices()

        assert plans[finance_constants.MONTHLY_PLAN.name] == constants.PayFastPlan(
            name="monthly_plan", amount=Decimal("249.50"), frequency=constants.Frequency.MONTHLY
        )
        assert plans[finance_constants.YEARLY_PLAN.name] == constants.PayFastPlan(
            name="yearly_plan", amount=Decimal("2495.00"), frequency=constants.Frequency.ANNUAL
        )

    def test_free_plan_costs_nothing_and_has_no_billing_frequency(self):
        free = constants.plan_prices()[finance_constants.FREE_PLAN.name]

        assert free.amount == Decimal("0.00")
        assert free.frequency is None
        assert not free.is_paid

    def test_plan_names_are_the_same_as_stripe_plan_names(self):
        # Sharing plan identities keeps plan display names and any plan-based logic backend-agnostic.
        assert set(constants.plan_prices()) == {plan.name for plan in finance_constants.ALL_PLANS}

    def test_get_paid_plan_rejects_unknown_and_free_plans(self):
        # Checkouts only ever start for a paid plan; the free plan is the default, not something you buy.
        with pytest.raises(constants.UnknownPlanError):
            constants.get_paid_plan("platinum_plan")
        with pytest.raises(constants.UnknownPlanError):
            constants.get_paid_plan(finance_constants.FREE_PLAN.name)

    def test_get_paid_plan_returns_the_plan(self):
        assert constants.get_paid_plan("yearly_plan").frequency == constants.Frequency.ANNUAL


class TestDonationAmounts:
    @override_settings(PAYFAST_DONATION_AMOUNTS=["50", "100.5", "150"])
    def test_donation_amounts_are_decimals_with_cents(self):
        assert constants.donation_amounts() == [Decimal("50.00"), Decimal("100.50"), Decimal("150.00")]


class TestUrls:
    @override_settings(PAYFAST_SANDBOX=True)
    def test_sandbox_urls(self):
        # https://developers.payfast.co.za/docs#sandbox
        assert constants.process_url() == "https://sandbox.payfast.co.za/eng/process"
        assert constants.validate_url() == "https://sandbox.payfast.co.za/eng/query/validate"

    @override_settings(PAYFAST_SANDBOX=False)
    def test_live_urls(self):
        # https://developers.payfast.co.za/docs#go_live
        assert constants.process_url() == "https://www.payfast.co.za/eng/process"
        assert constants.validate_url() == "https://www.payfast.co.za/eng/query/validate"

    def test_api_base_url_is_the_same_host_for_sandbox_and_live(self):
        # The sandbox uses the same API host with ?testing=true (https://developers.payfast.co.za/api#recurring-billing).
        assert constants.API_BASE_URL == "https://api.payfast.co.za"

    def test_card_update_url_encodes_the_return_url(self):
        # https://developers.payfast.co.za/docs#recurring_card_update
        url = constants.card_update_url("abc-123", return_url="https://app.example.com/en/subscriptions?x=1")

        assert url == (
            "https://www.payfast.co.za/eng/recurring/update/abc-123"
            "?return=https%3A%2F%2Fapp.example.com%2Fen%2Fsubscriptions%3Fx%3D1"
        )


class TestNotificationSources:
    def test_valid_hosts_match_payfast_docs(self):
        # https://developers.payfast.co.za/docs#step_4_confirm_payment
        assert constants.VALID_ITN_HOSTS == (
            "www.payfast.co.za",
            "w1w.payfast.co.za",
            "w2w.payfast.co.za",
            "sandbox.payfast.co.za",
        )

    @pytest.mark.parametrize(
        "ip", ["197.97.145.144", "197.97.145.159", "41.74.179.200", "102.216.36.5", "144.126.193.139"]
    )
    def test_published_payfast_ips_are_recognised(self, ip):
        # https://developers.payfast.co.za/docs#ports-ips
        assert constants.is_published_payfast_ip(ip)

    @pytest.mark.parametrize("ip", ["197.97.145.160", "8.8.8.8", "127.0.0.1", "not-an-ip"])
    def test_other_ips_are_not_recognised(self, ip):
        assert not constants.is_published_payfast_ip(ip)
