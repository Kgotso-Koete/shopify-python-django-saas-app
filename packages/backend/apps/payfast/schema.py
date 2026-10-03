"""
GraphQL API for PayFast billing. Always part of the schema (config/schema.py), whichever payment
backend is active, so the web app's generated types never depend on configuration; the resolvers
refuse to act unless PAYMENT_BACKEND is "payfast".

Permissions mirror the Stripe resolvers in apps/finances/schema.py: `billing.view` to read a
tenant's billing data, `billing.manage` to change it, and nothing for public information.
"""

import uuid

import graphene
from django.conf import settings
from graphene import relay
from graphene.types.generic import GenericScalar
from graphene_django import DjangoObjectType
from graphql_relay import from_global_id

from apps.multitenancy.constants import ActionType
from common.acl.policies import AnyoneFullAccess, IsTenantMemberAccess
from common.action_logging.service import log_action
from common.graphql import exceptions
from common.graphql.acl import permission_classes, requires
from . import constants, services
from .models import PayFastCheckout, PayFastPayment

# Billing intervals as the web app names them, per PayFast frequency.
INTERVALS = {constants.Frequency.MONTHLY: "month", constants.Frequency.ANNUAL: "year"}


def validation_error(message: str) -> exceptions.GraphQlValidationError:
    """A user-facing error in the shape the web app's useApiForm shows as a generic form error."""
    return exceptions.GraphQlValidationError({"non_field_errors": [message]})


def require_payfast():
    if settings.PAYMENT_BACKEND != settings.PAYMENT_BACKEND_PAYFAST:
        raise validation_error("PayFast is not the active payment backend.")


def web_app_url(path: str) -> str:
    """
    An absolute URL on our own web app for a relative `path` such as "/en/<tenant>/subscriptions".
    Only same-site relative paths are accepted; otherwise any caller could make PayFast redirect our
    customers to a site of their choosing after payment.
    """
    if not path or not path.startswith("/") or path.startswith("//") or "\\" in path:
        raise validation_error("Return and cancel paths must be paths on this web app.")
    return f"{settings.WEB_APP_URL.rstrip('/')}{path}"


def request_tenant(info, tenant_id):
    """The request's tenant, after checking it is the one named by `tenant_id`."""
    tenant = getattr(info.context, "tenant", None)
    if tenant is None:
        raise validation_error("Organisation not found.")
    try:
        _, pk = from_global_id(tenant_id)
    except Exception:  # noqa: BLE001 - graphql_relay raises several error types for bad ids
        pk = None
    if str(tenant.pk) not in {str(pk), str(tenant_id)}:
        raise validation_error("Organisation not found.")
    return tenant


# --- Types -----------------------------------------------------------------------------------------


class PaymentConfigType(graphene.ObjectType):
    """Which payment backend the server uses, so the web app can show the matching pages."""

    backend = graphene.String(required=True)
    currency = graphene.String(required=True)


class PayFastPlanType(graphene.ObjectType):
    name = graphene.String(required=True)
    amount = graphene.Decimal(required=True)
    currency = graphene.String(required=True)
    interval = graphene.String(description="month, year, or null for the free plan")


class PayFastSubscriptionType(graphene.ObjectType):
    plan = graphene.String(required=True, description="The plan paid for in the current period")
    effective_plan = graphene.String(required=True, description="The plan the organisation has right now")
    pending_plan = graphene.String(description="A plan change that takes effect at the next renewal")
    pending_amount = graphene.Decimal(description="What the pending plan charges, from the next renewal")
    status = graphene.String(required=True)
    amount = graphene.Decimal(required=True)
    current_period_start = graphene.DateTime()
    current_period_end = graphene.DateTime()
    trial_end = graphene.DateTime()
    cancel_at_period_end = graphene.Boolean(required=True)
    can_activate_trial = graphene.Boolean(required=True)
    has_card = graphene.Boolean(required=True)
    card_update_url = graphene.String(
        return_path=graphene.String(), description="PayFast-hosted page to update the card on file"
    )

    @staticmethod
    def resolve_effective_plan(parent, info):
        return parent.effective_plan()

    @staticmethod
    def resolve_pending_plan(parent, info):
        return parent.pending_plan or None

    @staticmethod
    def resolve_card_update_url(parent, info, return_path=None):
        return_url = web_app_url(return_path) if return_path else settings.WEB_APP_URL
        return services.card_update_url(parent, return_url=return_url)


class PayFastPaymentType(DjangoObjectType):
    class Meta:
        model = PayFastPayment
        interfaces = (relay.Node,)
        fields = ("id", "pf_payment_id", "kind", "plan", "amount_gross", "item_name", "payment_status", "created_at")
        # Plain strings ("donation", "subscription") instead of generated GraphQL enums.
        convert_choices_to_enum = False


class PayFastPaymentConnection(graphene.Connection):
    class Meta:
        node = PayFastPaymentType


class PayFastCheckoutType(graphene.ObjectType):
    """POST `fields` to `action_url` (an HTML form) to send the buyer to PayFast."""

    action_url = graphene.String(required=True)
    fields = GenericScalar(required=True)
    m_payment_id = graphene.ID(required=True)


def checkout_type(form: services.CheckoutForm) -> PayFastCheckoutType:
    return PayFastCheckoutType(action_url=form.action_url, fields=form.fields, m_payment_id=str(form.m_payment_id))


# --- Queries ---------------------------------------------------------------------------------------


class Query(graphene.ObjectType):
    payment_config = graphene.Field(PaymentConfigType, required=True)
    payfast_subscription_plans = graphene.List(graphene.NonNull(PayFastPlanType), required=True)
    payfast_donation_amounts = graphene.List(graphene.NonNull(graphene.Decimal), required=True)
    payfast_active_subscription = graphene.Field(PayFastSubscriptionType, tenant_id=graphene.ID(required=True))
    payfast_payments = relay.ConnectionField(PayFastPaymentConnection, tenant_id=graphene.ID(required=True))
    payfast_checkout_status = graphene.String(
        tenant_id=graphene.ID(required=True), m_payment_id=graphene.ID(required=True)
    )

    @staticmethod
    @permission_classes(AnyoneFullAccess)
    def resolve_payment_config(root, info):
        is_payfast = settings.PAYMENT_BACKEND == settings.PAYMENT_BACKEND_PAYFAST
        return PaymentConfigType(backend=settings.PAYMENT_BACKEND, currency=constants.CURRENCY if is_payfast else "USD")

    @staticmethod
    @permission_classes(AnyoneFullAccess)
    def resolve_payfast_subscription_plans(root, info):
        return [
            PayFastPlanType(
                name=plan.name,
                amount=plan.amount,
                currency=constants.CURRENCY,
                interval=INTERVALS.get(plan.frequency),
            )
            for plan in constants.plan_prices().values()
        ]

    @staticmethod
    @permission_classes(AnyoneFullAccess)
    def resolve_payfast_donation_amounts(root, info):
        return constants.donation_amounts()

    @staticmethod
    @permission_classes(IsTenantMemberAccess, requires("billing.view"))
    def resolve_payfast_active_subscription(root, info, tenant_id, **kwargs):
        require_payfast()
        return services.get_subscription(request_tenant(info, tenant_id))

    @staticmethod
    @permission_classes(IsTenantMemberAccess, requires("billing.view"))
    def resolve_payfast_payments(root, info, tenant_id, **kwargs):
        require_payfast()
        # Only real charges: not R0 trial starts, and not cancellation notices.
        return PayFastPayment.objects.filter(
            tenant=request_tenant(info, tenant_id), payment_status="COMPLETE", amount_gross__gt=0
        ).order_by("-created_at")

    @staticmethod
    @permission_classes(IsTenantMemberAccess, requires("billing.view"))
    def resolve_payfast_checkout_status(root, info, tenant_id, m_payment_id, **kwargs):
        require_payfast()
        try:
            checkout_id = uuid.UUID(str(m_payment_id))
        except ValueError:
            return None
        checkout = PayFastCheckout.objects.filter(
            tenant=request_tenant(info, tenant_id), m_payment_id=checkout_id
        ).first()
        return checkout.status if checkout else None


# --- Mutations -------------------------------------------------------------------------------------


class PayFastCreateCheckoutMutation(relay.ClientIDMutation):
    """
    Start a subscription, or switch a paying organisation to another plan: returns the signed PayFast
    form for the chosen paid plan (services.create_subscription_checkout).
    """

    class Input:
        tenant_id = graphene.String(required=True)
        plan = graphene.String(required=True)
        return_path = graphene.String(required=True)
        cancel_path = graphene.String(required=True)

    checkout = graphene.Field(PayFastCheckoutType)

    @classmethod
    def mutate_and_get_payload(cls, root, info, tenant_id, plan, return_path, cancel_path, **kwargs):
        require_payfast()
        tenant = request_tenant(info, tenant_id)
        return_url, cancel_url = web_app_url(return_path), web_app_url(cancel_path)
        try:
            form = services.create_subscription_checkout(
                tenant=tenant, user=info.context.user, plan_name=plan, return_url=return_url, cancel_url=cancel_url
            )
        except services.PayFastError as error:
            raise validation_error(str(error)) from error
        return cls(checkout=checkout_type(form))


class PayFastCreateDonationCheckoutMutation(relay.ClientIDMutation):
    """Start a once-off donation of one of the offered amounts."""

    class Input:
        tenant_id = graphene.String(required=True)
        amount = graphene.String(required=True)
        return_path = graphene.String(required=True)
        cancel_path = graphene.String(required=True)

    checkout = graphene.Field(PayFastCheckoutType)

    @classmethod
    def mutate_and_get_payload(cls, root, info, tenant_id, amount, return_path, cancel_path, **kwargs):
        require_payfast()
        tenant = request_tenant(info, tenant_id)
        return_url, cancel_url = web_app_url(return_path), web_app_url(cancel_path)
        try:
            form = services.create_donation_checkout(
                tenant=tenant, user=info.context.user, amount=amount, return_url=return_url, cancel_url=cancel_url
            )
        except services.PayFastError as error:
            raise validation_error(str(error)) from error
        return cls(checkout=checkout_type(form))


class PayFastCancelSubscriptionMutation(relay.ClientIDMutation):
    """Cancel the paid plan: billing stops now, the plan lasts until the end of the period."""

    class Input:
        tenant_id = graphene.String(required=True)

    active_subscription = graphene.Field(PayFastSubscriptionType)

    @classmethod
    def mutate_and_get_payload(cls, root, info, tenant_id, **kwargs):
        require_payfast()
        tenant = request_tenant(info, tenant_id)
        try:
            subscription = services.cancel_subscription(tenant=tenant)
        except services.PayFastError as error:
            raise validation_error(str(error)) from error

        # Same audit entry as the Stripe CancelActiveSubscriptionMutation.
        log_action(
            tenant_id=tenant.pk,
            action_type=ActionType.DELETE,
            entity_type="subscription",
            entity_id=str(tenant.pk),
            entity_name="Subscription",
            actor_user=info.context.user,
            changes={"status": {"old": "active", "new": "cancelled"}},
        )
        return cls(active_subscription=subscription)


@permission_classes(IsTenantMemberAccess)
class Mutation(graphene.ObjectType):
    """PayFast billing mutations; all require tenant membership plus billing.manage."""

    payfast_create_checkout = permission_classes(requires("billing.manage"))(PayFastCreateCheckoutMutation.Field())
    payfast_create_donation_checkout = permission_classes(requires("billing.manage"))(
        PayFastCreateDonationCheckoutMutation.Field()
    )
    payfast_cancel_subscription = permission_classes(requires("billing.manage"))(
        PayFastCancelSubscriptionMutation.Field()
    )
