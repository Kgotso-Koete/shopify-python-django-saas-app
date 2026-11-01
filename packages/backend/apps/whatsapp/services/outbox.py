"""
The ordered send queue (plan Step 1.4c, decision D21).

The queue is the message table: every reply is first stored as an outbound WhatsAppMessage with
status QUEUED, in the same transaction as the work that produced it, so nothing is lost if a worker
restarts and no extra store is needed (agents.md section 4.1). Redis only carries the Celery note
that wakes a worker ("drain contact 7"), never the messages or their order.

One drain at a time per contact sends that contact's queued rows strictly in the order they were
queued (by id), each only after Meta accepted the one before it. Different contacts drain in
parallel. Each message gets its own short transaction: take the contact's send lock (a Postgres
advisory lock), take its oldest queued row, send it, save Meta's id, commit. A status webhook that
arrives quickly then finds the id.

Meta's error codes, and which ones to retry:
https://developers.facebook.com/documentation/business-messaging/whatsapp/support/error-codes
Meta's message statuses, reported by webhook:
https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/reference/messages/status.md
"""

import enum
import logging
from datetime import timedelta
from functools import partial

from django.conf import settings
from django.db import connection, transaction
from django.db.models import Min
from django.utils import timezone

from ..client import PermanentSendError, RetryableSendError, SendError, send_backend
from ..constants import MessageDirection, MessageKind, MessageStatus
from ..models import WhatsAppContact, WhatsAppMessage

logger = logging.getLogger(__name__)

# A passing failure (a timeout, Meta's throughput or same-user pacing limits) is retried this many
# times by the send task, each after a longer wait, before it counts as permanent.
MAX_SEND_RETRIES = 5
FIRST_RETRY_DELAY_SECONDS = 5
MAX_RETRY_DELAY_SECONDS = 300
# Strict mode waits this long at most for Meta's "sent" on the previous message: Meta's docs don't
# promise a status for every message, and a queue must never stick forever.
STRICT_MODE_MAX_WAIT_SECONDS = 30
# The whatsapp_send_queued command (Step 1.4d) gives up on a message still failing for a passing
# reason once it has been queued this long, so a queue never sticks forever without a worker either.
QUEUED_MESSAGE_MAX_AGE_SECONDS = 60 * 60

# The first half of the two-number advisory lock key (the contact id is the second), so these locks
# can't collide with any other code's advisory locks. Any fixed number would do; 0x5741 is "WA".
SEND_LOCK_NAMESPACE = 0x5741

# A queued row's kind comes from the message's own type (builders.py makes only these three).
KINDS_BY_TYPE = {"text": MessageKind.TEXT, "interactive": MessageKind.INTERACTIVE, "image": MessageKind.IMAGE}


class DrainResult(enum.StrEnum):
    """What one drain of a contact's queue ended with."""

    # Nothing left to send (or the contact no longer exists).
    DONE = "done"
    # Another drain holds the contact's lock and will send the queue itself.
    BUSY = "busy"
    # Strict mode: the previous message is accepted but not yet sent; its status webhook wakes us.
    WAITING = "waiting"


@transaction.atomic
def queue_messages(contact: WhatsAppContact, messages: list[dict]) -> list[WhatsAppMessage]:
    """
    Store `messages` (builders.py output) as `contact`'s next queued replies, in order, and wake a
    drain for the contact once they're committed.
    """
    rows = []
    for message in messages:
        kind = KINDS_BY_TYPE.get(message.get("type"))
        if kind is None:
            raise ValueError(f"Can't queue a message of type {message.get('type')!r}.")
        rows.append(
            WhatsAppMessage.objects.create(
                contact=contact,
                direction=MessageDirection.OUTBOUND,
                kind=kind,
                # The whole message, so a retry sends exactly what the handler built.
                payload=message,
                status=MessageStatus.QUEUED,
            )
        )
    _schedule_drain(contact.pk)
    return rows


def drain(contact_id: int, backend=None) -> DrainResult:
    """
    Send `contact_id`'s queued messages, oldest first, one transaction each.

    A permanent send error marks the message FAILED and cancels the ones queued behind it, then the
    drain goes on (there's nothing left behind it). A passing one (RetryableSendError) is raised for
    the send task to retry; that message's transaction rolls back, so it stays QUEUED.
    """
    backend = backend or send_backend()
    while True:
        with transaction.atomic():
            # If another drain holds the contact's lock, leave the queue to it rather than wait, so
            # two workers never interleave one contact's messages.
            if not _try_lock_contact(contact_id):
                return DrainResult.BUSY
            contact = WhatsAppContact.objects.filter(pk=contact_id).first()
            if contact is None:
                return DrainResult.DONE

            head = _queued(contact_id).first()
            if head is None:
                return DrainResult.DONE
            if settings.WHATSAPP_SEND_WAIT_FOR_SENT_STATUS and _waiting_on_previous(head):
                return DrainResult.WAITING

            try:
                wamid = backend.send(contact, head.payload)
            except PermanentSendError as error:
                _fail(head, error)
                continue

            head.wamid = wamid
            head.status = backend.status_after_send
            head.save(update_fields=["wamid", "status", "updated_at"])


def drain_all() -> dict[str, int]:
    """
    Drain every contact that has queued messages, oldest queue first: the whatsapp_send_queued
    command's work (Step 1.4d), for deployments without a Celery worker and as a safety net for
    queues a crash or a `busy` drain left behind.

    A passing failure is left queued for the next run, which is the backoff an eager deployment
    can't give, unless its message has been queued longer than QUEUED_MESSAGE_MAX_AGE_SECONDS; then
    it's given up like the send task's last retry. Returns how many contacts ended each way.
    """
    counts = {"checked": 0, "sent": 0, "busy": 0, "waiting": 0, "to_retry": 0, "given_up": 0}
    contact_ids = (
        WhatsAppMessage.objects.filter(direction=MessageDirection.OUTBOUND, status=MessageStatus.QUEUED)
        .values("contact_id")
        .annotate(oldest=Min("pk"))
        .order_by("oldest")
        .values_list("contact_id", flat=True)
    )
    outcome_counts = {DrainResult.DONE: "sent", DrainResult.BUSY: "busy", DrainResult.WAITING: "waiting"}
    for contact_id in list(contact_ids):
        counts["checked"] += 1
        try:
            counts[outcome_counts[drain(contact_id)]] += 1
        except RetryableSendError as error:
            head = _queued(contact_id).first()
            cutoff = timezone.now() - timedelta(seconds=QUEUED_MESSAGE_MAX_AGE_SECONDS)
            if head is not None and head.created_at <= cutoff:
                give_up(contact_id, error)
                counts["given_up"] += 1
            else:
                counts["to_retry"] += 1
    return counts


def give_up(contact_id: int, error: SendError) -> None:
    """The send task's last resort after every retry failed: fail the head of the queue, cancel the rest."""
    with transaction.atomic():
        head = _queued(contact_id).select_for_update().first()
        if head is not None:
            _fail(head, error)


def retry_delay(retries: int) -> int:
    """Seconds before retry number `retries + 1`: 5, 10, 20, 40… up to MAX_RETRY_DELAY_SECONDS."""
    return min(FIRST_RETRY_DELAY_SECONDS * 2**retries, MAX_RETRY_DELAY_SECONDS)


def on_status(message: WhatsAppMessage) -> None:
    """
    Called by the webhook (services/inbound.py) after Meta's status for one of our messages is
    recorded. Only strict mode waits on statuses: there, a FAILED message cancels what was queued
    behind it, and any status wakes the contact's queue.
    """
    if not settings.WHATSAPP_SEND_WAIT_FOR_SENT_STATUS:
        return
    if message.status == MessageStatus.FAILED:
        _cancel_behind(message)
    _schedule_drain(message.contact_id)


def _try_lock_contact(contact_id: int) -> bool:
    """
    Take the contact's send lock for the current transaction, or return False at once if another
    transaction holds it. A Postgres advisory lock (maintainer's decision, 2026-10-17), not a lock on
    the contact's row: it blocks nothing else, so an inbound message updating the contact's name or
    number never waits behind a send, and it's released at commit or rollback like a row lock.
    https://www.postgresql.org/docs/current/functions-admin.html#FUNCTIONS-ADVISORY-LOCKS
    """
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_xact_lock(%s, %s)", [SEND_LOCK_NAMESPACE, contact_id])
        return cursor.fetchone()[0]


def _queued(contact_id: int):
    """The contact's queued outbound messages, oldest first: the queue itself."""
    return WhatsAppMessage.objects.filter(
        contact_id=contact_id, direction=MessageDirection.OUTBOUND, status=MessageStatus.QUEUED
    ).order_by("pk")


def _waiting_on_previous(head: WhatsAppMessage) -> bool:
    """Strict mode: whether the message before `head` is accepted by Meta but not yet reported sent."""
    previous = (
        WhatsAppMessage.objects.filter(contact_id=head.contact_id, direction=MessageDirection.OUTBOUND, pk__lt=head.pk)
        .exclude(status=MessageStatus.CANCELLED)
        .order_by("-pk")
        .first()
    )
    if previous is None or previous.status != MessageStatus.ACCEPTED:
        return False
    return previous.updated_at > timezone.now() - timedelta(seconds=STRICT_MODE_MAX_WAIT_SECONDS)


def _fail(head: WhatsAppMessage, error: SendError) -> None:
    """Mark `head` FAILED with Meta's code, and cancel what was queued behind it."""
    head.status = MessageStatus.FAILED
    head.error_code = error.code
    head.save(update_fields=["status", "error_code", "updated_at"])
    _cancel_behind(head)


def _cancel_behind(message: WhatsAppMessage) -> None:
    """
    Cancel the messages queued after `message` for its contact: they only made sense after it.
    Messages queued later, for a later reply, aren't touched, because this runs when it fails.
    """
    cancelled = (
        _queued(message.contact_id)
        .filter(pk__gt=message.pk)
        .update(status=MessageStatus.CANCELLED, updated_at=timezone.now())
    )
    # Ids and Meta's code only, never the message: it may hold personal data.
    logger.warning(
        "WhatsApp message id=%s failed (code %s); %s queued after it cancelled.",
        message.pk,
        message.error_code,
        cancelled,
    )


def _schedule_drain(contact_id: int) -> None:
    """Wake a drain for the contact once the current transaction commits, when its rows are visible."""
    from ..tasks import send_queued_messages

    transaction.on_commit(partial(send_queued_messages.delay, contact_id))
