"""
Tests for apps/whatsapp/client.py: sending one message through Meta's Cloud API, and the send
backends that choose between really sending and only logging (plan Step 1.4b, decision D8).

HTTP is mocked: no test reaches Meta. Meta's references:
- sending messages (the envelope, `to`, and the returned contacts[].wa_id and messages[].id):
  https://developers.facebook.com/documentation/business-messaging/whatsapp/messages/send-messages.md
- sending to a business-scoped user id with `recipient`:
  https://developers.facebook.com/documentation/business-messaging/whatsapp/business-scoped-user-ids
- error codes, and which ones to retry:
  https://developers.facebook.com/documentation/business-messaging/whatsapp/support/error-codes

Kind of test: integration (agents.md section 2.5). Why: the client saves the wa_id Meta returns on
the contact, in the test database; Meta's HTTP is mocked.
"""

from unittest.mock import Mock

import pytest
import requests

from ..client import (
    FlowValidationError,
    LogSendBackend,
    MetaSendBackend,
    PermanentSendError,
    PhoneNumberDetails,
    RetryableSendError,
    TokenRejectedError,
    WhatsAppClient,
    WindowClosedError,
    send_backend,
)
from .factories import ContactFactory, InternalAccountFactory

pytestmark = pytest.mark.django_db

ACCESS_TOKEN = "EAAGtest-access-token"
TEXT_MESSAGE = {"type": "text", "text": {"body": "Hi", "preview_url": False}}


@pytest.fixture(autouse=True)
def graph_api_version(settings):
    settings.WHATSAPP_GRAPH_API_VERSION = "v26.0"


@pytest.fixture
def account():
    return InternalAccountFactory(phone_number_id="100000000000001", access_token=ACCESS_TOKEN)


@pytest.fixture
def contact(account):
    return ContactFactory(account=account, bsuid="ZA.1000000000000000001", wa_id="27000001001")


@pytest.fixture
def post(mocker):
    """requests.post inside the client, answering with Meta's success shape unless a test says otherwise."""
    return mocker.patch("apps.whatsapp.client.requests.post", return_value=meta_success())


def meta_success(wamid="wamid.SENT1", wa_id="27000001001"):
    """Meta's answer to a successful send: the recipient as Meta knows them, and the new message's id."""
    return fake_response(
        200,
        {
            "messaging_product": "whatsapp",
            "contacts": [{"input": wa_id, "wa_id": wa_id}],
            "messages": [{"id": wamid}],
        },
    )


def meta_error(code, status=400):
    """Meta's error shape: error.message, type, code, error_data.details and fbtrace_id."""
    return fake_response(
        status,
        {
            "error": {
                "message": f"(#{code}) Something went wrong",
                "type": "OAuthException",
                "code": code,
                "error_data": {"messaging_product": "whatsapp", "details": "Details from Meta"},
                "fbtrace_id": "AbCdEf123",
            }
        },
    )


def fake_response(status, body):
    response = Mock(status_code=status, ok=status < 400)
    response.json.return_value = body
    return response


class TestTheRequest:
    def test_a_message_is_posted_to_the_numbers_messages_endpoint_with_its_token(self, account, contact, post):
        WhatsAppClient(account).send(contact, TEXT_MESSAGE)

        url = post.call_args.args[0]
        kwargs = post.call_args.kwargs
        assert url == "https://graph.facebook.com/v26.0/100000000000001/messages"
        assert kwargs["headers"]["Authorization"] == f"Bearer {ACCESS_TOKEN}"
        # A request without a timeout could hang a worker forever.
        assert kwargs["timeout"] > 0

    def test_the_body_is_the_message_inside_meta_s_envelope_addressed_to_the_phone_number(self, account, contact, post):
        WhatsAppClient(account).send(contact, TEXT_MESSAGE)

        assert post.call_args.kwargs["json"] == {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": "27000001001",
            "type": "text",
            "text": {"body": "Hi", "preview_url": False},
        }

    def test_a_contact_without_a_phone_number_is_addressed_by_business_scoped_user_id(self, account, post):
        contact = ContactFactory(account=account, bsuid="ZA.1000000000000000002", wa_id="")

        WhatsAppClient(account).send(contact, TEXT_MESSAGE)

        body = post.call_args.kwargs["json"]
        assert body["recipient"] == "ZA.1000000000000000002"
        # Meta uses `to` when both are set, so only one is ever sent.
        assert "to" not in body


class TestTheResult:
    def test_sending_returns_meta_s_id_for_the_new_message(self, account, contact, post):
        post.return_value = meta_success(wamid="wamid.NEW1")

        assert WhatsAppClient(account).send(contact, TEXT_MESSAGE) == "wamid.NEW1"

    def test_the_wa_id_meta_returns_is_stored_when_it_differs(self, account, contact, post):
        # The send docs say the returned wa_id "may not match" the input; Meta's is the one to keep.
        post.return_value = meta_success(wa_id="27000001999")

        WhatsAppClient(account).send(contact, TEXT_MESSAGE)

        contact.refresh_from_db()
        assert contact.wa_id == "27000001999"


class TestErrors:
    @pytest.mark.parametrize(
        "code",
        [
            130429,  # the number's throughput limit
            131056,  # too many messages to the same recipient in a short time
            4,  # the app's API call rate limit
            80007,  # the WhatsApp Business account's rate limit
            131000,  # an unknown error: Meta's docs say to try again
        ],
    )
    def test_errors_meta_says_to_retry_later_are_retryable(self, account, contact, post, code):
        post.return_value = meta_error(code)

        with pytest.raises(RetryableSendError) as raised:
            WhatsAppClient(account).send(contact, TEXT_MESSAGE)

        assert raised.value.code == code

    def test_a_closed_24_hour_window_has_its_own_error(self, account, contact, post):
        # 131047: only a template can be sent now, so retrying the same message would never work.
        post.return_value = meta_error(131047)

        with pytest.raises(WindowClosedError) as raised:
            WhatsAppClient(account).send(contact, TEXT_MESSAGE)

        assert raised.value.code == 131047
        assert isinstance(raised.value, PermanentSendError)

    def test_a_rejected_access_token_has_its_own_error(self, account, contact, post):
        # 190: the account's token expired and must be replaced; every send would fail until it is.
        post.return_value = meta_error(190, status=401)

        with pytest.raises(TokenRejectedError) as raised:
            WhatsAppClient(account).send(contact, TEXT_MESSAGE)

        assert isinstance(raised.value, PermanentSendError)

    @pytest.mark.parametrize("code", [131026, 131051])
    def test_any_other_meta_error_is_permanent_and_keeps_meta_s_code(self, account, contact, post, code):
        # 131026: the message couldn't be delivered; 131051: an unsupported message type.
        post.return_value = meta_error(code)

        with pytest.raises(PermanentSendError) as raised:
            WhatsAppClient(account).send(contact, TEXT_MESSAGE)

        assert raised.value.code == code
        assert not isinstance(raised.value, RetryableSendError)

    @pytest.mark.parametrize("failure", [requests.Timeout("timed out"), requests.ConnectionError("no route")])
    def test_a_timeout_or_dropped_connection_is_retryable(self, account, contact, post, failure):
        post.side_effect = failure

        with pytest.raises(RetryableSendError):
            WhatsAppClient(account).send(contact, TEXT_MESSAGE)

    def test_a_server_error_without_a_meta_error_body_is_retryable(self, account, contact, post):
        response = Mock(status_code=503, ok=False)
        response.json.side_effect = ValueError("not JSON")
        post.return_value = response

        with pytest.raises(RetryableSendError):
            WhatsAppClient(account).send(contact, TEXT_MESSAGE)

    def test_an_error_never_contains_the_access_token(self, account, contact, post):
        # Errors end up in logs; the token must never be there.
        post.return_value = meta_error(131026)

        with pytest.raises(PermanentSendError) as raised:
            WhatsAppClient(account).send(contact, TEXT_MESSAGE)

        assert ACCESS_TOKEN not in str(raised.value)


class TestSendBackends:
    def test_the_log_backend_is_chosen_by_default_and_makes_no_http_call(self, settings, contact, post):
        settings.WHATSAPP_SEND_BACKEND = "LOG"

        backend = send_backend()
        wamid = backend.send(contact, TEXT_MESSAGE)

        assert isinstance(backend, LogSendBackend)
        # A fake id, clearly not Meta's, so a logged reply can't be mistaken for a sent one.
        assert wamid.startswith("log.")
        post.assert_not_called()

    def test_every_logged_message_gets_its_own_fake_id(self, settings, contact, post):
        settings.WHATSAPP_SEND_BACKEND = "LOG"

        assert send_backend().send(contact, TEXT_MESSAGE) != send_backend().send(contact, TEXT_MESSAGE)

    def test_the_meta_backend_sends_through_the_client(self, settings, contact, post):
        settings.WHATSAPP_SEND_BACKEND = "META"

        backend = send_backend()
        wamid = backend.send(contact, TEXT_MESSAGE)

        assert isinstance(backend, MetaSendBackend)
        assert wamid == "wamid.SENT1"
        post.assert_called_once()


class TestPhoneNumberDetails:
    """
    Checking an account's id and token with Meta before they're saved (plan Step 1.5, user story 11):
    https://developers.facebook.com/documentation/business-messaging/whatsapp/business-phone-numbers/phone-numbers.md
    """

    @pytest.fixture
    def get(self, mocker):
        details = fake_response(
            200, {"display_phone_number": "+27 83 000 0001", "verified_name": "Acme Store", "id": "100000000000001"}
        )
        return mocker.patch("apps.whatsapp.client.requests.get", return_value=details)

    def test_it_asks_meta_for_the_number_with_the_accounts_token(self, account, get):
        WhatsAppClient(account).get_phone_number()

        assert get.call_args.args[0] == "https://graph.facebook.com/v26.0/100000000000001"
        assert get.call_args.kwargs["params"] == {"fields": "display_phone_number,verified_name"}
        assert get.call_args.kwargs["headers"]["Authorization"] == f"Bearer {ACCESS_TOKEN}"
        assert get.call_args.kwargs["timeout"] > 0

    def test_it_returns_the_display_number_and_the_business_name_meta_verified(self, account, get):
        details = WhatsAppClient(account).get_phone_number()

        assert details == PhoneNumberDetails(display_phone_number="+27 83 000 0001", verified_name="Acme Store")

    def test_a_rejected_token_has_its_own_error(self, account, get):
        get.return_value = meta_error(190, status=401)

        with pytest.raises(TokenRejectedError):
            WhatsAppClient(account).get_phone_number()

    def test_an_id_meta_doesnt_know_is_a_permanent_error_with_meta_s_code(self, account, get):
        # 100: "Invalid parameter", what Meta answers for an id that isn't a phone number id.
        get.return_value = meta_error(100)

        with pytest.raises(PermanentSendError) as raised:
            WhatsAppClient(account).get_phone_number()

        assert raised.value.code == 100
        assert ACCESS_TOKEN not in str(raised.value)

    def test_a_timeout_is_retryable(self, account, get):
        get.side_effect = requests.Timeout("timed out")

        with pytest.raises(RetryableSendError):
            WhatsAppClient(account).get_phone_number()


class TestTemplateMessages:
    """
    The "Send test message" button (user story 11) sends Meta's sample `hello_world` template to a
    number the admin types. A template, because a free-form message needs the recipient to have
    written first, within 24 hours. Template messages:
    https://developers.facebook.com/documentation/business-messaging/whatsapp/templates/overview.md
    """

    def test_a_template_is_sent_to_a_phone_number_in_meta_s_envelope(self, account, post):
        wamid = WhatsAppClient(account).send_template("27831234567", "hello_world", language="en_US")

        assert post.call_args.args[0] == "https://graph.facebook.com/v26.0/100000000000001/messages"
        assert post.call_args.kwargs["json"] == {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": "27831234567",
            "type": "template",
            "template": {"name": "hello_world", "language": {"code": "en_US"}},
        }
        assert wamid == "wamid.SENT1"

    def test_meta_refusing_the_template_raises_a_permanent_error(self, account, post):
        # 131026: undeliverable, e.g. the number isn't on WhatsApp; shown to the admin who typed it.
        post.return_value = meta_error(131026)

        with pytest.raises(PermanentSendError):
            WhatsAppClient(account).send_template("27831234567", "hello_world", language="en_US")


class TestNumberTroubleshooting:
    """
    The repair calls behind the number troubleshooting tools (plan D18, Step 1.5b, user story 23).
    Each request's method, path and body are as Meta documents them:
    - status and verification: https://developers.facebook.com/documentation/business-messaging/whatsapp/business-phone-numbers/phone-numbers.md
    - registration: https://developers.facebook.com/documentation/business-messaging/whatsapp/business-phone-numbers/registration.md
    - subscribing the app: https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/onboarding-customers-as-a-tech-provider.md
    """

    @pytest.fixture
    def get(self, mocker):
        status = {
            "status": "CONNECTED",
            "code_verification_status": "VERIFIED",
            "quality_rating": "GREEN",
            "name_status": "APPROVED",
            "verified_name": "Acme Store",
            "display_phone_number": "+27 83 000 0001",
            "id": "100000000000001",
        }
        return mocker.patch("apps.whatsapp.client.requests.get", return_value=fake_response(200, status))

    @pytest.fixture
    def success(self, post):
        post.return_value = fake_response(200, {"success": True})
        return post

    def test_the_status_asks_for_meta_s_fields_and_returns_them_as_they_are(self, account, get):
        status = WhatsAppClient(account).get_number_status()

        assert get.call_args.args[0] == "https://graph.facebook.com/v26.0/100000000000001"
        assert get.call_args.kwargs["params"] == {
            "fields": "status,code_verification_status,quality_rating,name_status,verified_name,display_phone_number"
        }
        # As Meta sent them, so the tab shows Meta's own words.
        assert status["status"] == "CONNECTED"
        assert status["code_verification_status"] == "VERIFIED"
        assert status["quality_rating"] == "GREEN"

    @pytest.mark.parametrize("method", ["SMS", "VOICE"])
    def test_requesting_a_code_sends_the_method_and_language_in_the_query_string(self, account, success, method):
        WhatsAppClient(account).request_code(method, language="en_US")

        assert success.call_args.args[0] == "https://graph.facebook.com/v26.0/100000000000001/request_code"
        assert success.call_args.kwargs["params"] == {"code_method": method, "language": "en_US"}
        assert success.call_args.kwargs["headers"]["Authorization"] == f"Bearer {ACCESS_TOKEN}"

    def test_verifying_sends_the_code_as_a_form_field(self, account, success):
        WhatsAppClient(account).verify_code("123456")

        assert success.call_args.args[0] == "https://graph.facebook.com/v26.0/100000000000001/verify_code"
        assert success.call_args.kwargs["data"] == {"code": "123456"}

    def test_registering_sends_the_pin_in_meta_s_json_body(self, account, success):
        WhatsAppClient(account).register("654321")

        assert success.call_args.args[0] == "https://graph.facebook.com/v26.0/100000000000001/register"
        assert success.call_args.kwargs["json"] == {"messaging_product": "whatsapp", "pin": "654321"}

    def test_subscribing_the_app_posts_to_the_whatsapp_business_account(self, account, success):
        WhatsAppClient(account).subscribe_app()

        assert success.call_args.args[0] == f"https://graph.facebook.com/v26.0/{account.waba_id}/subscribed_apps"

    @pytest.mark.parametrize(
        "call",
        [
            lambda client: client.request_code("SMS", language="en_US"),
            lambda client: client.verify_code("123456"),
            lambda client: client.register("654321"),
            lambda client: client.subscribe_app(),
        ],
        ids=["request-code", "verify-code", "register", "subscribe-app"],
    )
    def test_meta_refusing_a_repair_keeps_meta_s_code(self, account, post, call):
        # 133016: too many registration attempts; the number is blocked for 72 hours.
        post.return_value = meta_error(133016)

        with pytest.raises(PermanentSendError) as raised:
            call(WhatsAppClient(account))

        assert raised.value.code == 133016

    def test_the_pin_never_reaches_a_log_line_or_an_error(self, account, post, caplog):
        post.return_value = meta_error(133005)

        with caplog.at_level("DEBUG"):
            with pytest.raises(PermanentSendError) as raised:
                WhatsAppClient(account).register("654321")

        assert "654321" not in caplog.text
        assert "654321" not in str(raised.value)


class TestPublishingFlows:
    """
    Creating and publishing a WhatsApp Flow in one call (plan Step 1.11a): POST /<WABA_ID>/flows with
    name, categories, flow_json as a string and publish. Meta answers with the Flow's id and any
    validation_errors: https://developers.facebook.com/docs/whatsapp/flows/reference/flowsapi
    """

    FLOW_JSON = '{"version": "7.2", "screens": []}'

    def test_the_flow_is_created_and_published_on_the_whatsapp_business_account(self, account, post):
        post.return_value = fake_response(200, {"id": "900000000000001", "success": True, "validation_errors": []})

        flow_id = WhatsAppClient(account).create_flow("item-abc12345", self.FLOW_JSON)

        assert post.call_args.args[0] == f"https://graph.facebook.com/v26.0/{account.waba_id}/flows"
        assert post.call_args.kwargs["json"] == {
            "name": "item-abc12345",
            "categories": ["OTHER"],
            "flow_json": self.FLOW_JSON,
            "publish": True,
        }
        assert post.call_args.kwargs["headers"]["Authorization"] == f"Bearer {ACCESS_TOKEN}"
        assert flow_id == "900000000000001"

    def test_validation_errors_are_raised_with_meta_s_messages(self, account, post):
        post.return_value = fake_response(
            200,
            {
                "id": "900000000000002",
                "success": False,
                "validation_errors": [
                    {"error": "INVALID_PROPERTY", "message": "Property 'init-value' is not allowed here."}
                ],
            },
        )

        with pytest.raises(FlowValidationError) as raised:
            WhatsAppClient(account).create_flow("item-abc12345", self.FLOW_JSON)

        assert "Property 'init-value' is not allowed here." in str(raised.value)
        assert raised.value.errors[0]["error"] == "INVALID_PROPERTY"

    def test_meta_refusing_the_request_keeps_meta_s_code(self, account, post):
        post.return_value = meta_error(100)

        with pytest.raises(PermanentSendError) as raised:
            WhatsAppClient(account).create_flow("item-abc12345", self.FLOW_JSON)

        assert raised.value.code == 100
