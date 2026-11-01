"""
Connecting an organization's WhatsApp number with a form, testing it, and disconnecting it (plan
Step 1.5, user story 11). The GraphQL API calls these after its permission checks (Step 1.5f).

The maintainer's decisions (plan Step 1.5, 2026-10-17):
- the test message is sent directly, so the admin sees Meta's answer in the form
- disconnecting wipes the secrets and keeps the history; reconnecting in the same organization
  reuses the row with fresh credentials
- a number with a row in another organization is refused, even after that one disconnected it; the
  operator frees it in the Django admin

Since Step 1.17 the form says what the number is for. An organization has one active number its team
texts, and any number of external communications numbers. Since Step 2.7 a number can serve both, and
is then the team's number; an admin changes a connected number's role with change_purpose. Once a
number is saved, the app that answers each audience it serves may set it up, through its handler's
optional on_connected(account): apps.whatsapp_saas publishes its forms that way.

Since Step 1.18 a number is on our one Meta app, whose App secret and verify token are settings, and
since Step 2.9 it can instead be on one of its organization's own Meta apps (services/meta_apps.py).
The form takes the number's id, its WhatsApp Business account's id and an access token; connecting
then subscribes the token's app to that WhatsApp Business account, so its messages reach a webhook.

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
from ..models import MetaApp, WhatsAppAccount, WhatsAppIdentity, WhatsAppMessage
from ..phone_numbers import InvalidPhoneNumber, normalize_phone_number
from . import identity

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


def connect_account(*, tenant, purpose: str, phone_number_id: str, waba_id: str, access_token: str, meta_app_id=None):
    """
    Connect a number for `tenant` with the form's fields. Meta is asked about the number with the
    given token first, then the token's app is subscribed to its WhatsApp Business account; nothing is
    saved unless Meta accepts both. The number is on the organization's Meta app `meta_app_id`, or on
    this service's app when it's None (plan Step 2.9). Returns a ConnectedAccount.
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
    if existing is not None and existing.is_active and existing.purpose != purpose:
        # A disconnected number may come back with any role (plan Step 2.7, decision 2).
        raise AccountError(
            f"This number is already your organization's {existing.get_purpose_display().lower()} number. "
            "Change whom it serves with Change on its row instead.",
            code="connected_for_the_other_purpose",
            field="phone_number_id",
        )
    _check_one_team_number(tenant, purpose, existing)
    meta_app = find_app(tenant, meta_app_id, field="meta_app_id") if meta_app_id else None

    # Checked with an unsaved account, so a refused id or token leaves nothing behind.
    candidate = WhatsAppAccount(phone_number_id=values["phone_number_id"], waba_id=values["waba_id"])
    candidate.access_token = values["access_token"]
    details = _ask_meta(lambda: WhatsAppClient(candidate).get_phone_number())
    credentials_verified_at = timezone.now()
    # Without the subscription Meta sends the number's messages nowhere we can see them.
    _ask_meta(lambda: WhatsAppClient(candidate).subscribe_app())

    account = existing or WhatsAppAccount(purpose=purpose, tenant=tenant)
    account.purpose = purpose
    account.phone_number_id = values["phone_number_id"]
    account.waba_id = values["waba_id"]
    account.access_token = values["access_token"]
    account.display_phone_number = details.display_phone_number
    account.verified_name = details.verified_name
    account.connection_method = ConnectionMethod.MANUAL
    account.meta_app = meta_app
    account.credentials_verified_at = credentials_verified_at
    account.subscribed_at = timezone.now()
    account.is_active = True
    account.save()

    _set_up(account, _audiences(purpose))
    return ConnectedAccount(account=account)


@transaction.atomic
def change_purpose(*, tenant, account_id, purpose: str) -> WhatsAppAccount:
    """
    Change whom a connected number serves: the team, customers, or both (plan Step 2.7, decisions 2
    and 3). It keeps its credentials, history and Meta registration. When it stops serving the team,
    its members' links are removed and their conversations forgotten, as if each had sent `unlink`;
    when it stops serving customers, its store link and store customers stay, unused. When it starts
    serving an audience, that audience's handler sets it up (on_connected), e.g. publishing forms.
    """
    if purpose not in AccountPurpose.values:
        raise AccountError("Choose whom the number serves.", code="invalid_purpose", field="purpose")
    account = find_account(tenant, account_id, for_update=True)
    if not account.is_active:
        raise AccountError("This number is disconnected. Connect it again first.", code="not_connected")
    if account.purpose == purpose:
        return account
    _check_one_team_number(tenant, purpose, account)

    before = set(_audiences(account.purpose))
    account.purpose = purpose
    account.save(update_fields=["purpose", "updated_at"])
    if AccountPurpose.INTERNAL_COMMUNICATIONS in before and not AccountPurpose.serves_team(purpose):
        # A link is a permission to act for the organization; it doesn't stay behind the wall.
        for linked in WhatsAppIdentity.objects.filter(account=account).select_related("user"):
            identity.unlink(linked.user, account)
    _set_up(account, [audience for audience in _audiences(purpose) if audience not in before])
    return account


def _check_one_team_number(tenant, purpose: str, account: WhatsAppAccount | None) -> None:
    """An organization's team texts one number (Step 1.17), internal or serving both (Step 2.7)."""
    team_number = WhatsAppAccount.objects.internal_for(tenant)
    if AccountPurpose.serves_team(purpose) and team_number is not None and team_number != account:
        raise AccountError(
            f"Your organization's team already texts {team_number.display_phone_number or team_number.phone_number_id}. "
            "An organization has one number for its team: change or disconnect that one first.",
            code="internal_number_exists",
        )


def _audiences(purpose: str) -> list[str]:
    """The handlers' purposes a number with `purpose` serves: the team's, the customers', or both."""
    audiences = []
    if AccountPurpose.serves_team(purpose):
        audiences.append(AccountPurpose.INTERNAL_COMMUNICATIONS)
    if AccountPurpose.serves_customers(purpose):
        audiences.append(AccountPurpose.EXTERNAL_COMMUNICATIONS)
    return audiences


def _set_up(account: WhatsAppAccount, audiences: list[str]) -> None:
    """Tell each audience's handler about the number, once the row is committed, so a task it queues finds it."""
    for audience in audiences:
        on_connected = getattr(registry.handler_for(audience), "on_connected", None)
        if on_connected is not None:
            transaction.on_commit(partial(on_connected, account))


@transaction.atomic
def disconnect_account(*, tenant, account_id) -> None:
    """
    Wipe the number's access token, mark it inactive, and delete its contacts (plan Step 2.8, finding
    17). Numbers are recycled, so whoever gets the number next must never reach its history. Deleting
    a contact deletes, through the database's cascades, its messages, its conversation with the
    assistant's history, its phone link and its store customer. The number's own row and its store
    link stay, as configuration, for when it's connected again; a lapsed plan deletes nothing.
    """
    account = find_account(tenant, account_id, for_update=True)
    account.access_token_encrypted = ""
    account.is_active = False
    account.save(update_fields=["access_token_encrypted", "is_active", "updated_at"])
    account.contacts.all().delete()


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


def find_app(tenant, meta_app_id, *, for_update: bool = False, field: str | None = None) -> MetaApp:
    """The organization's own Meta app (plan Step 2.9); another organization's is "not found", as a missing one is."""
    apps = MetaApp.objects.filter(tenant=tenant)
    if for_update:
        apps = apps.select_for_update()
    app = apps.filter(pk=meta_app_id).first()
    if app is None:
        raise AccountError("Meta app not found.", code="app_not_found", field=field)
    return app


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
