"""
Tests for the WhatsApp Flow forms in apps/whatsapp_saas/menus.py (plan Step 1.11b, decisions D9 and
D11, user stories 5 and 6, Step 1.17): creating and renaming items, and renaming the organization,
with pre-filled forms.

- a form opens pre-filled: the current name when renaming
- everything happens in the number's organization, so the item form has no organization to choose,
  and no organization can be created here (maintainer's decision, 2026-10-22)
- its answers are checked by the same rules as the website's (the Step 1.9 operations and their
  serializers), and then go through Confirm; nothing is saved before the user presses it
- an expired or tampered form changes nothing

Kind of test: integration (agents.md section 2.5). Why: messages are routed through the real router
and handler against the test database, with forms published through the log send backend; nothing
is faked but the send task's Celery delay.
"""

import pytest

from apps.demo.models import CrudDemoItem
from apps.demo.tests.factories import CrudDemoItemFactory
from apps.multitenancy.constants import TenantType, TenantUserRole
from apps.multitenancy.models import Tenant
from apps.multitenancy.tests.factories import TenantFactory
from apps.whatsapp.services import flows

from ..flows import FLOWS_DIR
from .chat import main_menu, send, team_member

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def setup(settings, mocker):
    settings.WHATSAPP_DEFAULT_CONVERSATION_MODE = "WHATSAPP_FORM"
    settings.WHATSAPP_SEND_BACKEND = "LOG"
    mocker.patch("apps.whatsapp.tasks.send_queued_messages.delay")


@pytest.fixture
def acme():
    return TenantFactory(type=TenantType.ORGANIZATION, name="Acme")


@pytest.fixture
def contact(acme):
    """An admin of Acme, texting Acme's internal number."""
    return team_member(acme)


def publish_forms(account):
    """The forms, published as connecting the number does (fake ids, with the log backend)."""
    for path in FLOWS_DIR.glob("*.json"):
        flows.publish(account, path.stem, path.read_text())


@pytest.fixture
def published(contact):
    publish_forms(contact.account)


def answer(contact, form, **answers):
    """Complete `form` (a Screen holding a Flow message) with `answers`, as Meta's nfm_reply does."""
    return send(contact, form_answers={"flow_token": form.flow["flow_token"], **answers})


class TestNewItem:
    def test_the_form_opens_for_the_numbers_organization(self, contact, published):
        menu = main_menu(contact)

        [form] = send(contact, press=menu.press("New item"))

        assert form.flow["flow_action_payload"]["screen"] == "ITEM"
        data = form.flow["flow_action_payload"]["data"]
        assert data == {"heading": "Create an item in Acme", "name": ""}

    def test_the_answers_are_confirmed_before_anything_is_saved(self, contact, acme, published):
        menu = main_menu(contact)
        [form] = send(contact, press=menu.press("New item"))

        [question] = answer(contact, form, name="Monthly report")

        assert "Monthly report" in question.body and "Acme" in question.body
        assert question.titles == ["Confirm", "Cancel", "Main menu"]
        assert not CrudDemoItem.objects.filter(name="Monthly report").exists()

        [done] = send(contact, press=question.press("Confirm"))
        assert "Created" in done.body
        assert CrudDemoItem.objects.get(name="Monthly report").tenant == acme

    def test_an_organization_sent_with_the_answers_is_ignored(self, contact, acme, published):
        # A form published before Step 1.17 still sends one; the number's organization is the only one.
        menu = main_menu(contact)
        [form] = send(contact, press=menu.press("New item"))
        elsewhere = TenantFactory(type=TenantType.ORGANIZATION)

        [question] = answer(contact, form, organization=str(elsewhere.pk), name="Monthly report")
        send(contact, press=question.press("Confirm"))

        assert CrudDemoItem.objects.get(name="Monthly report").tenant == acme

    def test_the_websites_validation_applies_before_confirming(self, contact, published):
        menu = main_menu(contact)
        [form] = send(contact, press=menu.press("New item"))

        screens = answer(contact, form, name="")

        assert "name" in screens[0].body.lower()
        assert "Confirm" not in screens[-1].titles


class TestEditingAnItem:
    def test_the_form_opens_with_the_current_name(self, contact, acme, published):
        item = CrudDemoItemFactory(tenant=acme, name="Monthly report")
        menu = main_menu(contact)
        [items] = send(contact, press=menu.press("Items"))
        [detail] = send(contact, press=items.press("Monthly report"))

        [form] = send(contact, press=detail.press("Edit"))

        assert form.flow["flow_action_payload"]["data"]["name"] == "Monthly report"
        [question] = answer(contact, form, name="Quarterly report")
        send(contact, press=question.press("Confirm"))
        assert CrudDemoItem.objects.get(pk=item.pk).name == "Quarterly report"


class TestTheOrganization:
    def test_an_admin_renames_it_with_the_current_name_pre_filled(self, contact, acme, published):
        menu = main_menu(contact)

        [form] = send(contact, press=menu.press("Rename organization"))

        assert form.flow["flow_action_payload"]["screen"] == "ORGANIZATION"
        assert form.flow["flow_action_payload"]["data"]["name"] == "Acme"
        [question] = answer(contact, form, name="Acme Holdings")
        send(contact, press=question.press("Confirm"))
        assert Tenant.objects.get(pk=acme.pk).name == "Acme Holdings"

    def test_a_member_isnt_offered_rename(self):
        beta = TenantFactory(type=TenantType.ORGANIZATION, name="Beta")

        menu = main_menu(team_member(beta, role=TenantUserRole.MEMBER))

        assert "Rename organization" not in menu.titles


class TestFormsThatCantBeUsed:
    def test_a_form_answered_twice_changes_nothing_the_second_time(self, contact, published):
        menu = main_menu(contact)
        [form] = send(contact, press=menu.press("New item"))
        answer(contact, form, name="Monthly report")

        screens = answer(contact, form, name="Again")

        assert screens[0].body.startswith("That form has expired")

    def test_a_tampered_form_changes_nothing(self, contact, published):
        menu = main_menu(contact)
        [form] = send(contact, press=menu.press("New item"))
        form.flow["flow_token"] = form.flow["flow_token"][:-2] + "xx"

        screens = answer(contact, form, name="Monthly report")

        assert screens[0].body.startswith("That form has expired")

    def test_forms_that_arent_published_say_what_to_do(self, contact):
        menu = main_menu(contact)

        screens = send(contact, press=menu.press("New item"))

        # Connecting the number publishes them (Step 1.17); an admin can connect it again, on the
        # website's WhatsApp page (Step 1.19).
        assert "WhatsApp page" in screens[0].body
