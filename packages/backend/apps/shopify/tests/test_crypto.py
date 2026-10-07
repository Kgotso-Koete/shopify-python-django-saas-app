"""
Tests for token encryption/decryption.
"""

import pytest
from cryptography.fernet import Fernet
from django.conf import settings

from apps.shopify.crypto import encrypt_token, decrypt_token

pytestmark = pytest.mark.django_db


def test_encrypt_decrypt_roundtrip(monkeypatch):
    key = Fernet.generate_key().decode("utf-8")
    monkeypatch.setattr(settings, "SHOPIFY_TOKEN_ENCRYPTION_KEY", key)

    plaintext = "shpua_1234567890abcdef1234567890abcdef"
    encrypted = encrypt_token(plaintext)

    assert encrypted != plaintext
    assert "shpua_" not in encrypted

    decrypted = decrypt_token(encrypted)
    assert decrypted == plaintext


def test_empty_token(monkeypatch):
    key = Fernet.generate_key().decode("utf-8")
    monkeypatch.setattr(settings, "SHOPIFY_TOKEN_ENCRYPTION_KEY", key)

    assert encrypt_token("") == ""
    assert decrypt_token("") == ""


def test_missing_key(monkeypatch):
    monkeypatch.setattr(settings, "SHOPIFY_TOKEN_ENCRYPTION_KEY", "")

    with pytest.raises(ValueError, match="SHOPIFY_TOKEN_ENCRYPTION_KEY is not set"):
        encrypt_token("foo")


def test_wrong_key(monkeypatch):
    key1 = Fernet.generate_key().decode("utf-8")
    key2 = Fernet.generate_key().decode("utf-8")

    monkeypatch.setattr(settings, "SHOPIFY_TOKEN_ENCRYPTION_KEY", key1)
    encrypted = encrypt_token("foo")

    monkeypatch.setattr(settings, "SHOPIFY_TOKEN_ENCRYPTION_KEY", key2)
    from cryptography.fernet import InvalidToken

    with pytest.raises(InvalidToken):
        decrypt_token(encrypted)
