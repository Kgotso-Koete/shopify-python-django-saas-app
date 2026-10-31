"""
Tests for the whatsapp_shop_seed_demo command (plan Step 2.1b), which the human checks run after
whatsapp_seed_demo and shopify_seed_demo.

Kind of test: integration (agents.md section 2.5). Why: the three commands run against the test
database; nothing is faked.
"""

import pytest
from django.core.management import CommandError, call_command

from apps.multitenancy.constants import TenantType, TenantUserRole
from apps.multitenancy.tests.factories import TenantFactory, TenantMembershipFactory
from apps.users.tests.factories import UserFactory
from apps.whatsapp.models import WhatsAppAccount

from .. import services

pytestmark = pytest.mark.django_db

STOREFRONT_SCOPES = ["read_products", "unauthenticated_read_product_listings", "unauthenticated_write_checkouts"]


@pytest.fixture
def owner(settings):
    # The storefront scopes are opt-in (the default is read_products alone), and shopify_seed_demo gives
    # the demo store the scopes SHOPIFY_SCOPES lists, so a deployment selling on WhatsApp lists them.
    settings.SHOPIFY_SCOPES = STOREFRONT_SCOPES
    user = UserFactory()
    TenantMembershipFactory(
        user=user, tenant=TenantFactory(type=TenantType.ORGANIZATION, name="Acme"), role=TenantUserRole.OWNER
    )
    return user


def seed(owner, *commands):
    for command in commands:
        call_command(command, email=owner.email, organization="Acme")


def test_two_demo_numbers_sell_from_the_demo_store_and_one_has_none(owner):
    seed(owner, "whatsapp_seed_demo", "shopify_seed_demo", "whatsapp_shop_seed_demo")

    stores = {
        account.phone_number_id: services.store_for(account)
        for account in WhatsAppAccount.objects.filter(
            phone_number_id__in=["100000000000801", "100000000000802", "100000000000803"]
        )
    }
    assert stores["100000000000801"] is None
    assert stores["100000000000802"].shop_domain == "linked-demo.myshopify.com"
    assert stores["100000000000803"].shop_domain == "linked-demo.myshopify.com"


def test_it_can_run_again(owner):
    seed(owner, "whatsapp_seed_demo", "shopify_seed_demo", "whatsapp_shop_seed_demo", "whatsapp_shop_seed_demo")


def test_it_says_which_seed_to_run_first(owner):
    with pytest.raises(CommandError, match="whatsapp_seed_demo"):
        seed(owner, "whatsapp_shop_seed_demo")

    with pytest.raises(CommandError, match="shopify_seed_demo"):
        seed(owner, "whatsapp_seed_demo", "whatsapp_shop_seed_demo")
