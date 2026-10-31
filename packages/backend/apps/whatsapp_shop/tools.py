"""
The store assistant's tools, for a store customer on an external number set to the assistant (plan
Step 2.5, phase 2 decisions 2 and 3, D12).

A fixed list, reading only the number's own store, so the assistant can't reach another shop:
- find_products: products for sale, by words or newest first, 7 at a time
- show_product and show_cart: end the turn on the menus' own screen, so Add to cart, Buy now and
  Checkout are the customer's presses (phase 2, decision 3). No tool changes the cart.

A product id the model makes up finds nothing in this store and says the product isn't for sale.
A problem comes back as {"success": false, "error": ...}, as the team's tools return one.
"""

from apps.shopify import storefront
from apps.shopify.client import ShopifyAPIError
from apps.shopify.products import ShopifyReconnectRequired, ShopifyTryAgainLater
from apps.whatsapp.agent.tools import Tool, ToolResult, Toolset
from apps.whatsapp.builders import LIST_ITEMS_MAX

from . import menus, services

NULLABLE_STRING = {"type": ["string", "null"]}
UNREACHABLE = {"success": False, "error": "The shop can't be reached right now."}
SHOWN = {
    "success": True,
    "status": "shown",
    "message": "The customer now sees it with its buttons, and chooses for themselves.",
}
# The list page a shown product's Back returns to: the newest products.
NEWEST = {"words": None, "after": None, "before": None}


def find_products(turn, words, after):
    shop = services.store_for(turn.contact.account)
    try:
        if words and words.strip():
            found = storefront.search_products(shop, words.strip(), first=LIST_ITEMS_MAX, after=after, before=None)
        else:
            found = storefront.list_products(shop, first=LIST_ITEMS_MAX, after=after, before=None)
    except (ShopifyReconnectRequired, ShopifyTryAgainLater, ShopifyAPIError):
        return dict(UNREACHABLE)
    page_info = found["page_info"]
    return {
        "success": True,
        "products": [
            {"id": item["id"], "title": item["title"], "price": menus.price(item), "description": item["description"]}
            for item in found["products"]
        ],
        "next_page": page_info["end_cursor"] if page_info["has_next_page"] else None,
    }


def show_product(turn, product_id):
    handler = menus.StoreHandler()
    return ToolResult(
        dict(SHOWN), messages=handler.show(turn, menus.PRODUCT, {"product_id": product_id, "back": NEWEST})
    )


def show_cart(turn):
    handler = menus.StoreHandler()
    return ToolResult(dict(SHOWN), messages=handler.show(turn, menus.CART, {}))


TOOLS = Toolset(
    [
        Tool(
            "find_products",
            "Find the shop's products for sale. Give words to search for, or null for the newest. Pass a "
            "previous result's next_page as after for the next 7, or null.",
            {"words": NULLABLE_STRING, "after": NULLABLE_STRING},
            find_products,
        ),
        Tool(
            "show_product",
            "Show the customer one product, by an id from find_products, with its picture, price, options and "
            "the Add to cart and Buy now buttons. Ends your turn: the customer taps what they want.",
            {"product_id": {"type": "string"}},
            show_product,
        ),
        Tool(
            "show_cart",
            "Show the customer their cart, with its total and the Checkout button. Ends your turn.",
            {},
            show_cart,
        ),
    ]
)
