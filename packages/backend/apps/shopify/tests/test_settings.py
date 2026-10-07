"""
Tests proving the Shopify settings in config/settings.py are read from environment variables,
and that each one has a safe default when the variable is unset.
"""

import pytest

from .utils import read_settings

pytestmark = pytest.mark.django_db

SHOPIFY_SETTINGS = [
    "SHOPIFY_API_KEY",
    "SHOPIFY_API_SECRET",
    "SHOPIFY_SCOPES",
    "SHOPIFY_API_VERSION",
    "SHOPIFY_TOKEN_ENCRYPTION_KEY",
    "SHOPIFY_AUTH_TIMEOUT",
    "SHOPIFY_WEBHOOK_DISPATCH",
    "SHOPIFY_ENABLED",
]


class TestShopifySettings:
    def test_shopify_settings_read_env_vars(self):
        values = read_settings(
            SHOPIFY_SETTINGS,
            SHOPIFY_API_KEY="test_key",
            SHOPIFY_API_SECRET="test_secret",
            SHOPIFY_SCOPES="read_products,write_products",
            SHOPIFY_API_VERSION="2027-01",
            SHOPIFY_TOKEN_ENCRYPTION_KEY="test_encryption_key",
            SHOPIFY_AUTH_TIMEOUT="900",
            SHOPIFY_WEBHOOK_DISPATCH="celery",
        )

        assert values == {
            "SHOPIFY_API_KEY": "'test_key'",
            "SHOPIFY_API_SECRET": "'test_secret'",
            "SHOPIFY_SCOPES": "['read_products', 'write_products']",
            "SHOPIFY_API_VERSION": "'2027-01'",
            "SHOPIFY_TOKEN_ENCRYPTION_KEY": "'test_encryption_key'",
            "SHOPIFY_AUTH_TIMEOUT": "900",
            "SHOPIFY_WEBHOOK_DISPATCH": "'celery'",
            "SHOPIFY_ENABLED": "True",
        }

    def test_shopify_settings_have_safe_defaults_when_unset(self):
        unset = {name: None for name in SHOPIFY_SETTINGS if name != "SHOPIFY_ENABLED"}

        values = read_settings(SHOPIFY_SETTINGS, **unset)

        assert values == {
            "SHOPIFY_API_KEY": "''",
            "SHOPIFY_API_SECRET": "''",
            "SHOPIFY_SCOPES": "['read_products']",
            "SHOPIFY_API_VERSION": "'2026-10'",
            "SHOPIFY_TOKEN_ENCRYPTION_KEY": "''",
            "SHOPIFY_AUTH_TIMEOUT": "600",
            "SHOPIFY_WEBHOOK_DISPATCH": "'sync'",
            "SHOPIFY_ENABLED": "False",
        }
