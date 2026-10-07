"""
System checks for the Shopify app.
"""

from django.core.checks import Error, register


@register
def check_shopify_settings(app_configs, **kwargs):
    from django.conf import settings

    errors = []

    if not getattr(settings, "SHOPIFY_ENABLED", False):
        return errors

    encryption_key = getattr(settings, "SHOPIFY_TOKEN_ENCRYPTION_KEY", "")
    if not encryption_key:
        errors.append(
            Error(
                "SHOPIFY_TOKEN_ENCRYPTION_KEY is required when SHOPIFY_ENABLED is True.",
                id="shopify.E001",
            )
        )
    else:
        # Validate it's a valid Fernet key
        import base64

        try:
            decoded = base64.urlsafe_b64decode(encryption_key)
            if len(decoded) != 32:
                raise ValueError
        except Exception:
            errors.append(
                Error(
                    "SHOPIFY_TOKEN_ENCRYPTION_KEY must be a valid 32-byte url-safe base64-encoded Fernet key.",
                    hint=(
                        'Generate one with: python -c "from cryptography.fernet import Fernet; '
                        'print(Fernet.generate_key().decode())"'
                    ),
                    id="shopify.E002",
                )
            )

    scopes = getattr(settings, "SHOPIFY_SCOPES", [])
    if not scopes:
        errors.append(
            Error(
                "SHOPIFY_SCOPES must contain at least one scope when SHOPIFY_ENABLED is True.",
                id="shopify.E003",
            )
        )

    api_version = getattr(settings, "SHOPIFY_API_VERSION", "")
    import re

    if not re.match(r"^\d{4}-(01|04|07|10)$", api_version):
        errors.append(
            Error(
                "SHOPIFY_API_VERSION must be shaped YYYY-MM with month 01, 04, 07, or 10.",
                id="shopify.E004",
            )
        )

    dispatch = getattr(settings, "SHOPIFY_WEBHOOK_DISPATCH", "sync")
    if dispatch not in {"sync", "celery"}:
        errors.append(
            Error(
                "SHOPIFY_WEBHOOK_DISPATCH must be either 'sync' or 'celery'.",
                id="shopify.E005",
            )
        )

    return errors
