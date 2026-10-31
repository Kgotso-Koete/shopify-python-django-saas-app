"""
The external communications numbers' handler: what a store customer gets when they text an
organization's own WhatsApp number (plan phase 2, decision D1, user stories 12, 13, 14, 16 and 21).
Registered with apps.whatsapp's registry in apps.py.

- **Who is answered:** anyone texting a number that sells from a store that can still sell on
  WhatsApp. A number with no store chosen, or whose store was uninstalled, needs a reinstall or lacks
  the storefront scopes, sends no reply at all (user story 25).
- **The store customer:** made on their first message, one per contact (D4).
- **The mode:** the number's own setting, menus by default (phase 2, decision 2).

Every screen is built with apps.whatsapp's builders, so every one offers a way back (D17), and every
button is an opaque id from turn.choice (section 8.5).

Products (Step 2.3, user story 12) are read live from the store's Storefront API, never stored: only
those for sale, 7 to a page. Browsing lists the newest first; searching asks for typed words
(turn.expect_text) and lists the most relevant first. Shopify pages by cursor, so each Previous and
Next carries the cursor, and a search's words, of the page it leads to.

A product (Step 2.4, user story 13) shows its picture, price and description. With one variant it
offers Add to cart, Buy now and Back; with several, the customer picks a variant first.

The cart (phase 2, decision 1, user story 16): Add to cart keeps one open cart per store customer, a
Storefront cart whose id is on their StoreCustomer; Buy now makes a separate one-item cart. Checkout
is a link button to the cart's own Shopify checkout, which is the whole payment step (D13): this app
never sees a payment. A cart Shopify no longer has (expired, or checked out) or one from the
number's previous store is started afresh.
"""

from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

from apps.shopify import storefront
from apps.shopify.client import ShopifyAPIError
from apps.shopify.products import ShopifyReconnectRequired, ShopifyTryAgainLater
from apps.shopify.storefront import ShopifyCartError
from apps.whatsapp.agent import service as agent
from apps.whatsapp.agent.service import AgentError
from apps.whatsapp.builders import (
    LIST_ITEMS_MAX,
    MAIN_MENU,
    Choice,
    Row,
    link_button,
    list_message,
    reply_buttons,
    text_reply,
)

from . import services
from .models import StoreCustomer, StorefrontChannel

BROWSE = "browse"
SEARCH = "search"
CART = "cart"
PRODUCT = "product"
VARIANTS = "variants"
VARIANT = "variant"
ADD = "cart.add"
BUY = "buy"
CHECKOUT = "checkout"
EMPTY = "cart.empty"

# Meta's image headers take JPEG or PNG only; another format would fail the whole message.
SHOWABLE_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png")
# The cart's lines shown in one message; a longer cart says how many more it holds.
CART_LINES_SHOWN = 10
CHECKOUT_TEXT = "Tap Checkout to pay in the shop's secure Shopify checkout."

# Longer than any product search needs; it's kept in the conversation with each page's buttons.
SEARCH_WORDS_MAX = 100

UNREACHABLE_TEXT = "The shop can't be reached right now. Please try again in a few minutes."
ASSISTANT_UNAVAILABLE_TEXT = "Sorry, the assistant isn't available right now. Send *menu* to browse the shop instead."

HELP_TEXT = (
    "Send *menu* at any time for the main menu: browse the shop's products, search them, or see your "
    "cart and check out. *cancel* stops what you're doing."
)


class StoreHandler:
    """Answers store customers on an external number (registry.py describes the methods)."""

    def answers(self, contact) -> bool:
        shop = services.store_for(contact.account)
        return shop is not None and services.can_sell_on_whatsapp(shop)

    def conversation_mode(self, contact) -> str:
        channel = StorefrontChannel.objects.filter(account=contact.account).first()
        return channel.conversation_mode if channel else ""

    def help_text(self, turn) -> str:
        return HELP_TEXT

    def main_menu(self, turn) -> list[dict]:
        _store_customer(turn)
        rows = [
            Row(turn.choice(BROWSE), "Browse products", "The newest first"),
            Row(turn.choice(SEARCH), "Search", "Find a product by name"),
            Row(turn.choice(CART), "Your cart", "See what's in it and check out"),
        ]
        body = f"Welcome to {_shop_name(turn)}. What would you like to do?"
        return [list_message(body, button_label="Menu", section_title="Main menu", rows=rows)]

    def on_choice(self, turn, kind: str, data: dict) -> list[dict]:
        screens = {
            BROWSE: self._products,
            SEARCH: self._search,
            PRODUCT: self._product,
            VARIANTS: self._product,
            VARIANT: self._variant,
            ADD: self._add_to_cart,
            BUY: self._buy_now,
            CART: self._cart,
            CHECKOUT: self._checkout,
            EMPTY: self._empty_cart,
        }
        screen = screens.get(kind)
        if screen is None:
            return self.main_menu(turn)
        return self._show(turn, screen, data)

    def show(self, turn, kind: str, data: dict) -> list[dict]:
        """The screen a button of `kind` with `data` leads to; the assistant's tools show screens with it."""
        return self.on_choice(turn, kind, data)

    def on_free_text(self, turn, text: str) -> list[dict]:
        # The number is set to the assistant (phase 2, decision 2); it only shows, the customer taps (decision 3).
        from . import prompts
        from .tools import TOOLS

        _store_customer(turn)
        try:
            return agent.respond(turn, text, tools=TOOLS, instructions=prompts.instructions(_shop_name(turn)))
        except AgentError:
            # The channel's texts point to the team's "mode menu"; a customer has the menus instead.
            return text_reply(ASSISTANT_UNAVAILABLE_TEXT) + self.main_menu(turn)

    def on_typed_answer(self, turn, kind: str, data: dict, text: str) -> list[dict]:
        words = " ".join(text.split())[:SEARCH_WORDS_MAX]
        if kind != SEARCH or not words:
            return self.main_menu(turn)
        return self._show(turn, self._products, {"words": words})

    def on_flow_reply(self, turn, response: dict) -> list[dict]:
        # This number sends no forms.
        return self.main_menu(turn)

    def _show(self, turn, screen, data) -> list[dict]:
        """A screen, or that the shop can't be reached and the main menu."""
        try:
            return screen(turn, data)
        except ShopifyCartError as error:
            # Shopify's own words for the customer, such as "The product 'X' is already sold out."
            return text_reply(f"Sorry, that couldn't go in your cart: {error}") + self.main_menu(turn)
        except (ShopifyReconnectRequired, ShopifyTryAgainLater, ShopifyAPIError, UnsafeCheckoutLink):
            # Never Shopify's own words here: a store needing a reconnect is the business's to fix.
            return text_reply(UNREACHABLE_TEXT) + self.main_menu(turn)

    # Browsing and searching (Step 2.3, user story 12)

    def _products(self, turn, data) -> list[dict]:
        """A page of the products for sale: the newest first, or those matching the search's words."""
        shop = services.store_for(turn.contact.account)
        words = data.get("words")
        where = {"after": data.get("after"), "before": data.get("before")}
        if words:
            found = storefront.search_products(shop, words, first=LIST_ITEMS_MAX, **where)
        else:
            found = storefront.list_products(shop, first=LIST_ITEMS_MAX, **where)

        products, page_info = found["products"], found["page_info"]
        if not products and words:
            search_again = Choice(turn.choice(SEARCH), "Search again")
            browse_all = Choice(turn.choice(BROWSE), "Browse all")
            return [
                reply_buttons(f'Nothing for sale matches "{words}".', [search_again, browse_all], way_back=MAIN_MENU)
            ]
        if not products:
            return text_reply("There's nothing for sale here yet.")

        # Back from a product returns to this very page.
        back = {"words": words, **where}
        rows = [
            Row(turn.choice(PRODUCT, product_id=item["id"], back=back), item["title"], price(item)) for item in products
        ]
        # BROWSE with the search's words pages through the search.
        previous = None
        if page_info["has_previous_page"]:
            previous = Row(turn.choice(BROWSE, words=words, before=page_info["start_cursor"]), "Previous")
        following = None
        if page_info["has_next_page"]:
            following = Row(turn.choice(BROWSE, words=words, after=page_info["end_cursor"]), "Next")
        body = f'Products matching "{words}".' if words else "Products, newest first."
        return [
            list_message(
                body, button_label="Products", section_title="Products", rows=rows, previous=previous, next=following
            )
        ]

    def _search(self, turn, data) -> list[dict]:
        turn.expect_text(SEARCH)
        return text_reply("Type what you're looking for, such as a product's name. Send *menu* to go back instead.")

    # A product (Step 2.4, user story 13)

    def _product(self, turn, data) -> list[dict]:
        """The product with its buttons, or, with several variants, a page of them to pick from."""
        shop = services.store_for(turn.contact.account)
        product = storefront.get_product(shop, data["product_id"])
        if product is None or not product["variants"]:
            return text_reply("Sorry, that product isn't for sale any more.") + self.main_menu(turn)

        variants = product["variants"]
        if len(variants) == 1:
            body = f"*{product['title']}*\n{price(product)}"
            if product["description"]:
                body += f"\n\n{product['description']}"
            back = Choice(turn.choice(BROWSE, **data["back"]), "Back")
            return [_buy_buttons(turn, product, variants[0], body, back, data["back"])]

        page = max(1, int(data.get("page", 1)))
        start = (page - 1) * LIST_ITEMS_MAX
        shown = {"product_id": product["id"], "back": data["back"]}
        rows = [
            Row(
                turn.choice(VARIANT, **shown, page=page, variant=_variant_shown(product, item)),
                item["title"],
                f"{item['currency_code']} {_amount(item['price'])}",
            )
            for item in variants[start : start + LIST_ITEMS_MAX]
        ]
        previous = Row(turn.choice(VARIANTS, **shown, page=page - 1), "Previous") if page > 1 else None
        has_next = start + LIST_ITEMS_MAX < len(variants)
        following = Row(turn.choice(VARIANTS, **shown, page=page + 1), "Next") if has_next else None
        body = f"*{product['title']}* comes in {len(variants)} options. Which one would you like?"
        return [
            list_message(
                body, button_label="Options", section_title="Options", rows=rows, previous=previous, next=following
            )
        ]

    def _variant(self, turn, data) -> list[dict]:
        """A variant picked from the list, shown from what its row stored, so Shopify isn't asked again."""
        variant = data["variant"]
        body = (
            f"*{variant['product_title']}* ({variant['title']})\n{variant['currency_code']} {_amount(variant['price'])}"
        )
        back = Choice(
            turn.choice(VARIANTS, product_id=data["product_id"], back=data["back"], page=data["page"]), "Back"
        )
        product = {"title": variant["product_title"], "image_url": variant["image_url"]}
        return [_buy_buttons(turn, product, variant, body, back, data["back"])]

    # The cart (phase 2, decision 1, user story 16)

    def _add_to_cart(self, turn, data) -> list[dict]:
        shop = services.store_for(turn.contact.account)
        customer = _store_customer(turn)
        cart = _open_cart(customer, shop)
        if cart is None:
            cart = storefront.create_cart(shop, data["variant_id"], phone=_phone(turn.contact))
        else:
            cart = storefront.add_to_cart(shop, cart["id"], data["variant_id"])
        customer.cart_id, customer.cart_shop = cart["id"], shop
        customer.save(update_fields=["cart_id", "cart_shop", "updated_at"])

        checkout = Choice(turn.choice(CHECKOUT), "Checkout")
        your_cart = Choice(turn.choice(CART), "Your cart")
        keep_shopping = Choice(turn.choice(BROWSE, **data["back"]), "Keep shopping")
        body = f"Added {data['label']} to your cart. It holds {_cart_size(cart)}."
        return [reply_buttons(body, [checkout, your_cart], way_back=keep_shopping)]

    def _buy_now(self, turn, data) -> list[dict]:
        """A one-item cart of its own, straight to checkout; the open cart is left as it is."""
        shop = services.store_for(turn.contact.account)
        cart = storefront.create_cart(shop, data["variant_id"], phone=_phone(turn.contact))
        return [_checkout_link(cart, f"{data['label']}, {data['price']}. {CHECKOUT_TEXT}")]

    def _cart(self, turn, data) -> list[dict]:
        cart = _open_cart(_store_customer(turn), services.store_for(turn.contact.account))
        if cart is None or not cart["lines"]:
            return [_empty_cart_screen(turn, "Your cart is empty.")]

        lines = [
            f"{line['quantity']} × {_line_title(line)}: {cart['currency_code']} {_amount(line['amount'])}"
            for line in cart["lines"][:CART_LINES_SHOWN]
        ]
        more = len(cart["lines"]) - CART_LINES_SHOWN
        if more > 0:
            lines.append(f"…and {more} more")
        body = "Your cart:\n" + "\n".join(lines) + f"\n\nTotal: {cart['currency_code']} {_amount(cart['total_amount'])}"
        checkout = Choice(turn.choice(CHECKOUT), "Checkout")
        empty = Choice(turn.choice(EMPTY), "Empty cart")
        return [reply_buttons(body, [checkout, empty], way_back=MAIN_MENU)]

    def _checkout(self, turn, data) -> list[dict]:
        cart = _open_cart(_store_customer(turn), services.store_for(turn.contact.account))
        if cart is None or not cart["lines"]:
            return [_empty_cart_screen(turn, "Your cart is empty.")]
        return [_checkout_link(cart, f"Your cart holds {_cart_size(cart)}. {CHECKOUT_TEXT}")]

    def _empty_cart(self, turn, data) -> list[dict]:
        # Shopify forgets an unused cart by itself within 30 days; it's only dropped here.
        customer = _store_customer(turn)
        customer.cart_id, customer.cart_shop = "", None
        customer.save(update_fields=["cart_id", "cart_shop", "updated_at"])
        return [_empty_cart_screen(turn, "Your cart is empty now.")]


class UnsafeCheckoutLink(Exception):
    """Shopify returned a checkout link that isn't https; it's never sent to a customer."""


def _buy_buttons(turn, product: dict, variant: dict, body: str, back: Choice, listing: dict) -> dict:
    """
    A product's or variant's screen: Add to cart, Buy now, and the way back. `listing` is the product
    list's page it came from, where Keep shopping returns after an add.
    """
    label = product["title"] if variant["title"] == "Default Title" else f"{product['title']} ({variant['title']})"
    item = {"variant_id": variant["id"], "label": label}
    add = Choice(turn.choice(ADD, **item, back=listing), "Add to cart")
    buy = Choice(turn.choice(BUY, **item, price=f"{variant['currency_code']} {_amount(variant['price'])}"), "Buy now")
    return reply_buttons(body, [add, buy], way_back=back, image_url=_showable_image(product.get("image_url")))


def _variant_shown(product: dict, variant: dict) -> dict:
    """What a variant's screen shows, kept with its row until it's pressed."""
    return {
        "id": variant["id"],
        "title": variant["title"],
        "price": variant["price"],
        "currency_code": variant["currency_code"],
        "product_title": product["title"],
        "image_url": product["image_url"],
    }


def _open_cart(customer: StoreCustomer, shop) -> dict | None:
    """The customer's open cart in `shop`, or None: none yet, from another store, or gone from Shopify."""
    if not customer.cart_id or customer.cart_shop_id != shop.pk:
        return None
    return storefront.get_cart(shop, customer.cart_id)


def _empty_cart_screen(turn, body: str) -> dict:
    return reply_buttons(body, [Choice(turn.choice(BROWSE), "Browse products")], way_back=MAIN_MENU)


def _checkout_link(cart: dict, body: str) -> dict:
    """The cart's own Shopify checkout, as a link button; only ever an https link."""
    if urlparse(cart["checkout_url"]).scheme != "https":
        raise UnsafeCheckoutLink()
    return link_button(body, display_text="Checkout", url=cart["checkout_url"])


def _cart_size(cart: dict) -> str:
    items = "1 item" if cart["total_quantity"] == 1 else f"{cart['total_quantity']} items"
    return f"{items}: {cart['currency_code']} {_amount(cart['total_amount'])}"


def _line_title(line: dict) -> str:
    # Shopify names a product's only variant "Default Title".
    return line["title"] if line["variant"] == "Default Title" else f"{line['title']} ({line['variant']})"


def _phone(contact) -> str | None:
    """The customer's number as Shopify's cart takes it, with its +, or None when Meta gave none."""
    return f"+{contact.wa_id}" if contact.wa_id else None


def _showable_image(url: str | None) -> str | None:
    """The picture's link if Meta can show it in a header, judged by the file name; else None."""
    if url and urlparse(url).path.lower().endswith(SHOWABLE_IMAGE_EXTENSIONS):
        return url
    return None


def price(product: dict) -> str:
    """The price, such as "USD 19.99", or a range such as "USD 19.99 – 24.50" when variants differ."""
    low, high = _amount(product["price_min"]), _amount(product["price_max"])
    if low == high:
        return f"{product['currency_code']} {low}"
    return f"{product['currency_code']} {low} – {high}"


def _amount(value: str) -> str:
    """Shopify's amount with two decimals ("24.5" reads "24.50"), or as Shopify sent it."""
    try:
        return f"{Decimal(value):.2f}"
    except InvalidOperation:
        return value


def _shop_name(turn) -> str:
    """The number's business name, as Meta verified it, or its store's domain."""
    account = turn.contact.account
    return account.verified_name or services.store_for(account).shop_domain


def _store_customer(turn) -> StoreCustomer:
    """The contact's store customer, made on their first message (D4)."""
    store_customer, _ = StoreCustomer.objects.get_or_create(
        contact=turn.contact, defaults={"tenant": turn.contact.account.tenant}
    )
    return store_customer
