"""
Ask Meta for the review status of every active number's message templates, and keep it (plan Step 4.7, user
story WA.D3.OM.J2.A2), so the WhatsApp page shows whether a business's order templates are approved.

The beat task runs the same check once a day; run this from a daily cron job instead on a deployment without
a Celery worker (agents.md section 4.1). Safe to run any number of times. With WHATSAPP_SEND_BACKEND=LOG
nothing reaches Meta.

A number Meta refuses (one business's revoked token, say) doesn't stop the others: the command goes on, then
ends with an error naming every number refused, so cron or a person still sees the failure.

    docker compose run --rm backend python manage.py whatsapp_check_template_statuses
"""

from django.core.management.base import BaseCommand, CommandError

from ...services import templates


class Command(BaseCommand):
    help = "Ask Meta for the review status of every active number's message templates."

    def handle(self, *args, **options):
        result = templates.check_all()
        for account, error in result["failed"].items():
            self.stdout.write(self.style.ERROR(f"{account}: refused by Meta: {error}"))
        self.stdout.write(f"checked={result['checked']} failed={len(result['failed'])}")
        if result["failed"]:
            refused = "; ".join(str(account) for account in result["failed"])
            raise CommandError(f"Meta refused the template check of {len(result['failed'])} number(s): {refused}")
