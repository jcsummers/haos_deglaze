"""Static regression checks for the recipe-browser and Lovelace UI build."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SENSOR_SOURCE = (ROOT / "custom_components" / "deglaze_poc" / "sensor.py").read_text()
WEBSOCKET_SOURCE = (ROOT / "custom_components" / "deglaze_poc" / "websocket.py").read_text()
INIT_SOURCE = (ROOT / "custom_components" / "deglaze_poc" / "__init__.py").read_text()
SERVICE_SOURCE = (ROOT / "custom_components" / "deglaze_poc" / "services.py").read_text()
SERVICE_YAML = (ROOT / "custom_components" / "deglaze_poc" / "services.yaml").read_text()
API_SOURCE = (ROOT / "custom_components" / "deglaze_poc" / "api.py").read_text()
COORDINATOR_SOURCE = (ROOT / "custom_components" / "deglaze_poc" / "coordinator.py").read_text()
CARD_SOURCE = (ROOT / "www" / "deglaze-cards.js").read_text()


class UiBuildTests(unittest.TestCase):
    def test_auth_renewal_diagnostic_is_a_response_enabled_read_only_action(self):
        self.assertIn('"test_auth_renewal"', SERVICE_SOURCE)
        self.assertIn('supports_response=SupportsResponse.ONLY', SERVICE_SOURCE)
        self.assertIn('client.async_test_auth_renewal()', SERVICE_SOURCE)
        self.assertIn('"read_only": True', SERVICE_SOURCE)
        self.assertIn('self._id_token_expires_at = 0', API_SOURCE)
        self.assertIn('return await self.async_get_grocery_list()', API_SOURCE)
        self.assertIn('test_auth_renewal:', (ROOT / "custom_components" / "deglaze_poc" / "services.yaml").read_text())

    def test_error_handling_diagnostic_is_response_enabled_and_read_only(self):
        self.assertIn('"test_error_handling"', SERVICE_SOURCE)
        self.assertIn('supports_response=SupportsResponse.ONLY', SERVICE_SOURCE)
        self.assertIn('client.async_test_error_handling()', SERVICE_SOURCE)
        self.assertIn('"simulated_failure_origin": "local-only"', API_SOURCE)
        self.assertIn('_FailFirstListReadSession', API_SOURCE)
        self.assertIn('test_error_handling:', SERVICE_YAML)
        self.assertIn('no grocery items are changed', SERVICE_YAML)

    def test_transport_errors_are_converted_to_safe_integration_errors(self):
        self.assertIn('import aiohttp', API_SOURCE)
        self.assertIn('asyncio.TimeoutError, aiohttp.ClientError', API_SOURCE)
        self.assertIn('failed due to a network or timeout error', API_SOURCE)
        self.assertIn('response bodies were not logged', SERVICE_SOURCE)

    def test_recipe_per_entity_sensor_manager_removed(self):
        self.assertNotIn("class DeglazeRecipeSensor", SENSOR_SOURCE)
        self.assertNotIn("class RecipeSensorManager", SENSOR_SOURCE)
        self.assertIn("async_entries_for_config_entry", SENSOR_SOURCE)

    def test_all_four_lovelace_cards_are_registered(self):
        for card in (
            "deglaze-grocery-add-card",
            "deglaze-upcoming-meals-card",
            "deglaze-weekly-meal-planner-card",
            "deglaze-recipe-library-card",
        ):
            self.assertIn(f'customElements.define("{card}"', CARD_SOURCE)

    def test_recipe_library_uses_backend_websocket_cache(self):
        self.assertIn("/recipes/list", WEBSOCKET_SOURCE)
        self.assertIn('f"{DOMAIN}/recipe"', WEBSOCKET_SOURCE)
        self.assertIn("register_websocket_commands(hass)", INIT_SOURCE)
        self.assertIn('type: `${this._config.domain}/recipes/list`', CARD_SOURCE)

    def test_recipe_detail_exposes_canonical_ingredient_choices(self):
        self.assertIn("extract_recipe_ingredient_choices", API_SOURCE)
        self.assertIn('details["ingredients_for_grocery"] = extract_recipe_ingredient_choices(recipe.get("ingredients"))', WEBSOCKET_SOURCE)
        self.assertIn('ingredients_for_grocery', CARD_SOURCE)
        self.assertIn('class="ingredient-choice"', CARD_SOURCE)
        self.assertIn('id="review-ingredients"', CARD_SOURCE)

    def test_recipe_to_grocery_websocket_schema_avoids_unsupported_ensure_list(self):
        # Home Assistant's voluptuous module does not expose vol.ensure_list.
        # Require JSON arrays explicitly and validate their contents/length.
        self.assertNotIn("vol.ensure_list", WEBSOCKET_SOURCE)
        self.assertIn('vol.Required("ingredient_ids"): vol.All(\n            list, vol.Length(min=1, max=300)', WEBSOCKET_SOURCE)
        self.assertIn('vol.Optional("store_ids", default=[]): vol.All(\n            list, vol.Length(max=100)', WEBSOCKET_SOURCE)

    def test_recipe_to_grocery_websocket_uses_async_response_and_server_validation(self):
        self.assertIn('f"{DOMAIN}/recipe/add-ingredients"', WEBSOCKET_SOURCE)
        self.assertIn('@websocket_api.async_response\nasync def websocket_add_recipe_ingredients(', WEBSOCKET_SOURCE)
        self.assertIn('async_register_command(hass, websocket_add_recipe_ingredients)', WEBSOCKET_SOURCE)
        self.assertIn('add_recipe_ingredients_from_selection(', SERVICE_SOURCE)
        self.assertIn('plan_recipe_ingredient_additions(', SERVICE_SOURCE)
        self.assertIn('include_duplicates', CARD_SOURCE)
        self.assertIn('store_ids: this._ingredientStoreIds', CARD_SOURCE)
        self.assertIn('await coordinator.async_request_refresh()', SERVICE_SOURCE)

    def test_recipe_to_grocery_review_has_duplicate_warning_store_choice_and_confirmation(self):
        self.assertIn('Possible duplicate of', CARD_SOURCE)
        self.assertIn('Add ingredients flagged as possible duplicates anyway', CARD_SOURCE)
        self.assertIn('Assign to store(s) (optional)', CARD_SOURCE)
        self.assertIn('Confirm and add', CARD_SOURCE)
        self.assertIn('Back to recipe', CARD_SOURCE)

    def test_recipe_to_grocery_verifies_store_assignment_and_refreshes_grocery_card(self):
        self.assertIn('"store_assignment_verified": stores_verified', SERVICE_SOURCE)
        self.assertIn('grocery_item_store_ids(refreshed_by_id[item["id"]])', SERVICE_SOURCE)
        self.assertIn('"store_assignment_warning"', SERVICE_SOURCE)
        self.assertIn('deglaze-grocery-list-updated', CARD_SOURCE)
        grocery_card = CARD_SOURCE.split("class DeglazeGroceryAddCard extends HTMLElement", 1)[1].split("const deglazeCategoryLabel", 1)[0]
        self.assertIn('window.addEventListener("deglaze-grocery-list-updated"', grocery_card)
        self.assertIn('window.removeEventListener("deglaze-grocery-list-updated"', grocery_card)

    def test_recipe_library_exposes_and_filters_deglaze_collections(self):
        self.assertIn("normalize_recipe_collection_manifest", API_SOURCE)
        self.assertIn("recipe_collection_ids", API_SOURCE)
        self.assertIn('"collections": public_collections', WEBSOCKET_SOURCE)
        self.assertIn('"collection_ids"', WEBSOCKET_SOURCE)
        self.assertIn('"collection_names"', WEBSOCKET_SOURCE)
        self.assertIn('data["recipe_meta"].get("collections")', COORDINATOR_SOURCE)
        self.assertIn('id="collection-filter"', CARD_SOURCE)
        self.assertIn('optgroup label="Your collections"', CARD_SOURCE)
        self.assertIn('optgroup label="Built-in categories"', CARD_SOURCE)
        self.assertIn("_selectedCollectionId", CARD_SOURCE)
        self.assertIn("_getFilteredRecipes()", CARD_SOURCE)
        self.assertIn("collection_ids.includes(this._selectedCollectionId)", CARD_SOURCE)
        self.assertIn("recipe.collection_names.slice(0, 4).map", CARD_SOURCE)
        self.assertIn("collectionNames.map", CARD_SOURCE)

    def test_card_wires_grocery_and_meal_plan_services(self):
        self.assertIn("deglaze_poc.add_grocery_item", CARD_SOURCE)
        self.assertIn('"add_meal_plan_item"', CARD_SOURCE)
        self.assertIn('"refresh"', CARD_SOURCE)

    def test_grocery_card_loads_items_and_supports_status_updates(self):
        self.assertIn('`${this._config.domain}/grocery/list`', CARD_SOURCE)
        self.assertIn('"set_grocery_item_status"', CARD_SOURCE)
        self.assertIn('id="search"', CARD_SOURCE)
        self.assertIn('id="filter"', CARD_SOURCE)
        self.assertIn("Mark bought", CARD_SOURCE)
        self.assertIn("Mark to buy", CARD_SOURCE)

    def test_grocery_sensor_attributes_stay_small(self):
        grocery_sensor = SENSOR_SOURCE.split("class DeglazeGroceryListSensor", 1)[1].split(
            "class DeglazeRecipeLibrarySensor", 1
        )[0]
        # The full item list is served to the card through WebSocket, not stored
        # in Recorder-backed sensor state attributes.
        self.assertNotIn('"items":', grocery_sensor)
        for attribute in ("pending_count", "completed_count", "item_count", "list_count", "last_updated"):
            self.assertIn(f'"{attribute}"', grocery_sensor)
        self.assertIn('f"{DOMAIN}/grocery/list"', WEBSOCKET_SOURCE)

    def test_grocery_card_supports_store_management_assignment_grouping_and_sorting(self):
        self.assertIn('f"{DOMAIN}/grocery/list"', WEBSOCKET_SOURCE)
        self.assertIn('"stores": stores', WEBSOCKET_SOURCE)
        for service in ("create_grocery_store", "rename_grocery_store", "delete_grocery_store", "set_grocery_item_stores"):
            self.assertIn(f'"{service}"', SERVICE_SOURCE)
            self.assertIn(f'{service}:', SERVICE_YAML)
        self.assertIn('"/lists/stores"', API_SOURCE)
        self.assertIn('"/lists/stores/update"', API_SOURCE)
        self.assertIn('"/lists/stores/delete"', API_SOURCE)
        self.assertIn('"updates": {"stores": normalized_ids}', API_SOURCE)
        self.assertIn('id="manage-stores"', CARD_SOURCE)
        self.assertIn('id="store-filter"', CARD_SOURCE)
        self.assertIn('id="group-by"', CARD_SOURCE)
        self.assertIn('id="sort-by"', CARD_SOURCE)
        self.assertIn('id="add-store-form"', CARD_SOURCE)
        self.assertIn('class="assignment-panel"', CARD_SOURCE)
        self.assertIn('default_group_by', CARD_SOURCE)
        self.assertIn('default_sort_by', CARD_SOURCE)
        self.assertIn('key: "default_group_by"', CARD_SOURCE)
        self.assertIn('key: "default_sort_by"', CARD_SOURCE)
        self.assertIn('name="add-store"', CARD_SOURCE)
        self.assertIn('Deleting a store removes its associations', CARD_SOURCE)

    def test_grocery_sensor_stays_small_and_store_list_is_websocket_only(self):
        grocery_sensor = SENSOR_SOURCE.split("class DeglazeGroceryListSensor", 1)[1].split(
            "class DeglazeRecipeLibrarySensor", 1
        )[0]
        self.assertNotIn('"stores":', grocery_sensor)
        self.assertIn('"stores": stores', WEBSOCKET_SOURCE)

    def test_grocery_card_defaults_to_to_buy_filter(self):
        self.assertIn('this._filter = "pending";', CARD_SOURCE)
        self.assertIn('default_filter: "pending"', CARD_SOURCE)
        self.assertIn('this._config.default_filter', CARD_SOURCE)
        self.assertIn('value="pending"', CARD_SOURCE)

    def test_weekly_meal_plan_range_handler_uses_async_websocket_response(self):
        # Home Assistant invokes websocket handlers as callbacks. Async handlers
        # must be wrapped by @async_response or the coroutine is never awaited.
        handler_block = WEBSOCKET_SOURCE.split(
            'f"{DOMAIN}/meal-plan/range"', 1
        )[1].split('def websocket_list_recipes', 1)[0]
        self.assertIn('@websocket_api.async_response\nasync def websocket_get_meal_plan_range(', handler_block)
        self.assertNotIn('RuntimeWarning', WEBSOCKET_SOURCE)
        self.assertIn('async_register_command(hass, websocket_get_meal_plan_range)', WEBSOCKET_SOURCE)

    def test_weekly_meal_planner_fetches_exact_range_and_edits_with_version(self):
        self.assertIn('f"{DOMAIN}/meal-plan/range"', WEBSOCKET_SOURCE)
        self.assertIn('async_register_command(hass, websocket_get_meal_plan_range)', WEBSOCKET_SOURCE)
        self.assertIn('type: `${this._config.domain}/meal-plan/range`', CARD_SOURCE)
        self.assertIn('"update_meal_plan_item"', SERVICE_SOURCE)
        self.assertIn('"remove_meal_plan_item"', SERVICE_SOURCE)
        self.assertIn('"/planning/update-item"', API_SOURCE)
        self.assertIn('"/planning/remove-item"', API_SOURCE)
        self.assertIn('data-action="previous-week"', CARD_SOURCE)
        self.assertIn('data-action="next-week"', CARD_SOURCE)
        self.assertIn('data-action="confirm-remove"', CARD_SOURCE)
        self.assertIn('"version": int(version)', API_SOURCE)
        self.assertIn('this._hass.callService(this._config.domain, "update_meal_plan_item"', CARD_SOURCE)

    def test_weekly_meal_planner_has_a_visual_editor_and_native_width(self):
        block = CARD_SOURCE.split("class DeglazeWeeklyMealPlannerCard extends HTMLElement", 1)[1].split("const deglazeContentLines", 1)[0]
        self.assertIn('deglaze-weekly-meal-planner-card-editor', block)
        self.assertIn("getGridOptions()", block)
        self.assertIn('customElements.define("deglaze-weekly-meal-planner-card"', CARD_SOURCE)
        self.assertIn('customElements.define("deglaze-weekly-meal-planner-card-editor"', CARD_SOURCE)

    def test_weekly_meal_planner_configures_displayed_days_but_fetches_full_week(self):
        block = CARD_SOURCE.split("class DeglazeWeeklyMealPlannerCard extends HTMLElement", 1)[1].split("const deglazeContentLines", 1)[0]
        self.assertIn('display_days: 7', block)
        self.assertIn('const displayDayCount = deglazeClampDisplayDays(this._config.display_days)', block)
        self.assertIn('const displayedDates = deglazeDisplayedDates(this._weekStart, displayDayCount)', block)
        self.assertIn('const days = displayedDates.map((date) =>', block)
        self.assertIn('const displayEnd = displayedDates[displayedDates.length - 1]', block)
        load_block = block.split('async _loadPlan()', 1)[1].split('async _moveWeek', 1)[0]
        self.assertIn('start: this._weekStart', load_block)
        self.assertIn('end: this._weekEnd', load_block)
        editor = CARD_SOURCE.split('class DeglazeWeeklyMealPlannerCardEditor extends DeglazeCardEditorBase', 1)[1].split('if (!customElements.get("deglaze-grocery-add-card-editor")', 1)[0]
        self.assertIn('key: "display_days"', editor)
        self.assertIn('min: 1, max: 7, default: 7', editor)
        self.assertIn('Displays the first 1–7 days of the selected week', editor)
        self.assertIn('static getStubConfig() { return { title: "Weekly meal planner", domain: "deglaze_poc", grid_columns: 12, refresh_interval: 120, display_days: 7 }; }', block)

    def test_weekly_meal_planner_uses_aligned_day_rows_and_meal_slot_columns(self):
        block = CARD_SOURCE.split("class DeglazeWeeklyMealPlannerCard extends HTMLElement", 1)[1].split("const deglazeContentLines", 1)[0]
        self.assertIn('const labelOptions = ["Breakfast", "Lunch", "Dinner", "Snack"]', block)
        self.assertIn('class="week-scroll"', block)
        self.assertIn('class="week-grid">${plannerCells}', block)
        self.assertIn('const plannerCells =', block)
        self.assertIn('class="week-cell day-label"', block)
        self.assertIn('class="week-cell slot-cell"', block)
        self.assertIn('grid-template-columns:minmax(88px,.72fr) repeat(${slotColumns.length},minmax(132px,1fr))', block)
        self.assertIn('overflow-x:auto', block)
        self.assertIn('Scroll horizontally to see all meal slots.', block)
        # All scheduled items remain visible even when Deglaze returns a custom label.
        self.assertIn('const hasOtherSlotItems = visibleItems.some', block)
        self.assertIn('slot === "Other"', block)

    def test_upcoming_meals_loads_directly_from_integration(self):
        self.assertIn('`${this._config.domain}/meal-plan`', CARD_SOURCE)
        self.assertIn('vol.Required("type"): f"{DOMAIN}/meal-plan"', WEBSOCKET_SOURCE)
        self.assertIn('this._hass.callWS({ type: `${this._config.domain}/meal-plan` })', CARD_SOURCE)

    def test_websocket_endpoints_expose_current_grocery_and_meal_data(self):
        self.assertIn('f"{DOMAIN}/grocery/list"', WEBSOCKET_SOURCE)
        self.assertIn('"items": compact_items', WEBSOCKET_SOURCE)
        self.assertIn('"items": items', WEBSOCKET_SOURCE)
        self.assertIn('"sync_error"', WEBSOCKET_SOURCE)

    def test_all_cards_offer_visual_editors_and_picker_defaults(self):
        for card, editor in (
            ("DeglazeGroceryAddCard", "deglaze-grocery-add-card-editor"),
            ("DeglazeUpcomingMealsCard", "deglaze-upcoming-meals-card-editor"),
            ("DeglazeRecipeLibraryCard", "deglaze-recipe-library-card-editor"),
        ):
            card_block = CARD_SOURCE.split(f"class {card}", 1)[1].split("\nclass ", 1)[0]
            self.assertIn(f'static getConfigElement() {{ return document.createElement("{editor}"); }}', card_block)
            self.assertIn("static getStubConfig()", card_block)
            self.assertIn("getGridOptions()", card_block)
        self.assertIn('"config-changed"', CARD_SOURCE)
        self.assertIn('customElements.define("deglaze-grocery-add-card-editor"', CARD_SOURCE)
        self.assertIn('customElements.define("deglaze-upcoming-meals-card-editor"', CARD_SOURCE)
        self.assertIn('customElements.define("deglaze-recipe-library-card-editor"', CARD_SOURCE)
        self.assertIn('key: "grid_columns"', CARD_SOURCE)

    def test_cards_expose_native_sections_grid_sizing(self):
        self.assertGreaterEqual(CARD_SOURCE.count("getGridOptions()"), 3)
        self.assertIn('grid_columns: 12', CARD_SOURCE)
        self.assertIn('min_columns: 6, max_columns: 12', CARD_SOURCE)
        self.assertIn('Preferred width in Sections dashboards', CARD_SOURCE)

    def test_meals_card_can_filter_meal_types(self):
        self.assertIn('key: "meal_types"', CARD_SOURCE)
        self.assertIn('selectedMealTypes.includes(deglazeMealLabel(item.label).toLocaleLowerCase())', CARD_SOURCE)

    def test_recipe_browser_uses_container_width_for_responsive_layout(self):
        self.assertIn('@container (max-width:650px)', CARD_SOURCE)

    def test_recipe_collection_membership_editor_is_wired_to_safe_service(self):
        self.assertIn('async_edit_recipe_collection_membership', API_SOURCE)
        self.assertIn('"/recipes/bulk-edit"', API_SOURCE)
        self.assertIn('"type": "bulkAddRemoveTag"', API_SOURCE)
        self.assertIn('"set_recipe_collections"', SERVICE_SOURCE)
        self.assertIn('normalize_recipe_collection_manifest', SERVICE_SOURCE)
        self.assertIn('plan_recipe_collection_changes', SERVICE_SOURCE)
        self.assertIn('async_force_recipe_refresh()', SERVICE_SOURCE)
        self.assertIn('id="save-collections"', CARD_SOURCE)
        self.assertIn('class="membership-checkbox"', CARD_SOURCE)
        self.assertIn('"set_recipe_collections"', CARD_SOURCE)
        self.assertIn('set_recipe_collections:', SERVICE_YAML)
        self.assertIn('raw_collection_ids = call.data["collection_ids"]', SERVICE_SOURCE)
        self.assertIn('if any(not isinstance(collection_id, str) or not collection_id.strip() for collection_id in raw_collection_ids):', SERVICE_SOURCE)
        self.assertIn('some changes may have been applied', SERVICE_SOURCE)
        self.assertIn('refreshed library does not yet reflect', SERVICE_SOURCE)
        manifest = __import__("json").loads((ROOT / "custom_components" / "deglaze_poc" / "manifest.json").read_text())
        self.assertEqual(manifest["version"], "1.0.0")


if __name__ == "__main__":
    unittest.main()
