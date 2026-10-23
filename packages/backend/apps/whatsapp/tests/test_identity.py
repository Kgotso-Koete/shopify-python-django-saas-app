"""
Tests for apps/whatsapp/services/identity.py: linking a user's phone on an organization's internal
communications number (plan Step 1.7b, decision D3, user stories 1 and 2, Step 1.17).

Linking needs two proofs at once: the logged-in web session names the account (start_link issues
a code for the number typed on the profile), and Meta's signed webhook proves the phone (the code
must come back *from that phone*, as "link 123456"). The code store is apps.phone_verification,
with the WHATSAPP_INBOUND channel (D20).

- the profile page chooses the organization: the code opens a chat with its internal number, and
  only a member of it can link there
- a user has one link per internal number, so a member of two organizations links on each
- anyone who isn't linked gets no reply, except to "link <code>" (maintainer's decision, 2026-10-22)
- a phone linked to another account on that number is refused
- `unlink` removes the link on one number
- unlinking, and linking a phone afresh, forget its conversation: the menus, the assistant's history
  and unconfirmed writes (Step 1.13)

Kind of test: integration (agents.md section 2.5). Why: identities, contacts, memberships and codes
are rows in the test database; nothing is faked.
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.multitenancy.constants import TenantType, TenantUserRole
from apps.multitenancy.models import TenantMembership
from apps.multitenancy.tests.factories import TenantFactory, TenantMembershipFactory
from apps.phone_verification.models import PhoneVerificationCode
from apps.users.tests.factories import UserFactory

from ..agent import history
from ..models import WhatsAppAgentItem, WhatsAppConversation, WhatsAppIdentity, WhatsAppPendingAction
from ..services import identity
from ..services.identity import IdentityError
from .factories import ContactFactory, ExternalAccountFactory, InternalAccountFactory

pytestmark = pytest.mark.django_db

NUMBER = "27831234567"


@pytest.fixture(autouse=True)
def web_app_url(settings):
    settings.WEB_APP_URL = "https://app.example.com"


@pytest.fixture
def acme():
    return TenantFactory(type=TenantType.ORGANIZATION, name="Acme")


@pytest.fixture
def internal(acme):
    """Acme's internal communications number, the one its team texts."""
    return InternalAccountFactory(tenant=acme, display_phone_number="+27 00 000 0000")


@pytest.fixture
def user(acme):
    user = UserFactory()
    TenantMembershipFactory(user=user, tenant=acme, role=TenantUserRole.MEMBER)
    return user


@pytest.fixture
def sender(internal):
    """The person texting Acme's internal number from NUMBER."""
    return ContactFactory(account=internal, wa_id=NUMBER)


def link(user, contact):
    return WhatsAppIdentity.objects.create(user=user, contact=contact, account=contact.account)


def conversation_of(contact, user, *, linked=True):
    """A conversation as `user` leaves it: menus, history and a pending write."""
    if linked:
        link(user, contact)
    tenant = contact.account.tenant
    conversation = WhatsAppConversation.objects.create(
        contact=contact, tenant=tenant, state={"next_choice": 9, "choices": {"c8": {"kind": "items", "data": {}}}}
    )
    history.append(conversation, {"role": "user", "content": "rename Acme"})
    WhatsAppPendingAction.objects.create(
        conversation=conversation,
        user=user,
        tenant=tenant,
        action="organizations.rename",
        arguments={"name": "Acme Holdings"},
        expires_at=timezone.now() + timedelta(minutes=30),
    )
    return conversation


def assert_forgotten(conversation):
    conversation.refresh_from_db()
    # Only the id counter stays, so old buttons never mean something new.
    assert conversation.state == {"next_choice": 9}
    assert not WhatsAppAgentItem.objects.filter(conversation=conversation).exists()
    assert WhatsAppPendingAction.objects.get(conversation=conversation).consumed_at is not None


def bodies(messages):
    """The text of each reply, whatever kind of message carries it."""
    texts = []
    for message in messages:
        if message["type"] == "text":
            texts.append(message["text"]["body"])
        else:
            texts.append(message["interactive"]["body"]["text"])
    return texts


class TestStartingALink:
    def test_the_typed_number_is_normalized_and_a_code_issued_for_it(self, acme, internal, user):
        started = identity.start_link(user, acme, "083 123 4567")

        assert started.phone_number == NUMBER
        assert len(started.code) == 6
        code_row = PhoneVerificationCode.objects.get(user=user)
        assert code_row.phone_number == NUMBER
        assert code_row.channel == "WHATSAPP_INBOUND"

    def test_the_link_opens_a_chat_with_the_organizations_internal_number(self, acme, internal, user):
        started = identity.start_link(user, acme, NUMBER)

        assert started.link == f"https://wa.me/27000000000?text=link%20{started.code}"

    def test_a_number_that_cant_be_one_is_refused(self, acme, internal, user):
        with pytest.raises(IdentityError) as raised:
            identity.start_link(user, acme, "call me")

        assert raised.value.code == "invalid_phone_number"

    def test_a_phone_linked_to_another_account_on_that_number_is_refused(self, acme, internal, user, sender):
        link(UserFactory(), sender)

        with pytest.raises(IdentityError) as raised:
            identity.start_link(user, acme, NUMBER)

        assert raised.value.code == "linked_elsewhere"

    def test_the_same_phone_linked_on_another_organizations_number_doesnt_matter(self, acme, internal, user):
        # Each organization's number is its own: Beta's link says nothing about Acme's.
        link(UserFactory(), ContactFactory(account=InternalAccountFactory(), wa_id=NUMBER))

        assert identity.start_link(user, acme, NUMBER).phone_number == NUMBER

    def test_an_organization_without_an_internal_number_cant_be_linked_on(self, acme, user):
        ExternalAccountFactory(tenant=acme)

        with pytest.raises(IdentityError) as raised:
            identity.start_link(user, acme, NUMBER)

        assert raised.value.code == "not_available"
        assert "Acme" in str(raised.value)

    def test_only_a_member_can_start_a_link(self, acme, internal):
        with pytest.raises(IdentityError) as raised:
            identity.start_link(UserFactory(), acme, NUMBER)

        assert raised.value.code == "not_found"

    def test_a_pending_invitation_isnt_membership(self, acme, internal):
        invited = UserFactory()
        TenantMembershipFactory(user=invited, tenant=acme, is_accepted=False)

        with pytest.raises(IdentityError) as raised:
            identity.start_link(invited, acme, NUMBER)

        assert raised.value.code == "not_found"


class TestTheLinkMessage:
    def test_the_code_sent_from_that_phone_links_it_on_that_number(self, acme, internal, user, sender):
        started = identity.start_link(user, acme, NUMBER)

        replies = identity.handle_unlinked_message(sender, f"link {started.code}")

        linked = WhatsAppIdentity.objects.get(user=user)
        assert linked.contact == sender
        assert linked.account == internal
        assert linked.linked_at is not None
        assert "Acme" in bodies(replies)[0]

    def test_the_command_is_forgiving_about_case_and_spaces(self, acme, internal, user, sender):
        started = identity.start_link(user, acme, NUMBER)

        identity.handle_unlinked_message(sender, f"  LINK   {started.code} ")

        assert WhatsAppIdentity.objects.filter(user=user, contact=sender).exists()

    def test_the_code_sent_from_any_other_phone_links_nothing(self, acme, internal, user, sender):
        # The phone is proven by being the sender; a code forwarded to someone else proves nothing.
        started = identity.start_link(user, acme, NUMBER)
        stranger = ContactFactory(account=internal, wa_id="27839999999")

        replies = identity.handle_unlinked_message(stranger, f"link {started.code}")

        assert not WhatsAppIdentity.objects.exists()
        assert "didn't work" in bodies(replies)[0]

    def test_a_wrong_code_links_nothing(self, acme, internal, user, sender):
        identity.start_link(user, acme, NUMBER)

        replies = identity.handle_unlinked_message(sender, "link 000000")

        assert not WhatsAppIdentity.objects.exists()
        assert "didn't work" in bodies(replies)[0]

    def test_a_code_sent_to_an_organization_the_user_isnt_a_member_of_links_nothing(self, acme, internal, user):
        # The code isn't tied to a number; membership of the number's organization is what counts.
        started = identity.start_link(user, acme, NUMBER)
        beta_sender = ContactFactory(account=InternalAccountFactory(), wa_id=NUMBER)

        replies = identity.handle_unlinked_message(beta_sender, f"link {started.code}")

        assert not WhatsAppIdentity.objects.exists()
        assert "not a member" in bodies(replies)[0]

    def test_a_code_sent_to_an_external_number_links_nothing(self, acme, internal, user):
        started = identity.start_link(user, acme, NUMBER)
        customer = ContactFactory(account=ExternalAccountFactory(tenant=acme), wa_id=NUMBER)

        identity.handle_unlinked_message(customer, f"link {started.code}")

        assert not WhatsAppIdentity.objects.exists()

    def test_linking_another_phone_on_the_same_number_moves_the_link(self, acme, internal, user, sender):
        old = link(user, ContactFactory(account=internal, wa_id="27830000000"))
        started = identity.start_link(user, acme, NUMBER)

        identity.handle_unlinked_message(sender, f"link {started.code}")

        assert WhatsAppIdentity.objects.get(user=user, account=internal).contact == sender
        assert not WhatsAppIdentity.objects.filter(pk=old.pk).exists()

    def test_a_link_on_another_organizations_number_stays(self, acme, internal, user, sender):
        beta = InternalAccountFactory()
        TenantMembershipFactory(user=user, tenant=beta.tenant)
        on_beta = link(user, ContactFactory(account=beta, wa_id=NUMBER))
        started = identity.start_link(user, acme, NUMBER)

        identity.handle_unlinked_message(sender, f"link {started.code}")

        assert WhatsAppIdentity.objects.filter(user=user).count() == 2
        assert WhatsAppIdentity.objects.filter(pk=on_beta.pk).exists()


class TestStrangers:
    @pytest.mark.parametrize("text", ["hi", "menu", "show me my organizations", "link", "link abc"])
    def test_an_unlinked_sender_gets_no_reply(self, internal, sender, text):
        # The maintainer's decision (2026-10-22): a customer who finds the team's number hears nothing.
        assert identity.handle_unlinked_message(sender, text) == []
        assert not WhatsAppIdentity.objects.exists()


class TestFindingTheLinkedMember:
    def test_the_linked_member_of_the_numbers_organization_is_found(self, internal, user, sender):
        link(user, sender)

        assert identity.identity_for(sender).user == user

    def test_a_phone_nobody_linked_has_none(self, internal):
        assert identity.identity_for(ContactFactory(account=internal)) is None

    def test_a_user_who_left_the_organization_counts_as_nobody(self, acme, internal, user, sender):
        link(user, sender)
        TenantMembership.objects.filter(user=user, tenant=acme).delete()

        assert identity.identity_for(sender) is None


class TestUnlinking:
    def test_unlinking_removes_the_link_on_that_number_and_keeps_the_contact(self, internal, user, sender):
        link(user, sender)

        identity.unlink(user, internal)

        assert not WhatsAppIdentity.objects.exists()
        assert sender.__class__.objects.filter(pk=sender.pk).exists()

    def test_links_on_other_numbers_stay(self, internal, user, sender):
        link(user, sender)
        beta = link(user, ContactFactory(account=InternalAccountFactory(), wa_id=NUMBER))

        identity.unlink(user, internal)

        assert list(WhatsAppIdentity.objects.filter(user=user)) == [beta]

    def test_unlinking_forgets_the_conversation(self, internal, user, sender):
        # Its history and anything waiting for Confirm belonged to this user: the next person
        # linked to the phone must not inherit them (chosen on 2026-10-20).
        conversation = conversation_of(sender, user)

        identity.unlink(user, internal)

        assert_forgotten(conversation)

    def test_linking_starts_from_a_forgotten_conversation(self, acme, internal, user, sender):
        conversation = conversation_of(sender, UserFactory(), linked=False)
        started = identity.start_link(user, acme, NUMBER)

        identity.handle_unlinked_message(sender, f"link {started.code}")

        assert_forgotten(conversation)

    def test_unlinking_without_a_link_is_harmless(self, internal, user):
        identity.unlink(user, internal)

        assert not WhatsAppIdentity.objects.exists()
