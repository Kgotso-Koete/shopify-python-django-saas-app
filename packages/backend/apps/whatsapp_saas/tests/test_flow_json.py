"""
Tests for the WhatsApp Flow JSON files in apps/whatsapp_saas/flows/ (plan Step 1.11a, decision D9):
the forms an organization's team fills in to create or rename items, and rename the organization.

They're sent pre-filled with flow_action "navigate" and have no data endpoint, so each file must:
- need no endpoint: no routing_model or data_api_version
  (https://developers.facebook.com/docs/whatsapp/flows/reference/flowjson)
- declare every ${data.…} it uses under its screen's `data`, each with an `__example__`
- keep its inputs outside a Form component, since `init-value` (the pre-fill) works only there
  (https://developers.facebook.com/docs/whatsapp/flows/reference/components)
- end with a Footer whose `complete` action sends the answers back as its payload

Kind of test: unit (agents.md section 2.5). Why: it reads JSON files and checks their shape, with no
database or network; nothing is faked.
"""

import json
import re
from pathlib import Path

import pytest

from ..flows import FLOWS_DIR, SCREEN_NAMES

# The root conftest.py registers fixtures whose autouse parts need the database.
pytestmark = pytest.mark.django_db

FLOW_FILES = sorted(Path(FLOWS_DIR).glob("*.json"))
DATA_REFERENCE = re.compile(r"\$\{data\.([a-z_]+)\}")


def components(screen):
    return screen["layout"]["children"]


def test_there_is_one_file_per_form():
    assert {path.stem for path in FLOW_FILES} == set(SCREEN_NAMES)


def test_the_item_form_has_no_organization_to_choose():
    # Everything happens in the number's organization (plan Step 1.17, maintainer's decision of 2026-10-22).
    [screen] = json.loads((Path(FLOWS_DIR) / "item.json").read_text())["screens"]

    assert [c["name"] for c in components(screen) if c["type"] in ("TextInput", "Dropdown")] == ["name"]
    assert set(screen["data"]) == {"heading", "name"}


@pytest.mark.parametrize("path", FLOW_FILES, ids=lambda path: path.stem)
class TestEachFlow:
    def test_it_needs_no_endpoint(self, path):
        flow = json.loads(path.read_text())

        assert "routing_model" not in flow
        assert "data_api_version" not in flow
        # A Flow JSON version that has component init-value (4.0 and later).
        assert tuple(int(part) for part in flow["version"].split(".")) >= (4, 0)

    def test_it_opens_on_its_named_screen_which_ends_the_flow(self, path):
        [screen] = json.loads(path.read_text())["screens"]

        assert screen["id"] == SCREEN_NAMES[path.stem]
        assert screen["terminal"] is True

    def test_every_data_reference_is_declared_with_an_example(self, path):
        [screen] = json.loads(path.read_text())["screens"]
        used = set(DATA_REFERENCE.findall(json.dumps(screen["layout"])))

        assert used
        for name in used:
            assert "__example__" in screen["data"][name], name

    def test_inputs_are_outside_a_form_so_they_can_be_pre_filled(self, path):
        [screen] = json.loads(path.read_text())["screens"]

        assert all(component["type"] != "Form" for component in components(screen))
        inputs = [c for c in components(screen) if c["type"] in ("TextInput", "Dropdown")]
        assert inputs
        assert all(component["init-value"].startswith("${data.") for component in inputs)

    def test_the_footer_completes_the_flow_with_every_answer(self, path):
        [screen] = json.loads(path.read_text())["screens"]
        footer = components(screen)[-1]
        inputs = [c["name"] for c in components(screen) if c["type"] in ("TextInput", "Dropdown")]

        assert footer["type"] == "Footer"
        action = footer["on-click-action"]
        assert action["name"] == "complete"
        assert action["payload"] == {name: "${form." + name + "}" for name in inputs}
