"""
Django admin for WhatsApp numbers, contacts and messages (plan Step 1.5b, decision D18).

The operator's view of every number, with the same troubleshooting tools organization admins have on
their WhatsApp tab, for when an organization asks the operator for help: Meta's status, a
verification code by SMS or voice, and re-subscribing the app are admin actions; registering with the PIN and entering a code have a small
form page each, like PayFast's refund page (apps/payfast/admin.py). Each repair is recorded in the
admin's own history, without the PIN or the code. The account's secrets are never shown.
"""

from django import forms
from django.contrib import admin, messages
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html

from .models import WhatsAppAccount, WhatsAppContact, WhatsAppMessage
from .services import number_tools
from .services.number_tools import NumberToolError

# Never shown, not even encrypted: the access token.
SECRET_FIELDS = ("access_token_encrypted",)


class PinForm(forms.Form):
    # Meta's two-step verification PIN: exactly 6 digits, passed straight to Meta (D18).
    pin = forms.RegexField(regex=r"^\d{6}$", error_messages={"invalid": "The PIN is exactly 6 digits."})


class CodeForm(forms.Form):
    code = forms.RegexField(
        regex=r"^\d{4,8}$", error_messages={"invalid": "The code is the 4 to 8 digits Meta sent the number."}
    )


@admin.register(WhatsAppAccount)
class WhatsAppAccountAdmin(admin.ModelAdmin):
    list_display = ("phone_number_id", "display_phone_number", "purpose", "tenant", "is_active", "connection_method")
    list_filter = ("purpose", "is_active", "connection_method")
    search_fields = ("phone_number_id", "display_phone_number", "verified_name", "tenant__name")
    raw_id_fields = ("tenant",)
    exclude = SECRET_FIELDS
    readonly_fields = ("number_tools",)
    actions = ("check_status", "request_code_sms", "request_code_voice", "subscribe_app")

    @admin.display(description="Number tools")
    def number_tools(self, account):
        if not account.pk:
            return "-"
        return format_html(
            '<a href="{}">Register with the PIN</a> | <a href="{}">Enter a verification code</a>',
            reverse("admin:whatsapp_whatsappaccount_register", args=[account.pk]),
            reverse("admin:whatsapp_whatsappaccount_verify", args=[account.pk]),
        )

    @admin.action(description="Show Meta's status for the selected numbers")
    def check_status(self, request, queryset):
        for account in queryset:
            try:
                status = number_tools.get_status(account)
            except NumberToolError as error:
                self.message_user(request, f"{account.phone_number_id}: {error}", messages.ERROR)
            else:
                shown = ", ".join(f"{field}: {value}" for field, value in status.items() if field != "id")
                self.message_user(request, f"{account.phone_number_id}: {shown}", messages.INFO)

    @admin.action(description="Request a verification code by SMS")
    def request_code_sms(self, request, queryset):
        self._repair_each(
            request,
            queryset,
            "request_code (SMS)",
            lambda a: number_tools.request_code(a, method="SMS", actor=request.user),
        )

    @admin.action(description="Request a verification code by voice call")
    def request_code_voice(self, request, queryset):
        self._repair_each(
            request,
            queryset,
            "request_code (VOICE)",
            lambda a: number_tools.request_code(a, method="VOICE", actor=request.user),
        )

    @admin.action(description="Subscribe the app to the number's WhatsApp Business account again")
    def subscribe_app(self, request, queryset):
        self._repair_each(
            request, queryset, "subscribe_app", lambda a: number_tools.subscribe_app(a, actor=request.user)
        )

    def _repair_each(self, request, queryset, operation, call):
        for account in queryset:
            try:
                call(account)
            except NumberToolError as error:
                self.message_user(request, f"{account.phone_number_id}: {error}", messages.ERROR)
            else:
                self.log_change(request, account, f"WhatsApp number tool: {operation}")
                self.message_user(request, f"{account.phone_number_id}: {operation} done.", messages.SUCCESS)

    def get_urls(self):
        return [
            path(
                "<path:object_id>/register/",
                self.admin_site.admin_view(self.register_view),
                name="whatsapp_whatsappaccount_register",
            ),
            path(
                "<path:object_id>/verify/",
                self.admin_site.admin_view(self.verify_view),
                name="whatsapp_whatsappaccount_verify",
            ),
            *super().get_urls(),
        ]

    def register_view(self, request, object_id):
        return self._tool_view(
            request,
            object_id,
            form_class=PinForm,
            operation="register",
            title="Register the number with its PIN",
            submit_label="Register with Meta",
            # Meta's limit, before the PIN is sent (D18, user story 23).
            warning="Meta allows 10 registration attempts per number in 72 hours; after that, registration "
            "is blocked for 72 hours.",
            call=lambda account, data: number_tools.register(account, pin=data["pin"], actor=request.user),
        )

    def verify_view(self, request, object_id):
        return self._tool_view(
            request,
            object_id,
            form_class=CodeForm,
            operation="verify_code",
            title="Enter the verification code",
            submit_label="Send the code to Meta",
            warning=None,
            call=lambda account, data: number_tools.verify_code(account, code=data["code"], actor=request.user),
        )

    def _tool_view(self, request, object_id, *, form_class, operation, title, submit_label, warning, call):
        account = get_object_or_404(WhatsAppAccount, pk=object_id)
        if not self.has_change_permission(request, account):
            return redirect("admin:index")

        form = form_class(request.POST or None)
        error = None
        if request.method == "POST" and form.is_valid():
            try:
                call(account, form.cleaned_data)
            except NumberToolError as tool_error:
                error = str(tool_error)
            else:
                # The admin's history names the operation only, never the PIN or the code.
                self.log_change(request, account, f"WhatsApp number tool: {operation}")
                messages.success(request, f"{operation} done.")
                return redirect("admin:whatsapp_whatsappaccount_change", account.pk)

        context = {
            **self.admin_site.each_context(request),
            "title": title,
            "opts": self.model._meta,
            "account": account,
            "form": form,
            "warning": warning,
            "error": error,
            "submit_label": submit_label,
        }
        return TemplateResponse(request, "admin/whatsapp/number_tool.html", context)


@admin.register(WhatsAppContact)
class WhatsAppContactAdmin(admin.ModelAdmin):
    list_display = ("bsuid", "wa_id", "profile_name", "account")
    search_fields = ("bsuid", "wa_id", "profile_name")
    raw_id_fields = ("account",)


@admin.register(WhatsAppMessage)
class WhatsAppMessageAdmin(admin.ModelAdmin):
    list_display = ("wamid", "contact", "direction", "kind", "status", "error_code", "created_at")
    list_filter = ("direction", "kind", "status")
    search_fields = ("wamid",)
    raw_id_fields = ("contact",)
