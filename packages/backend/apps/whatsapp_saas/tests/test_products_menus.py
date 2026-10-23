"""
Tests for the Shopify product menus in apps/whatsapp_saas/menus.py (plan Step 1.12b, user story 7):
an organization member browses and searches their organization's stores from WhatsApp, on its
internal communications number (Step 1.17).

- Products is on the main menu for a member with shopify.view, as the website's products page is
- one store goes straight to it; several are picked from a list; none says how to connect one
- a store offers Browse and Search; lists hold 7, newest first, with Previous and Next by Shopify's
  cursors and Main menu (D17)
- a product's detail shows its picture, price and status, and Back returns to the same page
- Search asks for the words, typed (turn.expect_text, chosen on 2026-10-20), and keeps them while
  paging
- a store that must be reconnected, or a busy Shopify, gets a clear message and the main menu

Kind of test: integration (agents.md section 2.5). Why: messages go through the real router and
handler against the test database; fetch_products, which calls Shopify's Admin API, is mocked, and
so is the send task's Celery delay.
"""

import pytest

from apps.multitenancy.constants import TenantType, TenantUserRole
from apps.multitenancy.models import OrganizationRolePermission, invalidate_user_permissions_cache
from apps.multitenancy.tests.factories import TenantFactory
from apps.shopify.models import ShopifyShop
from apps.shopify.products import ShopifyReconnectRequired

from .chat import main_menu, send, team_member

pytestmark = pytest.mark.django_db


def product(number, **overrides):
    """One product as fetch_products returns it."""
    return {
        "id": f"gid://shopify/Product/{number}",
        "title": f"Product {number:02d}",
        "handle": f"product-{number:02d}",
        "status": "ACTIVE",
        "image_url": f"https://cdn.shopify.com/product-{number:02d}.jpg?v=1",
        "image_alt": None,
        "price_min": "19.99",
        "price_max": "24.50",
        "currency_code": "ZAR",
        **overrides,
    }


def page_of(products, *, has_next=False, has_previous=False):
    return {
        "products": products,
        "page_info": {
            "has_next_page": has_next,
            "has_previous_page": has_previous,
            "start_cursor": "cursor-start",
            "end_cursor": "cursor-end",
        },
    }


@pytest.fixture(autouse=True)
def setup(settings, mocker):
    settings.WHATSAPP_DEFAULT_CONVERSATION_MODE = "WHATSAPP_FORM"
    mocker.patch("apps.whatsapp.tasks.send_queued_messages.delay")


@pytest.fixture
def fetch(mocker):
    return mocker.patch(
        "apps.whatsapp_saas.use_cases.fetch_products",
        return_value=page_of([product(number) for number in range(1, 8)], has_next=True),
    )


@pytest.fixture
def acme():
    return TenantFactory(type=TenantType.ORGANIZATION, name="Acme")


@pytest.fixture
def contact(acme):
    """A member of Acme, texting Acme's internal number."""
    return team_member(acme, role=TenantUserRole.MEMBER)


@pytest.fixture
def user(contact):
    return contact.identity.user


@pytest.fixture
def store(acme):
    return ShopifyShop.objects.create(shop_domain="acme.myshopify.com", tenant=acme)


def open_store(contact, acme):
    """From the main menu to the one store's screen."""
    menu = main_menu(contact)
    [screen] = send(contact, press=menu.press("Products"))
    return screen


def browse(contact, acme):
    [page] = send(contact, press=open_store(contact, acme).press("Browse"))
    return page


class TestTheWayIn:
    def test_products_is_on_the_main_menu_for_a_member(self, contact, acme, store):
        assert "Products" in main_menu(contact).titles

    def test_not_without_shopify_view(self, contact, user, acme, store):
        OrganizationRolePermission.objects.filter(role__tenant=acme, permission__code="shopify.view").delete()
        invalidate_user_permissions_cache(user.id, acme.id)

        assert "Products" not in main_menu(contact).titles

    def test_without_a_store_it_says_how_to_connect_one(self, contact, acme):
        menu = main_menu(contact)

        screens = send(contact, press=menu.press("Products"))

        assert "No Shopify store" in screens[0].body
        assert "Shopify page" in screens[0].body

    def test_one_store_goes_straight_to_it(self, contact, acme, store):
        screen = open_store(contact, acme)

        assert "acme.myshopify.com" in screen.body
        assert screen.titles == ["Browse", "Search", "Main menu"]

    def test_several_stores_are_picked_from_a_list(self, contact, acme, store):
        ShopifyShop.objects.create(shop_domain="acme-outlet.myshopify.com", tenant=acme)
        menu = main_menu(contact)

        [stores] = send(contact, press=menu.press("Products"))
        [screen] = send(contact, press=stores.press("acme-outlet"))

        # A row title holds 24 characters, which most full domains overflow, so it's the store's
        # handle, with the full domain beneath.
        assert stores.titles == ["acme-outlet", "acme", "Main menu"]
        assert stores.descriptions[:2] == ["acme-outlet.myshopify.com", "acme.myshopify.com"]
        assert "acme-outlet.myshopify.com" in screen.body


class TestBrowsing:
    def test_a_page_holds_seven_newest_first_with_price_and_status(self, contact, acme, store, fetch):
        page = browse(contact, acme)

        assert fetch.call_args.kwargs["newest_first"] is True
        assert page.titles == [f"Product {number:02d}" for number in range(1, 8)] + ["Next", "Main menu"]
        assert page.descriptions[0] == "ZAR 19.99 – 24.50 · Active"
        assert "newest first" in page.body

    def test_next_and_previous_follow_shopifys_cursors(self, contact, acme, store, fetch):
        first = browse(contact, acme)
        fetch.return_value = page_of([product(8)], has_previous=True)

        [second] = send(contact, press=first.press("Next"))
        assert fetch.call_args.kwargs["after"] == "cursor-end"
        assert second.titles == ["Product 08", "Previous", "Main menu"]

        send(contact, press=second.press("Previous"))
        assert fetch.call_args.kwargs["before"] == "cursor-start"

    def test_a_products_detail_shows_its_picture_price_and_status(self, contact, acme, store, fetch):
        page = browse(contact, acme)

        [detail] = send(contact, press=page.press("Product 01"))

        assert "Product 01" in detail.body
        assert "ZAR 19.99 – 24.50" in detail.body
        assert "Active" in detail.body
        assert detail.image_url == "https://cdn.shopify.com/product-01.jpg?v=1"
        assert detail.titles == ["Back"]

    def test_one_price_is_shown_once(self, contact, acme, store, fetch):
        fetch.return_value = page_of([product(1, price_max="19.99")])

        assert browse(contact, acme).descriptions[0] == "ZAR 19.99 · Active"

    @pytest.mark.parametrize(
        "image_url",
        [
            pytest.param(None, id="shopify_has_no_image_yet"),
            pytest.param("https://cdn.shopify.com/product-01.webp", id="a_format_meta_cant_show"),
        ],
    )
    def test_a_picture_meta_cant_show_is_left_out(self, contact, acme, store, fetch, image_url):
        # Meta's image headers take JPEG or PNG only; anything else would fail the whole message.
        fetch.return_value = page_of([product(1, image_url=image_url)])
        page = browse(contact, acme)

        [detail] = send(contact, press=page.press("Product 01"))

        assert detail.image_url is None
        assert "Product 01" in detail.body

    def test_back_returns_to_the_same_page(self, contact, acme, store, fetch):
        first = browse(contact, acme)
        [second] = send(contact, press=first.press("Next"))
        [detail] = send(contact, press=second.press("Product 01"))
        fetch.reset_mock()

        send(contact, press=detail.press("Back"))

        assert fetch.call_args.kwargs["after"] == "cursor-end"

    def test_a_store_that_must_be_reconnected_says_so_and_shows_the_main_menu(self, contact, acme, store, fetch):
        fetch.side_effect = ShopifyReconnectRequired()
        screen = open_store(contact, acme)

        screens = send(contact, press=screen.press("Browse"))

        assert "reconnected" in screens[0].body
        assert "Products" in screens[-1].titles


class TestSearching:
    def search(self, contact, acme, words):
        [prompt] = send(contact, press=open_store(contact, acme).press("Search"))
        assert "Type what you're looking for" in prompt.body
        return send(contact, words)

    def test_the_typed_words_search_the_store(self, contact, acme, store, fetch):
        [results] = self.search(contact, acme, "  blue   shirt ")

        assert fetch.call_args.kwargs["query"] == "blue shirt"
        assert '"blue shirt"' in results.body

    def test_the_search_is_kept_while_paging(self, contact, acme, store, fetch):
        [results] = self.search(contact, acme, "shirt")

        send(contact, press=results.press("Next"))

        assert fetch.call_args.kwargs["query"] == "shirt"
        assert fetch.call_args.kwargs["after"] == "cursor-end"

    def test_no_results_offer_another_search_or_the_whole_list(self, contact, acme, store, fetch):
        fetch.return_value = page_of([])

        [results] = self.search(contact, acme, "unicorn")

        assert "unicorn" in results.body
        assert results.titles == ["Search again", "Browse all", "Main menu"]

    def test_menu_instead_of_words_goes_back_without_searching(self, contact, acme, store, fetch):
        [menu] = self.search(contact, acme, "menu")

        assert "Products" in menu.titles
        fetch.assert_not_called()
