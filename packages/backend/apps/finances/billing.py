"""
Backend-agnostic entry points for the few billing actions that code outside the payment apps needs,
dispatched to Stripe or PayFast according to settings.PAYMENT_BACKEND.

Callers (the tenant signal, tenant deletion) use these instead of calling a provider directly, so
they don't need to know which provider is active. The Stripe branches do exactly what those
callers did before PayFast existed. See docs/superpowers/plans/2026-09-30-payfast-payment-backend-plan.md section 3.3.
"""

from django.conf import settings
from djstripe import enums as djstripe_enums, models as djstripe_models

from apps.payfast import services as payfast_services
from . import constants
from .serializers import CancelTenantActiveSubscriptionSerializer
from .services import subscriptions

# The Stripe subscription statuses Stripe still bills, so its plan still applies: active, trialing,
# and past_due while Stripe retries the payment, the counterpart of PayFast's 7-day grace. Stripe
# ends a failed renewal as unpaid or canceled, which count as the free plan, as PayFast's do:
# https://docs.stripe.com/billing/subscriptions/overview#subscription-statuses
STRIPE_BILLED_STATUSES = (
    djstripe_enums.SubscriptionStatus.active,
    djstripe_enums.SubscriptionStatus.trialing,
    djstripe_enums.SubscriptionStatus.past_due,
)


def is_payfast() -> bool:
    return settings.PAYMENT_BACKEND == settings.PAYMENT_BACKEND_PAYFAST


def initialize_tenant(tenant):
    """Put a new tenant on the free plan with the active payment provider."""
    if is_payfast():
        return payfast_services.initialize_tenant(tenant)
    return subscriptions.initialize_tenant(tenant=tenant)


def effective_plan(tenant) -> str:
    """
    The name of the plan that applies to `tenant` right now, such as "monthly_plan", the same way for
    both providers (WhatsApp plan Step 3.2, phase 3 decision 2). A trial counts as the plan being
    trialled; anything no longer billed counts as the free plan.

    It only reads: unlike subscriptions.get_schedule(tenant), it never asks Stripe to create a
    customer, so a feature check can't call Stripe.
    """
    free = constants.FREE_PLAN.name
    if is_payfast():
        # Computed on read, so a trial or period that ends counts at once (apps.payfast.models).
        return payfast_services.get_subscription(tenant).effective_plan()

    customer = djstripe_models.Customer.objects.filter(subscriber=tenant).first()
    if customer is None or not customer.subscriptions.filter(status__in=STRIPE_BILLED_STATUSES).exists():
        return free
    schedule = subscriptions.get_schedule(customer=customer)
    if schedule is None:
        return free
    try:
        phase = subscriptions.get_current_schedule_phase(schedule)
    except IndexError:
        # Every phase has ended: nothing is scheduled to be billed.
        return free
    price = djstripe_models.Price.objects.filter(id=phase["items"][0]["price"]).select_related("product").first()
    return price.product.name if price else free


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
