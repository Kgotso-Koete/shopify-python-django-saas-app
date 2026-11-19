"""
Issuing invoices (WhatsApp plan phase 4, Step 4.4a, decisions 10, 11, 13 and 16).

An invoice is issued for a PayFast payment the transaction history shows: completed, for more than
nothing (apps/payfast/schema.py's payfastPayments). It takes the next number in the service's one
sequence, in the same transaction as the invoice row, so a number is never taken without its invoice.
A payment has one invoice: issuing again returns it, found by its link to the payment, which payments
keep since they're never deleted (decision 17).

A renewal the daily catch-up recorded has a placeholder PayFast id until its ITN turns up with the real
one (decision 18). Its invoice is issued at once with the placeholder, and issuing again after the ITN
updates the invoice's copy of the id. That copy is a reference for looking payments up; the PDF
doesn't print it, so nothing printed changes.
"""

from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.payfast.models import PayFastPayment

from .models import Invoice, InvoiceCounter

COMPLETE = "COMPLETE"


def issue_invoice(payment: PayFastPayment) -> Invoice | None:
    """The payment's invoice, issued now if it has none; None for a payment that gets no invoice."""
    if payment.payment_status != COMPLETE or payment.amount_gross <= Decimal("0"):
        return None
    with transaction.atomic():
        existing = Invoice.objects.select_for_update().filter(payment=payment).first()
        if existing is not None:
            if existing.pf_payment_id != payment.pf_payment_id:
                existing.pf_payment_id = payment.pf_payment_id
                existing.save(update_fields=["pf_payment_id", "updated_at"])
            return existing
        sequence = _next_number()
        issued_at = timezone.now()
        return Invoice.objects.create(
            sequence=sequence,
            number=f"INV-{issued_at.year}-{sequence:06d}",
            issued_at=issued_at,
            tenant=payment.tenant,
            payment=payment,
            tenant_name=payment.tenant.name if payment.tenant else payment.tenant_name,
            pf_payment_id=payment.pf_payment_id,
            m_payment_id=payment.m_payment_id,
            supplier_name=settings.INVOICE_SUPPLIER_NAME,
            supplier_address=settings.INVOICE_SUPPLIER_ADDRESS,
            description=payment.item_name,
            amount=payment.amount_gross,
        )


def _next_number() -> int:
    """
    The service's next invoice number, taken under a row lock (call inside a transaction). The one
    counter row is created by the migration, so this only ever locks it, never races to create it.
    """
    counter = InvoiceCounter.objects.select_for_update().get(pk=InvoiceCounter.THE_ONE)
    counter.last_number += 1
    counter.save(update_fields=["last_number"])
    return counter.last_number
