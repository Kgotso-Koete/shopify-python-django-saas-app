"""
Read a store's products from the Shopify Admin API (plan step 11, section 5.2).

Products are fetched live on every call and never stored. Shopify's field names stay in this
module: callers get plain dicts with our own keys.
"""

from typing import Any

from apps.shopify.client import ShopifyRefreshTokenRejected, ShopifyThrottledError, admin_client_for

MAX_PAGE_SIZE = 50


class ShopifyReconnectRequired(Exception):
    """The store is uninstalled or its tokens no longer work; only reconnecting it helps."""

    def __init__(self):
        super().__init__("This store needs to be reconnected. Open the Shopify page and connect it again.")


class ShopifyTryAgainLater(Exception):
    """Shopify rate-limited the request; the same request works again after a short wait."""

    def __init__(self):
        super().__init__("Shopify is busy right now. Try again in a few seconds.")


# Admin API 2026-10. featuredImage and priceRange are deprecated, so featuredMedia and priceRangeV2.
# Paging forward is first + after; backward is last + before.
PRODUCTS_QUERY = """
query Products($first: Int, $after: String, $last: Int, $before: String) {
  products(first: $first, after: $after, last: $last, before: $before) {
    nodes {
      id
      title
      handle
      status
      featuredMedia {
        preview {
          image {
            url
            altText
          }
        }
      }
      priceRangeV2 {
        minVariantPrice {
          amount
          currencyCode
        }
        maxVariantPrice {
          amount
          currencyCode
        }
      }
    }
    pageInfo {
      hasNextPage
      hasPreviousPage
      startCursor
      endCursor
    }
  }
}
"""


def fetch_products(shop, first: int, after: str | None = None, before: str | None = None) -> dict[str, Any]:
    """
    One page of the shop's products. `first` is the page size, capped at MAX_PAGE_SIZE; pass the
    previous page's end cursor as `after` for the next page, or its start cursor as `before` for the
    previous one.
    """
    # The messages are fixed texts: they reach the browser, so nothing from Shopify's reply goes in.
    if shop.uninstalled_at or shop.needs_reinstall:
        raise ShopifyReconnectRequired()

    page_size = min(first, MAX_PAGE_SIZE)
    if before:
        variables = {"last": page_size, "before": before}
    else:
        variables = {"first": page_size}
        if after:
            variables["after"] = after

    try:
        # admin_client_for flags the store needs_reinstall when Shopify rejects its refresh token.
        data = admin_client_for(shop).graphql(PRODUCTS_QUERY, variables=variables)
    except ShopifyRefreshTokenRejected as error:
        raise ShopifyReconnectRequired() from error
    except ShopifyThrottledError as error:
        raise ShopifyTryAgainLater() from error
    products = data["products"]
    page_info = products["pageInfo"]

    return {
        "products": [_product(node) for node in products["nodes"]],
        "page_info": {
            "has_next_page": page_info["hasNextPage"],
            "has_previous_page": page_info["hasPreviousPage"],
            "start_cursor": page_info["startCursor"],
            "end_cursor": page_info["endCursor"],
        },
    }


def _product(node: dict[str, Any]) -> dict[str, Any]:
    # No media, or media whose preview Shopify hasn't finished processing, means no image.
    image = ((node.get("featuredMedia") or {}).get("preview") or {}).get("image") or {}
    price_range = node["priceRangeV2"]
    return {
        "id": node["id"],
        "title": node["title"],
        "handle": node["handle"],
        "status": node["status"],
        "image_url": image.get("url"),
        "image_alt": image.get("altText"),
        "price_min": price_range["minVariantPrice"]["amount"],
        "price_max": price_range["maxVariantPrice"]["amount"],
        "currency_code": price_range["minVariantPrice"]["currencyCode"],
    }
