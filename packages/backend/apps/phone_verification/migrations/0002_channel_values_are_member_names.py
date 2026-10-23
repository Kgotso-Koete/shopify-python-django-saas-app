"""
The stored channel becomes its member's name (WhatsApp plan Step 1.16, agents.md section 5.3b):
"whatsapp_inbound" becomes "WHATSAPP_INBOUND", and so on. The reverse restores the old values.

A code binds its channel into its HMAC, so codes issued before this migration stop matching. They
last minutes, so that's accepted rather than repaired. The field's choices follow in the next
migration, which makemigrations generated.
"""

from django.db import migrations

OLD_TO_NEW = {
    "whatsapp_inbound": "WHATSAPP_INBOUND",
    "whatsapp_template": "WHATSAPP_TEMPLATE",
    "sms": "SMS",
}


def store_member_names(apps, schema_editor):
    _rewrite(apps, OLD_TO_NEW)


def store_old_values(apps, schema_editor):
    _rewrite(apps, {new: old for old, new in OLD_TO_NEW.items()})


def _rewrite(apps, mapping):
    code = apps.get_model("phone_verification", "PhoneVerificationCode")
    for old, new in mapping.items():
        code.objects.filter(channel=old).update(channel=new)


class Migration(migrations.Migration):
    dependencies = [
        ("phone_verification", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(store_member_names, store_old_values),
    ]
