"""
Tests for the PayFast management commands (apps/payfast/management/commands/).
"""

import pytest
from django.core.management import CommandError, call_command

from apps.multitenancy.constants import TenantUserRole
from ..models import PayFastPayment

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("payfast_backend")]


@pytest.fixture
def owner(user_factory, tenant, tenant_membership_factory):
    """A user who owns `tenant`, the organisations the seed command fills in."""
    user = user_factory()
    tenant_membership_factory(tenant=tenant, user=user, role=TenantUserRole.OWNER)
    return user


class TestSeedDemo:
    def test_seeds_example_payments_in_development(self, settings, owner):
        settings.PAYFAST_ENVIRONMENT = "development"

        call_command("payfast_seed_demo", email=owner.email)

        assert PayFastPayment.objects.filter(pf_payment_id__startswith="seed-").exists()

    def test_refuses_to_run_in_production(self, settings, owner):
        # Plan section 12, issue 6: fake payments must never reach a live transaction history.
        settings.PAYFAST_ENVIRONMENT = "production"

        with pytest.raises(CommandError, match="production"):
            call_command("payfast_seed_demo", email=owner.email)

        assert not PayFastPayment.objects.exists()
