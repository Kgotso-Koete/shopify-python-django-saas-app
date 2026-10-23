"""
Publish this app's WhatsApp Flows (the forms in apps/whatsapp_saas/flows/) to every active internal
communications number's WhatsApp Business account (plan Step 1.11, decision D9, Step 1.17).

Connecting a number publishes its forms already; this is for after a form's JSON changes. Safe to
run any number of times: a form whose JSON hasn't changed since it was last published is left alone,
and a changed one is published as a new Flow (Meta doesn't allow editing a published Flow). With
WHATSAPP_SEND_BACKEND=LOG nothing reaches Meta and fake ids are stored, so the menus can be tried
locally.

    docker compose run --rm backend python manage.py whatsapp_publish_flows
"""

from django.core.management.base import BaseCommand, CommandError

from apps.whatsapp.client import SendError
from apps.whatsapp.constants import AccountPurpose
from apps.whatsapp.models import WhatsAppAccount

from ...publishing import publish_forms


class Command(BaseCommand):
    help = "Publish the WhatsApp Flows to every active internal communications number's WhatsApp Business account."

    def handle(self, *args, **options):
        internal_numbers = WhatsAppAccount.objects.filter(
            purpose=AccountPurpose.INTERNAL_COMMUNICATIONS, is_active=True
        ).order_by("pk")
        if not internal_numbers:
            self.stdout.write(
                "There's no internal communications number yet. Connect one on an organization's WhatsApp tab."
            )
            return

        for account in internal_numbers:
            self.stdout.write(f"{account}:")
            try:
                published = publish_forms(account)
            except SendError as error:
                # Meta's own words, e.g. its validation errors for the JSON.
                raise CommandError(f"{account}: {error}") from error
            for name, flow, changed in published:
                if changed:
                    self.stdout.write(self.style.SUCCESS(f"  Published {name}: Flow id {flow.flow_id}"))
                else:
                    self.stdout.write(f"  {name} is up to date: Flow id {flow.flow_id}")
