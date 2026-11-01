"""
Choices shared across the WhatsApp app.

Defined once here so the settings check (checks.py) and, later, the models that store a user's
conversation mode and the send queue all use the same values (agents.md section 2.2).

Every value is its member's own name (plan Step 1.16, agents.md section 5.3b), so the database and the
settings show the same word the code uses. Meta's own values, such as a status webhook's "sent", are
translated where they come in (services/inbound.py).
"""

from django.db import models

# The ActionLog entity type for a WhatsApp number (ActionLog.entity_type is free text, so no upstream
# choices need changing), used by the number troubleshooting tools (plan D18).
ACTION_LOG_ENTITY_TYPE = "whatsapp_account"


class AccountPurpose(models.TextChoices):
    """Who texts a WhatsApp number (plan decision D2, renamed in Step 1.16), which decides its handler."""

    # For the organization's own team: its members text it to run the organization from WhatsApp
    # (menus, forms, the assistant). An organization has one active (Step 1.17).
    INTERNAL_COMMUNICATIONS = "INTERNAL_COMMUNICATIONS", "Internal communications"
    # For people outside the organization: its store customers text it to shop (phase 2), and later
    # other outside parties. Always one organization.
    EXTERNAL_COMMUNICATIONS = "EXTERNAL_COMMUNICATIONS", "External communications"
    # One number for both (plan Step 2.7, redesigned 2026-10-29): members whose phone is linked on it
    # get the team's menus, and anyone else is a store customer. It's the organization's team number.
    INTERNAL_AND_EXTERNAL_COMMUNICATIONS = (
        "INTERNAL_AND_EXTERNAL_COMMUNICATIONS",
        "Internal and external communications",
    )

    @classmethod
    def serves_team(cls, purpose: str) -> bool:
        """Whether the organization's members text a number with this purpose, once linked."""
        return purpose in (cls.INTERNAL_COMMUNICATIONS, cls.INTERNAL_AND_EXTERNAL_COMMUNICATIONS)

    @classmethod
    def serves_customers(cls, purpose: str) -> bool:
        """Whether anyone outside the organization texting a number with this purpose is answered."""
        return purpose in (cls.EXTERNAL_COMMUNICATIONS, cls.INTERNAL_AND_EXTERNAL_COMMUNICATIONS)


# The purposes of numbers the team texts; an organization has one active (plan Step 2.7, decision 1).
TEAM_PURPOSES = (
    AccountPurpose.INTERNAL_COMMUNICATIONS,
    AccountPurpose.INTERNAL_AND_EXTERNAL_COMMUNICATIONS,
)


class ConnectionMethod(models.TextChoices):
    """How an account's number was connected (plan section 8.2)."""

    # From the seed_whatsapp command, removed in Step 1.17 with the numbers it made; no row uses it now.
    SEED = "SEED", "Seed command"
    # An organization admin typed the ids and secrets into the WhatsApp tab's form (user story 11).
    MANUAL = "MANUAL", "Form"
    # Phase 4: Meta's Embedded Signup popup (user story 18).
    EMBEDDED_SIGNUP = "EMBEDDED_SIGNUP", "Embedded Signup"


class MessageKind(models.TextChoices):
    """
    The kinds of incoming message the app handles (plan Step 1.3a), plus UNSUPPORTED: anything else
    Meta sends is stored as an unsupported message rather than dropped, but isn't acted on.

    Field paths: https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/reference/messages.md
    """

    # messages[].text.body
    TEXT = "TEXT", "Text"
    # messages[].interactive.button_reply: a reply button was pressed.
    BUTTON_REPLY = "BUTTON_REPLY", "Button reply"
    # messages[].interactive.list_reply: a row of a list message was picked.
    LIST_REPLY = "LIST_REPLY", "List reply"
    # messages[].interactive.nfm_reply: a WhatsApp Flow (form) was completed.
    FLOW_REPLY = "FLOW_REPLY", "Flow reply"
    # Any other type (a sticker, an image, or Meta's own "unsupported"): stored, not handled.
    UNSUPPORTED = "UNSUPPORTED", "Unsupported"
    # Outbound only: a message we send with buttons, a list, a link button or a Flow (builders.py).
    # Our outbound plain text is TEXT, like inbound text.
    INTERACTIVE = "INTERACTIVE", "Interactive"
    # Outbound only: a picture sent on its own, such as a store's logo at its welcome (Step 2.8,
    # finding 13). An inbound picture is still UNSUPPORTED.
    IMAGE = "IMAGE", "Image"


class MessageDirection(models.TextChoices):
    """Which way a stored message went."""

    # Someone texted one of our numbers.
    INBOUND = "INBOUND", "Inbound"
    # We replied (plan decision D8: queued first, then sent).
    OUTBOUND = "OUTBOUND", "Outbound"


class MessageStatus(models.TextChoices):
    """
    Where a stored message is in its life. One list for both directions:
    - inbound: RECEIVED when the webhook stores it, then PROCESSED once the worker has handled it
    - outbound: QUEUED until sent, ACCEPTED once Meta takes it, then Meta's own statuses, reported
      back by webhook:
      https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/reference/messages/status.md
    - FAILED, either way; CANCELLED for an outbound message that waited behind one that failed (D21)
    """

    RECEIVED = "RECEIVED", "Received"
    PROCESSED = "PROCESSED", "Processed"
    QUEUED = "QUEUED", "Queued"
    # Meta accepted the send request and returned the message's id. Meta's own "sent" comes later,
    # by webhook; strict ordering (WHATSAPP_SEND_WAIT_FOR_SENT_STATUS) waits for it (D21).
    ACCEPTED = "ACCEPTED", "Accepted by Meta"
    SENT = "SENT", "Sent"
    DELIVERED = "DELIVERED", "Delivered"
    READ = "READ", "Read"
    # A voice message was first played.
    PLAYED = "PLAYED", "Played"
    FAILED = "FAILED", "Failed"
    # Never sent: it was queued behind a message that failed, and would make no sense on its own.
    CANCELLED = "CANCELLED", "Cancelled"


class ConversationMode(models.TextChoices):
    """How a conversation is driven (plan section 8.5)."""

    # WhatsApp interactive lists, buttons and Flows: deterministic, no AI involved.
    WHATSAPP_FORM = "WHATSAPP_FORM", "Menus and forms"
    # Free text goes to the AI assistant, which calls the same operations as the menus (plan D10).
    AGENTIC = "AGENTIC", "AI assistant"


class SendBackend(models.TextChoices):
    """Where outbound messages go (plan decision D8)."""

    # Store each reply and mark it sent without calling Meta: the default, which needs nothing.
    LOG = "LOG", "Log only"
    # Send each reply through Meta's WhatsApp Cloud API.
    META = "META", "Meta Cloud API"
