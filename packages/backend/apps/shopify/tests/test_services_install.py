import pytest
import datetime
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.shopify.services import start_install, complete_install
from apps.shopify.models import ShopifyOAuthState, ShopifyShop
from apps.shopify.client import TokenResponse
from apps.multitenancy.tests.factories import TenantFactory
from apps.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_start_install():
    url = start_install("test.myshopify.com")

    assert url.startswith("https://test.myshopify.com/admin/oauth/authorize?")
    assert "client_id=" in url
    assert "scope=" in url
    assert "redirect_uri=" in url
    assert "state=" in url

    state = ShopifyOAuthState.objects.first()
    assert state is not None
    assert state.shop_domain == "test.myshopify.com"
    assert state.tenant is None
    assert url.endswith(f"state={state.nonce}")


def test_start_install_cleans_up_expired_states(freezer):
    freezer.move_to("2026-10-01T10:00:00Z")
    ShopifyOAuthState.objects.create(nonce="expired", shop_domain="old.myshopify.com")

    freezer.move_to("2026-10-01T10:30:00Z")  # Past SHOPIFY_AUTH_TIMEOUT
    start_install("new.myshopify.com")

    assert ShopifyOAuthState.objects.filter(nonce="expired").count() == 0
    assert ShopifyOAuthState.objects.count() == 1


def test_complete_install_happy_path(mocker):
    state = ShopifyOAuthState.objects.create(nonce="valid_nonce", shop_domain="test.myshopify.com")

    mock_exchange = mocker.patch("apps.shopify.client.ShopifyAdminClient.exchange_code")
    mock_exchange.return_value = TokenResponse(
        access_token="acc_123",
        scope=",".join(settings.SHOPIFY_SCOPES),
        expires_in=3600,
        refresh_token="ref_123",
        refresh_token_expires_in=7776000,
    )

    shop = complete_install("test.myshopify.com", "code123", "valid_nonce")

    assert shop.shop_domain == "test.myshopify.com"
    assert shop.access_token == "acc_123"
    assert shop.refresh_token == "ref_123"
    assert shop.scopes == ",".join(settings.SHOPIFY_SCOPES)
    assert not shop.needs_reinstall
    assert shop.uninstalled_at is None

    # State should be consumed
    assert ShopifyOAuthState.objects.count() == 0


def test_complete_install_invalid_nonce():
    with pytest.raises(ValidationError, match="Invalid or already consumed state nonce"):
        complete_install("test.myshopify.com", "code123", "bad_nonce")


def test_complete_install_shop_mismatch():
    ShopifyOAuthState.objects.create(nonce="valid_nonce", shop_domain="other.myshopify.com")

    with pytest.raises(ValidationError, match="State nonce does not match"):
        complete_install("test.myshopify.com", "code123", "valid_nonce")


def test_complete_install_expired_nonce(freezer):
    freezer.move_to("2026-10-01T10:00:00Z")
    ShopifyOAuthState.objects.create(nonce="valid_nonce", shop_domain="test.myshopify.com")

    freezer.move_to("2026-10-01T10:30:00Z")  # Past SHOPIFY_AUTH_TIMEOUT
    with pytest.raises(ValidationError, match="State nonce has expired"):
        complete_install("test.myshopify.com", "code123", "valid_nonce")

    # Expired state is NOT deleted here — the @transaction.atomic rollback
    # undoes any deletes. start_install's periodic cleanup handles it.
    assert ShopifyOAuthState.objects.count() == 1


def test_complete_install_missing_scopes(mocker):
    ShopifyOAuthState.objects.create(nonce="valid_nonce", shop_domain="test.myshopify.com")

    mock_exchange = mocker.patch("apps.shopify.client.ShopifyAdminClient.exchange_code")
    mock_exchange.return_value = TokenResponse(
        access_token="acc_123",
        scope="read_orders",  # Missing the ones in SHOPIFY_SCOPES
        expires_in=3600,
        refresh_token="ref_123",
        refresh_token_expires_in=7776000,
    )

    with pytest.raises(ValidationError, match="Merchant did not grant all required scopes"):
        complete_install("test.myshopify.com", "code123", "valid_nonce")


def test_complete_install_reinstall_keeps_tenant(mocker):
    tenant = TenantFactory()
    shop = ShopifyShop.objects.create(
        shop_domain="test.myshopify.com", tenant=tenant, uninstalled_at=timezone.now(), needs_reinstall=True
    )

    ShopifyOAuthState.objects.create(nonce="valid_nonce", shop_domain="test.myshopify.com")

    mock_exchange = mocker.patch("apps.shopify.client.ShopifyAdminClient.exchange_code")
    mock_exchange.return_value = TokenResponse(
        access_token="acc_123",
        scope=",".join(settings.SHOPIFY_SCOPES),
        expires_in=3600,
        refresh_token="ref_123",
        refresh_token_expires_in=7776000,
    )

    updated_shop = complete_install("test.myshopify.com", "code123", "valid_nonce")

    assert updated_shop.id == shop.id
    assert updated_shop.tenant == tenant
    assert updated_shop.uninstalled_at is None
    assert not updated_shop.needs_reinstall
