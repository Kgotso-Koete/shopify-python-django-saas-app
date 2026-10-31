"""
Store customers' side of WhatsApp (plan phase 2). See docs/superpowers/plans/2026-10-06-whatsapp-first-channel-plan.md.
"""

from django.db import models

from apps.whatsapp.constants import ConversationMode
from common.models import TimestampedMixin


class StorefrontChannel(TimestampedMixin, models.Model):
    """
    "This external communications number sells from this Shopify store" (plan Step 2.1b, decision 4,
    user story 25). One per number at most (Step 2.1, decision 1); a number with none has no store
    chosen, and its customers get no reply.

    Kept here, not as a column on WhatsAppAccount, so apps.whatsapp never depends on apps.shopify.
    The rules (external numbers only, the organization's own eligible stores) are in services.py,
    the one place that writes these rows.
    """

    # Deleting the number deletes its link.
    account = models.OneToOneField(
        "whatsapp.WhatsAppAccount", on_delete=models.CASCADE, related_name="storefront_channel"
    )
    # Deleting the store deletes the link, never the number: the number then shows "no store chosen".
    shop = models.ForeignKey("shopify.ShopifyShop", on_delete=models.CASCADE, related_name="whatsapp_channels")
    # Menus or the assistant for every customer of the number, set by its admins (phase 2, decision 2):
    # the assistant calls OpenAI for each message, so the business decides, not the customer.
    conversation_mode = models.CharField(
        max_length=32, choices=ConversationMode.choices, default=ConversationMode.WHATSAPP_FORM
    )

    class Meta:
        verbose_name = "WhatsApp storefront channel"

    def __str__(self):
        return f"{self.account} sells from {self.shop}"


class StoreCustomer(TimestampedMixin, models.Model):
    """
    Someone texting an organization's external number to buy from its store (plan decision D4,
    Step 2.2): never a SaaS user or a member, and scoped to that one number, so the same phone
    texting two organizations is two store customers (user story 14). Created on their first
    message.
    """

    # Deleting the contact (e.g. Shopify's customers/redact, Step 2.6) deletes the store customer.
    contact = models.OneToOneField("whatsapp.WhatsAppContact", on_delete=models.CASCADE, related_name="store_customer")
    tenant = models.ForeignKey("multitenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    # The open cart, Shopify's id for it, and the store it's in (phase 2, decision 1). A cart from
    # another store (the number's store changed) or one Shopify no longer has is dropped.
    cart_id = models.CharField(max_length=255, blank=True)
    cart_shop = models.ForeignKey(
        "shopify.ShopifyShop", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    def __str__(self):
        return f"Store customer {self.contact}"
