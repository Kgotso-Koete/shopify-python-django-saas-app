"""
The number troubleshooting tools (plan decision D18, Step 1.5b, user story 23): Meta's repair calls
for a number that's stuck in registration or verification, as checked and logged operations. They
replace the reference app's unauthenticated GET routes, which anyone could call.

- The input is checked before Meta is asked: SMS or VOICE, a numeric code, a 6-digit PIN.
- Every repair writes an action-log entry, whatever Meta answered, because Meta counts each
  registration attempt against its limit. The code and the PIN are never logged or stored. The
  read-only status isn't logged.
- Each of Meta's errors comes back with a plain explanation and a link to Meta's page.

The organization and its permission are checked by the caller (the GraphQL API, or the Django admin
for the operator).

Meta's references:
https://developers.facebook.com/documentation/business-messaging/whatsapp/business-phone-numbers/phone-numbers.md
https://developers.facebook.com/documentation/business-messaging/whatsapp/business-phone-numbers/registration.md
https://developers.facebook.com/documentation/business-messaging/whatsapp/support/error-codes
"""

import re

from apps.multitenancy.constants import ActionType
from common.action_logging.service import log_action

from ..client import PermanentSendError, RetryableSendError, TokenRejectedError, WhatsAppClient
from ..constants import ACTION_LOG_ENTITY_TYPE

PHONE_NUMBERS_DOC = (
    "https://developers.facebook.com/documentation/business-messaging/whatsapp/business-phone-numbers/phone-numbers.md"
)
REGISTRATION_DOC = (
    "https://developers.facebook.com/documentation/business-messaging/whatsapp/business-phone-numbers/registration.md"
)
ERROR_CODES_DOC = "https://developers.facebook.com/documentation/business-messaging/whatsapp/support/error-codes"

# The language Meta's code message is sent in; Meta's own example uses en_US.
CODE_LANGUAGE = "en_US"
CODE_METHODS = ("SMS", "VOICE")
CODE_PATTERN = re.compile(r"\d{4,8}")
PIN_PATTERN = re.compile(r"\d{6}")

# Meta's errors for these calls, in plain words: (our code, explanation, Meta's page). The texts and
# codes are from the error-codes and registration pages above.
EXPLANATIONS = {
    133016: (
        "too_many_attempts",
        "Meta allows 10 registration attempts per number in 72 hours, and this number has used them. "
        "Registration is blocked for 72 hours.",
        REGISTRATION_DOC,
    ),
    136024: ("already_verified", "This number is already verified, so it needs no code.", PHONE_NUMBERS_DOC),
    133005: ("wrong_pin", "The two-step verification PIN is wrong.", ERROR_CODES_DOC),
    133006: ("verify_first", "The number must be verified with a code before it's registered.", REGISTRATION_DOC),
    133008: ("too_many_pin_guesses", "Too many wrong PINs for this number. Wait before trying again.", ERROR_CODES_DOC),
    133009: ("pin_too_fast", "The PIN was entered too soon after the last try. Wait, then try again.", ERROR_CODES_DOC),
    133010: (
        "not_registered",
        "The number isn't registered on the WhatsApp Business Platform yet. Register it with its PIN.",
        REGISTRATION_DOC,
    ),
}


class NumberToolError(Exception):
    """
    A repair that didn't work, explained for the admin: `code` for the web app, `field` for the form
    field at fault, `meta_code` for Meta's own error code, and `help_url` for Meta's page about it.
    """

    def __init__(self, message: str, code: str, *, field=None, meta_code=None, help_url=ERROR_CODES_DOC):
        super().__init__(message)
        self.code = code
        self.field = field
        self.meta_code = meta_code
        self.help_url = help_url


def get_status(account) -> dict:
    """Meta's own view of the number, its fields as Meta sends them."""
    _require_connected(account)
    return _ask_meta(lambda: WhatsAppClient(account).get_number_status())


def request_code(account, *, method: str, actor) -> None:
    """Ask Meta to send the number a verification code by SMS or voice call."""
    method = method.strip().upper()
    if method not in CODE_METHODS:
        raise NumberToolError("Choose SMS or VOICE.", "invalid_method", field="method")
    _repair(account, actor, "request_code", lambda client: client.request_code(method, language=CODE_LANGUAGE))


def verify_code(account, *, code: str, actor) -> None:
    """Send Meta the code the number received."""
    code = code.strip()
    if not CODE_PATTERN.fullmatch(code):
        raise NumberToolError("The code is the 4 to 8 digits Meta sent the number.", "invalid_code", field="code")
    _repair(account, actor, "verify_code", lambda client: client.verify_code(code))


def register(account, *, pin: str, actor) -> None:
    """Register the number with its 6-digit two-step verification PIN, which passes straight to Meta."""
    pin = pin.strip()
    if not PIN_PATTERN.fullmatch(pin):
        raise NumberToolError("The PIN is exactly 6 digits.", "invalid_pin", field="pin")
    _repair(account, actor, "register", lambda client: client.register(pin))


def subscribe_app(account, *, actor) -> None:
    """Subscribe this app to the number's WhatsApp Business account webhooks again."""
    _repair(account, actor, "subscribe_app", lambda client: client.subscribe_app())


def _repair(account, actor, operation: str, call) -> None:
    """Run one repair call, and log it, succeeded or failed, without its code or PIN."""
    _require_connected(account)
    try:
        _ask_meta(lambda: call(WhatsAppClient(account)))
    except NumberToolError as error:
        _log(account, actor, operation, outcome="failed", meta_code=error.meta_code)
        raise
    _log(account, actor, operation, outcome="succeeded")


def _require_connected(account) -> None:
    if not account.is_active:
        raise NumberToolError("This number is disconnected, so there's no token to ask Meta with.", "not_connected")


def _ask_meta(call):
    """Run one request to Meta, turning its failure into a NumberToolError with an explanation."""
    try:
        return call()
    except TokenRejectedError as error:
        raise NumberToolError(
            f"Meta rejected the number's access token (Meta error {error.code}). Connect the number again "
            "with a valid token.",
            "token_rejected",
            meta_code=error.code,
        ) from error
    except RetryableSendError as error:
        raise NumberToolError("Meta couldn't be reached. Try again in a minute.", "try_again_later") from error
    except PermanentSendError as error:
        code, explanation, help_url = EXPLANATIONS.get(error.code, ("meta_refused", None, ERROR_CODES_DOC))
        # An unknown error shows Meta's own words: Meta's code, message and trace id.
        message = f"{explanation} (Meta error {error.code})" if explanation else f"Meta refused the request. {error}"
        raise NumberToolError(f"{message} {help_url}", code, meta_code=error.code, help_url=help_url) from error


def _log(account, actor, operation: str, *, outcome: str, meta_code=None) -> None:
    """One action-log entry per repair, in the number's organization's activity log."""
    metadata = {"operation": operation, "outcome": outcome}
    if meta_code is not None:
        metadata["meta_error_code"] = meta_code
    log_action(
        tenant_id=account.tenant_id,
        action_type=ActionType.SETTINGS_CHANGE,
        entity_type=ACTION_LOG_ENTITY_TYPE,
        entity_id=str(account.id),
        entity_name=account.display_phone_number or account.phone_number_id,
        actor_user=actor,
        metadata=metadata,
        # D18: every repair is recorded, even where an organization switched routine logging off.
        force_log=True,
    )
