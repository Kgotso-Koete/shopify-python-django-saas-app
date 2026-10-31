"""
Tests for the install services in apps/shopify/services.py: start_install and complete_install.

Kind of test: integration (agents.md section 2.5). Why: they write OAuth states and stores in the
test database; Shopify's OAuth code exchange is mocked.
"""

import pytest
import datetime
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.shopify.services import start_install, complete_install, missing_scopes
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


class TestAWriteScopeCoversItsReadScope:
    """
    WhatsApp plan Step 2.1b, decision 3. Shopify: "Any scope that writes a resource also grants read
    access to it" (https://shopify.dev/docs/api/usage/access-scopes), and a dev store's install
    granted unauthenticated_write_checkouts without listing unauthenticated_read_checkouts (Step 2.1a,
    result 2). So a requested read scope counts as granted when its write twin is.
    """

    def test_a_read_scope_is_covered_by_its_granted_write_scope(self):
        required = ["read_products", "unauthenticated_read_checkouts", "unauthenticated_write_checkouts"]

        assert missing_scopes(required, "read_products,unauthenticated_write_checkouts") == set()

    def test_a_write_scope_is_not_covered_by_its_read_scope(self):
        assert missing_scopes(["write_products"], "read_products") == {"write_products"}

    def test_a_scope_with_no_granted_twin_is_missing(self):
        assert missing_scopes(["read_products", "read_orders"], "read_products,write_products") == {"read_orders"}

    def test_spaces_around_granted_scopes_are_ignored(self):
        assert missing_scopes(["read_products"], " read_products , write_orders ") == set()

    def test_the_install_accepts_a_read_scope_covered_by_its_write_scope(self, mocker, settings):
        settings.SHOPIFY_SCOPES = ["read_products", "unauthenticated_read_checkouts", "unauthenticated_write_checkouts"]
        ShopifyOAuthState.objects.create(nonce="valid_nonce", shop_domain="test.myshopify.com")
        mock_exchange = mocker.patch("apps.shopify.client.ShopifyAdminClient.exchange_code")
        mock_exchange.return_value = TokenResponse(
            access_token="acc_123",
            # What Shopify sent back in Step 2.1a: the write scope, without its read twin.
            scope="read_products,unauthenticated_write_checkouts",
            expires_in=3600,
            refresh_token="ref_123",
            refresh_token_expires_in=7776000,
        )

        shop = complete_install("test.myshopify.com", "code123", "valid_nonce")

        assert shop.scopes == "read_products,unauthenticated_write_checkouts"

    def test_the_install_still_refuses_a_scope_that_is_really_missing(self, mocker, settings):
        settings.SHOPIFY_SCOPES = ["read_products", "unauthenticated_read_product_listings"]
        ShopifyOAuthState.objects.create(nonce="valid_nonce", shop_domain="test.myshopify.com")
        mock_exchange = mocker.patch("apps.shopify.client.ShopifyAdminClient.exchange_code")
        mock_exchange.return_value = TokenResponse(
            access_token="acc_123",
            scope="read_products",
            expires_in=3600,
            refresh_token="ref_123",
            refresh_token_expires_in=7776000,
        )

        with pytest.raises(ValidationError, match="unauthenticated_read_product_listings"):
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
