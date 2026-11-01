"""
What each plan includes, as decided for WhatsApp plan phase 3 (decision 1, 2026-10-31): the free
plan includes neither Shopify nor WhatsApp, and the monthly and yearly plans include both. A trial
includes what the plan being trialled includes, so it needs no rows of its own.

The plan names are written out, not imported, so this migration keeps meaning what it meant when it
ran, whatever the code says later. Changing what a plan includes is a new migration like this one.
"""

from django.db import migrations

ROWS = [
    ("monthly_plan", "SHOPIFY"),
    ("monthly_plan", "WHATSAPP"),
    ("yearly_plan", "SHOPIFY"),
    ("yearly_plan", "WHATSAPP"),
]


def add_rows(apps, schema_editor):
    PlanFeature = apps.get_model("entitlements", "PlanFeature")
    for plan, feature in ROWS:
        PlanFeature.objects.get_or_create(plan=plan, feature=feature)


def remove_rows(apps, schema_editor):
    PlanFeature = apps.get_model("entitlements", "PlanFeature")
    for plan, feature in ROWS:
        PlanFeature.objects.filter(plan=plan, feature=feature).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("entitlements", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(add_rows, remove_rows),
    ]
