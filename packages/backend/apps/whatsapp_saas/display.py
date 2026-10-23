"""How a Shopify product's price and status read in chat, for the menus and the assistant alike."""

PRODUCT_STATUSES = {"ACTIVE": "Active", "DRAFT": "Draft", "ARCHIVED": "Archived"}


def price(product: dict) -> str:
    """The price, such as "ZAR 19.99", or a range such as "ZAR 19.99 – 24.50" when variants differ."""
    if product["price_min"] == product["price_max"]:
        return f"{product['currency_code']} {product['price_min']}"
    return f"{product['currency_code']} {product['price_min']} – {product['price_max']}"


def status(product: dict) -> str:
    return PRODUCT_STATUSES.get(product["status"], product["status"].capitalize())
