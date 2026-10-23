"""
Every WhatsApp number belongs to an organization (WhatsApp plan Step 1.17): there's no platform number.

- The old platform number's rows, which had no organization, are deleted, with their contacts, messages
  and links. They exist only in development. The reverse can't bring them back, and doesn't try.
- An organization has at most one active internal communications number.
- A user's link names the internal number it was made on, and a user has one link per number instead of
  one in all.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def delete_numbers_without_an_organization(apps, schema_editor):
    apps.get_model("whatsapp", "WhatsAppAccount").objects.filter(tenant__isnull=True).delete()
    if schema_editor is not None:
        # The deletes cascade through foreign keys Postgres checks at commit; checking them now lets
        # this migration alter the same tables next.
        schema_editor.execute("SET CONSTRAINTS ALL IMMEDIATE")


def name_each_links_number(apps, schema_editor):
    identity = apps.get_model("whatsapp", "WhatsAppIdentity")
    for linked in identity.objects.select_related("contact"):
        linked.account_id = linked.contact.account_id
        linked.save(update_fields=["account"])


class Migration(migrations.Migration):
    dependencies = [
        ("whatsapp", "0014_alter_whatsappaccount_connection_method_and_more"),
        ("multitenancy", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RemoveConstraint(model_name="whatsappaccount", name="whatsapp_account_tenant_matches_purpose"),
        migrations.RunPython(delete_numbers_without_an_organization, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="whatsappaccount",
            name="tenant",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="whatsapp_accounts",
                to="multitenancy.tenant",
            ),
        ),
        migrations.AddConstraint(
            model_name="whatsappaccount",
            constraint=models.UniqueConstraint(
                condition=models.Q(("is_active", True), ("purpose", "INTERNAL_COMMUNICATIONS")),
                fields=("tenant",),
                name="whatsapp_account_one_active_internal_per_tenant",
            ),
        ),
        migrations.AlterField(
            model_name="whatsappidentity",
            name="user",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="whatsapp_identities",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="whatsappidentity",
            name="account",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="identities",
                to="whatsapp.whatsappaccount",
            ),
        ),
        migrations.RunPython(name_each_links_number, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="whatsappidentity",
            name="account",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="identities",
                to="whatsapp.whatsappaccount",
            ),
        ),
        migrations.AddConstraint(
            model_name="whatsappidentity",
            constraint=models.UniqueConstraint(
                fields=("user", "account"), name="whatsapp_identity_unique_user_per_account"
            ),
        ),
    ]
