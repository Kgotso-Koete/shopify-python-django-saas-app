from django.core.management.base import BaseCommand

from apps.multitenancy.models import Tenant
from apps.payfast.models import PayFastSubscription


class Command(BaseCommand):
    help = (
        "Give every tenant without a PayFast subscription a free-plan one. Run once after switching an "
        "existing deployment to PAYMENT_BACKEND=payfast; new tenants get one automatically. Safe to re-run."
    )

    def handle(self, *args, **options):
        missing = Tenant.objects.filter(payfast_subscription__isnull=True)
        created = PayFastSubscription.objects.bulk_create([PayFastSubscription(tenant=tenant) for tenant in missing])
        self.stdout.write(f"Created {len(created)} free-plan PayFast subscription(s).")
