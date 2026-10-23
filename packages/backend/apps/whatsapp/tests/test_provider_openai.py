"""
Tests for apps/whatsapp/agent/provider.py: the assistant's one call to OpenAI's Responses API, as a
plain HTTP request (plan Step 1.13, decision D12; no SDK, agents.md section 5.3a).

- the request: POST /v1/responses with the key, the model, the instructions, the history as input
  items, strict function tools, one tool call at a time, and store: false, so OpenAI keeps nothing
  (the history is ours)
- the reply: its text and its function calls, as items that can be sent back as history next time
- a timeout, a lost connection, a 429 or a 5xx is tried once more; every failure is one
  ProviderError, whose message holds neither the key nor OpenAI's words

Responses API: https://developers.openai.com/api/docs/api-reference/responses/create
Function calling: https://developers.openai.com/api/docs/guides/function-calling
Conversation state and store: https://developers.openai.com/api/docs/guides/conversation-state

Kind of test: unit (agents.md section 2.5). Why: the provider on its own, with no network;
requests.post is patched with fake responses, as test_client.py does for Meta.
"""

from unittest.mock import Mock

import pytest
import requests

from ..agent.provider import RESPONSES_URL, FunctionCall, OpenAIProvider, ProviderError, get_provider

# The root conftest.py registers fixtures whose autouse parts need the database.
pytestmark = pytest.mark.django_db

TOOL = {
    "type": "function",
    "name": "list_items",
    "description": "List the selected organization's items.",
    "parameters": {
        "type": "object",
        "properties": {"page": {"type": ["integer", "null"]}},
        "required": ["page"],
        "additionalProperties": False,
    },
    "strict": True,
}


def fake_response(status, body):
    response = Mock(status_code=status, ok=status < 400)
    response.json.return_value = body
    return response


def response_with(*output, status="completed"):
    """A Responses API response holding `output` items, as OpenAI returns it."""
    return fake_response(
        200, {"id": "resp_1", "object": "response", "model": "gpt-5.1", "status": status, "output": list(output)}
    )


def message(text):
    return {
        "type": "message",
        "id": "msg_1",
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "output_text", "text": text, "annotations": []}],
    }


def function_call(name, arguments, call_id="call_1"):
    return {
        "type": "function_call",
        "id": "fc_1",
        "call_id": call_id,
        "name": name,
        "arguments": arguments,
        "status": "completed",
    }


def openai_error(status, code="server_error"):
    # OpenAI's error body; its message may quote the request, so it must never reach a log line.
    return fake_response(status, {"error": {"message": "You said: secret words", "type": "server_error", "code": code}})


@pytest.fixture
def post(mocker):
    return mocker.patch("apps.whatsapp.agent.provider.requests.post", return_value=response_with(message("Hello")))


@pytest.fixture(autouse=True)
def no_waiting(mocker):
    # The one retry waits a moment first; not in tests.
    return mocker.patch("apps.whatsapp.agent.provider.time.sleep")


def respond(items=None):
    provider = OpenAIProvider(api_key="sk-test", model="gpt-5.1")
    return provider.respond(
        instructions="You help SaaS users.", items=items or [{"role": "user", "content": "hi"}], tools=[TOOL]
    )


class TestTheRequest:
    def test_it_posts_to_the_responses_api_with_the_key_and_a_timeout(self, post):
        respond()

        args, kwargs = post.call_args
        assert args == (RESPONSES_URL,)
        assert RESPONSES_URL == "https://api.openai.com/v1/responses"
        assert kwargs["headers"]["Authorization"] == "Bearer sk-test"
        assert kwargs["timeout"] == 60

    def test_it_sends_the_history_tools_and_store_false(self, post):
        history = [
            {"role": "user", "content": "list my items"},
            {"type": "function_call", "call_id": "call_0", "name": "list_items", "arguments": '{"page": null}'},
            {"type": "function_call_output", "call_id": "call_0", "output": '{"success": true}'},
            {"role": "assistant", "content": "You have none."},
            {"role": "user", "content": "hi"},
        ]

        respond(history)

        assert post.call_args.kwargs["json"] == {
            "model": "gpt-5.1",
            "instructions": "You help SaaS users.",
            "input": history,
            "tools": [TOOL],
            # Nothing is kept by OpenAI; the history lives in our database (D12).
            "store": False,
            # One call at a time, so a write's Confirm is never one of several at once.
            "parallel_tool_calls": False,
        }


class TestTheReply:
    def test_text_comes_back_as_an_assistant_message_for_the_history(self, post):
        post.return_value = response_with(message("You have 3 items."))

        reply = respond()

        assert reply.text == "You have 3 items."
        assert reply.calls == []
        # No OpenAI ids: with store false there's nothing on their side for an id to point at.
        assert reply.items == [{"role": "assistant", "content": "You have 3 items."}]

    def test_a_function_call_comes_back_with_its_call_id(self, post):
        post.return_value = response_with(function_call("list_items", '{"page": 2}'))

        reply = respond()

        assert reply.text == ""
        assert reply.calls == [FunctionCall(call_id="call_1", name="list_items", arguments='{"page": 2}')]
        assert reply.items == [
            {"type": "function_call", "call_id": "call_1", "name": "list_items", "arguments": '{"page": 2}'}
        ]

    def test_reasoning_items_are_left_out(self, post):
        post.return_value = response_with({"type": "reasoning", "id": "rs_1", "summary": []}, message("Done."))

        assert respond().items == [{"role": "assistant", "content": "Done."}]

    def test_a_refusal_is_shown_like_any_answer(self, post):
        refusal = {"type": "message", "role": "assistant", "content": [{"type": "refusal", "refusal": "I can't."}]}
        post.return_value = response_with(refusal)

        assert respond().text == "I can't."


class TestFailures:
    @pytest.mark.parametrize("status", [400, 401, 403, 404])
    def test_a_refused_request_is_a_provider_error_at_once(self, post, status):
        post.return_value = openai_error(status, code="invalid_request")

        with pytest.raises(ProviderError) as error:
            respond()

        assert post.call_count == 1
        assert str(status) in str(error.value)
        assert "invalid_request" in str(error.value)
        # Neither the key nor OpenAI's own words, which may quote the conversation.
        assert "sk-test" not in str(error.value)
        assert "secret words" not in str(error.value)

    @pytest.mark.parametrize("status", [429, 500, 503])
    def test_a_busy_or_failing_openai_is_tried_once_more(self, post, status, no_waiting):
        post.side_effect = [openai_error(status), response_with(message("Hello"))]

        assert respond().text == "Hello"
        assert post.call_count == 2
        no_waiting.assert_called_once()

    @pytest.mark.parametrize("failure", [requests.Timeout("slow"), requests.ConnectionError("no route")])
    def test_a_timeout_or_lost_connection_is_tried_once_more(self, post, failure):
        post.side_effect = [failure, response_with(message("Hello"))]

        assert respond().text == "Hello"

    def test_failing_twice_is_a_provider_error(self, post):
        post.side_effect = [openai_error(500), openai_error(500)]

        with pytest.raises(ProviderError):
            respond()

        assert post.call_count == 2

    def test_a_reply_that_isnt_json_is_a_provider_error(self, post):
        broken = fake_response(200, None)
        broken.json.side_effect = ValueError("not JSON")
        post.return_value = broken

        with pytest.raises(ProviderError):
            respond()

    def test_a_failed_response_is_a_provider_error(self, post):
        post.return_value = response_with(status="failed")

        with pytest.raises(ProviderError):
            respond()


class TestTheConfiguredProvider:
    def test_the_whatsapp_model_is_used_when_set(self, settings):
        settings.OPENAI_API_KEY = "sk-test"
        settings.WHATSAPP_AI_MODEL = "gpt-5.1"
        settings.OPENAI_MODEL = "gpt-3.5-turbo-instruct"

        assert get_provider().model == "gpt-5.1"

    def test_an_empty_whatsapp_model_falls_back_to_openai_model(self, settings):
        settings.OPENAI_API_KEY = "sk-test"
        settings.WHATSAPP_AI_MODEL = ""
        settings.OPENAI_MODEL = "gpt-5.1"

        assert get_provider().model == "gpt-5.1"

    def test_without_a_key_there_is_no_provider(self, settings):
        settings.OPENAI_API_KEY = ""

        assert get_provider() is None
