"""
Submit the order templates (apps/whatsapp_shop/templates.py, plan phase 4, Step 4.3d-2) to every active
number serving customers' WhatsApp Business account.

Connecting a number submits them already; this is for numbers connected before Step 4.3d-2, and after the
templates' wording changes (Step 4.7 replaced two templates with one, and retires the old two). Safe to run any
number of times: a template submitted with the same content is left alone, and a changed one is edited
in place (Meta allows one edit a day of an approved template). With WHATSAPP_SEND_BACKEND=LOG nothing
reaches Meta and fake ids are stored.

A number Meta refuses (one business's revoked token, say) doesn't stop the others (plan Step 4.6): its
reason is printed and the command goes on, then ends with an error naming every number refused, so cron
or a person still sees the failure. Running it again retries only those; the rest are up to date.

    docker compose run --rm backend python manage.py whatsapp_publish_order_templates
"""

from django.core.management.base import BaseCommand, CommandError

from apps.whatsapp.client import SendError
from apps.whatsapp.models import WhatsAppAccount

from ...templates import CUSTOMER_PURPOSES, publish_order_templates


class Command(BaseCommand):
    help = "Submit the order templates to every active number serving customers' WhatsApp Business account."

    def handle(self, *args, **options):
        numbers = WhatsAppAccount.objects.filter(purpose__in=CUSTOMER_PURPOSES, is_active=True).order_by("pk")
        if not numbers:
            self.stdout.write(
                "There's no number serving customers yet. Connect one on an organization's WhatsApp page."
            )
            return

        refused = []
        for account in numbers:
            self.stdout.write(f"{account}:")
            try:
                published = publish_order_templates(account)
            except SendError as error:
                # Meta's own words, e.g. why it refused the template or an edit; then the next number.
                self.stdout.write(self.style.ERROR(f"  Refused by Meta: {error}"))
                refused.append(str(account))
                continue
            for name, template, changed in published:
                if changed:
                    self.stdout.write(self.style.SUCCESS(f"  Submitted {name}: template id {template.template_id}"))
                else:
                    self.stdout.write(f"  {name} is up to date: template id {template.template_id}")

        if refused:
            raise CommandError(f"Meta refused the templates of {len(refused)} number(s): {'; '.join(refused)}")
