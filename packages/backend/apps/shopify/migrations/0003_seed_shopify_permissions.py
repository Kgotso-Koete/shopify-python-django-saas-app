from django.db import migrations

# Registering permission codes in apps/shopify/permissions.py only puts them in the in-code
# registry. Permission checks (user_has_permission) read database rows, so this migration
# creates those rows and grants them to the system roles of tenants that already exist.
# Tenants created afterwards get them from create_system_roles_for_tenant.

SHOPIFY_PERMISSION_CODES = ["shopify.view", "shopify.manage"]


def add_shopify_permissions(apps, schema_editor):
    from apps.multitenancy.permissions import get_all_permissions

    Permission = apps.get_model("multitenancy", "Permission")
    for perm_def in get_all_permissions():
        if perm_def.code in SHOPIFY_PERMISSION_CODES:
            Permission.objects.update_or_create(
                code=perm_def.code,
                defaults={
                    "name": perm_def.name,
                    "description": perm_def.description,
                    "category": getattr(perm_def.category, "value", perm_def.category),
                    "sort_order": perm_def.sort_order,
                    "is_system": True,
                },
            )


def assign_shopify_permissions_to_system_roles(apps, schema_editor):
    from apps.multitenancy.constants import SystemRoleType
    from apps.multitenancy.permissions import get_effective_role_template_permissions

    OrganizationRole = apps.get_model("multitenancy", "OrganizationRole")
    OrganizationRolePermission = apps.get_model("multitenancy", "OrganizationRolePermission")
    Permission = apps.get_model("multitenancy", "Permission")

    for role_type in (SystemRoleType.OWNER, SystemRoleType.ADMIN, SystemRoleType.MEMBER):
        # The same grants permissions.py registers; None means the role gets every permission (OWNER).
        template = get_effective_role_template_permissions(role_type)
        codes = [c for c in SHOPIFY_PERMISSION_CODES if template is None or c in template]
        permissions = list(Permission.objects.filter(code__in=codes))
        for role in OrganizationRole.objects.filter(system_role_type=role_type):
            for permission in permissions:
                OrganizationRolePermission.objects.get_or_create(role=role, permission=permission)


class Migration(migrations.Migration):

    dependencies = [
        ("multitenancy", "0023_alter_permission_category"),
        ("shopify", "0002_shopifywebhookdelivery_remove_shopifytoken_store_and_more"),
    ]

    operations = [
        migrations.RunPython(add_shopify_permissions, migrations.RunPython.noop),
        migrations.RunPython(assign_shopify_permissions_to_system_roles, migrations.RunPython.noop),
    ]
