"""
The WhatsApp page's API for which store each external number sells from (plan Step 2.1b, decision 5,
user story WA.D3.OM.J1.A3), modelled on apps/whatsapp/schema.py.

- whatsAppStorefronts lists the organization's external numbers, each with its store or none; it
  needs whatsapp.view, like the numbers themselves.
- whatsAppEligibleStores and chooseWhatsAppStore serve the store picker; they need whatsapp.manage.
- setWhatsAppStorefrontMode sets menus or the assistant for a number's customers (phase 2, decision
  2); it needs whatsapp.manage too.

The connect form makes two calls: apps.whatsapp's connectWhatsAppAccount, then chooseWhatsAppStore,
which also changes the store later (decision 5). The organization is always the one the tenant
middleware checked the user belongs to (info.context.tenant), never one taken from the input.
"""

import graphene

from apps.whatsapp.constants import AccountPurpose, ConversationMode
from apps.whatsapp.models import WhatsAppAccount
from apps.whatsapp.schema import ConversationModeEnum
from common.acl.policies import IsTenantMemberAccess
from common.graphql import exceptions
from common.graphql.acl import permission_classes, requires

from . import failed_updates, services
from .services import StoreChannelError


class WhatsAppStorefrontType(graphene.ObjectType):
    """
    One external number, the store it sells from and its customers' mode; shopDomain and
    conversationMode are null while no store is chosen.
    """

    account_id = graphene.ID(required=True)
    shop_domain = graphene.String()
    conversation_mode = graphene.Field(ConversationModeEnum)


def _storefront(account) -> dict:
    channel = services.channel_for(account)
    return {
        # The account's hashid, as WhatsAppAccountType.id gives it, so the web app can match the rows.
        "account_id": str(account.id),
        "shop_domain": channel.shop.shop_domain if channel else None,
        "conversation_mode": ConversationMode(channel.conversation_mode) if channel else None,
    }


def _tenant(info):
    """The organization the tenant middleware checked the user belongs to."""
    return getattr(info.context, "tenant", None)


def _user_error(error: StoreChannelError) -> exceptions.GraphQlValidationError:
    # The same shape as apps.whatsapp's errors: under the field at fault, or non_field_errors.
    return exceptions.GraphQlValidationError({error.field or "non_field_errors": [str(error)]}, code=error.code)


class StorefrontsQuery(graphene.ObjectType):
    whats_app_storefronts = graphene.List(
        graphene.NonNull(WhatsAppStorefrontType), tenant_id=graphene.ID(required=True), required=True
    )
    whats_app_eligible_stores = graphene.List(
        graphene.NonNull(graphene.String), tenant_id=graphene.ID(required=True), required=True
    )

    @staticmethod
    @permission_classes(IsTenantMemberAccess, requires("whatsapp.view"))
    def resolve_whats_app_storefronts(root, info, tenant_id):
        tenant = _tenant(info)
        if tenant is None:
            return []
        # Numbers serving customers only, external or both (Step 2.7): a team-only number never sells.
        numbers = WhatsAppAccount.objects.filter(
            tenant=tenant,
            purpose__in=[purpose for purpose in AccountPurpose.values if AccountPurpose.serves_customers(purpose)],
        ).order_by("created_at")
        return [_storefront(account) for account in numbers]

    @staticmethod
    @permission_classes(IsTenantMemberAccess, requires("whatsapp.manage"))
    def resolve_whats_app_eligible_stores(root, info, tenant_id):
        tenant = _tenant(info)
        if tenant is None:
            return []
        return [shop.shop_domain for shop in services.eligible_stores(tenant)]


OrderStageEnum = graphene.Enum.from_enum(failed_updates.OrderStage, name="WhatsAppOrderStage")


class WhatsAppFailedOrderUpdateType(graphene.ObjectType):
    """
    An order update WhatsApp couldn't deliver (plan Step 4.7, user story WA.D3.OM.J2.A3): which order stage, on
    which number, to which customer, when it failed, and Meta's reason in plain words.
    """

    checkout_id = graphene.ID(required=True)
    stage = graphene.Field(OrderStageEnum, required=True)
    account_id = graphene.ID(required=True)
    number = graphene.String(required=True)
    # The customer's WhatsApp profile name, or their number when they have none.
    customer = graphene.String(required=True)
    failed_at = graphene.DateTime(required=True)
    # Meta's error code, or null when Meta couldn't be reached.
    error_code = graphene.Int()
    reason = graphene.String(required=True)


def _failed_update(update: failed_updates.FailedUpdate) -> dict:
    contact = update.checkout.store_customer.contact
    return {
        "checkout_id": str(update.checkout.pk),
        "stage": update.stage,
        "account_id": str(contact.account.id),
        "number": contact.account.display_phone_number,
        "customer": contact.profile_name or contact.wa_id,
        "failed_at": update.message.updated_at,
        "error_code": update.message.error_code,
        "reason": update.reason,
    }


class FailedOrderUpdatesQuery(graphene.ObjectType):
    whats_app_failed_order_updates = graphene.List(
        graphene.NonNull(WhatsAppFailedOrderUpdateType), tenant_id=graphene.ID(required=True), required=True
    )

    @staticmethod
    @permission_classes(IsTenantMemberAccess, requires("whatsapp.view"))
    def resolve_whats_app_failed_order_updates(root, info, tenant_id):
        tenant = _tenant(info)
        if tenant is None:
            return []
        return [_failed_update(update) for update in failed_updates.failed_updates(tenant)]


class Query(StorefrontsQuery, FailedOrderUpdatesQuery, graphene.ObjectType):
    pass


class SendWhatsAppOrderUpdateAgainInput(graphene.InputObjectType):
    tenant_id = graphene.ID(required=True)
    checkout_id = graphene.ID(required=True)
    stage = graphene.Field(OrderStageEnum, required=True)


class SendWhatsAppOrderUpdateAgain(graphene.Mutation):
    """Send a failed order update again, built fresh from the order Shopify has now (user story WA.D3.OM.J2.A3)."""

    class Arguments:
        input = SendWhatsAppOrderUpdateAgainInput(required=True)

    checkout_id = graphene.ID(required=True)
    stage = graphene.Field(OrderStageEnum, required=True)

    @classmethod
    def mutate(cls, root, info, input):
        stage = failed_updates.OrderStage(input.stage)
        try:
            checkout = failed_updates.send_again(_tenant(info), input.checkout_id, stage)
        except failed_updates.FailedUpdateError as error:
            raise exceptions.GraphQlValidationError({"non_field_errors": [str(error)]}, code=error.code) from error
        return cls(checkout_id=str(checkout.pk), stage=stage)


class ChooseWhatsAppStoreInput(graphene.InputObjectType):
    tenant_id = graphene.ID(required=True)
    account_id = graphene.ID(required=True)
    shop_domain = graphene.String(required=True)


class ChooseWhatsAppStore(graphene.Mutation):
    """Make one of the organization's external numbers sell from one of its stores, or change it."""

    class Arguments:
        input = ChooseWhatsAppStoreInput(required=True)

    storefront = graphene.Field(WhatsAppStorefrontType, required=True)

    @classmethod
    def mutate(cls, root, info, input):
        try:
            channel = services.choose_store(
                tenant=_tenant(info), account_id=input.account_id, shop_domain=input.shop_domain
            )
        except StoreChannelError as error:
            raise _user_error(error) from error
        return cls(storefront=_storefront(channel.account))


class SetWhatsAppStorefrontModeInput(graphene.InputObjectType):
    tenant_id = graphene.ID(required=True)
    account_id = graphene.ID(required=True)
    mode = graphene.Field(ConversationModeEnum, required=True)


class SetWhatsAppStorefrontMode(graphene.Mutation):
    """Menus or the assistant for every customer of one of the organization's external numbers."""

    class Arguments:
        input = SetWhatsAppStorefrontModeInput(required=True)

    storefront = graphene.Field(WhatsAppStorefrontType, required=True)

    @classmethod
    def mutate(cls, root, info, input):
        try:
            channel = services.set_mode(
                tenant=_tenant(info), account_id=input.account_id, mode=ConversationMode(input.mode).value
            )
        except StoreChannelError as error:
            raise _user_error(error) from error
        return cls(storefront=_storefront(channel.account))


@permission_classes(IsTenantMemberAccess)
class Mutation(graphene.ObjectType):
    # Choosing a number's store and its customers' mode sets it up, which needs no plan (plan Step
    # 2.8, finding 16); its customers get replies only on a plan that includes WhatsApp.
    choose_whats_app_store = permission_classes(requires("whatsapp.manage"))(ChooseWhatsAppStore.Field())
    set_whats_app_storefront_mode = permission_classes(requires("whatsapp.manage"))(SetWhatsAppStorefrontMode.Field())
    # Step 4.7, user story WA.D3.OM.J2.A3.
    send_whats_app_order_update_again = permission_classes(requires("whatsapp.manage"))(
        SendWhatsAppOrderUpdateAgain.Field()
    )
