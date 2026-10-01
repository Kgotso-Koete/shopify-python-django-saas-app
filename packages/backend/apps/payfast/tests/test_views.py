"""
Integration tests for the ITN endpoint, POST /api/payfast/notify/ (apps/payfast/views.py).

Real URL routing, real request parsing, real signature check and a real database. Only the two
calls that would leave the machine are replaced: PayFast's /eng/query/validate confirmation and
the DNS lookup of PayFast's hosts. The request comes from an IP in PayFast's published range
(https://developers.payfast.co.za/docs#ports-ips).
"""

from unittest import mock

import pytest

from .. import services
from ..models import PayFastPayment, PayFastSubscription
from .utils import itn_pairs, signed_itn_body

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("payfast_backend", "payfast_confirms", "no_dns")]

URL = "/api/payfast/notify/"
PAYFAST_IP = "197.97.145.150"


@pytest.fixture
def payfast_confirms():
    with mock.patch("apps.payfast.itn.confirm_with_payfast", return_value=True) as confirm:
        yield confirm


@pytest.fixture
def no_dns():
    with mock.patch("apps.payfast.itn.resolve_payfast_hosts", return_value=set()):
        yield


def post_itn(client, body, remote_addr=PAYFAST_IP):
    return client.post(URL, data=body, content_type="application/x-www-form-urlencoded", REMOTE_ADDR=remote_addr)


@pytest.fixture
def donation_checkout(tenant, user):
    return services.create_donation_checkout(
        tenant=tenant,
        user=user,
        amount="50",
        return_url="https://app.example.com/r",
        cancel_url="https://app.example.com/c",
    )


class TestNotifyEndpoint:
    def test_genuine_itn_is_processed_and_acknowledged(self, client, donation_checkout):
        body = signed_itn_body(
            itn_pairs(m_payment_id=str(donation_checkout.m_payment_id), pf_payment_id="31337", amount_gross="50.00")
        )

        response = post_itn(client, body)

        # PayFast needs a 200, or it re-sends the ITN (https://developers.payfast.co.za/docs#step_4_confirm_payment).
        assert response.status_code == 200
        assert PayFastPayment.objects.get(pf_payment_id="31337").kind == PayFastPayment.Kind.DONATION

    def test_repeated_itn_is_acknowledged_again_without_a_second_payment(self, client, donation_checkout):
        body = signed_itn_body(
            itn_pairs(m_payment_id=str(donation_checkout.m_payment_id), pf_payment_id="31337", amount_gross="50.00")
        )

        post_itn(client, body)
        response = post_itn(client, body)

        assert response.status_code == 200
        assert PayFastPayment.objects.filter(pf_payment_id="31337").count() == 1

    def test_forged_signature_is_rejected(self, client, donation_checkout):
        body = signed_itn_body(
            itn_pairs(m_payment_id=str(donation_checkout.m_payment_id), amount_gross="50.00"), passphrase="guess"
        )

        response = post_itn(client, body)

        assert response.status_code == 400
        assert not PayFastPayment.objects.exists()

    def test_request_from_outside_payfast_is_rejected(self, client, donation_checkout):
        body = signed_itn_body(itn_pairs(m_payment_id=str(donation_checkout.m_payment_id), amount_gross="50.00"))

        response = post_itn(client, body, remote_addr="8.8.8.8")

        assert response.status_code == 400
        assert not PayFastPayment.objects.exists()

    def test_wrong_amount_is_rejected(self, client, donation_checkout):
        body = signed_itn_body(itn_pairs(m_payment_id=str(donation_checkout.m_payment_id), amount_gross="5.00"))

        response = post_itn(client, body)

        assert response.status_code == 400
        assert not PayFastPayment.objects.exists()

    def test_itn_for_something_we_did_not_start_is_acknowledged_and_ignored(self, client):
        # Genuine (signed, confirmed) but unknown, e.g. a payment from another integration on the same
        # PayFast account. Acknowledge it so PayFast stops retrying; change nothing.
        response = post_itn(client, signed_itn_body(itn_pairs(m_payment_id="someone-else")))

        assert response.status_code == 200
        assert not PayFastPayment.objects.exists()

    def test_only_post_is_allowed(self, client):
        assert client.get(URL).status_code == 405

    def test_endpoint_is_off_when_stripe_is_the_backend(self, client, settings, donation_checkout):
        # A stray ITN must not change anything in a Stripe deployment.
        settings.PAYMENT_BACKEND = "stripe"
        body = signed_itn_body(itn_pairs(m_payment_id=str(donation_checkout.m_payment_id), amount_gross="50.00"))

        assert post_itn(client, body).status_code == 404

    def test_endpoint_needs_no_csrf_token_or_login(self, client, donation_checkout):
        # PayFast is neither logged in nor able to send a CSRF token; the ITN checks replace both.
        client.handler.enforce_csrf_checks = True
        body = signed_itn_body(
            itn_pairs(m_payment_id=str(donation_checkout.m_payment_id), pf_payment_id="42", amount_gross="50.00")
        )

        assert post_itn(client, body).status_code == 200


class TestSubscriptionItnEndToEnd:
    def test_trial_checkout_itn_activates_the_trial(self, client, tenant, user):
        checkout = services.create_subscription_checkout(
            tenant=tenant,
            user=user,
            plan_name="monthly_plan",
            return_url="https://app.example.com/r",
            cancel_url="https://app.example.com/c",
        )
        body = signed_itn_body(
            itn_pairs(
                m_payment_id=str(checkout.m_payment_id),
                pf_payment_id="777",
                amount_gross="0.00",
                amount_fee="0.00",
                amount_net="0.00",
                token="dc0521d3-55fe-269b-fa00-b647310d760f",
            )
        )

        assert post_itn(client, body).status_code == 200

        subscription = PayFastSubscription.objects.get(tenant=tenant)
        assert subscription.status == PayFastSubscription.Status.TRIALING
        assert subscription.token == "dc0521d3-55fe-269b-fa00-b647310d760f"
