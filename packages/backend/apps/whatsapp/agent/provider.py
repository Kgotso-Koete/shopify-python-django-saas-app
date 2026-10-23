"""
The assistant's model: one call to OpenAI's Responses API, as a plain HTTP request (plan Step 1.13,
decision D12; no SDK, agents.md section 5.3a).

- the history goes as input items, and store: false keeps OpenAI from storing anything
- tools are strict function tools, called one at a time (parallel_tool_calls: false)
- the reply's messages and function calls come back as input items to send next time, without
  OpenAI's ids, since with store: false there's nothing on their side for an id to point at;
  reasoning items are left out for the same reason
- a timeout, a lost connection, a 429 or a 5xx is tried once more after a short pause; every
  failure becomes a ProviderError naming only the HTTP status and OpenAI's error code, never the
  key or OpenAI's message, which may quote the conversation

Responses API: https://developers.openai.com/api/docs/api-reference/responses/create
Function calling: https://developers.openai.com/api/docs/guides/function-calling
Conversation state and store: https://developers.openai.com/api/docs/guides/conversation-state
Error codes: https://developers.openai.com/api/docs/guides/error-codes
"""

import time
from dataclasses import dataclass

import requests
from django.conf import settings

RESPONSES_URL = "https://api.openai.com/v1/responses"
# Seconds to wait for OpenAI: a user is waiting on WhatsApp, and a request without a timeout could
# hang a worker forever.
TIMEOUT_SECONDS = 60
# Seconds before the one retry.
RETRY_PAUSE_SECONDS = 1
# Worth one more try: rate limited, or OpenAI having a bad moment.
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


@dataclass(frozen=True)
class FunctionCall:
    call_id: str
    name: str
    # A JSON object, as the model wrote it; tools.Toolset checks it before anything runs.
    arguments: str


@dataclass(frozen=True)
class ProviderReply:
    text: str
    calls: list[FunctionCall]
    # What to add to the history, as input items.
    items: list[dict]


class ProviderError(Exception):
    """OpenAI couldn't answer: unreachable, refused the request, or the response failed."""


class _Retryable(ProviderError):
    pass


class OpenAIProvider:
    def __init__(self, *, api_key: str, model: str):
        self.model = model
        self._api_key = api_key

    def respond(self, *, instructions: str, items: list[dict], tools: list[dict]) -> ProviderReply:
        body = {
            "model": self.model,
            "instructions": instructions,
            "input": items,
            "tools": tools,
            "store": False,
            "parallel_tool_calls": False,
        }
        try:
            data = self._post(body)
        except _Retryable:
            time.sleep(RETRY_PAUSE_SECONDS)
            data = self._post(body)
        if data.get("status") == "failed":
            raise ProviderError("OpenAI's response failed.")
        return _reply_from(data.get("output") or [])

    def _post(self, body: dict) -> dict:
        try:
            response = requests.post(
                RESPONSES_URL,
                json=body,
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=TIMEOUT_SECONDS,
            )
        except (requests.Timeout, requests.ConnectionError) as error:
            raise _Retryable(f"Couldn't reach OpenAI: {type(error).__name__}") from error
        if not response.ok:
            failure = _Retryable if response.status_code in RETRYABLE_STATUSES else ProviderError
            raise failure(f"OpenAI answered HTTP {response.status_code} ({_error_code(response)})")
        try:
            return response.json()
        except ValueError as error:
            raise ProviderError("OpenAI's answer wasn't JSON.") from error


def get_provider() -> OpenAIProvider | None:
    """The configured provider, or None without an OpenAI key. An empty WHATSAPP_AI_MODEL means OPENAI_MODEL."""
    if not settings.OPENAI_API_KEY:
        return None
    return OpenAIProvider(api_key=settings.OPENAI_API_KEY, model=settings.WHATSAPP_AI_MODEL or settings.OPENAI_MODEL)


def _reply_from(output: list[dict]) -> ProviderReply:
    texts, calls, items = [], [], []
    for entry in output:
        if entry.get("type") == "message":
            text = "".join(_text_of(part) for part in entry.get("content") or [])
            texts.append(text)
            items.append({"role": "assistant", "content": text})
        elif entry.get("type") == "function_call":
            call = FunctionCall(call_id=entry["call_id"], name=entry["name"], arguments=entry["arguments"])
            calls.append(call)
            items.append(
                {"type": "function_call", "call_id": call.call_id, "name": call.name, "arguments": call.arguments}
            )
    return ProviderReply(text="\n\n".join(text for text in texts if text), calls=calls, items=items)


def _text_of(part: dict) -> str:
    """A message part's text: output_text, or a refusal, which is shown like any answer."""
    if part.get("type") == "output_text":
        return part.get("text", "")
    if part.get("type") == "refusal":
        return part.get("refusal", "")
    return ""


def _error_code(response) -> str:
    """OpenAI's error code or type, such as "invalid_api_key": never its message, which may quote the request."""
    try:
        error = response.json()["error"]
        return str(error.get("code") or error.get("type") or "no error code")
    except (ValueError, KeyError, TypeError, AttributeError):
        return "no error body"
