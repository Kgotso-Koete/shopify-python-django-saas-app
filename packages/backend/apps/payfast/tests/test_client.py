"""
Unit tests for apps/payfast/client.py, the PayFast Subscriptions and Refunds API client.

The HTTP session is a fake, so these tests pin exactly what we send to api.payfast.co.za:
endpoint, method, headers (merchant-id, version, timestamp, signature), body and the sandbox flag.
Reference: https://developers.payfast.co.za/api
"""

from decimal import Decimal
from unittest import mock

import pytest

from .. import signature
from ..client import PayFastApiClient, PayFastApiError

pytestmark = pytest.mark.django_db

PAYFAST_API_SETTINGS = {
    "PAYFAST_MERCHANT_ID": "10000100",
    "PAYFAST_PASSPHRASE": "jt7NOE43FZPn",
    "PAYFAST_SANDBOX": True,
}
TOKEN = "dc0521d3-55fe-269b-fa00-b647310d760f"


@pytest.fixture(autouse=True)
def payfast_api_settings(settings):
    """PayFast credentials for every test here (pytest-django's `settings` fixture undoes it afterwards)."""
    for name, value in PAYFAST_API_SETTINGS.items():
        setattr(settings, name, value)


def fake_response(payload, status_code=200):
    response = mock.Mock()
    response.status_code = status_code
    response.json.return_value = payload
    return response


def make_client(payload=None, status_code=200):
    """A client whose session returns `payload` (PayFast's JSON envelope) for every request."""
    session = mock.Mock()
    session.request.return_value = fake_response(
        payload if payload is not None else {"code": 200, "status": "success", "data": {"response": True}},
        status_code,
    )
    return PayFastApiClient(session=session), session


def sent(session):
    """The (method, url, kwargs) of the single request the fake session received."""
    call = session.request.call_args
    return call.args[0], call.args[1], call.kwargs


class TestRequestFormat:
    def test_headers_are_signed_with_the_api_signature(self):
        client, session = make_client()

        client.cancel(TOKEN)

        _, _, kwargs = sent(session)
        headers = kwargs["headers"]
        assert headers["merchant-id"] == "10000100"
        assert headers["version"] == "v1"
        assert headers["timestamp"]
        # The signature covers the headers (minus itself), the body and the passphrase.
        unsigned_headers = {
            key: value for key, value in headers.items() if key in ("merchant-id", "version", "timestamp")
        }
        assert headers["signature"] == signature.api_signature(
            unsigned_headers, kwargs.get("data") or {}, "jt7NOE43FZPn"
        )

    def test_sandbox_adds_testing_query_parameter(self):
        client, session = make_client()

        client.cancel(TOKEN)

        assert sent(session)[2]["params"] == {"testing": "true"}

    def test_live_mode_sends_no_testing_parameter(self, settings):
        settings.PAYFAST_SANDBOX = False
        client, session = make_client()

        client.cancel(TOKEN)

        assert sent(session)[2]["params"] == {}

    def test_requests_have_a_timeout(self):
        # A hung PayFast API must never hang a web request or Celery worker forever.
        client, session = make_client()

        client.cancel(TOKEN)

        assert sent(session)[2]["timeout"] > 0


class TestSubscriptionEndpoints:
    def test_fetch(self):
        subscription = {
            "amount": 19900,
            "frequency": 3,
            "run_date": "2026-11-01T00:00:00+02:00",
            "status_text": "ACTIVE",
        }
        client, session = make_client({"code": 200, "status": "success", "data": {"response": subscription}})

        assert client.fetch(TOKEN) == subscription
        method, url, _ = sent(session)
        assert (method, url) == ("GET", f"https://api.payfast.co.za/subscriptions/{TOKEN}/fetch")

    def test_cancel(self):
        client, session = make_client()

        client.cancel(TOKEN)

        method, url, _ = sent(session)
        assert (method, url) == ("PUT", f"https://api.payfast.co.za/subscriptions/{TOKEN}/cancel")

    def test_update_sends_amount_in_cents(self):
        # The update endpoint takes `amount` in cents (https://developers.payfast.co.za/api#update-a-subscription).
        client, session = make_client()

        client.update(TOKEN, amount=Decimal("1990.00"), frequency=6, run_date="2026-10-31")

        method, url, kwargs = sent(session)
        assert (method, url) == ("PATCH", f"https://api.payfast.co.za/subscriptions/{TOKEN}/update")
        assert kwargs["data"] == {"amount": "199000", "frequency": "6", "run_date": "2026-10-31"}

    def test_update_requires_at_least_one_field(self):
        # "The body must contain at least one of the optional payload variables."
        client, _ = make_client()

        with pytest.raises(ValueError):
            client.update(TOKEN)


class TestRefundEndpoints:
    def test_refund_query(self):
        client, session = make_client(
            {"code": 200, "status": "success", "data": {"response": {"status": "REFUNDABLE"}}}
        )

        assert client.refund_query("1089250") == {"status": "REFUNDABLE"}
        assert sent(session)[:2] == ("GET", "https://api.payfast.co.za/refunds/query/1089250")

    def test_refund_create_sends_cents_and_reason(self):
        client, session = make_client()

        client.refund_create("1089250", amount=Decimal("50.00"), reason="Requested by customer")

        method, url, kwargs = sent(session)
        assert (method, url) == ("POST", "https://api.payfast.co.za/refunds/1089250")
        assert kwargs["data"] == {"amount": "5000", "reason": "Requested by customer", "notify_buyer": "1"}


class TestErrors:
    def test_failed_status_raises_with_payfast_message(self):
        client, _ = make_client(
            {"code": 400, "status": "failed", "data": {"response": False, "message": "Failure"}}, status_code=400
        )

        with pytest.raises(PayFastApiError, match="Failure"):
            client.cancel(TOKEN)

    def test_network_error_raises_payfast_api_error(self):
        # Callers only need to handle one exception type.
        import requests

        client, session = make_client()
        session.request.side_effect = requests.ConnectionError("unreachable")

        with pytest.raises(PayFastApiError):
            client.cancel(TOKEN)

    def test_non_json_response_raises_payfast_api_error(self):
        client, session = make_client()
        session.request.return_value.json.side_effect = ValueError("not json")

        with pytest.raises(PayFastApiError):
            client.cancel(TOKEN)

    def test_html_error_page_is_reported_with_status_and_body(self):
        # PayFast's API answers some failures with an HTML "Whoops, looks like something went wrong." page
        # and HTTP 200 (seen in the sandbox on subscription updates). The error must say so, with the
        # status and the start of the body, instead of a bare JSON parse error.
        client, session = make_client()
        session.request.return_value.json.side_effect = ValueError("Expecting value: line 1 column 1 (char 0)")
        session.request.return_value.text = "<!DOCTYPE html><h1>Whoops, looks like something went wrong.</h1>"

        with pytest.raises(PayFastApiError) as error:
            client.update(TOKEN, amount=Decimal("1990.00"))

        message = str(error.value)
        assert "not JSON" in message
        assert "HTTP 200" in message
        assert "Whoops, looks like something went wrong." in message
