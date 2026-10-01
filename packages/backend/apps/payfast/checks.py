"""
Django system checks for the PayFast configuration.

They run on every `manage.py` command and when the server starts, so a PAYMENT_BACKEND=payfast
deployment with missing credentials or an invalid price fails loudly at startup, not at the first
payment. Registered in apps.PayfastConfig.ready().
"""

from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.core.checks import Error

# PayFast rejects payments below ZAR 5.00 (https://developers.payfast.co.za/docs#go_live), and
# recurring_amount has the same documented minimum (https://developers.payfast.co.za/docs#subscriptions).
PAYFAST_MINIMUM_AMOUNT = Decimal("5.00")

# Settings that must be non-empty for PayFast to work at all.
REQUIRED_SETTINGS = ("PAYFAST_MERCHANT_ID", "PAYFAST_MERCHANT_KEY", "PAYFAST_PASSPHRASE", "PAYFAST_NOTIFY_URL")


def check_payfast_settings(app_configs, **kwargs):
    """Return a list of configuration errors; an empty list means PayFast is correctly configured."""
    if settings.PAYMENT_BACKEND not in settings.PAYMENT_BACKENDS:
        return [
            Error(
                f"PAYMENT_BACKEND is {settings.PAYMENT_BACKEND!r}, expected one of {settings.PAYMENT_BACKENDS}.",
                id="payfast.E001",
            )
        ]

    # Stripe deployments don't need any PayFast configuration.
    if settings.PAYMENT_BACKEND != settings.PAYMENT_BACKEND_PAYFAST:
        return []

    # The settings are resolved from *_DEVELOPMENT or *_PRODUCTION variables (see config/settings.py),
    # so the message names the variable that actually has to be set in this environment.
    suffix = settings.PAYFAST_ENVIRONMENT.upper()
    errors = [
        Error(
            f"{name}_{suffix} must be set when PAYMENT_BACKEND is 'payfast' "
            f"(PayFast {settings.PAYFAST_ENVIRONMENT} credentials).",
            id="payfast.E002",
        )
        for name in REQUIRED_SETTINGS
        if not getattr(settings, name)
    ]

    notify_url = settings.PAYFAST_NOTIFY_URL
    if notify_url and not notify_url.startswith("https://"):
        errors.append(
            Error(
                "PAYFAST_NOTIFY_URL must be a public https:// URL; PayFast posts payment notifications to it.",
                id="payfast.E003",
            )
        )

    for name in ("PAYFAST_MONTHLY_PRICE", "PAYFAST_YEARLY_PRICE"):
        if not is_valid_amount(getattr(settings, name)):
            errors.append(
                Error(
                    f"{name} must be a ZAR amount of at least {PAYFAST_MINIMUM_AMOUNT} with at most two decimals.",
                    id="payfast.E004",
                )
            )

    donation_amounts = settings.PAYFAST_DONATION_AMOUNTS
    if not donation_amounts or not all(is_valid_amount(amount) for amount in donation_amounts):
        errors.append(
            Error(
                "PAYFAST_DONATION_AMOUNTS must list at least one ZAR amount, each at least "
                f"{PAYFAST_MINIMUM_AMOUNT} with at most two decimals.",
                id="payfast.E005",
            )
        )

    return errors


def is_valid_amount(value) -> bool:
    """True if `value` is a decimal ZAR amount PayFast can charge: >= 5.00 and no more than 2 decimals."""
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        return False
    # exponent >= -2 means at most two digits after the decimal point.
    return amount.is_finite() and amount >= PAYFAST_MINIMUM_AMOUNT and amount.as_tuple().exponent >= -2
