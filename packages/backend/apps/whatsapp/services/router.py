"""
Deciding what every inbound message gets as a reply (plan Step 1.8a, section 8.5, decision D1).

The order, for one stored inbound message:
1. On an internal communications number, anyone but a linked member of its organization gets no
   reply, except to "link <code>" (Step 1.17, maintainer's decision of 2026-10-22). A linked member
   always works in the number's organization.
2. A button or list press is resolved through the conversation's choice map, whatever the mode. An
   unknown or expired id gets "that menu has expired" and the main menu (D17).
3. A completed Flow goes to the handler (Step 1.11).
4. An escape word (menu, help, cancel, mode menu, mode ai, unlink) is handled here, in both modes.
5. Text the handler asked for with turn.expect_text, such as a search's words, goes to it (Step
   1.12b), in both modes. Any other message, an escape word included, drops the question.
6. Other text gets the main menu in whatsapp_form mode, or goes to the assistant in agentic mode.

What users can actually do is the handler's: apps register one per account purpose (registry.py).
Replies go through the ordered send queue (D21), and the message is then marked processed, so a
message routed twice is answered once.
"""

from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .. import registry
from ..agent import history
from ..builders import MAIN_MENU, text_reply
from ..constants import AccountPurpose, ConversationMode, MessageDirection, MessageKind, MessageStatus
from ..models import WhatsAppConversation, WhatsAppMessage
from . import confirmations
from . import identity as identities
from . import outbox

HELP_TEXT = (
    "Send *menu* for the main menu at any time. *mode ai* lets you ask the assistant in your own words, "
    "and *mode menu* goes back to menus and forms. *cancel* stops what you're doing, and *unlink* "
    "disconnects your phone from your account on this number."
)
EXPIRED_TEXT = "That menu has expired, so here's the main menu."
UNSUPPORTED_TEXT = "Sorry, I can only read text, button presses and forms."


@dataclass
class Turn:
    """One inbound message, as a handler sees it: who sent it, and their conversation."""

    message: WhatsAppMessage
    contact: object
    conversation: WhatsAppConversation
    # The linked member on an internal number, and their link; None on an external number.
    user: object
    mode: str
    identity: object = None

    def choice(self, kind: str, **data) -> str:
        """
        Register a button or list row standing for (`kind`, `data`) and return its opaque id, such
        as "c7" (section 8.5). Ids are never reused within a conversation, so a press on an older
        screen can't mean something on a newer one.
        """
        state = self.conversation.state
        number = state.get("next_choice", 1)
        state["next_choice"] = number + 1
        choice_id = f"c{number}"
        state.setdefault("choices", {})[choice_id] = {"kind": kind, "data": data}
        return choice_id

    def expect_text(self, kind: str, **data) -> None:
        """
        Make the next message, if it's typed text and not an escape word, go to the handler's
        on_typed_answer(turn, kind, data, text): a question no button can answer, such as what to
        search for. It's asked once; any other message drops it.
        """
        self.conversation.state["expecting"] = {"kind": kind, "data": data}


def route(message_id: int) -> None:
    """Answer one stored inbound message, once: queue its replies and mark it processed."""
    with transaction.atomic():
        message = (
            WhatsAppMessage.objects.select_for_update()
            .select_related("contact__account")
            .filter(pk=message_id, direction=MessageDirection.INBOUND)
            .first()
        )
        if message is None or message.status != MessageStatus.RECEIVED:
            # Deleted since, or already answered: a retried task does nothing.
            return
        replies = _replies_for(message)
        if replies:
            outbox.queue_messages(message.contact, replies)
        message.status = MessageStatus.PROCESSED
        message.save(update_fields=["status", "updated_at"])


def _replies_for(message) -> list[dict]:
    contact = message.contact
    payload = message.payload or {}
    linked = None
    if contact.account.purpose == AccountPurpose.INTERNAL_COMMUNICATIONS:
        linked = identities.identity_for(contact)
        if linked is None:
            return identities.handle_unlinked_message(contact, payload.get("text", ""))
    handler = registry.handler_for(contact.account.purpose)
    if handler is None:
        # E.g. an external number before phase 2 adds store customers.
        return []

    conversation = _conversation_for(contact)
    # Every number belongs to one organization, and its conversations happen in it (Step 1.17).
    conversation.tenant = contact.account.tenant
    turn = Turn(
        message=message,
        contact=contact,
        conversation=conversation,
        user=linked.user if linked else None,
        mode=(linked.conversation_mode if linked else "") or settings.WHATSAPP_DEFAULT_CONVERSATION_MODE,
        identity=linked,
    )
    try:
        return _answer(turn, handler, payload)
    finally:
        conversation.state_expires_at = timezone.now() + timedelta(seconds=settings.WHATSAPP_CONVERSATION_TTL_SECONDS)
        # Unlinking forgets the organization (conversation.tenant) too.
        conversation.save(update_fields=["tenant", "state", "state_expires_at", "updated_at"])


def _answer(turn, handler, payload) -> list[dict]:
    kind = turn.message.kind
    # A question is for the very next message only, whatever that turns out to be.
    expecting = turn.conversation.state.pop("expecting", None)
    if kind in (MessageKind.BUTTON_REPLY, MessageKind.LIST_REPLY):
        action_id = payload.get("action_id", "")
        choice = _take_choices(turn).get(action_id)
        if action_id == MAIN_MENU.id:
            return handler.main_menu(turn)
        if choice is None:
            return text_reply(EXPIRED_TEXT) + handler.main_menu(turn)
        if confirmations.handles(choice["kind"]):
            # Confirm and Cancel are the channel's, whoever asked (D11).
            return confirmations.answer(turn, choice["kind"], choice["data"])
        return handler.on_choice(turn, choice["kind"], choice["data"])

    _take_choices(turn)
    if kind == MessageKind.FLOW_REPLY:
        return handler.on_flow_reply(turn, payload.get("flow_response") or {})
    if kind == MessageKind.UNSUPPORTED:
        return text_reply(UNSUPPORTED_TEXT) + handler.main_menu(turn)

    text = payload.get("text", "")
    escape = " ".join(text.lower().split())
    if escape == "menu":
        return handler.main_menu(turn)
    if escape == "help":
        return text_reply(HELP_TEXT)
    if escape == "cancel":
        _discard(turn)
        return text_reply("Cancelled.") + handler.main_menu(turn)
    if escape in ("mode ai", "mode menu") and turn.user is not None:
        return _switch_mode(turn, ConversationMode.AGENTIC if escape == "mode ai" else ConversationMode.WHATSAPP_FORM)
    if escape == "unlink" and turn.user is not None:
        identities.unlink(turn.user, turn.contact.account)
        # unlink forgot the stored conversation; this turn's copy is saved last, so it forgets too.
        _discard(turn)
        turn.conversation.tenant = None
        return text_reply("This number is now unlinked from your account. Link it again from your profile page.")

    if expecting is not None:
        return handler.on_typed_answer(turn, expecting["kind"], expecting["data"], text)
    if turn.mode == ConversationMode.AGENTIC:
        return handler.on_free_text(turn, text)
    return handler.main_menu(turn)


def _conversation_for(contact) -> WhatsAppConversation:
    conversation, _ = WhatsAppConversation.objects.select_for_update().get_or_create(contact=contact)
    if conversation.state_expires_at is not None and conversation.state_expires_at <= timezone.now():
        # Silence for longer than the TTL: the menus are forgotten, but ids still never repeat.
        conversation.state = {"next_choice": conversation.state.get("next_choice", 1)}
    return conversation


def _take_choices(turn) -> dict:
    """The current screen's choices, removed: every reply shows a new screen with new ids."""
    return turn.conversation.state.pop("choices", {})


def _discard(turn) -> None:
    """
    Forget half-finished screens, forms, unconfirmed actions and the assistant's history (Step
    1.13); only the id counter stays.
    """
    turn.conversation.state = {"next_choice": turn.conversation.state.get("next_choice", 1)}
    confirmations.discard_pending(turn.conversation)
    history.forget(turn.conversation)


def _switch_mode(turn, mode) -> list[dict]:
    """Save the user's mode on this number (user story 3); switching discards what was half done."""
    identity = turn.identity
    identity.conversation_mode = mode
    identity.save(update_fields=["conversation_mode", "updated_at"])
    _discard(turn)
    if mode == ConversationMode.AGENTIC:
        return text_reply("You're now talking to the assistant: ask in your own words. Send *mode menu* for menus.")
    return text_reply("You're back on menus and forms. Send *mode ai* to ask the assistant instead.")
