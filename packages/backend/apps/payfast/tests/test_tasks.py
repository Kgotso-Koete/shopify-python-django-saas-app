"""
Tests for the daily maintenance entry points: the Celery task, its beat schedule entry, and the
equivalent management command for deployments without Celery (docs/superpowers/agents.md, 4.1).
What the maintenance does is tested in test_services.py::TestDailyMaintenance.
"""

from io import StringIO
from unittest import mock

import pytest
from django.core.management import call_command

from .. import tasks
from ..models import PayFastSubscription
from .utils import read_settings

pytestmark = pytest.mark.django_db

COUNTS = {"trial_reminders": 1, "renewals_checked": 2, "ended": 0}


class TestDailyMaintenanceTask:
    def test_task_runs_the_daily_maintenance(self, payfast_backend):
        with mock.patch("apps.payfast.services.run_daily_maintenance", return_value=COUNTS) as run:
            assert tasks.daily_maintenance() == COUNTS

        run.assert_called_once_with()

    def test_task_does_nothing_when_payfast_is_not_the_backend(self, settings):
        # Beat entries can outlive a backend switch until beat restarts; the task must then be a no-op.
        settings.PAYMENT_BACKEND = "stripe"
        with mock.patch("apps.payfast.services.run_daily_maintenance") as run:
            tasks.daily_maintenance()

        run.assert_not_called()


class TestBeatSchedule:
    def test_task_is_scheduled_daily_when_payfast_is_the_backend(self):
        schedule = read_settings(["CELERY_BEAT_SCHEDULE"], PAYMENT_BACKEND="payfast")["CELERY_BEAT_SCHEDULE"]

        assert "'payfast-daily-maintenance'" in schedule
        assert "'apps.payfast.tasks.daily_maintenance'" in schedule
        assert "86400" in schedule  # every 24 hours, in seconds

    def test_task_is_not_scheduled_for_stripe(self):
        schedule = read_settings(["CELERY_BEAT_SCHEDULE"], PAYMENT_BACKEND="stripe")["CELERY_BEAT_SCHEDULE"]

        assert "payfast" not in schedule


class TestDailyMaintenanceCommand:
    def test_command_runs_the_daily_maintenance_and_reports_counts(self, payfast_backend):
        out = StringIO()
        with mock.patch("apps.payfast.services.run_daily_maintenance", return_value=COUNTS) as run:
            call_command("payfast_daily_maintenance", stdout=out)

        run.assert_called_once_with()
        assert "trial_reminders=1" in out.getvalue()
        assert "renewals_checked=2" in out.getvalue()


class TestInitTenantsCommand:
    def test_backfills_a_free_subscription_for_tenants_without_one(self, payfast_backend, tenant_factory):
        # Switching an existing deployment from Stripe to PayFast: older tenants have no PayFast record.
        tenants = [tenant_factory(), tenant_factory()]
        PayFastSubscription.objects.filter(tenant__in=tenants).delete()
        out = StringIO()

        call_command("payfast_init_tenants", stdout=out)

        assert PayFastSubscription.objects.filter(tenant__in=tenants, plan="free_plan").count() == 2
        assert "Created" in out.getvalue()

    def test_is_safe_to_run_twice(self, payfast_backend, tenant):
        call_command("payfast_init_tenants", stdout=StringIO())
        call_command("payfast_init_tenants", stdout=StringIO())

        assert PayFastSubscription.objects.filter(tenant=tenant).count() == 1
