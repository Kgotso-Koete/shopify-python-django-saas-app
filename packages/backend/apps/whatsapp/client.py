"""
Sending one message through Meta's WhatsApp Cloud API, and the send backends that choose between
really sending and only logging (plan Step 1.4b, decision D8).

The message part comes from builders.py; this module adds Meta's envelope and the recipient.
Meta's references:
- sending messages (the envelope, `to`, and the returned contacts[].wa_id and messages[].id):
  https://developers.facebook.com/documentation/business-messaging/whatsapp/messages/send-messages.md
- sending to a business-scoped user id with `recipient`:
  https://developers.facebook.com/documentation/business-messaging/whatsapp/business-scoped-user-ids
- error codes, and which ones to retry:
  https://developers.facebook.com/documentation/business-messaging/whatsapp/support/error-codes
"""

import logging
import uuid
from dataclasses import dataclass

import requests
from django.conf import settings

from .constants import MessageStatus, SendBackend

logger = logging.getLogger(__name__)

GRAPH_API_URL = "https://graph.facebook.com"
# Seconds; a request without a timeout could hang a worker forever.
REQUEST_TIMEOUT_SECONDS = 10

# Codes Meta's error-codes page says to retry later: throughput (130429), too many messages to one
# recipient (131056), the app's rate limit (4), the WhatsApp Business account's rate limit (80007),
# and an unknown error (131000).
RETRYABLE_ERROR_CODES = frozenset({130429, 131056, 4, 80007, 131000})
# More than 24 hours since the customer last wrote: only a template can be sent now.
WINDOW_CLOSED_ERROR_CODE = 131047
# The access token expired or was revoked; every send fails until it's replaced.
TOKEN_REJECTED_ERROR_CODE = 190


class SendError(Exception):
    """
    A message Meta didn't accept. `code` is Meta's error code, or None when there wasn't one
    (a timeout, or an error page instead of Meta's JSON). The message never holds the token.
    """

    def __init__(self, code: int | None, message: str):
        super().__init__(message)
        self.code = code


class RetryableSendError(SendError):
    """Worth sending again later: a rate limit, a timeout, or Meta having a bad moment."""


class PermanentSendError(SendError):
    """Sending the same message again would fail the same way."""


class WindowClosedError(PermanentSendError):
    """The 24-hour customer service window is closed (131047); only a template can be sent."""


class TokenRejectedError(PermanentSendError):
    """The account's access token was rejected (190) and must be replaced."""


class FlowValidationError(PermanentSendError):
    """Meta refused a Flow's JSON; `errors` are Meta's validation_errors, each with its message."""

    def __init__(self, errors: list[dict]):
        messages = "; ".join(error.get("message", str(error)) for error in errors)
        super().__init__(None, f"Meta refused the Flow JSON: {messages}")
        self.errors = errors


@dataclass(frozen=True)
class PhoneNumberDetails:
    """What Meta says about a phone number id: the number as shown, and the business name it verified."""

    display_phone_number: str
    verified_name: str


class WhatsAppClient:
    """
    Talks to Meta's Cloud API for one WhatsAppAccount's number, with that account's access token.
    Every failure is a SendError subclass, also for requests that send nothing (get_phone_number):
    Meta's error codes and their meaning are the same for every endpoint.
    """

    def __init__(self, account):
        self.account = account

    @property
    def _number_url(self) -> str:
        return f"{GRAPH_API_URL}/{settings.WHATSAPP_GRAPH_API_VERSION}/{self.account.phone_number_id}"

    @property
    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.account.access_token}", "Content-Type": "application/json"}

    def send(self, contact, message: dict) -> str:
        """
        Sends `message` (one builder's output) to `contact` and returns Meta's id for it (the wamid
        that later delivery statuses refer to). Raises a SendError subclass when Meta refuses it.
        """
        data = self._post_message(_envelope(contact, message))
        _keep_metas_wa_id(contact, data)
        return _wamid_from(data)

    def send_template(self, to: str, name: str, *, language: str) -> str:
        """
        Sends the approved template `name` to the phone number `to` (international digits, D19) and
        returns Meta's id for it. A template, unlike free text, may start a conversation: the
        "Send test message" button (user story 11) sends Meta's sample `hello_world`.
        https://developers.facebook.com/documentation/business-messaging/whatsapp/templates/overview.md
        """
        envelope = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": to}
        template = {"name": name, "language": {"code": language}}
        return _wamid_from(self._post_message({**envelope, "type": "template", "template": template}))

    def get_phone_number(self) -> PhoneNumberDetails:
        """
        Asks Meta about this account's phone number id, with its token: the check that the id and
        token work before they're saved (user story 11).
        https://developers.facebook.com/documentation/business-messaging/whatsapp/business-phone-numbers/phone-numbers.md
        """
        data = self._call(
            requests.get,
            self._number_url,
            params={"fields": "display_phone_number,verified_name"},
            headers=self._headers,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        return PhoneNumberDetails(
            display_phone_number=data.get("display_phone_number", ""), verified_name=data.get("verified_name", "")
        )

    # The number troubleshooting tools (plan D18, user story 23). None of these log anything: the
    # code and the PIN pass straight to Meta.

    def get_number_status(self) -> dict:
        """
        Meta's own view of the number, its fields as Meta sends them: `status` (a number must be
        connected to send and receive), `code_verification_status`, `quality_rating`, `name_status`.
        https://developers.facebook.com/documentation/business-messaging/whatsapp/business-phone-numbers/phone-numbers.md
        """
        fields = "status,code_verification_status,quality_rating,name_status,verified_name,display_phone_number"
        return self._call(
            requests.get,
            self._number_url,
            params={"fields": fields},
            headers=self._headers,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

    def request_code(self, method: str, *, language: str) -> None:
        """
        Ask Meta to send the number a verification code by "SMS" or "VOICE". Meta takes both in the
        query string; an already-verified number gets error 136024.
        https://developers.facebook.com/documentation/business-messaging/whatsapp/business-phone-numbers/phone-numbers.md
        """
        self._call(
            requests.post,
            f"{self._number_url}/request_code",
            params={"code_method": method, "language": language},
            headers=self._headers,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

    def verify_code(self, code: str) -> None:
        """
        Send Meta the code the number received, as a form field.
        https://developers.facebook.com/documentation/business-messaging/whatsapp/business-phone-numbers/phone-numbers.md
        """
        headers = {"Authorization": self._headers["Authorization"]}
        self._call(
            requests.post,
            f"{self._number_url}/verify_code",
            data={"code": code},
            headers=headers,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

    def register(self, pin: str) -> None:
        """
        Register the number with the Cloud API using its 6-digit two-step verification PIN (which
        becomes the PIN if none is set). Meta allows 10 calls per number in 72 hours, then answers
        133016 and blocks registration for 72 hours.
        https://developers.facebook.com/documentation/business-messaging/whatsapp/business-phone-numbers/registration.md
        """
        self._call(
            requests.post,
            f"{self._number_url}/register",
            json={"messaging_product": "whatsapp", "pin": pin},
            headers=self._headers,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

    def subscribe_app(self) -> None:
        """
        Subscribe this app to the WhatsApp Business account's webhooks, so Meta sends its numbers'
        events to our one webhook URL (D6).
        https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/onboarding-customers-as-a-tech-provider.md
        """
        url = f"{GRAPH_API_URL}/{settings.WHATSAPP_GRAPH_API_VERSION}/{self.account.waba_id}/subscribed_apps"
        self._call(requests.post, url, headers=self._headers, timeout=REQUEST_TIMEOUT_SECONDS)

    def create_flow(self, name: str, flow_json: str) -> str:
        """
        Create a WhatsApp Flow on the account's WhatsApp Business account and publish it in the same
        call, returning its id (plan Step 1.11). Meta lists any problems with the JSON in
        validation_errors, raised here as FlowValidationError; a published Flow can't be edited, so a
        changed form is published as a new Flow.
        https://developers.facebook.com/docs/whatsapp/flows/reference/flowsapi
        """
        url = f"{GRAPH_API_URL}/{settings.WHATSAPP_GRAPH_API_VERSION}/{self.account.waba_id}/flows"
        # "OTHER": none of Meta's other categories (sign-up, booking, survey…) fits a plain edit form.
        body = {"name": name, "categories": ["OTHER"], "flow_json": flow_json, "publish": True}
        data = self._call(requests.post, url, json=body, headers=self._headers, timeout=REQUEST_TIMEOUT_SECONDS)
        if data.get("validation_errors"):
            raise FlowValidationError(data["validation_errors"])
        return data["id"]

    def _post_message(self, body: dict) -> dict:
        return self._call(
            requests.post,
            f"{self._number_url}/messages",
            json=body,
            headers=self._headers,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

    @staticmethod
    def _call(method, url: str, **kwargs) -> dict:
        """One request to Meta; Meta's answer as a dict, or the SendError for its failure."""
        try:
            response = method(url, **kwargs)
        except (requests.Timeout, requests.ConnectionError) as error:
            # The exception names the URL, which holds no secret; the token is only in the header.
            raise RetryableSendError(None, f"Couldn't reach Meta: {type(error).__name__}") from error
        if not response.ok:
            raise _error_from(response)
        return response.json()


def _wamid_from(data: dict) -> str:
    """The new message's id from Meta's answer to a send."""
    try:
        return data["messages"][0]["id"]
    except (KeyError, IndexError, TypeError) as error:
        raise PermanentSendError(None, "Meta accepted the request but returned no message id") from error


def _envelope(contact, message: dict) -> dict:
    """
    Meta's envelope around a message. A contact is addressed by phone number when we have one,
    otherwise by business-scoped user id; Meta uses `to` when both are set, so only one is sent.
    """
    recipient = {"to": contact.wa_id} if contact.wa_id else {"recipient": contact.bsuid}
    return {"messaging_product": "whatsapp", "recipient_type": "individual", **recipient, **message}


def _error_from(response) -> SendError:
    """The SendError for a failed response, classified by Meta's error.code."""
    try:
        error = response.json()["error"]
        code = error["code"]
    except (ValueError, KeyError, TypeError):
        # No Meta error body, e.g. a load balancer's error page: a server error is worth retrying.
        message = f"Meta answered HTTP {response.status_code} without an error body"
        if response.status_code >= 500 or response.status_code == 429:
            return RetryableSendError(None, message)
        return PermanentSendError(None, message)

    # Meta's message, details and trace id help when asking Meta's support; none of them is the token.
    details = (error.get("error_data") or {}).get("details", "")
    message = f"Meta error {code}: {error.get('message', '')} {details} (fbtrace_id {error.get('fbtrace_id', '')})"
    if code in RETRYABLE_ERROR_CODES:
        return RetryableSendError(code, message)
    if code == WINDOW_CLOSED_ERROR_CODE:
        return WindowClosedError(code, message)
    if code == TOKEN_REJECTED_ERROR_CODE:
        return TokenRejectedError(code, message)
    return PermanentSendError(code, message)


def _keep_metas_wa_id(contact, data: dict) -> None:
    """The send docs say the returned wa_id may not match the one sent; Meta's is the one to keep."""
    contacts = data.get("contacts") or []
    wa_id = contacts[0].get("wa_id", "") if contacts else ""
    if wa_id and wa_id != contact.wa_id:
        contact.wa_id = wa_id
        contact.save(update_fields=["wa_id"])


class LogSendBackend:
    """
    Logs messages instead of sending them, for local development and tests (D8). Each gets a fake
    id starting "log.", clearly not Meta's, so a logged reply can't be mistaken for a sent one.
    """

    # No webhook will ever report on a logged message, so it counts as sent at once; otherwise
    # strict ordering would wait for a status that never comes (services/outbox.py).
    status_after_send = MessageStatus.SENT

    def send_template(self, account, to: str, name: str, *, language: str) -> str:
        wamid = f"log.{uuid.uuid4().hex}"
        logger.info("WhatsApp template not sent (log backend): %s, %r from account %s", wamid, name, account.pk)
        return wamid

    def send(self, contact, message: dict) -> str:
        wamid = f"log.{uuid.uuid4().hex}"
        logger.info("WhatsApp message not sent (log backend): %s to contact %s: %s", wamid, contact.pk, message)
        return wamid


class MetaSendBackend:
    """Sends messages through Meta's Cloud API, from the contact's own account's number."""

    # Meta accepted the request; its "sent" status arrives later by webhook (services/inbound.py).
    status_after_send = MessageStatus.ACCEPTED

    def send(self, contact, message: dict) -> str:
        return WhatsAppClient(contact.account).send(contact, message)

    def send_template(self, account, to: str, name: str, *, language: str) -> str:
        return WhatsAppClient(account).send_template(to, name, language=language)


def send_backend() -> LogSendBackend | MetaSendBackend:
    """The backend WHATSAPP_SEND_BACKEND names; the system check (E005) refuses any other value."""
    if settings.WHATSAPP_SEND_BACKEND == SendBackend.META:
        return MetaSendBackend()
    return LogSendBackend()
