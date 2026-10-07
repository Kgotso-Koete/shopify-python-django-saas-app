import pytest
import requests
from django.conf import settings

from apps.shopify.client import (
    ShopifyAdminClient,
    ShopifyAuthError,
    ShopifyRefreshTokenRejected,
    ShopifyAPIError,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def shopify_client():
    return ShopifyAdminClient(shop_domain="test.myshopify.com", access_token="test-token")


def test_exchange_code(mocker, shopify_client):
    mock_response = mocker.Mock()
    mock_response.ok = True
    mock_response.json.return_value = {
        "access_token": "acc_123",
        "scope": "read_products",
        "expires_in": 3600,
        "refresh_token": "ref_123",
        "refresh_token_expires_in": 7776000,
    }
    mocker.patch("requests.post", return_value=mock_response)

    token_response = shopify_client.exchange_code("auth_code_xyz")

    requests.post.assert_called_once_with(
        "https://test.myshopify.com/admin/oauth/access_token",
        json={
            "client_id": settings.SHOPIFY_API_KEY,
            "client_secret": settings.SHOPIFY_API_SECRET,
            "code": "auth_code_xyz",
            "expiring": "1",
        },
        timeout=10,
    )

    assert token_response.access_token == "acc_123"
    assert token_response.scope == "read_products"
    assert token_response.refresh_token == "ref_123"


def test_exchange_code_failure(mocker, shopify_client):
    mock_response = mocker.Mock()
    mock_response.ok = False
    mock_response.status_code = 400
    mock_response.text = "Bad Request"
    mocker.patch("requests.post", return_value=mock_response)

    with pytest.raises(ShopifyAuthError, match="Failed to exchange code: 400"):
        shopify_client.exchange_code("bad_code")


def test_refresh_token(mocker, shopify_client):
    mock_response = mocker.Mock()
    mock_response.ok = True
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "access_token": "acc_new",
        "scope": "read_products",
        "expires_in": 3600,
        "refresh_token": "ref_new",
        "refresh_token_expires_in": 7776000,
    }
    mocker.patch("requests.post", return_value=mock_response)

    token_response = shopify_client.refresh("old_ref_token")

    requests.post.assert_called_once_with(
        "https://test.myshopify.com/admin/oauth/access_token",
        json={
            "client_id": settings.SHOPIFY_API_KEY,
            "client_secret": settings.SHOPIFY_API_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": "old_ref_token",
        },
        timeout=10,
    )

    assert token_response.access_token == "acc_new"
    assert token_response.refresh_token == "ref_new"


def test_refresh_token_rejected_terminal(mocker, shopify_client):
    mock_response = mocker.Mock()
    mock_response.ok = False
    mock_response.status_code = 401
    mocker.patch("requests.post", return_value=mock_response)

    with pytest.raises(ShopifyRefreshTokenRejected, match="Refresh token rejected"):
        shopify_client.refresh("revoked_ref_token")


def test_refresh_token_transient_failure(mocker, shopify_client):
    mock_response = mocker.Mock()
    mock_response.ok = False
    mock_response.status_code = 500
    mock_response.text = "Internal Server Error"
    mocker.patch("requests.post", return_value=mock_response)

    with pytest.raises(ShopifyAuthError, match="Failed to refresh token: 500"):
        shopify_client.refresh("good_ref_token")


def test_graphql_success(mocker, shopify_client):
    mock_response = mocker.Mock()
    mock_response.ok = True
    mock_response.json.return_value = {"data": {"shop": {"name": "Test Shop"}}}
    mocker.patch("requests.post", return_value=mock_response)

    data = shopify_client.graphql("{ shop { name } }")

    requests.post.assert_called_once_with(
        f"https://test.myshopify.com/admin/api/{settings.SHOPIFY_API_VERSION}/graphql.json",
        json={"query": "{ shop { name } }"},
        headers={
            "X-Shopify-Access-Token": "test-token",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        timeout=10,
    )
    assert data["shop"]["name"] == "Test Shop"


def test_graphql_with_variables(mocker, shopify_client):
    mock_response = mocker.Mock()
    mock_response.ok = True
    mock_response.json.return_value = {"data": {"product": {"title": "Shoes"}}}
    mocker.patch("requests.post", return_value=mock_response)

    shopify_client.graphql(query="query($id: ID!) { product(id: $id) { title } }", variables={"id": "gid://123"})

    kwargs = requests.post.call_args[1]
    assert kwargs["json"]["variables"] == {"id": "gid://123"}


def test_graphql_http_error(mocker, shopify_client):
    mock_response = mocker.Mock()
    mock_response.ok = False
    mock_response.status_code = 404
    mock_response.text = "Not Found"
    mocker.patch("requests.post", return_value=mock_response)

    with pytest.raises(ShopifyAPIError, match="GraphQL request failed: 404"):
        shopify_client.graphql("{ shop { name } }")


def test_graphql_response_errors(mocker, shopify_client):
    mock_response = mocker.Mock()
    mock_response.ok = True
    mock_response.json.return_value = {"errors": [{"message": "Access denied"}]}
    mocker.patch("requests.post", return_value=mock_response)

    with pytest.raises(ShopifyAPIError, match="GraphQL errors:"):
        shopify_client.graphql("{ shop { name } }")


def test_graphql_requires_access_token():
    client = ShopifyAdminClient("test.myshopify.com")
    with pytest.raises(ValueError, match="access_token is required"):
        client.graphql("{ shop { name } }")


# ---------------------------------------------------------------------------
# admin_client_for Tests
# ---------------------------------------------------------------------------

from datetime import timedelta
from django.utils import timezone
from apps.shopify.models import ShopifyShop
from apps.shopify.client import admin_client_for


def test_admin_client_for_no_refresh_needed(mocker):
    # Setup shop with token expiring far in the future
    future_time = timezone.now() + timedelta(minutes=30)
    shop = ShopifyShop.objects.create(
        shop_domain="admin-client.myshopify.com",
        access_token="acc_valid",
        refresh_token="ref_valid",
        access_token_expires_at=future_time,
    )

    mock_refresh = mocker.patch.object(ShopifyAdminClient, "refresh")

    client = admin_client_for(shop)

    assert client.shop_domain == "admin-client.myshopify.com"
    assert client.access_token == "acc_valid"
    mock_refresh.assert_not_called()


def test_admin_client_for_needs_refresh(mocker):
    # Setup shop with token expiring soon (within REFRESH_MARGIN_SECONDS)
    soon_time = timezone.now() + timedelta(minutes=2)
    shop = ShopifyShop.objects.create(
        shop_domain="admin-client-refresh.myshopify.com",
        access_token="acc_old",
        refresh_token="ref_old",
        access_token_expires_at=soon_time,
    )

    from apps.shopify.client import TokenResponse

    mock_refresh = mocker.patch.object(ShopifyAdminClient, "refresh")
    mock_refresh.return_value = TokenResponse(
        access_token="acc_new",
        scope="read_products",
        expires_in=3600,
        refresh_token="ref_new",
        refresh_token_expires_in=7776000,
    )

    client = admin_client_for(shop)

    assert client.shop_domain == "admin-client-refresh.myshopify.com"
    assert client.access_token == "acc_new"

    # Check that shop was updated
    shop.refresh_from_db()
    assert shop.access_token_encrypted != ""
    assert shop.access_token == "acc_new"
    assert shop.refresh_token == "ref_new"
    assert shop.access_token_expires_at > timezone.now() + timedelta(minutes=50)


def test_admin_client_for_null_expiry(mocker):
    # Setup shop with null access_token_expires_at (legacy or manual entry)
    shop = ShopifyShop.objects.create(
        shop_domain="admin-client-null.myshopify.com",
        access_token="acc_null_expiry",
        refresh_token="ref_null_expiry",
        access_token_expires_at=None,
    )

    mock_refresh = mocker.patch.object(ShopifyAdminClient, "refresh")

    client = admin_client_for(shop)

    assert client.shop_domain == "admin-client-null.myshopify.com"
    assert client.access_token == "acc_null_expiry"
    mock_refresh.assert_not_called()
