"""
Tests for the WhatsApp webhook, /api/whatsapp/webhook/ (plan Step 1.3c, decisions D6 and D7, Step 1.18).

Meta's rules for it: https://developers.facebook.com/docs/graph-api/webhooks/getting-started
- GET is the subscription check: hub.mode=subscribe, hub.verify_token and hub.challenge, answered
  with the challenge only when the token is our Meta app's, WHATSAPP_VERIFY_TOKEN.
- POST carries events, signed with X-Hub-Signature-256 over the raw body, with our Meta app's App
  secret, WHATSAPP_APP_SECRET, whichever organization's number they're for. Nothing is stored before
  the signature passes.
- Meta retries anything but a 200 for days, so a signed body that can never succeed still gets a 200:
  https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/overview.md

Kind of test: integration (agents.md section 2.5). Why: requests go through the real route with
Django's test client, against the test database; the Celery task's delay is patched, and Meta is
simulated by signed posts.
"""

import hashlib
import hmac
import json

import pytest

from ..constants import MessageDirection, MessageKind, MessageStatus
from ..models import WhatsAppAccount, WhatsAppContact, WhatsAppMessage
from ..normalize import MalformedWebhook
from . import payloads
from .factories import ContactFactory, ExternalAccountFactory, InternalAccountFactory, MessageFactory

pytestmark = pytest.mark.django_db

WEBHOOK_URL = "/api/whatsapp/webhook/"
APP_SECRET = "our-app-secret"
VERIFY_TOKEN = "our-verify-token"
# Beta's external number, on our Meta app like every other.
BETA_PHONE_NUMBER_ID = "100000000000902"


@pytest.fixture(autouse=True)
def whatsapp_on(settings):
    """WhatsApp switched on, with our Meta app's App secret and verify token."""
    settings.WHATSAPP_ENABLED = True
    settings.WHATSAPP_APP_SECRET = APP_SECRET
    settings.WHATSAPP_VERIFY_TOKEN = VERIFY_TOKEN


@pytest.fixture
def acme_account():
    return InternalAccountFactory(phone_number_id=payloads.PHONE_NUMBER_ID)


@pytest.fixture
def beta_account():
    return ExternalAccountFactory(phone_number_id=BETA_PHONE_NUMBER_ID)


@pytest.fixture
def delay(mocker):
    """The Celery task's .delay, replaced so tests can see what was queued without a worker."""
    return mocker.patch("apps.whatsapp.views.process_inbound_message.delay")


def sign(raw_body: bytes, secret: str) -> str:
    """The X-Hub-Signature-256 header Meta would send for `raw_body` signed with `secret`."""
    return "sha256=" + hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()


def post_signed(client, body, secret=APP_SECRET):
    """POST `body` as Meta would: raw JSON bytes plus their signature."""
    raw_body = json.dumps(body).encode("utf-8")
    return client.post(
        WEBHOOK_URL,
        data=raw_body,
        content_type="application/json",
        HTTP_X_HUB_SIGNATURE_256=sign(raw_body, secret),
    )


def subscription_check(client, token, mode="subscribe"):
    return client.get(WEBHOOK_URL, {"hub.mode": mode, "hub.verify_token": token, "hub.challenge": "1158201444"})


class TestSwitchedOff:
    def test_the_webhook_does_not_exist_when_whatsapp_is_off(self, client, settings, acme_account, delay):
        # A stray webhook must change nothing on a deployment that doesn't use WhatsApp.
        settings.WHATSAPP_ENABLED = False
        body = payloads.envelope(payloads.messages_change(payloads.text_message()))

        assert subscription_check(client, VERIFY_TOKEN).status_code == 404
        assert post_signed(client, body).status_code == 404
        assert WhatsAppMessage.objects.count() == 0


class TestSubscriptionCheck:
    def test_our_token_gets_the_challenge_back(self, client):
        response = subscription_check(client, VERIFY_TOKEN)

        assert response.status_code == 200
        # Meta expects exactly the challenge, as plain text.
        assert response.content == b"1158201444"
        assert response["Content-Type"].startswith("text/plain")

    def test_a_wrong_token_is_refused(self, client):
        assert subscription_check(client, "not-a-token-we-issued").status_code == 403

    def test_without_a_token_set_nothing_passes(self, client, settings):
        # An empty setting must not match an empty token from a forged GET.
        settings.WHATSAPP_VERIFY_TOKEN = ""

        assert subscription_check(client, "").status_code == 403

    def test_a_mode_other_than_subscribe_is_refused(self, client):
        assert subscription_check(client, VERIFY_TOKEN, mode="unsubscribe").status_code == 403

    def test_other_methods_are_not_allowed(self, client):
        assert client.put(WEBHOOK_URL).status_code == 405


class TestStoringMessages:
    def test_a_signed_text_message_is_stored_and_queued_after_commit(
        self, client, acme_account, delay, django_capture_on_commit_callbacks
    ):
        with django_capture_on_commit_callbacks(execute=True) as callbacks:
            response = post_signed(client, payloads.envelope(payloads.messages_change(payloads.text_message())))

        assert response.status_code == 200

        contact = WhatsAppContact.objects.get(account=acme_account)
        assert contact.bsuid == payloads.SENDER_BSUID
        assert contact.wa_id == payloads.SENDER_WA_ID
        assert contact.profile_name == payloads.SENDER_NAME

        message = WhatsAppMessage.objects.get(contact=contact)
        assert message.direction == MessageDirection.INBOUND
        assert message.wamid == "wamid.TEXT1"
        assert message.kind == MessageKind.TEXT
        assert message.status == MessageStatus.RECEIVED
        assert message.payload == {"text": "Hi", "action_id": "", "flow_response": {}}

        # Queued only once the transaction committed, so the worker can't look for a row that
        # isn't there yet (D7).
        assert len(callbacks) == 1
        delay.assert_called_once_with(message.pk)

    def test_two_organizations_numbers_in_one_body_are_both_stored(
        self, client, acme_account, beta_account, delay, django_capture_on_commit_callbacks
    ):
        # One Meta app, one secret: a body may carry several numbers' events.
        body = payloads.envelope(
            payloads.messages_change(payloads.text_message(wamid="wamid.A")),
            payloads.messages_change(payloads.text_message(wamid="wamid.B"), phone_number_id=BETA_PHONE_NUMBER_ID),
        )

        with django_capture_on_commit_callbacks(execute=True):
            assert post_signed(client, body).status_code == 200

        assert WhatsAppMessage.objects.get(wamid="wamid.A").contact.account == acme_account
        assert WhatsAppMessage.objects.get(wamid="wamid.B").contact.account == beta_account

    def test_the_same_message_posted_twice_is_stored_and_queued_once(
        self, client, acme_account, delay, django_capture_on_commit_callbacks
    ):
        body = payloads.envelope(payloads.messages_change(payloads.text_message(wamid="wamid.RETRIED")))

        with django_capture_on_commit_callbacks(execute=True):
            assert post_signed(client, body).status_code == 200
            # Meta's retry: acknowledged, but not stored or queued a second time.
            assert post_signed(client, body).status_code == 200

        assert WhatsAppMessage.objects.filter(wamid="wamid.RETRIED").count() == 1
        delay.assert_called_once()

    def test_an_unsupported_message_is_stored_and_queued(
        self, client, acme_account, delay, django_capture_on_commit_callbacks
    ):
        # Queued too, so the sender can be told this kind of message isn't supported yet.
        with django_capture_on_commit_callbacks(execute=True):
            post_signed(client, payloads.envelope(payloads.messages_change(payloads.sticker_message())))

        message = WhatsAppMessage.objects.get(wamid="wamid.STICKER1")
        assert message.kind == MessageKind.UNSUPPORTED
        assert message.payload == {"message_type": "sticker"}
        delay.assert_called_once_with(message.pk)


class TestSignatures:
    def test_a_bad_signature_is_refused_and_nothing_is_stored(self, client, acme_account, delay):
        response = post_signed(
            client, payloads.envelope(payloads.messages_change(payloads.text_message())), secret="wrong-secret"
        )

        assert response.status_code == 403
        assert WhatsAppContact.objects.count() == 0
        assert WhatsAppMessage.objects.count() == 0
        delay.assert_not_called()

    def test_a_missing_signature_is_refused(self, client, acme_account, delay):
        raw_body = json.dumps(payloads.envelope(payloads.messages_change(payloads.text_message()))).encode("utf-8")

        response = client.post(WEBHOOK_URL, data=raw_body, content_type="application/json")

        assert response.status_code == 403
        assert WhatsAppMessage.objects.count() == 0

    def test_without_a_secret_set_nothing_passes(self, client, settings, acme_account, delay):
        settings.WHATSAPP_APP_SECRET = ""
        body = payloads.envelope(payloads.messages_change(payloads.text_message()))

        assert post_signed(client, body, secret="").status_code == 403
        assert WhatsAppMessage.objects.count() == 0


class TestStatuses:
    def test_a_status_updates_the_message_we_sent(self, client, acme_account, delay):
        sent = MessageFactory(
            contact=ContactFactory(account=acme_account),
            direction=MessageDirection.OUTBOUND,
            wamid="wamid.SENT1",
            status=MessageStatus.SENT,
        )

        # 131047: the 24-hour window had closed.
        failed = payloads.status(wamid="wamid.SENT1", state="failed", error_code=131047)
        post_signed(client, payloads.envelope(payloads.statuses_change(failed)))

        sent.refresh_from_db()
        assert sent.status == MessageStatus.FAILED
        assert sent.error_code == 131047
        # A status is a report about our own message, never something to act on.
        delay.assert_not_called()

    def test_a_status_for_a_message_we_never_sent_is_ignored(self, client, acme_account, delay):
        never_sent = payloads.status(wamid="wamid.UNKNOWN")
        response = post_signed(client, payloads.envelope(payloads.statuses_change(never_sent)))

        assert response.status_code == 200
        assert WhatsAppMessage.objects.count() == 0


class TestBodiesWeCannotUse:
    def test_a_number_not_connected_here_is_acknowledged_but_not_stored(self, client, delay):
        # A number on our Meta app that no organization connected: nothing to store it under, and a
        # retry would never get better.
        body = payloads.envelope(payloads.messages_change(payloads.text_message(), phone_number_id="100000000000999"))

        assert post_signed(client, body).status_code == 200
        assert WhatsAppMessage.objects.count() == 0
        assert WhatsAppAccount.objects.count() == 0
        delay.assert_not_called()

    def test_a_disconnected_numbers_events_are_acknowledged_but_never_stored(self, client, beta_account, delay):
        # Disconnecting (plan Step 1.5) marks the account inactive; from then on its number is
        # treated as one we don't know (user story 11).
        beta_account.is_active = False
        beta_account.save()
        body = payloads.envelope(
            payloads.messages_change(payloads.text_message(wamid="wamid.GONE"), phone_number_id=BETA_PHONE_NUMBER_ID)
        )

        assert post_signed(client, body).status_code == 200
        assert WhatsAppMessage.objects.count() == 0
        delay.assert_not_called()

    def test_a_body_that_is_not_json_is_a_bad_request(self, client, delay):
        raw_body = b"this is not json"

        response = client.post(
            WEBHOOK_URL,
            data=raw_body,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=sign(raw_body, APP_SECRET),
        )

        assert response.status_code == 400

    def test_a_signed_but_malformed_body_is_acknowledged_so_meta_stops_retrying(self, client, delay):
        malformed = {"object": "whatsapp_business_account"}

        assert post_signed(client, malformed).status_code == 200
        assert post_signed(client, malformed, secret="some-other-secret").status_code == 403
        assert WhatsAppMessage.objects.count() == 0

    def test_a_signed_body_that_cannot_be_read_is_acknowledged(self, client, acme_account, delay, mocker):
        mocker.patch("apps.whatsapp.views.normalize_webhook", side_effect=MalformedWebhook("bad"))

        response = post_signed(client, payloads.envelope(payloads.messages_change(payloads.text_message())))

        assert response.status_code == 200
        assert WhatsAppMessage.objects.count() == 0
