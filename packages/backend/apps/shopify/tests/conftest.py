import pytest
from cryptography.fernet import Fernet
from django.conf import settings


@pytest.fixture(autouse=True)
def enable_shopify_for_tests(monkeypatch):
    """
    Ensure Shopify is enabled for all tests and has valid keys,
    so views don't 404 and crypto doesn't crash, unless a specific
    test overrides these settings.
    """
    monkeypatch.setattr(settings, "SHOPIFY_API_KEY", "test_api_key")
    monkeypatch.setattr(settings, "SHOPIFY_API_SECRET", "test_api_secret")
    monkeypatch.setattr(settings, "SHOPIFY_ENABLED", True)

    # Generate a random Fernet key for token encryption
    key = Fernet.generate_key().decode("utf-8")
    monkeypatch.setattr(settings, "SHOPIFY_TOKEN_ENCRYPTION_KEY", key)

    monkeypatch.setattr(settings, "SHOPIFY_SCOPES", ["read_products"])
    monkeypatch.setattr(settings, "SHOPIFY_API_VERSION", "2026-10")
    monkeypatch.setattr(settings, "SHOPIFY_AUTH_TIMEOUT", 600)
