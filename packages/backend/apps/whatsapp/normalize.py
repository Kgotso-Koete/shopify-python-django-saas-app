"""
Turning Meta's nested WhatsApp webhook body into simple, typed events (plan Step 1.3a), so nothing
downstream digs through JSON.

The body's shape, and every field path used below, come from Meta's webhook reference:
- Envelope (object, entry[], changes[], value, field):
  https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/reference/messages.md
- Business-scoped user ids (contacts[].user_id, messages[].from_user_id; `from` and `wa_id` may
  be omitted): https://developers.facebook.com/documentation/business-messaging/whatsapp/business-scoped-user-ids
- Button and list replies:
  https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/reference/messages/interactive.md
- Flow replies (nfm_reply, response_json):
  https://developers.facebook.com/documentation/business-messaging/whatsapp/flows/guides/flowswebhooks.md
- Statuses: https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/reference/messages/status.md

One body can hold several entries, changes, messages and statuses (Meta batches them), and every
one is returned, in order.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .constants import MessageKind

# The only change field this app handles; others (account_update, user_id_update, ...) are ignored.
MESSAGES_FIELD = "messages"


class MalformedWebhook(ValueError):
    """The body doesn't have the shape Meta documents, so it can't be processed."""


@dataclass(frozen=True)
class InboundMessage:
    """A message someone sent to one of our numbers, of a kind the app handles (MessageKind)."""

    # Meta's id for the message ("wamid..."), unique, used to store each message once.
    wamid: str
    # The receiving number (value.metadata.phone_number_id), which picks the account (D6).
    phone_number_id: str
    # The sender's business-scoped user id: always present, the contact's key (D4).
    bsuid: str
    # The sender's phone number, or "" when Meta omits it.
    wa_id: str
    # The name the sender set in WhatsApp, for display only.
    profile_name: str
    kind: str
    # The text typed, or the pressed button's or picked row's title.
    text: str
    # The pressed button's or picked row's id, "" for other kinds.
    action_id: str
    # A completed Flow's answers, parsed from response_json; {} for other kinds.
    flow_response: dict = field(default_factory=dict)
    sent_at: datetime | None = None


@dataclass(frozen=True)
class DeliveryStatus:
    """What happened to a message we sent: sent, delivered, read, played or failed."""

    wamid: str
    phone_number_id: str
    state: str
    # Meta's error code when state is "failed" (e.g. 131047, the 24-hour window closed), else None.
    error_code: int | None
    occurred_at: datetime


@dataclass(frozen=True)
class UnsupportedMessage:
    """A message of a type the app doesn't handle yet; kept, so the sender can be told so."""

    wamid: str
    phone_number_id: str
    bsuid: str
    wa_id: str
    # Meta's messages[].type, e.g. "sticker", "image" or "unsupported".
    message_type: str
    sent_at: datetime


def normalize_webhook(payload) -> list:
    """Every message and status in a Meta webhook body, as typed events, in the order Meta sent them."""
    events = []
    for change in _messages_changes(payload):
        value = change.get("value")
        if not isinstance(value, dict):
            raise MalformedWebhook("A messages change has no value object.")
        phone_number_id = _receiving_number(value)

        # Senders are listed once in contacts[]; each message names its sender by from_user_id.
        names_by_bsuid = {
            contact.get("user_id"): contact.get("profile", {}).get("name", "")
            for contact in value.get("contacts", [])
            if isinstance(contact, dict)
        }

        for message in value.get("messages", []):
            events.append(_message_event(message, phone_number_id, names_by_bsuid))
        for status in value.get("statuses", []):
            events.append(_status_event(status, phone_number_id))
    return events


def receiving_phone_number_ids(payload) -> set[str]:
    """Every receiving number a body names; the webhook view picks the signing secret from these (D6)."""
    numbers = set()
    for change in _messages_changes(payload):
        value = change.get("value")
        if not isinstance(value, dict):
            raise MalformedWebhook("A messages change has no value object.")
        numbers.add(_receiving_number(value))
    return numbers


def _messages_changes(payload):
    """Yield every change whose field is "messages", across all entries; reject a malformed envelope."""
    if not isinstance(payload, dict):
        raise MalformedWebhook("The webhook body is not a JSON object.")
    entries = payload.get("entry")
    if not isinstance(entries, list):
        raise MalformedWebhook("The webhook body has no entry list.")
    for entry in entries:
        for change in entry.get("changes", []) if isinstance(entry, dict) else []:
            if isinstance(change, dict) and change.get("field") == MESSAGES_FIELD:
                yield change


def _receiving_number(value: dict) -> str:
    """value.metadata.phone_number_id, which every messages change carries."""
    phone_number_id = (value.get("metadata") or {}).get("phone_number_id")
    if not phone_number_id:
        raise MalformedWebhook("A messages change has no metadata.phone_number_id.")
    return phone_number_id


def _message_event(message, phone_number_id: str, names_by_bsuid: dict):
    """One messages[] item as an InboundMessage, or an UnsupportedMessage for a type we don't handle."""
    if not isinstance(message, dict) or not message.get("id"):
        raise MalformedWebhook("A message has no id.")
    # Meta includes from_user_id in every incoming message; `from` (the phone) may be omitted.
    bsuid = message.get("from_user_id")
    if not bsuid:
        raise MalformedWebhook("A message has no from_user_id (business-scoped user id).")

    common = {
        "wamid": message["id"],
        "phone_number_id": phone_number_id,
        "bsuid": bsuid,
        "wa_id": message.get("from", ""),
    }
    sent_at = _timestamp(message)
    kind, text, action_id, flow_response = _content(message)

    if kind is None:
        return UnsupportedMessage(**common, message_type=message.get("type", ""), sent_at=sent_at)
    return InboundMessage(
        **common,
        profile_name=names_by_bsuid.get(bsuid, ""),
        kind=kind,
        text=text,
        action_id=action_id,
        flow_response=flow_response,
        sent_at=sent_at,
    )


def _content(message: dict):
    """(kind, text, action_id, flow_response) for a handled message, or (None, ...) for any other type."""
    message_type = message.get("type")
    if message_type == "text":
        return MessageKind.TEXT, message.get("text", {}).get("body", ""), "", {}

    if message_type == "interactive":
        interactive = message.get("interactive", {})
        interactive_type = interactive.get("type")
        if interactive_type == "button_reply":
            reply = interactive.get("button_reply", {})
            return MessageKind.BUTTON_REPLY, reply.get("title", ""), reply.get("id", ""), {}
        if interactive_type == "list_reply":
            reply = interactive.get("list_reply", {})
            return MessageKind.LIST_REPLY, reply.get("title", ""), reply.get("id", ""), {}
        if interactive_type == "nfm_reply":
            # response_json is a JSON string holding the Flow's answers and its flow_token.
            try:
                response = json.loads(interactive.get("nfm_reply", {}).get("response_json", "{}"))
            except json.JSONDecodeError:
                raise MalformedWebhook("A Flow reply's response_json is not valid JSON.") from None
            return MessageKind.FLOW_REPLY, "", "", response

    return None, "", "", {}


def _status_event(status, phone_number_id: str) -> DeliveryStatus:
    """One statuses[] item; errors[].code is present only on failures."""
    if not isinstance(status, dict) or not status.get("id"):
        raise MalformedWebhook("A status has no id.")
    errors = status.get("errors") or []
    return DeliveryStatus(
        wamid=status["id"],
        phone_number_id=phone_number_id,
        state=status.get("status", ""),
        error_code=errors[0].get("code") if errors else None,
        occurred_at=_timestamp(status),
    )


def _timestamp(item: dict) -> datetime:
    """Meta's timestamp, Unix seconds as a string, as an aware UTC datetime."""
    try:
        return datetime.fromtimestamp(int(item["timestamp"]), tz=timezone.utc)
    except (KeyError, TypeError, ValueError):
        raise MalformedWebhook("A message or status has no valid timestamp.") from None
