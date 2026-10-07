from apps.multitenancy.permissions import (
    PermissionDefinition,
    register_app_permissions,
    register_permission_category,
    register_system_role_permissions,
)
from apps.multitenancy.constants import SystemRoleType

# 1. Register a new category for Shopify
register_permission_category(
    value="SHOPIFY",
    label="Shopify",
    description="Permissions for Shopify integration",
)

# 2. Define the permissions
SHOPIFY_PERMISSIONS = [
    PermissionDefinition(
        code="shopify.view",
        name="View Shopify Stores",
        description="View connected Shopify stores",
        category="SHOPIFY",
        sort_order=10,
    ),
    PermissionDefinition(
        code="shopify.manage",
        name="Manage Shopify Stores",
        description="Connect and disconnect Shopify stores",
        category="SHOPIFY",
        sort_order=20,
    ),
]

# 3. Register the permissions
register_app_permissions(SHOPIFY_PERMISSIONS)

# 4. Add them to system roles
# OWNER automatically gets all permissions. ADMIN gets both view and manage.
register_system_role_permissions(SystemRoleType.ADMIN, ["shopify.view", "shopify.manage"])
register_system_role_permissions(SystemRoleType.MEMBER, ["shopify.view"])
