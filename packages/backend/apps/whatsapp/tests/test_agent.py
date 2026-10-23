"""
Tests for the assistant's runtime in apps/whatsapp/agent/ (plan Step 1.13, decisions D11 and D12,
user story 8): one inbound message in agentic mode, answered by the model with the tools it's given.

- only the given tools run, and only with arguments that match their strict schema; anything else
  is refused back to the model, never run
- tool calls per message are capped (WHATSAPP_AI_MAX_TOOL_CALLS)
- a write doesn't run: its tool asks the user to confirm, and that question ends the turn, so the
  server's summary is what the user confirms (D11)
- every function call in the history gets its output, even when refused, so the history stays valid
- the history is rebuilt from WhatsAppAgentItem rows, the last 20 user turns, and kept until cancel,
  a mode switch or unlink (chosen on 2026-10-20)
- provider failures, or no OpenAI key, become an AgentError with a short message for the user

Kind of test: integration (agents.md section 2.5). Why: conversations and history are rows in the
test database; the provider is a fake that replays scripted replies and records what it was sent.
"""

import pytest

from ..agent import history, service
from ..agent.provider import ProviderError
from ..agent.service import AgentError
from ..agent.tools import Tool, ToolResult, Toolset
from ..builders import text_reply
from ..models import WhatsAppAgentItem, WhatsAppConversation
from ..services.router import Turn
from .agent_fakes import FakeProvider, calls, says
from .factories import ContactFactory, MessageFactory, InternalAccountFactory

pytestmark = pytest.mark.django_db

ran = []


def add(turn, a, b):
    ran.append(("add", a, b))
    return {"success": True, "sum": a + b}


def note(turn, text):
    ran.append(("note", text))
    return {"success": True}


def ask(turn, name):
    ran.append(("ask", name))
    return ToolResult({"success": True, "status": "awaiting_confirmation"}, messages=text_reply(f"Create {name}?"))


def broken(turn):
    raise RuntimeError("a bug in a tool")


TOOLS = Toolset(
    [
        Tool("add", "Add two numbers.", {"a": {"type": "integer"}, "b": {"type": "integer"}}, add),
        Tool("note", "Keep a note; text may be null.", {"text": {"type": ["string", "null"]}}, note),
        Tool("create_thing", "Create a thing, after the user confirms.", {"name": {"type": "string"}}, ask),
        Tool("broken", "Always fails.", {}, broken),
    ]
)


@pytest.fixture(autouse=True)
def setup(settings):
    settings.OPENAI_API_KEY = "sk-test"
    settings.WHATSAPP_AI_MODEL = "gpt-5.1"
    settings.WHATSAPP_AI_MAX_TOOL_CALLS = 3
    ran.clear()


@pytest.fixture
def turn():
    contact = ContactFactory(account=InternalAccountFactory())
    conversation = WhatsAppConversation.objects.create(contact=contact)
    return Turn(
        message=MessageFactory(contact=contact), contact=contact, conversation=conversation, user=None, mode="AGENTIC"
    )


def answer(turn, mocker, provider, text="hi"):
    mocker.patch("apps.whatsapp.agent.service.get_provider", return_value=provider)
    return service.respond(turn, text, tools=TOOLS, instructions="Be brief.")


def saved(turn):
    return list(WhatsAppAgentItem.objects.filter(conversation=turn.conversation).values_list("item", flat=True))


def bodies(messages):
    return [message["interactive"]["body"]["text"] for message in messages]


class TestAnswering:
    def test_text_is_the_reply_with_a_main_menu_button(self, turn, mocker):
        replies = answer(turn, mocker, FakeProvider(says("Hello!")))

        assert bodies(replies) == ["Hello!"]
        assert replies[0]["interactive"]["action"]["buttons"][0]["reply"]["title"] == "Main menu"

    def test_the_request_carries_the_instructions_tools_and_message(self, turn, mocker):
        provider = FakeProvider(says("Hello!"))

        answer(turn, mocker, provider, "hi there")

        [request] = provider.requests
        assert request["instructions"] == "Be brief."
        assert request["items"] == [{"role": "user", "content": "hi there"}]
        assert [tool["name"] for tool in request["tools"]] == ["add", "note", "create_thing", "broken"]

    def test_the_tools_are_strict_function_tools(self):
        [schema] = [tool for tool in TOOLS.schemas() if tool["name"] == "note"]

        assert schema == {
            "type": "function",
            "name": "note",
            "description": "Keep a note; text may be null.",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": ["string", "null"]}},
                "required": ["text"],
                "additionalProperties": False,
            },
            "strict": True,
        }

    def test_a_tool_runs_and_the_model_answers_from_its_result(self, turn, mocker):
        provider = FakeProvider(calls("add", '{"a": 2, "b": 3}'), says("2 and 3 make 5."))

        replies = answer(turn, mocker, provider)

        assert ran == [("add", 2, 3)]
        assert bodies(replies) == ["2 and 3 make 5."]
        assert provider.requests[1]["items"][-1] == {
            "type": "function_call_output",
            "call_id": "call_1",
            "output": '{"success": true, "sum": 5}',
        }

    def test_the_whole_exchange_is_saved_in_order(self, turn, mocker):
        answer(turn, mocker, FakeProvider(calls("add", '{"a": 2, "b": 3}'), says("5.")))

        assert saved(turn) == [
            {"role": "user", "content": "hi"},
            {"type": "function_call", "call_id": "call_1", "name": "add", "arguments": '{"a": 2, "b": 3}'},
            {"type": "function_call_output", "call_id": "call_1", "output": '{"success": true, "sum": 5}'},
            {"role": "assistant", "content": "5."},
        ]


class TestRefusedCalls:
    @pytest.mark.parametrize(
        "name, arguments",
        [
            pytest.param("delete_everything", "{}", id="a_tool_not_in_the_list"),
            pytest.param("add", '{"a": 2}', id="a_missing_argument"),
            pytest.param("add", '{"a": 2, "b": 3, "c": 4}', id="an_extra_argument"),
            pytest.param("add", '{"a": "2", "b": 3}', id="a_wrong_type"),
            pytest.param("add", '{"a": true, "b": 3}', id="a_boolean_isnt_an_integer"),
            pytest.param("add", "not json", id="arguments_that_arent_json"),
            pytest.param("add", "[2, 3]", id="arguments_that_arent_an_object"),
        ],
    )
    def test_it_is_refused_back_to_the_model_and_nothing_runs(self, turn, mocker, name, arguments):
        provider = FakeProvider(calls(name, arguments), says("Sorry."))

        answer(turn, mocker, provider)

        assert ran == []
        output = provider.requests[1]["items"][-1]
        assert output["type"] == "function_call_output"
        assert '"success": false' in output["output"]

    def test_null_is_accepted_where_the_schema_allows_it(self, turn, mocker):
        answer(turn, mocker, FakeProvider(calls("note", '{"text": null}'), says("Noted.")))

        assert ran == [("note", None)]

    def test_a_tool_that_fails_is_reported_to_the_model_without_its_details(self, turn, mocker):
        provider = FakeProvider(calls("broken", "{}"), says("Sorry."))

        answer(turn, mocker, provider)

        output = provider.requests[1]["items"][-1]["output"]
        assert '"success": false' in output
        assert "a bug in a tool" not in output


class TestTheCap:
    def test_more_calls_than_the_cap_stop_with_an_error_and_every_call_has_an_output(self, turn, mocker):
        provider = FakeProvider(*[calls("add", '{"a": 1, "b": 1}', call_id=f"call_{n}") for n in range(5)])

        with pytest.raises(AgentError) as error:
            answer(turn, mocker, provider)

        assert "too many steps" in str(error.value)
        assert len(ran) == 3
        items = saved(turn)
        call_ids = [item["call_id"] for item in items if item.get("type") == "function_call"]
        output_ids = [item["call_id"] for item in items if item.get("type") == "function_call_output"]
        assert call_ids == output_ids


class TestWrites:
    def test_a_write_ends_the_turn_with_its_confirmation_and_the_model_is_told(self, turn, mocker):
        provider = FakeProvider(calls("create_thing", '{"name": "Monthly report"}'))

        replies = answer(turn, mocker, provider)

        assert bodies(replies) == ["Create Monthly report?"]
        # The model isn't asked again in this turn: the summary the user confirms is the server's.
        assert len(provider.requests) == 1
        assert saved(turn)[-1] == {
            "type": "function_call_output",
            "call_id": "call_1",
            "output": '{"success": true, "status": "awaiting_confirmation"}',
        }


class TestFailures:
    def test_a_provider_failure_is_an_agent_error_with_a_way_out(self, turn, mocker):
        with pytest.raises(AgentError) as error:
            answer(turn, mocker, FakeProvider(error=ProviderError("timeout")))

        assert "mode menu" in str(error.value)
        assert "timeout" not in str(error.value)

    def test_without_an_openai_key_the_assistant_isnt_set_up(self, turn, mocker, settings):
        settings.OPENAI_API_KEY = ""
        mocker.patch("apps.whatsapp.agent.service.get_provider", return_value=None)

        with pytest.raises(AgentError) as error:
            service.respond(turn, "hi", tools=TOOLS, instructions="Be brief.")

        assert "isn't set up" in str(error.value)
        assert saved(turn) == []


class TestHistory:
    def test_it_is_rebuilt_from_the_last_20_user_turns(self, turn, mocker):
        for number in range(25):
            history.append(turn.conversation, {"role": "user", "content": f"question {number}"})
            history.append(turn.conversation, {"role": "assistant", "content": f"answer {number}"})
        provider = FakeProvider(says("Hello!"))

        answer(turn, mocker, provider, "question 25")

        items = provider.requests[0]["items"]
        users = [item["content"] for item in items if item.get("role") == "user"]
        assert len(users) == 20
        # Cut only between turns: the window starts on a user's message.
        assert items[0] == {"role": "user", "content": "question 6"}
        assert items[-1] == {"role": "user", "content": "question 25"}

    def test_forgetting_deletes_it(self, turn):
        history.append(turn.conversation, {"role": "user", "content": "hi"})

        history.forget(turn.conversation)

        assert saved(turn) == []
