"""
Tests for apps/whatsapp/normalize.py, which turns Meta's nested webhook body into simple, typed
events, so nothing downstream digs through JSON.

The payloads come from tests/payloads.py, which follows Meta's webhook reference (links there).

Kind of test: unit (agents.md section 2.5). Why: a plain function over JSON bodies built locally,
with no database or network; nothing is faked.
"""

from datetime import datetime, timezone

import pytest

from ..constants import MessageKind
from ..normalize import (
    DeliveryStatus,
    InboundMessage,
    MalformedWebhook,
    UnsupportedMessage,
    normalize_webhook,
    receiving_phone_number_ids,
)
from . import payloads

# The root conftest.py registers fixtures whose autouse parts need the database.
pytestmark = pytest.mark.django_db

# payloads.TIMESTAMP as an aware datetime.
SENT_AT = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)


class TestInboundMessages:
    def test_a_text_message(self):
        events = normalize_webhook(payloads.envelope(payloads.messages_change(payloads.text_message(text="Hi there"))))

        assert events == [
            InboundMessage(
                wamid="wamid.TEXT1",
                phone_number_id=payloads.PHONE_NUMBER_ID,
                bsuid=payloads.SENDER_BSUID,
                wa_id=payloads.SENDER_WA_ID,
                profile_name=payloads.SENDER_NAME,
                kind=MessageKind.TEXT,
                text="Hi there",
                action_id="",
                flow_response={},
                sent_at=SENT_AT,
            )
        ]

    def test_a_button_reply_carries_the_button_id(self):
        [event] = normalize_webhook(payloads.envelope(payloads.messages_change(payloads.button_reply(button_id="c7"))))

        assert event.kind == MessageKind.BUTTON_REPLY
        assert event.action_id == "c7"
        # The button's label is kept as the text, for history and logs.
        assert event.text == "Main menu"

    def test_a_list_reply_carries_the_row_id(self):
        [event] = normalize_webhook(payloads.envelope(payloads.messages_change(payloads.list_reply(row_id="c2"))))

        assert event.kind == MessageKind.LIST_REPLY
        assert event.action_id == "c2"
        assert event.text == "Acme"

    def test_a_flow_reply_has_its_response_json_parsed(self):
        response = {"flow_token": "signed-token", "name": "Acme Ltd"}

        [event] = normalize_webhook(payloads.envelope(payloads.messages_change(payloads.flow_reply(response=response))))

        assert event.kind == MessageKind.FLOW_REPLY
        # Meta sends response_json as a JSON string; it comes out as a dict.
        assert event.flow_response == response

    def test_a_sender_without_a_phone_number_keeps_their_business_scoped_user_id(self):
        # Meta omits `from` and `wa_id` for some users with usernames (plan section 6.1).
        message = payloads.text_message(wa_id="")
        change = payloads.messages_change(message, contacts=[payloads.contact(wa_id="")])

        [event] = normalize_webhook(payloads.envelope(change))

        assert event.bsuid == payloads.SENDER_BSUID
        assert event.wa_id == ""

    def test_the_profile_name_comes_from_the_matching_contact(self):
        # Two senders in one change: each message gets its own sender's name.
        first = payloads.text_message(wamid="wamid.A", bsuid="ZA.1", wa_id="27000001001")
        second = payloads.text_message(wamid="wamid.B", bsuid="ZA.2", wa_id="27000001002")
        contacts = [
            payloads.contact(bsuid="ZA.1", wa_id="27000001001", name="Thandi"),
            payloads.contact(bsuid="ZA.2", wa_id="27000001002", name="Sipho"),
        ]

        events = normalize_webhook(payloads.envelope(payloads.messages_change(first, second, contacts=contacts)))

        assert [event.profile_name for event in events] == ["Thandi", "Sipho"]


class TestStatusesAndOtherEvents:
    def test_a_status_update_is_its_own_type_never_a_message(self):
        [event] = normalize_webhook(payloads.envelope(payloads.statuses_change(payloads.status(state="read"))))

        assert event == DeliveryStatus(
            wamid="wamid.SENT1",
            phone_number_id=payloads.PHONE_NUMBER_ID,
            state="read",
            error_code=None,
            occurred_at=SENT_AT,
        )

    def test_a_failed_status_carries_its_error_code(self):
        # 131047: the 24-hour window had closed (plan section 6.1).
        [event] = normalize_webhook(
            payloads.envelope(payloads.statuses_change(payloads.status(state="failed", error_code=131047)))
        )

        assert event.state == "failed"
        assert event.error_code == 131047

    def test_a_message_type_we_dont_handle_is_kept_as_unsupported(self):
        # Never silently dropped: it's recorded, so the sender can be told it isn't supported yet.
        [event] = normalize_webhook(payloads.envelope(payloads.messages_change(payloads.sticker_message())))

        assert event == UnsupportedMessage(
            wamid="wamid.STICKER1",
            phone_number_id=payloads.PHONE_NUMBER_ID,
            bsuid=payloads.SENDER_BSUID,
            wa_id=payloads.SENDER_WA_ID,
            message_type="sticker",
            sent_at=SENT_AT,
        )

    def test_a_change_for_another_field_is_ignored(self):
        account_update = {"field": "account_update", "value": {"event": "VERIFIED_ACCOUNT"}}

        assert normalize_webhook(payloads.envelope(account_update)) == []


class TestBatches:
    def test_every_entry_change_and_message_in_one_body_comes_out_in_order(self):
        # Meta may batch several events into one POST; the reference app only ever read the first.
        body = payloads.envelope(
            payloads.messages_change(payloads.text_message(wamid="wamid.1"), payloads.text_message(wamid="wamid.2")),
            payloads.statuses_change(payloads.status(wamid="wamid.3")),
        )
        # A second entry: another WhatsApp Business account's events in the same POST.
        second_entry = payloads.envelope(payloads.messages_change(payloads.text_message(wamid="wamid.4")))["entry"][0]
        body["entry"].append(second_entry)

        assert [event.wamid for event in normalize_webhook(body)] == ["wamid.1", "wamid.2", "wamid.3", "wamid.4"]

    def test_every_receiving_number_in_a_body_is_collected(self):
        # The view uses these to choose the secret that checks the signature (D6).
        body = payloads.envelope(
            payloads.messages_change(payloads.text_message(), phone_number_id="100000000000001"),
            payloads.statuses_change(payloads.status(), phone_number_id="100000000000002"),
            {"field": "account_update", "value": {}},
        )

        assert receiving_phone_number_ids(body) == {"100000000000001", "100000000000002"}


class TestMalformedBodies:
    @pytest.mark.parametrize(
        "body",
        [
            [],  # not an object
            {"object": "whatsapp_business_account"},  # no entry list
            {"entry": [{"changes": [{"field": "messages", "value": {"messages": []}}]}]},  # no metadata
        ],
        ids=["not-an-object", "no-entry", "no-metadata"],
    )
    def test_a_malformed_body_raises_a_clear_error(self, body):
        with pytest.raises(MalformedWebhook):
            normalize_webhook(body)

    def test_a_message_without_a_business_scoped_user_id_is_malformed(self):
        # Meta includes from_user_id in every incoming message, and contacts are keyed on it (D4).
        message = payloads.text_message()
        del message["from_user_id"]
        change = payloads.messages_change(message, contacts=[{"profile": {"name": "Thandi"}, "wa_id": "27000001001"}])

        with pytest.raises(MalformedWebhook):
            normalize_webhook(payloads.envelope(change))
