from celery import shared_task
from django.conf import settings


@shared_task(ignore_result=True)
def daily_maintenance():
    """
    Run PayFast's daily maintenance (trial reminders, overdue renewals, ended subscriptions).
    Scheduled in CELERY_BEAT_SCHEDULE when PAYMENT_BACKEND == "payfast"; without Celery, run
    `python manage.py payfast_daily_maintenance` from a daily cron job instead.
    """
    # A beat entry can outlive a switch back to Stripe until beat restarts; do nothing then.
    if settings.PAYMENT_BACKEND != settings.PAYMENT_BACKEND_PAYFAST:
        return None

    from . import services

    return services.run_daily_maintenance()
