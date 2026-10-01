"""
Client for PayFast's REST API (https://developers.payfast.co.za/api): the Subscriptions endpoints we
use to fetch and cancel subscriptions, and the Refunds endpoints used by the admin refund form.
`update()` is kept for completeness but unused: plan changes go through a new checkout instead,
because the update endpoint fails in the PayFast sandbox (plan section 10).

Every call is signed (https://developers.payfast.co.za/api#authentication): the `merchant-id`,
`version` and `timestamp` headers, the body and the passphrase are sorted alphabetically and hashed
into a `signature` header. Sandbox calls go to the same host with `?testing=true`, which is left
out of the signature.
"""

import datetime
import logging
import re
from decimal import Decimal
from typing import Optional

import requests
from django.conf import settings

from . import constants, signature

logger = logging.getLogger(__name__)

API_VERSION = "v1"
TIMEOUT_SECONDS = 15


class PayFastApiError(Exception):
    """Any failure talking to the PayFast API: network error, bad response, or a "failed" status."""


def to_cents(amount: Decimal) -> str:
    """PayFast's API takes amounts as integer cents, e.g. Decimal("199.00") -> "19900"."""
    return str(int((Decimal(amount) * 100).quantize(Decimal("1"))))


class PayFastApiClient:
    def __init__(self, session: Optional[requests.Session] = None):
        # Injectable so tests can pass a fake session; a real one reuses connections between calls.
        self.session = session or requests.Session()

    # --- Subscriptions (https://developers.payfast.co.za/api#recurring-billing) -----------------

    def fetch(self, token: str) -> dict:
        """The subscription's current state: amount (cents), frequency, run_date, status_text, ..."""
        return self._request("GET", f"/subscriptions/{token}/fetch")

    def cancel(self, token: str):
        """Cancel the subscription entirely. PayFast emails the buyer and sends a CANCELLED ITN."""
        return self._request("PUT", f"/subscriptions/{token}/cancel")

    def update(self, token: str, *, amount: Optional[Decimal] = None, frequency=None, run_date=None, cycles=None):
        """Change a subscription's amount (ZAR), frequency, next run date and/or number of cycles."""
        body = {}
        if amount is not None:
            body["amount"] = to_cents(amount)
        if frequency is not None:
            body["frequency"] = str(int(frequency))
        if run_date is not None:
            body["run_date"] = str(run_date)
        if cycles is not None:
            body["cycles"] = str(int(cycles))
        if not body:
            # "The body must contain at least one of the optional payload variables."
            raise ValueError("update() needs at least one of amount, frequency, run_date or cycles")
        return self._request("PATCH", f"/subscriptions/{token}/update", body)

    # --- Refunds (https://developers.payfast.co.za/api#refunds) -------------------------------
    # Not available in the PayFast sandbox (see plan section 1.7), so these are only exercised live.

    def refund_query(self, pf_payment_id: str) -> dict:
        """What can be refunded for a payment, and by which method (PAYMENT_SOURCE or BANK_PAYOUT)."""
        return self._request("GET", f"/refunds/query/{pf_payment_id}")

    def refund_create(self, pf_payment_id: str, *, amount: Decimal, reason: str, bank_details: Optional[dict] = None):
        """Refund `amount` (ZAR) of a payment. `bank_details` is required when the method is BANK_PAYOUT."""
        body = {"amount": to_cents(amount), "reason": reason, "notify_buyer": "1", **(bank_details or {})}
        return self._request("POST", f"/refunds/{pf_payment_id}", body)

    # --- Plumbing -------------------------------------------------------------------------------

    def _request(self, method: str, path: str, body: Optional[dict] = None):
        headers = {
            "merchant-id": settings.PAYFAST_MERCHANT_ID,
            "version": API_VERSION,
            # ISO-8601 with an explicit offset, e.g. 2026-09-30T19:40:00+00:00.
            "timestamp": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat(),
        }
        headers["signature"] = signature.api_signature(headers, body or {}, settings.PAYFAST_PASSPHRASE)
        params = {"testing": "true"} if settings.PAYFAST_SANDBOX else {}

        try:
            response = self.session.request(
                method,
                f"{constants.API_BASE_URL}{path}",
                headers=headers,
                params=params,
                data=body,
                timeout=TIMEOUT_SECONDS,
            )
        except requests.RequestException as error:
            raise PayFastApiError(f"PayFast API {method} {path} failed: {error}") from error

        try:
            payload = response.json()
        except ValueError as error:
            # PayFast answers some failures with an HTML error page ("Whoops, looks like something went
            # wrong.") and HTTP 200, so report what came back rather than a bare JSON parse error.
            text = response.text if isinstance(response.text, str) else ""
            text = re.sub(r"<(style|script)[^>]*>.*?</\1>", " ", text, flags=re.S | re.I)
            body = " ".join(re.sub(r"<[^>]+>", " ", text).split())[:300]
            raise PayFastApiError(
                f"PayFast API {method} {path} returned a response that is not JSON "
                f"(HTTP {response.status_code}): {body}"
            ) from error

        # PayFast wraps every response as {"code": ..., "status": "success"|"failed", "data": {...}}.
        data = payload.get("data") or {}
        if response.status_code >= 400 or payload.get("status") != "success":
            message = data.get("message") or payload.get("status") or f"HTTP {response.status_code}"
            logger.warning("PayFast API %s %s returned %s: %s", method, path, response.status_code, message)
            raise PayFastApiError(message)
        return data.get("response")
