import importlib

import pytest
from django.apps import apps as django_apps

from apps.multitenancy.constants import SystemRoleType
from apps.multitenancy.models import OrganizationRolePermission, Permission
from apps.multitenancy.permissions import create_system_roles_for_tenant
from apps.multitenancy.tests.factories import TenantFactory

pytestmark = pytest.mark.django_db

SHOPIFY_CODES = {"shopify.view", "shopify.manage"}

# What apps/shopify/permissions.py grants each system role.
EXPECTED_ROLE_CODES = [
    (SystemRoleType.OWNER, SHOPIFY_CODES),
    (SystemRoleType.ADMIN, SHOPIFY_CODES),
    (SystemRoleType.MEMBER, {"shopify.view"}),
]


def _shopify_codes_of(tenant, role_type):
    return set(
        OrganizationRolePermission.objects.filter(
            role__tenant=tenant, role__system_role_type=role_type, permission__code__in=SHOPIFY_CODES
        ).values_list("permission__code", flat=True)
    )


def test_shopify_permissions_are_seeded_by_migrations():
    # Registering the codes in permissions.py is not enough: user_has_permission reads
    # database rows, so a migration has to create them.
    seeded = set(Permission.objects.filter(code__in=SHOPIFY_CODES).values_list("code", flat=True))

    assert seeded == SHOPIFY_CODES


@pytest.mark.parametrize("role_type, expected", EXPECTED_ROLE_CODES)
def test_new_tenant_system_roles_get_shopify_permissions(role_type, expected):
    tenant = TenantFactory()
    create_system_roles_for_tenant(tenant)

    assert _shopify_codes_of(tenant, role_type) == expected


@pytest.mark.parametrize("role_type, expected", EXPECTED_ROLE_CODES)
def test_migration_backfills_shopify_permissions_on_existing_tenant_roles(role_type, expected):
    # A tenant whose system roles were created before the Shopify permissions existed.
    tenant = TenantFactory()
    create_system_roles_for_tenant(tenant)
    OrganizationRolePermission.objects.filter(role__tenant=tenant, permission__code__in=SHOPIFY_CODES).delete()

    migration = importlib.import_module("apps.shopify.migrations.0003_seed_shopify_permissions")
    migration.assign_shopify_permissions_to_system_roles(django_apps, None)

    assert _shopify_codes_of(tenant, role_type) == expected
