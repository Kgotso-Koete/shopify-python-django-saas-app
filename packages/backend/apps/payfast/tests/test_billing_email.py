"""
The organization's billing email, saved through the real GraphQL view (WhatsApp plan Step 4.7, user story
WA.D6.OM.J1.A1).

The PayFast Subscriptions page's Billing email card saves it with upstream's `updateTenant` mutation. A real request
goes through the tenant middleware (apps/multitenancy/middleware.py), which finds the organization only from an
explicit `tenantId`, never from a plain `id`, so a request can't act on another organization by naming it. Upstream's
own `updateTenant` tests set the organization on the context directly and skip that lookup, which hid that the card's
save found no organization at all (human check J3.3, 2026-11-19: "'NoneType' object has no attribute '_meta'").

Kind of test: integration (agents.md section 2.5). Why: each test POSTs to /api/graphql/ through the real view and
its middleware, against the test database; nothing is faked, and the user is signed in with `force_authenticate`.
"""

import json

import pytest
from graphql_relay import to_global_id

from apps.multitenancy.constants import TenantType, TenantUserRole

pytestmark = [pytest.mark.django_db, pytest.mark.story("WA.D6.OM.J1.A1")]

# The card's own mutation (packages/webapp-libs/webapp-finances/src/payfast/payfast.graphql.ts).
MUTATION = """
    mutation payfastUpdateBillingEmailMutation($input: UpdateTenantMutationInput!) {
      updateTenant(input: $input) {
        tenant {
          id
          name
          billingEmail
        }
      }
    }
"""

BILLING_EMAIL = "accounts@acme.example"


@pytest.fixture
def organization(tenant_factory):
    """An organization whose billing email isn't set yet, so PayFast would bill its creator."""
    return tenant_factory(name="Acme", type=TenantType.ORGANIZATION, billing_email="")


def save_billing_email(api_client, user, organization):
    """Send the card's request, as `user`, naming the organization with `tenantId` as the middleware requires."""
    api_client.force_authenticate(user)
    tenant_id = to_global_id("TenantType", organization.id)
    variables = {
        "input": {"id": tenant_id, "tenantId": tenant_id, "name": organization.name, "billingEmail": BILLING_EMAIL}
    }
    response = api_client.post(
        "/api/graphql/", data=json.dumps({"query": MUTATION, "variables": variables}), content_type="application/json"
    )
    return response.json()


def test_an_owner_saves_the_organizations_billing_email(
    api_client, user_factory, organization, tenant_membership_factory
):
    owner = user_factory()
    tenant_membership_factory(tenant=organization, user=owner, role=TenantUserRole.OWNER)

    result = save_billing_email(api_client, owner, organization)

    # The whole answer first, so a failure shows GraphQL's own error.
    assert "errors" not in result, result
    assert result["data"]["updateTenant"]["tenant"]["billingEmail"] == BILLING_EMAIL
    organization.refresh_from_db()
    assert organization.billing_email == BILLING_EMAIL
    # PayFast bills this address from now on (Tenant.email), not the organization's creator.
    assert organization.email == BILLING_EMAIL


def test_a_member_cannot_change_it(api_client, user_factory, organization, tenant_membership_factory):
    # A Member doesn't hold org.settings.edit, the permission updateTenant requires: the card shows them the email
    # read-only, and the backend refuses the change itself.
    member = user_factory()
    tenant_membership_factory(tenant=organization, user=member, role=TenantUserRole.MEMBER)

    result = save_billing_email(api_client, member, organization)

    assert result.get("errors"), result
    # Refused for the permission, not for some other error ("permission_denied", common/graphql/acl).
    assert "permission" in result["errors"][0]["message"].lower(), result
    organization.refresh_from_db()
    assert organization.billing_email == ""
