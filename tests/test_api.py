"""Unit tests for the Deglaze API client; no real network calls are made."""
import asyncio
import importlib
import sys
import types
import unittest
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "deglaze_poc"
package = types.ModuleType("deglaze_poc_test")
package.__path__ = [str(PACKAGE_DIR)]
sys.modules.setdefault("deglaze_poc_test", package)
api_module = importlib.import_module("deglaze_poc_test.api")
DeglazeApiClient = api_module.DeglazeApiClient
DeglazeAPIError = api_module.DeglazeAPIError
FirebaseAuthError = api_module.FirebaseAuthError
InvalidSignInLink = api_module.InvalidSignInLink
parse_sign_in_link = api_module.parse_sign_in_link
summarize_grocery_response = api_module.summarize_grocery_response
extract_grocery_items = api_module.extract_grocery_items
extract_grocery_stores = api_module.extract_grocery_stores
grocery_item_store_ids = api_module.grocery_item_store_ids
normalize_recipe_collection_manifest = api_module.normalize_recipe_collection_manifest
recipe_collection_ids = api_module.recipe_collection_ids
plan_recipe_collection_changes = api_module.plan_recipe_collection_changes
extract_recipe_ingredient_choices = api_module.extract_recipe_ingredient_choices
normalize_grocery_item_key = api_module.normalize_grocery_item_key
plan_recipe_ingredient_additions = api_module.plan_recipe_ingredient_additions

EXAMPLE_LINK = (
    "https://deglaze-prod.firebaseapp.com/__/auth/action?"
    "apiKey=AIzaSyExampleKey123&mode=signIn&oobCode=one-time-code"
    "&continueUrl=https%3A%2F%2Fweb.deglaze.app%2Fsign-in%2Femail%2Fcheck"
)


class FakeResponse:
    def __init__(self, status, payload):
        self.status = status
        self.payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def json(self, content_type=None):
        return self.payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def _call(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        result = self.responses.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result

    def post(self, url, **kwargs):
        return self._call("POST", url, **kwargs)

    def get(self, url, **kwargs):
        return self._call("GET", url, **kwargs)

    def patch(self, url, **kwargs):
        return self._call("PATCH", url, **kwargs)


def test_client(session):
    client = DeglazeApiClient(
        session,
        "person@example.com",
        firebase_api_key="AIzaSyExampleKey123",
        device_id="device-test",
        time_zone="Europe/Copenhagen",
    )
    client._id_token = "test-id-token"
    client._id_token_expires_at = 9_999_999_999
    client.user_id = "test-user-id"
    client.refresh_token = "test-refresh-token"
    return client


class ParseLinkTests(unittest.TestCase):
    def test_parses_deglaze_link(self):
        parsed = parse_sign_in_link(EXAMPLE_LINK)
        self.assertEqual(parsed.api_key, "AIzaSyExampleKey123")
        self.assertEqual(parsed.oob_code, "one-time-code")

    def test_rejects_untrusted_host(self):
        with self.assertRaises(InvalidSignInLink):
            parse_sign_in_link(EXAMPLE_LINK.replace("deglaze-prod.firebaseapp.com", "evil.example"))

    def test_rejects_wrong_mode(self):
        with self.assertRaises(InvalidSignInLink):
            parse_sign_in_link(EXAMPLE_LINK.replace("mode=signIn", "mode=resetPassword"))


class GroceryTests(unittest.TestCase):
    def test_summarizes_real_shape_without_exposing_item_names(self):
        result = summarize_grocery_response({
            "data": {"lists": [{"id": "household-list", "items": [
                {"id": "private-item-id", "text": "Milk", "version": 7,
                 "status": {"status": "pending"}},
                {"id": "private-item-id-2", "text": "Bread", "status": {"status": "completed"}},
            ]}]}
        })
        self.assertTrue(result["schema_recognized"])
        self.assertEqual(result["list_count"], 1)
        self.assertEqual(result["item_count"], 2)
        self.assertEqual(result["pending_count"], 1)
        self.assertEqual(result["completed_count"], 1)
        self.assertNotIn("Milk", str(result))
        self.assertNotIn("private-item-id", str(result))

    def test_unknown_schema_is_not_zero(self):
        result = summarize_grocery_response({"unexpected": {"other": True}})
        self.assertFalse(result["schema_recognized"])
        self.assertIsNone(result["item_count"])

    def test_add_grocery_item_request(self):
        session = FakeSession([FakeResponse(200, {"data": {"ok": True}})])
        client = test_client(session)
        asyncio.run(client.async_add_grocery_item(
            "  Apples ", item_id="gli_test123", suggestion_id="apples", stores=["store-a"]
        ))
        method, url, call = session.calls[0]
        self.assertEqual(method, "POST")
        self.assertEqual(url, "https://gateway.deglaze.app/v1/lists/item")
        self.assertEqual(call["json"]["listId"], "household:hh-test-user-id:d")
        self.assertEqual(call["json"]["itemId"], "gli_test123")
        self.assertEqual(call["json"]["text"], "Apples")
        self.assertEqual(call["json"]["suggestionId"], "apples")
        self.assertEqual(call["json"]["stores"], ["store-a"])
        self.assertIn("ts", call["json"])
        self.assertEqual(call["headers"]["Authorization"], "Bearer test-id-token")

    def test_status_patch_includes_current_version_and_nested_status(self):
        session = FakeSession([FakeResponse(200, {"data": {"id": "item-1"}})])
        client = test_client(session)
        asyncio.run(client.async_set_grocery_item_status("item-1", 123, "completed"))
        method, url, call = session.calls[0]
        self.assertEqual(method, "PATCH")
        self.assertEqual(url, "https://gateway.deglaze.app/v1/lists/item")
        self.assertEqual(call["json"]["listId"], "household:hh-test-user-id:d")
        self.assertEqual(call["json"]["itemId"], "item-1")
        self.assertEqual(call["json"]["version"], 123)
        self.assertEqual(call["json"]["updates"]["status"]["status"], "completed")
        self.assertIsInstance(call["json"]["updates"]["status"]["ts"], int)


class GroceryStoreTests(unittest.TestCase):
    def test_extracts_and_sorts_store_metadata(self):
        stores = extract_grocery_stores({"data": {"lists": [{
            "id": "list-1",
            "stores": [
                {"id": "store-z", "name": "zeta", "version": 2, "private": "omit"},
                {"id": "store-a", "name": "Alpha", "version": 0},
                {"id": "store-bad", "name": " "},
                "invalid",
            ],
            "items": [],
        }]}})
        self.assertEqual([store["name"] for store in stores], ["Alpha", "zeta"])
        self.assertEqual(stores[0], {"id": "store-a", "name": "Alpha", "version": 0})
        self.assertNotIn("private", str(stores))

    def test_normalizes_item_store_associations(self):
        self.assertEqual(grocery_item_store_ids({"stores": ["s1", {"id": "s2"}, "s1", None]}), ["s1", "s2"])
        self.assertEqual(grocery_item_store_ids({"stores": None}), [])

    def test_create_store_payload(self):
        session = FakeSession([FakeResponse(200, {"data": {"id": "store-test", "name": "Market"}})])
        client = test_client(session)
        asyncio.run(client.async_create_grocery_store(" Market ", store_id="store-test"))
        method, url, call = session.calls[0]
        self.assertEqual(method, "POST")
        self.assertEqual(url, "https://gateway.deglaze.app/v1/lists/stores")
        self.assertEqual(call["json"], {"id": "store-test", "name": "Market"})

    def test_rename_store_uses_current_version(self):
        session = FakeSession([FakeResponse(200, {"data": {"id": "store-test", "name": "New name", "version": 4}})])
        client = test_client(session)
        asyncio.run(client.async_update_grocery_store("store-test", "New name", 3))
        method, url, call = session.calls[0]
        self.assertEqual(method, "POST")
        self.assertEqual(url, "https://gateway.deglaze.app/v1/lists/stores/update")
        self.assertEqual(call["json"], {"id": "store-test", "name": "New name", "version": 3})

    def test_delete_store_payload(self):
        session = FakeSession([FakeResponse(200, {"data": {"deleted": True}})])
        client = test_client(session)
        asyncio.run(client.async_delete_grocery_store("store-test"))
        method, url, call = session.calls[0]
        self.assertEqual(method, "POST")
        self.assertEqual(url, "https://gateway.deglaze.app/v1/lists/stores/delete")
        self.assertEqual(call["json"], {"id": "store-test"})

    def test_assign_item_stores_is_versioned_patch(self):
        session = FakeSession([FakeResponse(200, {"data": {"id": "item-1", "stores": ["s1", "s2"]}})])
        client = test_client(session)
        asyncio.run(client.async_set_grocery_item_stores("item-1", 17, ["s1", "s2", "s1"], "list-1"))
        method, url, call = session.calls[0]
        self.assertEqual(method, "PATCH")
        self.assertEqual(url, "https://gateway.deglaze.app/v1/lists/item")
        self.assertEqual(call["json"], {
            "listId": "list-1", "itemId": "item-1", "version": 17,
            "updates": {"stores": ["s1", "s2"]},
        })

    def test_store_mutations_reject_blank_inputs(self):
        client = test_client(FakeSession([]))
        for operation in (
            lambda: client.async_create_grocery_store(" ", store_id="id"),
            lambda: client.async_create_grocery_store("Store", store_id=" "),
            lambda: client.async_update_grocery_store("id", " ", 0),
            lambda: client.async_delete_grocery_store(" "),
            lambda: client.async_set_grocery_item_stores("item", 0, [""]),
        ):
            with self.assertRaises(ValueError):
                asyncio.run(operation())


class RecipeSyncTests(unittest.TestCase):
    def test_extract_recipe_ingredient_choices_preserves_sections_text_and_stable_ids(self):
        ingredients = {
            "sections": [
                {"id": "sauces", "title": "For the sauce", "items": [
                    {"id": "garlic-id", "text": "2 cloves garlic, minced"},
                    {"id": "salt-id", "text": "Salt to taste"},
                ]},
                {"title": "To serve", "items": ["Fresh scallions"]},
            ]
        }
        choices = extract_recipe_ingredient_choices(ingredients)
        self.assertEqual(choices, [
            {"id": "section-0:garlic-id", "text": "2 cloves garlic, minced", "section": "For the sauce"},
            {"id": "section-0:salt-id", "text": "Salt to taste", "section": "For the sauce"},
            {"id": "section-1:item-0", "text": "Fresh scallions", "section": "To serve"},
        ])

    def test_duplicate_key_normalizes_measurements_prep_and_plural(self):
        self.assertEqual(normalize_grocery_item_key("2 tbsp chopped garlic"), "garlic")
        self.assertEqual(normalize_grocery_item_key("Garlic"), "garlic")
        self.assertEqual(normalize_grocery_item_key("1 scallion (for topping)"), "scallion")
        self.assertEqual(normalize_grocery_item_key("scallions"), "scallion")
        self.assertEqual(normalize_grocery_item_key(""), "")

    def test_duplicate_key_preserves_unicode_ingredient_names(self):
        self.assertEqual(normalize_grocery_item_key("1 jalapeño, chopped"), normalize_grocery_item_key("jalapeños"))
        self.assertTrue(normalize_grocery_item_key("香菜"))

    def test_recipe_ingredient_add_plan_skips_existing_items_by_default(self):
        choices = [
            {"id": "section-0:garlic", "text": "2 cloves garlic, minced"},
            {"id": "section-0:onion", "text": "1 onion, diced"},
        ]
        existing = [{"id": "g1", "text": "Garlic", "status": {"status": "pending"}}]
        plan = plan_recipe_ingredient_additions(choices, ["section-0:garlic", "section-0:onion"], existing)
        self.assertEqual([choice["id"] for choice in plan["candidates"]], ["section-0:onion"])
        self.assertEqual(plan["duplicates"][0]["ingredient"], "2 cloves garlic, minced")
        self.assertEqual(plan["duplicates"][0]["matches"][0]["text"], "Garlic")

    def test_recipe_ingredient_add_plan_allows_explicit_duplicate_override(self):
        choices = [{"id": "section-0:milk", "text": "1 cup milk"}]
        existing = [{"id": "g1", "text": "Milk"}]
        plan = plan_recipe_ingredient_additions(choices, ["section-0:milk"], existing, True)
        self.assertEqual([choice["id"] for choice in plan["candidates"]], ["section-0:milk"])
        self.assertEqual(len(plan["duplicates"]), 1)

    def test_recipe_ingredient_add_plan_rejects_unknown_ids_and_empty_selection(self):
        choices = [{"id": "section-0:milk", "text": "1 cup milk"}]
        with self.assertRaisesRegex(ValueError, "Select at least one"):
            plan_recipe_ingredient_additions(choices, [], [])
        with self.assertRaisesRegex(ValueError, "no longer available"):
            plan_recipe_ingredient_additions(choices, ["not-an-ingredient"], [])

    def test_full_recipe_sync_follows_cursor_and_merges_records(self):
        session = FakeSession([
            FakeResponse(200, {"data": {
                "version": 300,
                "recipes": [{"id": "user:r1", "title": "First", "version": 280,
                             "ingredients": {"sections": []}}],
                "next": "next-cursor",
                "collections": {"collections": []},
                "limit": {"recipeLimits": {"unlimited": True}},
            }}),
            FakeResponse(200, {"data": {
                "version": 350,
                "recipes": [{"id": "user:r2", "title": "Second", "version": 340}],
            }}),
        ])
        client = test_client(session)
        recipes, meta = asyncio.run(client.async_sync_recipes())
        self.assertEqual(set(recipes), {"user:r1", "user:r2"})
        self.assertEqual(meta["version"], 350)
        self.assertEqual(meta["pages"], 2)
        self.assertEqual(meta["received"], 2)
        self.assertTrue(meta["full_sync"])
        self.assertEqual(meta["collections"], {"collections": []})
        self.assertEqual(session.calls[0][1], "https://gateway.deglaze.app/v1/recipes/get-list")
        self.assertEqual(session.calls[0][2]["json"], {})
        self.assertEqual(session.calls[1][2]["json"], {"start": "next-cursor"})

    def test_incremental_sync_uses_five_second_overlap_and_merges(self):
        session = FakeSession([FakeResponse(200, {"data": {
            "version": 20_000,
            "recipes": [{"id": "user:r1", "title": "Updated", "version": 19_999}],
        }})])
        client = test_client(session)
        old = {"user:r1": {"id": "user:r1", "title": "Old", "version": 10_000},
               "user:r2": {"id": "user:r2", "title": "Keep", "version": 9_000}}
        recipes, meta = asyncio.run(client.async_sync_recipes(old, 20_000))
        self.assertEqual(session.calls[0][2]["json"], {"sinceVersion": 15_000})
        self.assertEqual(recipes["user:r1"]["title"], "Updated")
        self.assertEqual(recipes["user:r2"]["title"], "Keep")
        self.assertFalse(meta["full_sync"])

    def test_incremental_sync_preserves_collection_manifest_when_page_omits_it(self):
        existing_collections = {"collections": [{"id": "uc:one", "name": "Cuban"}]}
        session = FakeSession([FakeResponse(200, {"data": {
            "version": 20_000,
            "recipes": [{"id": "user:r1", "title": "Updated", "version": 19_999}],
        }})])
        client = test_client(session)
        _recipes, meta = asyncio.run(client.async_sync_recipes(
            {"user:r1": {"id": "user:r1", "title": "Old"}},
            20_000,
            existing_collections,
        ))
        self.assertEqual(meta["collections"], existing_collections)


class RecipeCollectionTests(unittest.TestCase):
    def setUp(self):
        self.raw_manifest = {
            "collections": [
                {"id": "uc:cuban", "type": "tag", "tagType": "user", "name": "Cuban",
                 "userTags": ["cuban"], "systemTags": [], "deleted": False, "hidden": False},
                {"id": "uc:cooked", "type": "tag", "tagType": "user", "name": "Cooked & Liked",
                 "userTags": ["cooked & liked"], "systemTags": [], "deleted": False, "hidden": False,
                 "displayIfEmpty": True},
                {"id": "sc:tag:main", "type": "tag", "tagType": "system", "name": "Main Course",
                 "userTags": [], "systemTags": ["main"], "deleted": False, "hidden": False},
                {"id": "sc:tag:soup", "type": "tag", "tagType": "system", "name": "Soup",
                 "userTags": [], "systemTags": ["soup"], "deleted": False, "hidden": False},
                {"id": "sc:filter:recent", "type": "filter", "name": "Recently Added", "source": "system"},
                {"id": "uc:deleted", "type": "tag", "tagType": "user", "name": "Old",
                 "userTags": ["old"], "deleted": True, "hidden": False},
                {"id": "uc:hidden", "type": "tag", "tagType": "user", "name": "Hidden",
                 "userTags": ["hidden"], "deleted": False, "hidden": True},
            ],
            "layout": {"groups": []},
        }
        self.collections = normalize_recipe_collection_manifest(self.raw_manifest)

    def test_manifest_returns_visible_user_and_system_tags_not_filters(self):
        self.assertEqual(
            [(item["id"], item["tag_type"]) for item in self.collections],
            [("uc:cuban", "user"), ("uc:cooked", "user"),
             ("sc:tag:main", "system"), ("sc:tag:soup", "system")],
        )
        self.assertTrue(next(item for item in self.collections if item["id"] == "uc:cooked")["display_if_empty"])

    def test_structured_recipe_tags_map_to_multiple_collections(self):
        recipe = {"tags": [
            {"type": "user", "tag": "Cooked & Liked"},
            {"type": "system", "tag": "main"},
            {"type": "system", "tag": "soup"},
        ]}
        self.assertEqual(
            recipe_collection_ids(recipe, self.collections),
            ["uc:cooked", "sc:tag:main", "sc:tag:soup"],
        )

    def test_tag_matching_is_case_insensitive_and_legacy_strings_are_supported(self):
        self.assertEqual(
            recipe_collection_ids({"tags": [{"type": "user", "tag": "cUbAn"}]}, self.collections),
            ["uc:cuban"],
        )
        self.assertEqual(
            recipe_collection_ids({"tags": ["Soup"]}, self.collections),
            ["sc:tag:soup"],
        )

    def test_user_and_system_tags_do_not_cross_match(self):
        same_named = normalize_recipe_collection_manifest({"collections": [
            {"id": "uc:main", "type": "tag", "tagType": "user", "name": "Main",
             "userTags": ["main"], "systemTags": [], "hidden": False},
            {"id": "sc:main", "type": "tag", "tagType": "system", "name": "Main",
             "userTags": [], "systemTags": ["main"], "hidden": False},
        ]})
        self.assertEqual(
            recipe_collection_ids({"tags": [{"type": "system", "tag": "main"}]}, same_named),
            ["sc:main"],
        )


class MealPlanTests(unittest.TestCase):
    def test_get_meal_plan_sends_explicit_date_range(self):
        session = FakeSession([FakeResponse(200, {"data": {
            "start": "2026-11-01", "end": "2026-11-07", "items": []
        }})])
        client = test_client(session)
        asyncio.run(client.async_get_meal_plan("2026-11-01", "2026-11-07"))
        self.assertEqual(session.calls[0][1], "https://gateway.deglaze.app/v1/planning/get-meal-plan")
        self.assertEqual(session.calls[0][2]["json"], {"start": "2026-11-01", "end": "2026-11-07"})

    def test_add_meal_plan_item_body(self):
        session = FakeSession([FakeResponse(200, {"data": {"id": "plan-1"}})])
        client = test_client(session)
        asyncio.run(client.async_add_meal_plan_item(
            recipe_id="user:recipe-1", date="2026-11-17", label="Snack",
            is_leftovers=True, plan_item_id="j-test123",
        ))
        call = session.calls[0][2]
        self.assertEqual(session.calls[0][1], "https://gateway.deglaze.app/v1/planning/add-item")
        self.assertEqual(call["json"], {
            "type": "recipe", "id": "j-test123", "date": "2026-11-17",
            "recipeId": "user:recipe-1", "label": {"type": "system", "label": "Snack"},
            "isLeftovers": True,
        })

    def test_update_meal_plan_item_body_matches_observed_web_app_shape(self):
        session = FakeSession([FakeResponse(200, {"data": {"id": "user:plan-1", "version": 8}})])
        client = test_client(session)
        asyncio.run(client.async_update_meal_plan_item(
            item_id="user:plan-1", item_type="recipe", version=7,
            updates={"date": "2026-11-18", "label": {"type": "system", "label": "Dinner"}, "isLeftovers": True},
        ))
        self.assertEqual(session.calls[0][1], "https://gateway.deglaze.app/v1/planning/update-item")
        self.assertEqual(session.calls[0][2]["json"], {
            "id": "user:plan-1", "type": "recipe", "version": 7,
            "updates": {"date": "2026-11-18", "label": {"type": "system", "label": "Dinner"}, "isLeftovers": True},
        })

    def test_update_meal_plan_item_rejects_unsupported_update_fields(self):
        session = FakeSession([])
        client = test_client(session)
        with self.assertRaises(ValueError):
            asyncio.run(client.async_update_meal_plan_item(
                item_id="plan-1", item_type="recipe", version=1, updates={"recipeId": "different"},
            ))
        self.assertEqual(session.calls, [])

    def test_remove_meal_plan_item_body_matches_observed_web_app_shape(self):
        session = FakeSession([FakeResponse(200, {"data": {"id": "user:plan-1"}})])
        client = test_client(session)
        asyncio.run(client.async_remove_meal_plan_item("user:plan-1"))
        self.assertEqual(session.calls[0][1], "https://gateway.deglaze.app/v1/planning/remove-item")
        self.assertEqual(session.calls[0][2]["json"], {"id": "user:plan-1"})


class ErrorHandlingTests(unittest.TestCase):
    def test_http_error_body_is_not_exposed_and_next_request_recovers(self):
        private_body = "SIMULATED_PRIVATE_RESPONSE_BODY_DO_NOT_LOG"
        session = FakeSession([
            FakeResponse(503, {"error": private_body}),
            FakeResponse(200, {"data": {"lists": [{"id": "list", "items": []}]}}),
        ])
        client = test_client(session)

        with self.assertRaises(DeglazeAPIError) as ctx:
            asyncio.run(client.async_get_grocery_list())
        self.assertIn("HTTP 503", str(ctx.exception))
        self.assertNotIn(private_body, str(ctx.exception))

        recovered = asyncio.run(client.async_get_grocery_list())
        self.assertTrue(summarize_grocery_response(recovered)["schema_recognized"])
        self.assertEqual(len(session.calls), 2)

    def test_timeout_is_translated_to_safe_error_and_next_request_recovers(self):
        secret_url_detail = "private.invalid?refresh_token=DO_NOT_EXPOSE"
        session = FakeSession([
            asyncio.TimeoutError(secret_url_detail),
            FakeResponse(200, {"data": {"lists": [{"id": "list", "items": []}]}}),
        ])
        client = test_client(session)

        with self.assertRaises(DeglazeAPIError) as ctx:
            asyncio.run(client.async_get_grocery_list())
        self.assertIn("network or timeout error", str(ctx.exception))
        self.assertNotIn("DO_NOT_EXPOSE", str(ctx.exception))
        recovered = asyncio.run(client.async_get_grocery_list())
        self.assertTrue(summarize_grocery_response(recovered)["schema_recognized"])

    def test_firebase_refresh_timeout_is_safe(self):
        session = FakeSession([asyncio.TimeoutError("private refresh request details")])
        client = DeglazeApiClient(
            session,
            "person@example.com",
            firebase_api_key="AIzaSyExampleKey123",
            refresh_token="test-refresh-token",
        )
        with self.assertRaises(FirebaseAuthError) as ctx:
            asyncio.run(client.async_get_id_token(force_refresh=True))
        self.assertIn("network or timeout error", str(ctx.exception))
        self.assertNotIn("private refresh request details", str(ctx.exception))

    def test_live_diagnostic_injects_local_503_then_uses_real_read(self):
        session = FakeSession([
            FakeResponse(200, {"data": {"lists": [{"id": "list", "items": [
                {"id": "item-1", "text": "Private item name", "version": 1,
                 "status": {"status": "pending"}},
            ]}]}}),
        ])
        client = test_client(session)
        payload, diagnostics = asyncio.run(client.async_test_error_handling())
        summary = summarize_grocery_response(payload)
        self.assertTrue(diagnostics["simulated_failure_handled"])
        self.assertTrue(diagnostics["failure_message_sanitized"])
        self.assertEqual(diagnostics["simulated_failure_origin"], "local-only")
        self.assertEqual(diagnostics["recovery_read_request"], "passed")
        self.assertTrue(diagnostics["read_only"])
        self.assertTrue(summary["schema_recognized"])
        # Only the recovery request reaches the underlying session; the 503 was synthetic.
        self.assertEqual(len(session.calls), 1)
        self.assertNotIn("SIMULATED_PRIVATE_RESPONSE_BODY", str(diagnostics))


class RecipeCollectionMutationTests(unittest.TestCase):
    def test_collection_change_plan_only_includes_real_differences(self):
        changes = plan_recipe_collection_changes(
            {"uc:keep", "uc:remove", "sc:remove"},
            {"uc:keep", "uc:add"},
        )
        self.assertEqual(changes, [
            {"action": "remove", "collection_id": "sc:remove"},
            {"action": "remove", "collection_id": "uc:remove"},
            {"action": "add", "collection_id": "uc:add"},
        ])
        self.assertEqual(plan_recipe_collection_changes({"uc:one"}, {"uc:one"}), [])
        self.assertEqual(plan_recipe_collection_changes(set(), set()), [])

    def test_bulk_edit_request_matches_observed_deglaze_web_payload(self):
        session = FakeSession([FakeResponse(200, {
            "data": {"recipeVersions": {"user:r1": 12345}}
        })])
        client = test_client(session)
        asyncio.run(client.async_edit_recipe_collection_membership(
            recipe_id="user:r1", collection_id="uc:cuban", action="add"
        ))
        method, url, call = session.calls[0]
        self.assertEqual(method, "POST")
        self.assertEqual(url, "https://gateway.deglaze.app/v1/recipes/bulk-edit")
        self.assertEqual(call["json"], {
            "type": "bulkAddRemoveTag",
            "action": "add",
            "collectionId": "uc:cuban",
            "recipeIds": ["user:r1"],
        })

    def test_bulk_edit_remove_uses_same_endpoint_and_remove_action(self):
        session = FakeSession([FakeResponse(200, {"data": {"recipeVersions": {}}})])
        client = test_client(session)
        asyncio.run(client.async_edit_recipe_collection_membership(
            recipe_id="user:r1", collection_id="sc:tag:main", action="remove"
        ))
        self.assertEqual(session.calls[0][2]["json"]["action"], "remove")
        self.assertEqual(session.calls[0][2]["json"]["collectionId"], "sc:tag:main")
        self.assertEqual(session.calls[0][2]["json"]["recipeIds"], ["user:r1"])

    def test_bulk_edit_rejects_invalid_action_and_blank_ids_without_network(self):
        session = FakeSession([])
        client = test_client(session)
        for args in (
            {"recipe_id": "user:r1", "collection_id": "uc:cuban", "action": "delete"},
            {"recipe_id": " ", "collection_id": "uc:cuban", "action": "add"},
            {"recipe_id": "user:r1", "collection_id": " ", "action": "add"},
        ):
            with self.subTest(args=args), self.assertRaises(ValueError):
                asyncio.run(client.async_edit_recipe_collection_membership(**args))
        self.assertEqual(session.calls, [])

    def test_bulk_edit_rejects_malformed_success_response(self):
        session = FakeSession([FakeResponse(200, {"unexpected": {}})])
        client = test_client(session)
        with self.assertRaises(DeglazeAPIError):
            asyncio.run(client.async_edit_recipe_collection_membership(
                recipe_id="user:r1", collection_id="uc:cuban", action="add"
            ))


class AuthenticationTests(unittest.TestCase):
    def test_manual_renewal_expires_cached_token_then_reads_grocery_list(self):
        session = FakeSession([
            FakeResponse(200, {
                "id_token": "renewed-id-token", "refresh_token": "rotated-refresh-token",
                "expires_in": "3600", "user_id": "test-user-id",
            }),
            FakeResponse(200, {"data": {"lists": [{"id": "list", "items": [
                {"id": "item-a", "text": "Milk", "version": 1,
                 "status": {"status": "pending"}},
            ]}]}}),
        ])
        client = test_client(session)
        payload = asyncio.run(client.async_test_auth_renewal())

        self.assertEqual(payload["data"]["lists"][0]["items"][0]["text"], "Milk")
        self.assertEqual(len(session.calls), 2)
        refresh_method, refresh_url, refresh_call = session.calls[0]
        self.assertEqual(refresh_method, "POST")
        self.assertEqual(refresh_url, "https://securetoken.googleapis.com/v1/token")
        self.assertEqual(refresh_call["data"]["grant_type"], "refresh_token")
        self.assertEqual(refresh_call["data"]["refresh_token"], "test-refresh-token")
        read_method, read_url, read_call = session.calls[1]
        self.assertEqual(read_method, "GET")
        self.assertEqual(read_url, "https://gateway.deglaze.app/v1/lists")
        self.assertEqual(read_call["headers"]["Authorization"], "Bearer renewed-id-token")
        self.assertEqual(client._id_token, "renewed-id-token")
        self.assertGreater(client._id_token_expires_at, 0)

    def test_exchange_then_get_list(self):
        session = FakeSession([
            FakeResponse(200, {
                "idToken": "test-id-token", "refreshToken": "test-refresh-token",
                "expiresIn": "3600", "localId": "test-user-id",
            }),
            FakeResponse(200, {"data": {"lists": [{"id": "list", "items": []}]}}),
        ])
        client = DeglazeApiClient(session, "person@example.com", device_id="device-test")
        async def run_flow():
            await client.async_exchange_sign_in_link(EXAMPLE_LINK)
            return await client.async_get_grocery_list()
        result = asyncio.run(run_flow())
        self.assertIn("data", result)
        self.assertEqual(session.calls[0][1], "https://identitytoolkit.googleapis.com/v1/accounts:signInWithEmailLink")
        self.assertEqual(session.calls[0][2]["params"], {"key": "AIzaSyExampleKey123"})
        self.assertEqual(session.calls[0][2]["json"], {"email": "person@example.com", "oobCode": "one-time-code"})
        self.assertEqual(session.calls[1][0], "GET")
        self.assertEqual(session.calls[1][1], "https://gateway.deglaze.app/v1/lists")
        self.assertEqual(session.calls[1][2]["headers"]["Authorization"], "Bearer test-id-token")

    def test_refresh_token_rotation_is_persisted(self):
        session = FakeSession([FakeResponse(200, {
            "id_token": "refreshed-token", "refresh_token": "rotated-refresh",
            "expires_in": "3600", "user_id": "test-user-id",
        })])
        persisted = []
        client = DeglazeApiClient(
            session, "person@example.com", firebase_api_key="AIzaSyExampleKey123",
            refresh_token="old-refresh", on_refresh_token=persisted.append,
        )
        token = asyncio.run(client.async_get_id_token(force_refresh=True))
        self.assertEqual(token, "refreshed-token")
        self.assertEqual(persisted, ["rotated-refresh"])
        self.assertEqual(session.calls[0][1], "https://securetoken.googleapis.com/v1/token")

    def test_gateway_401_refreshes_and_retries_once(self):
        session = FakeSession([
            FakeResponse(401, {"error": "expired"}),
            FakeResponse(200, {
                "id_token": "fresh-id-token", "refresh_token": "rotated-refresh",
                "expires_in": "3600", "user_id": "test-user-id",
            }),
            FakeResponse(200, {"data": {"lists": [{"id": "list", "items": []}]}}),
        ])
        client = test_client(session)
        payload = asyncio.run(client.async_get_grocery_list())
        self.assertIn("data", payload)
        self.assertEqual([call[0] for call in session.calls], ["GET", "POST", "GET"])
        self.assertEqual(session.calls[1][1], "https://securetoken.googleapis.com/v1/token")
        self.assertEqual(
            session.calls[2][2]["headers"]["Authorization"], "Bearer fresh-id-token"
        )


if __name__ == "__main__":
    unittest.main()
