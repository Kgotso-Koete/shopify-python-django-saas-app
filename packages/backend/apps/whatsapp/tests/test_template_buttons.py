"""
Tests for a tap on a template's quick-reply button (WhatsApp plan Step 4.7, decision 30, user story
WA.D5.SC.J1.A2): Meta sends it as a message of type "button", with the payload set when the template was sent.

- it's read as a button press, its payload the action id and its label the text
- its id is the template's, not a choice of the conversation's (those are "c<n>" and "menu"), so the router
  hands any id holding ":" to the handler's on_template_button, however long ago the template went out; a
  handler without one gets the expired menu, as an unknown press does

Kind of test: unit for the reading (normalize_webhook on its own, nothing faked); integration for the routing
(agents.md section 2.5): the contact, conversation and messages are rows in the test database, with a stand-in
handler registered for the number's purpose.
"""

import pytest

from ..constants import MessageKind
from ..normalize import InboundMessage, normalize_webhook
from ..services import router
from . import payloads
from .factories import ContactFactory, ExternalAccountFactory, MessageFactory

pytestmark = [pytest.mark.django_db, pytest.mark.story("WA.D5.SC.J1.A2")]


def test_a_template_buttons_tap_is_read_as_a_press_with_its_payload():
    body = payloads.envelope(payloads.messages_change(payloads.template_button_reply(payload="order:abc")))

    [event] = normalize_webhook(body)

    assert isinstance(event, InboundMessage)
    assert event.kind == MessageKind.BUTTON_REPLY
    assert event.action_id == "order:abc"
    assert event.text == "Order details"


class Handler:
    """A stand-in for a number's handler: records template taps, and offers a main menu."""

    def __init__(self, with_template_buttons=True):
        self.taps = []
        if with_template_buttons:
            self.on_template_button = self._on_template_button

    def _on_template_button(self, turn, action_id):
        self.taps.append(action_id)
        return [{"type": "text", "text": {"body": f"tapped {action_id}", "preview_url": False}}]

    def main_menu(self, turn):
        return [{"type": "text", "text": {"body": "main menu", "preview_url": False}}]


@pytest.fixture
def contact(mocker):
    mocker.patch("apps.whatsapp.tasks.send_queued_messages.delay")
    # The organization's plan includes WhatsApp, so the number answers.
    mocker.patch("apps.whatsapp.services.router.entitlements.has_feature", return_value=True)
    return ContactFactory(account=ExternalAccountFactory())


def press(contact, action_id):
    payload = {"text": "Order details", "action_id": action_id, "flow_response": {}}
    message = MessageFactory(contact=contact, kind=MessageKind.BUTTON_REPLY, payload=payload)
    router.route(message.pk)
    rows = contact.messages.filter(direction="OUTBOUND").order_by("pk")
    # Each reply's text: a plain message's body, or an interactive one's.
    return [row.payload.get("text", {}).get("body") or row.payload["interactive"]["body"]["text"] for row in rows]


def test_the_router_hands_a_template_buttons_tap_to_the_handler(contact, mocker):
    handler = Handler()
    mocker.patch("apps.whatsapp.services.router.registry.handler_for", return_value=handler)

    assert press(contact, "order:abc") == ["tapped order:abc"]
    assert handler.taps == ["order:abc"]


def test_a_handler_without_template_buttons_gets_the_expired_menu(contact, mocker):
    mocker.patch(
        "apps.whatsapp.services.router.registry.handler_for", return_value=Handler(with_template_buttons=False)
    )

    replies = press(contact, "order:abc")

    assert replies == ["That menu has expired, so here's the main menu.", "main menu"]
