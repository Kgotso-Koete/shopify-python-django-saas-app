import pytest
from django.conf import settings
from django.core.signing import TimestampSigner
from graphql_relay import to_global_id

from apps.shopify.models import ShopifyShop
from apps.multitenancy.tests.factories import TenantFactory, TenantMembershipFactory
from apps.users.tests.factories import UserFactory
from apps.multitenancy.constants import TenantUserRole

pytestmark = pytest.mark.django_db


def test_shopify_shops_requires_shopify_view(graphene_client):
    user = UserFactory()
    tenant = TenantFactory()
    TenantMembershipFactory(user=user, tenant=tenant, role=TenantUserRole.MEMBER)
    # MEMBER gets shopify.view by default (apps/shopify/permissions.py), so take it away
    # to stand for any role without it.
    _remove_permission(tenant, TenantUserRole.MEMBER, "shopify.view")

    graphene_client.force_authenticate(user)
    graphene_client.set_tenant_dependent_context(tenant, TenantUserRole.MEMBER)

    query = """
    query($tenantId: ID!) {
      shopifyShops(tenantId: $tenantId) {
        shopDomain
      }
    }
    """
    response = graphene_client.query(query, variable_values={"tenantId": to_global_id("TenantType", tenant.id)})

    assert "errors" in response
    assert "permission" in response["errors"][0]["message"].lower()


def test_shopify_shops_with_shopify_view(graphene_client):
    user = UserFactory()
    tenant = TenantFactory()
    TenantMembershipFactory(user=user, tenant=tenant, role=TenantUserRole.ADMIN)
    _ensure_permission(tenant, TenantUserRole.ADMIN, "shopify.view")

    ShopifyShop.objects.create(
        shop_domain="test.myshopify.com",
        tenant=tenant,
        access_token="acc_123",
        refresh_token="ref_123",
        scopes="read_products",
        needs_reinstall=False,
    )

    graphene_client.force_authenticate(user)
    graphene_client.set_tenant_dependent_context(tenant, TenantUserRole.ADMIN)

    query = """
    query($tenantId: ID!) {
      shopifyShops(tenantId: $tenantId) {
        shopDomain
        scopes
        needsReinstall
      }
    }
    """
    response = graphene_client.query(query, variable_values={"tenantId": to_global_id("TenantType", tenant.id)})

    assert "errors" not in response
    assert len(response["data"]["shopifyShops"]) == 1
    assert response["data"]["shopifyShops"][0]["shopDomain"] == "test.myshopify.com"
    # Ensure no token fields are exposed
    assert "access_token" not in response["data"]["shopifyShops"][0]


def _ensure_permission(tenant, role_type, code):
    from apps.multitenancy.models import Permission, OrganizationRole, OrganizationRolePermission

    perm, _ = Permission.objects.get_or_create(code=code, defaults={"name": code, "category": "SHOPIFY"})
    role = OrganizationRole.objects.get(tenant=tenant, system_role_type=role_type)
    OrganizationRolePermission.objects.get_or_create(role=role, permission=perm)


def _remove_permission(tenant, role_type, code):
    from apps.multitenancy.models import OrganizationRolePermission

    OrganizationRolePermission.objects.filter(
        role__tenant=tenant, role__system_role_type=role_type, permission__code=code
    ).delete()


def test_member_without_shopify_manage_cannot_start_link_or_disconnect(graphene_client):
    user = UserFactory()
    tenant = TenantFactory()
    TenantMembershipFactory(user=user, tenant=tenant, role=TenantUserRole.MEMBER)

    graphene_client.force_authenticate(user)
    graphene_client.set_tenant_dependent_context(tenant, TenantUserRole.MEMBER)

    # 1. Start Install
    mutation = """
    mutation($input: ShopifyStartInstallInput!) {
      shopifyStartInstall(input: $input) {
        authorizeUrl
      }
    }
    """
    response = graphene_client.mutate(
        mutation,
        variable_values={
            "input": {"tenantId": to_global_id("TenantType", tenant.id), "shopDomain": "test.myshopify.com"}
        },
    )
    assert "errors" in response
    assert "permission" in response["errors"][0]["message"].lower()

    # 2. Link Shop
    mutation = """
    mutation($input: ShopifyLinkShopInput!) {
      shopifyLinkShop(input: $input) {
        shop {
          shopDomain
        }
      }
    }
    """
    response = graphene_client.mutate(
        mutation, variable_values={"input": {"tenantId": to_global_id("TenantType", tenant.id), "claim": "fake_claim"}}
    )
    assert "errors" in response
    assert "permission" in response["errors"][0]["message"].lower()

    # 3. Disconnect Shop
    mutation = """
    mutation($input: ShopifyDisconnectShopInput!) {
      shopifyDisconnectShop(input: $input) {
        ok
      }
    }
    """
    response = graphene_client.mutate(
        mutation,
        variable_values={
            "input": {"tenantId": to_global_id("TenantType", tenant.id), "shopDomain": "test.myshopify.com"}
        },
    )
    assert "errors" in response
    assert "permission" in response["errors"][0]["message"].lower()


def test_claim_tampered(graphene_client):
    user = UserFactory()
    tenant = TenantFactory()
    TenantMembershipFactory(user=user, tenant=tenant, role=TenantUserRole.OWNER)
    graphene_client.force_authenticate(user)
    graphene_client.set_tenant_dependent_context(tenant, TenantUserRole.OWNER)

    query = """
    query($claim: String!) {
      shopifyClaim(claim: $claim) {
        shopDomain
      }
    }
    """
    response = graphene_client.query(query, variable_values={"claim": "1:tampered:12345"})
    assert "errors" in response
    assert "Invalid or expired claim" in response["errors"][0]["message"]


def test_claim_already_used(graphene_client):
    user = UserFactory()
    tenant = TenantFactory()
    TenantMembershipFactory(user=user, tenant=tenant, role=TenantUserRole.OWNER)
    graphene_client.force_authenticate(user)
    graphene_client.set_tenant_dependent_context(tenant, TenantUserRole.OWNER)

    # Shop is already linked
    shop = ShopifyShop.objects.create(shop_domain="test.myshopify.com", tenant=tenant)
    signer = TimestampSigner()
    claim = signer.sign(str(shop.id))

    query = """
    query($claim: String!) {
      shopifyClaim(claim: $claim) {
        shopDomain
      }
    }
    """
    response = graphene_client.query(query, variable_values={"claim": claim})
    assert "errors" in response
    assert "Store is already connected" in response["errors"][0]["message"]


def test_claim_expired_with_freezer(graphene_client, freezer):
    user = UserFactory()
    tenant = TenantFactory()
    TenantMembershipFactory(user=user, tenant=tenant, role=TenantUserRole.OWNER)
    graphene_client.force_authenticate(user)
    graphene_client.set_tenant_dependent_context(tenant, TenantUserRole.OWNER)

    shop = ShopifyShop.objects.create(shop_domain="test.myshopify.com", tenant=None)

    freezer.move_to("2026-10-01T10:00:00Z")
    signer = TimestampSigner()
    claim = signer.sign(str(shop.id))

    freezer.move_to("2026-10-01T12:00:00Z")  # 2 hours later, limit is 1 hour

    query = """
    query($claim: String!) {
      shopifyClaim(claim: $claim) {
        shopDomain
      }
    }
    """
    response = graphene_client.query(query, variable_values={"claim": claim})
    assert "errors" in response
    assert "Invalid or expired claim" in response["errors"][0]["message"]


def test_authorize_url_content(graphene_client):
    user = UserFactory()
    tenant = TenantFactory()
    TenantMembershipFactory(user=user, tenant=tenant, role=TenantUserRole.OWNER)
    _ensure_permission(tenant, TenantUserRole.OWNER, "shopify.manage")
    graphene_client.force_authenticate(user)
    graphene_client.set_tenant_dependent_context(tenant, TenantUserRole.OWNER)

    mutation = """
    mutation($input: ShopifyStartInstallInput!) {
      shopifyStartInstall(input: $input) {
        authorizeUrl
      }
    }
    """
    response = graphene_client.mutate(
        mutation,
        variable_values={
            "input": {"tenantId": to_global_id("TenantType", tenant.id), "shopDomain": "test.myshopify.com"}
        },
    )
    assert "errors" not in response

    url = response["data"]["shopifyStartInstall"]["authorizeUrl"]
    assert "test.myshopify.com/admin/oauth/authorize" in url
    assert "client_id=" in url
    assert "scope=" in url
    assert "redirect_uri=" in url
    assert "state=" in url
