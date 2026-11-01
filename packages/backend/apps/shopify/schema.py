import graphene
from graphene_django import DjangoObjectType
from django.conf import settings
from django.core.signing import TimestampSigner, BadSignature, SignatureExpired
from graphql import GraphQLError

from apps.shopify.models import ShopifyShop
from apps.shopify.products import ShopifyReconnectRequired, ShopifyTryAgainLater, fetch_products
from apps.shopify.services import start_install
from apps.multitenancy.models import Tenant
from apps.multitenancy.constants import ActionEntityType, ActionType
from common.action_logging.service import log_action
from common.graphql import exceptions
from common.graphql.acl import permission_classes, requires
from common.acl.policies import AnyoneFullAccess, IsTenantMemberAccess, IsAuthenticatedFullAccess
from apps.entitlements.constants import Feature
from apps.entitlements.permissions import requires_feature

# Fields that use Shopify need the organization's plan to include it (WhatsApp plan phase 3, decision
# 5). Listing its stores, and disconnecting one, don't: a lapsed organization's stores are kept.
SHOPIFY_PLAN = requires_feature(Feature.SHOPIFY)


class ShopifyConfigType(graphene.ObjectType):
    enabled = graphene.Boolean(required=True)


class ShopifyShopType(DjangoObjectType):
    class Meta:
        model = ShopifyShop
        fields = ("shop_domain", "installed_at", "uninstalled_at", "needs_reinstall")

    scopes = graphene.List(graphene.NonNull(graphene.String), required=True)

    def resolve_scopes(self, info):
        if not self.scopes:
            return []
        return [s.strip() for s in self.scopes.split(",") if s.strip()]


class ShopifyClaimType(graphene.ObjectType):
    shop_domain = graphene.String(required=True)


# The products page (plan step 11). Fields match the plain dicts from products.fetch_products.
class ShopifyProductType(graphene.ObjectType):
    id = graphene.ID(required=True)
    title = graphene.String(required=True)
    handle = graphene.String(required=True)
    status = graphene.String(required=True)
    image_url = graphene.String()
    image_alt = graphene.String()
    # Decimal strings as Shopify sends them, so no rounding on the way to the browser.
    price_min = graphene.String(required=True)
    price_max = graphene.String(required=True)
    currency_code = graphene.String(required=True)


class ShopifyProductsPageInfoType(graphene.ObjectType):
    has_next_page = graphene.Boolean(required=True)
    has_previous_page = graphene.Boolean(required=True)
    start_cursor = graphene.String()
    end_cursor = graphene.String()


class ShopifyProductsType(graphene.ObjectType):
    products = graphene.List(graphene.NonNull(ShopifyProductType), required=True)
    page_info = graphene.Field(graphene.NonNull(ShopifyProductsPageInfoType))


def _user_error(message: str, code: str) -> exceptions.GraphQlValidationError:
    # GraphQlValidationError is on SanitizeErrorsMiddleware's safe list, so the message and code reach
    # the browser in production too, as extensions {"non_field_errors": [{"message": ..., "code": ...}]},
    # the same shape apps/payfast/schema.py uses.
    return exceptions.GraphQlValidationError({"non_field_errors": [message]}, code=code)


class Query(graphene.ObjectType):
    shopify_config = graphene.Field(graphene.NonNull(ShopifyConfigType))
    shopify_shops = graphene.List(
        graphene.NonNull(ShopifyShopType), tenant_id=graphene.ID(required=True), required=True
    )
    shopify_claim = graphene.Field(ShopifyClaimType, claim=graphene.String(required=True))
    shopify_products = graphene.Field(
        graphene.NonNull(ShopifyProductsType),
        tenant_id=graphene.ID(required=True),
        shop_domain=graphene.String(required=True),
        first=graphene.Int(required=True),
        after=graphene.String(),
        before=graphene.String(),
    )

    @staticmethod
    @permission_classes(AnyoneFullAccess)
    def resolve_shopify_config(root, info):
        return ShopifyConfigType(enabled=settings.SHOPIFY_ENABLED)

    @staticmethod
    @permission_classes(IsTenantMemberAccess, requires("shopify.view"))
    def resolve_shopify_shops(root, info, tenant_id):
        from graphql_relay import from_global_id

        try:
            _, pk = from_global_id(tenant_id)
        except Exception:
            pk = tenant_id
        return ShopifyShop.objects.filter(tenant_id=pk)

    @staticmethod
    @permission_classes(IsTenantMemberAccess, requires("shopify.view"), SHOPIFY_PLAN)
    def resolve_shopify_products(root, info, tenant_id, shop_domain, first, after=None, before=None):
        # The tenant comes from the request context, which the tenant middleware has already checked
        # the user belongs to. A store of another organization is then simply not found, with the same
        # answer as a missing one. No tenant must never match the unlinked stores (tenant NULL).
        tenant = getattr(info.context, "tenant", None)
        shop = ShopifyShop.objects.filter(tenant=tenant, shop_domain=shop_domain).first() if tenant else None
        if shop is None:
            raise _user_error("Store not found.", "store_not_found")

        try:
            return fetch_products(shop, first=first, after=after, before=before)
        except ShopifyReconnectRequired as error:
            raise _user_error(str(error), "reconnect_required") from error
        except ShopifyTryAgainLater as error:
            raise _user_error(str(error), "try_again_later") from error

    @staticmethod
    @permission_classes(IsAuthenticatedFullAccess)
    def resolve_shopify_claim(root, info, claim):
        signer = TimestampSigner()
        try:
            shop_id = signer.unsign(claim, max_age=3600)  # 1 hour
            shop = ShopifyShop.objects.get(id=shop_id, tenant__isnull=True)
            return ShopifyClaimType(shop_domain=shop.shop_domain)
        except (BadSignature, SignatureExpired, ShopifyShop.DoesNotExist):
            raise GraphQLError("Invalid or expired claim. Store is already connected or the link has expired.")


class ShopifyStartInstallInput(graphene.InputObjectType):
    tenant_id = graphene.ID(required=True)
    shop_domain = graphene.String(required=True)


class ShopifyStartInstall(graphene.Mutation):
    class Arguments:
        input = ShopifyStartInstallInput(required=True)

    authorize_url = graphene.String(required=True)

    @classmethod
    def mutate(cls, root, info, input):
        from apps.shopify.verification import is_valid_shop_domain

        if not is_valid_shop_domain(input.shop_domain):
            raise GraphQLError("Invalid shop domain.")

        from graphql_relay import from_global_id

        try:
            _, tenant_pk = from_global_id(input.tenant_id)
        except Exception:
            tenant_pk = input.tenant_id

        tenant = Tenant.objects.get(id=tenant_pk)
        url = start_install(input.shop_domain, tenant=tenant, user=info.context.user)
        return cls(authorize_url=url)


class ShopifyLinkShopInput(graphene.InputObjectType):
    tenant_id = graphene.ID(required=True)
    claim = graphene.String(required=True)


class ShopifyLinkShop(graphene.Mutation):
    class Arguments:
        input = ShopifyLinkShopInput(required=True)

    shop = graphene.Field(ShopifyShopType)

    @classmethod
    def mutate(cls, root, info, input):
        signer = TimestampSigner()
        try:
            shop_id = signer.unsign(input.claim, max_age=3600)
            from django.db import transaction

            from graphql_relay import from_global_id

            try:
                _, tenant_pk = from_global_id(input.tenant_id)
            except Exception:
                tenant_pk = input.tenant_id

            tenant = Tenant.objects.get(id=tenant_pk)

            with transaction.atomic():
                shop = ShopifyShop.objects.select_for_update().get(id=shop_id)
                if shop.tenant_id is not None:
                    raise GraphQLError("Store is already connected.")
                shop.tenant = tenant
                shop.save(update_fields=["tenant_id"])

                log_action(
                    actor_user=info.context.user,
                    tenant_id=tenant.pk,
                    action_type=ActionType.CREATE,
                    entity_type=ActionEntityType.SHOPIFY_SHOP,
                    entity_id=str(shop.id),
                    entity_name=shop.shop_domain,
                )

            return cls(shop=shop)
        except (BadSignature, SignatureExpired, ShopifyShop.DoesNotExist):
            raise GraphQLError("Invalid or expired claim. Store is already connected or the link has expired.")


class ShopifyDisconnectShopInput(graphene.InputObjectType):
    tenant_id = graphene.ID(required=True)
    shop_domain = graphene.String(required=True)


class ShopifyDisconnectShop(graphene.Mutation):
    class Arguments:
        input = ShopifyDisconnectShopInput(required=True)

    ok = graphene.Boolean(required=True)

    @classmethod
    def mutate(cls, root, info, input):
        from django.db import transaction

        from graphql_relay import from_global_id

        try:
            _, tenant_pk = from_global_id(input.tenant_id)
        except Exception:
            tenant_pk = input.tenant_id

        tenant = Tenant.objects.get(id=tenant_pk)

        with transaction.atomic():
            shop = ShopifyShop.objects.filter(shop_domain=input.shop_domain, tenant=tenant).first()
            if shop:
                shop.tenant = None
                shop.save(update_fields=["tenant_id"])

                log_action(
                    actor_user=info.context.user,
                    tenant_id=tenant.pk,
                    action_type=ActionType.DELETE,
                    entity_type=ActionEntityType.SHOPIFY_SHOP,
                    entity_id=str(shop.id),
                    entity_name=shop.shop_domain,
                )
        return cls(ok=True)


@permission_classes(IsTenantMemberAccess)
class Mutation(graphene.ObjectType):
    shopify_start_install = permission_classes(requires("shopify.manage"), SHOPIFY_PLAN)(ShopifyStartInstall.Field())
    shopify_link_shop = permission_classes(requires("shopify.manage"), SHOPIFY_PLAN)(ShopifyLinkShop.Field())
    shopify_disconnect_shop = permission_classes(requires("shopify.manage"))(ShopifyDisconnectShop.Field())
