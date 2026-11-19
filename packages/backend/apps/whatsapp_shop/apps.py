from django.apps import AppConfig


class WhatsAppShopConfig(AppConfig):
    """
    What an organization's store customers get on its external communications WhatsApp numbers
    (plan decision D1, phase 2): for now, which Shopify store each number sells from (Step 2.1b).
    The channel itself is apps.whatsapp, which never imports this app, so the WhatsApp foundation
    stays usable without Shopify (Step 2.1b, decision 4). Deleting this app leaves the team's
    WhatsApp working.

    See docs/superpowers/plans/2026-10-06-whatsapp-first-channel-plan.md.
    """

    name = "apps.whatsapp_shop"
    verbose_name = "WhatsApp for an organization's store customers"

    def ready(self):
        from apps.shopify import payloads, signals
        from apps.whatsapp import registry
        from apps.whatsapp.constants import AccountPurpose

        from . import orders, receivers
        from .checkouts import CHECKOUT_ATTRIBUTE
        from .menus import StoreHandler

        # This app answers external communications numbers (D1, plan Step 2.2).
        registry.register_handler(AccountPurpose.EXTERNAL_COMMUNICATIONS, StoreHandler())
        # Its store customers are deleted when Shopify asks (Step 2.6, phase 2 decision 4).
        signals.customer_redacted.connect(receivers.delete_redacted_customer, dispatch_uid="whatsapp_shop.customer")
        signals.shop_redacted.connect(receivers.delete_redacted_shop, dispatch_uid="whatsapp_shop.shop")
        # An order delivery keeps the cart's checkout code, which apps.shopify otherwise drops (phase 4,
        # Step 4.3b, decision 4), so the order can find the chat it came from.
        payloads.keep_note_attribute(CHECKOUT_ATTRIBUTE)
        # Its store customers hear about their orders on the number they shopped on (Step 4.3c).
        signals.order_created.connect(orders.on_order_created, dispatch_uid="whatsapp_shop.order_created")
        signals.order_paid.connect(orders.on_order_paid, dispatch_uid="whatsapp_shop.order_paid")
