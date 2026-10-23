"""
The assistant's history for a conversation (plan Step 1.13, D12), kept in WhatsAppAgentItem.

OpenAI is sent store: false, so this is the only copy, rebuilt into each request. The maintainer
chose on 2026-10-20 to keep it until cancel, a mode switch or unlink, and to send the last 20 user
turns. A window always starts on a user's message, so a function call is never sent without its
output. Older items are deleted as the window moves on: they'd never be sent again, and keeping them
would only keep more personal data.
"""

from django.db.models import Max

from ..models import WhatsAppAgentItem

HISTORY_TURNS = 20


def append(conversation, item: dict) -> None:
    """Add one item at the end of the conversation's history."""
    last = WhatsAppAgentItem.objects.filter(conversation=conversation).aggregate(Max("sequence"))["sequence__max"]
    WhatsAppAgentItem.objects.create(conversation=conversation, sequence=(last or 0) + 1, item=item)
    if item.get("role") == "user":
        _drop_before_window(conversation)


def recent(conversation) -> list[dict]:
    """The items of the last HISTORY_TURNS user turns, oldest first."""
    start = _window_start(conversation)
    items = WhatsAppAgentItem.objects.filter(conversation=conversation, sequence__gte=start)
    return list(items.order_by("sequence").values_list("item", flat=True))


def forget(conversation) -> None:
    """Delete the whole history: on cancel, a mode switch or unlink."""
    WhatsAppAgentItem.objects.filter(conversation=conversation).delete()


def _window_start(conversation) -> int:
    """The sequence of the oldest user message in the window, or 0 for a history without one."""
    users = (
        WhatsAppAgentItem.objects.filter(conversation=conversation, item__role="user")
        .order_by("-sequence")
        .values_list("sequence", flat=True)[:HISTORY_TURNS]
    )
    return min(users, default=0)


def _drop_before_window(conversation) -> None:
    WhatsAppAgentItem.objects.filter(conversation=conversation, sequence__lt=_window_start(conversation)).delete()
