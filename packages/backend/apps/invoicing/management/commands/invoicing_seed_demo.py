"""
Demo invoices for an organization, for the human checks (WhatsApp plan Step 4.6, user story WA.D6.OM.J2.A1).
Run after payfast_seed_demo, which gives the organization its two example PayFast payments:

- an invoice for each of those payments, numbered one after the other in the service's sequence
- an Admin, who holds billing.view and can download them, and a Member, who doesn't and can't
- a second organization with a payment and invoice of its own, and nobody from the first in it, so
  its invoice is "not found" to the first organization's people

Each invoice is issued by the same task a real PayFast payment queues (apps/invoicing/tasks.py), so
its PDF is written to the default storage, wherever STORAGE_BACKEND points.

Development data only: the command refuses to run in production, and every payment is made up. Safe
to run again: a payment keeps its one invoice, and a written PDF is never written again.

    docker compose run --rm backend python manage.py invoicing_seed_demo --email <owner email>
"""

from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.multitenancy.constants import SystemRoleType, TenantType, TenantUserRole
from apps.multitenancy.models import (
    OrganizationRole,
    Tenant,
    TenantMembership,
    TenantMembershipRole,
    invalidate_user_permissions_cache,
)
from apps.payfast.models import PayFastPayment
from apps.users.models import User

from ...models import Invoice
from ...tasks import issue_invoice

# Made-up people of the seeded organization. An Admin holds billing.view but not billing.manage, and
# a Member holds neither (apps/multitenancy/permissions.py, ROLE_TEMPLATE_PERMISSIONS).
ADMIN_EMAIL = "invoicing-admin@example.com"
ADMIN_PASSWORD = "InvoicingAdmin123!"
MEMBER_EMAIL = "invoicing-member@example.com"
MEMBER_PASSWORD = "InvoicingMember123!"

# The second organization, and its one made-up payment. The "seed-" prefix marks it as seed data, as
# payfast_seed_demo's payment ids are marked.
SECOND_ORGANIZATION = "Invoicing demo: second organization"
SECOND_PAYMENT_ID = "seed-invoicing-second-monthly"


class Command(BaseCommand):
    help = "Issue demo invoices for an organization's seeded PayFast payments (development only)."

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
            raise CommandError("Cannot run invoicing_seed_demo in production!")

        email = options["email"]
        owner = User.objects.filter(email=email).first()
        if owner is None:
            raise CommandError(f"User with email '{email}' does not exist.")
        # TenantMembership's link back to Tenant is named user_memberships (apps/multitenancy/models.py).
        owned = Tenant.objects.filter(user_memberships__user=owner, user_memberships__role=TenantUserRole.OWNER)
        tenant = owned.filter(name=options["organization"]).first() if options["organization"] else owned.first()
        if tenant is None:
            raise CommandError(f"User '{email}' does not own that organization (or any). Create one first.")

        # payfast_seed_demo's payments: completed, for more than nothing, with ids starting "seed-".
        # Oldest first, so their invoices are numbered in the order the payments were made.
        payments = list(
            PayFastPayment.objects.filter(
                tenant=tenant, pf_payment_id__startswith="seed-", payment_status="COMPLETE", amount_gross__gt=0
            ).order_by("created_at", "pk")
        )
        if not payments:
            raise CommandError(
                "The demo PayFast payments aren't there: run payfast_seed_demo first, with the same email."
            )

        for payment in payments:
            self._invoice(payment)

        self._person(ADMIN_EMAIL, ADMIN_PASSWORD, tenant, TenantUserRole.ADMIN, SystemRoleType.ADMIN)
        self._person(MEMBER_EMAIL, MEMBER_PASSWORD, tenant, TenantUserRole.MEMBER, SystemRoleType.MEMBER)
        self.stdout.write(
            self.style.SUCCESS(f"Admin: {ADMIN_EMAIL} / {ADMIN_PASSWORD} (Admin of {tenant.name}, billing.view)")
        )
        self.stdout.write(
            self.style.SUCCESS(f"Member: {MEMBER_EMAIL} / {MEMBER_PASSWORD} (Member of {tenant.name}, no billing)")
        )

        self._second_organization(owner)

    def _invoice(self, payment):
        """Issue `payment`'s invoice and write its PDF, as the task queued by a real payment does."""
        # Called directly, not with .delay(): the seed runs it here and now, with or without a worker.
        issue_invoice(payment.pk)
        invoice = Invoice.objects.get(payment=payment)
        self.stdout.write(
            self.style.SUCCESS(
                f"Invoice {invoice.number} (id {invoice.id}) for {invoice.tenant_name}: "
                f"{invoice.description}, {invoice.currency} {invoice.amount}"
            )
        )

    def _second_organization(self, creator):
        """
        A second organization with one paid invoice and no members: nobody from the seeded
        organization belongs to it, so its invoice must be "not found" to them.
        """
        # `creator` is only recorded on the row; no signal makes them a member (apps/multitenancy).
        second, _ = Tenant.objects.get_or_create(
            name=SECOND_ORGANIZATION, creator=creator, defaults={"type": TenantType.ORGANIZATION}
        )
        payment, _ = PayFastPayment.objects.get_or_create(
            pf_payment_id=SECOND_PAYMENT_ID,
            defaults={
                "tenant": second,
                "kind": PayFastPayment.Kind.SUBSCRIPTION,
                "plan": "monthly_plan",
                "amount_gross": Decimal("199.00"),
                "payment_status": "COMPLETE",
                "item_name": "Monthly plan",
                "raw": {"seed": True},
            },
        )
        self._invoice(payment)

    @staticmethod
    def _person(email, password, tenant, legacy_role, system_role_type):
        """
        `email`, an accepted member of `tenant` with the role given. Permissions come from the RBAC role
        assignment (TenantMembershipRole), not the membership's legacy role field, so both are set, as in
        apps/whatsapp/management/commands/whatsapp_seed_demo.py.
        """
        user = User.objects.filter(email=email).first()
        if user is None:
            user = User.objects.create_user(email=email, password=password)
        user.is_confirmed = True
        user.save(update_fields=["is_confirmed"])
        membership, _ = TenantMembership.objects.get_or_create(
            user=user, tenant=tenant, defaults={"role": legacy_role, "is_accepted": True}
        )
        role = OrganizationRole.objects.get(tenant=tenant, system_role_type=system_role_type)
        TenantMembershipRole.objects.get_or_create(membership=membership, role=role)
        invalidate_user_permissions_cache(user.id, tenant.id)
