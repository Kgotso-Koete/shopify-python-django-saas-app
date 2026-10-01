"""
Tests for the PAYMENT_BACKEND switch in config/settings.py.

PAYMENT_BACKEND selects which payment provider the app uses: "payfast" (the default) or "stripe"
(the boilerplate's original provider). See docs/superpowers/plans/2026-09-30-payfast-payment-backend-plan.md section 3.1.

Django evaluates config/settings.py once, when the settings module is first imported, so by the
time a test runs the values are already fixed. Reloading the module inside this process would
change settings under every other test. Instead, each test imports config.settings in a fresh
Python subprocess with the environment it wants, and reads one value back. That proves the
environment variable is really wired up (docs/superpowers/agents.md, rule 2.3).
"""

import os
import pathlib
import subprocess
import sys

import pytest

# These tests don't touch the database themselves, but the root conftest.py registers
# apps.finances.tests.fixtures for every test, and its autouse fixtures create Stripe prices.
# So, like every other test module in this codebase, database access has to be allowed.
pytestmark = pytest.mark.django_db

# packages/backend, the directory that contains the `config` package. The subprocess runs from
# here so that `import config.settings` resolves exactly as it does for manage.py.
BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[3]

# Stripe keys that look configured (they don't contain "<CHANGE_ME>"). With these, the existing
# STRIPE_ENABLED rule would switch Stripe on, which lets the tests see whether PAYMENT_BACKEND
# overrides it.
CONFIGURED_STRIPE_KEYS = {
    "STRIPE_LIVE_SECRET_KEY": "sk_live_configured",
    "STRIPE_TEST_SECRET_KEY": "sk_test_configured",
}


def read_setting(name, **env_overrides):
    """
    Import config.settings in a new interpreter and return repr() of one setting.

    The subprocess inherits this process's environment (which already holds everything settings.py
    needs, such as DJANGO_SECRET_KEY and the database URL), with `env_overrides` applied on top.
    An override of None removes that variable, so a test can check the default used when it is unset.
    """
    env = os.environ.copy()
    for key, value in env_overrides.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value

    result = subprocess.run(
        [sys.executable, "-c", f"import config.settings as s; print(repr(s.{name}))"],
        cwd=BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    # settings.py may print warnings first, so the value is the last line of output.
    return result.stdout.strip().splitlines()[-1]


class TestPaymentBackendSetting:
    def test_payment_backend_defaults_to_payfast(self):
        # This fork serves South Africa, where Stripe isn't available, so PayFast is the default.
        # A deployment that wants Stripe sets PAYMENT_BACKEND=stripe explicitly.
        assert read_setting("PAYMENT_BACKEND", PAYMENT_BACKEND=None) == "'payfast'"

    def test_payment_backend_setting_reads_env_var(self):
        assert read_setting("PAYMENT_BACKEND", PAYMENT_BACKEND="stripe") == "'stripe'"


class TestStripeEnabledRespectsPaymentBackend:
    def test_stripe_disabled_by_default(self):
        # With PayFast as the default, an unset PAYMENT_BACKEND must not switch Stripe calls on.
        assert read_setting("STRIPE_ENABLED", PAYMENT_BACKEND=None, **CONFIGURED_STRIPE_KEYS) == "False"

    def test_stripe_stays_enabled_when_backend_is_stripe(self):
        # Regression guard: with Stripe selected, STRIPE_ENABLED is computed exactly as before.
        assert read_setting("STRIPE_ENABLED", PAYMENT_BACKEND="stripe", **CONFIGURED_STRIPE_KEYS) == "True"

    def test_stripe_disabled_when_backend_is_payfast(self):
        # Even with valid-looking Stripe keys, choosing PayFast must switch every Stripe API call
        # off (for example the free-plan signal on tenant creation, which checks STRIPE_ENABLED).
        assert read_setting("STRIPE_ENABLED", PAYMENT_BACKEND="payfast", **CONFIGURED_STRIPE_KEYS) == "False"
