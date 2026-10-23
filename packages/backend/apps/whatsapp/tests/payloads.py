"""
Builders for Meta-shaped WhatsApp webhook bodies, used by the WhatsApp tests.

Each builder follows the field paths in Meta's webhook reference, linked next to it, so a test
payload looks like what Meta really sends. All ids and numbers are obviously fake.

- Overview and envelope (object, entry, changes, value, field):
  https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/reference/messages.md
- Business-scoped user ids (contacts[].user_id, messages[].from_user_id, statuses[].recipient_user_id):
  https://developers.facebook.com/documentation/business-messaging/whatsapp/business-scoped-user-ids
"""

import json

# A fake receiving number and a fake sender, used unless a test passes its own.
PHONE_NUMBER_ID = "100000000000001"
DISPLAY_PHONE_NUMBER = "27000000000"
SENDER_BSUID = "ZA.1000000000000000001"
SENDER_WA_ID = "27000001001"
SENDER_NAME = "Thandi"
# Unix seconds, as Meta sends them (a string): 2026-10-15 12:00:00 UTC.
TIMESTAMP = "1792065600"


def envelope(*changes):
    """The outer body Meta posts: one entry (a WhatsApp Business account) holding `changes`."""
    return {
        "object": "whatsapp_business_account",
        "entry": [{"id": "200000000000001", "changes": list(changes)}],
    }


def messages_change(*messages, contacts=None, phone_number_id=PHONE_NUMBER_ID):
    """One `messages` change: the receiving number's metadata, the senders, and their messages."""
    return {
        "field": "messages",
        "value": {
            "messaging_product": "whatsapp",
            "metadata": {"display_phone_number": DISPLAY_PHONE_NUMBER, "phone_number_id": phone_number_id},
            "contacts": contacts if contacts is not None else [contact()],
            "messages": list(messages),
        },
    }


def statuses_change(*statuses, phone_number_id=PHONE_NUMBER_ID):
    """One `messages` change that carries delivery statuses for messages we sent, not user messages."""
    return {
        "field": "messages",
        "value": {
            "messaging_product": "whatsapp",
            "metadata": {"display_phone_number": DISPLAY_PHONE_NUMBER, "phone_number_id": phone_number_id},
            "statuses": list(statuses),
        },
    }


def contact(bsuid=SENDER_BSUID, wa_id=SENDER_WA_ID, name=SENDER_NAME):
    """A contacts[] entry. Meta omits wa_id when it can't share the phone number (BSUID page)."""
    entry = {"profile": {"name": name}, "user_id": bsuid}
    if wa_id:
        entry["wa_id"] = wa_id
    return entry


def _message(wamid, message_type, bsuid, wa_id, **body):
    """The fields every incoming message has; `from` is omitted when Meta can't share the number."""
    message = {"from_user_id": bsuid, "id": wamid, "timestamp": TIMESTAMP, "type": message_type, **body}
    if wa_id:
        message["from"] = wa_id
    return message


def text_message(wamid="wamid.TEXT1", text="Hi", bsuid=SENDER_BSUID, wa_id=SENDER_WA_ID):
    """A text message: messages[].text.body."""
    return _message(wamid, "text", bsuid, wa_id, text={"body": text})


def button_reply(wamid="wamid.BUTTON1", button_id="c1", title="Main menu", bsuid=SENDER_BSUID, wa_id=SENDER_WA_ID):
    """A reply-button press: messages[].interactive.button_reply.{id,title}.
    https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/reference/messages/interactive.md
    """
    return _message(
        wamid,
        "interactive",
        bsuid,
        wa_id,
        interactive={"type": "button_reply", "button_reply": {"id": button_id, "title": title}},
    )


def list_reply(wamid="wamid.LIST1", row_id="c2", title="Acme", bsuid=SENDER_BSUID, wa_id=SENDER_WA_ID):
    """A list-row pick: messages[].interactive.list_reply.{id,title,description}.
    https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/reference/messages/interactive.md
    """
    return _message(
        wamid,
        "interactive",
        bsuid,
        wa_id,
        interactive={"type": "list_reply", "list_reply": {"id": row_id, "title": title, "description": "Owner"}},
    )


def flow_reply(wamid="wamid.FLOW1", response=None, bsuid=SENDER_BSUID, wa_id=SENDER_WA_ID):
    """A completed WhatsApp Flow: messages[].interactive.nfm_reply, whose response_json is a JSON string.
    https://developers.facebook.com/documentation/business-messaging/whatsapp/flows/guides/flowswebhooks.md
    """
    response = response if response is not None else {"flow_token": "signed-token", "name": "Acme"}
    return _message(
        wamid,
        "interactive",
        bsuid,
        wa_id,
        interactive={
            "type": "nfm_reply",
            "nfm_reply": {"name": "flow", "body": "Sent", "response_json": json.dumps(response)},
        },
    )


def sticker_message(wamid="wamid.STICKER1", bsuid=SENDER_BSUID, wa_id=SENDER_WA_ID):
    """A message type this app doesn't handle yet."""
    return _message(wamid, "sticker", bsuid, wa_id, sticker={"id": "media-1", "mime_type": "image/webp"})


def status(wamid="wamid.SENT1", state="delivered", error_code=None):
    """A delivery status for a message we sent: statuses[].{id,status,timestamp,recipient_id,errors}.
    https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/reference/messages/status.md
    """
    entry = {
        "id": wamid,
        "status": state,
        "timestamp": TIMESTAMP,
        "recipient_id": SENDER_WA_ID,
        "recipient_user_id": SENDER_BSUID,
    }
    if error_code is not None:
        entry["errors"] = [{"code": error_code, "title": "Re-engagement message", "message": "Re-engagement message"}]
    return entry
