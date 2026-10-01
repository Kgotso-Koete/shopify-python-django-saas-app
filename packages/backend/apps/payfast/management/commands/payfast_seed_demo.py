"""
Development seed data for trying the PayFast pages by hand (docs/superpowers/agents.md, 1.3).

Gives every organisation the user owns a PayFast subscription record and two example payments (a
donation and a monthly plan charge), so the transaction history can be checked without paying first.
Payment ids start with "seed-" and the command is safe to re-run. It never contacts PayFast, so real
checkouts still go through the PayFast sandbox.
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.multitenancy.constants import TenantUserRole
from apps.multitenancy.models import Tenant
from apps.payfast import services
from apps.payfast.models import PayFastPayment

SEED_PAYMENTS = (
    {"suffix": "donation", "kind": PayFastPayment.Kind.DONATION, "plan": "", "amount": "50.00", "item": "Donation"},
    {
        "suffix": "monthly",
        "kind": PayFastPayment.Kind.SUBSCRIPTION,
        "plan": "monthly_plan",
        "amount": "199.00",
        "item": "Monthly plan",
    },
)


class Command(BaseCommand):
    help = "Seed example PayFast payment history for the organisations a user owns (development only)."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True, help="Email of an existing user whose organisations get the data")

    def handle(self, *args, email, **options):
        user = get_user_model().objects.filter(email=email).first()
        if user is None:
            raise CommandError(f"No user with email {email!r}; sign up in the web app first.")

        tenants = Tenant.objects.filter(
            user_memberships__user=user, user_memberships__role=TenantUserRole.OWNER
        ).distinct()
        for tenant in tenants:
            subscription = services.get_subscription(tenant)
            for seed in SEED_PAYMENTS:
                PayFastPayment.objects.get_or_create(
                    pf_payment_id=f"seed-{tenant.pk}-{seed['suffix']}",
                    defaults={
                        "tenant": tenant,
                        "kind": seed["kind"],
                        "plan": seed["plan"],
                        "subscription": subscription if seed["plan"] else None,
                        "amount_gross": Decimal(seed["amount"]),
                        "payment_status": "COMPLETE",
                        "item_name": seed["item"],
                        "raw": {"seed": True},
                    },
                )
            self.stdout.write(f"Seeded PayFast history for organisation {tenant.name!r} ({tenant.pk}).")
