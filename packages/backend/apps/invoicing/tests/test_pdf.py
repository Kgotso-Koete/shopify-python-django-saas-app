"""
Tests for an invoice's PDF (WhatsApp plan phase 4, Step 4.4b, decisions 13 and 18; D15): written with
ReportLab, and saying what the invoice row says.

- "Invoice", its number and date, the supplier's name and address, whom it's for, what was paid for and
  the amount, in rand
- no VAT and no "Tax Invoice" (decision 13), and no PayFast id (decision 18: the invoice's own number is
  its reference, so the PDF never changes when a catch-up renewal's id is filled in)

Kind of test: integration (agents.md section 2.5). Why: the invoice is a row in the test database and the
PDF is really rendered; it's written without compression, so its text can be read back from the bytes.
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from freezegun import freeze_time

from apps.multitenancy.constants import TenantType
from apps.multitenancy.tests.factories import TenantFactory
from apps.payfast.tests.factories import PayFastPaymentFactory

from .. import pdf, services

pytestmark = [pytest.mark.django_db, pytest.mark.story("WA.D6.OM.J2.A1")]


@pytest.fixture
def invoice(settings):
    settings.INVOICE_SUPPLIER_NAME = "Example SaaS (Pty) Ltd"
    settings.INVOICE_SUPPLIER_ADDRESS = "1 Example Road\nCape Town"
    acme = TenantFactory(type=TenantType.ORGANIZATION, name="Acme")
    payment = PayFastPaymentFactory(
        tenant=acme, item_name="Monthly plan", amount_gross=Decimal("199.00"), pf_payment_id="1089250"
    )
    with freeze_time(datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc)):
        return services.issue_invoice(payment)


def test_it_is_a_pdf(invoice):
    assert pdf.render(invoice).startswith(b"%PDF")


def test_it_says_what_the_invoice_says(invoice):
    rendered = pdf.render(invoice)

    for text in [
        b"Invoice",
        b"INV-2026-000001",
        b"2026-11-02",
        # PDF text strings escape parentheses, so "(Pty)" is stored as \(Pty\).
        rb"Example SaaS \(Pty\) Ltd",
        b"1 Example Road",
        b"Cape Town",
        b"Bill to",
        b"Acme",
        b"Monthly plan",
        b"ZAR 199.00",
    ]:
        assert text in rendered, text


def test_it_shows_no_vat_and_no_payfast_id(invoice):
    rendered = pdf.render(invoice)

    assert b"Tax Invoice" not in rendered
    assert b"VAT" not in rendered
    assert b"1089250" not in rendered
