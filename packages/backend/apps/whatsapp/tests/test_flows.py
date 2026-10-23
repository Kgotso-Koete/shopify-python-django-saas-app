"""
Tests for opening a WhatsApp Flow form and reading its answers in apps/whatsapp/services/flows.py
(plan Step 1.11b, decision D9).

A form is sent pre-filled (flow_action "navigate", builders.flow_message), and what it's for stays on
the server: the flow_token is a signed, expiring reference to a pending form stored in that
contact's conversation, never data. The answers come back in an nfm_reply whose response_json holds
the form's payload and the flow_token (https://developers.facebook.com/docs/whatsapp/flows/guides/sendingaflow).
- an expired, tampered or other contact's token finds nothing
- a form is answered once
- a form that isn't published says so, rather than sending a broken message

Kind of test: integration (agents.md section 2.5). Why: published flows and conversations are rows in
the test database; nothing is faked.
"""

from datetime import datetime, timedelta, timezone

import pytest

from ..models import WhatsAppConversation
from ..services import flows
from ..services.flows import FormExpired, FormNotAvailable
from ..services.router import Turn
from .factories import ContactFactory, MessageFactory, InternalAccountFactory

pytestmark = pytest.mark.django_db

NOW = datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def settings_for_forms(settings):
    settings.WHATSAPP_SEND_BACKEND = "LOG"
    settings.WHATSAPP_CONVERSATION_TTL_SECONDS = 1800


@pytest.fixture
def account():
    account = InternalAccountFactory(waba_id="200000000000001")
    flows.publish(account, "item", '{"version": "7.2", "screens": []}')
    return account


def turn_for(contact):
    conversation, _ = WhatsAppConversation.objects.get_or_create(contact=contact)
    return Turn(message=MessageFactory(contact=contact), contact=contact, conversation=conversation, user=None, mode="")


def open_item_form(turn):
    return flows.open_form(
        turn,
        form="item",
        screen="ITEM",
        data={"heading": "Create an item", "name": ""},
        body="Fill in the form to create an item.",
        cta="Create item",
        kind="item.form",
        context={"tenant_id": "Ab1Cd2"},
    )


def token_of(messages):
    return messages[0]["interactive"]["action"]["parameters"]["flow_token"]


class TestOpening:
    def test_the_published_form_is_sent_pre_filled(self, account):
        turn = turn_for(ContactFactory(account=account))

        [message] = open_item_form(turn)

        parameters = message["interactive"]["action"]["parameters"]
        assert parameters["flow_id"] == flows.flow_id_for(account, "item")
        assert parameters["flow_action"] == "navigate"
        assert parameters["flow_action_payload"] == {
            "screen": "ITEM",
            "data": {"heading": "Create an item", "name": ""},
        }
        assert parameters["flow_cta"] == "Create item"

    def test_the_token_is_a_reference_not_data(self, account):
        turn = turn_for(ContactFactory(account=account))

        token = token_of(open_item_form(turn))

        # What the form is for stays on the server.
        assert "Ab1Cd2" not in token
        assert "item.form" not in token

    def test_a_form_that_isnt_published_says_so(self, account):
        turn = turn_for(ContactFactory(account=account))

        with pytest.raises(FormNotAvailable):
            flows.open_form(
                turn,
                form="organization",
                screen="ORGANIZATION",
                data={"name": ""},
                body="b",
                cta="c",
                kind="k",
                context={},
            )


class TestAnswering:
    def test_the_answers_come_back_with_what_the_form_was_for(self, account):
        turn = turn_for(ContactFactory(account=account))
        token = token_of(open_item_form(turn))

        kind, context, answers = flows.read_answers(turn, {"flow_token": token, "name": "Monthly report"})

        assert kind == "item.form"
        assert context == {"tenant_id": "Ab1Cd2"}
        assert answers == {"name": "Monthly report"}

    def test_a_form_is_answered_once(self, account):
        turn = turn_for(ContactFactory(account=account))
        token = token_of(open_item_form(turn))
        flows.read_answers(turn, {"flow_token": token, "name": "Monthly report"})

        with pytest.raises(FormExpired):
            flows.read_answers(turn, {"flow_token": token, "name": "Again"})

    def test_a_tampered_token_finds_nothing(self, account):
        turn = turn_for(ContactFactory(account=account))
        token = token_of(open_item_form(turn))

        with pytest.raises(FormExpired):
            flows.read_answers(turn, {"flow_token": token[:-2] + "xx", "name": "Monthly report"})

    def test_a_missing_token_finds_nothing(self, account):
        turn = turn_for(ContactFactory(account=account))

        with pytest.raises(FormExpired):
            flows.read_answers(turn, {"name": "Monthly report"})

    def test_an_expired_token_finds_nothing(self, account, freezer):
        freezer.move_to(NOW)
        turn = turn_for(ContactFactory(account=account))
        token = token_of(open_item_form(turn))
        freezer.move_to(NOW + timedelta(seconds=1801))

        with pytest.raises(FormExpired):
            flows.read_answers(turn, {"flow_token": token, "name": "Monthly report"})

    def test_another_contacts_token_finds_nothing(self, account):
        theirs = turn_for(ContactFactory(account=account))
        token = token_of(open_item_form(theirs))
        mine = turn_for(ContactFactory(account=account))

        with pytest.raises(FormExpired):
            flows.read_answers(mine, {"flow_token": token, "name": "Monthly report"})
