"""
The invoicing system check (WhatsApp plan phase 4, decision 13). A deployment that takes PayFast
payments issues an invoice for each one, printed with the supplier's name and address from the
settings; without them, invoices would leave the supplier out. A warning, not an error: payments keep
working, and the operator can fill the settings in and restart.
"""

from django.conf import settings
from django.core import checks


def check_invoicing_settings(app_configs, **kwargs):
    """A list of warnings; empty when PayFast isn't used, or the supplier is complete."""
    if settings.PAYMENT_BACKEND != settings.PAYMENT_BACKEND_PAYFAST:
        return []
    warnings = []
    # Only spaces counts as empty (user story WA.D6.OP.J1.A2): it would print a blank supplier just the same.
    if not settings.INVOICE_SUPPLIER_NAME.strip():
        warnings.append(
            checks.Warning(
                "INVOICE_SUPPLIER_NAME is empty, so invoices for PayFast payments name no supplier.",
                hint="Set it to the business that issues the invoices, such as your company's registered name.",
                id="invoicing.W001",
            )
        )
    if not settings.INVOICE_SUPPLIER_ADDRESS.strip():
        warnings.append(
            checks.Warning(
                "INVOICE_SUPPLIER_ADDRESS is empty, so invoices for PayFast payments show no supplier address.",
                hint="Set it to the issuing business's address; use \\n between its lines.",
                id="invoicing.W002",
            )
        )
    return warnings
