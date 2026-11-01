"""
Tests for apps/entitlements/schema.py: the field that tells the web app which features an
organization has unlocked (WhatsApp plan Step 3.4, phase 3 decision 8, user story 28).

- any member of the organization can read it, a Member included, who has no billing.view
- it lists only feature names: on a paid plan or trial ["SHOPIFY", "WHATSAPP"], on the free plan [],
  and every feature while PLAN_ENTITLEMENTS_ENABLED is off
- someone not logged in can't read it

Kind of test: integration (agents.md section 2.5). Why: queries go through the real GraphQL schema,
permissions and test database; nothing is faked.
"""

import pytest
from graphql_relay import to_global_id

from apps.multitenancy.constants import TenantType, TenantUserRole
from apps.multitenancy.tests.factories import TenantFactory, TenantMembershipFactory
from apps.payfast.tests.factories import PayFastSubscriptionFactory
from apps.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

FEATURES = "query($t: ID!) { organizationFeatures(tenantId: $t) }"


@pytest.fixture(autouse=True)
def plans_decide(settings):
    settings.PLAN_ENTITLEMENTS_ENABLED = True
    settings.PAYMENT_BACKEND = settings.PAYMENT_BACKEND_PAYFAST


@pytest.fixture
def acme():
    return TenantFactory(type=TenantType.ORGANIZATION, name="Acme")


def ask(graphene_client, organization):
    return graphene_client.query(FEATURES, variable_values={"t": to_global_id("TenantType", organization.id)})


def as_member(graphene_client, organization, role=TenantUserRole.MEMBER):
    user = UserFactory()
    TenantMembershipFactory(user=user, tenant=organization, role=role)
    graphene_client.force_authenticate(user)
    graphene_client.set_tenant_dependent_context(organization, role)


class TestTheFeatures:
    def test_a_member_reads_the_features_of_a_paid_plan(self, graphene_client, acme):
        PayFastSubscriptionFactory(tenant=acme, monthly=True)
        as_member(graphene_client, acme)

        response = ask(graphene_client, acme)

        assert "errors" not in response
        assert response["data"]["organizationFeatures"] == ["SHOPIFY", "WHATSAPP"]

    def test_on_the_free_plan_the_list_is_empty(self, graphene_client, acme):
        as_member(graphene_client, acme)

        assert ask(graphene_client, acme)["data"]["organizationFeatures"] == []

    def test_with_the_setting_off_every_feature_is_listed(self, graphene_client, acme, settings):
        settings.PLAN_ENTITLEMENTS_ENABLED = False
        as_member(graphene_client, acme)

        assert ask(graphene_client, acme)["data"]["organizationFeatures"] == ["SHOPIFY", "WHATSAPP"]

    def test_someone_not_logged_in_cant_read_it(self, graphene_client, acme):
        # Membership itself is checked by IsTenantMemberAccess and the tenant middleware, as for
        # every organization's query; the test client sets the organization in context directly.
        response = ask(graphene_client, acme)

        assert response.get("errors")
        assert response["data"] is None
