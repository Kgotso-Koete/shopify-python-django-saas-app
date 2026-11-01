"""
Tests for browsing and searching a store in chat (WhatsApp plan Step 2.3, user stories 12 and 21).

- Browse products lists the products for sale, newest first, 7 to a page, each with its price, with
  Previous, Next and Main menu (D17); Shopify's cursors ride on the buttons' stored data
- Search asks for typed words and lists the matching products for sale, paged the same way, keeping
  the words; no match offers Search again and Browse all
- a store with nothing for sale says so
- Shopify being unreachable says so, with the main menu, never an error

Kind of test: integration (agents.md section 2.5). Why: the store, number and customer are rows in
the test database, routed through the real router and handler; Shopify's Storefront API is faked at
apps.shopify.storefront's functions.
"""

import pytest

from apps.multitenancy.constants import TenantType
from apps.multitenancy.tests.factories import TenantFactory
from apps.shopify.products import ShopifyTryAgainLater
from apps.whatsapp.constants import ConversationMode

from .chat import customer_of, selling_number, send, store

pytestmark = pytest.mark.django_db


def product(number=1, *, price_min="19.99", price_max="19.99"):
    """One product as apps.shopify.storefront returns it."""
    return {
        "id": f"gid://shopify/Product/{number}",
        "title": f"Snowboard {number}",
        "description": "A board.",
        "image_url": None,
        "price_min": price_min,
        "price_max": price_max,
        "currency_code": "USD",
    }


def page(products, *, has_next_page=False, has_previous_page=False):
    return {
        "products": products,
        "page_info": {
            "has_next_page": has_next_page,
            "has_previous_page": has_previous_page,
            "start_cursor": "cursor-start",
            "end_cursor": "cursor-end",
        },
    }


@pytest.fixture(autouse=True)
def setup(settings, mocker):
    settings.WHATSAPP_DEFAULT_CONVERSATION_MODE = ConversationMode.WHATSAPP_FORM
    mocker.patch("apps.whatsapp.tasks.send_queued_messages.delay")


@pytest.fixture
def shop():
    acme = TenantFactory(type=TenantType.ORGANIZATION, name="Acme")
    return store(acme)


@pytest.fixture
def customer(shop):
    return customer_of(selling_number(shop.tenant, shop))


@pytest.fixture
def listing(mocker):
    return mocker.patch("apps.shopify.storefront.list_products", return_value=page([product()]))


@pytest.fixture
def searching(mocker):
    return mocker.patch("apps.shopify.storefront.search_products", return_value=page([product()]))


def browse(customer):
    [menu] = send(customer, "hi")
    [screen] = send(customer, press=menu.press("Browse products"))
    return screen


class TestBrowsing:
    def test_products_for_sale_newest_first_seven_to_a_page(self, customer, shop, listing):
        listing.return_value = page([product(n) for n in range(1, 8)], has_next_page=True)

        screen = browse(customer)

        listing.assert_called_once_with(shop, first=7, after=None, before=None)
        assert screen.body == "Products, newest first."
        assert screen.titles == [*(f"Snowboard {n}" for n in range(1, 8)), "Next", "Main menu"]

    def test_each_shows_its_price_or_price_range(self, customer, listing):
        listing.return_value = page([product(1), product(2, price_min="19.99", price_max="24.5")])

        screen = browse(customer)

        assert screen.descriptions[:2] == ["USD 19.99", "USD 19.99 – 24.50"]

    def test_a_name_too_long_for_its_row_is_given_whole_with_its_price(self, customer, listing):
        # Step 2.8, finding 15: Meta cuts a row's title at 24 characters, so three products read "The
        # Collection Snowboar…". The row's description, up to 72, carries the whole name.
        liquid = {**product(1), "title": "The Collection Snowboard: Liquid"}
        oxygen = {**product(2, price_min="1025", price_max="1025"), "title": "The Collection Snowboard: Oxygen"}
        listing.return_value = page([liquid, oxygen, product(3)])

        screen = browse(customer)

        assert screen.descriptions[:3] == [
            "The Collection Snowboard: Liquid · USD 19.99",
            "The Collection Snowboard: Oxygen · USD 1025.00",
            # A name that fits its row keeps just its price.
            "USD 19.99",
        ]

    def test_next_and_previous_follow_shopifys_cursors(self, customer, shop, listing):
        listing.return_value = page([product()], has_next_page=True)
        first = browse(customer)

        listing.return_value = page([product(8)], has_previous_page=True)
        second = send(customer, press=first.press("Next"))[0]
        assert listing.call_args.kwargs == {"first": 7, "after": "cursor-end", "before": None}

        send(customer, press=second.press("Previous"))
        assert listing.call_args.kwargs == {"first": 7, "after": None, "before": "cursor-start"}

    def test_a_store_with_nothing_for_sale_says_so(self, customer, listing):
        listing.return_value = page([])

        screen = browse(customer)

        assert screen.body == "There's nothing for sale here yet."
        assert screen.titles == ["Main menu"]

    def test_shopify_being_unreachable_says_so_with_the_main_menu(self, customer, listing):
        listing.side_effect = ShopifyTryAgainLater()

        [menu] = send(customer, "hi")
        sorry, main_menu = send(customer, press=menu.press("Browse products"))

        assert sorry.body == "The shop can't be reached right now. Please try again in a few minutes."
        assert main_menu.titles[0] == "Browse products"


class TestSearching:
    def search(self, customer, words):
        [menu] = send(customer, "hi")
        [question] = send(customer, press=menu.press("Search"))
        assert question.body.startswith("Type what you're looking for")
        [screen] = send(customer, words)
        return screen

    def test_typed_words_search_the_products_for_sale(self, customer, shop, searching):
        screen = self.search(customer, "  blue   board ")

        searching.assert_called_once_with(shop, "blue board", first=7, after=None, before=None)
        assert screen.body == 'Products matching "blue board".'
        assert screen.titles == ["Snowboard 1", "Main menu"]

    def test_the_words_are_kept_while_paging(self, customer, shop, searching):
        searching.return_value = page([product()], has_next_page=True)
        first = self.search(customer, "board")

        send(customer, press=first.press("Next"))

        assert searching.call_args.args == (shop, "board")
        assert searching.call_args.kwargs == {"first": 7, "after": "cursor-end", "before": None}

    def test_no_match_offers_another_search_or_everything(self, customer, searching, listing):
        searching.return_value = page([])

        screen = self.search(customer, "kayak")

        assert screen.body == 'Nothing for sale matches "kayak".'
        assert screen.titles == ["Search again", "Browse all", "Main menu"]
        everything = send(customer, press=screen.press("Browse all"))[0]
        assert everything.body == "Products, newest first."
