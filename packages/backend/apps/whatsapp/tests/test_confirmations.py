"""
Tests for apps/whatsapp/services/confirmations.py: every write in chat is confirmed by the user, on
the server (plan Step 1.8b, decision D11, user story 8).

A write first becomes a WhatsAppPendingAction holding the exact action, arguments, user and
organization, with an expiry. The user gets a summary with Confirm and Cancel. Only pressing Confirm
runs it, once, and the action rechecks the permission when it runs. Menus and the assistant share
this, so the AI can never confirm on the user's behalf.

Kind of test: integration (agents.md section 2.5). Why: pending actions and conversations are rows
in the test database, driven through the router; the internal number's handler and the action are
fakes that record what they were asked.
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from .. import registry
from ..builders import text_reply
from ..constants import AccountPurpose, MessageDirection, MessageKind
from ..models import WhatsAppAgentItem, WhatsAppConversation, WhatsAppMessage, WhatsAppPendingAction
from ..services import confirmations, router
from ..services.confirmations import ActionRefused
from .factories import ContactFactory, InternalAccountFactory, MessageFactory, link_member

pytestmark = pytest.mark.django_db

ran = []


def create_item(user, tenant, name):
    """The fake action: records each run, and refuses a name the 'permission check' rejects."""
    if name == "forbidden":
        raise ActionRefused("You no longer have permission to do that.")
    ran.append((user.pk, name))
    return f"Created {name}."


class AskingHandler:
    """An internal number's handler whose free text asks to confirm creating an item with that name."""

    def main_menu(self, turn):
        return text_reply("MAIN MENU")

    def on_choice(self, turn, kind, data):
        return text_reply(f"CHOSE {kind}")

    def on_free_text(self, turn, text):
        return confirmations.ask_to_confirm(
            turn, action="test.create_item", arguments={"name": text}, summary=f"Create an item called {text}?"
        )

    def on_flow_reply(self, turn, response):
        return text_reply("FLOW")


@pytest.fixture(autouse=True)
def setup(settings, mocker):
    settings.WHATSAPP_DEFAULT_CONVERSATION_MODE = "AGENTIC"
    mocker.patch("apps.whatsapp.tasks.send_queued_messages.delay")
    # apps.whatsapp_saas registers the real handler at startup; it's put back afterwards.
    real = registry.handler_for(AccountPurpose.INTERNAL_COMMUNICATIONS)
    registry.register_handler(AccountPurpose.INTERNAL_COMMUNICATIONS, AskingHandler())
    confirmations.register_action("test.create_item", create_item)
    ran.clear()
    yield
    registry.register_handler(AccountPurpose.INTERNAL_COMMUNICATIONS, real)
    confirmations.unregister_action("test.create_item")


@pytest.fixture
def linked():
    contact = ContactFactory(account=InternalAccountFactory())
    link_member(contact)
    return contact


def send(contact, text=None, *, press=None):
    """Route one inbound message, a text or a press on a choice id, and return the reply texts."""
    if press is None:
        message = MessageFactory(contact=contact, payload={"text": text, "action_id": "", "flow_response": {}})
    else:
        message = MessageFactory(
            contact=contact,
            kind=MessageKind.BUTTON_REPLY,
            payload={"text": "", "action_id": press, "flow_response": {}},
        )
    router.route(message.pk)
    rows = WhatsAppMessage.objects.filter(contact=contact, direction=MessageDirection.OUTBOUND).order_by("pk")
    texts = [row.payload["interactive"]["body"]["text"] for row in rows]
    rows.delete()
    return texts


def button(contact, title):
    """The opaque id of the button titled `title` on the last screen."""
    choices = WhatsAppConversation.objects.get(contact=contact).state["choices"]
    [choice_id] = [cid for cid, choice in choices.items() if choice["kind"] == f"whatsapp.{title.lower()}"]
    return choice_id


class TestAsking:
    def test_a_write_is_summarised_with_confirm_and_cancel_and_nothing_runs_yet(self, linked):
        replies = send(linked, "Monthly report")

        assert replies == ["Create an item called Monthly report?"]
        assert ran == []
        pending = WhatsAppPendingAction.objects.get()
        assert pending.action == "test.create_item"
        assert pending.arguments == {"name": "Monthly report"}
        assert pending.user == linked.identity.user
        assert pending.consumed_at is None


class TestConfirming:
    def test_confirm_runs_the_stored_action_with_its_exact_arguments(self, linked):
        send(linked, "Monthly report")

        replies = send(linked, press=button(linked, "Confirm"))

        assert ran == [(linked.identity.user.pk, "Monthly report")]
        assert replies[0] == "Created Monthly report."

    def test_it_runs_once_even_if_confirmed_again(self, linked):
        send(linked, "Monthly report")
        confirm = button(linked, "Confirm")
        send(linked, press=confirm)

        send(linked, press=confirm)

        assert len(ran) == 1

    def test_cancel_runs_nothing(self, linked):
        send(linked, "Monthly report")

        replies = send(linked, press=button(linked, "Cancel"))

        assert ran == []
        assert replies[0].startswith("Cancelled")
        assert WhatsAppPendingAction.objects.get().consumed_at is not None

    def test_an_expired_confirmation_runs_nothing(self, linked):
        send(linked, "Monthly report")
        confirm = button(linked, "Confirm")
        WhatsAppPendingAction.objects.update(expires_at=timezone.now() - timedelta(seconds=1))

        replies = send(linked, press=confirm)

        assert ran == []
        assert replies[0].startswith("That confirmation has expired")

    def test_the_permission_is_checked_again_when_it_runs(self, linked):
        # The action refuses (as a use case does when the user lost the permission since asking).
        send(linked, "forbidden")

        replies = send(linked, press=button(linked, "Confirm"))

        assert ran == []
        assert replies[0] == "You no longer have permission to do that."

    def test_another_contacts_confirmation_does_nothing(self, linked):
        send(linked, "Monthly report")
        theirs = WhatsAppPendingAction.objects.get()
        other = ContactFactory(account=linked.account)
        link_member(other)
        send(other, "something")
        # Point the other contact's Confirm button at the first contact's pending action, as a
        # tampered id would.
        conversation = WhatsAppConversation.objects.get(contact=other)
        conversation.state["choices"][button(other, "Confirm")]["data"]["pending"] = theirs.pk
        conversation.save()

        send(other, press=button(other, "Confirm"))

        assert "Monthly report" not in [name for _, name in ran]
        assert WhatsAppPendingAction.objects.get(pk=theirs.pk).consumed_at is None


class TestTheAssistantIsTold:
    """
    The assistant only proposes writes; the outcome comes from the server (Step 1.13, D11). In
    agentic mode it's saved in the history as what the assistant's side said, so the model knows.
    """

    @pytest.mark.parametrize(
        "pressed, outcome",
        [("Confirm", "Created Monthly report."), ("Cancel", "Cancelled. Nothing was done.")],
    )
    def test_the_outcome_is_saved_in_the_assistants_history(self, linked, pressed, outcome):
        send(linked, "Monthly report")

        send(linked, press=button(linked, pressed))

        [item] = WhatsAppAgentItem.objects.values_list("item", flat=True)
        assert item == {"role": "assistant", "content": outcome}

    def test_in_menu_mode_nothing_is_saved(self, linked):
        send(linked, "Monthly report")
        # Changed directly: "mode menu" would discard the pending action.
        linked.identity.conversation_mode = "WHATSAPP_FORM"
        linked.identity.save()

        send(linked, press=button(linked, "Confirm"))

        assert not WhatsAppAgentItem.objects.exists()


class TestDiscarding:
    @pytest.mark.parametrize("word", ["cancel", "mode menu"])
    def test_cancel_and_switching_mode_discard_what_was_waiting(self, linked, word):
        send(linked, "Monthly report")
        confirm = button(linked, "Confirm")

        send(linked, word)
        send(linked, press=confirm)

        assert ran == []
        assert WhatsAppPendingAction.objects.get().consumed_at is not None

    def test_an_unknown_action_is_refused_safely(self, linked):
        send(linked, "Monthly report")
        WhatsAppPendingAction.objects.update(action="test.no_such_action")

        replies = send(linked, press=button(linked, "Confirm"))

        assert ran == []
        assert "can't be done" in replies[0]
