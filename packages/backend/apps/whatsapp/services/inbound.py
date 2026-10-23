"""
Storing the events of a verified webhook body (plan Step 1.3c, decisions D4 and D7).

The webhook view checks the signature and normalizes the body; this module only stores what came
in. Each message is stored once, keyed on Meta's message id, because Meta retries a webhook it
thinks failed and may deliver the same message twice:
https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/overview.md
"""

import logging

from django.db import IntegrityError, transaction

from ..constants import MessageDirection, MessageKind, MessageStatus
from ..models import WhatsAppAccount, WhatsAppContact, WhatsAppMessage
from ..normalize import DeliveryStatus, InboundMessage, UnsupportedMessage
from . import outbox

logger = logging.getLogger(__name__)

# Meta's status values (statuses[].status) that we record on our outbound messages:
# https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/reference/messages/status.md
META_STATUSES = {
    "sent": MessageStatus.SENT,
    "delivered": MessageStatus.DELIVERED,
    "read": MessageStatus.READ,
    "played": MessageStatus.PLAYED,
    "failed": MessageStatus.FAILED,
}


@transaction.atomic
def store_events(events: list, accounts_by_number: dict[str, WhatsAppAccount]) -> list[int]:
    """
    Store every event of one verified webhook body, and return the ids of the messages that are
    new, for the caller to queue for processing.

    `accounts_by_number` maps each receiving phone_number_id to its account; a number missing from
    it has no account here, so its events are logged and skipped.
    """
    new_message_ids = []
    for event in events:
        account = accounts_by_number.get(event.phone_number_id)
        if account is None:
            # Log the number only, never the message: it may hold personal data.
            logger.warning("WhatsApp event for unknown phone_number_id=%s; skipped.", event.phone_number_id)
            continue

        if isinstance(event, DeliveryStatus):
            _record_status(account, event)
        elif isinstance(event, (InboundMessage, UnsupportedMessage)):
            message_id = _store_message(account, event)
            if message_id is not None:
                new_message_ids.append(message_id)
    return new_message_ids


def _store_message(account: WhatsAppAccount, event) -> int | None:
    """Store one inbound message (and its sender) once; return its id, or None for a duplicate."""
    contact = _contact_for(account, event)

    if isinstance(event, InboundMessage):
        kind = event.kind
        payload = {"text": event.text, "action_id": event.action_id, "flow_response": event.flow_response}
    else:
        kind = MessageKind.UNSUPPORTED
        payload = {"message_type": event.message_type}

    try:
        # A savepoint: a duplicate's IntegrityError would otherwise spoil the whole transaction.
        with transaction.atomic():
            message = WhatsAppMessage.objects.create(
                contact=contact,
                direction=MessageDirection.INBOUND,
                wamid=event.wamid,
                kind=kind,
                payload=payload,
                status=MessageStatus.RECEIVED,
                sent_at=event.sent_at,
            )
    except IntegrityError:
        # The same wamid is already stored: a retried delivery, acknowledged but not repeated.
        logger.info("Duplicate WhatsApp message %s; skipped.", event.wamid)
        return None

    return message.pk


def _contact_for(account: WhatsAppAccount, event) -> WhatsAppContact:
    """The sender's contact on this number, created on first contact and kept up to date (D4)."""
    contact, created = WhatsAppContact.objects.get_or_create(
        account=account,
        bsuid=event.bsuid,
        defaults={"wa_id": event.wa_id, "profile_name": getattr(event, "profile_name", "")},
    )
    if not created:
        # Meta may send the phone number only sometimes, and people rename themselves; keep what's
        # known, and never blank out a phone number Meta just didn't include this time.
        changed = []
        if event.wa_id and contact.wa_id != event.wa_id:
            contact.wa_id = event.wa_id
            changed.append("wa_id")
        profile_name = getattr(event, "profile_name", "")
        if profile_name and contact.profile_name != profile_name:
            contact.profile_name = profile_name
            changed.append("profile_name")
        if changed:
            contact.save(update_fields=[*changed, "updated_at"])
    return contact


def _record_status(account: WhatsAppAccount, event: DeliveryStatus) -> None:
    """Record Meta's status on the outbound message it's about; a status for anything else is ignored."""
    status = META_STATUSES.get(event.state)
    if status is None:
        logger.info("Unknown WhatsApp status %r for %s; ignored.", event.state, event.wamid)
        return
    messages = WhatsAppMessage.objects.filter(
        contact__account=account, direction=MessageDirection.OUTBOUND, wamid=event.wamid
    )
    for message in messages:
        message.status = status
        message.error_code = event.error_code
        # updated_at too: strict ordering times its wait from it (services/outbox.py).
        message.save(update_fields=["status", "error_code", "updated_at"])
        # Strict ordering waits on these statuses: wake the queue, or cancel behind a failure (D21).
        outbox.on_status(message)
