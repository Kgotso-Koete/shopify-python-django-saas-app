"""
Tests for apps/whatsapp/permissions.py (plan decision D16, user story 11): what whatsapp.view and
whatsapp.manage each system role gets, and the data migration that grants them to existing
organizations. Modelled on apps/shopify/tests/test_permissions.py.

- whatsapp.view: see the organization's connected numbers and their status.
- whatsapp.manage: connect, test and disconnect a number, and use the troubleshooting tools.

Kind of test: integration (agents.md section 2.5). Why: permissions and role grants are rows in the
test database, and the migration runs against them; nothing is faked.
"""

import importlib

import pytest
from django.apps import apps as django_apps

from apps.multitenancy.constants import SystemRoleType
from apps.multitenancy.models import OrganizationRolePermission, Permission
from apps.multitenancy.permissions import create_system_roles_for_tenant
from apps.multitenancy.tests.factories import TenantFactory

pytestmark = pytest.mark.django_db

WHATSAPP_CODES = {"whatsapp.view", "whatsapp.manage"}

# Owners and admins can change the organization's numbers; members can only see them, as with Shopify.
EXPECTED_ROLE_CODES = [
    (SystemRoleType.OWNER, WHATSAPP_CODES),
    (SystemRoleType.ADMIN, WHATSAPP_CODES),
    (SystemRoleType.MEMBER, {"whatsapp.view"}),
]


def whatsapp_codes_of(tenant, role_type):
    return set(
        OrganizationRolePermission.objects.filter(
            role__tenant=tenant, role__system_role_type=role_type, permission__code__in=WHATSAPP_CODES
        ).values_list("permission__code", flat=True)
    )


def test_whatsapp_permissions_are_seeded_by_migrations():
    # Registering the codes in permissions.py is not enough: user_has_permission reads database
    # rows, so a migration has to create them.
    seeded = set(Permission.objects.filter(code__in=WHATSAPP_CODES).values_list("code", flat=True))

    assert seeded == WHATSAPP_CODES


@pytest.mark.parametrize("role_type, expected", EXPECTED_ROLE_CODES)
def test_new_organization_roles_get_whatsapp_permissions(role_type, expected):
    tenant = TenantFactory()
    create_system_roles_for_tenant(tenant)

    assert whatsapp_codes_of(tenant, role_type) == expected


@pytest.mark.parametrize("role_type, expected", EXPECTED_ROLE_CODES)
def test_the_migration_backfills_whatsapp_permissions_on_existing_organization_roles(role_type, expected):
    # An organization whose system roles were created before the WhatsApp permissions existed.
    tenant = TenantFactory()
    create_system_roles_for_tenant(tenant)
    OrganizationRolePermission.objects.filter(role__tenant=tenant, permission__code__in=WHATSAPP_CODES).delete()

    migration = importlib.import_module("apps.whatsapp.migrations.0006_seed_whatsapp_permissions")
    migration.assign_whatsapp_permissions_to_system_roles(django_apps, None)

    assert whatsapp_codes_of(tenant, role_type) == expected
