"""
Every stored enum value becomes its member's name (WhatsApp plan Step 1.16, agents.md section 5.3b):
"platform" becomes "INTERNAL_COMMUNICATIONS", "in" becomes "INBOUND", "sent" becomes "SENT", and so on.
The reverse restores the old values.

The account check constraint names the purposes, so it's dropped before the rows change and added
back, with the new names, after them. The fields' choices follow in the next migration, which
makemigrations generated; choices aren't enforced by the database, so their order doesn't matter.
"""

from django.db import migrations, models

# Model name -> field -> old stored value -> new stored value.
OLD_TO_NEW = {
    "WhatsAppAccount": {
        "purpose": {
            "platform": "INTERNAL_COMMUNICATIONS",
            "storefront": "EXTERNAL_COMMUNICATIONS",
        },
        "connection_method": {
            "seed": "SEED",
            "manual": "MANUAL",
            "embedded_signup": "EMBEDDED_SIGNUP",
        },
    },
    "WhatsAppMessage": {
        "direction": {"in": "INBOUND", "out": "OUTBOUND"},
        "kind": {
            "text": "TEXT",
            "button_reply": "BUTTON_REPLY",
            "list_reply": "LIST_REPLY",
            "flow_reply": "FLOW_REPLY",
            "unsupported": "UNSUPPORTED",
            "interactive": "INTERACTIVE",
        },
        "status": {
            "received": "RECEIVED",
            "processed": "PROCESSED",
            "queued": "QUEUED",
            "accepted": "ACCEPTED",
            "sent": "SENT",
            "delivered": "DELIVERED",
            "read": "READ",
            "played": "PLAYED",
            "failed": "FAILED",
            "cancelled": "CANCELLED",
        },
    },
    # An empty conversation mode means "the default applies" and isn't in the mapping, so it stays empty.
    "WhatsAppIdentity": {"conversation_mode": {"whatsapp_form": "WHATSAPP_FORM", "agentic": "AGENTIC"}},
}

CONSTRAINT_NAME = "whatsapp_account_tenant_matches_purpose"


def store_member_names(apps, schema_editor):
    _rewrite(apps, OLD_TO_NEW)


def store_old_values(apps, schema_editor):
    _rewrite(
        apps,
        {
            model: {field: {new: old for old, new in values.items()} for field, values in fields.items()}
            for model, fields in OLD_TO_NEW.items()
        },
    )


def _rewrite(apps, mapping):
    for model_name, fields in mapping.items():
        model = apps.get_model("whatsapp", model_name)
        for field, values in fields.items():
            for old, new in values.items():
                model.objects.filter(**{field: old}).update(**{field: new})


def _constraint(internal: str, external: str) -> models.CheckConstraint:
    return models.CheckConstraint(
        condition=models.Q(
            models.Q(("purpose", internal), ("tenant__isnull", True)),
            models.Q(("purpose", external), ("tenant__isnull", False)),
            _connector="OR",
        ),
        name=CONSTRAINT_NAME,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("whatsapp", "0012_whatsappagentitem"),
    ]

    operations = [
        migrations.RemoveConstraint(model_name="whatsappaccount", name=CONSTRAINT_NAME),
        migrations.RunPython(store_member_names, store_old_values),
        migrations.AddConstraint(
            model_name="whatsappaccount",
            constraint=_constraint("INTERNAL_COMMUNICATIONS", "EXTERNAL_COMMUNICATIONS"),
        ),
    ]
