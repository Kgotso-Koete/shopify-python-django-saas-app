"""
The catalog of what each plan includes (WhatsApp plan phase 3, decision 2): one row per plan and
feature, so a plan's name and its features can be seen together in the database, as the role
permissions can.

The plans themselves stay in code (apps.finances.constants), by name, as both payment backends know
them. The rows are created by data migrations, never by hand: the admin shows them read-only, so a
change is a commit with a test and a changelog entry, and every deployment has the same rows.
"""

from django.db import models
from django.db.models import Q

from apps.finances.constants import ALL_PLANS
from common.models import TimestampedMixin

from .constants import Feature

PLAN_NAME_MAX_LENGTH = 32
PLAN_NAMES = [plan.name for plan in ALL_PLANS]


class PlanFeature(TimestampedMixin, models.Model):
    # The plan's name in code, such as "monthly_plan"; a plan added in code needs a migration here.
    plan = models.CharField(max_length=PLAN_NAME_MAX_LENGTH, choices=[(name, name) for name in PLAN_NAMES])
    feature = models.CharField(max_length=32, choices=Feature.choices)

    class Meta:
        verbose_name = "Plan feature"
        ordering = ["plan", "feature"]
        constraints = [
            models.UniqueConstraint(fields=["plan", "feature"], name="entitlements_plan_feature_once"),
            # The database itself refuses a made-up plan or feature, not only forms.
            models.CheckConstraint(condition=Q(plan__in=PLAN_NAMES), name="entitlements_plan_in_code"),
            models.CheckConstraint(condition=Q(feature__in=Feature.values), name="entitlements_feature_known"),
        ]

    def __str__(self):
        return f"{self.plan} includes {self.feature}"
