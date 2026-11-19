"""
Signals apps.payfast sends, so other apps can react to payments without apps.payfast importing them.

payment_completed (WhatsApp plan phase 4, decisions 15 and 18), with `payment` (a PayFastPayment):
- when an ITN records a completed payment: a donation, a subscription's first charge, a plan change,
  a renewal, or a charge on a replaced token
- when the daily catch-up records a renewal whose ITN never came, under a placeholder id
- when that renewal's ITN turns up after all, with PayFast's real id; the same payment is sent again

It's sent inside the transaction that saves the payment, so a receiver doing slow work (such as
apps.invoicing's PDF) queues it with transaction.on_commit. A re-sent ITN, which changes nothing,
sends nothing.
"""

from django.dispatch import Signal

payment_completed = Signal()
