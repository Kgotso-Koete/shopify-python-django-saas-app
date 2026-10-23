"""
Every stored PayFast enum value becomes its member's name (PayFast plan section 14, agents.md section
5.3b): "active" becomes "ACTIVE", "subscription" becomes "SUBSCRIPTION", "complete" becomes
"COMPLETE", and the frequency codes 3 and 6 become "MONTHLY" and "ANNUAL". PayFast's own codes are
looked up only where the checkout form is built (constants.payfast_frequency_code).

PayFast is released (6.0.0), so this runs on production data, and it has a reverse:
- forward: the frequency columns become text (Postgres casts 3 to "3"), then the rows are rewritten
- backward: the rows get their old values back, then the frequency columns become integers again
  (Postgres casts "3" back to 3)

The other fields only change their choices, which the database doesn't enforce, so their order doesn't
matter. PayFastPayment.payment_status is PayFast's own COMPLETE or CANCELLED and is left alone.
"""

from django.db import migrations, models

# Model name -> field -> old stored value -> new stored value. The frequency columns hold text by the
# time the rows are rewritten, so the old codes are matched as "3" and "6".
OLD_TO_NEW = {
    "PayFastSubscription": {
        "status": {
            "active": "ACTIVE",
            "trialing": "TRIALING",
            "past_due": "PAST_DUE",
            "cancelled": "CANCELLED",
        },
        "frequency": {"3": "MONTHLY", "6": "ANNUAL"},
    },
    "PayFastCheckout": {
        "kind": {"subscription": "SUBSCRIPTION", "donation": "DONATION"},
        "status": {"pending": "PENDING", "complete": "COMPLETE"},
        "frequency": {"3": "MONTHLY", "6": "ANNUAL"},
    },
    "PayFastPayment": {
        "kind": {"subscription": "SUBSCRIPTION", "donation": "DONATION"},
    },
}

FREQUENCY_CHOICES = [("MONTHLY", "Monthly"), ("ANNUAL", "Annual")]
KIND_CHOICES = [("SUBSCRIPTION", "Subscription"), ("DONATION", "Donation")]


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
        model = apps.get_model("payfast", model_name)
        for field, values in fields.items():
            for old, new in values.items():
                model.objects.filter(**{field: old}).update(**{field: new})


class Migration(migrations.Migration):
    dependencies = [
        ("payfast", "0003_payment_caught_up"),
    ]

    operations = [
        # First the frequency columns become text, so they can hold the names.
        migrations.AlterField(
            model_name="payfastsubscription",
            name="frequency",
            field=models.CharField(blank=True, choices=FREQUENCY_CHOICES, max_length=16, null=True),
        ),
        migrations.AlterField(
            model_name="payfastcheckout",
            name="frequency",
            field=models.CharField(blank=True, choices=FREQUENCY_CHOICES, max_length=16, null=True),
        ),
        migrations.RunPython(store_member_names, store_old_values),
        # Then the other fields' choices and defaults, as the models now declare them.
        migrations.AlterField(
            model_name="payfastsubscription",
            name="status",
            field=models.CharField(
                choices=[
                    ("ACTIVE", "Active"),
                    ("TRIALING", "Trialing"),
                    ("PAST_DUE", "Past due"),
                    ("CANCELLED", "Cancelled"),
                ],
                default="ACTIVE",
                max_length=16,
            ),
        ),
        migrations.AlterField(
            model_name="payfastcheckout",
            name="kind",
            field=models.CharField(choices=KIND_CHOICES, max_length=16),
        ),
        migrations.AlterField(
            model_name="payfastcheckout",
            name="status",
            field=models.CharField(
                choices=[("PENDING", "Pending"), ("COMPLETE", "Complete")], default="PENDING", max_length=16
            ),
        ),
        migrations.AlterField(
            model_name="payfastpayment",
            name="kind",
            field=models.CharField(choices=KIND_CHOICES, max_length=16),
        ),
    ]
