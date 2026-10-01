"""
Backend-agnostic entry points for the few billing actions that code outside the payment apps needs,
dispatched to Stripe or PayFast according to settings.PAYMENT_BACKEND.

Callers (the tenant signal, tenant deletion) use these instead of calling a provider directly, so
they don't need to know which provider is active. The Stripe branches do exactly what those
callers did before PayFast existed. See docs/superpowers/plans/2026-09-30-payfast-payment-backend-plan.md section 3.3.
"""

from django.conf import settings

from apps.payfast import services as payfast_services
from .serializers import CancelTenantActiveSubscriptionSerializer
from .services import subscriptions


def is_payfast() -> bool:
    return settings.PAYMENT_BACKEND == settings.PAYMENT_BACKEND_PAYFAST


def initialize_tenant(tenant):
    """Put a new tenant on the free plan with the active payment provider."""
    if is_payfast():
        return payfast_services.initialize_tenant(tenant)
    return subscriptions.initialize_tenant(tenant=tenant)


def cancel_tenant_subscription(tenant):
    """Stop billing a tenant that is being deleted."""
    if is_payfast():
        payfast_services.cancel_tenant_subscription_immediately(tenant)
        return

    # Stripe: the code previously inline in apps.multitenancy.schema.DeleteTenantMutation, unchanged.
    schedule = subscriptions.get_schedule(tenant)
    if schedule:
        cancel_subscription_serializer = CancelTenantActiveSubscriptionSerializer(instance=schedule, data={})
        if cancel_subscription_serializer.is_valid():
            cancel_subscription_serializer.save()
