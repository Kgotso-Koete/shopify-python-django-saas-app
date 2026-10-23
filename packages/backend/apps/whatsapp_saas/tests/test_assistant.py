"""
Tests for agentic mode for an organization's team (plan Step 1.13, decisions D11 and D12, user story
8, Step 1.17): a linked member's words go to the assistant with this app's tools and instructions,
and its writes go through the same Confirm as the menus'.

- the model gets the instructions, naming the number's organization, and the fixed tool list
- "add an item called Monthly report" becomes Confirm and Cancel; only the press creates it, and the
  assistant is then told what happened
- when the assistant can't answer, the user is told, and gets the main menu

Kind of test: integration (agents.md section 2.5). Why: messages go through the real router,
handler, tools and confirmations against the test database; the model is a fake that replays
scripted replies, and the send task's Celery delay is patched.
"""

import pytest

from apps.demo.models import CrudDemoItem
from apps.multitenancy.constants import TenantType
from apps.multitenancy.tests.factories import TenantFactory
from apps.whatsapp.agent.provider import ProviderError
from apps.whatsapp.models import WhatsAppAgentItem
from apps.whatsapp.tests.agent_fakes import FakeProvider, calls, says

from ..tools import TOOLS
from .chat import send, team_member

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def setup(settings, mocker):
    settings.WHATSAPP_DEFAULT_CONVERSATION_MODE = "AGENTIC"
    mocker.patch("apps.whatsapp.tasks.send_queued_messages.delay")


@pytest.fixture
def acme():
    return TenantFactory(type=TenantType.ORGANIZATION, name="Acme")


@pytest.fixture
def contact(acme):
    """An admin of Acme, texting Acme's internal number."""
    return team_member(acme)


def with_model(mocker, provider):
    mocker.patch("apps.whatsapp.agent.service.get_provider", return_value=provider)
    return provider


class TestAsking:
    def test_the_model_gets_the_instructions_and_the_tools(self, contact, acme, mocker):
        provider = with_model(mocker, FakeProvider(says("You have no items yet.")))

        [reply] = send(contact, "what items do I have?")

        [request] = provider.requests
        assert "Acme" in request["instructions"]
        assert request["tools"] == TOOLS.schemas()
        assert request["items"] == [{"role": "user", "content": "what items do I have?"}]
        assert reply.body == "You have no items yet."
        assert reply.titles == ["Main menu"]

    def test_the_instructions_never_ask_to_pick_an_organization(self, contact, mocker):
        provider = with_model(mocker, FakeProvider(says("Hello.")))

        send(contact, "hi")

        assert "pick" not in provider.requests[0]["instructions"]


class TestWriting:
    def test_an_item_is_created_only_when_the_user_confirms(self, contact, acme, mocker):
        with_model(mocker, FakeProvider(calls("create_item", '{"name": "Monthly report"}')))

        [question] = send(contact, "add an item called Monthly report")

        assert question.body == "Create Monthly report in Acme?"
        assert question.titles == ["Confirm", "Cancel", "Main menu"]
        assert not CrudDemoItem.objects.exists()

        [done] = send(contact, press=question.press("Confirm"))

        assert done.body == "Created Monthly report in Acme."
        assert CrudDemoItem.objects.get().name == "Monthly report"
        # The model learns the outcome from what the user was told, not from its own claim.
        last = WhatsAppAgentItem.objects.order_by("sequence").last().item
        assert last == {"role": "assistant", "content": "Created Monthly report in Acme."}


class TestWhenTheAssistantCantAnswer:
    def test_a_provider_failure_says_so_and_shows_the_main_menu(self, contact, acme, mocker):
        with_model(mocker, FakeProvider(error=ProviderError("APITimeoutError")))

        screens = send(contact, "hi")

        assert "isn't available right now" in screens[0].body
        assert "Items" in screens[-1].titles

    def test_without_an_openai_key_it_says_its_not_set_up(self, contact, acme, mocker):
        mocker.patch("apps.whatsapp.agent.service.get_provider", return_value=None)

        screens = send(contact, "hi")

        assert "isn't set up" in screens[0].body
        assert "Items" in screens[-1].titles
