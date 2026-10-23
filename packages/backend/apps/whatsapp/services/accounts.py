"""
Connecting an organization's WhatsApp number with a form, testing it, and disconnecting it (plan
Step 1.5, user story 11). The GraphQL API calls these after its permission checks (Step 1.5f).

The maintainer's decisions (plan Step 1.5, 2026-10-17):
- the test message is sent directly, so the admin sees Meta's answer in the form
- disconnecting wipes the secrets and keeps the history; reconnecting in the same organization
  reuses the row with fresh credentials
- a number with a row in another organization is refused, even after that one disconnected it; the
  operator frees it in the Django admin

Since Step 1.17 the form says what the number is for. An organization has one active internal
communications number, which its team texts, and any number of external communications numbers. A
number is one or the other until one number for both (plan Step 2.7). Once a number is saved, the
app that answers numbers of its purpose may set it up, through its handler's optional
on_connected(account): apps.whatsapp_saas publishes its forms that way.

Since Step 1.18 every number is on our one Meta app, whose App secret and verify token are settings.
The form takes the number's id, its WhatsApp Business account's id and an access token; connecting
then subscribes our app to that WhatsApp Business account, so its messages reach our webhook.

Meta's references: checking a number,
https://developers.facebook.com/documentation/business-messaging/whatsapp/business-phone-numbers/phone-numbers.md
subscribing an app to a WhatsApp Business account,
https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/onboarding-customers-as-a-tech-provider.md
and sending a template,
https://developers.facebook.com/documentation/business-messaging/whatsapp/templates/overview.md
"""

from dataclasses import dataclass
from datetime import datetime
from functools import partial

from django.db import transaction
from django.utils import timezone

from .. import registry
from ..client import PermanentSendError, RetryableSendError, TokenRejectedError, WhatsAppClient, send_backend
from ..constants import AccountPurpose, ConnectionMethod, MessageDirection
from ..models import WhatsAppAccount, WhatsAppMessage
from ..phone_numbers import InvalidPhoneNumber, normalize_phone_number

# Meta's sample template, approved on every new WhatsApp Business account; its get-started guide
# sends it as the first message: https://developers.facebook.com/documentation/business-messaging/whatsapp/get-started.md
# Its language isn't stated on that page; en_US is the one WhatsApp Manager's API setup uses, and the
# human check for the test message confirms it.
TEST_TEMPLATE = "hello_world"
TEST_TEMPLATE_LANGUAGE = "en_US"

REQUIRED_FIELDS = {
    "phone_number_id": "Phone number ID",
    "waba_id": "WhatsApp Business account ID",
    "access_token": "Access token",
}


class AccountError(Exception):
    """
    Something the admin can fix, shown in the form. `code` is for the web app to react to, and
    `field` names the form field at fault, when there is one. The message never holds a secret.
    """

    def __init__(self, message: str, code: str, field: str | None = None):
        super().__init__(message)
        self.code = code
        self.field = field


@dataclass(frozen=True)
class ConnectedAccount:
    """A connected account, subscribed to our Meta app."""

    account: WhatsAppAccount


def connect_account(*, tenant, purpose: str, phone_number_id: str, waba_id: str, access_token: str):
    """
    Connect a number for `tenant` with the form's fields. Meta is asked about the number with the
    given token first, then our app is subscribed to its WhatsApp Business account; nothing is saved
    unless Meta accepts both. Returns a ConnectedAccount.
    """
    if purpose not in AccountPurpose.values:
        raise AccountError("Choose what the number is for.", code="invalid_purpose", field="purpose")
    values = {
        "phone_number_id": phone_number_id.strip(),
        "waba_id": waba_id.strip(),
        "access_token": access_token.strip(),
    }
    for field, label in REQUIRED_FIELDS.items():
        if not values[field]:
            raise AccountError(f"{label} is required.", code="required", field=field)

    existing = WhatsAppAccount.objects.filter(phone_number_id=values["phone_number_id"]).first()
    if existing is not None and existing.tenant_id != tenant.pk:
        # The same answer whether the other organization is connected or not, and whoever it is.
        raise AccountError(
            "This phone number is already connected to another organization.",
            code="already_connected",
            field="phone_number_id",
        )
    if existing is not None and existing.purpose != purpose:
        raise AccountError(
            f"This number is already your organization's {existing.get_purpose_display().lower()} number. "
            "A number is one or the other for now.",
            code="connected_for_the_other_purpose",
            field="phone_number_id",
        )
    internal = WhatsAppAccount.objects.internal_for(tenant)
    if purpose == AccountPurpose.INTERNAL_COMMUNICATIONS and internal is not None and internal != existing:
        raise AccountError(
            f"Your organization's team already texts {internal.display_phone_number or internal.phone_number_id}. "
            "Disconnect it first to connect another internal communications number.",
            code="internal_number_exists",
        )

    # Checked with an unsaved account, so a refused id or token leaves nothing behind.
    candidate = WhatsAppAccount(phone_number_id=values["phone_number_id"], waba_id=values["waba_id"])
    candidate.access_token = values["access_token"]
    details = _ask_meta(lambda: WhatsAppClient(candidate).get_phone_number())
    credentials_verified_at = timezone.now()
    # Without the subscription Meta sends the number's messages nowhere we can see them.
    _ask_meta(lambda: WhatsAppClient(candidate).subscribe_app())

    account = existing or WhatsAppAccount(purpose=purpose, tenant=tenant)
    account.phone_number_id = values["phone_number_id"]
    account.waba_id = values["waba_id"]
    account.access_token = values["access_token"]
    account.display_phone_number = details.display_phone_number
    account.verified_name = details.verified_name
    account.connection_method = ConnectionMethod.MANUAL
    account.credentials_verified_at = credentials_verified_at
    account.subscribed_at = timezone.now()
    account.is_active = True
    account.save()

    # Told only once the row is committed, so a task it queues always finds the account.
    on_connected = getattr(registry.handler_for(purpose), "on_connected", None)
    if on_connected is not None:
        transaction.on_commit(partial(on_connected, account))
    return ConnectedAccount(account=account)


@transaction.atomic
def disconnect_account(*, tenant, account_id) -> None:
    """Wipe the number's access token and mark it inactive; its contacts and messages stay."""
    account = find_account(tenant, account_id, for_update=True)
    account.access_token_encrypted = ""
    account.is_active = False
    account.save(update_fields=["access_token_encrypted", "is_active", "updated_at"])


def send_test_message(*, tenant, account_id, to: str) -> str:
    """
    Send Meta's `hello_world` template from the organization's number to `to`, typed in any common
    format (D19), and return Meta's message id. Sent directly, not queued, so Meta's answer can be
    shown in the form.
    """
    account = find_account(tenant, account_id)
    if not account.is_active:
        raise AccountError("This number is disconnected. Connect it again first.", code="not_connected")
    try:
        number = normalize_phone_number(to)
    except InvalidPhoneNumber as error:
        raise AccountError(str(error), code="invalid_phone_number", field="to") from error
    return _ask_meta(
        lambda: send_backend().send_template(account, number, TEST_TEMPLATE, language=TEST_TEMPLATE_LANGUAGE)
    )


def last_message_received_at(account: WhatsAppAccount) -> datetime | None:
    """When the newest message reached this number: the form's last proof (user story 11)."""
    newest = (
        WhatsAppMessage.objects.filter(contact__account=account, direction=MessageDirection.INBOUND)
        .order_by("-created_at")
        .values_list("created_at", flat=True)
        .first()
    )
    return newest


def find_account(tenant, account_id, *, for_update: bool = False) -> WhatsAppAccount:
    """
    The organization's own account; another organization's is "not found", as a missing one is.
    Every operation on one number, here and in the troubleshooting tools, finds it through this.
    """
    accounts = WhatsAppAccount.objects.filter(tenant=tenant)
    if for_update:
        accounts = accounts.select_for_update()
    account = accounts.filter(pk=account_id).first()
    if account is None:
        raise AccountError("WhatsApp number not found.", code="not_found")
    return account


def _ask_meta(call):
    """Run one request to Meta, turning its failure into an AccountError the admin can act on."""
    try:
        return call()
    except TokenRejectedError as error:
        raise AccountError(
            "Meta rejected the access token. Check that it's a valid, unexpired system user token.",
            code="token_rejected",
            field="access_token",
        ) from error
    except RetryableSendError as error:
        raise AccountError("Meta couldn't be reached. Try again in a minute.", code="try_again_later") from error
    except PermanentSendError as error:
        # The error's text is Meta's code, message and trace id: what Meta's support asks for.
        raise AccountError(f"Meta refused the request. {error}", code="meta_refused") from error
