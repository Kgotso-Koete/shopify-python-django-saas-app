"""
Tests for apps/whatsapp/services/outbox.py and the send_queued_messages task: the ordered send
queue (plan Step 1.4c, decision D21).

Every reply is first stored as an outbound WhatsAppMessage with status `queued`; that table is the
queue. One drain at a time per contact sends the queued rows strictly in the order they were
queued, each only after Meta accepted the one before it.
- A passing failure (a timeout, Meta's throughput or same-user pacing limits) is retried with
  backoff, and the messages behind it wait.
- A permanent failure marks the message `failed` and cancels the ones behind it.
- In strict mode (WHATSAPP_SEND_WAIT_FOR_SENT_STATUS) the next message also waits for Meta's `sent`
  status on the previous one.

Meta's error codes, and which ones to retry:
https://developers.facebook.com/documentation/business-messaging/whatsapp/support/error-codes
Meta's message statuses, reported by webhook:
https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/reference/messages/status.md

Kind of test: integration (agents.md section 2.5). Why: the queue is rows in the test database, and
the locking tests hold the real send lock from a second database connection; the send backend is a
fake that records what it's given.
"""

from datetime import datetime, timedelta, timezone

import pytest

from ..client import LogSendBackend, PermanentSendError, RetryableSendError, TokenRejectedError, WindowClosedError
from ..constants import MessageDirection, MessageKind, MessageStatus
from ..models import WhatsAppMessage
from ..normalize import DeliveryStatus
from ..services import outbox
from ..services.inbound import store_events
from ..tasks import send_queued_messages
from .factories import ContactFactory, MessageFactory
from .fakes import FakeBackend, another_sender_holds_the_send_lock

pytestmark = pytest.mark.django_db

TEXT = {"type": "text", "text": {"body": "Your item was created.", "preview_url": False}}
BUTTONS = {"type": "interactive", "interactive": {"type": "button", "body": {"text": "Delete it?"}}}


def text(body):
    """A plain text message, as builders.py makes them, with a body that names it in a test."""
    return {"type": "text", "text": {"body": body, "preview_url": False}}


@pytest.fixture
def contact():
    return ContactFactory()


@pytest.fixture
def delay(mocker):
    """The send task's delay: queueing would otherwise try to reach the Celery broker."""
    return mocker.patch("apps.whatsapp.tasks.send_queued_messages.delay")


@pytest.fixture
def strict_mode(settings):
    settings.WHATSAPP_SEND_WAIT_FOR_SENT_STATUS = True


def queued(contact, *bodies):
    """Queue one text message per body for `contact`, the way a handler queues its reply."""
    return outbox.queue_messages(contact, [text(body) for body in bodies])


def rows_of(contact):
    """The contact's outbound rows, oldest first, as (body, status) pairs."""
    return [
        (row.payload["text"]["body"], row.status)
        for row in WhatsAppMessage.objects.filter(contact=contact, direction=MessageDirection.OUTBOUND).order_by("pk")
    ]


def bodies(messages):
    return [message["text"]["body"] for message in messages]


class TestQueueing:
    def test_queued_messages_are_stored_as_outbound_rows_in_order(self, contact, delay):
        outbox.queue_messages(contact, [TEXT, BUTTONS])

        rows = list(WhatsAppMessage.objects.filter(contact=contact).order_by("pk"))
        assert [row.direction for row in rows] == [MessageDirection.OUTBOUND, MessageDirection.OUTBOUND]
        assert [row.status for row in rows] == [MessageStatus.QUEUED, MessageStatus.QUEUED]
        # The whole message is kept, so a retry sends exactly what the handler built.
        assert [row.payload for row in rows] == [TEXT, BUTTONS]
        # The kind comes from the message's own type.
        assert [row.kind for row in rows] == [MessageKind.TEXT, MessageKind.INTERACTIVE]
        # Meta gives the id only when it accepts the message.
        assert [row.wamid for row in rows] == ["", ""]

    def test_a_picture_is_stored_as_an_image(self, contact, delay):
        # A store's logo at its welcome (WhatsApp plan Step 2.8, finding 13).
        picture = {"type": "image", "image": {"link": "https://cdn.shopify.com/logo.png", "caption": "Acme"}}

        [row] = outbox.queue_messages(contact, [picture])

        assert row.kind == MessageKind.IMAGE
        assert row.payload == picture

    def test_queueing_schedules_one_send_for_the_contact_after_commit(
        self, contact, delay, django_capture_on_commit_callbacks
    ):
        with django_capture_on_commit_callbacks(execute=True):
            queued(contact, "one", "two")
            # Not before the rows are committed: the worker would find nothing to send.
            delay.assert_not_called()

        delay.assert_called_once_with(contact.pk)


class TestOrder:
    def test_a_contacts_messages_go_out_in_the_order_they_were_queued(self, contact, delay):
        queued(contact, "one", "two", "three")
        backend = FakeBackend()

        assert outbox.drain(contact.pk, backend=backend) == outbox.DrainResult.DONE

        assert bodies(backend.sent) == ["one", "two", "three"]
        assert rows_of(contact) == [
            ("one", MessageStatus.ACCEPTED),
            ("two", MessageStatus.ACCEPTED),
            ("three", MessageStatus.ACCEPTED),
        ]
        wamids = list(WhatsAppMessage.objects.filter(contact=contact).order_by("pk").values_list("wamid", flat=True))
        assert wamids == ["wamid.OUT0001", "wamid.OUT0002", "wamid.OUT0003"]

    def test_each_message_is_sent_only_after_the_one_before_it_was_accepted(self, contact, delay):
        queued(contact, "one", "two", "three")
        backend = FakeBackend()
        seen = []

        def look_at_the_queue(_contact, message):
            # What the database says at the moment each message is handed to Meta.
            seen.append((message["text"]["body"], rows_of(contact)))

        backend.before_send = look_at_the_queue
        outbox.drain(contact.pk, backend=backend)

        assert seen == [
            ("one", [("one", "QUEUED"), ("two", "QUEUED"), ("three", "QUEUED")]),
            ("two", [("one", "ACCEPTED"), ("two", "QUEUED"), ("three", "QUEUED")]),
            ("three", [("one", "ACCEPTED"), ("two", "ACCEPTED"), ("three", "QUEUED")]),
        ]

    def test_draining_again_sends_nothing_twice(self, contact, delay):
        queued(contact, "one", "two")
        backend = FakeBackend()

        outbox.drain(contact.pk, backend=backend)
        outbox.drain(contact.pk, backend=backend)

        assert bodies(backend.sent) == ["one", "two"]

    def test_draining_one_contact_never_sends_another_contacts_messages(self, contact, delay):
        other = ContactFactory()
        queued(contact, "mine")
        queued(other, "theirs")
        backend = FakeBackend()

        outbox.drain(contact.pk, backend=backend)

        assert bodies(backend.sent) == ["mine"]
        assert rows_of(other) == [("theirs", MessageStatus.QUEUED)]


class TestLocking:
    def test_a_contact_already_being_sent_to_is_left_to_that_sender(self, contact, delay):
        queued(contact, "one")
        backend = FakeBackend()

        # A real second database connection holds the contact's send lock (fakes.py).
        with another_sender_holds_the_send_lock(contact.pk):
            result = outbox.drain(contact.pk, backend=backend)

        # The other sender will send it; sending it here too could put two messages out of order.
        assert result == outbox.DrainResult.BUSY
        assert backend.sent == []
        assert rows_of(contact) == [("one", MessageStatus.QUEUED)]

    def test_another_contacts_lock_doesnt_hold_this_one_up(self, contact, delay):
        # One sender per contact, but different contacts drain in parallel.
        queued(contact, "one")
        other = ContactFactory()
        backend = FakeBackend()

        with another_sender_holds_the_send_lock(other.pk):
            result = outbox.drain(contact.pk, backend=backend)

        assert result == outbox.DrainResult.DONE
        assert bodies(backend.sent) == ["one"]


class TestFailures:
    def test_a_passing_failure_keeps_the_message_queued_and_holds_the_line(self, contact, delay):
        queued(contact, "one", "two")
        backend = FakeBackend(failures=[RetryableSendError(130429, "Meta error 130429: throughput")])

        # Raised for the task to retry; the messages behind it must not overtake it.
        with pytest.raises(RetryableSendError):
            outbox.drain(contact.pk, backend=backend)

        assert backend.sent == []
        assert rows_of(contact) == [("one", MessageStatus.QUEUED), ("two", MessageStatus.QUEUED)]

    # celery_keeps_the_test_connection (conftest.py): config/celery.py would otherwise close the
    # connection this test's transaction is using, before and after the task.
    @pytest.mark.usefixtures("celery_keeps_the_test_connection")
    def test_the_task_retries_a_passing_failure_and_sends_the_same_stored_message_once(self, contact, delay, mocker):
        queued(contact, "one", "two")
        backend = FakeBackend(failures=[RetryableSendError(None, "Couldn't reach Meta: Timeout")])
        mocker.patch("apps.whatsapp.services.outbox.send_backend", return_value=backend)

        # apply() runs the task in this process, retries included (without their countdown).
        send_queued_messages.apply(args=[contact.pk])

        assert bodies(backend.sent) == ["one", "two"]
        assert rows_of(contact) == [("one", MessageStatus.ACCEPTED), ("two", MessageStatus.ACCEPTED)]
        # Only the send was repeated: the work that produced the reply wasn't, so no new rows.
        assert WhatsAppMessage.objects.filter(contact=contact).count() == 2

    @pytest.mark.usefixtures("celery_keeps_the_test_connection")
    def test_when_every_retry_fails_the_message_fails_and_the_rest_are_cancelled(self, contact, delay, mocker):
        queued(contact, "one", "two", "three")
        throttled = [RetryableSendError(131056, "Meta error 131056: pair rate limit")] * (outbox.MAX_SEND_RETRIES + 1)
        backend = FakeBackend(failures=throttled)
        mocker.patch("apps.whatsapp.services.outbox.send_backend", return_value=backend)

        send_queued_messages.apply(args=[contact.pk])

        # The first try, then every retry.
        assert backend.attempts == outbox.MAX_SEND_RETRIES + 1
        assert rows_of(contact) == [
            ("one", MessageStatus.FAILED),
            ("two", MessageStatus.CANCELLED),
            ("three", MessageStatus.CANCELLED),
        ]
        assert WhatsAppMessage.objects.filter(contact=contact).order_by("pk").first().error_code == 131056

    @pytest.mark.usefixtures("celery_keeps_the_test_connection")
    def test_without_a_worker_a_passing_failure_waits_for_the_send_queued_command(
        self, settings, contact, delay, mocker
    ):
        # With CELERY_TASK_ALWAYS_EAGER, Celery runs a retry at once and ignores its countdown, so a
        # rate limit would use up every retry in a second (plan section 10). Instead the message stays
        # queued, and the whatsapp_send_queued command, run from cron, gives the wait (Step 1.4d).
        settings.CELERY_TASK_ALWAYS_EAGER = True
        queued(contact, "one", "two")
        backend = FakeBackend(failures=[RetryableSendError(130429, "Meta error 130429: throughput")])
        mocker.patch("apps.whatsapp.services.outbox.send_backend", return_value=backend)

        send_queued_messages.apply(args=[contact.pk])

        assert backend.attempts == 1
        assert rows_of(contact) == [("one", MessageStatus.QUEUED), ("two", MessageStatus.QUEUED)]

    def test_each_retry_waits_longer_than_the_one_before_up_to_a_limit(self):
        delays = [outbox.retry_delay(retries) for retries in range(10)]

        assert delays[0] > 0
        assert delays[:4] == sorted(delays[:4]) and len(set(delays[:4])) == 4
        assert max(delays) == outbox.MAX_RETRY_DELAY_SECONDS

    @pytest.mark.parametrize(
        "error",
        [
            PermanentSendError(131026, "Meta error 131026: undeliverable"),
            WindowClosedError(131047, "Meta error 131047: re-engagement message"),
            TokenRejectedError(190, "Meta error 190: access token expired"),
        ],
        ids=["undeliverable", "window-closed", "token-rejected"],
    )
    def test_a_permanent_failure_fails_the_message_and_cancels_the_ones_behind_it(self, contact, delay, error):
        queued(contact, "one", "two", "three")
        # The first message goes; the second fails for good.
        backend = FakeBackend(failures=[None, error])

        assert outbox.drain(contact.pk, backend=backend) == outbox.DrainResult.DONE

        assert bodies(backend.sent) == ["one"]
        # "three" made sense only after "two", so it's cancelled rather than sent out of context.
        assert rows_of(contact) == [
            ("one", MessageStatus.ACCEPTED),
            ("two", MessageStatus.FAILED),
            ("three", MessageStatus.CANCELLED),
        ]
        failed = WhatsAppMessage.objects.get(contact=contact, status=MessageStatus.FAILED)
        assert failed.error_code == error.code

    def test_a_message_queued_after_a_failure_is_sent_normally(self, contact, delay):
        # A failure cancels only what was waiting behind it, never a later conversation's replies.
        queued(contact, "one", "two")
        outbox.drain(contact.pk, backend=FakeBackend(failures=[PermanentSendError(131026, "undeliverable")]))
        queued(contact, "later")
        backend = FakeBackend()

        outbox.drain(contact.pk, backend=backend)

        assert bodies(backend.sent) == ["later"]


@pytest.mark.usefixtures("strict_mode")
class TestStrictMode:
    def test_after_one_message_is_accepted_the_next_waits(self, contact, delay):
        queued(contact, "one", "two")
        backend = FakeBackend()

        assert outbox.drain(contact.pk, backend=backend) == outbox.DrainResult.WAITING

        assert bodies(backend.sent) == ["one"]
        assert rows_of(contact) == [("one", MessageStatus.ACCEPTED), ("two", MessageStatus.QUEUED)]

    @pytest.mark.parametrize("meta_status", [MessageStatus.SENT, MessageStatus.DELIVERED, MessageStatus.READ])
    def test_once_the_previous_message_is_sent_the_next_goes(self, contact, delay, meta_status):
        queued(contact, "one", "two")
        # One backend for both drains: like Meta, it never hands out the same id twice.
        backend = FakeBackend()
        outbox.drain(contact.pk, backend=backend)
        # Meta's status webhook reports the first message (Step 1.3c records it on the row).
        WhatsAppMessage.objects.filter(contact=contact, wamid="wamid.OUT0001").update(status=meta_status)

        outbox.drain(contact.pk, backend=backend)

        assert bodies(backend.sent) == ["one", "two"]

    def test_a_previous_message_accepted_too_long_ago_no_longer_holds_the_line(self, contact, delay, freezer):
        # Meta's docs don't promise a `sent` status for every message, so the wait has a limit.
        accepted_at = datetime(2026, 10, 17, 9, 0, tzinfo=timezone.utc)
        freezer.move_to(accepted_at)
        queued(contact, "one", "two")
        # One backend for both drains: like Meta, it never hands out the same id twice.
        backend = FakeBackend()
        outbox.drain(contact.pk, backend=backend)
        freezer.move_to(accepted_at + timedelta(seconds=outbox.STRICT_MODE_MAX_WAIT_SECONDS + 1))

        outbox.drain(contact.pk, backend=backend)

        assert bodies(backend.sent) == ["one", "two"]

    def test_a_sent_status_from_meta_schedules_the_contacts_next_send(
        self, contact, delay, django_capture_on_commit_callbacks
    ):
        message = MessageFactory(
            contact=contact, direction=MessageDirection.OUTBOUND, status=MessageStatus.ACCEPTED, payload=TEXT
        )
        status = DeliveryStatus(
            wamid=message.wamid,
            phone_number_id=contact.account.phone_number_id,
            state="sent",
            error_code=None,
            occurred_at=datetime(2026, 10, 17, 9, 0, tzinfo=timezone.utc),
        )

        with django_capture_on_commit_callbacks(execute=True):
            store_events([status], {contact.account.phone_number_id: contact.account})

        delay.assert_called_once_with(contact.pk)

    def test_a_failed_status_from_meta_cancels_the_messages_waiting_behind_it(self, contact, delay):
        queued(contact, "one", "two", "three")
        outbox.drain(contact.pk, backend=FakeBackend())
        status = DeliveryStatus(
            wamid="wamid.OUT0001",
            phone_number_id=contact.account.phone_number_id,
            state="failed",
            error_code=131026,
            occurred_at=datetime(2026, 10, 17, 9, 0, tzinfo=timezone.utc),
        )

        store_events([status], {contact.account.phone_number_id: contact.account})

        assert rows_of(contact) == [
            ("one", MessageStatus.FAILED),
            ("two", MessageStatus.CANCELLED),
            ("three", MessageStatus.CANCELLED),
        ]


class TestStatusesWithoutStrictMode:
    def test_a_sent_status_schedules_nothing_when_strict_mode_is_off(
        self, settings, contact, delay, django_capture_on_commit_callbacks
    ):
        # Without strict mode the queue never waits for a status, so there's nothing to wake.
        settings.WHATSAPP_SEND_WAIT_FOR_SENT_STATUS = False
        message = MessageFactory(
            contact=contact, direction=MessageDirection.OUTBOUND, status=MessageStatus.ACCEPTED, payload=TEXT
        )
        status = DeliveryStatus(
            wamid=message.wamid,
            phone_number_id=contact.account.phone_number_id,
            state="sent",
            error_code=None,
            occurred_at=datetime(2026, 10, 17, 9, 0, tzinfo=timezone.utc),
        )

        with django_capture_on_commit_callbacks(execute=True):
            store_events([status], {contact.account.phone_number_id: contact.account})

        delay.assert_not_called()


class TestLogBackend:
    @pytest.mark.parametrize("strict", [False, True], ids=["normal", "strict"])
    def test_the_log_backend_marks_messages_sent_in_order_without_any_http_call(
        self, settings, contact, delay, mocker, strict
    ):
        # No webhook ever reports on a logged message, so it's `sent` at once, or strict mode would
        # wait forever.
        settings.WHATSAPP_SEND_WAIT_FOR_SENT_STATUS = strict
        post = mocker.patch("apps.whatsapp.client.requests.post")
        queued(contact, "one", "two")

        assert outbox.drain(contact.pk, backend=LogSendBackend()) == outbox.DrainResult.DONE

        assert rows_of(contact) == [("one", MessageStatus.SENT), ("two", MessageStatus.SENT)]
        assert all(
            wamid.startswith("log.")
            for wamid in WhatsAppMessage.objects.filter(contact=contact).values_list("wamid", flat=True)
        )
        post.assert_not_called()
