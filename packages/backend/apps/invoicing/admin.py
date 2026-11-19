"""
The operator's view of every invoice, whichever organization it's for, deleted ones included
(WhatsApp plan phase 4, decision 11). Read-only: an issued invoice is a record, never added, changed
or deleted by hand.
"""

from django.contrib import admin

from .models import Invoice


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ("number", "tenant_name", "amount", "currency", "issued_at", "pf_payment_id")
    search_fields = ("number", "tenant_name", "pf_payment_id", "m_payment_id")
    date_hierarchy = "issued_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
