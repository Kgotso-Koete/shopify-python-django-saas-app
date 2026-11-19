"""
Shopify database models (Shop, OAuth state, and Webhook deliveries).
"""

from django.conf import settings
from django.db import models

from common.models import TimestampedMixin
from apps.shopify.crypto import encrypt_token, decrypt_token


class ShopifyShop(TimestampedMixin, models.Model):
    """
    A store that installed the app. One row per shop domain; tokens are encrypted at rest.
    """

    shop_domain = models.CharField(max_length=255, unique=True, db_index=True)
    tenant = models.ForeignKey(
        "multitenancy.Tenant",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="shopify_shops",
    )
    access_token_encrypted = models.TextField(blank=True)
    access_token_expires_at = models.DateTimeField(null=True, blank=True)
    refresh_token_encrypted = models.TextField(blank=True)
    refresh_token_expires_at = models.DateTimeField(null=True, blank=True)
    scopes = models.CharField(max_length=1024, blank=True)
    installed_at = models.DateTimeField(null=True, blank=True)
    uninstalled_at = models.DateTimeField(null=True, blank=True)
    needs_reinstall = models.BooleanField(default=False)

    class Meta:
        # The Django admin's names for this app's models are written out, as apps/payfast's are: from the class
        # name, Django makes "shopify shop" (WhatsApp plan Step 4.7).
        verbose_name = "Shopify shop"

    def __str__(self):
        return self.shop_domain

    @property
    def access_token(self) -> str | None:
        if not self.access_token_encrypted:
            return None
        try:
            return decrypt_token(self.access_token_encrypted)
        except Exception:
            return None

    @access_token.setter
    def access_token(self, value: str | None):
        if not value:
            self.access_token_encrypted = ""
        else:
            self.access_token_encrypted = encrypt_token(value)

    @property
    def refresh_token(self) -> str | None:
        if not self.refresh_token_encrypted:
            return None
        try:
            return decrypt_token(self.refresh_token_encrypted)
        except Exception:
            return None

    @refresh_token.setter
    def refresh_token(self, value: str | None):
        if not value:
            self.refresh_token_encrypted = ""
        else:
            self.refresh_token_encrypted = encrypt_token(value)


class ShopifyOAuthState(TimestampedMixin, models.Model):
    """
    The single-use `state` nonce of one authorize redirect.
    """

    nonce = models.CharField(max_length=64, unique=True)
    shop_domain = models.CharField(max_length=255)
    tenant = models.ForeignKey("multitenancy.Tenant", null=True, blank=True, on_delete=models.CASCADE)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE)

    class Meta:
        # From the class name, Django makes "shopify o auth state".
        verbose_name = "Shopify OAuth state"

    def __str__(self):
        return f"OAuth state for {self.shop_domain}"


class ShopifyWebhookDelivery(TimestampedMixin, models.Model):
    """
    One received webhook, keyed by X-Shopify-Webhook-Id for deduplication.
    """

    webhook_id = models.CharField(max_length=255, unique=True)
    topic = models.CharField(max_length=128)
    shop_domain = models.CharField(max_length=255, db_index=True)
    payload = models.JSONField()
    # When its handler succeeded, set in the same transaction as the handler's work (deliveries.py,
    # WhatsApp plan Step 4.3e). Empty until then, so a repeat of the delivery runs it again.
    handled_at = models.DateTimeField(null=True, blank=True, db_index=True)
    # The last failure's exception, "Type: message", for the operator (WhatsApp plan, user story WA.D7.OP.J2.A2).
    last_error = models.TextField(blank=True, default="")
    # When the operator was emailed that the sweep gave up on it; each delivery is reported once.
    reported_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Shopify webhook delivery"
        # Django would add an "s": "deliverys".
        verbose_name_plural = "Shopify webhook deliveries"

    def __str__(self):
        return f"Webhook {self.topic} for {self.shop_domain}"
