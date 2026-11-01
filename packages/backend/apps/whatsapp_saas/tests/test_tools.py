"""
Tests for the assistant's tools for an organization's team in apps/whatsapp_saas/tools.py (plan Step
1.13, decisions D10 and D11, user story 8, Step 1.17).

- the list is fixed, and each tool runs one Step 1.9 or Step 1.12 operation, so the assistant can do
  exactly what the menus can, with the same permission checks
- the organization is the number's: no tool names one, and none lists, picks or creates one
  (maintainer's decision, 2026-10-22)
- a write asks the user to confirm, with the same summary the menus show, and saves nothing
- a refusal (not found, no permission, invalid) is told to the model in words it can pass on
- an id the model made up is simply not found

Kind of test: integration (agents.md section 2.5). Why: organizations, items, stores and pending
actions are rows in the test database; only fetch_products, which calls Shopify, is mocked.
"""

import json

import pytest

from apps.demo.models import CrudDemoItem
from apps.demo.tests.factories import CrudDemoItemFactory
from apps.multitenancy.constants import TenantType, TenantUserRole
from apps.multitenancy.tests.factories import TenantFactory, TenantMembershipFactory
from apps.shopify.models import ShopifyShop
from apps.users.tests.factories import UserFactory
from apps.whatsapp.models import WhatsAppConversation, WhatsAppPendingAction
from apps.whatsapp.services.router import Turn
from apps.whatsapp.tests.factories import ContactFactory, InternalAccountFactory, MessageFactory

from ..tools import TOOLS

pytestmark = pytest.mark.django_db


@pytest.fixture
def user():
    return UserFactory()


def turn_in(tenant, user):
    """A turn on `tenant`'s internal number, which the router puts the conversation in."""
    contact = ContactFactory(account=InternalAccountFactory(tenant=tenant))
    conversation = WhatsAppConversation.objects.create(contact=contact, tenant=tenant)
    return Turn(
        message=MessageFactory(contact=contact), contact=contact, conversation=conversation, user=user, mode="AGENTIC"
    )


@pytest.fixture
def working_in(user):
    tenant = TenantFactory(type=TenantType.ORGANIZATION, name="Acme")
    TenantMembershipFactory(user=user, tenant=tenant, role=TenantUserRole.ADMIN)
    return tenant


@pytest.fixture
def turn(working_in, user):
    return turn_in(working_in, user)


def run(turn, tool, **arguments):
    return TOOLS.run(turn, tool, json.dumps(arguments))


def body(result):
    [message] = result.messages
    return message["interactive"]["body"]["text"]


class TestTheList:
    def test_it_is_exactly_these_tools(self):
        assert [tool["name"] for tool in TOOLS.schemas()] == [
            "rename_organization",
            "list_items",
            "create_item",
            "update_item",
            "delete_item",
            "list_stores",
            "list_products",
        ]

    def test_a_name_is_the_users_own_never_made_up(self):
        # Step 2.8, finding 1: "I would like to create a new item" became an item called "New Item".
        for tool in TOOLS.schemas():
            if tool["name"] in {"create_item", "update_item", "rename_organization"}:
                description = tool["parameters"]["properties"]["name"]["description"]
                assert "exactly as the user gave it" in description
                assert "never make one up" in description

    def test_no_tool_names_an_organization(self):
        # Every tool works in the number's organization, never one from the model.
        for tool in TOOLS.schemas():
            names = set(tool["parameters"]["properties"])
            assert not names & {"organization_id", "tenant_id", "organization", "tenant"}


class TestTheOrganization:
    def test_renaming_asks_to_confirm_for_the_numbers_organization(self, turn, working_in):
        result = run(turn, "rename_organization", name="Acme Holdings")

        assert body(result) == "Rename Acme to Acme Holdings?"
        pending = WhatsAppPendingAction.objects.get()
        assert (pending.action, pending.tenant, pending.arguments) == (
            "organizations.rename",
            working_in,
            {"name": "Acme Holdings"},
        )

    def test_a_member_cant_rename(self, user):
        tenant = TenantFactory(type=TenantType.ORGANIZATION, name="Beta")
        TenantMembershipFactory(user=user, tenant=tenant, role=TenantUserRole.MEMBER)

        output = run(turn_in(tenant, user), "rename_organization", name="Gamma").output

        assert output["success"] is False
        assert output["code"] == "permission_denied"
        assert not WhatsAppPendingAction.objects.exists()


class TestItems:
    def test_listing_gives_a_page_of_the_organizations_items(self, turn, working_in):
        item = CrudDemoItemFactory(tenant=working_in, name="Monthly report")
        CrudDemoItemFactory(name="Someone else's")

        output = run(turn, "list_items", page=None).output

        assert output["items"] == [{"id": str(item.pk), "name": "Monthly report"}]
        assert (output["page"], output["total_pages"]) == (1, 1)

    def test_creating_one_asks_to_confirm_with_the_menus_summary_and_saves_nothing(self, turn, working_in):
        result = run(turn, "create_item", name="Monthly report")

        assert result.output == {
            "success": True,
            "status": "awaiting_confirmation",
            "message": "The user has been asked to confirm with buttons. Nothing is done until they press Confirm.",
        }
        assert body(result) == "Create Monthly report in Acme?"
        assert not CrudDemoItem.objects.exists()
        pending = WhatsAppPendingAction.objects.get()
        assert (pending.action, pending.tenant, pending.arguments) == (
            "items.create",
            working_in,
            {"name": "Monthly report"},
        )

    def test_the_websites_validation_applies_before_asking(self, turn, working_in):
        output = run(turn, "create_item", name="").output

        assert output["success"] is False
        assert output["code"] == "invalid"
        assert "Name" in output["error"]
        assert not WhatsAppPendingAction.objects.exists()

    def test_updating_and_deleting_ask_to_confirm(self, turn, working_in):
        item = CrudDemoItemFactory(tenant=working_in, name="Monthly report")

        assert body(run(turn, "update_item", item_id=str(item.pk), name="Quarterly report")) == (
            "Rename Monthly report to Quarterly report?"
        )
        assert body(run(turn, "delete_item", item_id=str(item.pk))) == "Delete Monthly report? This can't be undone."
        assert list(WhatsAppPendingAction.objects.order_by("pk").values_list("action", flat=True)) == [
            "items.update",
            "items.delete",
        ]
        assert CrudDemoItem.objects.get(pk=item.pk).name == "Monthly report"

    @pytest.mark.parametrize("item_id", ["another-organizations", "not an id"])
    def test_an_item_outside_the_organization_or_made_up_is_not_found(self, turn, working_in, item_id):
        if item_id == "another-organizations":
            item_id = str(CrudDemoItemFactory().pk)

        output = run(turn, "delete_item", item_id=item_id).output

        assert output == {"success": False, "error": "Item not found.", "code": "not_found"}


class TestProducts:
    @pytest.fixture
    def fetch(self, mocker):
        page = {
            "products": [
                {
                    "id": "gid://shopify/Product/1",
                    "title": "Blue shirt",
                    "handle": "blue-shirt",
                    "status": "ACTIVE",
                    "image_url": None,
                    "image_alt": None,
                    "price_min": "19.99",
                    "price_max": "19.99",
                    "currency_code": "ZAR",
                }
            ],
            "page_info": {
                "has_next_page": True,
                "has_previous_page": False,
                "start_cursor": "cursor-start",
                "end_cursor": "cursor-end",
            },
        }
        return mocker.patch("apps.whatsapp_saas.use_cases.fetch_products", return_value=page)

    def test_the_stores_are_listed(self, turn, working_in):
        store = ShopifyShop.objects.create(shop_domain="acme.myshopify.com", tenant=working_in)

        output = run(turn, "list_stores").output

        assert output["stores"] == [{"id": str(store.pk), "domain": "acme.myshopify.com"}]

    def test_with_one_store_products_need_no_store_id(self, turn, working_in, fetch):
        ShopifyShop.objects.create(shop_domain="acme.myshopify.com", tenant=working_in)

        output = run(turn, "list_products", store_id=None, search="shirt", after=None, before=None).output

        assert fetch.call_args.kwargs["query"] == "shirt"
        assert output["products"] == [{"title": "Blue shirt", "price": "ZAR 19.99", "status": "Active"}]
        assert output["next_page_after"] == "cursor-end"
        assert output["previous_page_before"] is None

    def test_with_several_stores_the_model_is_asked_to_choose(self, turn, working_in, fetch):
        ShopifyShop.objects.create(shop_domain="acme.myshopify.com", tenant=working_in)
        ShopifyShop.objects.create(shop_domain="acme-outlet.myshopify.com", tenant=working_in)

        output = run(turn, "list_products", store_id=None, search=None, after=None, before=None).output

        assert output["success"] is False
        assert "list_stores" in output["error"]
        fetch.assert_not_called()

    def test_a_made_up_store_id_is_not_found(self, turn, working_in, fetch):
        output = run(turn, "list_products", store_id="not an id", search=None, after=None, before=None).output

        assert output == {"success": False, "error": "Store not found.", "code": "not_found"}
