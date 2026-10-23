"""
A fake model for the assistant's tests (test-support code, agents.md section 2.1): it replays
scripted replies in order, and records what each request carried. No test calls OpenAI.
"""

from ..agent.provider import FunctionCall, ProviderReply


def says(text):
    """A reply in words."""
    return ProviderReply(text=text, calls=[], items=[{"role": "assistant", "content": text}])


def calls(name, arguments, call_id="call_1"):
    """A reply that calls the tool `name` with `arguments`, a JSON string."""
    call = FunctionCall(call_id=call_id, name=name, arguments=arguments)
    item = {"type": "function_call", "call_id": call_id, "name": name, "arguments": arguments}
    return ProviderReply(text="", calls=[call], items=[item])


class FakeProvider:
    """Replays `replies` in order, recording a copy of what each request carried."""

    def __init__(self, *replies, error=None):
        self.replies = list(replies)
        self.error = error
        self.requests = []

    def respond(self, *, instructions, items, tools):
        self.requests.append({"instructions": instructions, "items": [dict(item) for item in items], "tools": tools})
        if self.error is not None:
            raise self.error
        return self.replies.pop(0)
