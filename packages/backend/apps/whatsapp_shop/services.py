"""
Which Shopify store each external communications number sells from (plan Step 2.1b, user story 25).

- One number, one store (Step 2.1, decision 1); choosing again changes it.
- Only the organization's own stores, and only those that can sell on WhatsApp: still installed,
  not waiting for a reinstall, and holding the storefront scopes a WhatsApp cart needs.
- Another organization's number or store is "not found", as a missing one is, so nobody learns what
  others have (as apps.whatsapp's find_account does).

Permissions are checked by the GraphQL layer, as apps.whatsapp's are: choosing needs whatsapp.manage.
"""

from apps.shopify.models import ShopifyShop
from apps.shopify.services import missing_scopes
from apps.whatsapp.constants import AccountPurpose
from apps.whatsapp.models import WhatsAppAccount

from .models import StorefrontChannel

# The Storefront API's product listings and cart, through the store's Admin token used as a private
# Storefront token (Step 2.1b, decision 1; Step 2.1a, result 5). The write scope also grants reading
# checkouts (result 2): https://shopify.dev/docs/api/usage/access-scopes
STOREFRONT_SCOPES = ("unauthenticated_read_product_listings", "unauthenticated_write_checkouts")


class StoreChannelError(Exception):
    """
    Something the admin can fix, shown in the form. `code` is for the web app to react to, and
    `field` names the input at fault, when there is one.
    """

    def __init__(self, message: str, code: str, field: str | None = None):
        super().__init__(message)
        self.code = code
        self.field = field


def can_sell_on_whatsapp(shop: ShopifyShop) -> bool:
    """True for a store still installed, not waiting for a reinstall, and holding the storefront scopes."""
    return (
        shop.uninstalled_at is None
        and not shop.needs_reinstall
        and not missing_scopes(STOREFRONT_SCOPES, shop.scopes or "")
    )


def eligible_stores(tenant) -> list[ShopifyShop]:
    """The organization's stores a number can sell from, by domain."""
    shops = ShopifyShop.objects.filter(tenant=tenant).order_by("shop_domain")
    return [shop for shop in shops if can_sell_on_whatsapp(shop)]


def channel_for(account: WhatsAppAccount) -> StorefrontChannel | None:
    """
    `account`'s store link, or None while none is chosen. A store disconnected from the organization on
    the Shopify page, or linked to another organization since, is no store of the number's (Step 2.8,
    finding 22); its link is kept, so connecting the store again brings the number back with its mode.
    """
    return (
        StorefrontChannel.objects.filter(account=account, shop__tenant_id=account.tenant_id)
        .select_related("shop")
        .first()
    )


def store_for(account: WhatsAppAccount) -> ShopifyShop | None:
    """The store `account` sells from, or None while none is chosen."""
    channel = channel_for(account)
    return channel.shop if channel else None


def choose_store(*, tenant, account_id: str, shop_domain: str) -> StorefrontChannel:
    """Make the organization's external number `account_id` sell from its store `shop_domain`."""
    account = WhatsAppAccount.objects.filter(tenant=tenant, pk=account_id).first()
    if account is None:
        raise StoreChannelError("WhatsApp number not found.", code="not_found")
    if not AccountPurpose.serves_customers(account.purpose):
        # A number serving both the team and customers sells too (plan Step 2.7).
        raise StoreChannelError(
            "Only a number your customers text sells from a store: this one answers your team only. "
            "Change whom it serves on its row first.",
            code="not_external",
        )

    shop = ShopifyShop.objects.filter(tenant=tenant, shop_domain=shop_domain).first()
    if shop is None:
        raise StoreChannelError("Store not found.", code="store_not_found", field="shop_domain")
    if not can_sell_on_whatsapp(shop):
        raise StoreChannelError(
            f"{shop.shop_domain} can't sell on WhatsApp yet. Reconnect it on the Shopify page to grant the "
            "storefront permissions, then choose it again.",
            code="store_not_eligible",
            field="shop_domain",
        )

    # The number's mode is kept when its store changes.
    channel, _ = StorefrontChannel.objects.update_or_create(account=account, defaults={"shop": shop})
    return channel


def set_mode(*, tenant, account_id: str, mode: str) -> StorefrontChannel:
    """
    Menus (WHATSAPP_FORM) or the assistant (AGENTIC) for every customer of the organization's external
    number `account_id` (phase 2, decision 2). The setting lives with the number's store link, so a
    number needs its store first.
    """
    account = WhatsAppAccount.objects.filter(tenant=tenant, pk=account_id).first()
    if account is None:
        raise StoreChannelError("WhatsApp number not found.", code="not_found")
    channel = channel_for(account)
    if channel is None:
        raise StoreChannelError("Choose the store this number sells from first.", code="no_store")
    channel.conversation_mode = mode
    channel.save(update_fields=["conversation_mode", "updated_at"])
    return channel
