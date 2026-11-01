"""
Tests for where an organization's plan is checked (WhatsApp plan Step 3.3, phase 3 decisions 3, 4 and
5, user stories 26 and 27).

- browsing a store's products refuses an organization whose plan doesn't include Shopify, with
  "plan_required"
- setting up needs no plan (Step 2.8, finding 16): connecting and disconnecting numbers and stores,
  changing whom a number serves, choosing its store and its customers' mode, linking a phone, test
  messages and troubleshooting, so a business can set everything up before its trial starts
- reading what's kept stays allowed (decision 5): the numbers, their stores, the stores, the links
- with PLAN_ENTITLEMENTS_ENABLED off, nothing is refused for the plan
- the WhatsApp router answers nobody on a lapsed organization's number, store customers and linked
  members alike, while the message is still stored (decision 4)

Kind of test: integration (agents.md section 2.5). Why: requests go through the real GraphQL schema,
permissions and test database, and messages through the real router; only the store's name from
Shopify and the send task's Celery delay are faked.
"""

import pytest
from graphql_relay import to_global_id

from apps.multitenancy.constants import TenantType, TenantUserRole
from apps.multitenancy.tests.factories import TenantFactory, TenantMembershipFactory
from apps.payfast.tests.factories import PayFastSubscriptionFactory
from apps.users.tests.factories import UserFactory
from apps.whatsapp.constants import MessageDirection
from apps.whatsapp.models import WhatsAppMessage
from apps.whatsapp.tests.factories import ContactFactory, InternalAccountFactory, link_member
from apps.whatsapp_shop.tests.chat import customer_of, selling_number, send, store

pytestmark = pytest.mark.django_db

ID = to_global_id("Anything", "1")

# Each field that uses a feature, with a request that passes GraphQL's own validation. The plan is
# checked before anything else, so made-up ids are never looked up.
FIELDS = {
    "WHATSAPP": {
        "whatsAppNumberStatus": "query($t: ID!) { whatsAppNumberStatus(tenantId: $t, accountId: \"x\") { status } }",
        "connectWhatsAppAccount": (
            "mutation($t: ID!) { connectWhatsAppAccount(input: {tenantId: $t, purpose: EXTERNAL_COMMUNICATIONS, "
            'phoneNumberId: "1", wabaId: "2", accessToken: "3"}) { account { id } } }'
        ),
        "sendWhatsAppTestMessage": (
            'mutation($t: ID!) { sendWhatsAppTestMessage(input: {tenantId: $t, accountId: "x", to: "27000000000"}) '
            "{ messageId } }"
        ),
        "changeWhatsAppNumberPurpose": (
            "mutation($t: ID!) { changeWhatsAppNumberPurpose(input: {tenantId: $t, accountId: \"x\", "
            "purpose: INTERNAL_COMMUNICATIONS}) { account { id } } }"
        ),
        "requestWhatsAppVerificationCode": (
            'mutation($t: ID!) { requestWhatsAppVerificationCode(input: {tenantId: $t, accountId: "x", method: "SMS"}) '
            "{ ok } }"
        ),
        "verifyWhatsAppNumber": (
            'mutation($t: ID!) { verifyWhatsAppNumber(input: {tenantId: $t, accountId: "x", code: "123456"}) '
            "{ ok } }"
        ),
        "registerWhatsAppNumber": (
            'mutation($t: ID!) { registerWhatsAppNumber(input: {tenantId: $t, accountId: "x", pin: "123456"}) '
            "{ ok } }"
        ),
        "subscribeWhatsAppApp": (
            'mutation($t: ID!) { subscribeWhatsAppApp(input: {tenantId: $t, accountId: "x"}) { ok } }'
        ),
        "chooseWhatsAppStore": (
            'mutation($t: ID!) { chooseWhatsAppStore(input: {tenantId: $t, accountId: "x", shopDomain: "a.myshopify.com"}) '
            "{ storefront { accountId } } }"
        ),
        "setWhatsAppStorefrontMode": (
            'mutation($t: ID!) { setWhatsAppStorefrontMode(input: {tenantId: $t, accountId: "x", mode: AGENTIC}) '
            "{ storefront { accountId } } }"
        ),
        "startWhatsAppLink": (
            'mutation($t: ID!) { startWhatsAppLink(input: {tenantId: $t, phoneNumber: "0831234567"}) ' "{ code } }"
        ),
        # An organization's own Meta apps (WhatsApp plan Step 2.9).
        "whatsAppMetaApps": "query($t: ID!) { whatsAppMetaApps(tenantId: $t) { id } }",
        "registerWhatsAppMetaApp": (
            'mutation($t: ID!) { registerWhatsAppMetaApp(input: {tenantId: $t, appId: "1", appSecret: "s"}) '
            "{ metaApp { id } } }"
        ),
        "updateWhatsAppMetaAppSecret": (
            'mutation($t: ID!) { updateWhatsAppMetaAppSecret(input: {tenantId: $t, metaAppId: "x", appSecret: "s"}) '
            "{ metaApp { id } } }"
        ),
        "regenerateWhatsAppMetaAppVerifyToken": (
            'mutation($t: ID!) { regenerateWhatsAppMetaAppVerifyToken(input: {tenantId: $t, metaAppId: "x"}) '
            "{ metaApp { id } } }"
        ),
        "removeWhatsAppMetaApp": (
            'mutation($t: ID!) { removeWhatsAppMetaApp(input: {tenantId: $t, metaAppId: "x"}) { ok } }'
        ),
        "setWhatsAppNumberMetaApp": (
            'mutation($t: ID!) { setWhatsAppNumberMetaApp(input: {tenantId: $t, accountId: "x", metaAppId: null}) '
            "{ account { id } } }"
        ),
    },
    "SHOPIFY": {
        "shopifyProducts": (
            'query($t: ID!) { shopifyProducts(tenantId: $t, shopDomain: "a.myshopify.com", first: 12) '
            "{ products { title } } }"
        ),
        "shopifyStartInstall": (
            'mutation($t: ID!) { shopifyStartInstall(input: {tenantId: $t, shopDomain: "a.myshopify.com"}) '
            "{ authorizeUrl } }"
        ),
        "shopifyLinkShop": (
            'mutation($t: ID!) { shopifyLinkShop(input: {tenantId: $t, claim: "c"}) { shop { shopDomain } } }'
        ),
    },
}
# Only using a feature is locked: browsing products. The assistant and replies are locked in the
# router (TestTheRouter below). Everything else sets up, which needs no plan (Step 2.8, finding 16).
USING = {"shopifyProducts"}
LOCKED_FIELDS = [
    (feature, name, request) for feature, fields in FIELDS.items() for name, request in fields.items() if name in USING
]
SETUP_FIELDS = [
    (feature, name, request)
    for feature, fields in FIELDS.items()
    for name, request in fields.items()
    if name not in USING
]

# What's kept stays readable on a lapsed plan (decision 5).
READABLE = {
    "whatsAppAccounts": "query($t: ID!) { whatsAppAccounts(tenantId: $t) { id } }",
    "whatsAppStorefronts": "query($t: ID!) { whatsAppStorefronts(tenantId: $t) { accountId } }",
    "whatsAppEligibleStores": "query($t: ID!) { whatsAppEligibleStores(tenantId: $t) }",
    "shopifyShops": "query($t: ID!) { shopifyShops(tenantId: $t) { shopDomain } }",
}


@pytest.fixture(autouse=True)
def plans_decide(settings, mocker):
    settings.PLAN_ENTITLEMENTS_ENABLED = True
    settings.PAYMENT_BACKEND = settings.PAYMENT_BACKEND_PAYFAST
    mocker.patch("apps.whatsapp.tasks.send_queued_messages.delay")
    mocker.patch("apps.shopify.storefront.get_shop", return_value={"name": "Acme Snow Co", "logo_url": None})


@pytest.fixture
def acme():
    # On the free plan, as every organization starts.
    return TenantFactory(type=TenantType.ORGANIZATION, name="Acme")


def as_owner(graphene_client, organization):
    user = UserFactory()
    TenantMembershipFactory(user=user, tenant=organization, role=TenantUserRole.OWNER)
    graphene_client.force_authenticate(user)
    graphene_client.set_tenant_dependent_context(organization, TenantUserRole.OWNER)


def errors_of(graphene_client, organization, request):
    response = graphene_client.query(request, variable_values={"t": to_global_id("TenantType", organization.id)})
    return [error["message"] for error in response.get("errors") or []]


class TestTheApi:
    @pytest.mark.parametrize("feature, name, request_text", LOCKED_FIELDS, ids=[name for _, name, _ in LOCKED_FIELDS])
    def test_a_field_using_a_feature_the_plan_lacks_is_refused(
        self, graphene_client, acme, feature, name, request_text
    ):
        as_owner(graphene_client, acme)

        assert "plan_required" in errors_of(graphene_client, acme, request_text)

    @pytest.mark.parametrize("feature, name, request_text", SETUP_FIELDS, ids=[name for _, name, _ in SETUP_FIELDS])
    def test_setting_up_needs_no_plan(self, graphene_client, acme, feature, name, request_text):
        as_owner(graphene_client, acme)

        # Its own validation may still refuse the made-up ids; never the plan.
        assert "plan_required" not in errors_of(graphene_client, acme, request_text)

    @pytest.mark.parametrize("name", READABLE)
    def test_what_is_kept_stays_readable(self, graphene_client, acme, name):
        as_owner(graphene_client, acme)

        assert errors_of(graphene_client, acme, READABLE[name]) == []

    def test_disconnecting_a_number_stays_allowed(self, graphene_client, acme):
        as_owner(graphene_client, acme)
        account = InternalAccountFactory(tenant=acme)
        request = (
            "mutation($t: ID!, $a: ID!) { disconnectWhatsAppAccount(input: {tenantId: $t, accountId: $a}) "
            "{ account { id } } }"
        )

        response = graphene_client.query(
            request, variable_values={"t": to_global_id("TenantType", acme.id), "a": account.pk}
        )

        assert "plan_required" not in [error["message"] for error in response.get("errors") or []]

    def test_a_plan_with_the_feature_is_not_refused(self, graphene_client, acme):
        PayFastSubscriptionFactory(tenant=acme, monthly=True)
        as_owner(graphene_client, acme)

        assert "plan_required" not in errors_of(graphene_client, acme, FIELDS["SHOPIFY"]["shopifyProducts"])

    def test_with_the_setting_off_nothing_is_refused_for_the_plan(self, graphene_client, acme, settings):
        settings.PLAN_ENTITLEMENTS_ENABLED = False
        as_owner(graphene_client, acme)

        assert "plan_required" not in errors_of(graphene_client, acme, FIELDS["SHOPIFY"]["shopifyProducts"])


class TestTheRouter:
    def test_a_lapsed_organizations_customers_get_no_reply_and_the_message_is_kept(self, acme):
        customer = customer_of(selling_number(acme, store(acme)))

        assert send(customer, "hi") == []
        assert WhatsAppMessage.objects.filter(contact=customer, direction=MessageDirection.INBOUND).exists()

    def test_a_lapsed_organizations_linked_members_get_no_reply(self, acme):
        member = ContactFactory(account=InternalAccountFactory(tenant=acme))
        link_member(member)

        assert send(member, "hi") == []

    def test_on_a_plan_with_whatsapp_the_customer_is_answered(self, acme):
        PayFastSubscriptionFactory(tenant=acme, monthly=True)
        customer = customer_of(selling_number(acme, store(acme)))

        assert send(customer, "hi") != []
