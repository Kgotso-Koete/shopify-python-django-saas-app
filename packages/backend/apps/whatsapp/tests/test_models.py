"""
Tests for the WhatsApp account, contact and identity models (plan section 8.2, decisions D4 and D5,
Step 1.17).

A WhatsAppAccount is one WhatsApp number this app sends and receives on, and it always belongs to an
organization: its internal communications number, which its team texts, or an external communications
number, which its store customers text. A WhatsAppContact is someone who texted one of those numbers.

Kind of test: integration (agents.md section 2.5). Why: rows and the database's own constraints are
checked in the test database; nothing is faked.
"""

from datetime import datetime, timezone

import pytest
from cryptography.fernet import Fernet
from django.conf import settings
from django.db import IntegrityError, transaction

from apps.multitenancy.constants import TenantType
from apps.multitenancy.tests.factories import TenantFactory
from apps.users.tests.factories import UserFactory

from ..constants import AccountPurpose, MessageDirection, MessageKind, MessageStatus
from ..crypto import CredentialDecryptionError
from ..models import WhatsAppAccount, WhatsAppContact, WhatsAppIdentity, WhatsAppMessage
from .factories import ContactFactory, ExternalAccountFactory, InternalAccountFactory, MessageFactory

pytestmark = pytest.mark.django_db


class TestEveryNumberBelongsToAnOrganization:
    """Step 1.17: every number is connected on an organization's WhatsApp tab, so it has one."""

    def test_an_internal_number_belongs_to_an_organization(self):
        account = InternalAccountFactory()

        assert account.purpose == AccountPurpose.INTERNAL_COMMUNICATIONS
        assert account.tenant is not None

    def test_an_external_number_belongs_to_an_organization(self):
        account = ExternalAccountFactory()

        assert account.purpose == AccountPurpose.EXTERNAL_COMMUNICATIONS
        assert account.tenant is not None

    @pytest.mark.parametrize("factory", [InternalAccountFactory, ExternalAccountFactory])
    def test_a_number_without_an_organization_is_refused_by_the_database(self, factory):
        # The rule is in the database, so no code path (admin, shell, a bug) can break it.
        # transaction.atomic() keeps the failed insert from spoiling the rest of the test.
        with pytest.raises(IntegrityError), transaction.atomic():
            factory(tenant=None)

    def test_deleting_an_organization_deletes_its_numbers(self):
        # An organization's number can't outlive it: its credentials would belong to no one.
        account = ExternalAccountFactory()

        account.tenant.delete()

        assert not WhatsAppAccount.objects.filter(pk=account.pk).exists()


class TestOneInternalNumberPerOrganization:
    """Step 1.17: an organization's team texts one number, so it has at most one active internal number."""

    def test_a_second_active_internal_number_is_refused_by_the_database(self):
        first = InternalAccountFactory()

        with pytest.raises(IntegrityError), transaction.atomic():
            InternalAccountFactory(tenant=first.tenant)

    def test_a_disconnected_one_doesnt_count(self):
        first = InternalAccountFactory(is_active=False)

        second = InternalAccountFactory(tenant=first.tenant)

        assert second.pk != first.pk

    def test_two_organizations_have_one_each(self):
        InternalAccountFactory()
        InternalAccountFactory()

        assert WhatsAppAccount.objects.filter(purpose=AccountPurpose.INTERNAL_COMMUNICATIONS).count() == 2

    def test_an_organization_may_have_several_external_numbers(self):
        first = ExternalAccountFactory()

        ExternalAccountFactory(tenant=first.tenant)

        assert first.tenant.whatsapp_accounts.count() == 2

    def test_an_internal_and_an_external_number_can_share_an_organization(self):
        internal = InternalAccountFactory()

        ExternalAccountFactory(tenant=internal.tenant)

        assert internal.tenant.whatsapp_accounts.count() == 2


class TestFindingAnOrganizationsInternalNumber:
    def test_it_is_the_organizations_active_internal_number(self):
        organization = TenantFactory(type=TenantType.ORGANIZATION)
        InternalAccountFactory(tenant=organization, is_active=False)
        ExternalAccountFactory(tenant=organization)
        InternalAccountFactory()
        active = InternalAccountFactory(tenant=organization)

        assert WhatsAppAccount.objects.internal_for(organization) == active

    def test_without_one_there_is_none(self):
        organization = TenantFactory(type=TenantType.ORGANIZATION)
        ExternalAccountFactory(tenant=organization)

        assert WhatsAppAccount.objects.internal_for(organization) is None

    def test_there_is_no_platform_number_anymore(self):
        assert not hasattr(WhatsAppAccount.objects, "platform")


class TestPhoneNumberId:
    def test_a_phone_number_id_belongs_to_one_account_only(self):
        # The webhook routes each event by its receiving phone_number_id (D6), so two accounts
        # with the same one would make routing ambiguous.
        InternalAccountFactory(phone_number_id="100000000000777")

        with pytest.raises(IntegrityError), transaction.atomic():
            ExternalAccountFactory(phone_number_id="100000000000777")


class TestEncryptedCredentials:
    """D5: credentials are stored encrypted and read back as plain text."""

    def test_the_access_token_is_encrypted_at_rest(self):
        account = InternalAccountFactory(access_token="EAAGtest-access-token")

        # Read the raw column straight from the database, not through the model's property.
        stored = WhatsAppAccount.objects.values_list("access_token_encrypted", flat=True).get(pk=account.pk)
        assert stored != "EAAGtest-access-token"
        assert "EAAGtest-access-token" not in stored

        account.refresh_from_db()
        assert account.access_token == "EAAGtest-access-token"

    def test_a_number_holds_no_meta_app_secret_or_verify_token(self):
        # Every number is on our one Meta app, whose secret and token are settings (Step 1.18).
        fields = {field.name for field in WhatsAppAccount._meta.get_fields()}

        assert not fields & {"app_secret_encrypted", "webhook_verify_token_hash", "webhook_verified_at"}
        assert "subscribed_at" in fields
        assert not hasattr(WhatsAppAccount.objects, "find_by_verify_token")

    def test_a_credential_stored_with_another_key_raises_a_clear_error(self, monkeypatch):
        account = InternalAccountFactory(access_token="EAAGtest-access-token")

        monkeypatch.setattr(settings, "WHATSAPP_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))
        account.refresh_from_db()

        # Never a quiet empty token: sending with it would fail far from the real cause.
        with pytest.raises(CredentialDecryptionError):
            account.access_token


class TestContacts:
    """D4: every sender is a contact, scoped to the number they texted."""

    def test_a_contact_is_unique_per_account_on_its_business_scoped_user_id(self):
        contact = ContactFactory()

        with pytest.raises(IntegrityError), transaction.atomic():
            ContactFactory(account=contact.account, bsuid=contact.bsuid)

    def test_a_contact_must_have_a_business_scoped_user_id(self):
        # Meta sends user_id with every message (plan section 6.1); it's the contact's key.
        with pytest.raises(IntegrityError), transaction.atomic():
            ContactFactory(bsuid="")

    def test_a_maximum_length_business_scoped_user_id_fits(self):
        # Meta's ids are a country code and a period, plus "ENT." for parent ids, then up to 128
        # alphanumeric characters:
        # https://developers.facebook.com/documentation/business-messaging/whatsapp/business-scoped-user-ids
        longest = "US.ENT." + "1" * 128

        contact = ContactFactory(bsuid=longest)
        contact.refresh_from_db()

        assert contact.bsuid == longest

    def test_a_phone_number_is_unique_per_account_when_known(self):
        contact = ContactFactory()

        with pytest.raises(IntegrityError), transaction.atomic():
            ContactFactory(account=contact.account, wa_id=contact.wa_id)

    def test_several_contacts_without_a_phone_number_are_allowed(self):
        # Meta omits wa_id for some users with usernames, so an unknown phone is normal.
        account = InternalAccountFactory()

        ContactFactory(account=account, wa_id="")
        ContactFactory(account=account, wa_id="")

        assert WhatsAppContact.objects.filter(account=account, wa_id="").count() == 2

    def test_the_same_phone_texting_two_numbers_is_two_contacts(self):
        # The same person texting two organizations' stores is two separate contacts, one per
        # organization, so no organization ever sees the other's conversation (D4).
        first = ContactFactory(account=ExternalAccountFactory(), wa_id="27000001999")
        second = ContactFactory(account=ExternalAccountFactory(), wa_id="27000001999")

        assert first.pk != second.pk
        assert first.account.tenant != second.account.tenant

    def test_deleting_an_account_deletes_its_contacts(self):
        contact = ContactFactory()

        contact.account.delete()

        assert not WhatsAppContact.objects.filter(pk=contact.pk).exists()


class TestMessages:
    """Every message in and out, stored once (plan section 8.2 and decision D7)."""

    def test_a_message_stores_what_the_webhook_needs(self):
        sent_at = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)

        message = MessageFactory(
            direction=MessageDirection.INBOUND,
            wamid="wamid.HELLO",
            kind=MessageKind.BUTTON_REPLY,
            payload={"action_id": "c7", "text": "Main menu"},
            status=MessageStatus.RECEIVED,
            sent_at=sent_at,
        )
        message.refresh_from_db()

        assert message.direction == MessageDirection.INBOUND
        assert message.wamid == "wamid.HELLO"
        assert message.kind == MessageKind.BUTTON_REPLY
        assert message.payload == {"action_id": "c7", "text": "Main menu"}
        assert message.status == MessageStatus.RECEIVED
        assert message.sent_at == sent_at
        # Set only when Meta reports a failure, e.g. 131047 (the 24-hour window closed).
        assert message.error_code is None

    def test_a_message_id_from_meta_is_stored_once(self):
        # Meta retries a webhook it thinks failed, so the same message can arrive twice (D7). The
        # unique id is what makes the second one a duplicate instead of a second action.
        first = MessageFactory(wamid="wamid.RETRIED")

        with pytest.raises(IntegrityError), transaction.atomic():
            MessageFactory(contact=first.contact, wamid="wamid.RETRIED")

    def test_outbound_messages_may_wait_without_an_id(self):
        # Queued replies get Meta's id only once they're sent (D8), so many can have none yet.
        contact = ContactFactory()

        MessageFactory(contact=contact, direction=MessageDirection.OUTBOUND, wamid="", status=MessageStatus.QUEUED)
        MessageFactory(contact=contact, direction=MessageDirection.OUTBOUND, wamid="", status=MessageStatus.QUEUED)

        assert WhatsAppMessage.objects.filter(contact=contact, wamid="").count() == 2

    def test_unsupported_is_a_kind_a_message_can_be_stored_as(self):
        # Messages of a type we don't handle are stored too, so they're never silently lost.
        message = MessageFactory(kind=MessageKind.UNSUPPORTED, payload={"message_type": "sticker"})

        message.refresh_from_db()
        assert message.kind == MessageKind.UNSUPPORTED

    def test_deleting_a_contact_deletes_its_messages(self):
        message = MessageFactory()

        message.contact.delete()

        assert not WhatsAppMessage.objects.filter(pk=message.pk).exists()


class TestIdentities:
    """Step 1.17: a user links their phone once per internal number, so once per organization."""

    def test_an_identity_names_the_internal_number_it_was_linked_on(self):
        contact = ContactFactory()

        identity = WhatsAppIdentity.objects.create(user=UserFactory(), contact=contact, account=contact.account)

        assert identity.account == contact.account

    def test_a_user_can_link_on_two_organizations_numbers(self):
        user = UserFactory()
        first, second = ContactFactory(), ContactFactory()

        WhatsAppIdentity.objects.create(user=user, contact=first, account=first.account)
        WhatsAppIdentity.objects.create(user=user, contact=second, account=second.account)

        assert WhatsAppIdentity.objects.filter(user=user).count() == 2

    def test_a_user_has_one_link_per_number(self):
        user = UserFactory()
        account = InternalAccountFactory()
        first, second = ContactFactory(account=account), ContactFactory(account=account)
        WhatsAppIdentity.objects.create(user=user, contact=first, account=account)

        with pytest.raises(IntegrityError), transaction.atomic():
            WhatsAppIdentity.objects.create(user=user, contact=second, account=account)

    def test_a_phone_on_a_number_is_one_users_only(self):
        contact = ContactFactory()
        WhatsAppIdentity.objects.create(user=UserFactory(), contact=contact, account=contact.account)

        with pytest.raises(IntegrityError), transaction.atomic():
            WhatsAppIdentity.objects.create(user=UserFactory(), contact=contact, account=contact.account)
