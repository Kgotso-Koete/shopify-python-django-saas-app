"""
The cart's checkout code, which lets an order find the chat it came from (plan phase 4, Step 4.3a,
decisions 2, 4 and 21).

- **A new code per cart:** every cart the chat creates (Add to cart's open cart, and each Buy now)
  carries `wachk_` and 22 random characters from `secrets` as its `_whatsapp_checkout` attribute, so
  the code says what it is and can't be guessed. Shopify copies a cart's attributes to its order.
- **Kept with the cart:** a StoreCheckout row holds the code, the store customer, the store and the
  cart's id, made only once Shopify has accepted the cart.
- **The View cart link carries it too** (decision 21), as `attributes[_whatsapp_checkout]=…`, so an
  order placed from the website's cart finds the chat as well. A cart made before codes existed has
  none, and its link goes without one.
- **The customer never sees it:** checked at checkout, on the thank-you page, in the confirmation
  email and on the order status page (plan section 13, Experiment 4.3).
"""

import secrets

from apps.shopify import storefront

from .models import StoreCheckout

CHECKOUT_ATTRIBUTE = "_whatsapp_checkout"
CODE_PREFIX = "wachk_"
# token_urlsafe(16) is 22 characters, from letters, digits, - and _: safe in a link as it is.
CODE_BYTES = 16


def new_code() -> str:
    return f"{CODE_PREFIX}{secrets.token_urlsafe(CODE_BYTES)}"


def create_cart(store_customer, shop, variant_id: str, *, phone: str | None) -> dict:
    """A new cart in `shop` holding one of the variant, carrying a new code, which is kept with it."""
    code = new_code()
    cart = storefront.create_cart(shop, variant_id, phone=phone, attributes={CHECKOUT_ATTRIBUTE: code})
    StoreCheckout.objects.create(code=code, store_customer=store_customer, shop=shop, cart_id=cart["id"])
    return cart


def view_cart_url(store_customer, shop, cart: dict) -> str:
    """The shop's own cart page holding `cart`'s items, with the cart's code if it has one."""
    checkout = StoreCheckout.objects.filter(store_customer=store_customer, shop=shop, cart_id=cart["id"]).first()
    attributes = {CHECKOUT_ATTRIBUTE: checkout.code} if checkout else None
    return storefront.cart_page_url(shop, cart, attributes=attributes)
