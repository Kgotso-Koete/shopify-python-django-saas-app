"""
Tests for apps/whatsapp_shop/menus.py's handler, before any product is shown: who an external
number answers, the store customer it keeps, the mode and the main menu (WhatsApp plan Step 2.2,
phase 2 decision 2, user stories 14, 21 and 25).

- a number with no store chosen, or whose store can't sell on WhatsApp any more, sends no reply
- anyone texting a selling number becomes a store customer of the number's organization, once
- the main menu welcomes them to the store, by its own name in Shopify (Step 2.8, finding 12), or the
  number's business name when Shopify can't be reached, and offers Browse products, Search and Your
  cart, with Main menu as the way back (D17)
- help speaks to a customer, never of the team's modes or unlinking
- the number's own setting decides the mode, menus by default

Kind of test: integration (agents.md section 2.5). Why: organizations, stores, numbers, store links
and messages are rows in the test database, routed through the real router and the handler this app
registers; only the send task's Celery delay and the store's name from Shopify are faked.
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.multitenancy.constants import TenantType
from apps.multitenancy.tests.factories import TenantFactory
from apps.shopify.client import ShopifyAPIError
from apps.shopify.products import ShopifyTryAgainLater
from apps.whatsapp.constants import ConversationMode
from apps.whatsapp.models import WhatsAppMessage
from apps.whatsapp.tests.factories import ExternalAccountFactory

from ..models import StoreCustomer
from .chat import customer_of, selling_number, send, store

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def setup(settings, mocker):
    settings.WHATSAPP_DEFAULT_CONVERSATION_MODE = ConversationMode.WHATSAPP_FORM
    mocker.patch("apps.whatsapp.tasks.send_queued_messages.delay")


@pytest.fixture
def acme():
    return TenantFactory(type=TenantType.ORGANIZATION, name="Acme")


@pytest.fixture
def shop(acme):
    return store(acme)


@pytest.fixture
def number(acme, shop):
    return selling_number(acme, shop)


class TestWhoIsAnswered:
    def test_a_number_with_no_store_chosen_sends_no_reply(self, acme):
        # User story 25: its customers get no reply until a store is chosen.
        customer = customer_of(ExternalAccountFactory(tenant=acme))

        assert send(customer, "hi") == []
        assert not StoreCustomer.objects.exists()

    @pytest.mark.parametrize(
        "problem",
        [{"uninstalled_at": timezone.now()}, {"needs_reinstall": True}, {"scopes": "read_products"}],
        ids=["uninstalled", "needing a reinstall", "without the storefront scopes"],
    )
    def test_a_store_that_cant_sell_any_more_sends_no_reply(self, acme, problem):
        number = selling_number(acme, store(acme, **problem))

        assert send(customer_of(number), "hi") == []

    def test_anyone_texting_becomes_a_store_customer_of_the_organization_once(self, acme, number):
        customer = customer_of(number)

        send(customer, "hi")
        send(customer, "hi again")

        [store_customer] = StoreCustomer.objects.all()
        assert store_customer.contact == customer
        assert store_customer.tenant == acme
        assert store_customer.cart_id == ""


LOGO = "https://cdn.shopify.com/s/files/acme-square.png"


def welcome(name):
    return (
        f"Hi, welcome to {name}. Shop with us right here on WhatsApp: browse, search, and check out when "
        "you're ready."
    )


class TestTheMainMenu:
    def test_it_welcomes_to_the_stores_own_name_and_offers_the_store(self, number, shop, the_stores_details):
        # Step 2.8, finding 12: the store's name in Shopify, not the number's WhatsApp business name.
        [menu] = send(customer_of(number), "hi")

        # The number's own store; get_shop keeps the details an hour, so Shopify is asked once.
        the_stores_details.assert_called_with(shop)
        assert menu.body == welcome("Acme Snow Co")
        assert menu.titles == ["Browse products", "Search", "Your cart", "Main menu"]

    def test_with_shopify_unreachable_it_names_the_numbers_business(self, number, the_stores_details):
        # A name is no reason to fail the menu: the number's business name, as Meta verified it.
        the_stores_details.side_effect = ShopifyTryAgainLater()

        [menu] = send(customer_of(number), "hi")

        assert menu.body == welcome("Acme Outdoor")

    def test_with_neither_name_it_names_the_stores_domain(self, number, the_stores_details):
        the_stores_details.side_effect = ShopifyAPIError("down")
        number.verified_name = ""
        number.save()

        [menu] = send(customer_of(number), "hi")

        assert menu.body == welcome("acme.myshopify.com")

    # Step 2.8, finding 13: the store's logo when a customer starts a conversation.

    def test_a_customer_starting_gets_the_stores_logo_before_the_menu(self, number, the_stores_details):
        the_stores_details.return_value = {"name": "Acme Snow Co", "logo_url": LOGO}

        logo, menu = send(customer_of(number), "hi")

        assert logo.image_url == LOGO
        assert logo.body == "Acme Snow Co"
        assert menu.body == welcome("Acme Snow Co")

    def test_the_logo_isnt_repeated_while_the_conversation_goes_on(self, number, the_stores_details):
        the_stores_details.return_value = {"name": "Acme Snow Co", "logo_url": LOGO}
        customer = customer_of(number)
        send(customer, "hi")

        [menu] = send(customer, "menu")

        assert menu.body == welcome("Acme Snow Co")

    def test_after_a_day_of_quiet_the_logo_comes_again(self, number, the_stores_details):
        the_stores_details.return_value = {"name": "Acme Snow Co", "logo_url": LOGO}
        customer = customer_of(number)
        send(customer, "hi")
        WhatsAppMessage.objects.filter(contact=customer).update(created_at=timezone.now() - timedelta(hours=25))

        logo, _ = send(customer, "hi again")

        assert logo.image_url == LOGO

    def test_a_store_without_a_logo_sends_only_the_menu(self, number):
        [menu] = send(customer_of(number), "hi")

        assert menu.body == welcome("Acme Snow Co")

    def test_a_customer_starting_with_the_assistant_gets_the_logo_too(self, number, the_stores_details, mocker):
        from apps.whatsapp.tests.agent_fakes import FakeProvider, says

        the_stores_details.return_value = {"name": "Acme Snow Co", "logo_url": LOGO}
        number.storefront_channel.conversation_mode = ConversationMode.AGENTIC
        number.storefront_channel.save()
        mocker.patch("apps.whatsapp.agent.service.get_provider", return_value=FakeProvider(says("Hi! Welcome.")))

        logo, reply = send(customer_of(number), "hi")

        assert logo.image_url == LOGO
        assert reply.body == "Hi! Welcome."

    def test_typed_text_gets_the_main_menu(self, number):
        customer = customer_of(number)

        [menu] = send(customer, "do you have snowboards?")

        assert menu.titles[0] == "Browse products"

    def test_menu_works_from_anywhere(self, number):
        customer = customer_of(number)
        send(customer, "hi")

        [menu] = send(customer, "menu")

        assert menu.titles[0] == "Browse products"


class TestHelp:
    def test_it_speaks_to_a_customer(self, number):
        [help_screen] = send(customer_of(number), "help")

        assert "*menu*" in help_screen.body
        assert "mode" not in help_screen.body
        assert "unlink" not in help_screen.body


class TestTheMode:
    def test_menus_by_default(self, number):
        assert number.storefront_channel.conversation_mode == ConversationMode.WHATSAPP_FORM

    def test_the_numbers_setting_is_the_customers_mode(self, number, mocker):
        number.storefront_channel.conversation_mode = ConversationMode.AGENTIC
        number.storefront_channel.save()
        assistant = mocker.patch("apps.whatsapp_shop.menus.StoreHandler.on_free_text", return_value=[])

        send(customer_of(number), "anything blue?")

        assistant.assert_called_once()
        assert assistant.call_args.args[-1] == "anything blue?"


class TestANumberServingBoth:
    """One number for the team and the customers (plan Step 2.7): anyone not linked on it is a customer."""

    def test_a_stranger_gets_the_store(self, acme, shop):
        from apps.whatsapp.tests.factories import ContactFactory, InternalAccountFactory

        from ..models import StorefrontChannel

        shared = InternalAccountFactory(
            tenant=acme, purpose="INTERNAL_AND_EXTERNAL_COMMUNICATIONS", verified_name="Acme Outdoor"
        )
        StorefrontChannel.objects.create(account=shared, shop=shop)

        [menu] = send(ContactFactory(account=shared), "hi")

        assert menu.body == welcome("Acme Snow Co")
