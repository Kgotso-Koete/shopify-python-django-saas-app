"""
Linking a user's phone on an organization's internal communications number (plan Step 1.7,
decision D3, user stories WA.D1.OM.J1.A2 and WA.D1.OM.J1.A1, Step 1.17).

Two proofs at once, never one: start_link runs in the user's logged-in web session and issues a
code for the number they typed; the code must then arrive *from that phone* as "link 123456", in
a webhook Meta signed. The codes are apps.phone_verification's, on the WHATSAPP_INBOUND channel
(D20), which makes them expire, work once, and stop after a few wrong guesses.

A user links once per internal number, so once per organization. A code isn't tied to a number:
the profile page's choice of organization decides which number the "Open WhatsApp" link opens, and
linking checks that the user is a member of the number's organization. Membership is checked again
on every message (identity_for), so someone who leaves the organization is no longer answered.

Anyone who isn't linked gets no reply, except to "link <code>" (maintainer's decision, 2026-10-22),
so a store customer who finds the team's number hears nothing. A number serving both (plan Step 2.7)
is the team's number too: members link on it, and anyone else there is a store customer.

A conversation belongs to whoever is linked to the phone. Unlinking, and linking a phone afresh,
forget it: the menus, unconfirmed writes and the assistant's history (Step 1.13), so the next person
linked to that phone inherits none of it.

**A code received on WhatsApp** (plan phase 7, user story WA.D1.OM.J1.A3, decided 2026-11-09), when
PHONE_VERIFICATION_CHANNEL is WHATSAPP_TEMPLATE: start_link sends the code from the organization's team number
in its authentication template (LINK_TEMPLATE, submitted when the number connects), and the member types it on
the website (confirm_link). That proves the phone. A phone that has written to the team number before is
linked at once; otherwise a WhatsAppWaitingLink is kept, and identity_for links it when the phone first writes,
since a contact is keyed by Meta's business-scoped id, which only an incoming message gives. No SMS.
"""

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.multitenancy.models import TenantMembership
from apps.phone_verification.constants import Channel
from apps.phone_verification.services import CodeCheckError, check_code, issue_code

from ..agent import history
from ..builders import template_message, text_reply
from ..client import SendError, send_backend
from ..constants import AccountPurpose
from ..models import WhatsAppAccount, WhatsAppContact, WhatsAppConversation, WhatsAppIdentity, WhatsAppWaitingLink
from ..phone_numbers import InvalidPhoneNumber, normalize_phone_number
from . import confirmations

logger = logging.getLogger(__name__)

# "link 123456", in any case, with any spacing.
LINK_COMMAND = re.compile(r"^\s*link\s+(\d{6})\s*$", re.IGNORECASE)

# The authentication template the team number sends a link code in (phase 7): its name is fixed, and it can't
# take a name a business uses for its own templates, as the order templates' `shop_` names can't.
LINK_TEMPLATE = "team_link_code"
LINK_TEMPLATE_LANGUAGE = "en"
# How long a proved phone waits for its first message before the member must ask for a new code.
WAITING_LINK_DAYS = 7
# What typing the code did.
LINKED = "LINKED"
WAITING = "WAITING"


class IdentityError(Exception):
    """Linking can't start. `code` is for the web app; the message is for the user."""

    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class LinkStarted:
    """
    What the profile page shows: the code, and a wa.me link that opens the chat with it typed; both empty when
    the code was sent to the phone (channel WHATSAPP_TEMPLATE, phase 7), to be typed on the page instead.
    """

    code: str
    phone_number: str
    link: str
    expires_at: datetime
    channel: str = Channel.WHATSAPP_INBOUND


def link_template() -> dict:
    """
    The authentication template a link code is sent in (phase 7), as Meta's Message Templates API takes it:
    Meta's fixed wording with its security line, the code's expiry, and a copy-code button.
    https://developers.facebook.com/docs/whatsapp/business-management-api/authentication-templates
    """
    return {
        "category": "AUTHENTICATION",
        "language": LINK_TEMPLATE_LANGUAGE,
        "components": [
            {"type": "BODY", "add_security_recommendation": True},
            {"type": "FOOTER", "code_expiration_minutes": settings.WHATSAPP_LINK_CODE_TTL_SECONDS // 60},
            {"type": "BUTTONS", "buttons": [{"type": "OTP", "otp_type": "COPY_CODE", "text": "Copy code"}]},
        ],
    }


def publish_link_template(account):
    """Submit the link code template to the team number's WhatsApp Business account, if it changed."""
    from . import templates

    return templates.submit(account, LINK_TEMPLATE, **link_template())


def start_link(user, tenant, typed_number: str) -> LinkStarted:
    """
    Issue a link code for the number `user` typed on their profile, in any common format (D19), to
    link it on `tenant`'s internal communications number. With PHONE_VERIFICATION_CHANNEL set to
    WHATSAPP_TEMPLATE, the code is sent to that number from the team number instead of shown.
    """
    if tenant is None or not is_member(user, tenant):
        # The same answer as for an organization that doesn't exist.
        raise IdentityError("Organization not found.", "not_found")
    internal = WhatsAppAccount.objects.internal_for(tenant)
    if internal is None:
        raise IdentityError(f"{tenant.name} hasn't connected an internal communications number yet.", "not_available")
    try:
        number = normalize_phone_number(typed_number)
    except InvalidPhoneNumber as error:
        raise IdentityError(str(error), "invalid_phone_number") from error

    linked = WhatsAppIdentity.objects.filter(account=internal, contact__wa_id=number).first()
    if linked is not None and linked.user_id != user.pk:
        raise IdentityError("This number is already linked to another account.", "linked_elsewhere")

    if settings.PHONE_VERIFICATION_CHANNEL == Channel.WHATSAPP_TEMPLATE:
        return _send_code(user, tenant, internal, number)

    issued = issue_code(
        user=user,
        phone_number=number,
        channel=Channel.WHATSAPP_INBOUND,
        ttl_seconds=settings.WHATSAPP_LINK_CODE_TTL_SECONDS,
    )
    internal_number = re.sub(r"\D", "", internal.display_phone_number)
    # WhatsApp's "click to chat" link, wa.me/<international number, digits only>?text=<message>:
    # https://faq.whatsapp.com/5913398998672934. That page's text couldn't be fetched to confirm the
    # format (2026-10-18); the human check for the profile page (Step 1.14) opens the link for real.
    return LinkStarted(
        code=issued.code,
        phone_number=number,
        link=f"https://wa.me/{internal_number}?text=link%20{issued.code}",
        expires_at=issued.expires_at,
    )


def _send_code(user, tenant, internal, number: str) -> LinkStarted:
    """Issue a code on the WHATSAPP_TEMPLATE channel and send it from the team number; the page gets none."""
    issued = issue_code(
        user=user,
        phone_number=number,
        channel=Channel.WHATSAPP_TEMPLATE,
        ttl_seconds=settings.WHATSAPP_LINK_CODE_TTL_SECONDS,
    )
    # The code fills the body's blank and the copy-code button's.
    message = template_message(
        LINK_TEMPLATE, language=LINK_TEMPLATE_LANGUAGE, body=[issued.code], url_suffix=issued.code
    )
    try:
        send_backend().send_message_to(internal, number, message)
    except SendError as error:
        # Meta's words go to the log, never the code; the member is told what to do.
        logger.warning("WhatsApp account id=%s: the link code couldn't be sent: %s", internal.pk, error)
        raise IdentityError(
            f"The code couldn't be sent from {tenant.name}'s WhatsApp number. Ask an admin to check its templates "
            "on the WhatsApp page, then try again.",
            "not_sent",
        ) from error
    return LinkStarted(
        code="", phone_number=number, link="", expires_at=issued.expires_at, channel=Channel.WHATSAPP_TEMPLATE
    )


def confirm_link(user, tenant, typed_number: str, code: str) -> str:
    """
    Use the code `user` received on WhatsApp and typed on their profile (phase 7). Returns LINKED when the phone
    has written to the team number before, so it's linked now, or WAITING when it will be linked once it first
    writes, within WAITING_LINK_DAYS. Raises IdentityError when the code doesn't prove the number.
    """
    if tenant is None or not is_member(user, tenant):
        raise IdentityError("Organization not found.", "not_found")
    internal = WhatsAppAccount.objects.internal_for(tenant)
    if internal is None:
        raise IdentityError(f"{tenant.name} hasn't connected an internal communications number yet.", "not_available")
    try:
        number = normalize_phone_number(typed_number)
    except InvalidPhoneNumber as error:
        raise IdentityError(str(error), "invalid_phone_number") from error
    try:
        owner = check_code(phone_number=number, channel=Channel.WHATSAPP_TEMPLATE, code=code)
    except CodeCheckError as error:
        raise IdentityError("That code isn't right. Check it, or ask for a new one.", error.code) from error
    if owner.pk != user.pk:
        raise IdentityError("That code isn't right. Check it, or ask for a new one.", "wrong_code")

    with transaction.atomic():
        contact = WhatsAppContact.objects.filter(account=internal, wa_id=number).first()
        if contact is not None:
            _attach(user, contact)
            WhatsAppWaitingLink.objects.filter(user=user, account=internal).delete()
            return LINKED
        # Another member's waiting link for this phone is replaced: the phone was proved for this one now.
        WhatsAppWaitingLink.objects.filter(account=internal, phone_number=number).exclude(user=user).delete()
        WhatsAppWaitingLink.objects.update_or_create(user=user, account=internal, defaults={"phone_number": number})
    return WAITING


def waiting_link_for(user, account) -> WhatsAppWaitingLink | None:
    """The user's waiting link on the team number, while it lasts."""
    return _current_waiting_links().filter(user=user, account=account).first()


def is_link_command(text: str) -> bool:
    """Whether `text` is "link <code>", which links on any number the team texts."""
    return LINK_COMMAND.match(text or "") is not None


def handle_unlinked_message(contact, text: str) -> list[dict]:
    """
    The reply to anything an unlinked contact sends: a link command is tried; everything else gets
    no reply. Returns the messages to queue (builders.py output).
    """
    match = LINK_COMMAND.match(text or "")
    if match is None:
        return []
    try:
        user = _link(contact, match.group(1))
    except IdentityError as error:
        return text_reply(f"{error} Get a new code on your profile page: {_profile_url()}")
    return text_reply(
        f"Your WhatsApp number is now linked to your account ({user.email}) for {contact.account.tenant.name}."
    )


def unlink(user, account) -> None:
    """
    Remove the user's link on one internal number, from the profile page or by sending `unlink`.
    The contact is kept.
    """
    for linked in WhatsAppIdentity.objects.filter(user=user, account=account).select_related("contact"):
        forget_conversation(linked.contact)
        linked.delete()


def forget_conversation(contact) -> None:
    """Forget what the contact's conversation holds; only the button id counter stays."""
    conversation = WhatsAppConversation.objects.filter(contact=contact).first()
    if conversation is None:
        return
    history.forget(conversation)
    confirmations.discard_pending(conversation)
    conversation.tenant = None
    conversation.state = {"next_choice": conversation.state.get("next_choice", 1)}
    conversation.save(update_fields=["tenant", "state", "updated_at"])


def identity_for(contact) -> WhatsAppIdentity | None:
    """
    The link of a contact on an internal number, while its user is still a member of the number's
    organization; None for anyone else.
    """
    linked = WhatsAppIdentity.objects.filter(contact=contact).select_related("user", "account").first()
    if linked is None:
        # A phone proved with a typed code is linked when it first writes (phase 7).
        linked = _complete_waiting_link(contact)
    if linked is None or not is_member(linked.user, linked.account.tenant):
        return None
    return linked


def is_member(user, tenant) -> bool:
    """True when `user` has accepted membership of `tenant`; an invitation isn't membership."""
    return TenantMembership.objects.filter(user=user, tenant=tenant).exists()


@transaction.atomic
def _link(contact, code: str):
    account = contact.account
    if not AccountPurpose.serves_team(account.purpose) or not contact.wa_id:
        # Linking happens on the number the team texts only (internal, or serving both since Step 2.7),
        # and Meta must have told us the sender's number.
        raise IdentityError("That code didn't work.", "no_code")
    try:
        user = check_code(phone_number=contact.wa_id, channel=Channel.WHATSAPP_INBOUND, code=code)
    except CodeCheckError as error:
        raise IdentityError("That code didn't work.", error.code) from error
    if not is_member(user, account.tenant):
        raise IdentityError(f"Your account is not a member of {account.tenant.name}.", "not_a_member")
    _attach(user, contact)
    return user


def _attach(user, contact) -> WhatsAppIdentity:
    """Link `user` on the contact's number, moving any other phone of theirs there, from a fresh conversation."""
    account = contact.account
    linked = WhatsAppIdentity.objects.filter(contact=contact).first()
    if linked is not None and linked.user_id != user.pk:
        raise IdentityError("This number is already linked to another account.", "linked_elsewhere")
    # A user has one linked phone per number: linking another one there moves the link.
    for moved in (
        WhatsAppIdentity.objects.filter(user=user, account=account).exclude(contact=contact).select_related("contact")
    ):
        forget_conversation(moved.contact)
        moved.delete()
    forget_conversation(contact)
    attached, _ = WhatsAppIdentity.objects.get_or_create(user=user, contact=contact, defaults={"account": account})
    return attached


def _current_waiting_links():
    return WhatsAppWaitingLink.objects.filter(created_at__gt=timezone.now() - timedelta(days=WAITING_LINK_DAYS))


@transaction.atomic
def _complete_waiting_link(contact) -> WhatsAppIdentity | None:
    """Link the phone a member proved with a typed code, now that it has written; None when none waits for it."""
    if not contact.wa_id or not AccountPurpose.serves_team(contact.account.purpose):
        return None
    waiting = (
        _current_waiting_links()
        .select_for_update()
        .select_related("user")
        .filter(account=contact.account, phone_number=contact.wa_id)
        .first()
    )
    if waiting is None:
        return None
    user = waiting.user
    waiting.delete()
    if not is_member(user, contact.account.tenant):
        return None
    try:
        return _attach(user, contact)
    except IdentityError:
        return None


def _profile_url() -> str:
    return f"{settings.WEB_APP_URL.rstrip('/')}/profile"
