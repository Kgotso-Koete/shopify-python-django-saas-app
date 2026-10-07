from cryptography.fernet import Fernet
from django.conf import settings


def _get_fernet() -> Fernet:
    if not settings.SHOPIFY_TOKEN_ENCRYPTION_KEY:
        raise ValueError("SHOPIFY_TOKEN_ENCRYPTION_KEY is not set in settings.")
    return Fernet(settings.SHOPIFY_TOKEN_ENCRYPTION_KEY.encode("utf-8"))


def encrypt_token(token: str) -> str:
    """Encrypt a plaintext string token into a base64 Fernet token."""
    if not token:
        return ""
    f = _get_fernet()
    return f.encrypt(token.encode("utf-8")).decode("utf-8")


def decrypt_token(encrypted_token: str) -> str:
    """Decrypt a base64 Fernet token into a plaintext string."""
    if not encrypted_token:
        return ""
    f = _get_fernet()
    return f.decrypt(encrypted_token.encode("utf-8")).decode("utf-8")
