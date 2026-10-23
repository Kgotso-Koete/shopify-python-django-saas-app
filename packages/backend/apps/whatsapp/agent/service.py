"""
One message in agentic mode, from the user's words to a reply (plan Step 1.13, decisions D11 and
D12, user story 8).

The model is asked with the history and the handler's tools. Each function call it makes is run (or
refused) and its output added, and the model is asked again, until it answers in words. Three
things end the turn early:
- a write: its tool asks the user to confirm, and that question is the reply, so what the user
  confirms is the server's own summary, never the model's (D11)
- more tool calls than WHATSAPP_AI_MAX_TOOL_CALLS
- OpenAI failing, or no OpenAI key; the handler shows the AgentError's text with its main menu

Every function call gets its output in the history, even when refused or over the cap, because a
call without one would make every later request fail.
"""

import json
import logging

from django.conf import settings

from ..builders import text_reply
from . import history
from .provider import ProviderError, get_provider
from .tools import ToolResult, Toolset, refused

logger = logging.getLogger(__name__)

NOT_SET_UP_TEXT = "The assistant isn't set up on this service yet. Send *mode menu* to use the menus instead."
UNAVAILABLE_TEXT = (
    "Sorry, the assistant isn't available right now. Try again in a moment, or send *mode menu* to use "
    "the menus. Send *cancel* to start the conversation afresh."
)
TOO_MANY_STEPS_TEXT = (
    "Sorry, that took too many steps. Try asking for one thing at a time, or send *mode menu* to use the menus."
)
NO_ANSWER_TEXT = "Sorry, I don't have an answer for that. Send *mode menu* to use the menus instead."


class AgentError(Exception):
    """The assistant couldn't answer; the message is for the user."""


def respond(turn, text: str, *, tools: Toolset, instructions: str) -> list[dict]:
    """The reply to `text`, with the model calling `tools`; raises AgentError when it can't."""
    provider = get_provider()
    if provider is None:
        raise AgentError(NOT_SET_UP_TEXT)

    conversation = turn.conversation
    history.append(conversation, {"role": "user", "content": text})
    calls_made = 0
    while True:
        try:
            reply = provider.respond(
                instructions=instructions, items=history.recent(conversation), tools=tools.schemas()
            )
        except ProviderError as error:
            # The error's type only: never the conversation's words.
            logger.warning("The WhatsApp assistant's provider failed: %s", error)
            raise AgentError(UNAVAILABLE_TEXT) from error
        for item in reply.items:
            history.append(conversation, item)
        if not reply.calls:
            return text_reply(reply.text or NO_ANSWER_TEXT)

        ending = None
        for call in reply.calls:
            calls_made += 1
            if calls_made > settings.WHATSAPP_AI_MAX_TOOL_CALLS:
                result = refused("Too many tool calls for one message.")
            elif ending is not None:
                result = refused("Not run: the user is confirming another action first.")
            else:
                result = tools.run(turn, call.name, call.arguments)
            _add_output(conversation, call.call_id, result)
            if result.messages and ending is None:
                ending = result.messages
        if ending is not None:
            return ending
        if calls_made > settings.WHATSAPP_AI_MAX_TOOL_CALLS:
            raise AgentError(TOO_MANY_STEPS_TEXT)


def _add_output(conversation, call_id: str, result: ToolResult) -> None:
    history.append(
        conversation, {"type": "function_call_output", "call_id": call_id, "output": json.dumps(result.output)}
    )
