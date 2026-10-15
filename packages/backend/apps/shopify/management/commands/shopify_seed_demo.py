from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from django.utils import timezone
from django.core.signing import TimestampSigner

from apps.users.models import User
from apps.multitenancy.constants import SystemRoleType, TenantUserRole
from apps.multitenancy.models import (
    OrganizationRole,
    Tenant,
    TenantMembership,
    TenantMembershipRole,
    invalidate_user_permissions_cache,
)
from apps.shopify.models import ShopifyShop

# A made-up user with the Member role in the seeded organization, for the human check showing that a member
# without shopify.manage can't link a store. Development data only: the command refuses to run in production.
MEMBER_EMAIL = "shopify-member@example.com"
MEMBER_PASSWORD = "ShopifyMember123!"


class Command(BaseCommand):
    help = "Seed database with demo Shopify stores for testing."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True, type=str, help="Email of the user to link stores to.")
        # A user owns several organizations (always their personal one), so the demo stores must be able
        # to go to the one their real dev store is linked to.
        parser.add_argument(
            "--organization",
            type=str,
            default=None,
            help="Exact name of an organization the user owns. Default: the first one they own.",
        )

    def handle(self, *args, **options):
        if settings.ENVIRONMENT_NAME == "production":
            raise CommandError("Cannot run shopify_seed_demo in production!")

        email = options["email"]
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            raise CommandError(f"User with email '{email}' does not exist.")

        # TenantMembership's link back to Tenant is named user_memberships (apps/multitenancy/models.py).
        owned = Tenant.objects.filter(user_memberships__user=user, user_memberships__role=TenantUserRole.OWNER)
        organization = options["organization"]
        if organization:
            tenant = owned.filter(name=organization).first()
            if not tenant:
                raise CommandError(f"User '{email}' does not own an organization named '{organization}'.")
        else:
            tenant = owned.first()
            if not tenant:
                raise CommandError(f"User '{email}' does not own any tenants. Create a tenant first.")

        # 1. linked-demo.myshopify.com
        shop1, _ = ShopifyShop.objects.update_or_create(
            shop_domain="linked-demo.myshopify.com",
            defaults={
                "tenant": tenant,
                "access_token": "acc_fake123",
                "refresh_token": "ref_fake123",
                "scopes": ",".join(settings.SHOPIFY_SCOPES),
                "installed_at": timezone.now(),
                "uninstalled_at": None,
                "needs_reinstall": False,
            },
        )
        self.stdout.write(self.style.SUCCESS(f"Created linked store: {shop1.shop_domain} (Tenant: {tenant.name})"))

        # 2. unlinked-demo.myshopify.com
        shop2, _ = ShopifyShop.objects.update_or_create(
            shop_domain="unlinked-demo.myshopify.com",
            defaults={
                "tenant": None,
                "access_token": "acc_fake456",
                "refresh_token": "ref_fake456",
                "scopes": ",".join(settings.SHOPIFY_SCOPES),
                "installed_at": timezone.now(),
                "uninstalled_at": None,
                "needs_reinstall": False,
            },
        )
        signer = TimestampSigner()
        claim = signer.sign(str(shop2.id))
        self.stdout.write(self.style.SUCCESS(f"Created unlinked store: {shop2.shop_domain}"))
        self.stdout.write(f"  Link URL: {settings.WEB_APP_URL}/shopify/link?claim={claim}")

        # 3. uninstalled-demo.myshopify.com
        shop3, _ = ShopifyShop.objects.update_or_create(
            shop_domain="uninstalled-demo.myshopify.com",
            defaults={
                "tenant": tenant,
                "access_token": None,
                "refresh_token": None,
                "scopes": "",
                "installed_at": timezone.now() - timezone.timedelta(days=1),
                "uninstalled_at": timezone.now(),
                "needs_reinstall": False,
            },
        )
        self.stdout.write(self.style.SUCCESS(f"Created uninstalled store: {shop3.shop_domain} (Tenant: {tenant.name})"))

        # 4. reinstall-demo.myshopify.com
        shop4, _ = ShopifyShop.objects.update_or_create(
            shop_domain="reinstall-demo.myshopify.com",
            defaults={
                "tenant": tenant,
                "access_token": "acc_fake789",
                "refresh_token": "ref_fake789",
                "scopes": ",".join(settings.SHOPIFY_SCOPES),
                "installed_at": timezone.now(),
                "uninstalled_at": None,
                "needs_reinstall": True,
            },
        )
        self.stdout.write(
            self.style.SUCCESS(f"Created needs-reinstall store: {shop4.shop_domain} (Tenant: {tenant.name})")
        )

        # 5. A Member of the same organization. Permissions come from the RBAC role assignment
        # (TenantMembershipRole), not from the membership's legacy role field, so both are set.
        member = User.objects.filter(email=MEMBER_EMAIL).first()
        if member is None:
            member = User.objects.create_user(email=MEMBER_EMAIL, password=MEMBER_PASSWORD)
        member.is_confirmed = True
        member.save(update_fields=["is_confirmed"])
        membership, _ = TenantMembership.objects.get_or_create(
            user=member,
            tenant=tenant,
            defaults={"role": TenantUserRole.MEMBER, "is_accepted": True},
        )
        member_role = OrganizationRole.objects.get(tenant=tenant, system_role_type=SystemRoleType.MEMBER)
        TenantMembershipRole.objects.get_or_create(membership=membership, role=member_role)
        invalidate_user_permissions_cache(member.id, tenant.id)
        self.stdout.write(
            self.style.SUCCESS(f"Created member: {MEMBER_EMAIL} / {MEMBER_PASSWORD} (Member of {tenant.name})")
        )
