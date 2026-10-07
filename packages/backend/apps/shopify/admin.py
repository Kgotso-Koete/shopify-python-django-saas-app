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


@admin.register(ShopifyWebhookDelivery)
class ShopifyWebhookDeliveryAdmin(admin.ModelAdmin):
    list_display = ("webhook_id", "topic", "shop_domain", "created_at")
    search_fields = ("webhook_id", "shop_domain", "topic")
    list_filter = ("topic",)
    readonly_fields = ("webhook_id", "topic", "shop_domain", "payload")
