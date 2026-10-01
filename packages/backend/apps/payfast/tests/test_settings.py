"""
Tests proving the PayFast settings in config/settings.py are read from environment variables,
and that each one has a safe default when the variable is unset.

Credentials come in two sets, like the maintainer's other PayFast integrations: *_DEVELOPMENT
(PayFast sandbox) and *_PRODUCTION (live PayFast). ENVIRONMENT_NAME picks the set: "production"
uses the live set, anything else ("local", "test", "qa", ...) uses the sandbox set. The rest of
the code only ever reads the resolved, unsuffixed names (PAYFAST_MERCHANT_ID, ...).

See docs/superpowers/plans/2026-09-30-payfast-payment-backend-plan.md section 3.1 and section 7.
"""

import pytest

from .utils import read_settings

# The root conftest.py registers fixtures (Stripe prices) that need the database for every test.
pytestmark = pytest.mark.django_db

RESOLVED_CREDENTIALS = ["PAYFAST_MERCHANT_ID", "PAYFAST_MERCHANT_KEY", "PAYFAST_PASSPHRASE", "PAYFAST_NOTIFY_URL"]
OTHER_SETTINGS = [
    "PAYFAST_ENVIRONMENT",
    "PAYFAST_SANDBOX",
    "PAYFAST_VERIFY_SOURCE_IP",
    "PAYFAST_MONTHLY_PRICE",
    "PAYFAST_YEARLY_PRICE",
    "PAYFAST_DONATION_AMOUNTS",
]

BOTH_CREDENTIAL_SETS = {
    "PAYFAST_MERCHANT_ID_DEVELOPMENT": "10000100",
    "PAYFAST_MERCHANT_KEY_DEVELOPMENT": "46f0cd694581a",
    "PAYFAST_PASSPHRASE_DEVELOPMENT": "sandbox-passphrase",
    "PAYFAST_NOTIFY_URL_DEVELOPMENT": "https://tunnel.example.com/api/payfast/notify/",
    "PAYFAST_MERCHANT_ID_PRODUCTION": "12345678",
    "PAYFAST_MERCHANT_KEY_PRODUCTION": "livekey123",
    "PAYFAST_PASSPHRASE_PRODUCTION": "live-passphrase",
    "PAYFAST_NOTIFY_URL_PRODUCTION": "https://api.example.com/api/payfast/notify/",
}


class TestCredentialSetFollowsEnvironmentName:
    def test_production_uses_the_production_set_and_live_payfast(self):
        values = read_settings(
            RESOLVED_CREDENTIALS + ["PAYFAST_ENVIRONMENT", "PAYFAST_SANDBOX"],
            ENVIRONMENT_NAME="production",
            **BOTH_CREDENTIAL_SETS,
        )

        assert values == {
            "PAYFAST_MERCHANT_ID": "'12345678'",
            "PAYFAST_MERCHANT_KEY": "'livekey123'",
            "PAYFAST_PASSPHRASE": "'live-passphrase'",
            "PAYFAST_NOTIFY_URL": "'https://api.example.com/api/payfast/notify/'",
            "PAYFAST_ENVIRONMENT": "'production'",
            "PAYFAST_SANDBOX": "False",
        }

    @pytest.mark.parametrize("environment_name", ["local", "qa"])
    def test_every_other_environment_uses_the_development_set_and_the_sandbox(self, environment_name):
        values = read_settings(
            RESOLVED_CREDENTIALS + ["PAYFAST_ENVIRONMENT", "PAYFAST_SANDBOX"],
            ENVIRONMENT_NAME=environment_name,
            **BOTH_CREDENTIAL_SETS,
        )

        assert values == {
            "PAYFAST_MERCHANT_ID": "'10000100'",
            "PAYFAST_MERCHANT_KEY": "'46f0cd694581a'",
            "PAYFAST_PASSPHRASE": "'sandbox-passphrase'",
            "PAYFAST_NOTIFY_URL": "'https://tunnel.example.com/api/payfast/notify/'",
            "PAYFAST_ENVIRONMENT": "'development'",
            "PAYFAST_SANDBOX": "True",
        }


class TestOtherPayFastSettingsReadEnvVars:
    def test_shared_payfast_settings_read_env_vars(self):
        values = read_settings(
            OTHER_SETTINGS,
            ENVIRONMENT_NAME="local",
            PAYFAST_VERIFY_SOURCE_IP="False",
            PAYFAST_MONTHLY_PRICE="250.00",
            PAYFAST_YEARLY_PRICE="2500.00",
            PAYFAST_DONATION_AMOUNTS="20,40,60",
        )

        assert values == {
            "PAYFAST_ENVIRONMENT": "'development'",
            "PAYFAST_SANDBOX": "True",
            # Booleans are parsed, not kept as the string "False".
            "PAYFAST_VERIFY_SOURCE_IP": "False",
            # Prices stay strings here; apps.payfast.constants turns them into Decimals.
            "PAYFAST_MONTHLY_PRICE": "'250.00'",
            "PAYFAST_YEARLY_PRICE": "'2500.00'",
            # A comma-separated variable becomes a list.
            "PAYFAST_DONATION_AMOUNTS": "['20', '40', '60']",
        }


class TestPayFastSettingsDefaults:
    def test_payfast_settings_have_safe_defaults_when_unset(self):
        unset = {name: None for name in [*BOTH_CREDENTIAL_SETS, *OTHER_SETTINGS]}

        values = read_settings(RESOLVED_CREDENTIALS + OTHER_SETTINGS, ENVIRONMENT_NAME="local", **unset)

        assert values == {
            # No credentials by default: the system check reports them when PayFast is selected.
            "PAYFAST_MERCHANT_ID": "''",
            "PAYFAST_MERCHANT_KEY": "''",
            "PAYFAST_PASSPHRASE": "''",
            "PAYFAST_NOTIFY_URL": "''",
            "PAYFAST_ENVIRONMENT": "'development'",
            "PAYFAST_SANDBOX": "True",
            # The ITN source check is on unless explicitly disabled (e.g. behind ngrok locally).
            "PAYFAST_VERIFY_SOURCE_IP": "True",
            # The agreed default prices in ZAR (plan section 9).
            "PAYFAST_MONTHLY_PRICE": "'199.00'",
            "PAYFAST_YEARLY_PRICE": "'1990.00'",
            "PAYFAST_DONATION_AMOUNTS": "['50', '100', '150']",
        }
