"""
Tests for the names the Django admin shows for this app's models (found in the WhatsApp plan's Step 4.7 human
checks): Django makes them from the class name, so ShopifyWebhookDelivery read "Shopify webhook deliverys" and
ShopifyOAuthState "shopify o auth state". Each model names itself, as apps/payfast's models do.
https://docs.djangoproject.com/en/5.2/ref/models/options/#verbose-name

Kind of test: unit (agents.md section 2.5). Why: it reads each model's options; nothing is faked, and the
database isn't touched.
"""

import pytest

from ..models import ShopifyOAuthState, ShopifyShop, ShopifyWebhookDelivery

# Only because the root conftest.py's autouse fixtures need the database (agents.md section 2.5).
pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    "model, name, plural",
    [
        (ShopifyShop, "Shopify shop", "Shopify shops"),
        (ShopifyOAuthState, "Shopify OAuth state", "Shopify OAuth states"),
        (ShopifyWebhookDelivery, "Shopify webhook delivery", "Shopify webhook deliveries"),
    ],
)
def test_each_model_is_named_as_people_write_it(model, name, plural):
    assert model._meta.verbose_name == name
    assert model._meta.verbose_name_plural == plural
