"""
Django admin for PayFast billing records, plus a refund page for payments: the PayFast counterpart
of the Stripe admin refund view (apps/finances/views_admin.py).
"""

from decimal import Decimal

from django import forms
from django.contrib import admin, messages
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html

from . import services
from .client import PayFastApiError
from .models import PayFastCheckout, PayFastPayment, PayFastSubscription


@admin.register(PayFastSubscription)
class PayFastSubscriptionAdmin(admin.ModelAdmin):
    list_display = ("tenant", "plan", "pending_plan", "status", "amount", "current_period_end", "cancel_at_period_end")
    list_filter = ("plan", "status", "cancel_at_period_end")
    search_fields = ("tenant__name", "token")
    raw_id_fields = ("tenant",)


@admin.register(PayFastCheckout)
class PayFastCheckoutAdmin(admin.ModelAdmin):
    list_display = ("m_payment_id", "tenant", "kind", "plan", "amount", "is_trial", "status", "created_at")
    list_filter = ("kind", "status")
    search_fields = ("m_payment_id", "tenant__name")
    raw_id_fields = ("tenant", "created_by")


class RefundForm(forms.Form):
    amount = forms.DecimalField(min_value=Decimal("0.01"), decimal_places=2, max_digits=10, label="Amount (ZAR)")
    # PayFast requires 3 to 255 characters (https://developers.payfast.co.za/api#refund-create).
    reason = forms.CharField(min_length=3, max_length=255)


@admin.register(PayFastPayment)
class PayFastPaymentAdmin(admin.ModelAdmin):
    list_display = (
        "pf_payment_id",
        "tenant",
        "kind",
        "plan",
        "amount_gross",
        "refunded_amount",
        "payment_status",
        "created_at",
    )
    list_filter = ("kind", "payment_status")
    search_fields = ("pf_payment_id", "m_payment_id", "tenant__name")
    raw_id_fields = ("tenant", "subscription")
    readonly_fields = ("refund_link",)

    @admin.display(description="Refund")
    def refund_link(self, payment):
        if not payment.pk:
            return "-"
        return format_html(
            '<a href="{}">Refund this payment via PayFast</a>',
            reverse("admin:payfast_payfastpayment_refund", args=[payment.pk]),
        )

    def get_urls(self):
        return [
            path(
                "<path:object_id>/refund/",
                self.admin_site.admin_view(self.refund_view),
                name="payfast_payfastpayment_refund",
            ),
            *super().get_urls(),
        ]

    def refund_view(self, request, object_id):
        payment = get_object_or_404(PayFastPayment, pk=object_id)
        if not self.has_change_permission(request, payment):
            return redirect("admin:index")

        form = RefundForm(request.POST or None)
        error = None
        if request.method == "POST" and form.is_valid():
            try:
                refunded = services.refund_payment(
                    payment, amount=form.cleaned_data["amount"], reason=form.cleaned_data["reason"]
                )
            except services.PayFastError as refund_error:
                error = str(refund_error)
            else:
                messages.success(
                    request, f"Refunded {form.cleaned_data['amount']} ZAR (total refunded: {refunded} ZAR)."
                )
                return redirect("admin:payfast_payfastpayment_change", payment.pk)

        try:
            options = services.get_refund_options(payment)
        except PayFastApiError:
            options = None
            error = error or "PayFast could not be reached. Please try again later."

        context = {
            **self.admin_site.each_context(request),
            "title": f"Refund PayFast payment {payment.pf_payment_id}",
            "opts": self.model._meta,
            "payment": payment,
            "form": form,
            "options": options,
            "error": error,
        }
        return TemplateResponse(request, "admin/payfast/refund.html", context)
