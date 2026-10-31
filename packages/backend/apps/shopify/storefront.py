"""
A store's products and carts through Shopify's Storefront API, for its WhatsApp customers (WhatsApp
plan Step 2.2, phase 2 decisions 1 and 3).

Products are read live on every call and never stored. Shopify's field names stay in this module:
callers get plain dicts with our own keys, as products.py's do for the Admin API.

- **The token:** the store's Admin token, sent as a private Storefront token from the server (WhatsApp
  plan Step 2.1b, decision 1). Shopify lists private tokens as the kind "used to query the API from a
  server" (https://shopify.dev/docs/api/storefront); the Admin token working as one was proven on a
  dev store (Step 2.1a, result 5), not stated in the docs. It's read through admin_client_for, which
  refreshes it when it's about to expire.
- **No buyer IP:** Shopify asks for `Shopify-Storefront-Buyer-IP` on requests from buyer traffic, so it
  can tell buyers apart; a WhatsApp chat has no buyer IP to send. None of the experiment's requests
  was throttled without it (Step 2.1a, result 7).
- **No country:** a cart uses the store's own default country (Step 2.1b, decision 2).

API version 2026-10: https://shopify.dev/docs/api/storefront/latest
"""

import json
from typing import Any

import requests
from django.conf import settings

from apps.shopify.client import ShopifyAPIError, ShopifyRefreshTokenRejected, admin_client_for
from apps.shopify.products import ShopifyReconnectRequired, ShopifyTryAgainLater

MAX_PAGE_SIZE = 50
# A product's variants, read with the product. Most stores have a handful; more than this aren't offered.
MAX_VARIANTS = 100


class ShopifyCartError(Exception):
    """Shopify refused a cart change, or dropped its line; the message is Shopify's, for the customer."""


PRODUCT_FIELDS = """
  id
  title
  description(truncateAt: 300)
  availableForSale
  featuredImage {
    url
    altText
  }
  priceRange {
    minVariantPrice {
      amount
      currencyCode
    }
    maxVariantPrice {
      amount
      currencyCode
    }
  }
"""

PAGE_INFO = """
  pageInfo {
    hasNextPage
    hasPreviousPage
    startCursor
    endCursor
  }
"""

# `available_for_sale` is one of the `query` filters, "products that have at least one product variant
# available for sale"; CREATED_AT with reverse lists the newest first:
# https://shopify.dev/docs/api/storefront/latest/queries/products
PRODUCTS_QUERY = f"""
query Products(
  $first: Int, $after: String, $last: Int, $before: String, $query: String,
  $sortKey: ProductSortKeys, $reverse: Boolean
) {{
  products(
    first: $first, after: $after, last: $last, before: $before, query: $query,
    sortKey: $sortKey, reverse: $reverse
  ) {{
    nodes {{
      {PRODUCT_FIELDS}
    }}
    {PAGE_INFO}
  }}
}}
"""

# Search returns products, pages and articles, by relevance; ProductFilter's `available` and
# unavailableProducts HIDE leave out what can't be bought:
# https://shopify.dev/docs/api/storefront/latest/queries/search
SEARCH_QUERY = f"""
query Search($query: String!, $first: Int, $after: String, $last: Int, $before: String) {{
  search(
    query: $query, first: $first, after: $after, last: $last, before: $before,
    types: [PRODUCT], productFilters: [{{available: true}}], unavailableProducts: HIDE
  ) {{
    nodes {{
      __typename
      ... on Product {{
        {PRODUCT_FIELDS}
      }}
    }}
    {PAGE_INFO}
  }}
}}
"""

# https://shopify.dev/docs/api/storefront/latest/queries/product
PRODUCT_QUERY = f"""
query Product($id: ID!) {{
  product(id: $id) {{
    {PRODUCT_FIELDS}
    variants(first: {MAX_VARIANTS}) {{
      nodes {{
        id
        title
        availableForSale
        price {{
          amount
          currencyCode
        }}
      }}
    }}
  }}
}}
"""

# https://shopify.dev/docs/api/storefront/latest/objects/Cart
CART_FIELDS = """
  id
  checkoutUrl
  totalQuantity
  cost {
    totalAmount {
      amount
      currencyCode
    }
  }
  lines(first: 50) {
    nodes {
      id
      quantity
      cost {
        totalAmount {
          amount
          currencyCode
        }
      }
      merchandise {
        ... on ProductVariant {
          id
          title
          product {
            title
          }
        }
      }
    }
  }
"""

CART_CHANGE_RESULT = f"""
    cart {{
      {CART_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
    warnings {{
      code
      message
      target
    }}
"""

# https://shopify.dev/docs/api/storefront/latest/mutations/cartCreate
CART_CREATE = f"""
mutation CartCreate($input: CartInput!) {{
  cartCreate(input: $input) {{
    {CART_CHANGE_RESULT}
  }}
}}
"""

# https://shopify.dev/docs/api/storefront/latest/mutations/cartLinesAdd
CART_LINES_ADD = f"""
mutation CartLinesAdd($cartId: ID!, $lines: [CartLineInput!]!) {{
  cartLinesAdd(cartId: $cartId, lines: $lines) {{
    {CART_CHANGE_RESULT}
  }}
}}
"""

# https://shopify.dev/docs/api/storefront/latest/queries/cart
CART_QUERY = f"""
query Cart($id: ID!) {{
  cart(id: $id) {{
    {CART_FIELDS}
  }}
}}
"""


def list_products(shop, first: int, after: str | None = None, before: str | None = None) -> dict[str, Any]:
    """One page of the products a customer can buy, newest first; paged as products.fetch_products is."""
    variables = _paging(first, after, before)
    variables.update({"query": "available_for_sale:true", "sortKey": "CREATED_AT", "reverse": True})
    products = _query(shop, PRODUCTS_QUERY, variables)["products"]
    return _page(products["nodes"], products["pageInfo"])


def search_products(
    shop, words: str, first: int, after: str | None = None, before: str | None = None
) -> dict[str, Any]:
    """One page of the products for sale matching `words`, most relevant first."""
    variables = {"query": words, **_paging(first, after, before)}
    found = _query(shop, SEARCH_QUERY, variables)["search"]
    products = [node for node in found["nodes"] if node.get("__typename") == "Product"]
    return _page(products, found["pageInfo"])


def get_product(shop, product_id: str) -> dict[str, Any] | None:
    """A product with its variants for sale, or None if Shopify no longer has it."""
    node = _query(shop, PRODUCT_QUERY, {"id": product_id})["product"]
    if node is None:
        return None
    product = _product(node)
    product["variants"] = [
        {"id": variant["id"], "title": variant["title"], **_money(variant["price"], "price")}
        for variant in node["variants"]["nodes"]
        if variant["availableForSale"]
    ]
    return product


def create_cart(shop, variant_id: str, *, phone: str | None) -> dict[str, Any]:
    """A new cart holding one of the variant, for the customer with this phone (E.164, with +) if known."""
    cart_input = {"lines": [_line(variant_id)]}
    if phone:
        cart_input["buyerIdentity"] = {"phone": phone}
    return _cart_change(shop, CART_CREATE, "cartCreate", {"input": cart_input})


def add_to_cart(shop, cart_id: str, variant_id: str) -> dict[str, Any]:
    """The cart, with one more of the variant (Shopify adds to its line if it has one)."""
    return _cart_change(shop, CART_LINES_ADD, "cartLinesAdd", {"cartId": cart_id, "lines": [_line(variant_id)]})


def get_cart(shop, cart_id: str) -> dict[str, Any] | None:
    """
    The cart, or None if Shopify no longer has it: carts "expire within 30 days of creation", and
    "Shopify automatically deletes the cart when the customer completes their checkout":
    https://shopify.dev/docs/storefronts/headless/building-with-the-storefront-api/cart
    """
    node = _query(shop, CART_QUERY, {"id": cart_id})["cart"]
    return _cart(node) if node else None


def _query(shop, query: str, variables: dict[str, Any]) -> dict[str, Any]:
    # The messages are fixed texts: they reach customers, so nothing from Shopify's reply goes in.
    if shop.uninstalled_at or shop.needs_reinstall:
        raise ShopifyReconnectRequired()
    try:
        # admin_client_for refreshes the token, and flags the store when Shopify rejects its refresh token.
        token = admin_client_for(shop).access_token
    except ShopifyRefreshTokenRejected as error:
        raise ShopifyReconnectRequired() from error

    url = f"https://{shop.shop_domain}/api/{settings.SHOPIFY_API_VERSION}/graphql.json"
    headers = {
        "Shopify-Storefront-Private-Token": token,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    response = requests.post(url, json={"query": query, "variables": variables}, headers=headers, timeout=10)
    if not response.ok:
        raise ShopifyAPIError(f"Storefront request failed: {response.status_code}")

    data = response.json()
    if "errors" in data:
        # THROTTLED comes inside an HTTP 200, "Similar to 429 Too Many Requests":
        # https://shopify.dev/docs/api/storefront
        if any((error.get("extensions") or {}).get("code") == "THROTTLED" for error in data["errors"]):
            raise ShopifyTryAgainLater()
        raise ShopifyAPIError(f"Storefront GraphQL errors: {json.dumps(data['errors'])}")
    return data["data"]


def _cart_change(shop, mutation: str, name: str, variables: dict[str, Any]) -> dict[str, Any]:
    result = _query(shop, mutation, variables)[name]
    if result["userErrors"]:
        raise ShopifyCartError(result["userErrors"][0]["message"])
    # A line Shopify can't fill is set to 0 with only a warning, e.g. MERCHANDISE_OUT_OF_STOCK when the
    # store doesn't sell it where the cart is (Step 2.1a, result 6), so those are refusals too.
    for warning in result["warnings"]:
        if warning["code"].startswith("MERCHANDISE_"):
            raise ShopifyCartError(warning["message"])
    return _cart(result["cart"])


def _paging(first: int, after: str | None, before: str | None) -> dict[str, Any]:
    page_size = min(first, MAX_PAGE_SIZE)
    if before:
        return {"last": page_size, "before": before}
    variables = {"first": page_size}
    if after:
        variables["after"] = after
    return variables


def _page(nodes: list[dict], page_info: dict) -> dict[str, Any]:
    return {
        "products": [_product(node) for node in nodes],
        "page_info": {
            "has_next_page": page_info["hasNextPage"],
            "has_previous_page": page_info["hasPreviousPage"],
            "start_cursor": page_info["startCursor"],
            "end_cursor": page_info["endCursor"],
        },
    }


def _product(node: dict[str, Any]) -> dict[str, Any]:
    price_range = node["priceRange"]
    return {
        "id": node["id"],
        "title": node["title"],
        "description": node["description"],
        "image_url": (node.get("featuredImage") or {}).get("url"),
        "price_min": price_range["minVariantPrice"]["amount"],
        "price_max": price_range["maxVariantPrice"]["amount"],
        "currency_code": price_range["minVariantPrice"]["currencyCode"],
    }


def _cart(node: dict[str, Any]) -> dict[str, Any]:
    total = node["cost"]["totalAmount"]
    return {
        "id": node["id"],
        "checkout_url": node["checkoutUrl"],
        "total_quantity": node["totalQuantity"],
        "total_amount": total["amount"],
        "currency_code": total["currencyCode"],
        "lines": [
            {
                "title": line["merchandise"]["product"]["title"],
                "variant": line["merchandise"]["title"],
                "quantity": line["quantity"],
                "amount": line["cost"]["totalAmount"]["amount"],
            }
            for line in node["lines"]["nodes"]
        ],
    }


def _money(money: dict[str, str], key: str) -> dict[str, str]:
    return {key: money["amount"], "currency_code": money["currencyCode"]}


def _line(variant_id: str) -> dict[str, Any]:
    return {"merchandiseId": variant_id, "quantity": 1}
