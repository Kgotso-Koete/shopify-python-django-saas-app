"""
PayFast constants: plan prices, donation amounts, URLs and the sources PayFast notifications come from.

Plan identities are shared with the Stripe implementation (apps/finances/constants.py), so the rest
of the app never has to know which payment backend priced a plan. Only the ZAR amounts and PayFast
billing frequencies live here. Everything that depends on settings is a function, not a module-level
value, so `override_settings` in tests (and a changed env var after restart) is always picked up.
"""

import ipaddress
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional
from urllib.parse import quote_plus

from django.conf import settings
from django.db import models

from apps.finances import constants as finance_constants

CURRENCY = "ZAR"  # PayFast only supports South African rand.
CENTS = Decimal("0.01")


class Frequency(models.IntegerChoices):
    """PayFast subscription `frequency` codes (https://developers.payfast.co.za/docs#subscriptions)."""

    MONTHLY = 3, "Monthly"
    ANNUAL = 6, "Annual"


@dataclass(frozen=True)
class PayFastPlan:
    """A plan as PayFast bills it: the shared plan name, its ZAR price and its billing frequency."""

    name: str
    amount: Decimal
    frequency: Optional[int]

    @property
    def is_paid(self) -> bool:
        return self.amount > 0


class UnknownPlanError(ValueError):
    """Raised when a plan name isn't one of the paid plans a customer can check out."""


def to_amount(value) -> Decimal:
    """Convert a settings value such as "199" or "100.5" to a ZAR Decimal with cents (Decimal("199.00"))."""
    return Decimal(str(value)).quantize(CENTS)


def plan_prices() -> dict:
    """All plans keyed by their shared name, priced from the PAYFAST_* settings."""
    return {
        finance_constants.FREE_PLAN.name: PayFastPlan(
            name=finance_constants.FREE_PLAN.name, amount=Decimal("0.00"), frequency=None
        ),
        finance_constants.MONTHLY_PLAN.name: PayFastPlan(
            name=finance_constants.MONTHLY_PLAN.name,
            amount=to_amount(settings.PAYFAST_MONTHLY_PRICE),
            frequency=Frequency.MONTHLY,
        ),
        finance_constants.YEARLY_PLAN.name: PayFastPlan(
            name=finance_constants.YEARLY_PLAN.name,
            amount=to_amount(settings.PAYFAST_YEARLY_PRICE),
            frequency=Frequency.ANNUAL,
        ),
    }


def get_paid_plan(name: str) -> PayFastPlan:
    """Return the paid plan called `name`; the free plan and unknown names raise UnknownPlanError."""
    plan = plan_prices().get(name)
    if plan is None or not plan.is_paid:
        raise UnknownPlanError(f"{name!r} is not a paid plan")
    return plan


def donation_amounts() -> list:
    """The fixed donation amounts offered on the donation page, as ZAR Decimals."""
    return [to_amount(amount) for amount in settings.PAYFAST_DONATION_AMOUNTS]


def trial_period_days() -> int:
    """Trial length, shared with Stripe. The env var can arrive as a string, hence int()."""
    return int(settings.SUBSCRIPTION_TRIAL_PERIOD_DAYS)


# --- URLs -------------------------------------------------------------------------------------

LIVE_HOST = "www.payfast.co.za"
SANDBOX_HOST = "sandbox.payfast.co.za"

# The API host is the same for sandbox and live; sandbox calls add ?testing=true
# (https://developers.payfast.co.za/api#recurring-billing).
API_BASE_URL = "https://api.payfast.co.za"


def _host() -> str:
    return SANDBOX_HOST if settings.PAYFAST_SANDBOX else LIVE_HOST


def process_url() -> str:
    """Where the checkout form is POSTed (https://developers.payfast.co.za/docs#step_3_pay_on_payfast)."""
    return f"https://{_host()}/eng/process"


def validate_url() -> str:
    """Server-side ITN confirmation endpoint (https://developers.payfast.co.za/docs#step_4_confirm_payment)."""
    return f"https://{_host()}/eng/query/validate"


def card_update_url(token: str, return_url: str) -> str:
    """
    Link that lets a buyer update the card on a subscription, hosted by PayFast
    (https://developers.payfast.co.za/docs#recurring_card_update). The docs only give the live host.
    """
    return f"https://{LIVE_HOST}/eng/recurring/update/{token}?return={quote_plus(return_url, safe='')}"


# --- Where ITNs come from ----------------------------------------------------------------------

# Hosts PayFast's docs list as valid notification sources
# (https://developers.payfast.co.za/docs#step_4_confirm_payment).
VALID_ITN_HOSTS = (
    "www.payfast.co.za",
    "w1w.payfast.co.za",
    "w2w.payfast.co.za",
    "sandbox.payfast.co.za",
)

# PayFast's published server IPs (https://developers.payfast.co.za/docs#ports-ips). Checked in
# addition to resolving VALID_ITN_HOSTS, so a DNS hiccup can't reject a genuine notification.
PUBLISHED_IP_NETWORKS = tuple(
    ipaddress.ip_network(network)
    for network in (
        "197.97.145.144/28",
        "41.74.179.192/27",
        "102.216.36.0/28",
        "102.216.36.128/28",
        "144.126.193.139/32",
    )
)


def is_published_payfast_ip(ip: str) -> bool:
    """True if `ip` is inside one of PayFast's published server ranges."""
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(address in network for network in PUBLISHED_IP_NETWORKS)
