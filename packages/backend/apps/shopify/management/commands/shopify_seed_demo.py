from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from django.utils import timezone
from django.core.signing import TimestampSigner

from apps.users.models import User
from apps.multitenancy.models import Tenant
from apps.shopify.models import ShopifyShop


class Command(BaseCommand):
    help = "Seed database with demo Shopify stores for testing."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True, type=str, help="Email of the user to link stores to.")

    def handle(self, *args, **options):
        if settings.ENVIRONMENT_NAME == "production":
            raise CommandError("Cannot run shopify_seed_demo in production!")

        email = options["email"]
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            raise CommandError(f"User with email '{email}' does not exist.")

        tenant = Tenant.objects.filter(memberships__user=user, memberships__role="OWNER").first()
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
