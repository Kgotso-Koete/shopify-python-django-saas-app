"""
Tests for the migration that ends the platform number (plan Step 1.17): every WhatsApp number
belongs to an organization, so the old platform number's rows, which had none, are deleted with
their contacts, messages and links. They exist only in development.

The function is called directly, as test_enum_migration.py does, and never with transaction=True
(agents.md section 2.6). The migrated test database refuses a number without an organization, so
the test first makes the column nullable again, as it was before the migration; Postgres runs that
DDL inside the test's transaction, which rolls it back with everything else.

Kind of test: integration (agents.md section 2.5). Why: rows in the test database are deleted by
the migration's own function; nothing is faked.
"""

import copy
import importlib

import pytest
from django.apps import apps as django_apps
from django.db import connection, migrations

from ..models import WhatsAppAccount, WhatsAppContact, WhatsAppMessage
from .factories import ContactFactory, ExternalAccountFactory, InternalAccountFactory, MessageFactory

pytestmark = pytest.mark.django_db

migration = importlib.import_module("apps.whatsapp.migrations.0015_every_number_belongs_to_an_organization")


@pytest.fixture
def numbers_without_an_organization_allowed():
    """The column as it was before the migration: a number could have no organization."""
    required = WhatsAppAccount._meta.get_field("tenant")
    # A shallow copy keeps the resolved link to Tenant, which the schema editor needs.
    optional = copy.copy(required)
    optional.null = True
    with connection.schema_editor() as editor:
        editor.alter_field(WhatsAppAccount, required, optional)


def test_the_platform_number_and_its_history_are_deleted(numbers_without_an_organization_allowed):
    platform = InternalAccountFactory()
    message = MessageFactory(contact=ContactFactory(account=platform))
    WhatsAppAccount.objects.filter(pk=platform.pk).update(tenant=None)

    migration.delete_numbers_without_an_organization(django_apps, None)

    assert not WhatsAppAccount.objects.filter(pk=platform.pk).exists()
    assert not WhatsAppContact.objects.filter(pk=message.contact_id).exists()
    assert not WhatsAppMessage.objects.filter(pk=message.pk).exists()


def test_organizations_numbers_are_kept(numbers_without_an_organization_allowed):
    internal, external = InternalAccountFactory(), ExternalAccountFactory()

    migration.delete_numbers_without_an_organization(django_apps, None)

    assert WhatsAppAccount.objects.filter(pk__in=[internal.pk, external.pk]).count() == 2


def test_the_rows_go_before_the_column_becomes_required():
    operations = migration.Migration.operations
    delete = next(i for i, op in enumerate(operations) if isinstance(op, migrations.RunPython))
    required = next(
        i for i, op in enumerate(operations) if isinstance(op, migrations.AlterField) and op.name == "tenant"
    )

    assert delete < required
