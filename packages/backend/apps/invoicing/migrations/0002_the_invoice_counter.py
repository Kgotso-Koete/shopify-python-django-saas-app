"""
The service's one invoice counter row (WhatsApp plan phase 4, decision 11), created here so issuing an
invoice only ever locks it with select_for_update, and never races another issue to create it.
"""

from django.db import migrations

THE_ONE = 1


def create_the_counter(apps, schema_editor):
    InvoiceCounter = apps.get_model("invoicing", "InvoiceCounter")
    InvoiceCounter.objects.get_or_create(pk=THE_ONE)


class Migration(migrations.Migration):
    dependencies = [
        ("invoicing", "0001_initial"),
    ]

    operations = [
        # Nothing to undo: dropping the table in 0001's reverse removes the row.
        migrations.RunPython(create_the_counter, migrations.RunPython.noop),
    ]
