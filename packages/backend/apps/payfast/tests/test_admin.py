"""
Tests for the PayFast Django admin (apps/payfast/admin.py): the three models are browsable, and a
donation or subscription payment can be refunded from its admin page, the PayFast counterpart of
the Stripe admin refund view (apps/finances/views_admin.py).

Refunds use the PayFast Refunds API (https://developers.payfast.co.za/api#refunds), which PayFast
does not offer in its sandbox, so here the API is always the `payfast_api` mock.
"""

from decimal import Decimal

import pytest
from django.urls import reverse

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("payfast_backend")]


@pytest.fixture
def admin_user_client(client, user_factory):
    # In this codebase User.is_staff is is_superuser, so only superusers can use the Django admin.
    client.force_login(user_factory(is_superuser=True))
    return client


class TestAdminPages:
    @pytest.mark.parametrize("model_name", ["payfastsubscription", "payfastcheckout", "payfastpayment"])
    def test_changelist_loads(self, admin_user_client, model_name, pay_fast_subscription, pay_fast_payment):
        response = admin_user_client.get(reverse(f"admin:payfast_{model_name}_changelist"))

        assert response.status_code == 200

    def test_payment_page_links_to_the_refund_form(self, admin_user_client, pay_fast_payment):
        response = admin_user_client.get(reverse("admin:payfast_payfastpayment_change", args=[pay_fast_payment.pk]))

        assert reverse("admin:payfast_payfastpayment_refund", args=[pay_fast_payment.pk]) in response.content.decode()


class TestRefund:
    def url(self, payment):
        return reverse("admin:payfast_payfastpayment_refund", args=[payment.pk])

    def test_form_shows_what_payfast_says_is_refundable(self, admin_user_client, pay_fast_payment, payfast_api):
        payfast_api.refund_query.return_value = {
            "status": "REFUNDABLE",
            "amount_available_for_refund": 5000,
            "refund_partial": {"method": "PAYMENT_SOURCE"},
            "errors": [],
        }

        response = admin_user_client.get(self.url(pay_fast_payment))

        assert response.status_code == 200
        payfast_api.refund_query.assert_called_once_with(pay_fast_payment.pf_payment_id)
        assert "50.00" in response.content.decode()

    def test_refund_to_the_payment_source(self, admin_user_client, pay_fast_payment, payfast_api):
        payfast_api.refund_query.return_value = {
            "status": "REFUNDABLE",
            "amount_available_for_refund": 5000,
            "refund_partial": {"method": "PAYMENT_SOURCE"},
            "errors": [],
        }

        response = admin_user_client.post(
            self.url(pay_fast_payment), {"amount": "20.00", "reason": "Requested by customer"}
        )

        assert response.status_code == 302
        payfast_api.refund_create.assert_called_once_with(
            pay_fast_payment.pf_payment_id, amount=Decimal("20.00"), reason="Requested by customer"
        )
        pay_fast_payment.refresh_from_db()
        assert pay_fast_payment.refunded_amount == Decimal("20.00")

    def test_more_than_is_available_is_rejected(self, admin_user_client, pay_fast_payment, payfast_api):
        payfast_api.refund_query.return_value = {
            "status": "REFUNDABLE",
            "amount_available_for_refund": 1000,
            "refund_partial": {"method": "PAYMENT_SOURCE"},
            "errors": [],
        }

        response = admin_user_client.post(self.url(pay_fast_payment), {"amount": "20.00", "reason": "Too much"})

        assert response.status_code == 200
        payfast_api.refund_create.assert_not_called()

    def test_bank_payout_refunds_are_sent_to_the_payfast_dashboard(
        self, admin_user_client, pay_fast_payment, payfast_api
    ):
        # EFT payments are refunded by bank payout, which needs the buyer's bank details; that stays in
        # PayFast's own dashboard rather than being collected by our admin.
        payfast_api.refund_query.return_value = {
            "status": "REFUNDABLE",
            "amount_available_for_refund": 5000,
            "refund_partial": {"method": "BANK_PAYOUT"},
            "errors": [],
        }

        response = admin_user_client.post(self.url(pay_fast_payment), {"amount": "20.00", "reason": "EFT refund"})

        assert response.status_code == 200
        assert "PayFast dashboard" in response.content.decode()
        payfast_api.refund_create.assert_not_called()

    def test_not_refundable_shows_payfast_reason(self, admin_user_client, pay_fast_payment, payfast_api):
        payfast_api.refund_query.return_value = {
            "status": "NOT_AVAILABLE",
            "amount_available_for_refund": 0,
            "refund_partial": {"method": "NOT_AVAILABLE"},
            "errors": ["Refunds are not available for this payment method"],
        }

        response = admin_user_client.get(self.url(pay_fast_payment))

        assert "Refunds are not available for this payment method" in response.content.decode()

    def test_non_staff_users_cannot_refund(self, client, user_factory, pay_fast_payment, payfast_api):
        client.force_login(user_factory())

        response = client.post(self.url(pay_fast_payment), {"amount": "20.00", "reason": "x"})

        assert response.status_code == 302  # redirected to the admin login
        payfast_api.refund_create.assert_not_called()
