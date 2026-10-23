"""
Encryption for WhatsApp credentials at rest (plan decision D5).

Access tokens and app secrets are stored as Fernet tokens (AES with an HMAC, from the
`cryptography` package) under WHATSAPP_TOKEN_ENCRYPTION_KEY, never as plain text. Adapted from
apps/shopify/crypto.py rather than imported, so the two apps don't depend on each other
(agents.md section 3.1), with one deliberate difference: a value the current key can't read
raises CredentialDecryptionError instead of quietly reading as "no token".
"""

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


class CredentialDecryptionError(Exception):
    """A stored credential can't be decrypted with the current WHATSAPP_TOKEN_ENCRYPTION_KEY."""


def encrypt_credential(value: str) -> str:
    """Encrypt a plain-text credential for storage. Empty text stays empty and needs no key."""
    if not value:
        return ""
    return _fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_credential(stored: str) -> str:
    """Decrypt a stored credential back to plain text. Empty stays empty and needs no key."""
    if not stored:
        return ""
    try:
        return _fernet().decrypt(stored.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        # Fernet can't tell a wrong key from a damaged value; a changed key is by far the likeliest
        # cause, so the message points there. `from None` keeps Fernet's empty error out of the way.
        raise CredentialDecryptionError(
            "A stored WhatsApp credential can't be decrypted with the current WHATSAPP_TOKEN_ENCRYPTION_KEY. "
            "Was the key changed? Credentials stored under the old key must be entered again."
        ) from None


def _fernet() -> Fernet:
    """The Fernet cipher for WHATSAPP_TOKEN_ENCRYPTION_KEY, read at call time so tests can change it."""
    key = settings.WHATSAPP_TOKEN_ENCRYPTION_KEY
    if not key:
        raise ImproperlyConfigured("WHATSAPP_TOKEN_ENCRYPTION_KEY must be set to store WhatsApp credentials.")
    return Fernet(key.encode("utf-8"))
