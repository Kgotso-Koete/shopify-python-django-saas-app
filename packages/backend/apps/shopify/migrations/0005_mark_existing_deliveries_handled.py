# Written by hand (WhatsApp plan Step 4.3e). Deliveries stored before handled_at existed were
# dispatched when they arrived, so they count as handled; otherwise a repeat of one, or the sweep for
# unhandled deliveries, would run its handler a second time (an old app/uninstalled would wipe the
# tokens of a store installed again since).

from django.db import migrations
from django.db.models import F


def mark_existing_deliveries_handled(apps, schema_editor):
    ShopifyWebhookDelivery = apps.get_model("shopify", "ShopifyWebhookDelivery")
    ShopifyWebhookDelivery.objects.filter(handled_at__isnull=True).update(handled_at=F("created_at"))


class Migration(migrations.Migration):
    dependencies = [
        ("shopify", "0004_shopifywebhookdelivery_handled_at"),
    ]

    operations = [
        migrations.RunPython(mark_existing_deliveries_handled, migrations.RunPython.noop),
    ]
