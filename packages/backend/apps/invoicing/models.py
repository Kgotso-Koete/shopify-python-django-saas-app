"""
Invoices for this service's PayFast payments (WhatsApp plan phase 4, decisions 10, 11, 13 and 16).

The operator issues every invoice, so they share one numbered sequence (InvoiceCounter). Each invoice
copies what it says when it's issued (the supplier, the organization's name, the payment's ids, its
description and amount), so it reads the same years later, whatever changes around it, and it outlives
its organization and payment: SARS asks for supporting documents to be kept for five years.
"""

import hashid_field
from django.db import models

from common.models import TimestampedMixin

# PayFast takes payments in rand only (https://developers.payfast.co.za/docs).
CURRENCY = "ZAR"


class InvoiceCounter(models.Model):
    """
    The service's one invoice sequence (decision 11): a single row, locked with select_for_update
    while a number is taken, so no two invoices share a number and none is skipped.
    """

    # The single row's primary key; migration 0002 creates it.
    THE_ONE = 1

    last_number = models.PositiveIntegerField(default=0)

    def __str__(self) -> str:
        return f"Last invoice number: {self.last_number}"


class Invoice(TimestampedMixin, models.Model):
    """One invoice, for one completed PayFast payment, as it was issued."""

    # A hashid, since invoices are exposed through GraphQL (Step 4.4c), like WhatsApp accounts.
    id = hashid_field.HashidAutoField(primary_key=True)
    # The place in the service's sequence, and the number printed from it: INV-<year>-<sequence>.
    sequence = models.PositiveIntegerField(unique=True)
    number = models.CharField(max_length=32, unique=True)
    issued_at = models.DateTimeField()

    # Empty once the organization or payment is deleted: the invoice stays (decision 16), with the copies below.
    tenant = models.ForeignKey(
        "multitenancy.Tenant", null=True, blank=True, on_delete=models.SET_NULL, related_name="invoices"
    )
    payment = models.OneToOneField(
        "payfast.PayFastPayment", null=True, blank=True, on_delete=models.SET_NULL, related_name="invoice"
    )

    # Copies, made when the invoice is issued.
    tenant_name = models.CharField(max_length=255)
    # PayFast's transaction id, for looking the payment up in PayFast's records. A catch-up renewal's starts
    # as its placeholder and becomes the real id when its ITN arrives (decision 18).
    pf_payment_id = models.CharField(max_length=64, unique=True)
    m_payment_id = models.CharField(max_length=100, blank=True, default="")
    supplier_name = models.CharField(max_length=255, blank=True, default="")
    supplier_address = models.TextField(blank=True, default="")
    description = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default=CURRENCY)

    # The PDF, in the default storage, which is private (Step 4.4b); empty until it's written.
    pdf = models.FileField(upload_to="invoices/", blank=True)

    class Meta:
        ordering = ("-sequence",)

    def __str__(self) -> str:
        return f"{self.number} ({self.tenant_name})"
