"""
Store customers' side of WhatsApp (plan phase 2). See docs/superpowers/plans/2026-10-06-whatsapp-first-channel-plan.md.
"""

from django.db import models

from apps.whatsapp.constants import ConversationMode, MessageStatus
from common.models import TimestampedMixin

# A message Meta accepted, then perhaps reported sent, delivered, read or played.
SENT_STATUSES = (
    MessageStatus.ACCEPTED,
    MessageStatus.SENT,
    MessageStatus.DELIVERED,
    MessageStatus.READ,
    MessageStatus.PLAYED,
)


class StorefrontChannel(TimestampedMixin, models.Model):
    """
    "This external communications number sells from this Shopify store" (plan Step 2.1b, decision 4,
    user story WA.D3.OM.J1.A3). One per number at most (Step 2.1, decision 1); a number with none has no store
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
    texting two organizations is two store customers (user story WA.D4.SC.J2.A1). Created on their first
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


class StoreCheckout(TimestampedMixin, models.Model):
    """
    One cart the chat created, and the code that lets its order find the chat (plan phase 4, decisions 2
    and 4): the cart carries the code as its `_whatsapp_checkout` attribute, which Shopify copies to the
    order. Ids only, never the cart's or the order's contents. Made in checkouts.py, the one place that
    writes these rows.
    """

    # `wachk_` and 22 random characters; unique, so an order finds one cart at most.
    code = models.CharField(max_length=64, unique=True)
    # Deleting the store customer (Shopify's customers/redact deletes their contact, Step 2.6) deletes
    # their checkouts.
    store_customer = models.ForeignKey(StoreCustomer, on_delete=models.CASCADE, related_name="checkouts")
    shop = models.ForeignKey("shopify.ShopifyShop", on_delete=models.CASCADE, related_name="+")
    # Shopify's id for the cart, as on StoreCustomer.cart_id.
    cart_id = models.CharField(max_length=255)
    # Shopify's id for the order the code first arrived on (Step 4.3c); unique, and a later order
    # carrying the same code is ignored (decision 21). Empty until then.
    order_id = models.BigIntegerField(null=True, blank=True, unique=True)
    # Each stage's message to the customer (decision 3), at most one per stage (Step 4.7, user story
    # WA.D5.SY.J1.A1, replacing when each was queued): the stage counts as sent only once Meta accepts it,
    # and one whose message failed is on the business's list to send again (user story WA.D3.OM.J2.A3).
    received_message = models.ForeignKey(
        "whatsapp.WhatsAppMessage", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    paid_message = models.ForeignKey(
        "whatsapp.WhatsAppMessage", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    def __str__(self):
        return f"Checkout {self.code}"

    def stage_message(self, *, paid: bool):
        return self.paid_message if paid else self.received_message

    def stage_sent(self, *, paid: bool) -> bool:
        """Whether Meta accepted the stage's message (and maybe sent, delivered or read it since)."""
        message = self.stage_message(paid=paid)
        return message is not None and message.status in SENT_STATUSES
