"""
Tests for issuing an invoice for a completed PayFast payment (WhatsApp plan phase 4, Step 4.4a,
decisions 10, 11, 13 and 16).

- one sequence for the whole service, since the operator issues every invoice: INV-<year>-<number>,
  numbered without gaps or duplicates, across organizations
- an invoice copies what it says when it's issued: the supplier's name and address from the settings,
  the organization's name, the payment's PayFast ids, its description and amount
- a payment gets one invoice: issuing again returns the same one, with no new number
- only payments the transaction history shows get one: completed, for more than nothing
- an invoice outlives its organization and payment, keeping its copies

Kind of test: integration (agents.md section 2.5). Why: organizations, payments and invoices are rows in
the test database; nothing is faked.
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from freezegun import freeze_time

from apps.multitenancy.constants import TenantType
from apps.multitenancy.tests.factories import TenantFactory
from apps.payfast.tests.factories import PayFastPaymentFactory

from .. import services
from ..models import Invoice

pytestmark = [pytest.mark.django_db, pytest.mark.story("WA.D6.OM.J2.A1")]

NOW = datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def supplier(settings):
    settings.INVOICE_SUPPLIER_NAME = "Example SaaS (Pty) Ltd"
    settings.INVOICE_SUPPLIER_ADDRESS = "1 Example Road\nCape Town"


@pytest.fixture
def acme():
    return TenantFactory(type=TenantType.ORGANIZATION, name="Acme")


@freeze_time(NOW)
class TestNumbering:
    def test_the_first_invoice_is_number_one_of_the_year(self, acme):
        invoice = services.issue_invoice(PayFastPaymentFactory(tenant=acme))

        assert invoice.number == "INV-2026-000001"

    def test_one_sequence_runs_across_organizations(self, acme):
        globex = TenantFactory(type=TenantType.ORGANIZATION, name="Globex")

        numbers = [
            services.issue_invoice(PayFastPaymentFactory(tenant=tenant)).number for tenant in (acme, globex, acme)
        ]

        assert numbers == ["INV-2026-000001", "INV-2026-000002", "INV-2026-000003"]

    def test_the_sequence_carries_on_into_the_next_year(self, acme):
        services.issue_invoice(PayFastPaymentFactory(tenant=acme))

        with freeze_time(datetime(2027, 1, 1, 9, 0, tzinfo=timezone.utc)):
            invoice = services.issue_invoice(PayFastPaymentFactory(tenant=acme))

        # One sequence for the service (decision 11): the year says when, the number never restarts.
        assert invoice.number == "INV-2027-000002"


@freeze_time(NOW)
class TestWhatAnInvoiceSays:
    def test_it_copies_the_supplier_the_organization_and_the_payment(self, acme):
        payment = PayFastPaymentFactory(
            tenant=acme, item_name="Monthly plan", amount_gross=Decimal("199.00"), pf_payment_id="1089250"
        )

        invoice = services.issue_invoice(payment)

        assert (invoice.supplier_name, invoice.supplier_address) == (
            "Example SaaS (Pty) Ltd",
            "1 Example Road\nCape Town",
        )
        assert (invoice.tenant, invoice.tenant_name) == (acme, "Acme")
        assert (invoice.payment, invoice.pf_payment_id, invoice.m_payment_id) == (
            payment,
            "1089250",
            payment.m_payment_id,
        )
        assert (invoice.description, invoice.amount, invoice.currency) == ("Monthly plan", Decimal("199.00"), "ZAR")
        assert invoice.issued_at == NOW

    def test_a_later_change_of_supplier_details_never_rewrites_it(self, acme, settings):
        invoice = services.issue_invoice(PayFastPaymentFactory(tenant=acme))
        settings.INVOICE_SUPPLIER_NAME = "Renamed (Pty) Ltd"

        invoice.refresh_from_db()

        assert invoice.supplier_name == "Example SaaS (Pty) Ltd"


@freeze_time(NOW)
class TestOneInvoicePerPayment:
    def test_issuing_again_returns_the_same_invoice_with_no_new_number(self, acme):
        payment = PayFastPaymentFactory(tenant=acme)
        first = services.issue_invoice(payment)

        again = services.issue_invoice(payment)

        assert again == first
        assert Invoice.objects.count() == 1
        assert services.issue_invoice(PayFastPaymentFactory(tenant=acme)).number == "INV-2026-000002"

    def test_a_caught_up_renewal_is_invoiced_at_once_and_gets_payfasts_id_later(self, acme):
        # Decision 18: the daily catch-up records a renewal whose ITN never came under a placeholder id,
        # which a late ITN replaces with PayFast's real one (apps/payfast/services.py).
        payment = PayFastPaymentFactory(tenant=acme, pf_payment_id="caught-up-3f2a", caught_up=True)
        invoice = services.issue_invoice(payment)
        assert invoice.pf_payment_id == "caught-up-3f2a"

        payment.pf_payment_id = "1089777"
        payment.save()
        again = services.issue_invoice(payment)

        assert again == invoice
        assert (again.pf_payment_id, again.number) == ("1089777", "INV-2026-000001")
        assert Invoice.objects.count() == 1

    @pytest.mark.parametrize(
        "fields",
        [{"payment_status": "CANCELLED"}, {"amount_gross": Decimal("0.00")}],
        ids=["not completed", "for nothing"],
    )
    def test_only_a_payment_the_transaction_history_shows_gets_one(self, acme, fields):
        assert services.issue_invoice(PayFastPaymentFactory(tenant=acme, **fields)) is None
        assert not Invoice.objects.exists()


@freeze_time(NOW)
def test_an_invoice_outlives_its_organization(acme):
    payment = PayFastPaymentFactory(tenant=acme, pf_payment_id="1089250")
    invoice = services.issue_invoice(payment)

    acme.delete()

    invoice.refresh_from_db()
    assert (invoice.tenant, invoice.tenant_name, invoice.pf_payment_id) == (None, "Acme", "1089250")
    assert invoice.number == "INV-2026-000001"
    # The payment outlives it too, without its buyer's details (decision 17, Step 4.4p).
    assert invoice.payment == payment
