"""
Tests for the Shopify webhook deliveries' Django admin (WhatsApp plan Step 4.3e): the operator sees
when each delivery was handled, can list the ones still unhandled, and can't change when one was
handled, since the sweep and Shopify's retries rely on it.

Kind of test: integration (agents.md section 2.5). Why: requests go through the Django admin pages with
Django's test client, against the test database; nothing is faked.
"""

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.shopify import deliveries
from apps.shopify.models import ShopifyWebhookDelivery

pytestmark = [pytest.mark.django_db, pytest.mark.story("WA.D7.SY.J1.A1")]


@pytest.fixture(autouse=True)
def plain_static_files(settings):
    # Admin pages render {% static %}; plain storage serves files straight from the apps, as in
    # apps/invoicing/tests/test_admin.py.
    settings.STORAGES = {
        **settings.STORAGES,
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }


@pytest.fixture
def operator_client(client, user_factory):
    # In this codebase User.is_staff is is_superuser, so only superusers can use the Django admin.
    client.force_login(user_factory(is_superuser=True))
    return client


def received(webhook_id, handled):
    return ShopifyWebhookDelivery.objects.create(
        webhook_id=webhook_id,
        topic="orders/paid",
        shop_domain="admin-shop.myshopify.com",
        payload={"id": 5001},
        handled_at=timezone.now() if handled else None,
    )


def changelist(operator_client, **query):
    return operator_client.get(reverse("admin:shopify_shopifywebhookdelivery_changelist"), query).content.decode()


def test_the_list_shows_when_each_delivery_was_handled(operator_client):
    received("admin-handled", handled=True)
    received("admin-unhandled", handled=False)

    page = changelist(operator_client)

    assert "column-handled_at" in page
    assert "admin-handled" in page and "admin-unhandled" in page


def test_the_operator_can_list_the_unhandled_ones_only(operator_client):
    received("admin-handled", handled=True)
    received("admin-unhandled", handled=False)

    page = changelist(operator_client, handled="no")

    assert "admin-unhandled" in page
    assert "admin-handled" not in page


def test_when_a_delivery_was_handled_cant_be_changed(operator_client):
    delivery = received("admin-unhandled", handled=False)

    page = operator_client.get(reverse("admin:shopify_shopifywebhookdelivery_change", args=[delivery.pk]))

    assert page.status_code == 200
    assert 'name="handled_at' not in page.content.decode()


def handle_again(operator_client, *rows):
    return operator_client.post(
        reverse("admin:shopify_shopifywebhookdelivery_changelist"),
        {"action": "handle_again", "_selected_action": [row.pk for row in rows]},
        follow=True,
    ).content.decode()


@pytest.mark.story("WA.D7.OP.J2.A2")
def test_handle_again_handles_the_selected_deliveries(operator_client, mocker):
    # User story WA.D7.OP.J2.A2: once the cause is fixed, the operator handles a delivery the sweep gave up on.
    mocker.patch.dict(deliveries.TOPIC_HANDLERS, {"orders/paid": lambda shop_domain, payload: None})
    delivery = received("admin-again", handled=False)

    page = handle_again(operator_client, delivery)

    delivery.refresh_from_db()
    assert delivery.handled_at is not None
    assert "1 handled, 0 failed." in page


@pytest.mark.story("WA.D7.OP.J2.A2")
def test_handle_again_reports_one_that_still_fails(operator_client, mocker):
    def fails(shop_domain, payload):
        raise RuntimeError("Still broken.")

    mocker.patch.dict(deliveries.TOPIC_HANDLERS, {"orders/paid": fails})
    delivery = received("admin-still-failing", handled=False)

    page = handle_again(operator_client, delivery)

    delivery.refresh_from_db()
    assert delivery.handled_at is None
    assert delivery.last_error == "RuntimeError: Still broken."
    assert "0 handled, 1 failed." in page
