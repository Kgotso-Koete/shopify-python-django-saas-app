"""
Tests for deleting store customers' data when Shopify asks (WhatsApp plan Step 2.6, phase 2 decision
4, user story 14): apps.whatsapp_shop receives apps.shopify's customer_redacted and shop_redacted.

- customers/redact deletes the store customer whose WhatsApp number is Shopify's customer's phone,
  on the store's numbers: their contact, messages, conversation and store customer
- other customers, the same phone on another organization's number, and the team's contacts stay
- a customer Shopify sends without a phone matches nobody (a known limit: some contacts have no number)
- shop/redact deletes every store customer of the store's numbers and the numbers' links to it; the
  numbers themselves stay

Kind of test: integration (agents.md section 2.5). Why: apps.shopify's real redact handlers run
against rows in the test database, reaching this app through its connected receivers; nothing is
faked.
"""

import pytest

from apps.multitenancy.constants import TenantType
from apps.multitenancy.tests.factories import TenantFactory
from apps.shopify.services import handle_customers_redact, handle_shop_redact
from apps.whatsapp.models import WhatsAppAccount, WhatsAppContact, WhatsAppConversation, WhatsAppMessage
from apps.whatsapp.tests.factories import ContactFactory, InternalAccountFactory, MessageFactory

from ..models import StoreCustomer, StorefrontChannel
from .chat import selling_number, store

pytestmark = pytest.mark.django_db


@pytest.fixture
def shop():
    return store(TenantFactory(type=TenantType.ORGANIZATION, name="Acme"))


@pytest.fixture
def number(shop):
    return selling_number(shop.tenant, shop)


def store_customer(account, wa_id):
    """Someone who has texted the number, with a message and a conversation."""
    contact = ContactFactory(account=account, wa_id=wa_id)
    StoreCustomer.objects.create(contact=contact, tenant=account.tenant)
    MessageFactory(contact=contact)
    WhatsAppConversation.objects.create(contact=contact)
    return contact


def redact_customer(shop, phone):
    customer = {"id": 191167, "email": "john@example.com", "phone": phone}
    handle_customers_redact(shop.shop_domain, {"shop_domain": shop.shop_domain, "customer": customer})


class TestCustomersRedact:
    def test_the_customer_with_that_phone_is_deleted_with_everything_they_sent(self, shop, number):
        gone = store_customer(number, "27000001001")
        stays = store_customer(number, "27000001002")

        redact_customer(shop, "+27000001001")

        assert list(WhatsAppContact.objects.all()) == [stays]
        assert not WhatsAppMessage.objects.filter(contact_id=gone.pk).exists()
        assert not WhatsAppConversation.objects.filter(contact_id=gone.pk).exists()
        assert list(StoreCustomer.objects.values_list("contact", flat=True)) == [stays.pk]

    def test_any_way_shopify_writes_the_phone_matches(self, shop, number):
        store_customer(number, "27000001001")

        redact_customer(shop, "+27 00 000-1001")

        assert not WhatsAppContact.objects.exists()

    def test_other_organizations_and_the_team_keep_theirs(self, shop, number):
        theirs = selling_number(TenantFactory(type=TenantType.ORGANIZATION), store(shop.tenant, "theirs.myshopify.com"))
        other_shop_customer = store_customer(theirs, "27000001001")
        team_member = ContactFactory(account=InternalAccountFactory(tenant=shop.tenant), wa_id="27000001001")

        redact_customer(shop, "+27000001001")

        assert set(WhatsAppContact.objects.all()) == {other_shop_customer, team_member}

    def test_without_a_phone_nobody_matches(self, shop, number):
        store_customer(number, "27000001001")
        handle_customers_redact(shop.shop_domain, {"customer": {"id": 1, "email": "john@example.com", "phone": None}})

        assert WhatsAppContact.objects.count() == 1


class TestShopRedact:
    def test_every_store_customer_and_link_goes_and_the_numbers_stay(self, shop, number):
        store_customer(number, "27000001001")
        store_customer(number, "27000001002")
        other = selling_number(shop.tenant, store(shop.tenant, "other.myshopify.com"))
        kept = store_customer(other, "27000001003")

        handle_shop_redact(shop.shop_domain, {"shop_domain": shop.shop_domain})

        assert list(WhatsAppContact.objects.all()) == [kept]
        assert not StorefrontChannel.objects.filter(account=number).exists()
        assert WhatsAppAccount.objects.filter(pk=number.pk).exists()
