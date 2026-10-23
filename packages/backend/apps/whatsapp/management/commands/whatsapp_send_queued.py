"""
Send every queued WhatsApp reply (plan Step 1.4d, decision D21).

The safety net for the send queue in services/outbox.py. A deployment without a Celery worker
(CELERY_TASK_ALWAYS_EAGER) needs it from cron: there, a reply that fails for a passing reason (a rate
limit, a timeout) stays queued for this command, which is the wait such a deployment can't give
otherwise. With a worker it's still useful: it picks up queues a crashed process or a `busy` drain
left behind. Safe to run at any time, and any number of times, even alongside the worker.

    docker compose run --rm backend python manage.py whatsapp_send_queued

From cron, every 5 minutes:

    */5 * * * * cd /app && python manage.py whatsapp_send_queued
"""

from django.core.management.base import BaseCommand

from apps.whatsapp.services import outbox


class Command(BaseCommand):
    help = "Send every queued WhatsApp reply, in order, one contact at a time."

    def handle(self, *args, **options):
        counts = outbox.drain_all()
        # Counts only, never a message: cron output often ends up in an email or a log.
        self.stdout.write(
            f"WhatsApp send queue: {counts['checked']} contacts checked, {counts['sent']} sent, "
            f"{counts['busy']} busy, {counts['waiting']} waiting, {counts['to_retry']} to retry, "
            f"{counts['given_up']} given up."
        )
