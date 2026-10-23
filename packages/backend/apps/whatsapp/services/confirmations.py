"""
Every write in chat is confirmed by the user, on the server (plan Step 1.8b, decision D11).

A handler that wants to change something calls ask_to_confirm: the exact action and arguments are
stored as a WhatsAppPendingAction, and the user gets a summary with Confirm and Cancel. Only a press
on Confirm runs it, at most once, as the user who asked and for the organization they asked about.
The action rechecks the permission when it runs, since it may have changed. Menus and the assistant
share this, so the model can never confirm on the user's behalf.

Actions are registered by the apps that own them (apps.whatsapp_saas), the way handlers are
(registry.py): a callable(user, tenant, **arguments) that returns the reply text, or raises
ActionRefused with a reason the user can read.
"""

from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from ..agent import history
from ..builders import MAIN_MENU, Choice, reply_buttons, text_reply
from ..constants import ConversationMode
from ..models import WhatsAppPendingAction

CONFIRM = "whatsapp.confirm"
CANCEL = "whatsapp.cancel"

_actions = {}


class ActionRefused(Exception):
    """An action that can't run now; its message is shown to the user as it is."""


def register_action(name: str, function) -> None:
    _actions[name] = function


def unregister_action(name: str) -> None:
    _actions.pop(name, None)


def ask_to_confirm(turn, *, action: str, arguments: dict, summary: str, tenant=None) -> list[dict]:
    """Store the write and ask the user to confirm it; nothing runs yet."""
    pending = WhatsAppPendingAction.objects.create(
        conversation=turn.conversation,
        user=turn.user,
        tenant=tenant,
        action=action,
        arguments=arguments,
        # As long as the conversation's own menus last.
        expires_at=timezone.now() + timedelta(seconds=settings.WHATSAPP_CONVERSATION_TTL_SECONDS),
    )
    confirm = Choice(turn.choice(CONFIRM, pending=pending.pk), "Confirm")
    cancel = Choice(turn.choice(CANCEL, pending=pending.pk), "Cancel")
    # Confirm and Cancel, plus Main menu as the way back: Meta's three buttons (D17).
    return [reply_buttons(summary, [confirm, cancel], way_back=MAIN_MENU)]


def handles(kind: str) -> bool:
    """Whether a pressed choice is a Confirm or Cancel, which the router answers through here."""
    return kind in (CONFIRM, CANCEL)


def answer(turn, kind: str, data: dict) -> list[dict]:
    """The reply to a press on Confirm or Cancel."""
    outcome = _outcome(turn, kind, data)
    if turn.mode == ConversationMode.AGENTIC:
        # The assistant only proposed the write; it learns what happened from what the user was told.
        history.append(turn.conversation, {"role": "assistant", "content": outcome})
    return text_reply(outcome)


def _outcome(turn, kind: str, data: dict) -> str:
    with transaction.atomic():
        # Only this conversation's own pending actions, so an id from anywhere else finds nothing.
        pending = (
            WhatsAppPendingAction.objects.select_for_update()
            .filter(
                pk=data.get("pending"),
                conversation=turn.conversation,
                consumed_at__isnull=True,
                expires_at__gt=timezone.now(),
            )
            .first()
        )
        if pending is None:
            return "That confirmation has expired. Nothing was done."
        pending.consumed_at = timezone.now()
        pending.save(update_fields=["consumed_at", "updated_at"])

    if kind == CANCEL:
        return "Cancelled. Nothing was done."
    action = _actions.get(pending.action)
    if action is None:
        return "This action can't be done any more. Nothing was done."
    try:
        return action(pending.user, pending.tenant, **pending.arguments)
    except ActionRefused as refusal:
        return str(refusal)


def discard_pending(conversation) -> None:
    """Consume every open pending action without running it: `cancel`, or a switch of mode."""
    WhatsAppPendingAction.objects.filter(conversation=conversation, consumed_at__isnull=True).update(
        consumed_at=timezone.now()
    )
