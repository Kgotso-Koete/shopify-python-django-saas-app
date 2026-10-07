"""
Tests for the apps.shopify system checks.
"""

import pytest
from django.core.checks import Error

from apps.shopify.checks import check_shopify_settings

pytestmark = pytest.mark.django_db


class MockSettings:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


def test_no_errors_when_shopify_disabled(monkeypatch):
    monkeypatch.setattr("django.conf.settings", MockSettings(SHOPIFY_ENABLED=False))
    assert check_shopify_settings(None) == []


def test_errors_when_enabled_without_encryption_key(monkeypatch):
    monkeypatch.setattr(
        "django.conf.settings",
        MockSettings(
            SHOPIFY_ENABLED=True,
            SHOPIFY_TOKEN_ENCRYPTION_KEY="",
            SHOPIFY_SCOPES=["read_products"],
            SHOPIFY_API_VERSION="2026-10",
            SHOPIFY_WEBHOOK_DISPATCH="sync",
        ),
    )
    errors = check_shopify_settings(None)
    assert len(errors) == 1
    assert errors[0].id == "shopify.E001"


def test_errors_when_encryption_key_invalid(monkeypatch):
    monkeypatch.setattr(
        "django.conf.settings",
        MockSettings(
            SHOPIFY_ENABLED=True,
            SHOPIFY_TOKEN_ENCRYPTION_KEY="not-a-valid-fernet-key",
            SHOPIFY_SCOPES=["read_products"],
            SHOPIFY_API_VERSION="2026-10",
            SHOPIFY_WEBHOOK_DISPATCH="sync",
        ),
    )
    errors = check_shopify_settings(None)
    assert len(errors) == 1
    assert errors[0].id == "shopify.E002"


def test_errors_when_enabled_without_scopes(monkeypatch):
    monkeypatch.setattr(
        "django.conf.settings",
        MockSettings(
            SHOPIFY_ENABLED=True,
            SHOPIFY_TOKEN_ENCRYPTION_KEY="f" * 43 + "=",  # Valid shape
            SHOPIFY_SCOPES=[],
            SHOPIFY_API_VERSION="2026-10",
            SHOPIFY_WEBHOOK_DISPATCH="sync",
        ),
    )
    errors = check_shopify_settings(None)
    assert len(errors) == 1
    assert errors[0].id == "shopify.E003"


@pytest.mark.parametrize("version", ["", "2026", "2026-05", "2026-1", "abc"])
def test_errors_when_api_version_invalid(monkeypatch, version):
    monkeypatch.setattr(
        "django.conf.settings",
        MockSettings(
            SHOPIFY_ENABLED=True,
            SHOPIFY_TOKEN_ENCRYPTION_KEY="f" * 43 + "=",
            SHOPIFY_SCOPES=["read_products"],
            SHOPIFY_API_VERSION=version,
            SHOPIFY_WEBHOOK_DISPATCH="sync",
        ),
    )
    errors = check_shopify_settings(None)
    assert len(errors) == 1
    assert errors[0].id == "shopify.E004"


@pytest.mark.parametrize("dispatch", ["", "async", "none", "celery "])
def test_errors_when_dispatch_invalid(monkeypatch, dispatch):
    monkeypatch.setattr(
        "django.conf.settings",
        MockSettings(
            SHOPIFY_ENABLED=True,
            SHOPIFY_TOKEN_ENCRYPTION_KEY="f" * 43 + "=",
            SHOPIFY_SCOPES=["read_products"],
            SHOPIFY_API_VERSION="2026-10",
            SHOPIFY_WEBHOOK_DISPATCH=dispatch,
        ),
    )
    errors = check_shopify_settings(None)
    assert len(errors) == 1
    assert errors[0].id == "shopify.E005"


def test_no_errors_when_fully_configured(monkeypatch):
    monkeypatch.setattr(
        "django.conf.settings",
        MockSettings(
            SHOPIFY_ENABLED=True,
            SHOPIFY_TOKEN_ENCRYPTION_KEY="f" * 43 + "=",
            SHOPIFY_SCOPES=["read_products"],
            SHOPIFY_API_VERSION="2026-10",
            SHOPIFY_WEBHOOK_DISPATCH="celery",
        ),
    )
    assert check_shopify_settings(None) == []
