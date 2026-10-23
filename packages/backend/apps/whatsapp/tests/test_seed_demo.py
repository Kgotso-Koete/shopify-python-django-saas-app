"""
Tests for the whatsapp_seed_demo command (plan Steps 1.5 and 1.17): development data for the human
checks, for an organization the given user owns.

- demo external communications numbers, one in each state the WhatsApp tab shows
- the organization's internal communications number: a fake one when it has none, or the one it
  already has, which is never replaced (one active per organization)
- a linked user, an Admin, linked on that internal number; and a second organization, with its own
  internal number, where they're a Member
- safe to run again

Kind of test: integration (agents.md section 2.5). Why: the command writes rows in the test
database; nothing is faked.
"""

from io import StringIO

import pytest
from django.core.management import call_command

from apps.multitenancy.constants import TenantType, TenantUserRole
from apps.multitenancy.tests.factories import TenantFactory, TenantMembershipFactory
from apps.users.tests.factories import UserFactory

from ..constants import AccountPurpose
from ..models import WhatsAppAccount, WhatsAppIdentity
from ..services import identity
from .factories import InternalAccountFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner():
    user = UserFactory(email="owner@example.com")
    acme = TenantFactory(type=TenantType.ORGANIZATION, name="Acme")
    TenantMembershipFactory(user=user, tenant=acme, role=TenantUserRole.OWNER)
    return user


@pytest.fixture
def acme(owner):
    return owner.tenants.get(name="Acme")


def seed():
    out = StringIO()
    # Named, since the owner also owns the personal organization every user gets.
    call_command("whatsapp_seed_demo", email="owner@example.com", organization="Acme", stdout=out)
    return out.getvalue()


def test_the_external_demo_numbers_are_seeded_one_in_each_state(acme):
    output = seed()

    external = WhatsAppAccount.objects.filter(tenant=acme, purpose=AccountPurpose.EXTERNAL_COMMUNICATIONS)
    states = {account.phone_number_id: (account.is_active, account.subscribed_at is not None) for account in external}
    # Credentials only, then subscribed to our app (Step 1.18), then a message, then disconnected.
    assert states == {
        "100000000000801": (True, False),
        "100000000000802": (True, True),
        "100000000000803": (True, True),
        "100000000000804": (False, False),
    }
    assert "Verify token" not in output


def test_an_organization_without_an_internal_number_gets_a_fake_one(acme):
    seed()

    internal = WhatsAppAccount.objects.internal_for(acme)
    assert internal is not None
    assert internal.phone_number_id.startswith("1000000000008")


def test_an_organizations_own_internal_number_is_kept(acme):
    real = InternalAccountFactory(tenant=acme, phone_number_id="123456789012345")

    seed()

    assert WhatsAppAccount.objects.internal_for(acme) == real


def test_the_linked_user_is_a_linked_member_on_the_internal_number(acme):
    seed()

    linked = WhatsAppIdentity.objects.get(user__email="whatsapp-linked@example.com", account__tenant=acme)
    assert linked.account == WhatsAppAccount.objects.internal_for(acme)
    assert identity.identity_for(linked.contact) == linked


def test_the_second_organization_has_its_own_internal_number_and_link(acme):
    seed()

    second = WhatsAppIdentity.objects.exclude(account__tenant=acme).get(user__email="whatsapp-linked@example.com")
    assert second.account.tenant.name == "WhatsApp demo: second organization"
    assert second.account.purpose == AccountPurpose.INTERNAL_COMMUNICATIONS


def test_running_it_again_is_safe(acme):
    seed()

    output = seed()

    assert WhatsAppAccount.objects.filter(purpose=AccountPurpose.INTERNAL_COMMUNICATIONS).count() == 2
    assert WhatsAppIdentity.objects.count() == 2
    assert "Linked user" in output
