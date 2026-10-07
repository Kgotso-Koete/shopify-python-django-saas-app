import pytest
from cryptography.fernet import Fernet
from django.conf import settings
from django.utils import timezone

from apps.shopify.models import ShopifyShop, ShopifyOAuthState, ShopifyWebhookDelivery
from apps.multitenancy.tests.factories import TenantFactory
from apps.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_shopify_shop_creation():
    tenant = TenantFactory()
    shop = ShopifyShop.objects.create(shop_domain="test-store.myshopify.com", tenant=tenant)
    assert str(shop) == "test-store.myshopify.com"
    assert shop.access_token is None


def test_shopify_shop_token_encryption_and_decryption(monkeypatch):
    key = Fernet.generate_key().decode("utf-8")
    monkeypatch.setattr(settings, "SHOPIFY_TOKEN_ENCRYPTION_KEY", key)

    shop = ShopifyShop.objects.create(shop_domain="test-crypto.myshopify.com")

    shop.access_token = "shpua_12345"
    shop.refresh_token = "shpur_67890"
    shop.save()

    shop.refresh_from_db()

    assert shop.access_token_encrypted != "shpua_12345"
    assert "shpua_" not in shop.access_token_encrypted

    assert shop.refresh_token_encrypted != "shpur_67890"
    assert "shpur_" not in shop.refresh_token_encrypted

    assert shop.access_token == "shpua_12345"
    assert shop.refresh_token == "shpur_67890"


def test_shopify_shop_token_decryption_fails_gracefully(monkeypatch):
    key1 = Fernet.generate_key().decode("utf-8")
    monkeypatch.setattr(settings, "SHOPIFY_TOKEN_ENCRYPTION_KEY", key1)

    shop = ShopifyShop.objects.create(shop_domain="test-fail.myshopify.com")
    shop.access_token = "shpua_secret"
    shop.save()

    key2 = Fernet.generate_key().decode("utf-8")
    monkeypatch.setattr(settings, "SHOPIFY_TOKEN_ENCRYPTION_KEY", key2)

    shop.refresh_from_db()
    assert shop.access_token is None


def test_shopify_oauth_state_creation():
    user = UserFactory()
    tenant = TenantFactory(creator=user)
    state = ShopifyOAuthState.objects.create(
        nonce="123456", shop_domain="test.myshopify.com", tenant=tenant, created_by=user
    )
    assert str(state) == "OAuth state for test.myshopify.com"


def test_shopify_webhook_delivery_creation():
    delivery = ShopifyWebhookDelivery.objects.create(
        webhook_id="webhook-1", topic="app/uninstalled", shop_domain="test.myshopify.com", payload={"foo": "bar"}
    )
    assert str(delivery) == "Webhook app/uninstalled for test.myshopify.com"
