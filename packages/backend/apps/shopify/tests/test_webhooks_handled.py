"""
Tests that every Shopify webhook delivery gets handled (WhatsApp plan Step 4.3e; section 14, open
question 10). A delivery records when its handler succeeded, so Shopify's retry of a delivery whose
handler failed runs it again, instead of being answered as a duplicate and lost.

- a delivery whose handler succeeds is marked handled
- a handler that fails leaves its delivery unhandled, its work undone, and answers with an error, so
  Shopify retries
- Shopify's retry, with the same webhook id, runs the handler again and marks the delivery handled
- a repeat of a handled delivery gets 200, and its handler doesn't run again
- a topic with no handler is marked handled, so nothing tries it again
- one function, deliveries.handle, handles a delivery
- with Celery dispatch: the task handles the delivery; a repeat of an unhandled delivery is queued
  again, a handled one isn't; a failed handler is retried with a growing delay, then left for the
  sweep; a queue that's down answers with an error, so Shopify retries
- without a worker (CELERY_TASK_ALWAYS_EAGER), Celery dispatch handles inline, as sync does, so a
  failure still answers with an error and Shopify retries (agents.md section 4.1)

Kind of test: integration (agents.md section 2.5). Why: signed posts go through the real route with
Django's test client, against the test database; the topic's handler is replaced by a test double,
the Celery task's `delay` is patched, and nothing reaches Shopify.
"""

import base64
import hashlib
import hmac
import json

import logging

import pytest
from celery.exceptions import Retry
from django.conf import settings
from django.utils import timezone
from kombu.exceptions import OperationalError

from apps.shopify import deliveries, tasks
from apps.shopify.models import ShopifyShop, ShopifyWebhookDelivery
from apps.shopify.tasks import process_shopify_webhook

pytestmark = [pytest.mark.django_db, pytest.mark.story("WA.D7.SY.J1.A1")]

WEBHOOK_URL = "/api/shopify/webhooks/"
TOPIC = "orders/paid"
SHOP = "handled-shop.myshopify.com"


def post(client, webhook_id, topic=TOPIC):
    """A webhook signed as Shopify signs it."""
    body = json.dumps({"id": 5001}).encode("utf-8")
    signature = base64.b64encode(
        hmac.new(settings.SHOPIFY_API_SECRET.encode("utf-8"), body, hashlib.sha256).digest()
    ).decode("utf-8")
    return client.post(
        WEBHOOK_URL,
        data=body,
        content_type="application/json",
        HTTP_X_SHOPIFY_TOPIC=topic,
        HTTP_X_SHOPIFY_SHOP_DOMAIN=SHOP,
        HTTP_X_SHOPIFY_WEBHOOK_ID=webhook_id,
        HTTP_X_SHOPIFY_HMAC_SHA256=signature,
    )


class Handler:
    """
    A stand-in for a topic's handler. Each call writes a row, as a real handler's work would, then
    fails for the first `failures` calls.
    """

    def __init__(self, failures=0):
        self.failures = failures
        self.calls = 0

    def __call__(self, shop_domain, payload):
        self.calls += 1
        ShopifyShop.objects.create(shop_domain=f"work-{self.calls}.myshopify.com", scopes="read_orders")
        if self.calls <= self.failures:
            raise RuntimeError("The handler failed.")


@pytest.fixture(autouse=True)
def sync_dispatch(settings):
    settings.SHOPIFY_WEBHOOK_DISPATCH = "sync"


@pytest.fixture
def handler(mocker):
    def install(failures=0):
        stand_in = Handler(failures)
        mocker.patch.dict(deliveries.TOPIC_HANDLERS, {TOPIC: stand_in})
        return stand_in

    return install


def delivery(webhook_id):
    return ShopifyWebhookDelivery.objects.get(webhook_id=webhook_id)


class TestHandled:
    def test_a_delivery_whose_handler_succeeds_is_marked_handled(self, client, handler):
        stand_in = handler()
        before = timezone.now()

        response = post(client, "handled-1")

        assert response.status_code == 200
        assert stand_in.calls == 1
        assert delivery("handled-1").handled_at >= before

    def test_a_failed_handler_leaves_the_delivery_unhandled_and_answers_with_an_error(self, client, handler):
        handler(failures=1)

        response = post(client, "handled-2")

        # Any answer but 2xx makes Shopify send the same delivery again.
        assert response.status_code == 500
        assert delivery("handled-2").handled_at is None
        # The handler's work is undone with it.
        assert not ShopifyShop.objects.filter(shop_domain="work-1.myshopify.com").exists()

    def test_shopifys_retry_runs_the_handler_again_and_marks_it_handled(self, client, handler):
        stand_in = handler(failures=1)
        post(client, "handled-3")

        response = post(client, "handled-3")

        assert response.status_code == 200
        assert stand_in.calls == 2
        assert delivery("handled-3").handled_at is not None
        assert ShopifyWebhookDelivery.objects.filter(webhook_id="handled-3").count() == 1
        assert ShopifyShop.objects.filter(shop_domain="work-2.myshopify.com").exists()

    def test_a_repeat_of_a_handled_delivery_gets_200_and_the_handler_doesnt_run_again(self, client, handler):
        stand_in = handler()
        post(client, "handled-4")

        response = post(client, "handled-4")

        assert response.status_code == 200
        assert stand_in.calls == 1

    def test_a_topic_with_no_handler_is_marked_handled(self, client):
        response = post(client, "handled-5", topic="products/update")

        assert response.status_code == 200
        assert delivery("handled-5").handled_at is not None


class TestTheOneFunction:
    def test_handle_runs_the_handler_once_and_marks_the_delivery_handled(self, handler):
        stand_in = handler()
        row = ShopifyWebhookDelivery.objects.create(
            webhook_id="handled-6", topic=TOPIC, shop_domain=SHOP, payload={"id": 5001}
        )

        deliveries.handle(row)
        deliveries.handle(row)

        row.refresh_from_db()
        assert row.handled_at is not None
        assert stand_in.calls == 1


def stored(webhook_id):
    return ShopifyWebhookDelivery.objects.create(
        webhook_id=webhook_id, topic=TOPIC, shop_domain=SHOP, payload={"id": 5001}
    )


def run_task(delivery_id, retries=0):
    """Run the task as a worker would, on its `retries`-th retry."""
    process_shopify_webhook.push_request(retries=retries)
    try:
        process_shopify_webhook.run(delivery_id)
    finally:
        process_shopify_webhook.pop_request()


class TestCeleryDispatch:
    @pytest.fixture(autouse=True)
    def celery_dispatch(self, settings):
        settings.SHOPIFY_WEBHOOK_DISPATCH = "celery"
        settings.CELERY_TASK_ALWAYS_EAGER = False

    @pytest.fixture
    def queued(self, mocker):
        return mocker.patch("apps.shopify.webhooks.process_shopify_webhook.delay")

    def test_the_task_handles_the_delivery_and_marks_it_handled(self, client, handler, queued):
        stand_in = handler()
        post(client, "celery-1")
        queued.assert_called_once_with(delivery("celery-1").pk)

        run_task(delivery("celery-1").pk)

        assert stand_in.calls == 1
        assert delivery("celery-1").handled_at is not None

    def test_a_repeat_of_an_unhandled_delivery_is_queued_again(self, client, handler, queued):
        handler()
        post(client, "celery-2")

        response = post(client, "celery-2")

        assert response.status_code == 200
        assert queued.call_count == 2

    def test_a_repeat_of_a_handled_delivery_is_not_queued_again(self, client, handler, queued):
        handler()
        post(client, "celery-3")
        run_task(delivery("celery-3").pk)

        post(client, "celery-3")

        assert queued.call_count == 1

    def test_a_failed_handler_is_retried_with_a_growing_delay(self, handler, mocker):
        handler(failures=3)
        row = stored("celery-4")
        retry = mocker.patch.object(process_shopify_webhook, "retry", side_effect=Retry())

        with pytest.raises(Retry):
            run_task(row.pk)
        with pytest.raises(Retry):
            run_task(row.pk, retries=2)

        delays = [call.kwargs["countdown"] for call in retry.call_args_list]
        assert delays == [tasks.RETRY_DELAY_SECONDS, tasks.RETRY_DELAY_SECONDS * 4]
        row.refresh_from_db()
        assert row.handled_at is None

    def test_after_the_last_retry_the_delivery_is_left_for_the_sweep(self, handler, mocker, caplog):
        handler(failures=1)
        row = stored("celery-5")
        retry = mocker.patch.object(process_shopify_webhook, "retry")

        with caplog.at_level(logging.WARNING):
            run_task(row.pk, retries=tasks.MAX_RETRIES)

        retry.assert_not_called()
        row.refresh_from_db()
        assert row.handled_at is None
        assert any("celery-5" in record.getMessage() for record in caplog.records)

    def test_a_queue_that_is_down_answers_with_an_error_so_shopify_retries(self, client, handler, queued):
        handler()
        queued.side_effect = OperationalError("The broker is down.")

        response = post(client, "celery-6")

        assert response.status_code == 500
        assert delivery("celery-6").handled_at is None


class TestWithoutAWorker:
    """CELERY_TASK_ALWAYS_EAGER: no worker, so no Celery retries (agents.md section 4.1)."""

    @pytest.fixture(autouse=True)
    def eager_celery_dispatch(self, settings):
        settings.SHOPIFY_WEBHOOK_DISPATCH = "celery"
        settings.CELERY_TASK_ALWAYS_EAGER = True

    def test_celery_dispatch_handles_inline_and_a_failure_answers_with_an_error(self, client, handler, mocker):
        stand_in = handler(failures=1)
        queued = mocker.patch("apps.shopify.webhooks.process_shopify_webhook.delay")

        failed = post(client, "eager-1")
        retried = post(client, "eager-1")

        queued.assert_not_called()
        assert (failed.status_code, retried.status_code) == (500, 200)
        assert stand_in.calls == 2
        assert delivery("eager-1").handled_at is not None
