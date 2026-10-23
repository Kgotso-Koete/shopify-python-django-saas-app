"""
Tests for the whatsapp_send_queued management command (plan Step 1.4d): the safety net for the send
queue, run from cron like payfast_daily_maintenance.

It sends the queued replies of every contact that has any. A deployment with no Celery worker
(CELERY_TASK_ALWAYS_EAGER) needs it: there, a passing failure stays queued for this command instead
of being retried at once, and a process that dies mid-send leaves rows that only this command picks
up (plan section 10). It also covers a queue a `busy` drain left behind.

Kind of test: integration (agents.md section 2.5). Why: the command drains rows in the test
database, and the locking test holds the real send lock from a second database connection; the
send backend is a fake that records what it's given.
"""

from datetime import datetime, timedelta, timezone
from io import StringIO

import pytest
from django.core.management import call_command

from ..client import RetryableSendError
from ..constants import MessageDirection, MessageStatus
from ..models import WhatsAppMessage
from ..services import outbox
from .factories import ContactFactory
from .fakes import FakeBackend, another_sender_holds_the_send_lock

pytestmark = pytest.mark.django_db


@pytest.fixture
def delay(mocker):
    """The send task's delay: queueing would otherwise try to reach the Celery broker."""
    return mocker.patch("apps.whatsapp.tasks.send_queued_messages.delay")


@pytest.fixture
def backend(mocker):
    """The fake send backend the command's drains use."""
    fake = FakeBackend()
    mocker.patch("apps.whatsapp.services.outbox.send_backend", return_value=fake)
    return fake


def queue(contact, *bodies):
    """Queue one text message per body for `contact`, the way a handler queues its reply."""
    outbox.queue_messages(contact, [{"type": "text", "text": {"body": body, "preview_url": False}} for body in bodies])


def statuses_of(contact):
    """The contact's outbound rows' statuses, oldest first."""
    return list(
        WhatsAppMessage.objects.filter(contact=contact, direction=MessageDirection.OUTBOUND)
        .order_by("pk")
        .values_list("status", flat=True)
    )


def send_queued():
    """Run the command, and return what it printed."""
    out = StringIO()
    call_command("whatsapp_send_queued", stdout=out)
    return out.getvalue()


class TestSendingWhatIsQueued:
    def test_every_contacts_queued_messages_are_sent_in_order(self, delay, backend):
        first, second = ContactFactory(), ContactFactory()
        queue(first, "one", "two")
        queue(second, "three")

        send_queued()

        assert [message["text"]["body"] for message in backend.sent] == ["one", "two", "three"]
        assert statuses_of(first) == [MessageStatus.ACCEPTED, MessageStatus.ACCEPTED]
        assert statuses_of(second) == [MessageStatus.ACCEPTED]

    def test_running_it_again_sends_nothing_twice(self, delay, backend):
        queue(ContactFactory(), "one")

        send_queued()
        send_queued()

        assert len(backend.sent) == 1

    def test_it_prints_a_summary_and_never_a_message(self, delay, backend):
        queue(ContactFactory(), "Your private order details")
        queue(ContactFactory(), "More private details")

        output = send_queued()

        assert output.strip() == (
            "WhatsApp send queue: 2 contacts checked, 2 sent, 0 busy, 0 waiting, 0 to retry, 0 given up."
        )
        # Message text may hold personal data, and cron output often ends up in an email or a log.
        assert "private" not in output


class TestPassingFailures:
    def test_a_recent_message_that_fails_for_now_stays_queued_for_the_next_run(self, delay, backend):
        contact = ContactFactory()
        queue(contact, "one", "two")
        backend.failures = [RetryableSendError(130429, "Meta error 130429: throughput")]

        output = send_queued()

        assert statuses_of(contact) == [MessageStatus.QUEUED, MessageStatus.QUEUED]
        assert "1 to retry" in output

    def test_a_message_queued_too_long_that_still_fails_is_given_up(self, delay, backend, freezer):
        # So a queue never sticks forever: after QUEUED_MESSAGE_MAX_AGE_SECONDS a passing failure
        # counts as permanent, as it does after the send task's last retry.
        queued_at = datetime(2026, 10, 17, 9, 0, tzinfo=timezone.utc)
        freezer.move_to(queued_at)
        contact = ContactFactory()
        queue(contact, "one", "two")
        freezer.move_to(queued_at + timedelta(seconds=outbox.QUEUED_MESSAGE_MAX_AGE_SECONDS + 1))
        backend.failures = [RetryableSendError(131056, "Meta error 131056: pair rate limit")]

        output = send_queued()

        assert statuses_of(contact) == [MessageStatus.FAILED, MessageStatus.CANCELLED]
        assert WhatsAppMessage.objects.filter(contact=contact).order_by("pk").first().error_code == 131056
        assert "1 given up" in output


class TestLocking:
    def test_a_contact_another_sender_is_draining_is_skipped(self, delay, backend):
        busy, free = ContactFactory(), ContactFactory()
        queue(busy, "busy one")
        queue(free, "free one")

        # A real second database connection holds the busy contact's send lock (fakes.py).
        with another_sender_holds_the_send_lock(busy.pk):
            output = send_queued()

        # The other sender will send it; the command moves on to the next contact.
        assert [message["text"]["body"] for message in backend.sent] == ["free one"]
        assert statuses_of(busy) == [MessageStatus.QUEUED]
        assert "1 busy" in output
