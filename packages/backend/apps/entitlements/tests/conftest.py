import pytest
from cryptography.fernet import Fernet
from django.conf import settings


@pytest.fixture(autouse=True)
def encryption_keys(monkeypatch):
    """
    Fresh WhatsApp and Shopify encryption keys for every test, as apps/whatsapp_shop/tests/conftest.py
    gives its own: test_where_checked.py creates WhatsApp numbers and Shopify stores, whose tokens are
    stored encrypted. The full backend run of 2026-11-01, which reads .test.env and not the local .env,
    failed four of its tests without them.
    """
    monkeypatch.setattr(settings, "WHATSAPP_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))
    monkeypatch.setattr(settings, "SHOPIFY_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))
