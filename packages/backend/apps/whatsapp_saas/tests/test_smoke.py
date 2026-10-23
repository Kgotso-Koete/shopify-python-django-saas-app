"""
Smoke test: an organization's first WhatsApp journey through the real stack, the way the web app and
Meta drive it (plan Steps 1.15, 1.17 and 1.18). An admin connects Acme's internal communications
number on the WhatsApp tab, and our Meta app is subscribed to it -> its forms are published -> a team
member gets a link code on the profile page -> "link <code>" arrives in a webhook signed with our
app's secret -> the menus, in Acme -> the item form -> Confirm -> the item exists, and every reply
went out through the ordered send queue.

Nothing calls Meta for sending: WHATSAPP_SEND_BACKEND is "LOG", so replies are stored and marked sent
with "log." ids. Meta's check of the number and its subscription, when it's connected, are mocked. The Celery tasks' .delay
runs each task at once, in the test's own transaction (agents.md section 2.6); URL routing,
signatures, permissions, the router, the menus, the forms, confirmations and the queue are all real.

Kind of test: smoke (agents.md section 2.5). Why: one whole journey across GraphQL and the webhook,
through the real stack; only Celery's queueing is replaced, by running each task at once, and
Meta's answers when the number is connected are mocked.
"""

import hashlib
import hmac
import json

import pytest
from graphql_relay import to_global_id

from apps.demo.models import CrudDemoItem
from apps.multitenancy.constants import TenantType, TenantUserRole
from apps.multitenancy.tests.factories import TenantFactory, TenantMembershipFactory
from apps.users.tests.factories import UserFactory
from apps.whatsapp import tasks
from apps.whatsapp.constants import MessageDirection, MessageStatus
from apps.whatsapp.models import WhatsAppAccount, WhatsAppFlow, WhatsAppIdentity, WhatsAppMessage
from apps.whatsapp.tests import payloads
from apps.whatsapp.tests.fakes import meta_response

from .. import tasks as saas_tasks
from ..flows import SCREEN_NAMES
from .chat import Screen

pytestmark = pytest.mark.django_db

WEBHOOK_URL = "/api/whatsapp/webhook/"
APP_SECRET = "our-app-secret"

CONNECT = """
mutation ($input: ConnectWhatsAppAccountInput!) {
  connectWhatsAppAccount(input: $input) { account { id purpose subscribedAt } }
}
"""
START_LINK = """
mutation ($input: StartWhatsAppLinkInput!) {
  startWhatsAppLink(input: $input) { code link maskedNumber }
}
"""


@pytest.fixture(autouse=True)
def whatsapp_on(settings, mocker):
    settings.WHATSAPP_ENABLED = True
    settings.WHATSAPP_APP_SECRET = APP_SECRET
    settings.WHATSAPP_SEND_BACKEND = "LOG"
    settings.WHATSAPP_DEFAULT_CONVERSATION_MODE = "WHATSAPP_FORM"
    settings.WHATSAPP_GRAPH_API_VERSION = "v26.0"
    # Each task runs at once, as a worker would run it, inside the test's transaction.
    mocker.patch.object(tasks.process_inbound_message, "delay", side_effect=tasks.process_inbound_message)
    mocker.patch.object(tasks.send_queued_messages, "delay", side_effect=tasks.send_queued_messages)
    mocker.patch.object(saas_tasks.publish_forms, "delay", side_effect=saas_tasks.publish_forms)
    # Meta's answers when the form checks the number, and subscribes our app to its business account.
    mocker.patch(
        "apps.whatsapp.client.requests.get",
        return_value=meta_response(
            200, {"display_phone_number": payloads.DISPLAY_PHONE_NUMBER, "verified_name": "Acme Team"}
        ),
    )
    mocker.patch("apps.whatsapp.client.requests.post", return_value=meta_response(200, {"success": True}))


class Meta:
    """Posts what the sender does as Meta's signed webhook, and reads back what they were sent."""

    def __init__(self, client, django_capture_on_commit_callbacks):
        self.client = client
        self.capture = django_capture_on_commit_callbacks
        self.number = 0

    def post(self, message):
        raw_body = json.dumps(payloads.envelope(payloads.messages_change(message))).encode("utf-8")
        signature = "sha256=" + hmac.new(APP_SECRET.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        # The webhook queues the message once its row is committed; the router then queues the replies.
        with self.capture(execute=True):
            response = self.client.post(
                WEBHOOK_URL, data=raw_body, content_type="application/json", HTTP_X_HUB_SIGNATURE_256=signature
            )
        assert response.status_code == 200, response.content

    def next_wamid(self):
        self.number += 1
        return f"wamid.SMOKE{self.number}"

    def text(self, text):
        self.post(payloads.text_message(wamid=self.next_wamid(), text=text))
        return self.screens()

    def press(self, screen, title):
        if screen.has_buttons:
            self.post(payloads.button_reply(wamid=self.next_wamid(), button_id=screen.press(title), title=title))
        else:
            self.post(payloads.list_reply(wamid=self.next_wamid(), row_id=screen.press(title), title=title))
        return self.screens()

    def answer_form(self, screen, **answers):
        response = {"flow_token": screen.flow["flow_token"], **answers}
        self.post(payloads.flow_reply(wamid=self.next_wamid(), response=response))
        return self.screens()

    def screens(self):
        """The replies since the last read, oldest first; every one must have been sent, in order."""
        rows = list(WhatsAppMessage.objects.filter(direction=MessageDirection.OUTBOUND).order_by("pk"))
        for row in rows:
            assert row.status == MessageStatus.SENT, (row.pk, row.status)
            assert row.wamid.startswith("log.")
        WhatsAppMessage.objects.filter(pk__in=[row.pk for row in rows]).delete()
        return [Screen(row.payload) for row in rows]


def test_an_organizations_first_journey_from_connecting_its_number_to_a_confirmed_item(
    graphene_client, client, django_capture_on_commit_callbacks
):
    acme = TenantFactory(type=TenantType.ORGANIZATION, name="Acme")
    acme_id = to_global_id("TenantType", str(acme.pk))
    admin = UserFactory()
    TenantMembershipFactory(user=admin, tenant=acme, role=TenantUserRole.ADMIN)
    manager = UserFactory()
    TenantMembershipFactory(user=manager, tenant=acme, role=TenantUserRole.ADMIN)
    meta = Meta(client, django_capture_on_commit_callbacks)

    # On the WhatsApp tab: the admin connects Acme's internal communications number.
    graphene_client.force_authenticate(admin)
    graphene_client.set_tenant_dependent_context(acme, TenantUserRole.ADMIN)
    connect_input = {
        "tenantId": acme_id,
        "purpose": "INTERNAL_COMMUNICATIONS",
        "phoneNumberId": payloads.PHONE_NUMBER_ID,
        "wabaId": "200000000000001",
        "accessToken": "EAAGacme-access-token",
    }
    with django_capture_on_commit_callbacks(execute=True):
        executed = graphene_client.mutate(CONNECT, variable_values={"input": connect_input})
    assert "errors" not in executed, executed
    assert executed["data"]["connectWhatsAppAccount"]["account"]["subscribedAt"] is not None
    internal = WhatsAppAccount.objects.internal_for(acme)
    # Connecting it published its forms.
    assert {flow.name for flow in WhatsAppFlow.objects.filter(waba_id=internal.waba_id)} == set(SCREEN_NAMES)

    # On the profile page: the manager gets a code for their own phone, on Acme's number.
    graphene_client.force_authenticate(manager)
    executed = graphene_client.mutate(
        START_LINK, variable_values={"input": {"tenantId": acme_id, "phoneNumber": payloads.SENDER_WA_ID}}
    )
    assert "errors" not in executed, executed
    code = executed["data"]["startWhatsAppLink"]["code"]

    # Before linking, the phone gets no reply.
    assert meta.text("hi") == []

    # From that phone, the code links it.
    [linked] = meta.text(f"link {code}")
    assert "now linked" in linked.body
    assert WhatsAppIdentity.objects.get(user=manager).contact.wa_id == payloads.SENDER_WA_ID

    # The menus, in Acme: New item.
    [menu] = meta.text("hi")
    assert "Acme" in menu.body
    [form] = meta.press(menu, "New item")

    # The form's answers come back; nothing is saved before Confirm.
    [question] = meta.answer_form(form, name="Monthly report")
    assert question.body == "Create Monthly report in Acme?"
    assert not CrudDemoItem.objects.filter(name="Monthly report").exists()

    [done] = meta.press(question, "Confirm")
    assert done.body == "Created Monthly report in Acme."
    assert CrudDemoItem.objects.get(name="Monthly report").tenant == acme
