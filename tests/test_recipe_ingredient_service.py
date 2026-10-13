"""Focused tests for selected recipe-ingredient additions (no live API calls)."""
from __future__ import annotations

import asyncio
import copy
import importlib
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = ROOT / "custom_components" / "deglaze_poc"

# The real workflow function depends only on HomeAssistantError at runtime, but
# this build workspace doesn't install Home Assistant/voluptuous. Stub only the
# import-time interfaces needed to load services.py; no HA behavior is simulated
# beyond the explicit coordinator/client fakes below.
ha = types.ModuleType("homeassistant")
ha.__path__ = []
core = types.ModuleType("homeassistant.core")
core.HomeAssistant = type("HomeAssistant", (), {})
core.ServiceCall = type("ServiceCall", (), {})
core.SupportsResponse = type("SupportsResponse", (), {"ONLY": "only"})
exceptions = types.ModuleType("homeassistant.exceptions")
class HomeAssistantError(Exception):
    pass
exceptions.HomeAssistantError = HomeAssistantError
helpers = types.ModuleType("homeassistant.helpers")
helpers.__path__ = []
config_validation = types.ModuleType("homeassistant.helpers.config_validation")
helpers.config_validation = config_validation
voluptuous = types.ModuleType("voluptuous")
coordinator_stub = types.ModuleType("deglaze_poc_test.coordinator")
coordinator_stub.DeglazePOCCoordinator = type("DeglazePOCCoordinator", (), {})

for name, module in {
    "homeassistant": ha,
    "homeassistant.core": core,
    "homeassistant.exceptions": exceptions,
    "homeassistant.helpers": helpers,
    "homeassistant.helpers.config_validation": config_validation,
    "voluptuous": voluptuous,
}.items():
    sys.modules.setdefault(name, module)

package = types.ModuleType("deglaze_poc_test")
package.__path__ = [str(PACKAGE_DIR)]
sys.modules.setdefault("deglaze_poc_test", package)
sys.modules.setdefault("deglaze_poc_test.coordinator", coordinator_stub)
services_module = importlib.import_module("deglaze_poc_test.services")
add_recipe_ingredients_from_selection = services_module.add_recipe_ingredients_from_selection
api_module = importlib.import_module("deglaze_poc_test.api")


class FakeClient:
    default_grocery_list_id = "household:hh-test-user:d"

    def __init__(self, items=None, stores=None, *, omit_store_assignment=False, fail_add_at=None):
        self.items = copy.deepcopy(items or [])
        self.stores = copy.deepcopy(stores or [])
        self.omit_store_assignment = omit_store_assignment
        self.fail_add_at = fail_add_at
        self.add_calls = []

    async def async_get_grocery_list(self):
        return {"data": {"lists": [{
            "id": self.default_grocery_list_id,
            "items": copy.deepcopy(self.items),
            "stores": copy.deepcopy(self.stores),
        }]}}

    async def async_add_grocery_item(self, text, *, item_id, stores=None, **_kwargs):
        self.add_calls.append({"text": text, "item_id": item_id, "stores": list(stores or [])})
        if self.fail_add_at == len(self.add_calls):
            raise RuntimeError("synthetic network timeout")
        self.items.append({
            "id": item_id,
            "itemId": item_id,
            "text": text,
            "status": {"status": "pending"},
            "version": 1,
            "stores": [] if self.omit_store_assignment else list(stores or []),
        })
        return {"data": {"id": item_id}}


class FakeCoordinator:
    def __init__(self, client, recipe):
        self.client = client
        list_payload = {"data": {"lists": [{
            "id": client.default_grocery_list_id,
            "items": copy.deepcopy(client.items),
            "stores": copy.deepcopy(client.stores),
        }]}}
        self.data = {
            "recipes": {"recipe-1": recipe},
            "recipe_meta": {},
            "grocery": {
                "lists": api_module.extract_grocery_lists(list_payload),
                "items": api_module.extract_grocery_items(list_payload),
                "summary": {},
            },
            "errors": {},
        }
        self.refresh_count = 0

    async def async_request_refresh(self):
        self.refresh_count += 1
        payload = await self.client.async_get_grocery_list()
        self.data["grocery"] = {
            "lists": api_module.extract_grocery_lists(payload),
            "items": api_module.extract_grocery_items(payload),
            "summary": api_module.summarize_grocery_response(payload),
        }
        self.data["errors"].pop("grocery", None)


class RecipeIngredientServiceTests(unittest.TestCase):
    def setUp(self):
        self.recipe = {
            "id": "recipe-1",
            "title": "Garlic noodles",
            "ingredients": {"sections": [
                {"title": "Sauce", "items": [
                    {"id": "garlic", "text": "2 cloves garlic, minced"},
                    {"id": "soy", "text": "2 tbsp soy sauce"},
                ]},
                {"title": "To serve", "items": [
                    {"id": "scallion", "text": "2 scallions"},
                ]},
            ]},
        }
        self.stores = [{"id": "store-market", "name": "Market"}]

    def run_add(self, *, items=None, selected=None, stores=None, include_duplicates=False,
                omit_store_assignment=False, fail_add_at=None, recipe=None):
        client = FakeClient(
            items=items,
            stores=self.stores,
            omit_store_assignment=omit_store_assignment,
            fail_add_at=fail_add_at,
        )
        coordinator = FakeCoordinator(client, recipe or self.recipe)
        result = asyncio.run(add_recipe_ingredients_from_selection(
            client,
            coordinator,
            "recipe-1",
            selected if selected is not None else ["section-0:garlic", "section-0:soy"],
            stores or [],
            include_duplicates,
        ))
        return result, client, coordinator

    def test_adds_selected_ingredients_preserving_original_text_and_store_and_verifies(self):
        result, client, coordinator = self.run_add(selected=["section-0:garlic", "section-1:scallion"], stores=["store-market"])
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["added_count"], 2)
        self.assertEqual(result["verified_count"], 2)
        self.assertTrue(result["store_assignment_verified"])
        self.assertEqual([call["text"] for call in client.add_calls], ["2 cloves garlic, minced", "2 scallions"])
        self.assertTrue(all(call["stores"] == ["store-market"] for call in client.add_calls))
        self.assertEqual(coordinator.refresh_count, 1)

    def test_existing_duplicate_is_skipped_by_default_but_other_selection_adds(self):
        result, client, _coordinator = self.run_add(
            items=[{"id": "existing-garlic", "text": "Garlic", "status": {"status": "pending"}}],
            selected=["section-0:garlic", "section-0:soy"],
        )
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["added_count"], 1)
        self.assertEqual(result["skipped_duplicate_count"], 1)
        self.assertEqual([call["text"] for call in client.add_calls], ["2 tbsp soy sauce"])

    def test_explicit_duplicate_override_adds_duplicate_and_reports_it(self):
        result, client, _coordinator = self.run_add(
            items=[{"id": "existing-milk", "text": "Milk"}],
            selected=["section-0:soy"], include_duplicates=True,
        )
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["added_count"], 1)
        self.assertEqual(result["skipped_duplicate_count"], 0)
        self.assertEqual(len(client.add_calls), 1)

    def test_all_duplicates_skips_without_writes_or_refresh(self):
        result, client, coordinator = self.run_add(
            items=[{"id": "existing-garlic", "text": "Garlic"}],
            selected=["section-0:garlic"],
        )
        self.assertEqual(result["status"], "skipped")
        self.assertTrue(result["read_only"])
        self.assertEqual(result["added_count"], 0)
        self.assertEqual(client.add_calls, [])
        self.assertEqual(coordinator.refresh_count, 0)

    def test_stale_ingredient_id_is_rejected_without_writes(self):
        client = FakeClient(stores=self.stores)
        coordinator = FakeCoordinator(client, self.recipe)
        with self.assertRaisesRegex(HomeAssistantError, "no longer available"):
            asyncio.run(add_recipe_ingredients_from_selection(
                client, coordinator, "recipe-1", ["not-in-recipe"], [], False
            ))
        self.assertEqual(client.add_calls, [])

    def test_unknown_store_is_rejected_without_writes(self):
        client = FakeClient(stores=self.stores)
        coordinator = FakeCoordinator(client, self.recipe)
        with self.assertRaisesRegex(HomeAssistantError, "stores are no longer available"):
            asyncio.run(add_recipe_ingredients_from_selection(
                client, coordinator, "recipe-1", ["section-0:soy"], ["deleted-store"], False
            ))
        self.assertEqual(client.add_calls, [])

    def test_store_assignment_must_be_visible_after_refresh_to_report_full_success(self):
        result, client, _coordinator = self.run_add(
            selected=["section-0:soy"], stores=["store-market"], omit_store_assignment=True,
        )
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["added_count"], 1)
        self.assertEqual(result["verified_count"], 0)
        self.assertFalse(result["store_assignment_verified"])
        self.assertIn("store_assignment_warning", result)

    def test_failed_write_is_not_reported_as_passed(self):
        result, client, _coordinator = self.run_add(
            selected=["section-0:soy"], fail_add_at=1,
        )
        self.assertNotEqual(result["status"], "passed")
        self.assertEqual(result["added_count"], 0)
        self.assertTrue(result.get("error"))


if __name__ == "__main__":
    unittest.main()
