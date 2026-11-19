"""
Submit the link code template (apps/whatsapp/services/identity.py, plan phase 7, user story WA.D1.OM.J1.A3) to
every active team number's WhatsApp Business account: the authentication template a member receives their link
code in when PHONE_VERIFICATION_CHANNEL is WHATSAPP_TEMPLATE.

Connecting a team number submits it already; this is for numbers connected before the channel was switched on.
Safe to run any number of times: a template submitted with the same content is left alone. With
WHATSAPP_SEND_BACKEND=LOG nothing reaches Meta. A number Meta refuses doesn't stop the others; the command ends
with an error naming every number refused.

    docker compose run --rm backend python manage.py whatsapp_publish_link_templates
"""

from django.core.management.base import BaseCommand, CommandError

from ...client import SendError
from ...constants import TEAM_PURPOSES
from ...models import WhatsAppAccount
from ...services import identity


class Command(BaseCommand):
    help = "Submit the link code template to every active team number's WhatsApp Business account."

    def handle(self, *args, **options):
        refused = []
        for account in WhatsAppAccount.objects.filter(purpose__in=TEAM_PURPOSES, is_active=True).order_by("pk"):
            try:
                template, changed = identity.publish_link_template(account)
            except SendError as error:
                self.stdout.write(self.style.ERROR(f"{account}: refused by Meta: {error}"))
                refused.append(str(account))
                continue
            state = "submitted" if changed else "up to date"
            self.stdout.write(f"{account}: {identity.LINK_TEMPLATE} {state}, template id {template.template_id}")
        if refused:
            raise CommandError(f"Meta refused the link code template of {len(refused)} number(s): {'; '.join(refused)}")
