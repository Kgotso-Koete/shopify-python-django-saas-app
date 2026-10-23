"""
Helpers for the chat tests (test-support code, agents.md section 2.1): set up a team member texting
their organization's internal communications number (plan Step 1.17), send a message as them,
through the real router, and read the screens that came back.
"""

from apps.multitenancy.constants import TenantUserRole
from apps.whatsapp.constants import MessageDirection, MessageKind
from apps.whatsapp.models import WhatsAppAccount, WhatsAppMessage
from apps.whatsapp.services import router
from apps.whatsapp.tests.factories import ContactFactory, InternalAccountFactory, MessageFactory, link_member


class Screen:
    """
    One reply as the user sees it: its body text, its buttons or list rows as (id, title), the list
    rows' descriptions, its header image if any, and for a form (a Flow message) its parameters.
    """

    def __init__(self, message):
        interactive = message["interactive"]
        self.body = interactive["body"]["text"]
        self.image_url = interactive.get("header", {}).get("image", {}).get("link")
        action = interactive["action"]
        self.flow = action.get("parameters") if interactive["type"] == "flow" else None
        self.descriptions = []
        # Meta reports a press on a button and on a list row differently (button_reply, list_reply).
        self.has_buttons = "buttons" in action
        if "buttons" in action:
            self.options = [(button["reply"]["id"], button["reply"]["title"]) for button in action["buttons"]]
        elif "sections" in action:
            rows = [row for section in action["sections"] for row in section["rows"]]
            self.options = [(row["id"], row["title"]) for row in rows]
            self.descriptions = [row.get("description", "") for row in rows]
        else:
            self.options = []

    @property
    def titles(self):
        return [title for _, title in self.options]

    def press(self, title):
        [choice_id] = [choice_id for choice_id, shown in self.options if shown == title]
        return choice_id


def send(contact, text=None, *, press=None, form_answers=None) -> list[Screen]:
    """
    Route one message from `contact` (typed text, a press on a choice id, or a completed form's
    answers, flow_token included) and return the screens it got, oldest first.
    """
    if form_answers is not None:
        payload = {"text": "", "action_id": "", "flow_response": form_answers}
        message = MessageFactory(contact=contact, kind=MessageKind.FLOW_REPLY, payload=payload)
    elif press is not None:
        payload = {"text": "", "action_id": press, "flow_response": {}}
        message = MessageFactory(contact=contact, kind=MessageKind.LIST_REPLY, payload=payload)
    else:
        payload = {"text": text, "action_id": "", "flow_response": {}}
        message = MessageFactory(contact=contact, payload=payload)
    router.route(message.pk)
    rows = WhatsAppMessage.objects.filter(contact=contact, direction=MessageDirection.OUTBOUND).order_by("pk")
    screens = [Screen(row.payload) for row in rows]
    rows.delete()
    return screens


def team_member(tenant, user=None, role=TenantUserRole.ADMIN):
    """
    `user` (a new one by default) as a member of `tenant` with `role`, texting the organization's
    internal number (created if it has none) from a linked phone. Returns their contact.
    """
    internal = WhatsAppAccount.objects.internal_for(tenant) or InternalAccountFactory(tenant=tenant)
    contact = ContactFactory(account=internal)
    link_member(contact, user, role=role)
    return contact


def main_menu(contact):
    """The main menu, which works in the number's organization."""
    [menu] = send(contact, "hi")
    return menu
