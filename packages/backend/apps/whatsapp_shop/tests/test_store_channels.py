"""
Tests for apps/whatsapp_shop/services.py: which Shopify store each external communications number
sells from (WhatsApp plan Step 2.1b, decisions 4 and 5, user story 25).

- one external number sells from one store (Step 2.1, decision 1); choosing again changes it
- only the organization's own stores are offered, and only active ones holding the storefront
  scopes; another organization's store reads as "not found", as a missing one does
- internal communications numbers never sell from a store
- removing the store removes the link, never the number

Kind of test: integration (agents.md section 2.5). Why: organizations, WhatsApp numbers, Shopify
stores and the links between them are rows in the test database; nothing is faked.
"""

import pytest
from django.utils import timezone

from apps.multitenancy.constants import TenantType
from apps.multitenancy.tests.factories import TenantFactory
from apps.shopify.models import ShopifyShop
from apps.whatsapp.constants import AccountPurpose
from apps.whatsapp.models import WhatsAppAccount
from apps.whatsapp.tests.factories import ExternalAccountFactory, InternalAccountFactory

from .. import services
from ..models import StorefrontChannel
from ..services import StoreChannelError

pytestmark = pytest.mark.django_db

# What a store needs for a WhatsApp customer's cart (Step 2.1b, decision 1): the Storefront API's
# product listings and cart. unauthenticated_write_checkouts also grants reading checkouts.
STOREFRONT_SCOPES = "read_products,unauthenticated_read_product_listings,unauthenticated_write_checkouts"


@pytest.fixture
def acme():
    return TenantFactory(type=TenantType.ORGANIZATION, name="Acme")


@pytest.fixture
def number(acme):
    """Acme's external communications number, the one its store customers text."""
    return ExternalAccountFactory(tenant=acme)


def store(tenant, domain, *, scopes=STOREFRONT_SCOPES, **fields):
    return ShopifyShop.objects.create(shop_domain=domain, tenant=tenant, scopes=scopes, **fields)


class TestEligibleStores:
    def test_the_organizations_active_stores_with_the_storefront_scopes(self, acme):
        second = store(acme, "second.myshopify.com")
        first = store(acme, "first.myshopify.com")

        assert services.eligible_stores(acme) == [first, second]

    def test_stores_that_cannot_sell_on_whatsapp_are_left_out(self, acme):
        # The products page still works for these; a WhatsApp cart doesn't.
        store(acme, "read-only.myshopify.com", scopes="read_products")
        store(acme, "uninstalled.myshopify.com", uninstalled_at=timezone.now())
        store(acme, "reinstall.myshopify.com", needs_reinstall=True)
        store(TenantFactory(type=TenantType.ORGANIZATION), "someone-elses.myshopify.com")

        assert services.eligible_stores(acme) == []


class TestChoosingAStore:
    def test_choosing_links_the_number_to_the_store(self, acme, number):
        chosen = store(acme, "acme.myshopify.com")

        channel = services.choose_store(tenant=acme, account_id=str(number.pk), shop_domain="acme.myshopify.com")

        assert channel.account == number
        assert channel.shop == chosen
        assert services.store_for(number) == chosen

    def test_choosing_again_changes_the_store_and_keeps_one_link(self, acme, number):
        store(acme, "first.myshopify.com")
        second = store(acme, "second.myshopify.com")
        services.choose_store(tenant=acme, account_id=str(number.pk), shop_domain="first.myshopify.com")

        services.choose_store(tenant=acme, account_id=str(number.pk), shop_domain="second.myshopify.com")

        assert StorefrontChannel.objects.filter(account=number).count() == 1
        assert services.store_for(number) == second

    def test_a_number_with_no_store_chosen_has_none(self, number):
        assert services.store_for(number) is None

    def test_an_internal_number_never_sells_from_a_store(self, acme):
        # The team's number answers members only (Step 1.17); store customers text external numbers.
        internal = InternalAccountFactory(tenant=acme)
        store(acme, "acme.myshopify.com")

        with pytest.raises(StoreChannelError) as error:
            services.choose_store(tenant=acme, account_id=str(internal.pk), shop_domain="acme.myshopify.com")

        assert error.value.code == "not_external"
        assert not StorefrontChannel.objects.exists()

    def test_another_organizations_number_is_not_found(self, acme):
        theirs = ExternalAccountFactory(tenant=TenantFactory(type=TenantType.ORGANIZATION))
        store(acme, "acme.myshopify.com")

        with pytest.raises(StoreChannelError) as error:
            services.choose_store(tenant=acme, account_id=str(theirs.pk), shop_domain="acme.myshopify.com")

        assert error.value.code == "not_found"

    def test_another_organizations_store_reads_as_not_found(self, acme, number):
        # The same answer as a store that doesn't exist, so nobody learns which stores others have.
        store(TenantFactory(type=TenantType.ORGANIZATION), "theirs.myshopify.com")

        for domain in ("theirs.myshopify.com", "missing.myshopify.com"):
            with pytest.raises(StoreChannelError) as error:
                services.choose_store(tenant=acme, account_id=str(number.pk), shop_domain=domain)

            assert error.value.code == "store_not_found"
            assert error.value.field == "shop_domain"

    @pytest.mark.parametrize(
        "fields",
        [
            {"scopes": "read_products"},
            {"uninstalled_at": timezone.now()},
            {"needs_reinstall": True},
        ],
        ids=["without the storefront scopes", "uninstalled", "needing a reinstall"],
    )
    def test_a_store_that_cannot_sell_on_whatsapp_is_refused_with_what_to_do(self, acme, number, fields):
        store(acme, "acme.myshopify.com", **fields)

        with pytest.raises(StoreChannelError) as error:
            services.choose_store(tenant=acme, account_id=str(number.pk), shop_domain="acme.myshopify.com")

        assert error.value.code == "store_not_eligible"
        assert "Shopify page" in str(error.value)
        assert not StorefrontChannel.objects.exists()


class TestTheMode:
    """Menus or the assistant for a number's customers (WhatsApp plan phase 2, decision 2)."""

    def test_menus_until_an_admin_sets_the_assistant(self, acme, number):
        store(acme, "acme.myshopify.com")
        channel = services.choose_store(tenant=acme, account_id=str(number.pk), shop_domain="acme.myshopify.com")
        assert channel.conversation_mode == "WHATSAPP_FORM"

        services.set_mode(tenant=acme, account_id=str(number.pk), mode="AGENTIC")

        channel.refresh_from_db()
        assert channel.conversation_mode == "AGENTIC"

    def test_changing_the_store_keeps_the_mode(self, acme, number):
        store(acme, "first.myshopify.com")
        store(acme, "second.myshopify.com")
        services.choose_store(tenant=acme, account_id=str(number.pk), shop_domain="first.myshopify.com")
        services.set_mode(tenant=acme, account_id=str(number.pk), mode="AGENTIC")

        channel = services.choose_store(tenant=acme, account_id=str(number.pk), shop_domain="second.myshopify.com")

        assert channel.conversation_mode == "AGENTIC"

    def test_a_number_with_no_store_chosen_is_told_to_choose_one_first(self, acme, number):
        with pytest.raises(StoreChannelError) as error:
            services.set_mode(tenant=acme, account_id=str(number.pk), mode="AGENTIC")

        assert error.value.code == "no_store"
        assert not StorefrontChannel.objects.exists()

    def test_another_organizations_number_is_not_found(self, acme):
        theirs = ExternalAccountFactory(tenant=TenantFactory(type=TenantType.ORGANIZATION))

        with pytest.raises(StoreChannelError) as error:
            services.set_mode(tenant=acme, account_id=str(theirs.pk), mode="AGENTIC")

        assert error.value.code == "not_found"


class TestRemoving:
    def test_removing_the_store_removes_the_link_and_keeps_the_number(self, acme, number):
        chosen = store(acme, "acme.myshopify.com")
        services.choose_store(tenant=acme, account_id=str(number.pk), shop_domain="acme.myshopify.com")

        chosen.delete()

        assert WhatsAppAccount.objects.filter(pk=number.pk).exists()
        assert services.store_for(number) is None


class TestANumberServingBoth:
    """One number for the team and the customers (plan Step 2.7) sells from a store too."""

    def test_it_can_sell_from_a_store(self, acme):
        shared = InternalAccountFactory(tenant=acme, purpose=AccountPurpose.INTERNAL_AND_EXTERNAL_COMMUNICATIONS)
        store(acme, "acme.myshopify.com")

        services.choose_store(tenant=acme, account_id=str(shared.pk), shop_domain="acme.myshopify.com")

        assert services.store_for(shared).shop_domain == "acme.myshopify.com"

    def test_a_team_only_number_still_cant(self, acme):
        team_only = InternalAccountFactory(tenant=acme)
        store(acme, "acme.myshopify.com")

        with pytest.raises(StoreChannelError) as error:
            services.choose_store(tenant=acme, account_id=str(team_only.pk), shop_domain="acme.myshopify.com")

        assert error.value.code == "not_external"
