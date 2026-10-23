"""
Tests for apps/whatsapp_saas/menus.py: the WHATSAPP_FORM mode's menus for an organization's team on
its internal communications number (plan Step 1.10, user stories 4, 6, 9 and 21, Step 1.17).

Driven the way a team member drives them: messages through the router, with the real handler that
apps.whatsapp_saas registers at startup, and the real operations of Step 1.9 (the plan said they'd
be faked here; the real ones cost little and test what users will get).
- the main menu works in the number's organization; there's no organization to pick or create
  (maintainer's decision, 2026-10-22)
- items 7 to a page, with Previous, Next and Main menu (D17)
- every screen offers Back or Main menu, and `menu` works from each one
- item detail with Edit and Delete; Delete asks to confirm (D11)
- a member without features.crud.manage sees no Edit or Delete, and a press after losing the
  permission is refused

Kind of test: integration (agents.md section 2.5). Why: users, organizations, items, identities and
conversations are rows in the test database, routed through the real router and handler; nothing is
faked but the send task's Celery delay.
"""

import pytest

from apps.demo.models import CrudDemoItem
from apps.demo.tests.factories import CrudDemoItemFactory
from apps.multitenancy.constants import TenantType, TenantUserRole
from apps.multitenancy.models import OrganizationRolePermission, invalidate_user_permissions_cache
from apps.multitenancy.tests.factories import TenantFactory
from apps.whatsapp.models import WhatsAppConversation

from .chat import main_menu, send, team_member

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def setup(settings, mocker):
    settings.WHATSAPP_DEFAULT_CONVERSATION_MODE = "WHATSAPP_FORM"
    mocker.patch("apps.whatsapp.tasks.send_queued_messages.delay")


@pytest.fixture
def acme():
    return TenantFactory(type=TenantType.ORGANIZATION, name="Acme")


@pytest.fixture
def contact(acme):
    """An admin of Acme, texting Acme's internal number."""
    return team_member(acme)


class TestTheMainMenu:
    def test_it_works_in_the_numbers_organization(self, contact, acme):
        menu = main_menu(contact)

        assert "Acme" in menu.body
        assert "Items" in menu.titles
        assert WhatsAppConversation.objects.get(contact=contact).tenant == acme

    def test_its_text_names_the_organization_as_an_organization(self, contact):
        # Step 1.20: a personal organization is named after its owner's email, so "Organization:"
        # says what the name is.
        assert main_menu(contact).body == "You're working in Organization: Acme. What would you like to do?"

    def test_there_is_no_organization_to_pick_or_create(self, contact):
        menu = main_menu(contact)

        assert "Organizations" not in menu.titles
        assert "Create organization" not in menu.titles

    def test_it_ends_with_a_way_back(self, contact):
        assert main_menu(contact).titles[-1] == "Main menu"


class TestItems:
    def test_items_come_seven_to_a_page_with_next_and_main_menu(self, contact, acme):
        for number in range(16):
            CrudDemoItemFactory(tenant=acme, name=f"Item {number:02d}")
        menu = main_menu(contact)

        [first] = send(contact, press=menu.press("Items"))

        assert first.titles[:7] == [f"Item {number:02d}" for number in range(7)]
        assert first.titles[7:] == ["Next", "Main menu"]
        assert "1 of 3" in first.body

    def test_next_and_previous_move_between_pages(self, contact, acme):
        for number in range(16):
            CrudDemoItemFactory(tenant=acme, name=f"Item {number:02d}")
        menu = main_menu(contact)
        [first] = send(contact, press=menu.press("Items"))

        [second] = send(contact, press=first.press("Next"))
        [third] = send(contact, press=second.press("Next"))

        assert second.titles[0] == "Item 07"
        assert second.titles[-3:] == ["Previous", "Next", "Main menu"]
        assert third.titles == ["Item 14", "Item 15", "Previous", "Main menu"]

    def test_another_organizations_items_never_show(self, contact, acme):
        CrudDemoItemFactory(tenant=acme, name="Ours")
        CrudDemoItemFactory(tenant=TenantFactory(type=TenantType.ORGANIZATION), name="Theirs")
        menu = main_menu(contact)

        [items] = send(contact, press=menu.press("Items"))

        assert items.titles == ["Ours", "Main menu"]

    def test_menu_works_from_the_items_list(self, contact, acme):
        CrudDemoItemFactory(tenant=acme, name="Monthly report")
        menu = main_menu(contact)
        send(contact, press=menu.press("Items"))

        [back] = send(contact, "menu")

        assert "Items" in back.titles

    def test_an_items_detail_offers_edit_delete_and_back(self, contact, acme):
        CrudDemoItemFactory(tenant=acme, name="Monthly report")
        menu = main_menu(contact)
        [items] = send(contact, press=menu.press("Items"))

        [detail] = send(contact, press=items.press("Monthly report"))

        assert "Monthly report" in detail.body
        assert detail.titles == ["Edit", "Delete", "Back"]

    def test_back_returns_to_the_same_page_of_the_list(self, contact, acme):
        for number in range(10):
            CrudDemoItemFactory(tenant=acme, name=f"Item {number:02d}")
        menu = main_menu(contact)
        [first] = send(contact, press=menu.press("Items"))
        [second] = send(contact, press=first.press("Next"))
        [detail] = send(contact, press=second.press("Item 08"))

        [again] = send(contact, press=detail.press("Back"))

        assert again.titles[0] == "Item 07"


class TestDeleting:
    def test_delete_asks_to_confirm_and_confirm_deletes_it(self, contact, acme):
        item = CrudDemoItemFactory(tenant=acme, name="Monthly report")
        menu = main_menu(contact)
        [items] = send(contact, press=menu.press("Items"))
        [detail] = send(contact, press=items.press("Monthly report"))

        [question] = send(contact, press=detail.press("Delete"))
        assert "Monthly report" in question.body
        assert question.titles == ["Confirm", "Cancel", "Main menu"]
        assert CrudDemoItem.objects.filter(pk=item.pk).exists()

        [done] = send(contact, press=question.press("Confirm"))
        assert "Deleted" in done.body
        assert not CrudDemoItem.objects.filter(pk=item.pk).exists()

    def test_cancel_keeps_it(self, contact, acme):
        item = CrudDemoItemFactory(tenant=acme, name="Monthly report")
        menu = main_menu(contact)
        [items] = send(contact, press=menu.press("Items"))
        [detail] = send(contact, press=items.press("Monthly report"))
        [question] = send(contact, press=detail.press("Delete"))

        send(contact, press=question.press("Cancel"))

        assert CrudDemoItem.objects.filter(pk=item.pk).exists()


class TestPermissions:
    def test_a_member_without_manage_sees_no_edit_or_delete(self):
        beta = TenantFactory(type=TenantType.ORGANIZATION, name="Beta")
        contact = team_member(beta, role=TenantUserRole.MEMBER)
        OrganizationRolePermission.objects.filter(role__tenant=beta, permission__code="features.crud.manage").delete()
        CrudDemoItemFactory(tenant=beta, name="Monthly report")
        menu = main_menu(contact)
        [items] = send(contact, press=menu.press("Items"))

        [detail] = send(contact, press=items.press("Monthly report"))

        assert detail.titles == ["Back"]

    def test_a_press_after_losing_the_permission_is_refused(self, contact, acme):
        item = CrudDemoItemFactory(tenant=acme, name="Monthly report")
        menu = main_menu(contact)
        [items] = send(contact, press=menu.press("Items"))
        [detail] = send(contact, press=items.press("Monthly report"))
        OrganizationRolePermission.objects.filter(role__tenant=acme, permission__code="features.crud.manage").delete()
        # Permissions are cached per user and organization; upstream's role editing clears it like this.
        invalidate_user_permissions_cache(contact.identity.user_id, acme.id)

        [refused] = send(contact, press=detail.press("Delete"))

        assert "permission" in refused.body
        assert CrudDemoItem.objects.filter(pk=item.pk).exists()
