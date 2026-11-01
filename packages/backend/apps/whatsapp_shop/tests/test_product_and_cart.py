"""
Tests for a product's screen and the cart in chat (WhatsApp plan Step 2.4, phase 2 decision 1, user
stories 13, 16 and 21).

- a product shows its picture, title, price and description; with one variant, Add to cart, Buy now
  and Back to the page it was listed on; with several, the variants for sale to pick from first
- Add to cart keeps one open cart per store customer, in the number's store, and says what it holds
- Buy now sends a checkout link for a one-item cart, leaving the open cart alone
- Your cart lists its lines and total, with Checkout and Empty cart; Checkout sends its link
- a cart Shopify no longer has, or one from the number's previous store, is started afresh
- Shopify refusing a line says why; a product no longer for sale says so

Kind of test: integration (agents.md section 2.5). Why: the store, number, customer and cart id are
rows in the test database, routed through the real router and handler; Shopify's Storefront API is
faked at apps.shopify.storefront's functions.
"""

import pytest

from apps.multitenancy.constants import TenantType
from apps.multitenancy.tests.factories import TenantFactory
from apps.shopify.storefront import ShopifyCartError, ShopifySoldOut
from apps.whatsapp.constants import ConversationMode

from ..models import StoreCustomer, StorefrontChannel
from .chat import customer_of, selling_number, send, store

pytestmark = pytest.mark.django_db

CHECKOUT_URL = "https://acme.myshopify.com/cart/c/abc?key=secret"


def product(variants, *, image_url="https://cdn.shopify.com/s/files/board.jpg?v=1"):
    """One product as apps.shopify.storefront.get_product returns it."""
    return {
        "id": "gid://shopify/Product/1",
        "title": "Snowboard",
        "description": "Fast and light.",
        "image_url": image_url,
        "price_min": "19.99",
        "price_max": "24.5",
        "currency_code": "USD",
        "variants": variants,
    }


def variant(number, title, price="19.99"):
    return {"id": f"gid://shopify/ProductVariant/{number}", "title": title, "price": price, "currency_code": "USD"}


ONE_VARIANT = [variant(11, "Default Title")]


def cart(lines=None, *, cart_id="gid://shopify/Cart/abc", checkout_url=CHECKOUT_URL, removed=None):
    lines = (
        lines
        if lines is not None
        else [
            {
                "title": "Snowboard",
                "variant": "Default Title",
                "variant_id": "gid://shopify/ProductVariant/11",
                "quantity": 1,
                "amount": "19.99",
            }
        ]
    )
    return {
        "id": cart_id,
        "checkout_url": checkout_url,
        "total_quantity": sum(line["quantity"] for line in lines),
        "total_amount": "19.99",
        "currency_code": "USD",
        "lines": lines,
        # The lines Shopify had set to 0, taken out by the change that returned this cart.
        "removed": removed or [],
    }


@pytest.fixture(autouse=True)
def setup(settings, mocker):
    settings.WHATSAPP_DEFAULT_CONVERSATION_MODE = ConversationMode.WHATSAPP_FORM
    mocker.patch("apps.whatsapp.tasks.send_queued_messages.delay")


@pytest.fixture
def shop():
    return store(TenantFactory(type=TenantType.ORGANIZATION, name="Acme"))


@pytest.fixture
def number(shop):
    return selling_number(shop.tenant, shop)


@pytest.fixture
def customer(number):
    return customer_of(number)


@pytest.fixture
def shopify(mocker):
    """apps.shopify.storefront's functions, faked; each test sets what they return."""
    fake = mocker.Mock()
    listed = {
        "products": [product(ONE_VARIANT)],
        "page_info": {"has_next_page": False, "has_previous_page": False, "start_cursor": "s", "end_cursor": "e"},
    }
    for name, value in {
        "list_products": listed,
        "get_product": product(ONE_VARIANT),
        "create_cart": cart(),
        "add_to_cart": cart(),
        "get_cart": None,
    }.items():
        setattr(fake, name, mocker.patch(f"apps.shopify.storefront.{name}", return_value=value))
    return fake


def open_product(customer):
    [menu] = send(customer, "hi")
    [listing] = send(customer, press=menu.press("Browse products"))
    [screen] = send(customer, press=listing.press("Snowboard"))
    return screen


def store_customer(customer):
    return StoreCustomer.objects.get(contact=customer)


class TestAProduct:
    def test_one_variant_shows_the_product_with_its_three_buttons(self, customer, shop, shopify):
        screen = open_product(customer)

        shopify.get_product.assert_called_once_with(shop, "gid://shopify/Product/1")
        assert screen.body == "*Snowboard*\nUSD 19.99 – 24.50\n\nFast and light."
        assert screen.image_url == "https://cdn.shopify.com/s/files/board.jpg?v=1"
        assert screen.titles == ["Add to cart", "Buy now", "Back"]

    def test_back_returns_to_the_page_it_was_listed_on(self, customer, shopify):
        screen = open_product(customer)

        [listing] = send(customer, press=screen.press("Back"))

        assert listing.titles[0] == "Snowboard"
        assert shopify.list_products.call_count == 2

    def test_a_picture_meta_cant_show_is_left_out(self, customer, shopify):
        shopify.get_product.return_value = product(ONE_VARIANT, image_url="https://cdn.shopify.com/board.webp")

        assert open_product(customer).image_url is None

    def test_several_variants_are_picked_first(self, customer, shopify):
        shopify.get_product.return_value = product([variant(11, "Small"), variant(12, "Large", "24.5")])

        screen = open_product(customer)

        assert screen.body == "*Snowboard* comes in 2 options. Which one would you like?"
        assert screen.titles == ["Small", "Large", "Main menu"]
        assert screen.descriptions[:2] == ["USD 19.99", "USD 24.50"]

        [chosen] = send(customer, press=screen.press("Large"))
        assert chosen.body == "*Snowboard* (Large)\nUSD 24.50"
        assert chosen.titles == ["Add to cart", "Buy now", "Back"]

    def test_one_no_longer_for_sale_says_so(self, customer, shopify):
        shopify.get_product.return_value = product([])

        [menu] = send(customer, "hi")
        [listing] = send(customer, press=menu.press("Browse products"))
        sorry, main_menu = send(customer, press=listing.press("Snowboard"))

        assert sorry.body == "Sorry, that product isn't for sale any more."
        assert main_menu.titles[0] == "Browse products"


class TestAddToCart:
    def test_the_first_add_makes_the_customers_cart_with_their_number(self, customer, shop, shopify):
        screen = open_product(customer)

        [added] = send(customer, press=screen.press("Add to cart"))

        shopify.create_cart.assert_called_once_with(shop, "gid://shopify/ProductVariant/11", phone="+27000001001")
        assert added.body == "Added Snowboard to your cart. It holds 1 item: USD 19.99."
        assert added.titles == ["Checkout", "Your cart", "Keep shopping"]
        assert store_customer(customer).cart_id == "gid://shopify/Cart/abc"
        assert store_customer(customer).cart_shop == shop

    def test_the_next_add_goes_into_the_same_cart(self, customer, shop, shopify):
        screen = open_product(customer)
        send(customer, press=screen.press("Add to cart"))
        shopify.get_cart.return_value = cart()

        send(customer, press=open_product(customer).press("Add to cart"))

        # had: how many the cart held before, so Shopify's reply shows whether one more went in.
        shopify.add_to_cart.assert_called_once_with(
            shop, "gid://shopify/Cart/abc", "gid://shopify/ProductVariant/11", had=1
        )
        assert shopify.create_cart.call_count == 1

    def test_a_cart_shopify_no_longer_has_is_started_afresh(self, customer, shopify):
        screen = open_product(customer)
        send(customer, press=screen.press("Add to cart"))
        # Expired, or checked out: Shopify deletes a cart once its order is placed.
        shopify.get_cart.return_value = None

        send(customer, press=open_product(customer).press("Add to cart"))

        assert shopify.create_cart.call_count == 2
        shopify.add_to_cart.assert_not_called()

    def test_a_cart_from_the_numbers_previous_store_is_started_afresh(self, customer, number, shop, shopify):
        screen = open_product(customer)
        send(customer, press=screen.press("Add to cart"))
        shopify.get_cart.return_value = cart()
        StorefrontChannel.objects.filter(account=number).update(shop=store(shop.tenant, "other.myshopify.com"))

        send(customer, press=open_product(customer).press("Add to cart"))

        assert shopify.create_cart.call_count == 2
        assert store_customer(customer).cart_shop.shop_domain == "other.myshopify.com"

    def test_a_customer_without_a_number_gets_a_cart_without_one(self, customer, shop, shopify):
        # Meta leaves out the number for some username users (plan section 6.1).
        customer.wa_id = ""
        customer.save()

        send(customer, press=open_product(customer).press("Add to cart"))

        shopify.create_cart.assert_called_once_with(shop, "gid://shopify/ProductVariant/11", phone=None)

    def test_shopify_refusing_says_why(self, customer, shopify):
        shopify.create_cart.side_effect = ShopifyCartError("The product 'Snowboard' is already sold out.")

        sorry, main_menu = send(customer, press=open_product(customer).press("Add to cart"))

        assert sorry.body == "Sorry, that couldn't go in your cart: The product 'Snowboard' is already sold out."
        assert main_menu.titles[0] == "Browse products"
        assert store_customer(customer).cart_id == ""


class TestASoldOutProduct:
    """
    Finding 7 of Step 2.8: after one product sold out, every later add said "Sorry, that couldn't go in
    your cart: The product 'The 3p Fulfilled Snowboard' is already sold out", naming the wrong product,
    though the add had worked.
    """

    def test_an_add_names_the_product_that_sold_out(self, customer, shopify):
        shopify.create_cart.side_effect = ShopifySoldOut()

        sorry, main_menu = send(customer, press=open_product(customer).press("Add to cart"))

        assert sorry.body == "Sorry, Snowboard is sold out, so it couldn't go in your cart."
        assert main_menu.titles[0] == "Browse products"
        assert store_customer(customer).cart_id == ""

    def test_buy_now_names_the_product_that_sold_out(self, customer, shopify):
        shopify.create_cart.side_effect = ShopifySoldOut()

        sorry, _ = send(customer, press=open_product(customer).press("Buy now"))

        assert sorry.body == "Sorry, Snowboard is sold out."

    def test_an_add_that_worked_says_so_and_names_what_sold_out_once(self, customer, shopify):
        send(customer, press=open_product(customer).press("Add to cart"))
        shopify.get_cart.return_value = cart()
        shopify.add_to_cart.return_value = cart(
            removed=[{"title": "The 3p Fulfilled Snowboard", "variant": "Default Title"}]
        )

        [added] = send(customer, press=open_product(customer).press("Add to cart"))

        assert added.body == (
            "Added Snowboard to your cart. It holds 1 item: USD 19.99.\n\n"
            "Sold out, so taken out of your cart: The 3p Fulfilled Snowboard."
        )
        assert added.titles == ["Checkout", "Your cart", "Keep shopping"]


class TestBuyNow:
    def test_it_sends_a_checkout_link_for_that_one_item(self, customer, shop, shopify):
        screen = open_product(customer)

        [link] = send(customer, press=screen.press("Buy now"))

        shopify.create_cart.assert_called_once_with(shop, "gid://shopify/ProductVariant/11", phone="+27000001001")
        assert link.body == "Snowboard, USD 19.99. Tap Checkout to pay in the shop's secure Shopify checkout."
        assert link.link == {"display_text": "Checkout", "url": CHECKOUT_URL}
        # The open cart is left alone: Buy now makes its own.
        assert store_customer(customer).cart_id == ""

    def test_a_link_that_isnt_https_is_never_sent(self, customer, shopify):
        shopify.create_cart.return_value = cart(checkout_url="http://acme.myshopify.com/cart/c/abc")

        sorry, _ = send(customer, press=open_product(customer).press("Buy now"))

        assert sorry.body == "The shop can't be reached right now. Please try again in a few minutes."


class TestYourCart:
    def open_cart(self, customer):
        [menu] = send(customer, "hi")
        return send(customer, press=menu.press("Your cart"))[0]

    def test_an_empty_cart_offers_the_products(self, customer, shopify):
        screen = self.open_cart(customer)

        assert screen.body == "Your cart is empty."
        assert screen.titles == ["Browse products", "Main menu"]

    def test_it_lists_the_lines_and_total_with_checkout_and_empty_cart(self, customer, shopify):
        send(customer, press=open_product(customer).press("Add to cart"))
        shopify.get_cart.return_value = cart(
            [
                {"title": "Snowboard", "variant": "Large", "quantity": 2, "amount": "49.00"},
                {"title": "Wax", "variant": "Default Title", "quantity": 1, "amount": "5.00"},
            ]
        )

        screen = self.open_cart(customer)

        assert screen.body == "Your cart:\n2 × Snowboard (Large): USD 49.00\n1 × Wax: USD 5.00\n\nTotal: USD 19.99"
        assert screen.titles == ["Checkout", "Empty cart", "Main menu"]

    def test_checkout_sends_the_carts_link(self, customer, shopify):
        send(customer, press=open_product(customer).press("Add to cart"))
        shopify.get_cart.return_value = cart()
        screen = self.open_cart(customer)

        page, link = send(customer, press=screen.press("Checkout"))

        # Step 2.8, finding 10: the shop's own cart page first, then Checkout, nearest the thumb. A
        # link-button message carries one link, so they're two messages.
        assert page.body == "Review your cart on Acme Snow Co's website."
        assert page.link == {"display_text": "View cart", "url": "https://acme.myshopify.com/cart/11:1?storefront=true"}
        assert link.link == {"display_text": "Checkout", "url": CHECKOUT_URL}
        # Step 2.8, finding 11: the store's own name in Shopify, faked in conftest.py.
        assert link.body == (
            "Your cart from Acme Snow Co holds 1 item: USD 19.99. "
            "Tap Checkout to pay in the shop's secure Shopify checkout."
        )

    def test_empty_cart_forgets_it(self, customer, shopify):
        send(customer, press=open_product(customer).press("Add to cart"))
        shopify.get_cart.return_value = cart()
        screen = self.open_cart(customer)

        [emptied] = send(customer, press=screen.press("Empty cart"))

        assert emptied.body == "Your cart is empty now."
        assert emptied.titles == ["Browse products", "Main menu"]
        assert store_customer(customer).cart_id == ""
        assert store_customer(customer).cart_shop is None
