"""
Tests for apps/whatsapp/crypto.py, which encrypts WhatsApp credentials before they're stored
(plan decision D5): access tokens and app secrets never sit in the database as plain text.

Kind of test: unit (agents.md section 2.5). Why: plain encryption functions, with no database or
network; nothing is faked.
"""

import pytest
from cryptography.fernet import Fernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from ..crypto import CredentialDecryptionError, decrypt_credential, encrypt_credential

# The root conftest.py registers fixtures whose autouse parts need the database.
pytestmark = pytest.mark.django_db

# Shaped like a real Meta access token, so a leak of the plain text would be easy to spot.
PLAIN_TOKEN = "EAAGtest1234567890abcdef"


def test_encrypting_then_decrypting_gives_back_the_original():
    assert decrypt_credential(encrypt_credential(PLAIN_TOKEN)) == PLAIN_TOKEN


def test_the_encrypted_value_is_never_the_plain_text():
    encrypted = encrypt_credential(PLAIN_TOKEN)

    assert encrypted != PLAIN_TOKEN
    assert PLAIN_TOKEN not in encrypted


def test_the_same_text_encrypts_differently_each_time():
    # Fernet adds a random value to each encryption, so two accounts with the same token can't
    # be spotted by comparing their stored values.
    assert encrypt_credential(PLAIN_TOKEN) != encrypt_credential(PLAIN_TOKEN)


def test_empty_text_stays_empty_and_needs_no_key(monkeypatch):
    # A disconnected number's secrets are wiped to empty, so empty must store as empty, even on a
    # deployment that has no key yet.
    monkeypatch.setattr(settings, "WHATSAPP_TOKEN_ENCRYPTION_KEY", "")

    assert encrypt_credential("") == ""
    assert decrypt_credential("") == ""


def test_a_missing_key_is_a_configuration_error(monkeypatch):
    monkeypatch.setattr(settings, "WHATSAPP_TOKEN_ENCRYPTION_KEY", "")

    # ImproperlyConfigured is Django's error for a missing setting, and the message names it.
    with pytest.raises(ImproperlyConfigured, match="WHATSAPP_TOKEN_ENCRYPTION_KEY"):
        encrypt_credential(PLAIN_TOKEN)


def test_a_value_encrypted_with_another_key_raises_a_clear_error(monkeypatch):
    encrypted = encrypt_credential(PLAIN_TOKEN)

    # A rotated or wrong key: the stored value can no longer be read. This must be an error,
    # not a quiet "no token", so the cause is obvious (unlike apps/shopify, which returns None).
    monkeypatch.setattr(settings, "WHATSAPP_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))

    with pytest.raises(CredentialDecryptionError, match="WHATSAPP_TOKEN_ENCRYPTION_KEY"):
        decrypt_credential(encrypted)
