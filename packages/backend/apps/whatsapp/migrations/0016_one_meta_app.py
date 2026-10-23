"""
Every number is on our one Meta app (WhatsApp plan Step 1.18): its App secret and verify token are
settings, so a number no longer stores either.

`webhook_verified_at` meant "Meta checked the webhook with this number's own token", which our app's
one webhook can't prove per number. It's replaced by `subscribed_at`, "our app is subscribed to the
number's WhatsApp Business account", rather than renamed, because the old times don't mean that.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("whatsapp", "0015_every_number_belongs_to_an_organization"),
    ]

    operations = [
        migrations.RemoveConstraint(model_name="whatsappaccount", name="whatsapp_account_unique_verify_token_hash"),
        migrations.RemoveField(model_name="whatsappaccount", name="app_secret_encrypted"),
        migrations.RemoveField(model_name="whatsappaccount", name="webhook_verify_token_hash"),
        migrations.RemoveField(model_name="whatsappaccount", name="webhook_verified_at"),
        migrations.AddField(
            model_name="whatsappaccount",
            name="subscribed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
