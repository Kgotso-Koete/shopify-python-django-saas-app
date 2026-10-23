"""
The tools a handler gives the assistant (plan Step 1.13, D12), and running them safely.

Each tool is a strict function tool: every argument is required, an optional one allows null, and
nothing else is accepted. OpenAI enforces that on its side; it's checked again here, since a model's
output is never trusted, and a call that doesn't match is refused back to the model without
running. So is a tool that isn't in the list, and a tool that fails, whose details stay in the log.

https://developers.openai.com/api/docs/guides/function-calling
"""

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass

from django.db import transaction

logger = logging.getLogger(__name__)

# The JSON schema types tools may use, and the Python values that match them.
JSON_TYPES = {"string": str, "integer": int, "boolean": bool, "null": type(None)}


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    # Each argument's schema, such as {"type": ["string", "null"]}, by name.
    parameters: dict
    # Called as run(turn, **arguments); returns the output dict for the model, or a ToolResult.
    run: Callable


@dataclass(frozen=True)
class ToolResult:
    output: dict
    # Messages that end the turn, such as a write's Confirm question (D11); None lets the model go on.
    messages: list[dict] | None = None


class Toolset:
    def __init__(self, tools: list[Tool]):
        self._tools = {tool.name: tool for tool in tools}

    def schemas(self) -> list[dict]:
        """The tools as the Responses API takes them."""
        return [
            {
                "type": "function",
                "name": tool.name,
                "description": tool.description,
                "parameters": {
                    "type": "object",
                    "properties": tool.parameters,
                    "required": list(tool.parameters),
                    "additionalProperties": False,
                },
                "strict": True,
            }
            for tool in self._tools.values()
        ]

    def run(self, turn, name: str, arguments: str) -> ToolResult:
        """Run one call, or refuse it; either way there's an output for the model."""
        tool = self._tools.get(name)
        if tool is None:
            return refused(f"There's no tool called {name}.")
        try:
            values = json.loads(arguments)
        except ValueError:
            return refused("The arguments aren't valid JSON.")
        if not isinstance(values, dict):
            return refused("The arguments must be a JSON object.")
        problem = _mismatch(tool.parameters, values)
        if problem:
            return refused(problem)

        try:
            # A savepoint, so a tool that fails halfway leaves the conversation's transaction usable.
            with transaction.atomic():
                result = tool.run(turn, **values)
        except Exception:
            logger.exception("The WhatsApp assistant's tool %s failed", name)
            return refused("That didn't work because of a problem on our side. Suggest trying again later.")
        return result if isinstance(result, ToolResult) else ToolResult(result)


def refused(reason: str) -> ToolResult:
    return ToolResult({"success": False, "error": reason})


def _mismatch(parameters: dict, values: dict) -> str | None:
    """What's wrong with `values` for these parameters, or None when they match exactly."""
    missing = sorted(set(parameters) - set(values))
    extra = sorted(set(values) - set(parameters))
    if missing:
        return f"Missing arguments: {', '.join(missing)}."
    if extra:
        return f"Unknown arguments: {', '.join(extra)}."
    for name, schema in parameters.items():
        allowed = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_is(values[name], json_type) for json_type in allowed):
            return f"{name} must be {' or '.join(allowed)}."
    return None


def _is(value, json_type: str) -> bool:
    if json_type == "integer":
        # True and False are ints in Python, but not integers in JSON.
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, JSON_TYPES[json_type])
