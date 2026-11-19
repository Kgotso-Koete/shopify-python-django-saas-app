"""
Tests for the order updates WhatsApp couldn't deliver, on the WhatsApp page (WhatsApp plan Step 4.7, user story
WA.D3.OM.J2.A3, decided 2026-11-08): a store customer isn't left without their update.

- whatsAppFailedOrderUpdates lists each order stage whose message failed (after the send queue's hour of
  retries, or at once for a cause a person must fix), with the number, the customer, the stage, when it failed
  and Meta's reason in plain words; it needs whatsapp.view
- a stage sent since, a "received" overtaken by "paid", and another organization's updates aren't listed
- sendWhatsAppOrderUpdateAgain needs whatsapp.manage: it asks Shopify for the order by its id and builds the
  update fresh, a normal message if the customer's 24-hour window is open, otherwise the stage's template, and
  the stage keeps the new message; a store to reconnect, or an order Shopify no longer has, is refused with
  the reason, and so is an update that didn't fail

Kind of test: integration (agents.md section 2.5). Why: queries and mutations go through the real GraphQL
schema, permissions and test database; Shopify's Admin API is faked at apps.shopify.orders's
`admin_client_for`, and the send task's `delay` is patched, so nothing reaches Meta.
"""

from datetime import timedelta

import pytest
from django.utils import timezone
from graphql_relay import to_global_id

from apps.multitenancy.constants import TenantType, TenantUserRole
from apps.multitenancy.models import OrganizationRolePermission
from apps.multitenancy.tests.factories import TenantFactory, TenantMembershipFactory
from apps.users.tests.factories import UserFactory
from apps.whatsapp.constants import MessageDirection, MessageKind, MessageStatus
from apps.whatsapp.models import WhatsAppMessage
from apps.whatsapp.tests.factories import MessageFactory

from ..models import StoreCheckout, StoreCustomer
from .chat import customer_of, selling_number, store

pytestmark = [pytest.mark.django_db, pytest.mark.story("WA.D3.OM.J2.A3")]

FAILED_UPDATES = """
query($tenantId: ID!) {
  whatsAppFailedOrderUpdates(tenantId: $tenantId) {
    checkoutId stage accountId number customer failedAt errorCode reason
  }
}
"""

SEND_AGAIN = """
mutation($input: SendWhatsAppOrderUpdateAgainInput!) {
  sendWhatsAppOrderUpdateAgain(input: $input) { checkoutId stage }
}
"""

SHOPIFY_ORDER = {
    "order": {
        "name": "#1001",
        "cancelledAt": None,
        "displayFinancialStatus": "PAID",
        "displayFulfillmentStatus": "UNFULFILLED",
        "totalPriceSet": {"shopMoney": {"amount": "199.00", "currencyCode": "ZAR"}},
        "lineItems": {"nodes": [{"title": "Acme Snowboard", "quantity": 1}]},
    }
}


@pytest.fixture(autouse=True)
def setup(mocker):
    mocker.patch("apps.whatsapp.tasks.send_queued_messages.delay")


@pytest.fixture
def organization():
    return TenantFactory(type=TenantType.ORGANIZATION, name="Acme")


@pytest.fixture
def shop(organization):
    return store(organization)


@pytest.fixture
def customer(shop):
    contact = customer_of(selling_number(shop.tenant, shop))
    contact.profile_name = "Thandi"
    contact.save(update_fields=["profile_name"])
    # They wrote just now, so the 24-hour window is open.
    MessageFactory(contact=contact)
    return contact


@pytest.fixture
def shopify(mocker):
    client = mocker.Mock()
    client.graphql.return_value = SHOPIFY_ORDER
    mocker.patch("apps.shopify.orders.admin_client_for", return_value=client, create=True)
    return client


def update_message(contact, status, error_code=None):
    """An order update queued for the contact earlier, now with `status`."""
    return WhatsAppMessage.objects.create(
        contact=contact,
        direction=MessageDirection.OUTBOUND,
        kind=MessageKind.INTERACTIVE,
        payload={"type": "text", "text": {"body": "Order #1001 is paid.", "preview_url": False}},
        status=status,
        error_code=error_code,
    )


def checkout_of(contact, shop, code="wachk_FFFFFFFFFFFFFFFFFFFFFF", **stages):
    store_customer, _ = StoreCustomer.objects.get_or_create(contact=contact, defaults={"tenant": shop.tenant})
    return StoreCheckout.objects.create(
        code=code,
        store_customer=store_customer,
        shop=shop,
        cart_id=f"gid://shopify/Cart/{code}",
        order_id=5001 if code.endswith("F") else 5002,
        **stages,
    )


def act_as(graphene_client, organization, role):
    user = UserFactory()
    TenantMembershipFactory(user=user, tenant=organization, role=role)
    graphene_client.force_authenticate(user)
    graphene_client.set_tenant_dependent_context(organization, role)
    return user


def tenant_id(organization):
    return to_global_id("TenantType", organization.id)


def listed(graphene_client, organization):
    response = graphene_client.query(FAILED_UPDATES, variable_values={"tenantId": tenant_id(organization)})
    assert "errors" not in response, response
    return response["data"]["whatsAppFailedOrderUpdates"]


def send_again(graphene_client, organization, checkout, stage="PAID"):
    return graphene_client.query(
        SEND_AGAIN,
        variable_values={
            "input": {"tenantId": tenant_id(organization), "checkoutId": str(checkout.pk), "stage": stage}
        },
    )


def problem(response):
    error = response["errors"][0]
    assert error["message"] == "GraphQlValidationError"
    return error["extensions"]


class TestTheList:
    def test_a_failed_update_is_listed_with_its_number_customer_stage_and_metas_reason(
        self, graphene_client, organization, shop, customer
    ):
        act_as(graphene_client, organization, TenantUserRole.MEMBER)
        checkout = checkout_of(customer, shop, paid_message=update_message(customer, MessageStatus.FAILED, 190))

        [update] = listed(graphene_client, organization)

        assert update["checkoutId"] == str(checkout.pk)
        assert update["stage"] == "PAID"
        assert update["accountId"] == str(customer.account.id)
        assert update["number"] == customer.account.display_phone_number
        assert update["customer"] == "Thandi"
        assert update["failedAt"]
        assert update["errorCode"] == 190
        assert "access token" in update["reason"]

    @pytest.mark.parametrize(
        ("code", "words"),
        [
            (132001, "template"),
            (131047, "24 hours"),
            (131026, "couldn't deliver"),
            (None, "an hour"),
        ],
    )
    def test_metas_reason_is_in_plain_words(self, graphene_client, organization, shop, customer, code, words):
        act_as(graphene_client, organization, TenantUserRole.MEMBER)
        checkout_of(customer, shop, paid_message=update_message(customer, MessageStatus.FAILED, code))

        [update] = listed(graphene_client, organization)

        assert words in update["reason"]

    def test_a_cancelled_update_is_listed_too(self, graphene_client, organization, shop, customer):
        # Cancelled: it was queued behind a message that failed (decision D21).
        act_as(graphene_client, organization, TenantUserRole.MEMBER)
        checkout_of(customer, shop, received_message=update_message(customer, MessageStatus.CANCELLED))

        [update] = listed(graphene_client, organization)

        assert update["stage"] == "RECEIVED"

    def test_sent_ones_and_a_received_overtaken_by_paid_are_not_listed(
        self, graphene_client, organization, shop, customer
    ):
        act_as(graphene_client, organization, TenantUserRole.MEMBER)
        checkout_of(customer, shop, paid_message=update_message(customer, MessageStatus.DELIVERED))
        checkout_of(
            customer,
            shop,
            code="wachk_GGGGGGGGGGGGGGGGGGGGGG",
            received_message=update_message(customer, MessageStatus.FAILED, 190),
            paid_message=update_message(customer, MessageStatus.ACCEPTED),
        )

        assert listed(graphene_client, organization) == []

    def test_another_organizations_failures_are_not_listed(self, graphene_client, organization, shop, customer):
        other_shop = store(TenantFactory(type=TenantType.ORGANIZATION, name="Other"), domain="other.myshopify.com")
        other_customer = customer_of(selling_number(other_shop.tenant, other_shop))
        checkout_of(other_customer, other_shop, paid_message=update_message(other_customer, MessageStatus.FAILED, 190))
        act_as(graphene_client, organization, TenantUserRole.MEMBER)

        assert listed(graphene_client, organization) == []

    def test_it_needs_whatsapp_view(self, graphene_client, organization):
        act_as(graphene_client, organization, TenantUserRole.MEMBER)
        OrganizationRolePermission.objects.filter(
            role__tenant=organization, role__system_role_type=TenantUserRole.MEMBER, permission__code="whatsapp.view"
        ).delete()

        response = graphene_client.query(FAILED_UPDATES, variable_values={"tenantId": tenant_id(organization)})

        assert "permission" in response["errors"][0]["message"].lower()


class TestSendAgain:
    def test_it_asks_shopify_for_the_order_and_sends_the_update_fresh(
        self, graphene_client, organization, shop, customer, shopify
    ):
        act_as(graphene_client, organization, TenantUserRole.ADMIN)
        failed = update_message(customer, MessageStatus.FAILED, 190)
        checkout = checkout_of(customer, shop, paid_message=failed)

        response = send_again(graphene_client, organization, checkout)

        assert "errors" not in response, response
        assert response["data"]["sendWhatsAppOrderUpdateAgain"] == {"checkoutId": str(checkout.pk), "stage": "PAID"}
        [call] = shopify.graphql.call_args_list
        assert call.kwargs["variables"] == {"id": "gid://shopify/Order/5001"}
        checkout.refresh_from_db()
        assert checkout.paid_message != failed
        assert checkout.paid_message.status == MessageStatus.QUEUED
        # Built from the order as Shopify has it now (Step 4.7, decision 30).
        assert checkout.paid_message.payload["interactive"]["body"]["text"] == (
            "Order #1001 is paid.\n1 × Acme Snowboard\nTotal: ZAR 199.00\nPayment: Paid · Delivery: Not shipped yet"
        )
        assert listed(graphene_client, organization) == []

    def test_after_the_24_hour_window_it_sends_the_stages_template(
        self, graphene_client, organization, shop, customer, shopify
    ):
        act_as(graphene_client, organization, TenantUserRole.ADMIN)
        WhatsAppMessage.objects.filter(contact=customer).update(sent_at=timezone.now() - timedelta(hours=25))
        checkout = checkout_of(customer, shop, received_message=update_message(customer, MessageStatus.FAILED, 190))

        response = send_again(graphene_client, organization, checkout, stage="RECEIVED")

        assert "errors" not in response, response
        checkout.refresh_from_db()
        # One template for any stage since Step 4.7 (decision 30): the store and the order's number.
        template = checkout.received_message.payload["template"]
        assert template["name"] == "shop_order_update"
        assert [parameter["text"] for parameter in template["components"][0]["parameters"]][1:] == ["#1001"]

    def test_a_store_to_reconnect_is_refused_with_the_reason(
        self, graphene_client, organization, shop, customer, shopify
    ):
        act_as(graphene_client, organization, TenantUserRole.ADMIN)
        shop.needs_reinstall = True
        shop.save(update_fields=["needs_reinstall"])
        checkout = checkout_of(customer, shop, paid_message=update_message(customer, MessageStatus.FAILED, 190))

        response = send_again(graphene_client, organization, checkout)

        assert "reconnect" in str(problem(response)).lower()
        checkout.refresh_from_db()
        assert checkout.paid_message.status == MessageStatus.FAILED

    def test_an_order_shopify_no_longer_has_is_refused(self, graphene_client, organization, shop, customer, shopify):
        act_as(graphene_client, organization, TenantUserRole.ADMIN)
        shopify.graphql.return_value = {"order": None}
        checkout = checkout_of(customer, shop, paid_message=update_message(customer, MessageStatus.FAILED, 190))

        response = send_again(graphene_client, organization, checkout)

        assert "no longer has" in str(problem(response)).lower()

    def test_an_update_that_didnt_fail_is_refused(self, graphene_client, organization, shop, customer, shopify):
        act_as(graphene_client, organization, TenantUserRole.ADMIN)
        checkout = checkout_of(customer, shop, paid_message=update_message(customer, MessageStatus.DELIVERED))

        response = send_again(graphene_client, organization, checkout)

        assert "didn't fail" in str(problem(response)).lower()
        shopify.graphql.assert_not_called()

    def test_another_organizations_update_is_not_found(self, graphene_client, organization, shopify):
        other_shop = store(TenantFactory(type=TenantType.ORGANIZATION, name="Other"), domain="other.myshopify.com")
        other_customer = customer_of(selling_number(other_shop.tenant, other_shop))
        checkout = checkout_of(
            other_customer, other_shop, paid_message=update_message(other_customer, MessageStatus.FAILED, 190)
        )
        act_as(graphene_client, organization, TenantUserRole.ADMIN)

        response = send_again(graphene_client, organization, checkout)

        assert "not found" in str(problem(response)).lower()
        shopify.graphql.assert_not_called()

    def test_it_needs_whatsapp_manage(self, graphene_client, organization, shop, customer, shopify):
        act_as(graphene_client, organization, TenantUserRole.MEMBER)
        checkout = checkout_of(customer, shop, paid_message=update_message(customer, MessageStatus.FAILED, 190))

        response = send_again(graphene_client, organization, checkout)

        assert "permission" in response["errors"][0]["message"].lower()
        shopify.graphql.assert_not_called()
