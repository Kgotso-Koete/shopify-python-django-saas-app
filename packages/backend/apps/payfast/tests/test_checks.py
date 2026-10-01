"""
Tests for the PayFast Django system checks (apps/payfast/checks.py).

The checks run on every `manage.py` command and on server start. They turn a misconfigured
PAYMENT_BACKEND=payfast deployment into a clear startup error instead of a failed payment later.
See docs/superpowers/plans/2026-09-30-payfast-payment-backend-plan.md section 3.1.
"""

import pytest
from django.test import override_settings

from ..checks import check_payfast_settings

pytestmark = pytest.mark.django_db

# A complete, valid PayFast configuration. Each test overrides one value to break it.
VALID_PAYFAST_SETTINGS = {
    "PAYMENT_BACKEND": "payfast",
    "PAYFAST_ENVIRONMENT": "development",
    "PAYFAST_MERCHANT_ID": "10000100",
    "PAYFAST_MERCHANT_KEY": "46f0cd694581a",
    "PAYFAST_PASSPHRASE": "a-test-passphrase",
    "PAYFAST_NOTIFY_URL": "https://api.example.com/api/payfast/notify/",
    "PAYFAST_MONTHLY_PRICE": "199.00",
    "PAYFAST_YEARLY_PRICE": "1990.00",
    "PAYFAST_DONATION_AMOUNTS": ["50", "100", "150"],
}


def error_ids(**overrides):
    """Run the check with VALID_PAYFAST_SETTINGS plus `overrides`, and return the error ids."""
    with override_settings(**{**VALID_PAYFAST_SETTINGS, **overrides}):
        return [error.id for error in check_payfast_settings(app_configs=None)]


class TestPaymentBackendValue:
    def test_unknown_payment_backend_is_an_error(self):
        # A typo such as "payfst" must not silently fall back to Stripe.
        assert error_ids(PAYMENT_BACKEND="payfst") == ["payfast.E001"]

    def test_stripe_backend_ignores_missing_payfast_settings(self):
        # Stripe deployments must not be forced to configure PayFast.
        assert (
            error_ids(
                PAYMENT_BACKEND="stripe",
                PAYFAST_MERCHANT_ID="",
                PAYFAST_MERCHANT_KEY="",
                PAYFAST_PASSPHRASE="",
                PAYFAST_NOTIFY_URL="",
            )
            == []
        )


class TestPayFastConfiguration:
    def test_valid_configuration_has_no_errors(self):
        assert error_ids() == []

    @pytest.mark.parametrize(
        "setting_name", ["PAYFAST_MERCHANT_ID", "PAYFAST_MERCHANT_KEY", "PAYFAST_PASSPHRASE", "PAYFAST_NOTIFY_URL"]
    )
    def test_missing_required_setting_is_an_error(self, setting_name):
        # The passphrase is mandatory for subscriptions and the API (plan section 1.3), so it is not optional here.
        with override_settings(**{**VALID_PAYFAST_SETTINGS, setting_name: ""}):
            errors = check_payfast_settings(app_configs=None)

        assert [error.id for error in errors] == ["payfast.E002"]
        # The message names the environment variable to set, including its environment suffix,
        # so the fix is obvious from the startup output.
        assert f"{setting_name}_DEVELOPMENT" in errors[0].msg

    def test_notify_url_must_be_https(self):
        assert error_ids(PAYFAST_NOTIFY_URL="http://api.example.com/api/payfast/notify/") == ["payfast.E003"]

    @pytest.mark.parametrize("setting_name", ["PAYFAST_MONTHLY_PRICE", "PAYFAST_YEARLY_PRICE"])
    @pytest.mark.parametrize("bad_value", ["4.99", "0", "not-a-number", "-10"])
    def test_plan_price_below_payfast_minimum_or_invalid_is_an_error(self, setting_name, bad_value):
        # PayFast rejects payments under ZAR 5.00 (https://developers.payfast.co.za/docs#go_live), and
        # recurring_amount has a documented minimum of 5.00 (https://developers.payfast.co.za/docs#subscriptions).
        assert error_ids(**{setting_name: bad_value}) == ["payfast.E004"]

    def test_plan_price_with_more_than_two_decimals_is_an_error(self):
        # ZAR has cents only; "199.999" can't be charged as written.
        assert error_ids(PAYFAST_MONTHLY_PRICE="199.999") == ["payfast.E004"]

    def test_donation_amount_below_payfast_minimum_is_an_error(self):
        assert error_ids(PAYFAST_DONATION_AMOUNTS=["50", "4"]) == ["payfast.E005"]

    def test_empty_donation_amounts_is_an_error(self):
        # The donation page needs at least one amount to offer.
        assert error_ids(PAYFAST_DONATION_AMOUNTS=[]) == ["payfast.E005"]
