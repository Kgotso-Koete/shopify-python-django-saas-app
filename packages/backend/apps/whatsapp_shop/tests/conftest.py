import pytest
from cryptography.fernet import Fernet
from django.conf import settings


@pytest.fixture(autouse=True)
def whatsapp_encryption_key(monkeypatch):
    """
    A fresh WHATSAPP_TOKEN_ENCRYPTION_KEY for every test, as apps/whatsapp/tests/conftest.py gives
    its own: these tests create WhatsApp accounts, whose access tokens are stored encrypted. Without
    it they pass only where the local .env happens to hold a key.
    """
    monkeypatch.setattr(settings, "WHATSAPP_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))


@pytest.fixture(autouse=True)
def shopify_encryption_key(monkeypatch):
    """
    A fresh SHOPIFY_TOKEN_ENCRYPTION_KEY for every test, as apps/shopify/tests/conftest.py gives its
    own: shopify_seed_demo stores the demo stores' access tokens encrypted. The full backend run of
    2026-10-29 failed both seed tests without it.
    """
    monkeypatch.setattr(settings, "SHOPIFY_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))
