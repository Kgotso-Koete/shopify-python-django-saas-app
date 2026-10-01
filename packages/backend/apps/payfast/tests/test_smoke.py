"""
Smoke test: one tenant's whole PayFast journey through the real stack, the way the web app and
PayFast drive it. GraphQL checkout -> PayFast's ITN over HTTP -> GraphQL shows the trial -> plan
change -> cancellation -> a donation in the transaction history.

Only PayFast's servers are replaced: the /eng/query/validate confirmation, DNS, and the REST API.
Everything else (URL routing, signatures, permissions, database) is real.
"""

from unittest import mock

import pytest
from graphql_relay import to_global_id

from apps.multitenancy.constants import TenantUserRole
from .utils import itn_pairs, signed_itn_body

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("payfast_backend")]

PAYFAST_IP = "197.97.145.150"
TOKEN = "dc0521d3-55fe-269b-fa00-b647310d760f"
NEW_TOKEN = "7e57a2a1-0000-4000-8000-000000000002"


@pytest.fixture(autouse=True)
def payfast_servers():
    """PayFast confirms every ITN; DNS lookups are skipped (the source IP is in a published range)."""
    with (
        mock.patch("apps.payfast.itn.confirm_with_payfast", return_value=True),
        mock.patch("apps.payfast.itn.resolve_payfast_hosts", return_value=set()),
    ):
        yield


def graphql(client, document, **variables):
    executed = client.mutate(document, variable_values=variables)
    assert "errors" not in executed, executed
    return executed["data"]


def post_itn(http_client, **fields):
    response = http_client.post(
        "/api/payfast/notify/",
        data=signed_itn_body(itn_pairs(**fields)),
        content_type="application/x-www-form-urlencoded",
        REMOTE_ADDR=PAYFAST_IP,
    )
    assert response.status_code == 200, response.content


def test_a_tenants_journey_from_trial_to_cancellation(
    graphene_client, client, tenant, user_factory, tenant_membership_factory, payfast_api
):
    owner = user_factory()
    tenant_membership_factory(tenant=tenant, user=owner, role=TenantUserRole.OWNER)
    graphene_client.force_authenticate(owner)
    graphene_client.set_tenant_dependent_context(tenant, TenantUserRole.OWNER)
    tenant_id = to_global_id("TenantType", tenant.pk)
    subscription_query = """
        query($tenantId: ID!) {
          payfastActiveSubscription(tenantId: $tenantId) { plan effectivePlan pendingPlan status cancelAtPeriodEnd }
        }
    """

    # 1. The web app learns the backend, and the tenant starts on the free plan.
    assert graphql(graphene_client, "query { paymentConfig { backend } }")["paymentConfig"]["backend"] == "payfast"
    assert graphql(graphene_client, subscription_query, tenantId=tenant_id)["payfastActiveSubscription"]["plan"] == (
        "free_plan"
    )

    # 2. The owner chooses the monthly plan; the first purchase is an R0 trial.
    checkout = graphql(
        graphene_client,
        """
        mutation($input: PayFastCreateCheckoutMutationInput!) {
          payfastCreateCheckout(input: $input) { checkout { fields mPaymentId } }
        }
        """,
        input={"tenantId": tenant_id, "plan": "monthly_plan", "returnPath": "/en/r", "cancelPath": "/en/c"},
    )["payfastCreateCheckout"]["checkout"]
    assert checkout["fields"]["amount"] == "0.00"

    # 3. PayFast posts the ITN for the completed trial sign-up.
    post_itn(
        client,
        m_payment_id=checkout["mPaymentId"],
        pf_payment_id="100",
        amount_gross="0.00",
        amount_fee="0.00",
        amount_net="0.00",
        token=TOKEN,
    )
    status_query = """
        query($tenantId: ID!, $m: ID!) { payfastCheckoutStatus(tenantId: $tenantId, mPaymentId: $m) }
    """
    assert (
        graphql(graphene_client, status_query, tenantId=tenant_id, m=checkout["mPaymentId"])["payfastCheckoutStatus"]
        == "complete"
    )
    subscription = graphql(graphene_client, subscription_query, tenantId=tenant_id)["payfastActiveSubscription"]
    assert subscription["effectivePlan"] == "monthly_plan"
    assert subscription["status"] == "trialing"

    # 4. The owner switches to yearly: a new R0 PayFast subscription that bills from the end of the
    #    trial, and once PayFast confirms it, the old subscription is cancelled.
    switch = graphql(
        graphene_client,
        """
        mutation($input: PayFastCreateCheckoutMutationInput!) {
          payfastCreateCheckout(input: $input) { checkout { fields mPaymentId } }
        }
        """,
        input={"tenantId": tenant_id, "plan": "yearly_plan", "returnPath": "/en/r", "cancelPath": "/en/c"},
    )["payfastCreateCheckout"]["checkout"]
    assert switch["fields"]["amount"] == "0.00"
    post_itn(
        client,
        m_payment_id=switch["mPaymentId"],
        pf_payment_id="110",
        amount_gross="0.00",
        amount_fee="0.00",
        amount_net="0.00",
        token=NEW_TOKEN,
    )
    payfast_api.cancel.assert_called_once_with(TOKEN)
    assert (
        graphql(graphene_client, subscription_query, tenantId=tenant_id)["payfastActiveSubscription"]["pendingPlan"]
        == "yearly_plan"
    )
    payfast_api.cancel.reset_mock()

    # 5. The owner cancels; the plan lasts until the trial ends.
    graphql(
        graphene_client,
        """
        mutation($input: PayFastCancelSubscriptionMutationInput!) {
          payfastCancelSubscription(input: $input) { activeSubscription { cancelAtPeriodEnd } }
        }
        """,
        input={"tenantId": tenant_id},
    )
    payfast_api.cancel.assert_called_once_with(NEW_TOKEN)
    # PayFast confirms the cancellation with its own ITN, which must be harmless.
    post_itn(client, pf_payment_id="101", payment_status="CANCELLED", amount_gross="0.00", token=NEW_TOKEN)
    subscription = graphql(graphene_client, subscription_query, tenantId=tenant_id)["payfastActiveSubscription"]
    assert subscription["cancelAtPeriodEnd"] is True
    assert subscription["effectivePlan"] == "monthly_plan"
    assert subscription["pendingPlan"] is None

    # 6. A donation, which appears in the transaction history (the R0 trial start does not).
    donation = graphql(
        graphene_client,
        """
        mutation($input: PayFastCreateDonationCheckoutMutationInput!) {
          payfastCreateDonationCheckout(input: $input) { checkout { mPaymentId } }
        }
        """,
        input={"tenantId": tenant_id, "amount": "100", "returnPath": "/en/r", "cancelPath": "/en/c"},
    )["payfastCreateDonationCheckout"]["checkout"]
    post_itn(
        client, m_payment_id=donation["mPaymentId"], pf_payment_id="102", amount_gross="100.00", item_name="Donation"
    )
    history = graphql(
        graphene_client,
        "query($tenantId: ID!) { payfastPayments(tenantId: $tenantId) { edges { node { pfPaymentId kind } } } }",
        tenantId=tenant_id,
    )
    assert [edge["node"] for edge in history["payfastPayments"]["edges"]] == [
        {"pfPaymentId": "102", "kind": "donation"}
    ]
