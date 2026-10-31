"""
Demo links between an organization's external WhatsApp numbers and its Shopify store, for the human
checks (plan Step 2.1b, user story 25). Run after whatsapp_seed_demo and shopify_seed_demo, which
create the demo numbers and the demo store:

- the demo numbers ...802 and ...803 sell from linked-demo.myshopify.com
- ...801 has no store chosen, so the page shows both cases

Development data only: the command refuses to run in production. Safe to run again.

    docker compose run --rm backend python manage.py whatsapp_shop_seed_demo --email <owner email>
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.multitenancy.constants import TenantUserRole
from apps.multitenancy.models import Tenant
from apps.users.models import User
from apps.whatsapp.management.commands.whatsapp_seed_demo import CREDENTIALS_ONLY, MESSAGE_RECEIVED, SUBSCRIBED
from apps.whatsapp.models import WhatsAppAccount

from ...models import StorefrontChannel
from ...services import StoreChannelError, choose_store

# The store shopify_seed_demo links to the organization, with the scopes SHOPIFY_SCOPES lists.
DEMO_STORE = "linked-demo.myshopify.com"


class Command(BaseCommand):
    help = "Link an organization's demo WhatsApp numbers to its demo Shopify store (development only)."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True, type=str, help="Email of the user who owns the organization.")
        parser.add_argument(
            "--organization",
            type=str,
            default=None,
            help="Exact name of an organization the user owns. Default: the first one they own.",
        )

    def handle(self, *args, **options):
        if settings.ENVIRONMENT_NAME == "production":
            raise CommandError("Cannot run whatsapp_shop_seed_demo in production!")

        email = options["email"]
        user = User.objects.filter(email=email).first()
        if user is None:
            raise CommandError(f"User with email '{email}' does not exist.")
        # TenantMembership's link back to Tenant is named user_memberships (apps/multitenancy/models.py).
        owned = Tenant.objects.filter(user_memberships__user=user, user_memberships__role=TenantUserRole.OWNER)
        tenant = owned.filter(name=options["organization"]).first() if options["organization"] else owned.first()
        if tenant is None:
            raise CommandError(f"User '{email}' does not own that organization (or any). Create one first.")

        numbers = {
            account.phone_number_id: account
            for account in WhatsAppAccount.objects.filter(
                tenant=tenant, phone_number_id__in=[CREDENTIALS_ONLY, SUBSCRIBED, MESSAGE_RECEIVED]
            )
        }
        if len(numbers) < 3:
            raise CommandError(
                "The demo WhatsApp numbers aren't there: run whatsapp_seed_demo first, with the same options."
            )

        # The two numbers that sell from the demo store; choose_store applies the page's own rules.
        for phone_number_id in (SUBSCRIBED, MESSAGE_RECEIVED):
            try:
                choose_store(tenant=tenant, account_id=str(numbers[phone_number_id].pk), shop_domain=DEMO_STORE)
            except StoreChannelError as error:
                raise CommandError(
                    f"{error} Run shopify_seed_demo first, with the same options and SHOPIFY_SCOPES holding the "
                    "storefront scopes."
                ) from error
            self.stdout.write(f"WhatsApp number {phone_number_id} sells from {DEMO_STORE}")

        # The third shows "no store chosen".
        StorefrontChannel.objects.filter(account=numbers[CREDENTIALS_ONLY]).delete()
        self.stdout.write(f"WhatsApp number {CREDENTIALS_ONLY} has no store chosen")
