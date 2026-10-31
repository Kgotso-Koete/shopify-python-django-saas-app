"""
Tests for the signals apps.shopify's privacy webhook handlers send (WhatsApp plan Step 2.6, phase 2
decision 4), so apps that keep a store's customer data delete it without apps.shopify importing them.

- customers/redact sends customer_redacted with the store and Shopify's customer (id, email, phone)
- shop/redact sends shop_redacted with the store, before the store's row is anonymized, so a
  receiver still finds what belonged to it
- a store this app doesn't know sends nothing

Kind of test: integration (agents.md section 2.5). Why: the handlers run against store rows in the
test database, with a real receiver connected for each test; nothing is faked.
"""

import pytest

from apps.shopify.models import ShopifyShop
from apps.shopify.services import handle_customers_redact, handle_shop_redact

pytestmark = pytest.mark.django_db

CUSTOMER = {"id": 191167, "email": "john@example.com", "phone": "+27000001001"}


def signals():
    # Imported here, not at the top, so a missing module fails each test instead of the whole file.
    from apps.shopify import signals as module

    return module


@pytest.fixture
def shop():
    return ShopifyShop.objects.create(shop_domain="demo.myshopify.com", scopes="read_products")


@pytest.fixture
def received():
    """What each signal's receivers got, by signal name."""
    calls = {"customer_redacted": [], "shop_redacted": []}

    def on_customer(sender, shop, customer, **kwargs):
        calls["customer_redacted"].append((shop.shop_domain, customer))

    def on_shop(sender, shop, **kwargs):
        # The domain and organization as they were, before the tombstone.
        calls["shop_redacted"].append((shop.shop_domain, shop.tenant_id))

    signals().customer_redacted.connect(on_customer)
    signals().shop_redacted.connect(on_shop)
    yield calls
    signals().customer_redacted.disconnect(on_customer)
    signals().shop_redacted.disconnect(on_shop)


def test_customers_redact_sends_the_store_and_shopifys_customer(shop, received):
    handle_customers_redact("demo.myshopify.com", {"shop_domain": "demo.myshopify.com", "customer": CUSTOMER})

    assert received["customer_redacted"] == [("demo.myshopify.com", CUSTOMER)]


def test_shop_redact_sends_the_store_before_it_is_anonymized(shop, received):
    handle_shop_redact("demo.myshopify.com", {"shop_domain": "demo.myshopify.com"})

    assert received["shop_redacted"] == [("demo.myshopify.com", shop.tenant_id)]
    shop.refresh_from_db()
    assert shop.shop_domain.startswith("redacted-")


def test_a_store_this_app_doesnt_know_sends_nothing(received):
    handle_customers_redact("unknown.myshopify.com", {"customer": CUSTOMER})
    handle_shop_redact("unknown.myshopify.com", {})

    assert received == {"customer_redacted": [], "shop_redacted": []}
