"""
Invoicing a PayFast payment when apps.payfast says it completed (WhatsApp plan phase 4, decision 15),
connected in apps.py. apps.payfast sends payment_completed inside the transaction that saves the payment,
so the task is queued once that transaction commits: the worker always finds the payment, and a payment
rolled back is never invoiced.
"""

from functools import partial

from django.db import transaction

from . import tasks


def invoice_completed_payment(sender, payment, **kwargs):
    transaction.on_commit(partial(tasks.issue_invoice.delay, payment.pk))
