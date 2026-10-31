"""
Tests for apps/whatsapp/services/router.py and registry.py: deciding what every inbound message gets
as a reply (plan Step 1.8a, section 8.5, decision D1, user stories 2, 3 and 21).

The channel stays generic: what an organization's team can do is a handler that apps.whatsapp_saas
registers for internal communications numbers (D1), so these tests register a fake one. The router's
order (section 8.5):
1. on an internal number, anyone but a linked member of its organization gets no reply, except to
   "link <code>" (Step 1.17, maintainer's decision of 2026-10-22); a linked member always works in
   the number's organization
2. a button or list press is resolved through the conversation's choice map, whatever the mode;
   an expired or unknown id gets "that menu has expired" and the main menu
3. a Flow reply goes to the handler (its forms arrive in Step 1.11)
4. an escape word (menu, help, cancel, mode menu, mode ai, unlink) is handled directly, in both modes
5. text the handler asked for (turn.expect_text, Step 1.12b), such as a search's words, goes to it
   once, in either mode
6. other text goes to the main menu in whatsapp_form mode, or to the handler's free text (the
   assistant, Step 1.13) in agentic mode

Replies go through the send queue (D21); the inbound message is then marked processed.

Kind of test: integration (agents.md section 2.5). Why: messages, conversations, memberships and
identities are rows in the test database; the internal number's handler is a fake that records what
it was asked.
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.multitenancy.models import TenantMembership
from apps.multitenancy.tests.factories import TenantMembershipFactory
from apps.users.tests.factories import UserFactory

from .. import registry
from ..agent import history
from ..builders import text_reply
from ..constants import AccountPurpose, ConversationMode, MessageDirection, MessageKind, MessageStatus
from ..models import WhatsAppAgentItem, WhatsAppConversation, WhatsAppIdentity, WhatsAppMessage
from ..services import router
from ..tasks import process_inbound_message
from .factories import ContactFactory, ExternalAccountFactory, InternalAccountFactory, MessageFactory

pytestmark = pytest.mark.django_db


class FakeHandler:
    """Stands in for apps.whatsapp_saas's handler: answers each call with a recognizable text."""

    def __init__(self):
        self.calls = []
        # When set, a press asks for one typed answer, as a Search button does.
        self.asks_for_text = False
        # The organization each main menu was shown for.
        self.organizations = []

    def main_menu(self, turn):
        self.calls.append(("main_menu",))
        self.organizations.append(turn.conversation.tenant)
        # A screen offers buttons; their opaque ids come from the turn's choice map.
        turn.choice("items", page=2)
        return text_reply("MAIN MENU")

    def on_choice(self, turn, kind, data):
        self.calls.append(("on_choice", kind, data))
        if self.asks_for_text:
            turn.expect_text("search.words", store="demo")
            return text_reply("TYPE YOUR SEARCH")
        return text_reply(f"CHOSE {kind}")

    def on_typed_answer(self, turn, kind, data, text):
        self.calls.append(("on_typed_answer", kind, data, text))
        return text_reply(f"TYPED {text}")

    def on_free_text(self, turn, text):
        self.calls.append(("on_free_text", text))
        return text_reply(f"ASSISTANT {text}")

    def on_flow_reply(self, turn, response):
        self.calls.append(("on_flow_reply", response))
        return text_reply("FLOW")


@pytest.fixture
def handler():
    fake = FakeHandler()
    # apps.whatsapp_saas registers the real handler at startup; it's put back afterwards.
    real = registry.handler_for(AccountPurpose.INTERNAL_COMMUNICATIONS)
    registry.register_handler(AccountPurpose.INTERNAL_COMMUNICATIONS, fake)
    yield fake
    registry.register_handler(AccountPurpose.INTERNAL_COMMUNICATIONS, real)


@pytest.fixture(autouse=True)
def settings_for_routing(settings, mocker):
    settings.WHATSAPP_DEFAULT_CONVERSATION_MODE = ConversationMode.WHATSAPP_FORM
    settings.WHATSAPP_CONVERSATION_TTL_SECONDS = 1800
    settings.WEB_APP_URL = "https://app.example.com"
    # The send queue's task: replies are queued rows; nothing is sent in these tests.
    mocker.patch("apps.whatsapp.tasks.send_queued_messages.delay")


def link_member(contact, user=None):
    """Make `user` a member of the number's organization, linked on it from `contact`'s phone."""
    user = user or UserFactory()
    TenantMembershipFactory(user=user, tenant=contact.account.tenant)
    WhatsAppIdentity.objects.create(user=user, contact=contact, account=contact.account)
    return user


@pytest.fixture
def linked(handler):
    """A linked member's contact on their organization's internal number."""
    contact = ContactFactory(account=InternalAccountFactory())
    link_member(contact)
    return contact


def receive(contact, text=None, *, action_id="", kind=MessageKind.TEXT, flow_response=None):
    """Store an inbound message as the webhook would, route it, and return the reply texts."""
    payload = {"text": text or "", "action_id": action_id, "flow_response": flow_response or {}}
    message = MessageFactory(contact=contact, kind=kind, payload=payload)
    router.route(message.pk)
    return replies_to(contact)


def replies_to(contact):
    """The queued replies' texts, oldest first; reading them marks nothing."""
    texts = []
    for row in WhatsAppMessage.objects.filter(contact=contact, direction=MessageDirection.OUTBOUND).order_by("pk"):
        message = row.payload
        texts.append(message["text"]["body"] if message["type"] == "text" else message["interactive"]["body"]["text"])
    WhatsAppMessage.objects.filter(contact=contact, direction=MessageDirection.OUTBOUND).delete()
    return texts


def press_the_button_shown(contact):
    """The opaque id of the choice the fake main menu registered."""
    conversation = WhatsAppConversation.objects.get(contact=contact)
    [choice_id] = [choice_id for choice_id in conversation.state["choices"] if choice_id != "menu"]
    return choice_id


class TestUnlinkedSenders:
    def test_an_unlinked_sender_gets_no_reply(self, handler):
        stranger = ContactFactory(account=InternalAccountFactory())
        message = MessageFactory(contact=stranger, payload={"text": "do you have blue shirts?"})

        router.route(message.pk)

        assert replies_to(stranger) == []
        assert handler.calls == []
        # Answered with silence, once: it isn't routed again.
        message.refresh_from_db()
        assert message.status == MessageStatus.PROCESSED

    def test_a_linked_user_who_left_the_organization_gets_no_reply(self, linked, handler):
        TenantMembership.objects.filter(tenant=linked.account.tenant).delete()

        assert receive(linked, "hi") == []
        assert handler.calls == []

    def test_a_link_command_is_answered(self, handler):
        stranger = ContactFactory(account=InternalAccountFactory())

        [reply] = receive(stranger, "link 123456")

        assert "didn't work" in reply


class TestTheOrganization:
    def test_a_linked_member_works_in_the_numbers_organization(self, linked, handler):
        receive(linked, "hi")

        assert handler.organizations == [linked.account.tenant]
        assert WhatsAppConversation.objects.get(contact=linked).tenant == linked.account.tenant


class TestFreeText:
    def test_in_menu_mode_any_text_gets_the_main_menu(self, linked, handler):
        assert receive(linked, "hello") == ["MAIN MENU"]

    def test_in_agentic_mode_text_goes_to_the_assistant(self, linked, handler):
        linked.identity.conversation_mode = ConversationMode.AGENTIC
        linked.identity.save()

        assert receive(linked, "add an item called Monthly report") == ["ASSISTANT add an item called Monthly report"]

    def test_the_default_mode_applies_when_none_is_saved(self, linked, handler, settings):
        settings.WHATSAPP_DEFAULT_CONVERSATION_MODE = ConversationMode.AGENTIC

        assert receive(linked, "hi") == ["ASSISTANT hi"]

    def test_a_saved_mode_beats_the_default(self, linked, handler, settings):
        settings.WHATSAPP_DEFAULT_CONVERSATION_MODE = ConversationMode.AGENTIC
        linked.identity.conversation_mode = ConversationMode.WHATSAPP_FORM
        linked.identity.save()

        assert receive(linked, "hi") == ["MAIN MENU"]


class TestButtons:
    def test_a_pressed_button_resolves_to_what_it_stands_for(self, linked, handler):
        receive(linked, "hi")

        replies = receive(linked, kind=MessageKind.BUTTON_REPLY, action_id=press_the_button_shown(linked))

        assert replies == ["CHOSE items"]
        assert handler.calls[-1] == ("on_choice", "items", {"page": 2})

    def test_buttons_work_the_same_in_agentic_mode(self, linked, handler):
        receive(linked, "menu")
        linked.identity.conversation_mode = ConversationMode.AGENTIC
        linked.identity.save()

        replies = receive(linked, kind=MessageKind.LIST_REPLY, action_id=press_the_button_shown(linked))

        assert replies == ["CHOSE items"]

    def test_the_main_menu_button_always_works(self, linked, handler):
        assert receive(linked, kind=MessageKind.BUTTON_REPLY, action_id="menu") == ["MAIN MENU"]

    def test_an_unknown_button_says_the_menu_expired_and_shows_the_main_menu(self, linked, handler):
        replies = receive(linked, kind=MessageKind.BUTTON_REPLY, action_id="c999")

        assert replies[0].startswith("That menu has expired")
        assert replies[-1] == "MAIN MENU"

    def test_a_button_from_an_expired_conversation_falls_back_the_same_way(self, linked, handler):
        receive(linked, "hi")
        old_choice = press_the_button_shown(linked)
        WhatsAppConversation.objects.filter(contact=linked).update(
            state_expires_at=timezone.now() - timedelta(seconds=1)
        )

        replies = receive(linked, kind=MessageKind.BUTTON_REPLY, action_id=old_choice)

        assert replies[0].startswith("That menu has expired")

    def test_a_button_from_an_older_screen_doesnt_reach_a_newer_screens_choice(self, linked, handler):
        # Ids are never reused within a conversation, so an old press can't mean something new.
        receive(linked, "hi")
        first = press_the_button_shown(linked)
        receive(linked, "hi")

        assert receive(linked, kind=MessageKind.BUTTON_REPLY, action_id=first)[0].startswith("That menu has expired")


class TestEscapeWords:
    @pytest.mark.parametrize("mode", [ConversationMode.WHATSAPP_FORM, ConversationMode.AGENTIC])
    @pytest.mark.parametrize("word", ["menu", " MENU ", "Menu"])
    def test_menu_shows_the_main_menu_in_both_modes(self, linked, handler, mode, word):
        linked.identity.conversation_mode = mode
        linked.identity.save()

        assert receive(linked, word) == ["MAIN MENU"]

    def test_help_explains_the_escape_words(self, linked, handler):
        [reply] = receive(linked, "help")

        for word in ("menu", "mode ai", "mode menu", "cancel", "unlink"):
            assert word in reply

    def test_mode_ai_and_mode_menu_switch_the_saved_mode(self, linked, handler):
        receive(linked, "mode ai")
        linked.identity.refresh_from_db()
        assert linked.identity.conversation_mode == ConversationMode.AGENTIC

        receive(linked, "mode menu")
        linked.identity.refresh_from_db()
        assert linked.identity.conversation_mode == ConversationMode.WHATSAPP_FORM

    def test_switching_mode_changes_only_this_numbers_link(self, linked, handler):
        user = linked.identity.user
        elsewhere = ContactFactory(account=InternalAccountFactory(), wa_id=linked.wa_id)
        link_member(elsewhere, user)

        receive(linked, "mode ai")

        elsewhere.identity.refresh_from_db()
        assert elsewhere.identity.conversation_mode == ""

    def test_switching_mode_discards_a_half_finished_screen(self, linked, handler):
        receive(linked, "hi")
        old_choice = press_the_button_shown(linked)

        receive(linked, "mode ai")

        assert receive(linked, kind=MessageKind.BUTTON_REPLY, action_id=old_choice)[0].startswith(
            "That menu has expired"
        )

    def test_cancel_discards_the_screen_and_shows_the_main_menu(self, linked, handler):
        receive(linked, "hi")
        old_choice = press_the_button_shown(linked)

        assert receive(linked, "cancel")[-1] == "MAIN MENU"
        assert receive(linked, kind=MessageKind.BUTTON_REPLY, action_id=old_choice)[0].startswith(
            "That menu has expired"
        )

    @pytest.mark.parametrize("word", ["cancel", "mode menu", "mode ai"])
    def test_cancel_and_switching_mode_forget_the_assistants_history(self, linked, handler, word):
        # Chosen on 2026-10-20: kept until cancel, a mode switch or unlink.
        receive(linked, "hi")
        history.append(WhatsAppConversation.objects.get(contact=linked), {"role": "user", "content": "hi"})

        receive(linked, word)

        assert not WhatsAppAgentItem.objects.exists()

    def test_an_expired_conversation_keeps_the_assistants_history(self, linked, handler):
        receive(linked, "hi")
        history.append(WhatsAppConversation.objects.get(contact=linked), {"role": "user", "content": "hi"})
        WhatsAppConversation.objects.filter(contact=linked).update(
            state_expires_at=timezone.now() - timedelta(seconds=1)
        )

        receive(linked, "hi again")

        assert WhatsAppAgentItem.objects.count() == 1

    def test_unlink_removes_the_link_on_this_number_only(self, linked, handler):
        elsewhere = ContactFactory(account=InternalAccountFactory(), wa_id=linked.wa_id)
        link_member(elsewhere, linked.identity.user)

        [reply] = receive(linked, "unlink")

        assert "unlinked" in reply.lower()
        assert list(WhatsAppIdentity.objects.all()) == [elsewhere.identity]

    def test_unlink_in_chat_forgets_the_conversation(self, linked, handler):
        # The router saves its copy of the conversation last, so it must forget as unlink does.
        receive(linked, "hi")
        history.append(WhatsAppConversation.objects.get(contact=linked), {"role": "user", "content": "hi"})

        receive(linked, "unlink")

        conversation = WhatsAppConversation.objects.get(contact=linked)
        assert conversation.tenant is None
        assert "choices" not in conversation.state
        assert not WhatsAppAgentItem.objects.exists()


class TestTypedAnswers:
    """A handler can ask for one typed answer, e.g. a search's words, which no button can carry."""

    def ask_for_text(self, linked, handler):
        handler.asks_for_text = True
        # "menu" shows the main menu in both modes, so there's a button to press.
        receive(linked, "menu")
        assert receive(linked, kind=MessageKind.BUTTON_REPLY, action_id=press_the_button_shown(linked)) == [
            "TYPE YOUR SEARCH"
        ]
        handler.asks_for_text = False

    def test_the_next_text_is_the_answer(self, linked, handler):
        self.ask_for_text(linked, handler)

        assert receive(linked, "blue shirt") == ["TYPED blue shirt"]
        assert handler.calls[-1] == ("on_typed_answer", "search.words", {"store": "demo"}, "blue shirt")

    def test_it_is_answered_once(self, linked, handler):
        self.ask_for_text(linked, handler)
        receive(linked, "blue shirt")

        assert receive(linked, "red shirt") == ["MAIN MENU"]

    def test_an_escape_word_wins_and_drops_the_question(self, linked, handler):
        self.ask_for_text(linked, handler)

        assert receive(linked, "menu") == ["MAIN MENU"]
        assert receive(linked, "blue shirt") == ["MAIN MENU"]

    def test_a_button_press_drops_the_question(self, linked, handler):
        self.ask_for_text(linked, handler)

        receive(linked, kind=MessageKind.BUTTON_REPLY, action_id="menu")

        assert receive(linked, "blue shirt") == ["MAIN MENU"]

    def test_in_agentic_mode_the_answer_goes_to_the_handler_not_the_assistant(self, linked, handler):
        linked.identity.conversation_mode = ConversationMode.AGENTIC
        linked.identity.save()
        self.ask_for_text(linked, handler)

        assert receive(linked, "blue shirt") == ["TYPED blue shirt"]

    def test_an_expired_conversation_forgets_the_question(self, linked, handler):
        self.ask_for_text(linked, handler)
        WhatsAppConversation.objects.filter(contact=linked).update(
            state_expires_at=timezone.now() - timedelta(seconds=1)
        )

        assert receive(linked, "blue shirt") == ["MAIN MENU"]


class TestOtherMessages:
    def test_a_flow_reply_goes_to_the_handler(self, linked, handler):
        replies = receive(linked, kind=MessageKind.FLOW_REPLY, flow_response={"name": "Monthly report"})

        assert replies == ["FLOW"]
        assert handler.calls[-1] == ("on_flow_reply", {"name": "Monthly report"})

    def test_an_unsupported_message_gets_an_explanation_and_the_main_menu(self, linked, handler):
        message = MessageFactory(contact=linked, kind=MessageKind.UNSUPPORTED, payload={"message_type": "sticker"})
        router.route(message.pk)

        replies = replies_to(linked)
        assert "can only read text" in replies[0]
        assert replies[-1] == "MAIN MENU"

    def test_every_reply_is_queued_and_the_message_marked_processed(self, linked, handler):
        message = MessageFactory(contact=linked, payload={"text": "hi", "action_id": "", "flow_response": {}})

        router.route(message.pk)

        message.refresh_from_db()
        assert message.status == MessageStatus.PROCESSED
        queued = WhatsAppMessage.objects.filter(contact=linked, direction=MessageDirection.OUTBOUND)
        assert [row.status for row in queued] == [MessageStatus.QUEUED]

    def test_a_number_without_a_handler_is_processed_without_a_reply(self, mocker):
        # apps.whatsapp_shop registers the external numbers' handler (phase 2); without it, no reply.
        mocker.patch.dict(registry._handlers, clear=False)
        registry.unregister_handler(AccountPurpose.EXTERNAL_COMMUNICATIONS)
        contact = ContactFactory(account=ExternalAccountFactory())

        assert receive(contact, "hi") == []

    def test_a_message_routed_twice_is_answered_once(self, linked, handler):
        message = MessageFactory(contact=linked, payload={"text": "hi", "action_id": "", "flow_response": {}})

        router.route(message.pk)
        router.route(message.pk)

        assert len(replies_to(linked)) == 1


class FakeStoreHandler(FakeHandler):
    """
    Stands in for apps.whatsapp_shop's handler (phase 2): anyone texting an external number is a
    store customer, and the handler decides whether the number answers, in which mode, and its help.
    """

    def __init__(self):
        super().__init__()
        self.answering = True
        self.mode = ConversationMode.WHATSAPP_FORM

    def answers(self, contact):
        return self.answering

    def conversation_mode(self, contact):
        return self.mode

    def help_text(self, turn):
        return "STORE HELP"


@pytest.fixture
def store_handler():
    fake = FakeStoreHandler()
    real = registry.handler_for(AccountPurpose.EXTERNAL_COMMUNICATIONS)
    registry.register_handler(AccountPurpose.EXTERNAL_COMMUNICATIONS, fake)
    yield fake
    registry.register_handler(AccountPurpose.EXTERNAL_COMMUNICATIONS, real)


@pytest.fixture
def customer(store_handler):
    """Someone texting an organization's external number: no link, no membership (phase 2)."""
    return ContactFactory(account=ExternalAccountFactory())


class TestExternalNumbers:
    def test_anyone_gets_the_handlers_main_menu_without_linking(self, customer, store_handler):
        assert receive(customer, "hi") == ["MAIN MENU"]
        assert store_handler.organizations == [customer.account.tenant]

    def test_a_number_its_handler_wont_answer_gets_no_reply_at_all(self, customer, store_handler):
        # E.g. no store chosen yet (user story 25): not even "menu expired" or help.
        store_handler.answering = False

        assert receive(customer, "hi") == []
        assert receive(customer, "help") == []
        assert receive(customer, action_id="c99", kind=MessageKind.BUTTON_REPLY) == []
        assert store_handler.calls == []

    def test_the_handler_sets_the_mode(self, customer, store_handler):
        store_handler.mode = ConversationMode.AGENTIC

        assert receive(customer, "anything blue?") == ["ASSISTANT anything blue?"]

    def test_with_no_mode_from_the_handler_the_default_applies(self, customer, store_handler, settings):
        store_handler.mode = ""
        settings.WHATSAPP_DEFAULT_CONVERSATION_MODE = ConversationMode.AGENTIC

        assert receive(customer, "anything blue?") == ["ASSISTANT anything blue?"]

    def test_help_is_the_handlers_own(self, customer, store_handler):
        assert receive(customer, "help") == ["STORE HELP"]

    @pytest.mark.parametrize("word", ["mode ai", "mode menu", "unlink"])
    def test_the_teams_words_are_ordinary_text(self, customer, store_handler, word):
        # Only a linked member switches modes or unlinks; a store customer's words get the main menu.
        assert receive(customer, word) == ["MAIN MENU"]

    def test_a_handler_without_the_optional_methods_answers_in_the_default_mode(self, mocker):
        # The internal numbers' handler offers none of them: it keeps working as before. No store_handler
        # fixture here: patch.dict would snapshot its fake and put it back after the fixture's own undo.
        plain = FakeHandler()
        mocker.patch.dict(registry._handlers, {AccountPurpose.EXTERNAL_COMMUNICATIONS: plain})
        contact = ContactFactory(account=ExternalAccountFactory())

        assert receive(contact, "help")[0].startswith("Send *menu*")
        assert receive(contact, "hi") == ["MAIN MENU"]


class TestTheTask:
    def test_the_inbound_task_routes_the_message(self, linked, handler):
        message = MessageFactory(contact=linked, payload={"text": "hi", "action_id": "", "flow_response": {}})

        # Called directly, as the Celery worker would call it.
        process_inbound_message(message.pk)

        assert replies_to(linked) == ["MAIN MENU"]
