"""
Tests for the cart's checkout code (WhatsApp plan phase 4, Step 4.3a, decisions 2, 4 and 21): the label
that lets an order find the chat it came from.

- a new cart, from Add to cart or Buy now, carries a new code as its `_whatsapp_checkout` attribute,
  `wachk_` and 22 random characters, kept with the cart's id, the store customer and the store
- adding to the same cart makes no new code; a cart Shopify refused keeps none
- the View cart link carries the cart's code too (decision 21); a cart made before codes existed gets a
  link without one
- codes are unique, and go with their store customer (Shopify's customers/redact deletes the contact,
  Step 2.6)
- an order delivery keeps the code: this app asks apps.shopify to keep its `_whatsapp_checkout` note
  attribute, which apps.shopify otherwise drops (Step 4.3b)

Kind of test: integration (agents.md section 2.5). Why: the store, number, customer and their carts'
codes are rows in the test database, routed through the real router and handler; Shopify's Storefront
API is faked at apps.shopify.storefront's functions.
"""

import re

import pytest
from django.db import IntegrityError

from apps.multitenancy.constants import TenantType
from apps.multitenancy.tests.factories import TenantFactory
from apps.shopify.storefront import ShopifyCartError, ShopifySoldOut
from apps.whatsapp.constants import ConversationMode

from ..models import StoreCustomer
from .chat import customer_of, selling_number, send, store
from .test_product_and_cart import ONE_VARIANT, cart, open_product, product

pytestmark = pytest.mark.django_db

ATTRIBUTE = "_whatsapp_checkout"
# `wachk_` and 22 characters: secrets.token_urlsafe(16) gives 22, from letters, digits, - and _.
CODE = re.compile(r"wachk_[A-Za-z0-9_-]{22}")
VIEW_CART = "https://acme.myshopify.com/cart/11:1?storefront=true"


def checkouts():
    # Imported here, not at the top, so a missing model fails each test instead of the whole file.
    from ..models import StoreCheckout

    return StoreCheckout.objects


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


def press(customer, title):
    """Opens the product from the main menu's list and presses one of its buttons."""
    return send(customer, press=open_product(customer).press(title))


def code_sent(shopify, call=-1):
    """The code a cart was created with: its `_whatsapp_checkout` attribute."""
    return shopify.create_cart.call_args_list[call].kwargs["attributes"][ATTRIBUTE]


def your_cart(customer):
    """The messages "Your cart" sends: the View cart link, then the cart's screen."""
    [menu] = send(customer, "hi")
    return send(customer, press=menu.press("Your cart"))


@pytest.mark.story("WA.D5.SC.J1.A1")
class TestANewCart:
    def test_add_to_cart_creates_it_with_a_new_code_kept_with_the_cart(self, customer, shop, shopify):
        press(customer, "Add to cart")

        code = code_sent(shopify)
        assert CODE.fullmatch(code)
        [checkout] = checkouts().all()
        assert checkout.code == code
        assert checkout.cart_id == "gid://shopify/Cart/abc"
        assert checkout.shop == shop
        assert checkout.store_customer == StoreCustomer.objects.get(contact=customer)

    def test_buy_now_creates_its_own_cart_with_its_own_code(self, customer, shopify):
        press(customer, "Add to cart")
        shopify.create_cart.return_value = cart(cart_id="gid://shopify/Cart/buy")

        press(customer, "Buy now")

        first, second = code_sent(shopify, 0), code_sent(shopify, 1)
        assert first != second
        assert CODE.fullmatch(second)
        assert dict(checkouts().values_list("cart_id", "code")) == {
            "gid://shopify/Cart/abc": first,
            "gid://shopify/Cart/buy": second,
        }

    def test_adding_to_the_same_cart_makes_no_new_code(self, customer, shopify):
        press(customer, "Add to cart")
        shopify.get_cart.return_value = cart()

        press(customer, "Add to cart")

        shopify.add_to_cart.assert_called_once()
        assert checkouts().count() == 1

    def test_a_cart_shopify_refused_keeps_no_code(self, customer, shopify):
        shopify.create_cart.side_effect = ShopifyCartError("The product 'Snowboard' is already sold out.")
        press(customer, "Add to cart")
        shopify.create_cart.side_effect = ShopifySoldOut()
        press(customer, "Buy now")

        assert not checkouts().exists()


@pytest.mark.story("WA.D5.SC.J1.A1")
class TestTheViewCartLink:
    """Decision 21: the code reaches the order from the website's cart too (Experiment 4.3, O4)."""

    def test_your_cart_links_with_the_carts_code(self, customer, shopify):
        press(customer, "Add to cart")
        shopify.get_cart.return_value = cart()

        page, _ = your_cart(customer)

        assert page.link["url"] == f"{VIEW_CART}&attributes[{ATTRIBUTE}]={code_sent(shopify)}"

    def test_checkout_links_with_the_carts_code(self, customer, shopify):
        press(customer, "Add to cart")
        shopify.get_cart.return_value = cart()
        _, screen = your_cart(customer)

        page, _ = send(customer, press=screen.press("Checkout"))

        assert page.link["url"] == f"{VIEW_CART}&attributes[{ATTRIBUTE}]={code_sent(shopify)}"

    def test_a_cart_made_before_codes_existed_links_without_one(self, customer, shop, shopify):
        # A cart from before Step 4.3a has no code; Shopify forgets it within 30 days of its creation.
        StoreCustomer.objects.create(
            contact=customer, tenant=shop.tenant, cart_id="gid://shopify/Cart/abc", cart_shop=shop
        )
        shopify.get_cart.return_value = cart()

        page, _ = your_cart(customer)

        assert page.link["url"] == VIEW_CART


@pytest.mark.story("WA.D5.SC.J1.A1")
class TestTheCodes:
    def test_a_code_is_unique(self, customer, shop):
        store_customer = StoreCustomer.objects.create(contact=customer, tenant=shop.tenant)
        checkouts().create(code="wachk_same", store_customer=store_customer, shop=shop, cart_id="one")

        with pytest.raises(IntegrityError):
            checkouts().create(code="wachk_same", store_customer=store_customer, shop=shop, cart_id="two")

    def test_codes_go_with_their_store_customer(self, customer, shopify):
        # Shopify's customers/redact deletes the contact, and its store customer with it (Step 2.6).
        press(customer, "Add to cart")

        customer.delete()

        assert not checkouts().exists()


@pytest.mark.story("WA.D5.SC.J1.A2")
class TestAnOrderKeepsTheCode:
    @pytest.mark.parametrize("topic", ["orders/create", "orders/paid"])
    def test_an_order_delivery_keeps_the_checkout_attribute(self, topic):
        # Imported here, not at the top, so a missing module fails this test instead of the whole file.
        from apps.shopify import payloads

        order = {
            "id": 1,
            "name": "#1001",
            "note_attributes": [{"name": ATTRIBUTE, "value": "wachk_abc"}, {"name": "gift_message", "value": "Hi"}],
        }

        kept = payloads.trim(topic, order)

        assert kept["note_attributes"] == [{"name": ATTRIBUTE, "value": "wachk_abc"}]
