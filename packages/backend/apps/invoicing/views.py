"""
Downloading an invoice's PDF, /api/invoicing/<invoice id>/pdf/ (WhatsApp plan phase 4, Step 4.4c,
decisions 11, 12 and 19).

A Django REST framework view, so the web app's login cookie authenticates it as it does GraphQL. Every
request checks what GraphQL checks: the user's accepted membership of the invoice's organization, with
the same function the tenant middleware uses (it also blocks password logins from organizations that
enforce SSO), then billing.view. Another organization's invoice, or one whose organization was deleted,
is "not found", as a missing one is, so nobody learns which invoices exist. The PDF comes from the
default storage, whichever backend it is, so no storage link is ever handed out.
"""

from django.http import FileResponse, Http404
from rest_framework.views import APIView

from apps.multitenancy.middleware import get_current_tenant_with_membership_check
from apps.multitenancy.models import user_has_permission

from .models import Invoice


class InvoicePdfView(APIView):
    def get(self, request, invoice_id):
        invoice = _first_invoice(invoice_id)
        if invoice is None or invoice.tenant_id is None or not invoice.pdf:
            raise Http404
        tenant = get_current_tenant_with_membership_check(invoice.tenant_id, request.user, request)
        if tenant is None:
            raise Http404
        if not user_has_permission(request.user, tenant, "billing.view"):
            self.permission_denied(request, message="You don't have permission to see this organization's invoices.")
        return FileResponse(
            invoice.pdf.open("rb"), as_attachment=True, filename=f"{invoice.number}.pdf", content_type="application/pdf"
        )


def _first_invoice(invoice_id) -> Invoice | None:
    """The invoice, or None, also for an id the hashid field can't read."""
    try:
        return Invoice.objects.filter(pk=invoice_id).first()
    except (ValueError, TypeError):
        return None
