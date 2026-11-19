"""
Tests for what happens to an organization's PayFast payments when the organization is deleted
(WhatsApp plan phase 4, decision 17, Step 4.4p).

- the payments stay, as the operator's record for disputes and for SARS's five years of supporting
  documents, with their PayFast ids, amounts, status, plan and dates
- each keeps a copy of the organization's name, since its link to the organization becomes empty
- the buyer's name, email and phone are removed from the stored ITN, de-identifying it as POPIA
  section 14(4) asks once personal details are no longer needed; everything else in it stays
- another organization's payments are untouched

Kind of test: integration (agents.md section 2.5). Why: organizations and payments are rows in the test
database, deleted the way Django deletes them; nothing is faked.
"""

from decimal import Decimal

import pytest

from apps.multitenancy.constants import TenantType
from apps.multitenancy.tests.factories import TenantFactory

from ..models import PayFastPayment
from .factories import PayFastPaymentFactory

pytestmark = pytest.mark.django_db

# A stored ITN as PayFast sends it (https://developers.payfast.co.za/docs#step_4_confirm_payment), with the
# buyer's details, which PayFast includes, beside the payment's own.
ITN = {
    "m_payment_id": "b7c1f6c2",
    "pf_payment_id": "1089250",
    "payment_status": "COMPLETE",
    "item_name": "Monthly plan",
    "amount_gross": "199.00",
    "amount_fee": "-4.58",
    "amount_net": "194.42",
    "name_first": "Test",
    "name_last": "Buyer",
    "email_address": "buyer@example.com",
    "cell_number": "0820000000",
    "merchant_id": "10000100",
    "token": "",
    "billing_date": "2026-11-02",
}
BUYERS_DETAILS = {"name_first", "name_last", "email_address", "cell_number"}


@pytest.fixture
def acme():
    return TenantFactory(type=TenantType.ORGANIZATION, name="Acme")


def test_deleting_an_organization_keeps_its_payments_with_its_name(acme):
    payment = PayFastPaymentFactory(
        tenant=acme, pf_payment_id="1089250", amount_gross=Decimal("199.00"), plan="monthly_plan", raw=dict(ITN)
    )

    acme.delete()

    kept = PayFastPayment.objects.get(pk=payment.pk)
    assert kept.tenant is None
    assert kept.tenant_name == "Acme"
    assert (kept.pf_payment_id, kept.amount_gross, kept.plan, kept.payment_status) == (
        "1089250",
        Decimal("199.00"),
        "monthly_plan",
        "COMPLETE",
    )
    assert kept.created_at == payment.created_at


def test_the_buyers_name_email_and_phone_are_removed_from_the_stored_itn(acme):
    payment = PayFastPaymentFactory(tenant=acme, raw=dict(ITN))

    acme.delete()

    raw = PayFastPayment.objects.get(pk=payment.pk).raw
    assert BUYERS_DETAILS.isdisjoint(raw)
    assert raw == {key: value for key, value in ITN.items() if key not in BUYERS_DETAILS}


def test_another_organizations_payments_are_untouched(acme):
    other = PayFastPaymentFactory(tenant=TenantFactory(type=TenantType.ORGANIZATION, name="Globex"), raw=dict(ITN))
    PayFastPaymentFactory(tenant=acme, raw=dict(ITN))

    acme.delete()

    other.refresh_from_db()
    assert other.tenant.name == "Globex"
    assert other.tenant_name == ""
    assert other.raw == ITN
