"""
Tests that the invoicing settings read their environment variables (agents.md section 2.3; WhatsApp
plan phase 4, decision 13): the supplier's name and address printed on every invoice.

Kind of test: sanity (agents.md section 2.5). Why: config.settings is imported in a fresh subprocess with
the variables set or removed; nothing is faked.
"""

import pytest

from apps.payfast.tests.utils import read_settings

# Only because the root conftest.py's autouse fixtures need the database (agents.md section 2.5).
pytestmark = [pytest.mark.django_db, pytest.mark.story("WA.D6.OP.J1.A2")]

NAMES = ["INVOICE_SUPPLIER_NAME", "INVOICE_SUPPLIER_ADDRESS"]


def test_invoice_supplier_settings_read_env_vars():
    values = read_settings(
        NAMES, INVOICE_SUPPLIER_NAME="Example SaaS (Pty) Ltd", INVOICE_SUPPLIER_ADDRESS="1 Example Road, Cape Town"
    )

    assert values == {
        "INVOICE_SUPPLIER_NAME": repr("Example SaaS (Pty) Ltd"),
        "INVOICE_SUPPLIER_ADDRESS": repr("1 Example Road, Cape Town"),
    }


def test_invoice_supplier_settings_default_to_empty():
    # Empty is safe: nothing breaks, and the admin check (checks.py) says what's missing.
    values = read_settings(NAMES, INVOICE_SUPPLIER_NAME=None, INVOICE_SUPPLIER_ADDRESS=None)

    assert values == {"INVOICE_SUPPLIER_NAME": repr(""), "INVOICE_SUPPLIER_ADDRESS": repr("")}


def test_invoice_supplier_settings_drop_spaces_at_either_end():
    # User story WA.D6.OP.J1.A2: a stray space after the "=" in .env, or in Render's dashboard, would be copied
    # onto every invoice for good, since an issued invoice never changes.
    values = read_settings(
        NAMES,
        INVOICE_SUPPLIER_NAME="  Example SaaS (Pty) Ltd ",
        INVOICE_SUPPLIER_ADDRESS=" 1 Example Road\\nCape Town  ",
    )

    assert values == {
        "INVOICE_SUPPLIER_NAME": repr("Example SaaS (Pty) Ltd"),
        "INVOICE_SUPPLIER_ADDRESS": repr("1 Example Road\nCape Town"),
    }
