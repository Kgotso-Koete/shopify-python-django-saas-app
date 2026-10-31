"""
Linking a user's phone on an organization's internal communications number (plan Step 1.7,
decision D3, user stories 1 and 2, Step 1.17).

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
"""

import re
from dataclasses import dataclass
from datetime import datetime

from django.conf import settings
from django.db import transaction

from apps.multitenancy.models import TenantMembership
from apps.phone_verification.constants import Channel
from apps.phone_verification.services import CodeCheckError, check_code, issue_code

from ..agent import history
from ..builders import text_reply
from ..constants import AccountPurpose
from ..models import WhatsAppAccount, WhatsAppConversation, WhatsAppIdentity
from ..phone_numbers import InvalidPhoneNumber, normalize_phone_number
from . import confirmations

# "link 123456", in any case, with any spacing.
LINK_COMMAND = re.compile(r"^\s*link\s+(\d{6})\s*$", re.IGNORECASE)


class IdentityError(Exception):
    """Linking can't start. `code` is for the web app; the message is for the user."""

    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class LinkStarted:
    """What the profile page shows: the code, and a wa.me link that opens the chat with it typed."""

    code: str
    phone_number: str
    link: str
    expires_at: datetime


def start_link(user, tenant, typed_number: str) -> LinkStarted:
    """
    Issue a link code for the number `user` typed on their profile, in any common format (D19), to
    link it on `tenant`'s internal communications number.
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
    WhatsAppIdentity.objects.get_or_create(user=user, contact=contact, defaults={"account": account})
    return user


def _profile_url() -> str:
    return f"{settings.WEB_APP_URL.rstrip('/')}/profile"
