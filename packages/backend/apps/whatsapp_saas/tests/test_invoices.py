"""
Tests for the organization's invoices on its team's WhatsApp number (WhatsApp plan phase 4, Step 4.5b,
decisions 12 and 14; D15): "My invoices" in the main menu, and the assistant's show_invoices tool.

- offered to members with billing.view (the Owner and Admins by default), as on the website
- the organization's own invoices, newest first, 7 at most, each by its number with what it's for
- tapping one sends its PDF as a document, uploaded to Meta, never as a link, then the main menu
- no invoices yet says so; a press after losing billing.view is refused
- the assistant shows the same list for the user to tap, and tells anyone else to ask the owner

Kind of test: integration (agents.md section 2.5). Why: users, organizations, payments, invoices and
conversations are rows in the test database, routed through the real router and handler, with the log
send backend, which uploads nothing; the PDFs are files in a temporary folder through Django's file
storage, and only the send task's Celery delay is faked.
"""

import datetime
import json
from decimal import Decimal

import pytest
from django.core.files.base import ContentFile

from apps.finances.constants import MONTHLY_PLAN
from apps.invoicing import services as invoicing
from apps.multitenancy.constants import TenantType, TenantUserRole
from apps.multitenancy.models import OrganizationRolePermission, invalidate_user_permissions_cache
from apps.multitenancy.tests.factories import TenantFactory
from apps.payfast.models import PayFastSubscription
from apps.payfast.tests.factories import PayFastPaymentFactory, PayFastSubscriptionFactory
from apps.whatsapp.models import WhatsAppConversation
from apps.whatsapp.services.router import Turn

from .. import prompts
from ..tools import TOOLS
from .chat import main_menu, send, team_member

pytestmark = [pytest.mark.django_db, pytest.mark.story("WA.D6.OM.J2.A1")]

# Decision 14: anyone without billing.view is told to ask the owner, as for plans (Step 4.1).
ASK_THE_OWNER = "Ask the organization's owner for its invoices."


@pytest.fixture(autouse=True)
def setup(settings, mocker, tmp_path):
    settings.WHATSAPP_DEFAULT_CONVERSATION_MODE = "WHATSAPP_FORM"
    settings.WHATSAPP_SEND_BACKEND = "LOG"
    settings.STORAGES = {**settings.STORAGES, "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"}}
    settings.MEDIA_ROOT = str(tmp_path)
    mocker.patch("apps.whatsapp.tasks.send_queued_messages.delay")


@pytest.fixture
def acme():
    return TenantFactory(type=TenantType.ORGANIZATION, name="Acme")


def invoiced(tenant, item_name="Monthly plan", amount="199.00"):
    payment = PayFastPaymentFactory(tenant=tenant, item_name=item_name, amount_gross=Decimal(amount))
    invoice = invoicing.issue_invoice(payment)
    invoice.pdf.save(f"{invoice.number}.pdf", ContentFile(b"%PDF-test"), save=True)
    return invoice


def run_tool(contact):
    conversation, _ = WhatsAppConversation.objects.get_or_create(contact=contact, tenant=contact.account.tenant)
    turn = Turn(message=None, contact=contact, conversation=conversation, user=contact.identity.user, mode="AGENTIC")
    return TOOLS.run(turn, "show_invoices", json.dumps({}))


class TestTheMenu:
    @pytest.mark.parametrize("role", [TenantUserRole.OWNER, TenantUserRole.ADMIN])
    def test_billing_view_is_offered_my_invoices(self, acme, role):
        assert "My invoices" in main_menu(team_member(acme, role=role)).titles

    def test_a_member_without_billing_view_is_not(self, acme):
        assert "My invoices" not in main_menu(team_member(acme, role=TenantUserRole.MEMBER)).titles

    def test_it_lists_the_organizations_own_invoices_newest_first(self, acme):
        first = invoiced(acme, "Monthly plan")
        second = invoiced(acme, "Donation", "50.00")
        invoiced(TenantFactory(type=TenantType.ORGANIZATION, name="Globex"))
        contact = team_member(acme, role=TenantUserRole.ADMIN)

        [invoices] = send(contact, press=main_menu(contact).press("My invoices"))

        assert invoices.titles == [second.number, first.number, "Main menu"]
        assert invoices.descriptions[:2] == ["Donation · ZAR 50.00", "Monthly plan · ZAR 199.00"]

    def test_it_lists_seven_at_most(self, acme):
        for _ in range(9):
            invoiced(acme)
        contact = team_member(acme, role=TenantUserRole.ADMIN)

        [invoices] = send(contact, press=main_menu(contact).press("My invoices"))

        assert len(invoices.titles) == 8
        assert invoices.titles[0] == "INV-" + invoices.titles[0][4:]

    def test_tapping_one_sends_its_pdf_as_a_document_then_the_main_menu(self, acme):
        invoice = invoiced(acme)
        contact = team_member(acme, role=TenantUserRole.ADMIN)
        [invoices] = send(contact, press=main_menu(contact).press("My invoices"))

        [document, menu] = send(contact, press=invoices.press(invoice.number))

        assert document.document["filename"] == f"{invoice.number}.pdf"
        assert document.document["id"].startswith("log.")
        assert document.body == f"Invoice {invoice.number} for Acme: Monthly plan, ZAR 199.00."
        assert "My invoices" in menu.titles

    def test_with_no_invoices_yet_it_says_so(self, acme):
        contact = team_member(acme, role=TenantUserRole.OWNER)

        [empty, *_] = send(contact, press=main_menu(contact).press("My invoices"))

        assert empty.body.startswith("No invoices yet")

    def test_during_a_trial_it_says_when_the_first_invoice_comes(self, acme):
        # User story WA.D6.OM.J2.A1: a free trial isn't a payment, so it has no invoice; the Owner is told when
        # the first one comes, the trial's end, when the first payment is charged.
        PayFastSubscriptionFactory(
            tenant=acme,
            plan=MONTHLY_PLAN.name,
            status=PayFastSubscription.Status.TRIALING,
            has_used_trial=True,
            trial_end=datetime.datetime(2026, 12, 7, 10, tzinfo=datetime.UTC),
        )
        contact = team_member(acme, role=TenantUserRole.OWNER)

        [empty, *_] = send(contact, press=main_menu(contact).press("My invoices"))

        assert empty.body == "No invoices yet. Your first comes with your first payment on 2026-12-07."

    def test_a_press_after_losing_billing_view_is_refused(self, acme):
        invoice = invoiced(acme)
        contact = team_member(acme, role=TenantUserRole.ADMIN)
        [invoices] = send(contact, press=main_menu(contact).press("My invoices"))
        OrganizationRolePermission.objects.filter(role__tenant=acme, permission__code="billing.view").delete()
        invalidate_user_permissions_cache(contact.identity.user_id, acme.id)

        [refused, *_] = send(contact, press=invoices.press(invoice.number))

        assert refused.body == ASK_THE_OWNER


class TestTheAssistant:
    def test_it_shows_the_list_for_the_user_to_tap(self, acme):
        invoice = invoiced(acme)

        result = run_tool(team_member(acme, role=TenantUserRole.ADMIN))

        [message] = result.messages
        rows = message["interactive"]["action"]["sections"][0]["rows"]
        assert rows[0]["title"] == invoice.number
        assert result.output["success"] is True

    def test_the_instructions_say_to_show_invoices_for_anything_about_them(self, acme):
        contact = team_member(acme, role=TenantUserRole.ADMIN)
        conversation, _ = WhatsAppConversation.objects.get_or_create(contact=contact, tenant=acme)
        turn = Turn(
            message=None, contact=contact, conversation=conversation, user=contact.identity.user, mode="AGENTIC"
        )

        assert "For invoices or receipts, call show_invoices" in prompts.instructions(turn)

    def test_it_tells_a_member_without_billing_view_to_ask_the_owner(self, acme):
        result = run_tool(team_member(acme, role=TenantUserRole.MEMBER))

        assert result.messages is None
        assert result.output == {"success": False, "error": ASK_THE_OWNER, "code": "permission_denied"}
