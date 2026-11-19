"""
Tests for the invoicing system check (WhatsApp plan phase 4, decision 13): a deployment that takes
PayFast payments, and so issues invoices, is warned at startup when the supplier's name or address,
printed on every invoice, isn't set. A warning, not an error: payments keep working.

Kind of test: sanity (agents.md section 2.5). Why: the check function runs against overridden settings;
nothing is faked.
"""

import pytest

from ..checks import check_invoicing_settings

# Only because the root conftest.py's autouse fixtures need the database (agents.md section 2.5).
pytestmark = [pytest.mark.django_db, pytest.mark.story("WA.D6.OP.J1.A2")]


@pytest.fixture
def payfast(settings):
    settings.PAYMENT_BACKEND = "payfast"
    settings.INVOICE_SUPPLIER_NAME = "Example SaaS (Pty) Ltd"
    settings.INVOICE_SUPPLIER_ADDRESS = "1 Example Road, Cape Town"
    return settings


def ids(messages):
    return [message.id for message in messages]


def test_a_complete_supplier_needs_no_warning(payfast):
    assert check_invoicing_settings(None) == []


@pytest.mark.parametrize(
    ("name", "warning"), [("INVOICE_SUPPLIER_NAME", "invoicing.W001"), ("INVOICE_SUPPLIER_ADDRESS", "invoicing.W002")]
)
def test_a_missing_supplier_detail_is_warned_about(payfast, name, warning):
    setattr(payfast, name, "")

    assert ids(check_invoicing_settings(None)) == [warning]


@pytest.mark.parametrize(
    ("name", "warning"), [("INVOICE_SUPPLIER_NAME", "invoicing.W001"), ("INVOICE_SUPPLIER_ADDRESS", "invoicing.W002")]
)
def test_a_supplier_detail_of_only_spaces_counts_as_missing(payfast, name, warning):
    # User story WA.D6.OP.J1.A2: blanks would print an empty supplier on every invoice, as an empty value would.
    setattr(payfast, name, "   ")

    assert ids(check_invoicing_settings(None)) == [warning]


def test_without_payfast_nothing_is_invoiced_so_nothing_is_needed(settings):
    settings.PAYMENT_BACKEND = "stripe"
    settings.INVOICE_SUPPLIER_NAME = ""
    settings.INVOICE_SUPPLIER_ADDRESS = ""

    assert check_invoicing_settings(None) == []
