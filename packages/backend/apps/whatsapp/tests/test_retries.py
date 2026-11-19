"""
Tests for retrying a message Meta turned away for a passing reason (WhatsApp plan Step 4.7, user story
WA.D5.SY.J1.A1, decided 2026-11-08): one rule, with a Celery worker or without, for up to an hour.

- with a worker, the send task keeps retrying, each wait longer up to MAX_RETRY_DELAY_SECONDS, until the
  message has been queued for QUEUED_MESSAGE_MAX_AGE_SECONDS (an hour); the next passing failure after that
  fails it and cancels what was queued behind it, as a permanent one does
- without a worker (CELERY_TASK_ALWAYS_EAGER, e.g. Render's free plan, which has no free cron either), the
  webhooks that already arrive run the send sweep (outbox.drain_all, the whatsapp_send_queued command's work),
  at most once every SWEEP_EVERY_SECONDS: Meta's webhook, and Shopify's order webhooks (test_order_delivery.py
  in whatsapp_shop); with a worker, the send task does the retrying and the webhooks run no sweep

Kind of test: integration (agents.md section 2.5). Why: the queue is rows in the test database, and
Meta's webhook goes through the real route with Django's test client, signed as Meta signs it; the send
backend is a fake that records what it's given, and Celery's delay is patched where queuing is checked.
"""

import hashlib
import hmac
import json
from datetime import timedelta

import pytest
from django.core.cache import cache
from django.utils import timezone

from ..client import RetryableSendError
from ..constants import MessageDirection, MessageStatus
from ..models import WhatsAppMessage
from ..services import outbox
from ..tasks import send_queued_messages
from . import payloads
from .factories import ContactFactory, InternalAccountFactory
from .fakes import FakeBackend

pytestmark = [pytest.mark.django_db, pytest.mark.story("WA.D5.SY.J1.A1")]

APP_SECRET = "our-app-secret"


def text(body):
    return {"type": "text", "text": {"body": body, "preview_url": False}}


def rows_of(contact):
    return [
        (row.payload["text"]["body"], row.status)
        for row in WhatsAppMessage.objects.filter(contact=contact, direction=MessageDirection.OUTBOUND).order_by("pk")
    ]


@pytest.fixture
def contact():
    return ContactFactory()


@pytest.fixture
def delay(mocker):
    return mocker.patch("apps.whatsapp.tasks.send_queued_messages.delay")


@pytest.fixture(autouse=True)
def no_sweep_yet():
    """Each test starts as if no sweep had run lately."""
    cache.delete(outbox.SWEEP_CACHE_KEY)
    yield
    cache.delete(outbox.SWEEP_CACHE_KEY)


def queued(contact, *bodies, ago=timedelta(0)):
    rows = outbox.queue_messages(contact, [text(body) for body in bodies])
    WhatsAppMessage.objects.filter(pk__in=[row.pk for row in rows]).update(created_at=timezone.now() - ago)
    return rows


@pytest.mark.usefixtures("celery_keeps_the_test_connection")
class TestWithAWorker:
    def test_it_keeps_retrying_past_five_tries_within_the_hour(self, contact, delay, mocker):
        # Until Step 4.7 the task gave up after 5 retries, about 2.5 minutes with a worker.
        queued(contact, "one", "two")
        busy = [RetryableSendError(131000, "Meta error 131000: something went wrong")] * 8
        backend = FakeBackend(failures=busy)
        mocker.patch("apps.whatsapp.services.outbox.send_backend", return_value=backend)

        send_queued_messages.apply(args=[contact.pk])

        assert backend.attempts == 8 + 2
        assert rows_of(contact) == [("one", MessageStatus.ACCEPTED), ("two", MessageStatus.ACCEPTED)]

    def test_after_an_hour_queued_a_passing_failure_fails_it_and_cancels_the_rest(self, contact, delay, mocker):
        queued(contact, "one", "two", "three", ago=timedelta(seconds=outbox.QUEUED_MESSAGE_MAX_AGE_SECONDS + 60))
        backend = FakeBackend(failures=[RetryableSendError(131056, "Meta error 131056: pair rate limit")] * 3)
        mocker.patch("apps.whatsapp.services.outbox.send_backend", return_value=backend)

        send_queued_messages.apply(args=[contact.pk])

        assert backend.attempts == 1
        assert rows_of(contact) == [
            ("one", MessageStatus.FAILED),
            ("two", MessageStatus.CANCELLED),
            ("three", MessageStatus.CANCELLED),
        ]
        assert WhatsAppMessage.objects.filter(contact=contact).order_by("pk").first().error_code == 131056

    def test_the_hour_is_the_same_as_the_sweeps(self):
        # One rule, with a worker or without (decided 2026-11-08).
        assert outbox.QUEUED_MESSAGE_MAX_AGE_SECONDS == 60 * 60
        assert not hasattr(outbox, "MAX_SEND_RETRIES")


class TestWithoutAWorker:
    @pytest.fixture(autouse=True)
    def eager(self, settings):
        settings.CELERY_TASK_ALWAYS_EAGER = True

    def test_the_sweep_sends_what_a_passing_failure_left_queued(self, contact, delay, mocker):
        queued(contact, "one")
        backend = FakeBackend()
        mocker.patch("apps.whatsapp.services.outbox.send_backend", return_value=backend)

        outbox.sweep_if_due()

        assert rows_of(contact) == [("one", MessageStatus.ACCEPTED)]

    def test_the_sweep_gives_up_on_a_message_queued_over_an_hour(self, contact, delay, mocker):
        queued(contact, "one", ago=timedelta(seconds=outbox.QUEUED_MESSAGE_MAX_AGE_SECONDS + 60))
        backend = FakeBackend(failures=[RetryableSendError(130429, "Meta error 130429: throughput")])
        mocker.patch("apps.whatsapp.services.outbox.send_backend", return_value=backend)

        outbox.sweep_if_due()

        assert rows_of(contact) == [("one", MessageStatus.FAILED)]

    def test_it_runs_at_most_once_every_few_minutes(self, mocker):
        drain_all = mocker.patch("apps.whatsapp.services.outbox.drain_all", return_value={})

        outbox.sweep_if_due()
        outbox.sweep_if_due()

        drain_all.assert_called_once_with()

    def test_metas_webhook_runs_the_sweep_once_it_has_stored_its_events(
        self, client, settings, mocker, django_capture_on_commit_callbacks
    ):
        settings.WHATSAPP_ENABLED = True
        settings.WHATSAPP_APP_SECRET = APP_SECRET
        mocker.patch("apps.whatsapp.views.process_inbound_message.delay")
        sweep = mocker.patch("apps.whatsapp.services.outbox.sweep_if_due")
        InternalAccountFactory(phone_number_id=payloads.PHONE_NUMBER_ID)
        raw_body = json.dumps(payloads.envelope(payloads.messages_change(payloads.text_message()))).encode("utf-8")
        signature = "sha256=" + hmac.new(APP_SECRET.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()

        with django_capture_on_commit_callbacks(execute=True):
            response = client.post(
                "/api/whatsapp/webhook/",
                data=raw_body,
                content_type="application/json",
                HTTP_X_HUB_SIGNATURE_256=signature,
            )

        assert response.status_code == 200
        sweep.assert_called_once_with()


def test_with_a_worker_the_webhooks_run_no_sweep(settings, mocker):
    settings.CELERY_TASK_ALWAYS_EAGER = False
    drain_all = mocker.patch("apps.whatsapp.services.outbox.drain_all", return_value={})

    outbox.sweep_if_due()

    drain_all.assert_not_called()
