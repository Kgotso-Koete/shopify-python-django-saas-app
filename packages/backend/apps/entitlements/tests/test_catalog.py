"""
Tests for apps.entitlements' catalog of what each plan includes (WhatsApp plan Step 3.1, phase 3
decisions 1 and 2, user story 26).

- a feature is an enum stored by its names (agents.md section 5.3b)
- the data migration lists `free_plan` with nothing, and `monthly_plan` and `yearly_plan` with
  SHOPIFY and WHATSAPP
- the database refuses a plan that isn't one of the plans in code, a feature that isn't one of the
  enum's, and the same plan and feature twice
- the admin shows the rows read-only: they change only through migrations, so every change is a
  commit with a test

Kind of test: integration (agents.md section 2.5). Why: the rows the data migration created, and the
database's constraints, in the test database; nothing is faked.
"""

import pytest
from django.contrib import admin
from django.db import IntegrityError, transaction

from apps.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def models():
    # Imported here, not at the top, so a missing app fails each test instead of the whole file.
    from apps.entitlements import models as module

    return module


def refused(**fields):
    """Whether the database refuses a row with these fields."""
    try:
        with transaction.atomic():
            models().PlanFeature.objects.create(**fields)
    except IntegrityError:
        return True
    return False


class TestTheFeatures:
    def test_each_is_stored_as_its_own_name(self):
        from apps.entitlements.constants import Feature

        assert [(feature.value, feature.label) for feature in Feature] == [
            ("SHOPIFY", "Shopify"),
            ("WHATSAPP", "WhatsApp"),
        ]


class TestTheCatalog:
    def test_the_migration_lists_what_each_plan_includes(self):
        rows = sorted(models().PlanFeature.objects.values_list("plan", "feature"))

        # free_plan has no rows: it includes neither (decision 1).
        assert rows == [
            ("monthly_plan", "SHOPIFY"),
            ("monthly_plan", "WHATSAPP"),
            ("yearly_plan", "SHOPIFY"),
            ("yearly_plan", "WHATSAPP"),
        ]

    def test_a_plan_that_isnt_in_code_is_refused(self):
        assert refused(plan="gold_plan", feature="SHOPIFY")

    def test_a_feature_that_isnt_in_the_enum_is_refused(self):
        assert refused(plan="free_plan", feature="INVOICES")

    def test_a_plan_and_feature_appear_once(self):
        assert refused(plan="monthly_plan", feature="SHOPIFY")

    def test_a_new_row_for_a_plan_in_code_is_taken(self):
        assert not refused(plan="free_plan", feature="SHOPIFY")


class TestTheAdmin:
    def test_it_shows_the_rows_but_never_changes_them(self, rf):
        model_admin = admin.site._registry[models().PlanFeature]
        request = rf.get("/")
        # A superuser may do anything the admin allows; is_staff follows from it on this User model.
        request.user = UserFactory(is_superuser=True)

        assert model_admin.has_view_permission(request)
        assert not model_admin.has_add_permission(request)
        assert not model_admin.has_change_permission(request)
        assert not model_admin.has_delete_permission(request)
