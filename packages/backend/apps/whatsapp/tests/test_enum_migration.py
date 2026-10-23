"""
Tests for the data migration that rewrites the WhatsApp app's stored enum values to their member
names (plan Step 1.16, agents.md section 5.3b): "platform" becomes "INTERNAL_COMMUNICATIONS", "in"
becomes "INBOUND", "sent" becomes "SENT", and so on, with a reverse that restores the old values.

The functions are called directly, as test_permissions.py does with its migration, and never with
transaction=True (agents.md section 2.6). The check constraint the migration drops and adds back is
gone from the migrated test database since Step 1.17, so nothing stops the old values being written.

Kind of test: integration (agents.md section 2.5). Why: rows in the test database are rewritten by
the migration's own functions; nothing is faked.
"""

import importlib

import pytest
from django.apps import apps as django_apps
from django.db import migrations

from apps.users.tests.factories import UserFactory

from ..models import WhatsAppAccount, WhatsAppIdentity, WhatsAppMessage
from .factories import ContactFactory, MessageFactory

pytestmark = pytest.mark.django_db

migration = importlib.import_module("apps.whatsapp.migrations.0013_enum_values_are_member_names")


def link(contact):
    return WhatsAppIdentity.objects.create(user=UserFactory(), contact=contact, account=contact.account)


@pytest.fixture
def old_rows():
    """A contact's account, an outbound message and a link, with the values stored before Step 1.16."""
    contact = ContactFactory()
    message = MessageFactory(contact=contact)
    identity = link(contact)
    # .update() writes the raw values, as the old code stored them.
    WhatsAppAccount.objects.filter(pk=contact.account.pk).update(purpose="platform", connection_method="seed")
    WhatsAppMessage.objects.filter(pk=message.pk).update(kind="button_reply", direction="out", status="delivered")
    WhatsAppIdentity.objects.filter(pk=identity.pk).update(conversation_mode="agentic")
    return contact.account, message, identity


def stored(account, message, identity):
    return (
        WhatsAppAccount.objects.filter(pk=account.pk).values_list("purpose", "connection_method").get(),
        WhatsAppMessage.objects.filter(pk=message.pk).values_list("kind", "direction", "status").get(),
        WhatsAppIdentity.objects.filter(pk=identity.pk).values_list("conversation_mode", flat=True).get(),
    )


def test_old_values_become_member_names(old_rows):
    migration.store_member_names(django_apps, None)

    assert stored(*old_rows) == (
        ("INTERNAL_COMMUNICATIONS", "SEED"),
        ("BUTTON_REPLY", "OUTBOUND", "DELIVERED"),
        "AGENTIC",
    )


def test_the_reverse_restores_the_old_values(old_rows):
    migration.store_member_names(django_apps, None)

    migration.store_old_values(django_apps, None)

    assert stored(*old_rows) == (("platform", "seed"), ("button_reply", "out", "delivered"), "agentic")


def test_an_empty_conversation_mode_stays_empty():
    # Empty means "the default applies" (user story 3), not a mode to rename.
    identity = link(ContactFactory())

    migration.store_member_names(django_apps, None)

    identity.refresh_from_db()
    assert identity.conversation_mode == ""


def test_the_purposes_are_renamed_to_say_who_a_number_is_for():
    assert migration.OLD_TO_NEW["WhatsAppAccount"]["purpose"] == {
        "platform": "INTERNAL_COMMUNICATIONS",
        "storefront": "EXTERNAL_COMMUNICATIONS",
    }


def test_the_purpose_constraint_is_dropped_before_the_rows_change_and_added_after():
    # The old constraint names "platform", the new one "INTERNAL_COMMUNICATIONS": with either in
    # place while the rows change, the migration would fail on existing accounts.
    kinds = [type(operation) for operation in migration.Migration.operations]

    remove, run, add = (
        kinds.index(migrations.RemoveConstraint),
        kinds.index(migrations.RunPython),
        kinds.index(migrations.AddConstraint),
    )
    assert remove < run < add
