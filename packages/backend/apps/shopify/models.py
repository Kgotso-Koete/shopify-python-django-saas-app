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

    def __str__(self):
        return f"Webhook {self.topic} for {self.shop_domain}"
