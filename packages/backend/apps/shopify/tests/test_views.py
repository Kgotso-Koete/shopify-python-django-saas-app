import hmac
import hashlib
from urllib.parse import urlencode

import pytest
from django.conf import settings
from django.urls import reverse
from django.core.signing import TimestampSigner
from graphql_relay import to_global_id

from apps.shopify.models import ShopifyShop, ShopifyOAuthState
from apps.multitenancy.tests.factories import TenantFactory


pytestmark = pytest.mark.django_db


def _sign_query(params: dict, secret: str) -> str:
    """Build query string using the same encoding as verification.py."""
    sorted_parts = []
    for k in sorted(params.keys()):
        v = params[k]
        encoded_k = str(k).replace("%", "%25").replace("&", "%26").replace("=", "%3D")
        encoded_v = str(v).replace("%", "%25").replace("&", "%26")
        sorted_parts.append(f"{encoded_k}={encoded_v}")
    query_string = "&".join(sorted_parts)
    return hmac.new(secret.encode("utf-8"), query_string.encode("utf-8"), hashlib.sha256).hexdigest()


def test_install_view_disabled(client, monkeypatch):
    monkeypatch.setattr(settings, "SHOPIFY_ENABLED", False)
    response = client.get(reverse("shopify-install") + "?shop=test.myshopify.com")
    assert response.status_code == 404


def test_install_view_missing_shop(client):
    response = client.get(reverse("shopify-install"))
    assert response.status_code == 400


def test_install_view_bad_hmac(client):
    response = client.get(reverse("shopify-install") + "?shop=test.myshopify.com&hmac=bad")
    assert response.status_code == 400


def test_install_view_new_shop_redirects_to_authorize(client):
    params = {"shop": "new-shop.myshopify.com", "timestamp": "123456"}
    params["hmac"] = _sign_query(params, settings.SHOPIFY_API_SECRET)

    response = client.get(reverse("shopify-install"), params)

    assert response.status_code == 302
    assert response.url.startswith("https://new-shop.myshopify.com/admin/oauth/authorize?")


def test_install_view_installed_unlinked_redirects_to_link(client, monkeypatch):
    ShopifyShop.objects.create(shop_domain="installed.myshopify.com", access_token="acc_123", refresh_token="ref_123")

    params = {"shop": "installed.myshopify.com", "timestamp": "123456"}
    params["hmac"] = _sign_query(params, settings.SHOPIFY_API_SECRET)

    response = client.get(reverse("shopify-install"), params)

    assert response.status_code == 302
    assert response.url.startswith(f"{settings.WEB_APP_URL}/shopify/link?claim=")


def test_install_view_installed_linked_redirects_to_webapp(client):
    tenant = TenantFactory()
    ShopifyShop.objects.create(
        shop_domain="linked.myshopify.com", access_token="acc_123", refresh_token="ref_123", tenant=tenant
    )

    params = {"shop": "linked.myshopify.com", "timestamp": "123456"}
    params["hmac"] = _sign_query(params, settings.SHOPIFY_API_SECRET)

    response = client.get(reverse("shopify-install"), params)

    assert response.status_code == 302
    # The shops list lives under /:tenantId/, so the redirect has to name the tenant;
    # without it the web app reads "shopify" as the tenant id.
    tenant_path = to_global_id("TenantType", tenant.id)
    assert response.url == f"{settings.WEB_APP_URL}/{tenant_path}/shopify?connected=linked.myshopify.com"


def test_callback_view_disabled(client, monkeypatch):
    monkeypatch.setattr(settings, "SHOPIFY_ENABLED", False)
    response = client.get(reverse("shopify-callback") + "?shop=test.myshopify.com")
    assert response.status_code == 404


def test_callback_view_missing_code_or_state(client):
    params = {"shop": "test.myshopify.com", "timestamp": "123456"}
    params["hmac"] = _sign_query(params, settings.SHOPIFY_API_SECRET)
    response = client.get(reverse("shopify-callback"), params)
    assert response.status_code == 400


def test_callback_view_happy_path_unlinked(client, mocker):
    ShopifyOAuthState.objects.create(nonce="nonce_123", shop_domain="test.myshopify.com")

    # Mock complete_install to return a new shop
    mock_complete = mocker.patch("apps.shopify.views.complete_install")
    shop = ShopifyShop(id=99, shop_domain="test.myshopify.com")
    mock_complete.return_value = shop

    params = {"shop": "test.myshopify.com", "code": "code_xyz", "state": "nonce_123", "timestamp": "123456"}
    params["hmac"] = _sign_query(params, settings.SHOPIFY_API_SECRET)

    response = client.get(reverse("shopify-callback"), params)

    assert response.status_code == 302
    assert response.url.startswith(f"{settings.WEB_APP_URL}/shopify/link?claim=")
    mock_complete.assert_called_once_with("test.myshopify.com", "code_xyz", "nonce_123")


def test_callback_view_happy_path_linked(client, mocker):
    tenant = TenantFactory()
    ShopifyOAuthState.objects.create(nonce="nonce_123", shop_domain="test.myshopify.com", tenant=tenant)

    # Mock complete_install to return a linked shop
    mock_complete = mocker.patch("apps.shopify.views.complete_install")
    shop = ShopifyShop(id=99, shop_domain="test.myshopify.com", tenant=tenant)
    mock_complete.return_value = shop

    params = {"shop": "test.myshopify.com", "code": "code_xyz", "state": "nonce_123", "timestamp": "123456"}
    params["hmac"] = _sign_query(params, settings.SHOPIFY_API_SECRET)

    response = client.get(reverse("shopify-callback"), params)

    assert response.status_code == 302
    tenant_path = to_global_id("TenantType", tenant.id)
    assert response.url == f"{settings.WEB_APP_URL}/{tenant_path}/shopify?connected=test.myshopify.com"
