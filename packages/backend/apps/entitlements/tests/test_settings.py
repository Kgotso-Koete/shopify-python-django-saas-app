"""
Tests proving PLAN_ENTITLEMENTS_ENABLED in config/settings.py is read from its environment variable,
and is off when the variable is unset (agents.md section 2.3; WhatsApp plan phase 3, decision 7: off
by default, so an upgrade changes nothing until an operator chooses to sell plans).

Kind of test: sanity (agents.md section 2.5). Why: it proves the setting reads its environment
variable, in a fresh subprocess; nothing is faked.
"""

import pytest

from .utils import read_settings

# The root conftest.py's autouse fixtures need the database, so these tests are marked to allow it.
pytestmark = pytest.mark.django_db


class TestTheSetting:
    def test_plan_entitlements_enabled_setting_reads_env_var(self):
        # Compared as repr() strings, so "True" also proves the type is a bool.
        assert read_settings(["PLAN_ENTITLEMENTS_ENABLED"], PLAN_ENTITLEMENTS_ENABLED="true") == {
            "PLAN_ENTITLEMENTS_ENABLED": "True"
        }

    def test_it_is_off_when_unset(self):
        assert read_settings(["PLAN_ENTITLEMENTS_ENABLED"], PLAN_ENTITLEMENTS_ENABLED=None) == {
            "PLAN_ENTITLEMENTS_ENABLED": "False"
        }
