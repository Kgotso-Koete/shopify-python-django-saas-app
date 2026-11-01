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
- Since Step 2.9 an organization's own Meta app has its own address, /api/whatsapp/webhook/<public
  id>/, with its own verify token and App secret; each address stores events only for its app's numbers.

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
from .factories import ContactFactory, ExternalAccountFactory, InternalAccountFactory, MessageFactory, MetaAppFactory

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


class TestRefusalsAreLogged:
    """Step 1.22: a 403 says why in the log, without the secret, the signature or the body."""

    LOGGER = "apps.whatsapp.views"

    def refusal_logs(self, caplog):
        return [record for record in caplog.records if record.name == self.LOGGER and record.levelname == "WARNING"]

    def assert_nothing_secret_logged(self, caplog, *values):
        for value in values:
            assert value not in caplog.text

    def test_a_signature_that_does_not_match_is_logged(self, client, acme_account, delay, caplog):
        body = payloads.envelope(payloads.messages_change(payloads.text_message()))
        raw_body = json.dumps(body).encode("utf-8")

        with caplog.at_level("WARNING", logger=self.LOGGER):
            post_signed(client, body, secret="wrong-secret")

        [record] = self.refusal_logs(caplog)
        assert "doesn't match WHATSAPP_APP_SECRET" in record.getMessage()
        self.assert_nothing_secret_logged(caplog, APP_SECRET, sign(raw_body, "wrong-secret"), "wamid.TEXT1")

    def test_a_missing_signature_is_logged(self, client, acme_account, delay, caplog):
        raw_body = json.dumps(payloads.envelope(payloads.messages_change(payloads.text_message()))).encode("utf-8")

        with caplog.at_level("WARNING", logger=self.LOGGER):
            client.post(WEBHOOK_URL, data=raw_body, content_type="application/json")

        [record] = self.refusal_logs(caplog)
        assert "no X-Hub-Signature-256 header" in record.getMessage()
        self.assert_nothing_secret_logged(caplog, APP_SECRET, "wamid.TEXT1")

    def test_an_empty_secret_setting_is_logged(self, client, settings, acme_account, delay, caplog):
        settings.WHATSAPP_APP_SECRET = ""
        body = payloads.envelope(payloads.messages_change(payloads.text_message()))

        with caplog.at_level("WARNING", logger=self.LOGGER):
            post_signed(client, body, secret="")

        [record] = self.refusal_logs(caplog)
        assert "WHATSAPP_APP_SECRET is empty" in record.getMessage()

    def test_an_accepted_post_logs_no_warning(self, client, acme_account, delay, caplog):
        with caplog.at_level("WARNING", logger=self.LOGGER):
            post_signed(client, payloads.envelope(payloads.messages_change(payloads.text_message())))

        assert self.refusal_logs(caplog) == []


class TestAnOrganizationsOwnApp:
    """
    Plan Step 2.9: a number in an organization's own Meta app has its webhooks at that app's address,
    /api/whatsapp/webhook/<public id>/, checked with that app's verify token and App secret; events are
    stored only for the numbers on that app, and the general address stays for this service's app.
    """

    APP_SECRET = "the-organizations-app-secret"

    @pytest.fixture
    def app(self):
        return MetaAppFactory(app_secret=self.APP_SECRET)

    @pytest.fixture
    def number_on_it(self, app):
        return ExternalAccountFactory(tenant=app.tenant, meta_app=app, phone_number_id=payloads.PHONE_NUMBER_ID)

    def url(self, app):
        return f"{WEBHOOK_URL}{app.public_id}/"

    def post(self, client, url, body, secret):
        raw_body = json.dumps(body).encode("utf-8")
        return client.post(
            url, data=raw_body, content_type="application/json", HTTP_X_HUB_SIGNATURE_256=sign(raw_body, secret)
        )

    def check(self, client, url, token):
        return client.get(url, {"hub.mode": "subscribe", "hub.verify_token": token, "hub.challenge": "1158201444"})

    def test_meta_s_check_with_the_apps_token_gets_the_challenge(self, client, app):
        response = self.check(client, self.url(app), app.verify_token)

        assert response.status_code == 200
        assert response.content == b"1158201444"
        assert response["Content-Type"].startswith("text/plain")

    def test_another_token_is_refused_at_each_address(self, client, app):
        assert self.check(client, self.url(app), VERIFY_TOKEN).status_code == 403
        assert self.check(client, WEBHOOK_URL, app.verify_token).status_code == 403

    def test_a_regenerated_token_replaces_the_old_one(self, client, app):
        old = app.verify_token
        app.verify_token = "a-new-verify-token"
        app.save()

        assert self.check(client, self.url(app), old).status_code == 403
        assert self.check(client, self.url(app), "a-new-verify-token").status_code == 200

    def test_an_address_nobody_was_given_is_not_found(self, client, delay):
        url = f"{WEBHOOK_URL}no-such-app-address/"
        body = payloads.envelope(payloads.messages_change(payloads.text_message()))

        assert self.check(client, url, VERIFY_TOKEN).status_code == 404
        assert self.post(client, url, body, APP_SECRET).status_code == 404

    def test_the_address_does_not_exist_when_whatsapp_is_off(self, client, settings, app):
        settings.WHATSAPP_ENABLED = False

        assert self.check(client, self.url(app), app.verify_token).status_code == 404

    def test_a_message_signed_with_the_apps_secret_is_stored_and_queued(
        self, client, app, number_on_it, delay, django_capture_on_commit_callbacks
    ):
        body = payloads.envelope(payloads.messages_change(payloads.text_message()))

        with django_capture_on_commit_callbacks(execute=True):
            response = self.post(client, self.url(app), body, self.APP_SECRET)

        assert response.status_code == 200
        message = WhatsAppMessage.objects.get(wamid="wamid.TEXT1")
        assert message.contact.account == number_on_it
        delay.assert_called_once_with(message.pk)

    def test_another_secret_is_refused_at_each_address_and_nothing_stored(self, client, app, number_on_it, delay):
        body = payloads.envelope(payloads.messages_change(payloads.text_message()))

        # This service's secret at the app's address, and the app's secret at the general one.
        assert self.post(client, self.url(app), body, APP_SECRET).status_code == 403
        assert self.post(client, WEBHOOK_URL, body, self.APP_SECRET).status_code == 403
        assert WhatsAppMessage.objects.count() == 0

    def test_a_number_on_another_app_is_never_stored_from_this_one(
        self, client, app, acme_account, delay, django_capture_on_commit_callbacks
    ):
        # acme_account is on this service's app: a body signed by the organization's app can't speak for it.
        body = payloads.envelope(payloads.messages_change(payloads.text_message()))

        with django_capture_on_commit_callbacks(execute=True):
            assert self.post(client, self.url(app), body, self.APP_SECRET).status_code == 200

        assert WhatsAppMessage.objects.count() == 0
        delay.assert_not_called()

    def test_a_number_on_an_organizations_app_is_never_stored_from_the_general_address(
        self, client, number_on_it, delay, django_capture_on_commit_callbacks
    ):
        body = payloads.envelope(payloads.messages_change(payloads.text_message()))

        with django_capture_on_commit_callbacks(execute=True):
            assert post_signed(client, body).status_code == 200

        assert WhatsAppMessage.objects.count() == 0

    def test_a_refusal_names_the_app_and_never_its_secret(self, client, app, number_on_it, delay, caplog):
        body = payloads.envelope(payloads.messages_change(payloads.text_message()))

        with caplog.at_level("WARNING", logger="apps.whatsapp.views"):
            self.post(client, self.url(app), body, "wrong-secret")

        assert f"doesn't match the App secret registered for Meta app {app.app_id}" in caplog.text
        assert self.APP_SECRET not in caplog.text


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
