"""
An order's details, asked of Shopify's Admin API each time they're needed (WhatsApp plan phase 4, decision 4;
Step 4.7, decision 30, user stories WA.D5.SC.J1.A2 and WA.D3.OM.J2.A3; agents.md section 5.3d): the app keeps
only the order's id. Only protected customer data level 1 fields are asked for; the status page link
(statusPageUrl) needs level 2, which this app doesn't have, and opens the order to whoever holds it.

Needs the read_orders scope, which a store has whenever it sends order webhooks (decision 8). Errors
are the ones products.py raises, for the same reasons.
"""

from apps.shopify.client import ShopifyRefreshTokenRejected, ShopifyThrottledError, admin_client_for
from apps.shopify.products import ShopifyReconnectRequired, ShopifyTryAgainLater

ORDER_DETAILS_QUERY = """
query OrderDetails($id: ID!) {
  order(id: $id) {
    name
    cancelledAt
    displayFinancialStatus
    displayFulfillmentStatus
    totalPriceSet {
      shopMoney {
        amount
        currencyCode
      }
    }
    lineItems(first: 50) {
      nodes {
        title
        quantity
      }
    }
  }
}
"""


def order_details(shop, order_id: int) -> dict | None:
    """
    `shop`'s order `order_id` as Shopify has it now (WhatsApp plan Step 4.7, decision 30; agents.md section
    5.3d): its `name` (such as "#1006"), `total_price` and `currency`, `financial_status` and
    `fulfillment_status` (Shopify's display statuses, such as "PAID" and "UNFULFILLED"), whether it's
    `cancelled`, and its `lines`, each a title and quantity. Only protected customer data level 1 fields:
    never the customer, an address or the status page. None when Shopify no longer has the order.
    https://shopify.dev/docs/api/admin-graphql/latest/objects/Order
    """
    order = _order(shop, order_id, ORDER_DETAILS_QUERY)
    if not order:
        return None
    money = (order.get("totalPriceSet") or {}).get("shopMoney") or {}
    return {
        "id": order_id,
        "name": order.get("name") or "",
        "total_price": money.get("amount"),
        "currency": money.get("currencyCode"),
        "financial_status": order.get("displayFinancialStatus") or "",
        "fulfillment_status": order.get("displayFulfillmentStatus") or "",
        "cancelled": bool(order.get("cancelledAt")),
        "lines": [
            {"title": line.get("title") or "", "quantity": line.get("quantity") or 0}
            for line in (order.get("lineItems") or {}).get("nodes") or []
        ],
    }


def _order(shop, order_id: int, query: str) -> dict | None:
    """Shopify's answer about the order, or None; raises when the store must be reconnected or is throttled."""
    if shop.uninstalled_at or shop.needs_reinstall:
        raise ShopifyReconnectRequired()
    try:
        # admin_client_for flags the store needs_reinstall when Shopify rejects its refresh token.
        data = admin_client_for(shop).graphql(query, variables={"id": f"gid://shopify/Order/{order_id}"})
    except ShopifyRefreshTokenRejected as error:
        raise ShopifyReconnectRequired() from error
    except ShopifyThrottledError as error:
        raise ShopifyTryAgainLater() from error
    return data.get("order")
