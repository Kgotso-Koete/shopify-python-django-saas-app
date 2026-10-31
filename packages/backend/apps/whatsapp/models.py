"""
WhatsApp models (plan section 8.2).

A WhatsAppAccount is one WhatsApp number this app sends and receives on; a WhatsAppContact is
someone who texted one of those numbers. More models (messages, conversations, identities) are
added by later steps of docs/superpowers/plans/2026-10-06-whatsapp-first-channel-plan.md.
"""

import hashid_field
from django.conf import settings
from django.db import models
from django.db.models import Q

from common.models import TimestampedMixin

from .constants import (
    AccountPurpose,
    ConnectionMethod,
    ConversationMode,
    MessageDirection,
    MessageKind,
    MessageStatus,
    TEAM_PURPOSES,
)
from .crypto import decrypt_credential, encrypt_credential
from .managers import WhatsAppAccountManager


class WhatsAppAccount(TimestampedMixin, models.Model):
    """
    One WhatsApp Business number of an organization (plan Step 1.17): its internal communications
    number, which its team texts, or an external communications number, which its store customers
    text. Inbound events are routed to an account by `phone_number_id` (plan decision D6).
    Credentials are stored encrypted (D5).
    """

    # A hashid, like CrudDemoItem's, because accounts are exposed through GraphQL (plan Step 1.5).
    id = hashid_field.HashidAutoField(primary_key=True)
    # Long enough for INTERNAL_AND_EXTERNAL_COMMUNICATIONS (plan Step 2.7).
    purpose = models.CharField(max_length=40, choices=AccountPurpose.choices)
    # Every number is connected on an organization's WhatsApp tab. Deleting the organization deletes
    # its numbers, credentials included.
    tenant = models.ForeignKey(
        "multitenancy.Tenant",
        on_delete=models.CASCADE,
        related_name="whatsapp_accounts",
    )
    # The number people see and text, as Meta shows it.
    display_phone_number = models.CharField(max_length=32, blank=True)
    # Meta's id for the number; every webhook event names it in metadata.phone_number_id:
    # https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/reference/messages.md
    phone_number_id = models.CharField(max_length=64, unique=True)
    # Meta's id for the WhatsApp Business account the number belongs to.
    waba_id = models.CharField(max_length=64)
    # Read and written through the `access_token` property below, never directly. Empty once the
    # number is disconnected. Every number is on our one Meta app, whose App secret and verify token
    # are settings (plan Step 1.18).
    access_token_encrypted = models.TextField(blank=True)
    # When Meta last subscribed our app to the number's WhatsApp Business account, so its messages
    # reach our webhook: the form's second proof (user story 11, Step 1.18).
    subscribed_at = models.DateTimeField(null=True, blank=True)
    # The business name Meta verified for the number, as Meta returned it when the account was checked.
    verified_name = models.CharField(max_length=255, blank=True)
    connection_method = models.CharField(
        max_length=32, choices=ConnectionMethod.choices, default=ConnectionMethod.MANUAL
    )
    # When Meta last accepted this account's id and token: the form's first proof (user story 11).
    credentials_verified_at = models.DateTimeField(null=True, blank=True)
    # False once the organization disconnects the number: its secrets are wiped, its history kept, and
    # the webhook treats it as a number it doesn't know (plan Step 1.5, maintainer's decision).
    is_active = models.BooleanField(default=True)

    objects = WhatsAppAccountManager()

    class Meta:
        constraints = [
            # An organization's team texts one number (Step 1.17), internal or serving both (Step 2.7); a
            # disconnected one doesn't count.
            models.UniqueConstraint(
                fields=["tenant"],
                condition=Q(purpose__in=TEAM_PURPOSES, is_active=True),
                name="whatsapp_account_one_active_team_number_per_tenant",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.display_phone_number or self.phone_number_id} ({self.get_purpose_display()})"

    @property
    def access_token(self) -> str:
        """The plain-text access token; raises CredentialDecryptionError if the key has changed."""
        return decrypt_credential(self.access_token_encrypted)

    @access_token.setter
    def access_token(self, value: str) -> None:
        self.access_token_encrypted = encrypt_credential(value)


class WhatsAppContact(TimestampedMixin, models.Model):
    """
    Someone who texted a WhatsApp number (plan decision D4): a team member on an organization's
    internal number, or a store customer on an external one. Scoped to one account, so the same
    person texting two organizations is two contacts.
    """

    account = models.ForeignKey(WhatsAppAccount, on_delete=models.CASCADE, related_name="contacts")
    # Meta's business-scoped user id (contacts[].user_id, messages[].from_user_id), e.g.
    # "US.13491208655302741918": a country code and a period ("US.ENT." for parent ids), then up
    # to 128 alphanumeric characters, so up to 135 in all. Always present, so it's the contact's
    # key; it changes only if the user changes number:
    # https://developers.facebook.com/documentation/business-messaging/whatsapp/business-scoped-user-ids
    bsuid = models.CharField(max_length=150)
    # The phone number, digits only (e.g. "27831234567"). Meta omits it for some users with
    # usernames, so it can be empty (same page as bsuid above).
    wa_id = models.CharField(max_length=32, blank=True)
    # The name the person set in WhatsApp: for display only, never proof of who they are.
    profile_name = models.CharField(max_length=255, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["account", "bsuid"], name="whatsapp_contact_unique_bsuid_per_account"),
            # Unique only when known, so several contacts without a phone number can coexist.
            models.UniqueConstraint(
                fields=["account", "wa_id"],
                condition=~Q(wa_id=""),
                name="whatsapp_contact_unique_wa_id_per_account",
            ),
            models.CheckConstraint(condition=~Q(bsuid=""), name="whatsapp_contact_bsuid_not_empty"),
        ]

    def __str__(self) -> str:
        return self.profile_name or self.wa_id or self.bsuid


class WhatsAppIdentity(TimestampedMixin, models.Model):
    """
    A user's phone, linked on one organization's internal number (plan decision D3, user story 1,
    Step 1.17): one per user per internal number, and one-to-one with the contact. The upstream User
    model is untouched. Created only when both proofs meet: a code issued to the logged-in user, sent
    from the phone (Step 1.7).
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="whatsapp_identities")
    # The internal number the phone was linked on: always the contact's own account, stored here so the
    # database can keep one link per user per number.
    account = models.ForeignKey(WhatsAppAccount, on_delete=models.CASCADE, related_name="identities")
    contact = models.OneToOneField(WhatsAppContact, on_delete=models.CASCADE, related_name="identity")
    # How the user wants to talk to the app; empty means WHATSAPP_DEFAULT_CONVERSATION_MODE (user story 3).
    conversation_mode = models.CharField(max_length=32, choices=ConversationMode.choices, blank=True)
    linked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "account"], name="whatsapp_identity_unique_user_per_account")
        ]

    def __str__(self) -> str:
        return f"{self.user} on WhatsApp ({self.contact})"


class WhatsAppConversation(TimestampedMixin, models.Model):
    """
    One per contact (plan section 8.2): where they are in the menus. `state` holds the choice map
    (each button's opaque id and what it stands for, section 8.5), paging cursors and half-filled
    forms, and expires after WHATSAPP_CONVERSATION_TTL_SECONDS of silence.
    """

    contact = models.OneToOneField(WhatsAppContact, on_delete=models.CASCADE, related_name="conversation")
    # The organization the conversation works in: the number's, set by the router on every message
    # (Step 1.17). Every action still rechecks the user's membership.
    tenant = models.ForeignKey(
        "multitenancy.Tenant", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    state = models.JSONField(default=dict, blank=True)
    state_expires_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"Conversation with {self.contact}"


class WhatsAppPendingAction(TimestampedMixin, models.Model):
    """
    A write waiting for the user's Confirm (plan decision D11): the exact action and arguments, who
    asked and for which organization, and until when. Runs at most once; Cancel, expiry, a mode
    switch or `cancel` consume it without running it.
    """

    conversation = models.ForeignKey(WhatsAppConversation, on_delete=models.CASCADE, related_name="pending_actions")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    tenant = models.ForeignKey("multitenancy.Tenant", null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    # A name registered with services.confirmations.register_action, e.g. "items.create".
    action = models.CharField(max_length=64)
    # Validated values only, never free text the model invented (D10, D11).
    arguments = models.JSONField(default=dict, blank=True)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"{self.action} for {self.user}"


class WhatsAppFlow(TimestampedMixin, models.Model):
    """
    One published WhatsApp Flow (a form) on a WhatsApp Business account (plan Step 1.11, D9): which
    form it is, Meta's id for it, and a hash of the JSON it was published from, so the publish
    command publishes a form again only when its file changed. Flows belong to the WhatsApp Business
    account, not to one number.
    """

    waba_id = models.CharField(max_length=64)
    # The form's file name, e.g. "item" for apps/whatsapp_saas/flows/item.json.
    name = models.CharField(max_length=64)
    flow_id = models.CharField(max_length=64)
    json_sha256 = models.CharField(max_length=64)
    published_at = models.DateTimeField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["waba_id", "name"], name="whatsapp_flow_unique_name_per_waba")]

    def __str__(self) -> str:
        return f"{self.name} ({self.flow_id})"


class WhatsAppAgentItem(TimestampedMixin, models.Model):
    """
    One item of the assistant's history in a conversation (plan Step 1.13, D12): a user's or the
    assistant's message, a function call, or its output, in the Responses API's input shape. OpenAI
    is sent store: false, so this is the only copy. Kept until cancel, a mode switch or unlink
    (maintainer's choice, 2026-10-20); each request sends the last 20 user turns of it.
    """

    conversation = models.ForeignKey(WhatsAppConversation, on_delete=models.CASCADE, related_name="agent_items")
    # Order within the conversation, counting up from 1.
    sequence = models.PositiveIntegerField()
    item = models.JSONField()

    class Meta:
        ordering = ["sequence"]
        constraints = [
            models.UniqueConstraint(fields=["conversation", "sequence"], name="whatsapp_agent_item_unique_sequence")
        ]

    def __str__(self) -> str:
        return f"Item {self.sequence} of {self.conversation}"


class WhatsAppMessage(TimestampedMixin, models.Model):
    """
    One message in or out of a conversation with a contact (plan section 8.2). Inbound and
    outbound share this table, so a conversation's history (and phase 5's transcript) is one query.
    Outbound rows double as the send queue (D8).
    """

    # Deleting a contact deletes its messages; the account is reached through the contact.
    contact = models.ForeignKey(WhatsAppContact, on_delete=models.CASCADE, related_name="messages")
    direction = models.CharField(max_length=8, choices=MessageDirection.choices)
    # Meta's message id ("wamid..."): messages[].id inbound, or the id Meta returns when we send.
    # Empty for an outbound message still queued. Unique when set, so a webhook Meta retries is
    # stored once (D7): https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/overview.md
    wamid = models.CharField(max_length=255, blank=True)
    kind = models.CharField(max_length=32, choices=MessageKind.choices)
    # Only what processing needs (the text, a button id, a Flow's answers), never the whole body.
    payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=16, choices=MessageStatus.choices)
    # Meta's error code when status is FAILED, e.g. 131047 (the 24-hour window closed).
    error_code = models.IntegerField(null=True, blank=True)
    # When Meta says the message was sent (its Unix timestamp), as opposed to when we stored it.
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["wamid"],
                condition=~Q(wamid=""),
                name="whatsapp_message_unique_wamid",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.get_direction_display()} {self.get_kind_display()} {self.wamid or '(queued)'}"
