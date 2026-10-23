"""
WhatsApp permission codes (plan decision D16), registered the way apps/shopify/permissions.py
registers Shopify's. apps.multitenancy imports this module when it collects every app's permissions,
and migration 0006_seed_whatsapp_permissions creates the database rows that user_has_permission reads.
"""

from apps.multitenancy.constants import SystemRoleType
from apps.multitenancy.permissions import (
    PermissionDefinition,
    register_app_permissions,
    register_permission_category,
    register_system_role_permissions,
)

register_permission_category(
    value="WHATSAPP",
    label="WhatsApp",
    description="Permissions for the organization's WhatsApp numbers",
)

WHATSAPP_PERMISSIONS = [
    PermissionDefinition(
        code="whatsapp.view",
        name="View WhatsApp Numbers",
        description="See the organization's WhatsApp numbers and their status",
        category="WHATSAPP",
        sort_order=10,
    ),
    PermissionDefinition(
        code="whatsapp.manage",
        name="Manage WhatsApp Numbers",
        description="Connect, test, troubleshoot and disconnect the organization's WhatsApp numbers",
        category="WHATSAPP",
        sort_order=20,
    ),
]

register_app_permissions(WHATSAPP_PERMISSIONS)

# OWNER automatically gets every permission. Admins can change the numbers; members can only see
# them, as with Shopify.
register_system_role_permissions(SystemRoleType.ADMIN, ["whatsapp.view", "whatsapp.manage"])
register_system_role_permissions(SystemRoleType.MEMBER, ["whatsapp.view"])
