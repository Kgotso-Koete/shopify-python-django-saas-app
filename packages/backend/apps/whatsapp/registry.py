"""
The handler registry (plan decision D1): which app answers a number, by the number's purpose.

The channel (apps.whatsapp) never imports what users can do in chat. apps.whatsapp_saas registers
the internal communications numbers' handler, and phase 2's apps.whatsapp_shop the external
communications numbers', each from its AppConfig.ready(), the way apps register permissions through apps/<app>/permissions.py.
Deleting either app leaves the other working (agents.md section 3.1).

A handler is any object with these methods, each returning the messages to queue (builders.py
output) for one inbound message, described by a router.Turn:
- main_menu(turn)
- on_choice(turn, kind, data): a button or list row the handler offered with turn.choice(kind, **data)
- on_free_text(turn, text): free text in agentic mode (the assistant, Step 1.13)
- on_flow_reply(turn, response): a completed WhatsApp Flow (Step 1.11)
- on_typed_answer(turn, kind, data, text): the text it asked for with turn.expect_text(kind, **data)
  (Step 1.12b)

and, optionally, on_connected(account): called once a number of its purpose is connected and saved,
to set it up, e.g. publish the handler's forms to it (Step 1.17).
"""

_handlers = {}


def register_handler(purpose: str, handler) -> None:
    """Make `handler` answer every number with this AccountPurpose; None removes it."""
    if handler is None:
        _handlers.pop(purpose, None)
    else:
        _handlers[purpose] = handler


def unregister_handler(purpose: str) -> None:
    _handlers.pop(purpose, None)


def handler_for(purpose: str):
    """The handler for numbers with this purpose, or None while no app has registered one."""
    return _handlers.get(purpose)
