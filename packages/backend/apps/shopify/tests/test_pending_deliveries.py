"""
Tests for the sweep that handles Shopify deliveries left unhandled (WhatsApp plan Step 4.3e; section
14, open question 10), such as after a broker outage, or once the task's retries and Shopify's are
spent. One service function, deliveries.handle_pending, with two callers: a management command, for a
deployment with cron but no worker, and a Celery beat task (agents.md section 4.1).

- a delivery unhandled for longer than PENDING_AFTER is handled
- a newer one is left to the retries still under way; a handled one is left alone; one older than
  GIVE_UP_AFTER is left for a person to look at in the admin
- a failure is logged and counted, and the sweep goes on to the next delivery
- the command and the beat task run the sweep; beat schedules it when Shopify is enabled

Kind of test: integration (agents.md section 2.5). Why: the sweep runs against delivery rows in the test
database, with the topic's handler replaced by a test double. The exception is the beat-schedule
tests, which are sanity: they read settings in a fresh subprocess.
"""

import logging
from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.shopify import deliveries, tasks
from apps.shopify.models import ShopifyWebhookDelivery

from .utils import read_settings

pytestmark = [pytest.mark.django_db, pytest.mark.story("WA.D7.SY.J1.A1")]

TOPIC = "orders/paid"


class Handler:
    """A stand-in for a topic's handler, failing for the first `failures` calls."""

    def __init__(self, failures=0):
        self.failures = failures
        self.calls = 0

    def __call__(self, shop_domain, payload):
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("The handler failed.")


@pytest.fixture
def handler(mocker):
    def install(failures=0):
        stand_in = Handler(failures)
        mocker.patch.dict(deliveries.TOPIC_HANDLERS, {TOPIC: stand_in})
        return stand_in

    return install


def received(webhook_id, ago, handled=False):
    """A delivery stored `ago` before now."""
    row = ShopifyWebhookDelivery.objects.create(
        webhook_id=webhook_id, topic=TOPIC, shop_domain="sweep-shop.myshopify.com", payload={"id": 5001}
    )
    when = timezone.now() - ago
    ShopifyWebhookDelivery.objects.filter(pk=row.pk).update(created_at=when, handled_at=when if handled else None)
    return row


def handled_at(row):
    row.refresh_from_db()
    return row.handled_at


class TestTheSweep:
    def test_a_delivery_unhandled_for_too_long_is_handled(self, handler):
        stand_in = handler()
        row = received("sweep-1", deliveries.PENDING_AFTER + timedelta(minutes=1))

        counts = deliveries.handle_pending()

        assert counts == {"handled": 1, "failed": 0}
        assert stand_in.calls == 1
        assert handled_at(row) is not None

    def test_a_newer_one_is_left_to_the_retries_under_way(self, handler):
        stand_in = handler()
        row = received("sweep-2", deliveries.PENDING_AFTER - timedelta(minutes=1))

        assert deliveries.handle_pending() == {"handled": 0, "failed": 0}
        assert stand_in.calls == 0
        assert handled_at(row) is None

    def test_a_handled_one_is_left_alone(self, handler):
        stand_in = handler()
        received("sweep-3", deliveries.PENDING_AFTER + timedelta(hours=1), handled=True)

        assert deliveries.handle_pending() == {"handled": 0, "failed": 0}
        assert stand_in.calls == 0

    def test_one_older_than_give_up_after_is_left_for_the_admin(self, handler):
        stand_in = handler()
        row = received("sweep-4", deliveries.GIVE_UP_AFTER + timedelta(hours=1))

        assert deliveries.handle_pending() == {"handled": 0, "failed": 0}
        assert stand_in.calls == 0
        assert handled_at(row) is None

    def test_a_failure_is_logged_and_the_sweep_goes_on(self, handler, caplog):
        handler(failures=1)
        old = deliveries.PENDING_AFTER + timedelta(minutes=5)
        failing = received("sweep-5", old + timedelta(minutes=1))
        next_one = received("sweep-6", old)

        with caplog.at_level(logging.WARNING):
            counts = deliveries.handle_pending()

        assert counts == {"handled": 1, "failed": 1}
        assert handled_at(failing) is None
        assert handled_at(next_one) is not None
        assert any("sweep-5" in record.getMessage() for record in caplog.records)


@pytest.mark.story("WA.D7.OP.J2.A2")
class TestTellingTheOperator:
    """
    User story WA.D7.OP.J2.A2: past GIVE_UP_AFTER the sweep stops, so the operator is told once, by email, with
    each delivery's shop, topic and last error, and can handle it again from the admin once the cause is fixed.
    """

    @pytest.fixture
    def send_email(self, settings, mocker):
        settings.OPERATOR_EMAILS = ["ops@example.com"]
        return mocker.patch("common.emails.send_email")

    def test_a_failure_keeps_its_error_on_the_delivery(self, handler):
        handler(failures=1)
        row = received("tell-1", deliveries.PENDING_AFTER + timedelta(minutes=1))

        deliveries.handle_pending()

        row.refresh_from_db()
        assert row.last_error == "RuntimeError: The handler failed."

    def test_one_the_sweep_gave_up_on_is_emailed_to_the_operator_once(self, handler, send_email):
        handler()
        row = received("tell-2", deliveries.GIVE_UP_AFTER + timedelta(hours=1))
        ShopifyWebhookDelivery.objects.filter(pk=row.pk).update(last_error="RuntimeError: Shopify said no.")

        deliveries.handle_pending()
        deliveries.handle_pending()

        send_email.apply_async.assert_called_once()
        [(to, name, data, lang)] = [call.args[0] for call in send_email.apply_async.call_args_list]
        assert (to, name, lang) == (["ops@example.com"], "SHOPIFY_WEBHOOKS_UNHANDLED", "en")
        [delivery] = data["deliveries"]
        assert delivery["webhook_id"] == "tell-2"
        assert delivery["topic"] == TOPIC
        assert delivery["shop_domain"] == "sweep-shop.myshopify.com"
        assert delivery["last_error"] == "RuntimeError: Shopify said no."
        assert delivery["received_at"]
        row.refresh_from_db()
        assert row.reported_at is not None

    def test_handled_and_newer_ones_are_not_reported(self, handler, send_email):
        handler()
        received("tell-3", deliveries.GIVE_UP_AFTER + timedelta(hours=1), handled=True)
        received("tell-4", deliveries.GIVE_UP_AFTER - timedelta(hours=1))

        deliveries.handle_pending()

        send_email.apply_async.assert_not_called()

    def test_without_an_operator_email_none_is_sent_and_none_is_marked(self, handler, settings, mocker):
        settings.OPERATOR_EMAILS = []
        send_email = mocker.patch("common.emails.send_email")
        handler()
        row = received("tell-5", deliveries.GIVE_UP_AFTER + timedelta(hours=1))

        deliveries.handle_pending()

        send_email.apply_async.assert_not_called()
        row.refresh_from_db()
        assert row.reported_at is None


class TestItsCallers:
    def test_the_command_runs_the_sweep_and_reports_its_counts(self, handler):
        handler()
        received("sweep-7", deliveries.PENDING_AFTER + timedelta(minutes=1))
        out = StringIO()

        call_command("shopify_handle_pending_deliveries", stdout=out)

        assert "handled=1 failed=0" in out.getvalue()

    def test_the_beat_task_runs_the_sweep(self, handler):
        handler()
        row = received("sweep-8", deliveries.PENDING_AFTER + timedelta(minutes=1))

        assert tasks.handle_pending_deliveries() == {"handled": 1, "failed": 0}
        assert handled_at(row) is not None


class TestBeatSchedule:
    def test_the_sweep_is_scheduled_every_15_minutes_when_shopify_is_enabled(self):
        schedule = read_settings(["CELERY_BEAT_SCHEDULE"], SHOPIFY_API_KEY="key", SHOPIFY_API_SECRET="secret")[
            "CELERY_BEAT_SCHEDULE"
        ]

        assert "'shopify-handle-pending-deliveries'" in schedule
        assert "'apps.shopify.tasks.handle_pending_deliveries'" in schedule
        assert "900" in schedule  # every 15 minutes, in seconds

    def test_it_isnt_scheduled_without_shopify(self):
        schedule = read_settings(["CELERY_BEAT_SCHEDULE"], SHOPIFY_API_KEY=None, SHOPIFY_API_SECRET=None)[
            "CELERY_BEAT_SCHEDULE"
        ]

        assert "shopify" not in schedule
