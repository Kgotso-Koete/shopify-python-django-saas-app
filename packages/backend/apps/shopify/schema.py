import graphene
from graphene_django import DjangoObjectType
from django.conf import settings
from django.core.signing import TimestampSigner, BadSignature, SignatureExpired
from graphql import GraphQLError

from apps.shopify.models import ShopifyShop
from apps.shopify.services import start_install
from apps.multitenancy.models import Tenant
from apps.multitenancy.constants import ActionEntityType, ActionType
from common.action_logging.service import log_action
from common.graphql.acl import permission_classes, requires
from common.acl.policies import AnyoneFullAccess, IsTenantMemberAccess, IsAuthenticatedFullAccess


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


class Query(graphene.ObjectType):
    shopify_config = graphene.Field(graphene.NonNull(ShopifyConfigType))
    shopify_shops = graphene.List(
        graphene.NonNull(ShopifyShopType), tenant_id=graphene.ID(required=True), required=True
    )
    shopify_claim = graphene.Field(ShopifyClaimType, claim=graphene.String(required=True))

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
    shopify_start_install = permission_classes(requires("shopify.manage"))(ShopifyStartInstall.Field())
    shopify_link_shop = permission_classes(requires("shopify.manage"))(ShopifyLinkShop.Field())
    shopify_disconnect_shop = permission_classes(requires("shopify.manage"))(ShopifyDisconnectShop.Field())
