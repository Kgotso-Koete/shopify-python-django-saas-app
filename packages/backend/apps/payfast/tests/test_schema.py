"""
Integration tests for the PayFast GraphQL API (apps/payfast/schema.py), through the real schema
(config.schema) with the same `graphene_client` the Stripe tests use.

Permissions mirror the Stripe resolvers in apps/finances/schema.py: reading billing data needs
`billing.view`, changing it needs `billing.manage` (both Owner-only by default), and public data
(plans, donation amounts, which backend is active) needs nothing.
"""

from decimal import Decimal

import pytest
from graphql_relay import to_global_id

from apps.multitenancy.constants import TenantUserRole
from ..models import PayFastCheckout

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("payfast_backend")]


@pytest.fixture
def owner_client(graphene_client, tenant, user_factory, tenant_membership_factory):
    """A client acting as an Owner of `tenant` (Owners hold billing.view and billing.manage)."""
    owner = user_factory()
    tenant_membership_factory(tenant=tenant, user=owner, role=TenantUserRole.OWNER)
    graphene_client.force_authenticate(owner)
    graphene_client.set_tenant_dependent_context(tenant, TenantUserRole.OWNER)
    graphene_client.user = owner
    return graphene_client


@pytest.fixture
def member_client(graphene_client, tenant, user_factory, tenant_membership_factory):
    """A plain Member of `tenant`, who has neither billing permission."""
    member = user_factory()
    tenant_membership_factory(tenant=tenant, user=member, role=TenantUserRole.MEMBER)
    graphene_client.force_authenticate(member)
    graphene_client.set_tenant_dependent_context(tenant, TenantUserRole.MEMBER)
    return graphene_client


def tenant_id(tenant):
    return to_global_id("TenantType", tenant.pk)


def error_message(executed):
    """The user-facing message of a GraphQlValidationError, as the web app's useApiForm reads it."""
    return executed["errors"][0]["extensions"]["non_field_errors"][0]["message"]


class TestPaymentConfigQuery:
    QUERY = "query { paymentConfig { backend currency } }"

    def test_tells_anyone_which_backend_is_active(self, graphene_client):
        executed = graphene_client.query(self.QUERY)

        assert executed["data"]["paymentConfig"] == {"backend": "payfast", "currency": "ZAR"}

    def test_stripe_backend(self, graphene_client, settings):
        settings.PAYMENT_BACKEND = "stripe"

        executed = graphene_client.query(self.QUERY)

        assert executed["data"]["paymentConfig"] == {"backend": "stripe", "currency": "USD"}


class TestPublicPayFastQueries:
    def test_subscription_plans_use_prices_from_settings(self, graphene_client, settings):
        settings.PAYFAST_MONTHLY_PRICE = "249.00"

        executed = graphene_client.query("query { payfastSubscriptionPlans { name amount currency interval } }")

        assert executed["data"]["payfastSubscriptionPlans"] == [
            {"name": "free_plan", "amount": "0.00", "currency": "ZAR", "interval": None},
            {"name": "monthly_plan", "amount": "249.00", "currency": "ZAR", "interval": "month"},
            {"name": "yearly_plan", "amount": "1990.00", "currency": "ZAR", "interval": "year"},
        ]

    def test_donation_amounts(self, graphene_client):
        executed = graphene_client.query("query { payfastDonationAmounts }")

        assert executed["data"]["payfastDonationAmounts"] == ["50.00", "100.00", "150.00"]


class TestActiveSubscriptionQuery:
    QUERY = """
        query($tenantId: ID!) {
          payfastActiveSubscription(tenantId: $tenantId) {
            plan effectivePlan pendingPlan status amount currentPeriodEnd trialEnd
            cancelAtPeriodEnd canActivateTrial hasCard cardUpdateUrl
          }
        }
    """

    def test_owner_sees_the_subscription(self, owner_client, tenant, pay_fast_subscription_factory):
        subscription = pay_fast_subscription_factory(tenant=tenant, monthly=True)

        executed = owner_client.query(self.QUERY, variable_values={"tenantId": tenant_id(tenant)})

        data = executed["data"]["payfastActiveSubscription"]
        assert data["plan"] == "monthly_plan"
        assert data["effectivePlan"] == "monthly_plan"
        assert data["status"] == "active"
        assert data["amount"] == "199.00"
        assert data["hasCard"] is True
        assert data["canActivateTrial"] is False
        assert data["cardUpdateUrl"].startswith(
            f"https://www.payfast.co.za/eng/recurring/update/{subscription.token}?return="
        )

    def test_free_tenant(self, owner_client, tenant):
        executed = owner_client.query(self.QUERY, variable_values={"tenantId": tenant_id(tenant)})

        data = executed["data"]["payfastActiveSubscription"]
        assert data["effectivePlan"] == "free_plan"
        assert data["canActivateTrial"] is True
        assert data["cardUpdateUrl"] is None

    def test_member_without_billing_view_is_denied(self, member_client, tenant):
        executed = member_client.query(self.QUERY, variable_values={"tenantId": tenant_id(tenant)})

        assert executed["errors"][0]["message"] == "permission_denied"

    def test_anonymous_is_denied(self, graphene_client, tenant):
        executed = graphene_client.query(self.QUERY, variable_values={"tenantId": tenant_id(tenant)})

        assert executed["errors"][0]["message"] == "permission_denied"


class TestPaymentsQuery:
    QUERY = """
        query($tenantId: ID!) {
          payfastPayments(tenantId: $tenantId) {
            edges { node { pfPaymentId kind plan amountGross itemName } }
          }
        }
    """

    def test_lists_completed_charges_of_this_tenant_only(
        self, owner_client, tenant, tenant_factory, pay_fast_payment_factory
    ):
        pay_fast_payment_factory(tenant=tenant, pf_payment_id="1", amount_gross=Decimal("50.00"))
        pay_fast_payment_factory(
            tenant=tenant,
            pf_payment_id="2",
            kind="subscription",
            plan="monthly_plan",
            amount_gross=Decimal("199.00"),
            item_name="Monthly plan",
        )
        # Not charges: an R0 trial start and a cancellation notice.
        pay_fast_payment_factory(tenant=tenant, pf_payment_id="3", amount_gross=Decimal("0.00"))
        pay_fast_payment_factory(tenant=tenant, pf_payment_id="4", payment_status="CANCELLED")
        # Another tenant's payment.
        pay_fast_payment_factory(tenant=tenant_factory(), pf_payment_id="5")

        executed = owner_client.query(self.QUERY, variable_values={"tenantId": tenant_id(tenant)})

        nodes = [edge["node"] for edge in executed["data"]["payfastPayments"]["edges"]]
        assert sorted(node["pfPaymentId"] for node in nodes) == ["1", "2"]
        assert {node["pfPaymentId"]: node["kind"] for node in nodes} == {"1": "donation", "2": "subscription"}

    def test_member_without_billing_view_is_denied(self, member_client, tenant):
        executed = member_client.query(self.QUERY, variable_values={"tenantId": tenant_id(tenant)})

        assert executed["errors"][0]["message"] == "permission_denied"


class TestCheckoutStatusQuery:
    QUERY = """
        query($tenantId: ID!, $mPaymentId: ID!) {
          payfastCheckoutStatus(tenantId: $tenantId, mPaymentId: $mPaymentId)
        }
    """

    def test_returns_the_status_of_this_tenants_checkout(self, owner_client, tenant, pay_fast_checkout_factory):
        checkout = pay_fast_checkout_factory(tenant=tenant, status=PayFastCheckout.Status.COMPLETE)

        executed = owner_client.query(
            self.QUERY, variable_values={"tenantId": tenant_id(tenant), "mPaymentId": str(checkout.m_payment_id)}
        )

        assert executed["data"]["payfastCheckoutStatus"] == "complete"

    def test_another_tenants_checkout_is_invisible(self, owner_client, tenant, pay_fast_checkout_factory):
        checkout = pay_fast_checkout_factory()  # belongs to a different tenant

        executed = owner_client.query(
            self.QUERY, variable_values={"tenantId": tenant_id(tenant), "mPaymentId": str(checkout.m_payment_id)}
        )

        assert executed["data"]["payfastCheckoutStatus"] is None


class TestCreateCheckoutMutation:
    MUTATION = """
        mutation($input: PayFastCreateCheckoutMutationInput!) {
          payfastCreateCheckout(input: $input) {
            checkout { actionUrl fields mPaymentId }
          }
        }
    """

    def mutate(self, client, tenant, **fields):
        return client.mutate(
            self.MUTATION,
            variable_values={
                "input": {
                    "tenantId": tenant_id(tenant),
                    "plan": "monthly_plan",
                    "returnPath": "/en/t/subscriptions/payfast-return",
                    "cancelPath": "/en/t/subscriptions/current-subscription/edit",
                    **fields,
                }
            },
        )

    def test_owner_gets_a_signed_form_for_payfast(self, owner_client, tenant):
        executed = self.mutate(owner_client, tenant)

        checkout = executed["data"]["payfastCreateCheckout"]["checkout"]
        assert checkout["actionUrl"] == "https://sandbox.payfast.co.za/eng/process"
        assert checkout["fields"]["signature"]
        # Return and cancel URLs are built on the server from WEB_APP_URL and the relative paths given.
        assert checkout["fields"]["return_url"] == (
            f"https://app.example.com/en/t/subscriptions/payfast-return?m={checkout['mPaymentId']}"
        )
        assert (
            checkout["fields"]["cancel_url"] == "https://app.example.com/en/t/subscriptions/current-subscription/edit"
        )
        assert PayFastCheckout.objects.get(m_payment_id=checkout["mPaymentId"]).created_by == owner_client.user

    @pytest.mark.parametrize("bad_path", ["https://evil.example/steal", "//evil.example/steal", "relative/path"])
    def test_only_relative_paths_on_our_web_app_are_accepted(self, owner_client, tenant, bad_path):
        # Otherwise PayFast would redirect our customers to any site a request asked for.
        executed = self.mutate(owner_client, tenant, returnPath=bad_path)

        assert executed["errors"][0]["message"] == "GraphQlValidationError"
        assert not PayFastCheckout.objects.exists()

    def test_service_errors_are_shown_to_the_user(self, owner_client, tenant):
        executed = self.mutate(owner_client, tenant, plan="free_plan")

        assert "not a plan you can subscribe to" in error_message(executed)

    def test_member_without_billing_manage_is_denied(self, member_client, tenant):
        executed = self.mutate(member_client, tenant)

        assert executed["errors"][0]["message"] == "permission_denied"

    def test_not_available_when_stripe_is_the_backend(self, owner_client, tenant, settings):
        settings.PAYMENT_BACKEND = "stripe"

        executed = self.mutate(owner_client, tenant)

        assert "PayFast is not the active payment backend" in error_message(executed)


class TestCreateDonationCheckoutMutation:
    MUTATION = """
        mutation($input: PayFastCreateDonationCheckoutMutationInput!) {
          payfastCreateDonationCheckout(input: $input) {
            checkout { actionUrl fields mPaymentId }
          }
        }
    """

    def mutate(self, client, tenant, amount):
        return client.mutate(
            self.MUTATION,
            variable_values={
                "input": {
                    "tenantId": tenant_id(tenant),
                    "amount": amount,
                    "returnPath": "/en/t/finances/payfast-return",
                    "cancelPath": "/en/t/finances/payment-confirm",
                }
            },
        )

    def test_owner_gets_a_donation_form(self, owner_client, tenant):
        executed = self.mutate(owner_client, tenant, "100.00")

        fields = executed["data"]["payfastCreateDonationCheckout"]["checkout"]["fields"]
        assert fields["amount"] == "100.00"
        assert fields["item_name"] == "Donation"

    def test_amount_not_offered_is_rejected(self, owner_client, tenant):
        executed = self.mutate(owner_client, tenant, "7.00")

        assert "donation amounts" in error_message(executed)


class TestPlanChangeCheckout:
    MUTATION = """
        mutation($input: PayFastCreateCheckoutMutationInput!) {
          payfastCreateCheckout(input: $input) {
            checkout { fields mPaymentId }
          }
        }
    """

    def test_paying_owner_gets_a_r0_checkout_for_the_new_plan(
        self, owner_client, tenant, pay_fast_subscription_factory, payfast_api
    ):
        # Plan changes are a new PayFast subscription billed from the end of the paid period; the
        # PayFast update API isn't used (it fails in the sandbox).
        import datetime

        from django.utils import timezone

        period_end = timezone.now() + datetime.timedelta(days=10)
        pay_fast_subscription_factory(tenant=tenant, monthly=True, current_period_end=period_end)

        executed = owner_client.mutate(
            self.MUTATION,
            variable_values={
                "input": {
                    "tenantId": tenant_id(tenant),
                    "plan": "yearly_plan",
                    "returnPath": "/en/r",
                    "cancelPath": "/en/c",
                }
            },
        )

        fields = executed["data"]["payfastCreateCheckout"]["checkout"]["fields"]
        assert fields["amount"] == "0.00"
        assert fields["recurring_amount"] == "1990.00"
        assert fields["billing_date"] == period_end.date().isoformat()
        payfast_api.update.assert_not_called()


class TestCancelSubscriptionMutation:
    MUTATION = """
        mutation($input: PayFastCancelSubscriptionMutationInput!) {
          payfastCancelSubscription(input: $input) {
            activeSubscription { plan effectivePlan cancelAtPeriodEnd }
          }
        }
    """

    def test_owner_cancels_at_period_end(self, owner_client, tenant, pay_fast_subscription_factory, payfast_api):
        import datetime

        from django.utils import timezone

        subscription = pay_fast_subscription_factory(
            tenant=tenant, monthly=True, current_period_end=timezone.now() + datetime.timedelta(days=10)
        )

        executed = owner_client.mutate(self.MUTATION, variable_values={"input": {"tenantId": tenant_id(tenant)}})

        assert executed["data"]["payfastCancelSubscription"]["activeSubscription"] == {
            "plan": "monthly_plan",
            "effectivePlan": "monthly_plan",
            "cancelAtPeriodEnd": True,
        }
        payfast_api.cancel.assert_called_once_with(subscription.token)

    def test_member_without_billing_manage_is_denied(self, member_client, tenant, payfast_api):
        executed = member_client.mutate(self.MUTATION, variable_values={"input": {"tenantId": tenant_id(tenant)}})

        assert executed["errors"][0]["message"] == "permission_denied"
        payfast_api.cancel.assert_not_called()
