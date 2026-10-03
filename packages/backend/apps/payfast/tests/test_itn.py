"""
Unit tests for apps/payfast/itn.py: verifying that an ITN (Instant Transaction Notification) really
comes from PayFast before anything acts on it.

PayFast's docs require these checks, and say "you should not continue the process if a test fails"
(https://developers.payfast.co.za/docs#step_4_confirm_payment):
1. the signature is valid;
2. the request comes from a PayFast server;
3. the amount matches what we expected (done in services.process_itn, which knows the expectation);
4. PayFast's /eng/query/validate endpoint confirms the data.
We also check that the ITN is for our merchant account.
"""

from unittest import mock

import pytest
from django.test import RequestFactory

from .. import itn, signature
from ..client import PayFastApiError
from .utils import itn_pairs, signed_itn_body

pytestmark = pytest.mark.django_db

PASSPHRASE = "jt7NOE43FZPn"
ITN_SETTINGS = {
    "PAYFAST_MERCHANT_ID": "10000100",
    "PAYFAST_PASSPHRASE": PASSPHRASE,
    "PAYFAST_SANDBOX": True,
    "PAYFAST_VERIFY_SOURCE_IP": True,
}
PAYFAST_IP = "197.97.145.150"  # inside a published PayFast range (https://developers.payfast.co.za/docs#ports-ips)


def signed_body(merchant_id="10000100", passphrase=PASSPHRASE):
    """A form-encoded ITN body signed the way PayFast signs it."""
    pairs = [
        ("m_payment_id", "5b1f0c1e-0000-4000-8000-000000000001"),
        ("pf_payment_id", "1089250"),
        ("payment_status", "COMPLETE"),
        ("item_name", "Donation"),
        ("item_description", ""),
        ("amount_gross", "50.00"),
        ("amount_fee", "-1.15"),
        ("amount_net", "48.85"),
        ("merchant_id", merchant_id),
    ]
    param_string = "&".join(f"{key}={signature.php_urlencode(value)}" for key, value in pairs)
    sig = signature._md5(f"{param_string}&passphrase={signature.php_urlencode(passphrase)}")
    return f"{param_string}&signature={sig}".encode()


def itn_request(body=None, remote_addr=PAYFAST_IP, forwarded_for=None):
    extra = {"REMOTE_ADDR": remote_addr}
    if forwarded_for:
        extra["HTTP_X_FORWARDED_FOR"] = forwarded_for
    return RequestFactory().post(
        "/api/payfast/notify/",
        data=body if body is not None else signed_body(),
        content_type="application/x-www-form-urlencoded",
        **extra,
    )


@pytest.fixture
def payfast_confirms():
    """PayFast's validate endpoint answers VALID; the test can inspect what was posted to it."""
    with mock.patch.object(itn, "confirm_with_payfast", return_value=True) as confirm:
        yield confirm


@pytest.fixture
def no_dns():
    """Keep tests off the network: host resolution returns nothing, so only published IPs count."""
    with mock.patch.object(itn, "resolve_payfast_hosts", return_value=set()):
        yield


@pytest.fixture
def itn_settings(settings):
    for name, value in ITN_SETTINGS.items():
        setattr(settings, name, value)
    return settings


@pytest.mark.usefixtures("no_dns", "itn_settings")
class TestVerifyItn:
    def test_genuine_itn_returns_its_fields_in_order(self, payfast_confirms):
        data = itn.verify_itn(itn_request())

        assert data[0] == ("m_payment_id", "5b1f0c1e-0000-4000-8000-000000000001")
        assert dict(data)["amount_gross"] == "50.00"

    def test_validate_endpoint_receives_the_param_string_without_passphrase(self, payfast_confirms):
        # PayFast's samples post the ITN param string to /eng/query/validate without the passphrase.
        itn.verify_itn(itn_request())

        posted = payfast_confirms.call_args.args[0]
        assert posted.startswith("m_payment_id=")
        assert "passphrase" not in posted
        assert "signature" not in posted

    def test_bad_signature_is_rejected(self, payfast_confirms):
        with pytest.raises(itn.ItnRejected, match="signature"):
            itn.verify_itn(itn_request(signed_body(passphrase="wrong")))
        payfast_confirms.assert_not_called()

    def test_unknown_source_ip_is_rejected(self, payfast_confirms):
        with pytest.raises(itn.ItnRejected, match="source"):
            itn.verify_itn(itn_request(remote_addr="8.8.8.8"))

    def test_other_merchant_is_rejected(self, payfast_confirms):
        with pytest.raises(itn.ItnRejected, match="merchant"):
            itn.verify_itn(itn_request(signed_body(merchant_id="99999999")))

    def test_payfast_not_confirming_is_rejected(self):
        with mock.patch.object(itn, "confirm_with_payfast", return_value=False):
            with pytest.raises(itn.ItnRejected, match="confirm"):
                itn.verify_itn(itn_request())

    def test_source_check_can_be_disabled_for_local_tunnels(self, payfast_confirms, itn_settings):
        itn_settings.PAYFAST_VERIFY_SOURCE_IP = False
        # Behind ngrok the source IP is the tunnel's; signature and server confirmation still apply.
        assert itn.verify_itn(itn_request(remote_addr="10.0.0.1"))


@pytest.mark.usefixtures("no_dns", "itn_settings")
class TestCancellationItn:
    """
    Plan section 12, issue 4. In the sandbox, PayFast's /eng/query/validate didn't answer VALID for the
    CANCELLED ITN of a subscription, so a cancellation made on PayFast's side never reached the app.
    The signature, merchant and source checks still apply; only for a cancellation that validate
    won't confirm, PayFast's Subscriptions API (GET /fetch) must confirm it instead.
    """

    TOKEN = "2afa4575-5628-051a-d0ed-4e071b56a7b0"

    def cancelled_request(self):
        pairs = itn_pairs(
            payment_status="CANCELLED",
            pf_payment_id="",
            amount_gross="0.00",
            amount_fee="0.00",
            amount_net="0.00",
            token=self.TOKEN,
        )
        return itn_request(signed_itn_body(pairs))

    def test_cancellation_confirmed_by_the_subscriptions_api_is_accepted(self):
        with mock.patch.object(itn, "confirm_with_payfast", return_value=False), mock.patch.object(
            itn, "cancellation_confirmed_by_api", return_value=True
        ) as api_confirms:
            data = dict(itn.verify_itn(self.cancelled_request()))

        assert data["payment_status"] == "CANCELLED"
        api_confirms.assert_called_once_with(self.TOKEN)

    def test_cancellation_the_api_does_not_confirm_is_rejected(self):
        with mock.patch.object(itn, "confirm_with_payfast", return_value=False), mock.patch.object(
            itn, "cancellation_confirmed_by_api", return_value=False
        ):
            with pytest.raises(itn.ItnRejected, match="confirm"):
                itn.verify_itn(self.cancelled_request())

    def test_a_payment_validate_does_not_confirm_never_falls_back_to_the_api(self):
        # Only cancellations move no money; a COMPLETE ITN still needs validate's VALID.
        with mock.patch.object(itn, "confirm_with_payfast", return_value=False), mock.patch.object(
            itn, "cancellation_confirmed_by_api", return_value=True
        ) as api_confirms:
            with pytest.raises(itn.ItnRejected, match="confirm"):
                itn.verify_itn(itn_request())

        api_confirms.assert_not_called()

    def test_a_bad_signature_is_rejected_before_any_confirmation(self):
        pairs = itn_pairs(payment_status="CANCELLED", token=self.TOKEN)
        with mock.patch.object(itn, "cancellation_confirmed_by_api", return_value=True) as api_confirms:
            with pytest.raises(itn.ItnRejected, match="signature"):
                itn.verify_itn(itn_request(signed_itn_body(pairs, passphrase="wrong")))

        api_confirms.assert_not_called()


class TestCancellationConfirmedByApi:
    @pytest.fixture
    def api(self):
        client = mock.Mock(name="PayFastApiClient()")
        with mock.patch.object(itn, "PayFastApiClient", return_value=client):
            yield client

    def test_cancelled_subscription_is_confirmed(self, api):
        api.fetch.return_value = {"status_text": "CANCELLED", "token": "tok"}

        assert itn.cancellation_confirmed_by_api("tok")
        api.fetch.assert_called_once_with("tok")

    def test_active_subscription_is_not_confirmed(self, api):
        api.fetch.return_value = {"status_text": "ACTIVE"}

        assert not itn.cancellation_confirmed_by_api("tok")

    def test_api_error_is_not_confirmed(self, api):
        api.fetch.side_effect = PayFastApiError("boom")

        assert not itn.cancellation_confirmed_by_api("tok")

    def test_no_token_is_not_confirmed(self, api):
        assert not itn.cancellation_confirmed_by_api("")
        api.fetch.assert_not_called()


class TestClientIp:
    def test_uses_remote_addr_without_a_proxy(self):
        assert itn.client_ip(itn_request(remote_addr="197.97.145.150")) == "197.97.145.150"

    def test_uses_the_address_our_proxy_appended(self):
        # Render and AWS ALB append the real client IP to X-Forwarded-For. Anything before it was
        # supplied by the client and could be forged, so the last entry is the one to trust.
        request = itn_request(remote_addr="10.0.0.2", forwarded_for="1.2.3.4, 197.97.145.150")

        assert itn.client_ip(request) == "197.97.145.150"


class TestSourceIsPayFast:
    def test_published_ip_is_accepted_even_if_dns_fails(self):
        with mock.patch.object(itn, "resolve_payfast_hosts", return_value=set()):
            assert itn.source_is_payfast(PAYFAST_IP)

    def test_ip_resolved_from_a_payfast_host_is_accepted(self):
        with mock.patch.object(itn, "resolve_payfast_hosts", return_value={"203.0.113.9"}):
            assert itn.source_is_payfast("203.0.113.9")


@pytest.fixture
def sandbox(settings):
    settings.PAYFAST_SANDBOX = True


@pytest.mark.usefixtures("sandbox")
class TestConfirmWithPayFast:
    def test_posts_to_sandbox_validate_url_and_accepts_valid(self):
        with mock.patch("apps.payfast.itn.requests.post") as post:
            post.return_value.text = "VALID"

            assert itn.confirm_with_payfast("m_payment_id=1&pf_payment_id=2")

        args, kwargs = post.call_args
        assert args[0] == "https://sandbox.payfast.co.za/eng/query/validate"
        assert kwargs["data"] == "m_payment_id=1&pf_payment_id=2"
        assert kwargs["timeout"] > 0

    def test_anything_but_valid_is_not_confirmed(self):
        with mock.patch("apps.payfast.itn.requests.post") as post:
            post.return_value.text = "INVALID"

            assert not itn.confirm_with_payfast("m_payment_id=1")

    def test_network_error_is_not_confirmed(self):
        import requests

        with mock.patch("apps.payfast.itn.requests.post", side_effect=requests.Timeout):
            assert not itn.confirm_with_payfast("m_payment_id=1")
