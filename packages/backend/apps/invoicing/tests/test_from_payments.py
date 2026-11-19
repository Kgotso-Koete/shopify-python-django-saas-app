"""
Tests for invoicing a PayFast payment when apps.payfast says it completed (WhatsApp plan phase 4, Step
4.4b, decisions 15 and 18; D15).

- payment_completed queues the invoice task once the payment's transaction commits
- the task issues the invoice and writes its PDF to the default storage, which is private
- running again changes nothing: one invoice, one PDF
- a catch-up renewal's late ITN updates the invoice's PayFast id and leaves the PDF as it was
- a payment that gets no invoice (cancelled, or for nothing) gets none from the task either

Kind of test: integration (agents.md section 2.5). Why: payments and invoices are rows in the test
database, and PDFs are written to a temporary folder through Django's file storage; only the task's
Celery delay is patched, where the queueing is what's tested.
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from django.core.files.storage import default_storage
from freezegun import freeze_time

from apps.multitenancy.constants import TenantType
from apps.multitenancy.tests.factories import TenantFactory
from apps.payfast.models import PayFastPayment
from apps.payfast.signals import payment_completed
from apps.payfast.tests.factories import PayFastPaymentFactory

from .. import tasks
from ..models import Invoice

pytestmark = [pytest.mark.django_db, pytest.mark.story("WA.D6.OM.J2.A1")]

NOW = datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def private_storage(settings, tmp_path):
    """The default storage, as local files in a temporary folder, as in development."""
    settings.STORAGES = {**settings.STORAGES, "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"}}
    settings.MEDIA_ROOT = str(tmp_path)
    settings.INVOICE_SUPPLIER_NAME = "Example SaaS (Pty) Ltd"
    settings.INVOICE_SUPPLIER_ADDRESS = "1 Example Road\nCape Town"


@pytest.fixture
def payment():
    return PayFastPaymentFactory(
        tenant=TenantFactory(type=TenantType.ORGANIZATION, name="Acme"),
        item_name="Monthly plan",
        amount_gross=Decimal("199.00"),
        pf_payment_id="1089250",
    )


def test_a_completed_payment_queues_its_invoice_once_committed(payment, mocker, django_capture_on_commit_callbacks):
    delay = mocker.patch("apps.invoicing.tasks.issue_invoice.delay")

    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        payment_completed.send(sender=PayFastPayment, payment=payment)

    assert len(callbacks) == 1
    delay.assert_called_once_with(payment.pk)


@freeze_time(NOW)
def test_the_task_issues_the_invoice_and_writes_its_pdf_to_the_default_storage(payment):
    tasks.issue_invoice(payment.pk)

    invoice = Invoice.objects.get(payment=payment)
    assert invoice.pdf.name == "invoices/INV-2026-000001.pdf"
    with default_storage.open(invoice.pdf.name, "rb") as stored:
        assert stored.read().startswith(b"%PDF")


@freeze_time(NOW)
def test_running_again_changes_nothing(payment):
    tasks.issue_invoice(payment.pk)
    first = Invoice.objects.get(payment=payment)

    tasks.issue_invoice(payment.pk)

    again = Invoice.objects.get(payment=payment)
    assert (again.number, again.pdf.name) == (first.number, first.pdf.name)
    assert default_storage.listdir("invoices")[1] == ["INV-2026-000001.pdf"]


@freeze_time(NOW)
def test_a_late_itn_updates_the_payfast_id_and_leaves_the_pdf(payment):
    payment.pf_payment_id = "caught-up-3f2a"
    payment.save()
    tasks.issue_invoice(payment.pk)
    with default_storage.open("invoices/INV-2026-000001.pdf", "rb") as stored:
        before = stored.read()

    payment.pf_payment_id = "1089777"
    payment.save()
    tasks.issue_invoice(payment.pk)

    invoice = Invoice.objects.get(payment=payment)
    assert invoice.pf_payment_id == "1089777"
    with default_storage.open(invoice.pdf.name, "rb") as stored:
        assert stored.read() == before


def test_a_payment_that_gets_no_invoice_gets_none_from_the_task(payment):
    payment.payment_status = "CANCELLED"
    payment.save()

    tasks.issue_invoice(payment.pk)

    assert not Invoice.objects.exists()
