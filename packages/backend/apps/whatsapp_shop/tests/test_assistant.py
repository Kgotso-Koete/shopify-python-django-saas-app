"""
Tests for the store assistant (WhatsApp plan Step 2.5, phase 2 decisions 2 and 3, user stories 12,
13 and 21): on a number set to the assistant, a customer's words go to it, with this app's tools and
instructions.

- the model is told which shop it serves, by the store's own name in Shopify, and gets exactly four
  tools: finding products, showing a list of products, showing a product and showing the cart; none
  changes the cart
- its instructions welcome customers to the store, never mention a product it hasn't found, and show
  products as a list the customer taps, never as text (Step 2.8, findings 4, 6 and 12)
- finding products reads the store's products for sale, by words or newest first
- showing a product or the cart ends the turn on that screen, so Add to cart and Buy now are the
  customer's own presses
- when the assistant can't answer, the customer is told in a store's words and gets the main menu

Kind of test: integration (agents.md section 2.5). Why: messages go through the real router,
handler and tools against the test database; the model is a fake that replays scripted replies,
Shopify's Storefront API is faked at apps.shopify.storefront's functions, and the send task's
Celery delay is patched.
"""

import json

import pytest

from apps.multitenancy.constants import TenantType
from apps.multitenancy.tests.factories import TenantFactory
from apps.whatsapp.agent.provider import ProviderError
from apps.whatsapp.constants import ConversationMode
from apps.whatsapp.tests.agent_fakes import FakeProvider, calls, says

from ..models import StoreCustomer
from ..tools import TOOLS
from .chat import customer_of, selling_number, send, store

pytestmark = pytest.mark.django_db


def product(number=1):
    return {
        "id": f"gid://shopify/Product/{number}",
        "title": f"Snowboard {number}",
        "description": "A board.",
        "image_url": None,
        "price_min": "19.99",
        "price_max": "19.99",
        "currency_code": "USD",
    }


def page(products, *, has_next_page=False):
    info = {"has_next_page": has_next_page, "has_previous_page": False, "start_cursor": "s", "end_cursor": "e"}
    return {"products": products, "page_info": info}


@pytest.fixture(autouse=True)
def setup(settings, mocker):
    settings.WHATSAPP_DEFAULT_CONVERSATION_MODE = ConversationMode.WHATSAPP_FORM
    mocker.patch("apps.whatsapp.tasks.send_queued_messages.delay")


@pytest.fixture
def shop():
    return store(TenantFactory(type=TenantType.ORGANIZATION, name="Acme"))


@pytest.fixture
def customer(shop):
    number = selling_number(shop.tenant, shop, conversation_mode=ConversationMode.AGENTIC)
    return customer_of(number)


@pytest.fixture
def shopify(mocker):
    fake = mocker.Mock()
    one = {
        **product(),
        "variants": [
            {
                "id": "gid://shopify/ProductVariant/11",
                "title": "Default Title",
                "price": "19.99",
                "currency_code": "USD",
            }
        ],
    }
    for name, value in {
        "list_products": page([product(1), product(2)], has_next_page=True),
        "search_products": page([product(1)]),
        "get_product": one,
        "get_cart": None,
        "create_cart": {
            "id": "gid://shopify/Cart/abc",
            "checkout_url": "https://acme.myshopify.com/c",
            "total_quantity": 1,
            "total_amount": "19.99",
            "currency_code": "USD",
            "lines": [],
            "removed": [],
        },
    }.items():
        setattr(fake, name, mocker.patch(f"apps.shopify.storefront.{name}", return_value=value))
    return fake


def with_model(mocker, provider):
    mocker.patch("apps.whatsapp.agent.service.get_provider", return_value=provider)
    return provider


def tool_output(provider, request=1):
    """The output the model got back for its call, in the request after it."""
    [output] = [item for item in provider.requests[request]["items"] if item.get("type") == "function_call_output"]
    return json.loads(output["output"])


class TestWhatTheModelGets:
    def test_the_stores_name_and_four_tools_none_changing_the_cart(self, customer, mocker):
        provider = with_model(mocker, FakeProvider(says("Hello! What are you looking for?")))

        [reply] = send(customer, "hi there")

        assert reply.body == "Hello! What are you looking for?"
        # The store's own name in Shopify (Step 2.8, finding 12), faked in conftest.py.
        assert "Acme Snow Co" in provider.requests[0]["instructions"]
        names = [tool["name"] for tool in provider.requests[0]["tools"]]
        assert names == ["find_products", "show_products", "show_product", "show_cart"]
        assert [tool["name"] for tool in TOOLS.schemas()] == names

    def test_the_instructions_welcome_to_the_store_and_forbid_made_up_examples(self, customer, mocker):
        # Step 2.8, finding 4: a snowboard shop's greeting suggested an "investment guide".
        provider = with_model(mocker, FakeProvider(says("Hi!")))

        send(customer, "hi")

        instructions = provider.requests[0]["instructions"]
        assert "welcome them to Acme Snow Co" in instructions
        assert "not even as an example" in instructions

    def test_the_instructions_say_to_show_products_as_a_list_never_as_text(self, customer, mocker):
        # Step 2.8, finding 6: products listed as text, with "If you tap on one, I can open it".
        provider = with_model(mocker, FakeProvider(says("Hi!")))

        send(customer, "hi")

        assert "Never list products as text" in provider.requests[0]["instructions"]

    def test_the_instructions_say_to_show_the_cart_for_anything_about_it(self, customer, mocker):
        # Step 2.8, finding 19: asked to clear the cart, and for its link, it said it couldn't.
        provider = with_model(mocker, FakeProvider(says("Hi!")))

        send(customer, "hi")

        instructions = provider.requests[0]["instructions"]
        assert "For anything about the cart" in instructions
        assert "call show_cart" in instructions

    def test_the_customer_is_a_store_customer_from_their_first_words(self, customer, mocker):
        with_model(mocker, FakeProvider(says("Hello!")))

        send(customer, "hi there")

        assert StoreCustomer.objects.filter(contact=customer).exists()


class TestFindingProducts:
    def test_words_search_the_stores_products_for_sale(self, customer, shop, shopify, mocker):
        provider = with_model(
            mocker, FakeProvider(calls("find_products", '{"words": "board", "after": null}'), says("I found one."))
        )

        send(customer, "any boards?")

        shopify.search_products.assert_called_once_with(shop, "board", first=7, after=None, before=None)
        assert tool_output(provider) == {
            "success": True,
            "products": [
                {
                    "id": "gid://shopify/Product/1",
                    "title": "Snowboard 1",
                    "price": "USD 19.99",
                    "description": "A board.",
                }
            ],
            "next_page": None,
        }

    def test_no_words_lists_the_newest_with_the_next_pages_cursor(self, customer, shop, shopify, mocker):
        provider = with_model(
            mocker, FakeProvider(calls("find_products", '{"words": null, "after": null}'), says("Here they are."))
        )

        send(customer, "what's new?")

        shopify.list_products.assert_called_once_with(shop, first=7, after=None, before=None)
        assert tool_output(provider)["next_page"] == "e"


class TestShowing:
    def test_a_product_ends_the_turn_on_its_screen_and_the_customer_taps(self, customer, shop, shopify, mocker):
        provider = with_model(mocker, FakeProvider(calls("show_product", '{"product_id": "gid://shopify/Product/1"}')))

        [screen] = send(customer, "show me snowboard 1")

        assert screen.titles == ["Add to cart", "Buy now", "Back"]
        assert len(provider.requests) == 1
        # Only the customer's own press puts it in the cart.
        shopify.create_cart.assert_not_called()
        send(customer, press=screen.press("Add to cart"))
        shopify.create_cart.assert_called_once()

    def test_several_products_end_the_turn_on_a_list_the_customer_taps(self, customer, shop, shopify, mocker):
        # Step 2.8, finding 6: the menus' own product list, whose rows open each product's screen.
        provider = with_model(mocker, FakeProvider(calls("show_products", '{"words": "board"}')))

        [listing] = send(customer, "show me your boards")

        shopify.search_products.assert_called_once_with(shop, "board", first=7, after=None, before=None)
        assert listing.titles[0] == "Snowboard 1"
        assert len(provider.requests) == 1
        [screen] = send(customer, press=listing.press("Snowboard 1"))
        assert screen.titles == ["Add to cart", "Buy now", "Back"]

    def test_with_no_words_the_list_is_the_newest(self, customer, shop, shopify, mocker):
        with_model(mocker, FakeProvider(calls("show_products", '{"words": null}')))

        [listing] = send(customer, "what's new?")

        shopify.list_products.assert_called_once_with(shop, first=7, after=None, before=None)
        assert [title for title in listing.titles[:2]] == ["Snowboard 1", "Snowboard 2"]

    def test_the_cart_ends_the_turn_on_its_screen(self, customer, mocker, shopify):
        with_model(mocker, FakeProvider(calls("show_cart", "{}")))

        [screen] = send(customer, "what's in my cart?")

        assert screen.body == "Your cart is empty."

    def test_the_shop_being_unreachable_is_told_to_the_model(self, customer, shopify, mocker):
        from apps.shopify.products import ShopifyTryAgainLater

        shopify.search_products.side_effect = ShopifyTryAgainLater()
        provider = with_model(
            mocker, FakeProvider(calls("find_products", '{"words": "board", "after": null}'), says("Sorry."))
        )

        send(customer, "boards?")

        assert tool_output(provider) == {"success": False, "error": "The shop can't be reached right now."}


class TestWhenItCantAnswer:
    def test_the_customer_is_told_in_a_stores_words_with_the_main_menu(self, customer, mocker):
        with_model(mocker, FakeProvider(error=ProviderError("timeout")))

        sorry, menu = send(customer, "hi")

        assert sorry.body == "Sorry, the assistant isn't available right now. Send *menu* to browse the shop instead."
        assert "mode" not in sorry.body
        assert menu.titles[0] == "Browse products"

    def test_without_an_openai_key_the_same(self, customer, mocker):
        mocker.patch("apps.whatsapp.agent.service.get_provider", return_value=None)

        sorry, _ = send(customer, "hi")

        assert sorry.body.startswith("Sorry, the assistant isn't available right now.")
