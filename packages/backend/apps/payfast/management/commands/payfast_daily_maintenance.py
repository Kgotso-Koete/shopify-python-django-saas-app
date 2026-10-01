from django.core.management.base import BaseCommand

from apps.payfast import services


class Command(BaseCommand):
    help = (
        "Run PayFast daily maintenance: trial-ending emails, overdue renewal checks and ending cancelled "
        "subscriptions. Celery beat runs this daily when PAYMENT_BACKEND=payfast; without Celery, run it "
        "from a daily cron job."
    )

    def handle(self, *args, **options):
        counts = services.run_daily_maintenance()
        self.stdout.write(" ".join(f"{name}={value}" for name, value in counts.items()))
