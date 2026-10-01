"""
Tests for apps/finances/billing.py, the small dispatch module that sends the few backend-agnostic
billing actions to Stripe or PayFast depending on PAYMENT_BACKEND:

- a new tenant gets the free plan (apps/finances/signals.py);
- a deleted tenant's paid subscription is cancelled (apps/multitenancy/schema.py DeleteTenantMutation).

With the default PAYMENT_BACKEND=stripe, both must behave exactly as before.
See docs/superpowers/plans/2026-09-30-payfast-payment-backend-plan.md section 3.3.
"""

from unittest import mock

import pytest
from graphql_relay import to_global_id

from apps.multitenancy.constants import TenantType, TenantUserRole
from apps.payfast.models import PayFastSubscription
from .. import billing

pytestmark = pytest.mark.django_db

DELETE_TENANT_MUTATION = '''
    mutation DeleteTenant($input: DeleteTenantMutationInput!) {
      deleteTenant(input: $input) {
        deletedIds
      }
    }
'''


class TestNewTenantGetsTheFreePlan:
    def test_with_payfast_a_free_payfast_subscription_is_created(self, payfast_backend, tenant_factory):
        with mock.patch("apps.finances.services.subscriptions.initialize_tenant") as stripe_initialize:
            tenant = tenant_factory()

        assert PayFastSubscription.objects.get(tenant=tenant).plan == "free_plan"
        # No Stripe call when PayFast is the backend.
        stripe_initialize.assert_not_called()

    def test_with_stripe_the_stripe_initialization_runs_as_before(self, settings, tenant_factory):
        settings.PAYMENT_BACKEND = "stripe"
        settings.STRIPE_ENABLED = True
        with mock.patch("apps.finances.services.subscriptions.initialize_tenant") as stripe_initialize:
            tenant = tenant_factory()

        # (The user factory also creates the user's own default tenant, so there may be other calls.)
        stripe_initialize.assert_any_call(tenant=tenant)
        assert not PayFastSubscription.objects.filter(tenant=tenant).exists()


class TestCancelTenantSubscription:
    def test_with_payfast_the_payfast_subscription_is_cancelled(self, payfast_backend, tenant):
        with mock.patch("apps.payfast.services.cancel_tenant_subscription_immediately") as payfast_cancel:
            billing.cancel_tenant_subscription(tenant)

        payfast_cancel.assert_called_once_with(tenant)

    def test_with_stripe_the_active_schedule_is_cancelled_as_before(self, settings, tenant):
        settings.PAYMENT_BACKEND = "stripe"
        schedule = mock.Mock()
        with (
            mock.patch("apps.finances.billing.subscriptions.get_schedule", return_value=schedule) as get_schedule,
            mock.patch("apps.finances.billing.CancelTenantActiveSubscriptionSerializer") as serializer_class,
        ):
            billing.cancel_tenant_subscription(tenant)

        get_schedule.assert_called_once_with(tenant)
        serializer_class.assert_called_once_with(instance=schedule, data={})
        serializer_class.return_value.save.assert_called_once()

    def test_with_stripe_and_no_schedule_nothing_is_cancelled(self, settings, tenant):
        settings.PAYMENT_BACKEND = "stripe"
        with (
            mock.patch("apps.finances.billing.subscriptions.get_schedule", return_value=None),
            mock.patch("apps.finances.billing.CancelTenantActiveSubscriptionSerializer") as serializer_class,
        ):
            billing.cancel_tenant_subscription(tenant)

        serializer_class.assert_not_called()


class TestDeleteTenantUsesBilling:
    def test_deleting_a_tenant_cancels_its_payfast_subscription(
        self,
        payfast_backend,
        payfast_api,
        graphene_client,
        user,
        tenant_factory,
        tenant_membership_factory,
        pay_fast_subscription_factory,
    ):
        tenant = tenant_factory(name="Tenant 1", type=TenantType.ORGANIZATION)
        tenant_membership_factory(tenant=tenant, user=user, role=TenantUserRole.OWNER)
        subscription = pay_fast_subscription_factory(tenant=tenant, monthly=True)
        # Captured now: Django clears the pk of the (shared) tenant instance once it is deleted.
        global_tenant_id = to_global_id("TenantType", tenant.id)
        graphene_client.force_authenticate(user)
        graphene_client.set_tenant_dependent_context(tenant, TenantUserRole.OWNER)

        executed = graphene_client.mutate(DELETE_TENANT_MUTATION, variable_values={"input": {"id": global_tenant_id}})

        assert executed["data"]["deleteTenant"]["deletedIds"] == [global_tenant_id]
        # PayFast must stop charging a tenant that no longer exists.
        payfast_api.cancel.assert_called_once_with(subscription.token)
