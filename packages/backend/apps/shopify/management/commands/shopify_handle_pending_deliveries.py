from django.core.management.base import BaseCommand

from apps.shopify import deliveries


class Command(BaseCommand):
    help = (
        "Handle the Shopify webhook deliveries left unhandled, such as after a queue outage (WhatsApp plan "
        "Step 4.3e). Celery beat runs this every 15 minutes when Shopify is enabled; without a worker, run "
        "it from a cron job, every 15 minutes or so."
    )

    def handle(self, *args, **options):
        counts = deliveries.handle_pending()
        self.stdout.write(" ".join(f"{name}={value}" for name, value in counts.items()))
