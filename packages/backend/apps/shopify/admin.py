from django.contrib import admin
from .models import ShopifyShop, ShopifyOAuthState, ShopifyWebhookDelivery


@admin.register(ShopifyShop)
class ShopifyShopAdmin(admin.ModelAdmin):
    list_display = (
        "shop_domain",
        "tenant",
        "installed_at",
        "uninstalled_at",
        "needs_reinstall",
        "has_access_token",
    )
    search_fields = ("shop_domain",)
    list_filter = ("needs_reinstall",)
    readonly_fields = (
        "access_token_encrypted",
        "refresh_token_encrypted",
        "scopes",
        "installed_at",
        "uninstalled_at",
    )

    def has_access_token(self, obj):
        return bool(obj.access_token_encrypted)

    has_access_token.boolean = True


@admin.register(ShopifyOAuthState)
class ShopifyOAuthStateAdmin(admin.ModelAdmin):
    list_display = ("nonce", "shop_domain", "tenant", "created_by", "created_at")
    search_fields = ("shop_domain", "nonce")
    readonly_fields = ("nonce", "shop_domain", "tenant", "created_by")


class HandledFilter(admin.SimpleListFilter):
    """Deliveries whose handler has succeeded, or not yet (WhatsApp plan Step 4.3e)."""

    title = "handled"
    parameter_name = "handled"

    def lookups(self, request, model_admin):
        return (("no", "Not handled"), ("yes", "Handled"))

    def queryset(self, request, queryset):
        if self.value() == "no":
            return queryset.filter(handled_at__isnull=True)
        if self.value() == "yes":
            return queryset.filter(handled_at__isnull=False)
        return queryset


@admin.register(ShopifyWebhookDelivery)
class ShopifyWebhookDeliveryAdmin(admin.ModelAdmin):
    list_display = ("webhook_id", "topic", "shop_domain", "created_at", "handled_at", "last_error")
    search_fields = ("webhook_id", "shop_domain", "topic")
    list_filter = (HandledFilter, "topic")
    # handled_at too: the sweep and Shopify's retries rely on it (WhatsApp plan Step 4.3e).
    readonly_fields = ("webhook_id", "topic", "shop_domain", "payload", "handled_at", "last_error", "reported_at")
    actions = ["handle_again"]

    @admin.action(description="Handle again")
    def handle_again(self, request, queryset):
        """
        Run the selected deliveries' handlers again, once the cause is fixed (WhatsApp plan, user story
        WA.D7.OP.J2.A2); one already handled is left as it is.
        """
        from apps.shopify.deliveries import try_to_handle

        results = [try_to_handle(delivery) for delivery in queryset]
        self.message_user(request, f"{results.count(True)} handled, {results.count(False)} failed.")
