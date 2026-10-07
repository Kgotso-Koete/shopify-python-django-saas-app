import json
from dataclasses import dataclass
from typing import Any

import requests
from django.conf import settings


class ShopifyAuthError(Exception):
    """Raised when authentication fails (e.g., exchanging code or refreshing)."""


class ShopifyRefreshTokenRejected(ShopifyAuthError):
    """Raised when a refresh token is permanently rejected (401)."""


class ShopifyAPIError(Exception):
    """Raised when a GraphQL request returns HTTP errors or GraphQL-level errors."""


@dataclass
class TokenResponse:
    access_token: str
    scope: str
    expires_in: int
    refresh_token: str
    refresh_token_expires_in: int


class ShopifyAdminClient:
    """
    Client for interacting with the Shopify Admin API.
    Used for exchanging OAuth codes, refreshing tokens, and making GraphQL queries.
    """

    def __init__(self, shop_domain: str, access_token: str | None = None):
        self.shop_domain = shop_domain
        self.access_token = access_token
        self.api_version = settings.SHOPIFY_API_VERSION

    @property
    def _base_url(self) -> str:
        return f"https://{self.shop_domain}"

    def exchange_code(self, code: str) -> TokenResponse:
        """
        Exchange an OAuth authorization code for an offline access token (with refresh token).
        """
        url = f"{self._base_url}/admin/oauth/access_token"
        payload = {
            "client_id": settings.SHOPIFY_API_KEY,
            "client_secret": settings.SHOPIFY_API_SECRET,
            "code": code,
            "expiring": "1",  # Request an expiring offline token
        }

        response = requests.post(url, json=payload, timeout=10)

        if not response.ok:
            raise ShopifyAuthError(f"Failed to exchange code: {response.status_code} {response.text}")

        data = response.json()
        return TokenResponse(
            access_token=data["access_token"],
            scope=data["scope"],
            expires_in=data["expires_in"],
            refresh_token=data["refresh_token"],
            refresh_token_expires_in=data["refresh_token_expires_in"],
        )

    def refresh(self, refresh_token: str) -> TokenResponse:
        """
        Refresh an expiring offline token.
        """
        url = f"{self._base_url}/admin/oauth/access_token"
        payload = {
            "client_id": settings.SHOPIFY_API_KEY,
            "client_secret": settings.SHOPIFY_API_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }

        response = requests.post(url, json=payload, timeout=10)

        if response.status_code == 401:
            # 401 on refresh is terminal (revoked, uninstalled, or already consumed).
            raise ShopifyRefreshTokenRejected("Refresh token rejected")
        elif not response.ok:
            # 5xx, 429, network errors are transient; we raise AuthError and can retry later
            raise ShopifyAuthError(f"Failed to refresh token: {response.status_code} {response.text}")

        data = response.json()
        return TokenResponse(
            access_token=data["access_token"],
            scope=data["scope"],
            expires_in=data["expires_in"],
            refresh_token=data["refresh_token"],
            refresh_token_expires_in=data["refresh_token_expires_in"],
        )

    def graphql(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        """
        Execute a GraphQL query against the Admin API.
        """
        if not self.access_token:
            raise ValueError("access_token is required for GraphQL requests")

        url = f"{self._base_url}/admin/api/{self.api_version}/graphql.json"
        headers = {
            "X-Shopify-Access-Token": self.access_token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        payload = {"query": query}
        if variables:
            payload["variables"] = variables

        response = requests.post(url, json=payload, headers=headers, timeout=10)

        if not response.ok:
            raise ShopifyAPIError(f"GraphQL request failed: {response.status_code} {response.text}")

        data = response.json()
        if "errors" in data:
            raise ShopifyAPIError(f"GraphQL errors: {json.dumps(data['errors'])}")

        return data["data"]


def admin_client_for(shop) -> ShopifyAdminClient:
    """
    Returns an initialized ShopifyAdminClient for the given ShopifyShop.
    If the access token is expiring within REFRESH_MARGIN_SECONDS, it refreshes
    it automatically and updates the ShopifyShop record in the database.
    """
    from datetime import timedelta
    from django.utils import timezone
    from apps.shopify.constants import REFRESH_MARGIN_SECONDS

    client = ShopifyAdminClient(shop_domain=shop.shop_domain, access_token=shop.access_token)

    # If we don't have an expiry, assume it's valid (e.g. legacy non-expiring token)
    if not shop.access_token_expires_at:
        return client

    # Check if expiring soon
    margin = timedelta(seconds=REFRESH_MARGIN_SECONDS)
    if timezone.now() + margin > shop.access_token_expires_at:
        # Needs refresh
        token_response = client.refresh(shop.refresh_token)

        # Update shop
        shop.access_token = token_response.access_token
        shop.refresh_token = token_response.refresh_token
        shop.access_token_expires_at = timezone.now() + timedelta(seconds=token_response.expires_in)
        if token_response.refresh_token_expires_in:
            shop.refresh_token_expires_at = timezone.now() + timedelta(seconds=token_response.refresh_token_expires_in)

        shop.save(
            update_fields=[
                "access_token_encrypted",
                "refresh_token_encrypted",
                "access_token_expires_at",
                "refresh_token_expires_at",
            ]
        )

        # Update client with new access token
        client.access_token = token_response.access_token

    return client
