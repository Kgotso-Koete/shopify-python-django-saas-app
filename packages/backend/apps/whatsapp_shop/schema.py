"""
The WhatsApp page's API for which store each external number sells from (plan Step 2.1b, decision 5,
user story 25), modelled on apps/whatsapp/schema.py.

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
from apps.whatsapp.schema import WHATSAPP_PLAN, ConversationModeEnum
from common.acl.policies import IsTenantMemberAccess
from common.graphql import exceptions
from common.graphql.acl import permission_classes, requires

from . import services
from .models import StorefrontChannel
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
    channel = StorefrontChannel.objects.filter(account=account).select_related("shop").first()
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


class Query(graphene.ObjectType):
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
    # Changing a number's store or mode uses WhatsApp, so the plan must include it (plan phase 3,
    # decision 5); listing the numbers' stores doesn't.
    choose_whats_app_store = permission_classes(requires("whatsapp.manage"), WHATSAPP_PLAN)(ChooseWhatsAppStore.Field())
    set_whats_app_storefront_mode = permission_classes(requires("whatsapp.manage"), WHATSAPP_PLAN)(
        SetWhatsAppStorefrontMode.Field()
    )
