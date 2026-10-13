"""Home Assistant actions for Deglaze grocery and meal-planning operations."""
from __future__ import annotations

from datetime import date
import logging
import secrets
from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .api import (
    DeglazePOCError,
    extract_grocery_items,
    extract_grocery_lists,
    extract_grocery_stores,
    extract_recipe_ingredient_choices,
    grocery_item_store_ids,
    normalize_recipe_collection_manifest,
    plan_recipe_ingredient_additions,
    plan_recipe_collection_changes,
    recipe_collection_ids,
    recipe_is_active,
    summarize_grocery_response,
)
from .const import DOMAIN
from .coordinator import DeglazePOCCoordinator


_LOGGER = logging.getLogger(__name__)

SERVICES = (
    "add_grocery_item",
    "set_grocery_item_status",
    "create_grocery_store",
    "rename_grocery_store",
    "delete_grocery_store",
    "set_grocery_item_stores",
    "add_meal_plan_item",
    "update_meal_plan_item",
    "remove_meal_plan_item",
    "set_recipe_collections",
    "refresh",
    "test_auth_renewal",
    "test_error_handling",
)


async def async_register_services(hass: HomeAssistant) -> None:
    """Register idempotent service handlers."""
    definitions = {
        "add_grocery_item": (
            _add_grocery_item,
            vol.Schema({
                vol.Required("text"): vol.All(cv.string, vol.Length(min=1, max=500)),
                vol.Optional("suggestion_id"): cv.string,
                vol.Optional("manual_category"): cv.string,
                vol.Optional("stores", default=[]): vol.All(
                    cv.ensure_list,
                    vol.Length(max=100),
                    [vol.All(cv.string, vol.Length(min=1, max=256))],
                ),
            }),
        ),
        "set_grocery_item_status": (
            _set_grocery_item_status,
            vol.Schema({
                vol.Required("item_id"): cv.string,
                vol.Required("status"): vol.In(("pending", "completed")),
            }),
        ),
        "create_grocery_store": (
            _create_grocery_store,
            vol.Schema({vol.Required("name"): vol.All(cv.string, vol.Length(min=1, max=100))}),
        ),
        "rename_grocery_store": (
            _rename_grocery_store,
            vol.Schema({
                vol.Required("store_id"): vol.All(cv.string, vol.Length(min=1, max=256)),
                vol.Required("name"): vol.All(cv.string, vol.Length(min=1, max=100)),
            }),
        ),
        "delete_grocery_store": (
            _delete_grocery_store,
            vol.Schema({vol.Required("store_id"): vol.All(cv.string, vol.Length(min=1, max=256))}),
        ),
        "set_grocery_item_stores": (
            _set_grocery_item_stores,
            vol.Schema({
                vol.Required("item_id"): vol.All(cv.string, vol.Length(min=1, max=512)),
                vol.Required("store_ids"): vol.All(
                    cv.ensure_list,
                    vol.Length(max=100),
                    [vol.All(cv.string, vol.Length(min=1, max=256))],
                ),
            }),
        ),
        "add_meal_plan_item": (
            _add_meal_plan_item,
            vol.Schema({
                vol.Required("recipe_id"): vol.All(cv.string, vol.Length(min=1, max=512)),
                vol.Required("date"): vol.Match(r"^\d{4}-\d{2}-\d{2}$"),
                vol.Required("label"): vol.In(("Breakfast", "Lunch", "Dinner", "Snack")),
                vol.Optional("is_leftovers", default=False): cv.boolean,
            }),
        ),
        "update_meal_plan_item": (
            _update_meal_plan_item,
            vol.Schema({
                vol.Required("item_id"): vol.All(cv.string, vol.Length(min=1, max=512)),
                vol.Required("item_type"): vol.In(("recipe", "note")),
                vol.Required("version"): vol.All(vol.Coerce(int), vol.Range(min=0)),
                vol.Optional("date"): vol.Match(r"^\d{4}-\d{2}-\d{2}$"),
                vol.Optional("label"): vol.In(("Breakfast", "Lunch", "Dinner", "Snack")),
                vol.Optional("is_leftovers"): cv.boolean,
            }),
        ),
        "remove_meal_plan_item": (
            _remove_meal_plan_item,
            vol.Schema({
                vol.Required("item_id"): vol.All(cv.string, vol.Length(min=1, max=512)),
            }),
        ),
        "set_recipe_collections": (
            _set_recipe_collections,
            vol.Schema({
                vol.Required("recipe_id"): vol.All(cv.string, vol.Length(min=1, max=512)),
                vol.Required("collection_ids"): vol.All(
                    cv.ensure_list,
                    vol.Length(max=100),
                    [vol.All(cv.string, vol.Length(min=1, max=256))],
                ),
            }),
        ),
        "refresh": (_refresh, vol.Schema({})),
    }
    for name, (handler, schema) in definitions.items():
        if not hass.services.has_service(DOMAIN, name):
            hass.services.async_register(DOMAIN, name, handler, schema=schema)
    if not hass.services.has_service(DOMAIN, "test_auth_renewal"):
        hass.services.async_register(
            DOMAIN,
            "test_auth_renewal",
            _test_auth_renewal,
            schema=vol.Schema({}),
            supports_response=SupportsResponse.ONLY,
        )
    if not hass.services.has_service(DOMAIN, "test_error_handling"):
        hass.services.async_register(
            DOMAIN,
            "test_error_handling",
            _test_error_handling,
            schema=vol.Schema({}),
            supports_response=SupportsResponse.ONLY,
        )


def async_remove_services(hass: HomeAssistant) -> None:
    """Remove service handlers after the last config entry unloads."""
    for name in SERVICES:
        if hass.services.has_service(DOMAIN, name):
            hass.services.async_remove(DOMAIN, name)


def _get_runtime(hass: HomeAssistant) -> dict[str, Any]:
    entries = hass.data.get(DOMAIN, {})
    for runtime in entries.values():
        if isinstance(runtime, dict) and runtime.get("client") and runtime.get("coordinator"):
            return runtime
    raise HomeAssistantError("Deglaze is not currently loaded. Reload the integration and try again.")


def _select_default_grocery_list(client: Any, payload: dict[str, Any]) -> dict[str, Any]:
    """Select the current account's grocery list without guessing across multiple lists."""
    lists = extract_grocery_lists(payload)
    if lists is None or not lists:
        raise HomeAssistantError("Deglaze did not return a recognized grocery list.")
    expected_id = client.default_grocery_list_id
    selected = next((item for item in lists if item.get("id") == expected_id), None)
    if selected is None and len(lists) == 1:
        # Some responses omit/alias the list ID; the integration is single-account and
        # Deglaze currently returns one grocery list. Multi-list responses require an
        # exact ID match to avoid changing another list.
        selected = lists[0]
    if selected is None:
        raise HomeAssistantError("Could not identify the current Deglaze grocery list safely.")
    return selected


def _stores_for_list(grocery_list: dict[str, Any]) -> list[dict[str, Any]]:
    payload = {"data": {"lists": [grocery_list]}}
    return extract_grocery_stores(payload)



async def _fresh_grocery_list(client: Any) -> dict[str, Any]:
    try:
        payload = await client.async_get_grocery_list()
    except Exception as err:
        if isinstance(err, DeglazePOCError):
            raise HomeAssistantError(str(err)) from None
        raise HomeAssistantError("Could not refresh the Deglaze grocery list before this change.") from None
    return _select_default_grocery_list(client, payload)


async def _refresh_after_grocery_mutation(coordinator: DeglazePOCCoordinator, operation: str) -> None:
    """Refresh state after writes; describe ambiguous outcome if refresh is unsuccessful."""
    try:
        await coordinator.async_request_refresh()
    except Exception:
        _LOGGER.warning("Deglaze %s was sent, but the grocery list could not be refreshed.", operation)
        raise HomeAssistantError(
            f"The {operation} request may have succeeded, but Home Assistant could not refresh the list. "
            "Refresh and verify Deglaze before retrying."
        ) from None
    if (coordinator.data or {}).get("errors", {}).get("grocery"):
        _LOGGER.warning("Deglaze %s was sent, but the grocery refresh still reports an error.", operation)
        raise HomeAssistantError(
            f"The {operation} request may have succeeded, but refreshed list data is unavailable. "
            "Refresh and verify Deglaze before retrying."
        )


async def _add_grocery_item(call: ServiceCall) -> None:
    runtime = _get_runtime(call.hass)
    client = runtime["client"]
    coordinator: DeglazePOCCoordinator = runtime["coordinator"]
    text = call.data["text"].strip()
    if not text:
        raise HomeAssistantError("Grocery item text cannot be blank.")
    item_id = "gli_" + secrets.token_urlsafe(12).replace("-", "_")
    selected_stores = list(dict.fromkeys(call.data.get("stores", [])))
    if selected_stores:
        current_list = await _fresh_grocery_list(client)
        known_store_ids = {store["id"] for store in _stores_for_list(current_list)}
        if set(selected_stores) - known_store_ids:
            raise HomeAssistantError("One or more selected stores are no longer available. Refresh the card and try again.")
    try:
        await client.async_add_grocery_item(
            text,
            item_id=item_id,
            suggestion_id=call.data.get("suggestion_id"),
            manual_category=call.data.get("manual_category"),
            stores=selected_stores,
        )
        await _refresh_after_grocery_mutation(coordinator, "grocery-item addition")
    except HomeAssistantError:
        raise
    except (DeglazePOCError, ValueError) as err:
        raise HomeAssistantError(str(err)) from err


async def add_recipe_ingredients_from_selection(
    client: Any,
    coordinator: DeglazePOCCoordinator,
    recipe_id: str,
    ingredient_ids: list[str],
    store_ids: list[str],
    include_duplicates: bool = False,
) -> dict[str, Any]:
    """Add chosen canonical ingredient lines with duplicate re-check and verification.

    Ingredient IDs are resolved against the synchronized recipe cache, so callers
    cannot submit arbitrary ingredient text. Existing-list duplicate checks are
    repeated server-side immediately before writes. The function deliberately adds
    each item separately because the observed Deglaze API exposes a single-item
    add request, then performs one coordinator refresh and verifies new IDs.
    """
    from homeassistant.exceptions import HomeAssistantError

    data = coordinator.data or {}
    recipe = (data.get("recipes") or {}).get(recipe_id)
    if not isinstance(recipe, dict) or not recipe_is_active(recipe):
        raise HomeAssistantError("That recipe is not available in the active synchronized library.")

    choices = extract_recipe_ingredient_choices(recipe.get("ingredients"))
    selected_stores = list(dict.fromkeys(store_ids))

    try:
        grocery_payload = await client.async_get_grocery_list()
    except Exception as err:
        if isinstance(err, DeglazePOCError):
            raise HomeAssistantError(str(err)) from None
        raise HomeAssistantError("Could not read the grocery list before adding recipe ingredients.") from None
    grocery_list = _select_default_grocery_list(client, grocery_payload)
    current_items = grocery_list.get("items")
    if not isinstance(current_items, list):
        raise HomeAssistantError("Deglaze returned an unrecognized grocery item list. No ingredients were added.")
    known_store_ids = {store["id"] for store in _stores_for_list(grocery_list)}
    if set(selected_stores) - known_store_ids:
        raise HomeAssistantError("One or more selected stores are no longer available. Refresh and try again.")

    try:
        addition_plan = plan_recipe_ingredient_additions(
            choices, ingredient_ids, current_items, include_duplicates
        )
    except ValueError as err:
        raise HomeAssistantError(str(err)) from None
    duplicates = addition_plan["duplicates"]
    candidates = addition_plan["candidates"]

    if not candidates:
        return {
            "status": "skipped",
            "added_count": 0,
            "skipped_duplicate_count": len(duplicates),
            "skipped_duplicates": duplicates,
            "read_only": True,
            "message": "All selected ingredients already appear on the grocery list, so nothing was added. Choose Add anyway to include them.",
        }

    attempted: list[dict[str, str]] = []
    request_error = ""
    for choice in candidates:
        item_id = "gli_" + secrets.token_urlsafe(12).replace("-", "_")
        attempted.append({"id": item_id, "text": choice["text"]})
        try:
            await client.async_add_grocery_item(
                choice["text"], item_id=item_id, stores=selected_stores,
            )
        except Exception as err:
            request_error = str(err)[:180] if isinstance(err, DeglazePOCError) else "A grocery item request failed or timed out."
            _LOGGER.warning("Adding recipe ingredients stopped after an API error; response bodies were not logged.")
            break

    refresh_error = False
    try:
        await coordinator.async_request_refresh()
        if (coordinator.data or {}).get("errors", {}).get("grocery"):
            refresh_error = True
    except Exception:
        refresh_error = True

    refreshed_grocery = ((coordinator.data or {}).get("grocery") or {})
    refreshed_items = refreshed_grocery.get("items")
    if not isinstance(refreshed_items, list):
        refreshed_items = []
        refresh_error = True
    refreshed_by_id: dict[str, dict[str, Any]] = {}
    for item in refreshed_items:
        if not isinstance(item, dict):
            continue
        item_key = item.get("id") or item.get("itemId")
        if isinstance(item_key, str) and item_key:
            refreshed_by_id[item_key] = item

    present = [item for item in attempted if item["id"] in refreshed_by_id]
    missing = [item for item in attempted if item["id"] not in refreshed_by_id]
    store_assignment_mismatches = [
        item for item in present
        if selected_stores and not set(selected_stores).issubset(
            set(grocery_item_store_ids(refreshed_by_id[item["id"]]))
        )
    ]
    # An ingredient is counted as added if it exists after the refresh. Full
    # success additionally requires the chosen store assignment to be visible.
    all_candidates_attempted = len(attempted) == len(candidates)
    stores_verified = not selected_stores or not store_assignment_mismatches
    complete = (
        not request_error and not refresh_error and not missing
        and stores_verified and all_candidates_attempted
    )
    result: dict[str, Any] = {
        "status": "passed" if complete else ("partial" if present or attempted else "failed"),
        "added_count": len(present),
        "verified_count": len(present) - len(store_assignment_mismatches),
        "attempted_count": len(attempted),
        "skipped_duplicate_count": len(duplicates) if not include_duplicates else 0,
        "skipped_duplicates": duplicates if not include_duplicates else [],
        "store_ids": selected_stores,
        "store_assignment_verified": stores_verified,
        "read_only": False,
    }
    if complete:
        result["message"] = f"Added and verified {len(present)} ingredient(s) from {recipe.get('title') or 'the selected recipe'}."
        if selected_stores:
            result["message"] += " Store assignment was also verified."
        if duplicates and not include_duplicates:
            result["message"] += f" Skipped {len(duplicates)} possible duplicate(s)."
    else:
        result["message"] = (
            f"Found {len(present)} of {len(candidates)} requested ingredient addition(s) after refresh. "
            "Some requests or store assignments may not have completed as expected. "
            "Refresh and compare the grocery list with Deglaze before retrying."
        )
        if store_assignment_mismatches:
            result["store_assignment_warning"] = (
                f"Store assignment could not be verified for {len(store_assignment_mismatches)} added item(s)."
            )
        if missing:
            result["missing_count"] = len(missing)
        if request_error:
            result["error"] = request_error
        if refresh_error:
            result["refresh_warning"] = "The grocery list refresh did not complete cleanly."
    return result


async def _set_grocery_item_status(call: ServiceCall) -> None:
    runtime = _get_runtime(call.hass)
    client = runtime["client"]
    coordinator: DeglazePOCCoordinator = runtime["coordinator"]
    item_id = call.data["item_id"]
    status = call.data["status"]
    try:
        # Get a fresh list before PATCH so the optimistic/concurrency version is current.
        payload = await client.async_get_grocery_list()
        matches = [item for item in extract_grocery_items(payload) if item.get("id") == item_id]
        if not matches:
            raise HomeAssistantError("That grocery item was not found in the current list.")
        item = matches[0]
        version = item.get("version")
        if version is None:
            raise HomeAssistantError("Deglaze did not return a version for that grocery item.")
        list_id = item.get("listId") or client.default_grocery_list_id
        await client.async_set_grocery_item_status(item_id, int(version), status, list_id)
        await _refresh_after_grocery_mutation(coordinator, "grocery-item status update")
    except HomeAssistantError:
        raise
    except (DeglazePOCError, ValueError, TypeError) as err:
        raise HomeAssistantError(str(err)) from err


async def _create_grocery_store(call: ServiceCall) -> None:
    """Create a store and verify it is present after refreshing the grocery list."""
    runtime = _get_runtime(call.hass)
    client = runtime["client"]
    coordinator: DeglazePOCCoordinator = runtime["coordinator"]
    name = call.data["name"].strip()
    if not name:
        raise HomeAssistantError("Store name cannot be blank.")
    grocery_list = await _fresh_grocery_list(client)
    stores = _stores_for_list(grocery_list)
    if any(store["name"].casefold() == name.casefold() for store in stores):
        raise HomeAssistantError("A store with that name already exists.")
    store_id = "store-" + secrets.token_urlsafe(12).replace("-", "_")
    try:
        await client.async_create_grocery_store(name, store_id=store_id)
    except (DeglazePOCError, ValueError) as err:
        raise HomeAssistantError(str(err)) from None
    await _refresh_after_grocery_mutation(coordinator, "store creation")
    stores_after = extract_grocery_stores({"data": {"lists": (coordinator.data or {}).get("grocery", {}).get("lists", [])}})
    if not any(store["id"] == store_id and store["name"] == name for store in stores_after):
        raise HomeAssistantError("Deglaze received the store creation request, but the refreshed list does not show it. Verify Deglaze before retrying.")


async def _rename_grocery_store(call: ServiceCall) -> None:
    """Rename a store with its fresh concurrency version and verify the result."""
    runtime = _get_runtime(call.hass)
    client = runtime["client"]
    coordinator: DeglazePOCCoordinator = runtime["coordinator"]
    store_id = call.data["store_id"].strip()
    name = call.data["name"].strip()
    if not store_id or not name:
        raise HomeAssistantError("Store ID and name are required.")
    grocery_list = await _fresh_grocery_list(client)
    stores = _stores_for_list(grocery_list)
    store = next((candidate for candidate in stores if candidate["id"] == store_id), None)
    if store is None:
        raise HomeAssistantError("That store no longer exists. Refresh the grocery card.")
    if store["name"] == name:
        return
    if any(candidate["id"] != store_id and candidate["name"].casefold() == name.casefold() for candidate in stores):
        raise HomeAssistantError("Another store already uses that name.")
    version = store.get("version")
    if version is None:
        raise HomeAssistantError("Deglaze did not return the store version required to rename it safely.")
    try:
        await client.async_update_grocery_store(store_id, name, int(version))
    except (DeglazePOCError, ValueError, TypeError) as err:
        raise HomeAssistantError(str(err)) from None
    await _refresh_after_grocery_mutation(coordinator, "store rename")
    stores_after = extract_grocery_stores({"data": {"lists": (coordinator.data or {}).get("grocery", {}).get("lists", [])}})
    renamed = next((candidate for candidate in stores_after if candidate["id"] == store_id), None)
    if renamed is None or renamed["name"] != name:
        raise HomeAssistantError("The rename request may have succeeded, but the refreshed list does not confirm it. Verify Deglaze before retrying.")


async def _delete_grocery_store(call: ServiceCall) -> None:
    """Delete a store definition; Deglaze removes associations but keeps grocery items."""
    runtime = _get_runtime(call.hass)
    client = runtime["client"]
    coordinator: DeglazePOCCoordinator = runtime["coordinator"]
    store_id = call.data["store_id"].strip()
    if not store_id:
        raise HomeAssistantError("Store ID cannot be blank.")
    grocery_list = await _fresh_grocery_list(client)
    store = next((candidate for candidate in _stores_for_list(grocery_list) if candidate["id"] == store_id), None)
    if store is None:
        raise HomeAssistantError("That store no longer exists. Refresh the grocery card.")
    try:
        await client.async_delete_grocery_store(store_id)
    except (DeglazePOCError, ValueError) as err:
        raise HomeAssistantError(str(err)) from None
    await _refresh_after_grocery_mutation(coordinator, "store deletion")
    stores_after = extract_grocery_stores({"data": {"lists": (coordinator.data or {}).get("grocery", {}).get("lists", [])}})
    if any(candidate["id"] == store_id for candidate in stores_after):
        raise HomeAssistantError("Deglaze received the delete request, but the store remains in the refreshed list. Verify Deglaze before retrying.")


async def _set_grocery_item_stores(call: ServiceCall) -> None:
    """Set an item's store assignments, using fresh item version and verified store IDs."""
    runtime = _get_runtime(call.hass)
    client = runtime["client"]
    coordinator: DeglazePOCCoordinator = runtime["coordinator"]
    item_id = call.data["item_id"].strip()
    desired_ids = list(dict.fromkeys(item_id.strip() for item_id in call.data["store_ids"] if isinstance(item_id, str) and item_id.strip()))
    if not item_id:
        raise HomeAssistantError("Grocery item ID cannot be blank.")
    try:
        payload = await client.async_get_grocery_list()
    except Exception as err:
        if isinstance(err, DeglazePOCError):
            raise HomeAssistantError(str(err)) from None
        raise HomeAssistantError("Could not refresh the Deglaze grocery list before changing stores.") from None
    grocery_list = _select_default_grocery_list(client, payload)
    known_store_ids = {store["id"] for store in _stores_for_list(grocery_list)}
    if set(desired_ids) - known_store_ids:
        raise HomeAssistantError("One or more selected stores no longer exist. Refresh the card and try again.")
    items = extract_grocery_items(payload)
    matches = [item for item in items if item.get("id") == item_id]
    if not matches:
        raise HomeAssistantError("That grocery item was not found in the current list.")
    item = matches[0]
    version = item.get("version")
    if version is None:
        raise HomeAssistantError("Deglaze did not return a version for this grocery item.")
    current_ids = set(grocery_item_store_ids(item))
    if current_ids == set(desired_ids):
        return
    list_id = item.get("listId") or grocery_list.get("id") or client.default_grocery_list_id
    try:
        await client.async_set_grocery_item_stores(item_id, int(version), desired_ids, list_id)
    except (DeglazePOCError, ValueError, TypeError) as err:
        raise HomeAssistantError(str(err)) from None
    await _refresh_after_grocery_mutation(coordinator, "grocery item store assignment")
    items_after = (coordinator.data or {}).get("grocery", {}).get("items", [])
    refreshed_item = next((candidate for candidate in items_after if candidate.get("id") == item_id), None)
    if not isinstance(refreshed_item, dict) or set(grocery_item_store_ids(refreshed_item)) != set(desired_ids):
        raise HomeAssistantError("The store assignment request may have succeeded, but the refreshed item does not confirm it. Verify Deglaze before retrying.")


async def _add_meal_plan_item(call: ServiceCall) -> None:
    runtime = _get_runtime(call.hass)
    client = runtime["client"]
    coordinator: DeglazePOCCoordinator = runtime["coordinator"]
    recipe_id = call.data["recipe_id"].strip()
    meal_date = call.data["date"]
    try:
        # Validate the calendar date, not just its YYYY-MM-DD shape.
        date.fromisoformat(meal_date)
    except ValueError as err:
        raise HomeAssistantError("Enter a valid date in YYYY-MM-DD format.") from err
    if not recipe_id:
        raise HomeAssistantError("Recipe ID cannot be blank.")
    plan_item_id = "j-" + secrets.token_urlsafe(10)
    try:
        await client.async_add_meal_plan_item(
            recipe_id=recipe_id,
            date=meal_date,
            label=call.data["label"],
            is_leftovers=call.data.get("is_leftovers", False),
            plan_item_id=plan_item_id,
        )
        coordinator.async_force_meal_plan_refresh()
        await coordinator.async_request_refresh()
    except (DeglazePOCError, ValueError) as err:
        raise HomeAssistantError(str(err)) from err


async def _update_meal_plan_item(call: ServiceCall) -> None:
    """Update a planned item's supported fields with its current version."""
    runtime = _get_runtime(call.hass)
    client = runtime["client"]
    coordinator: DeglazePOCCoordinator = runtime["coordinator"]
    item_id = call.data["item_id"].strip()
    item_type = call.data["item_type"]
    updates: dict[str, Any] = {}

    if "date" in call.data:
        try:
            date.fromisoformat(call.data["date"])
        except ValueError as err:
            raise HomeAssistantError("Enter a valid date in YYYY-MM-DD format.") from err
        updates["date"] = call.data["date"]
    if "label" in call.data:
        updates["label"] = {"type": "system", "label": call.data["label"]}
    if "is_leftovers" in call.data:
        updates["isLeftovers"] = bool(call.data["is_leftovers"])
    if not item_id or not updates:
        raise HomeAssistantError("Provide a planned item and at least one field to change.")

    try:
        await client.async_update_meal_plan_item(
            item_id=item_id,
            item_type=item_type,
            version=int(call.data["version"]),
            updates=updates,
        )
    except (DeglazePOCError, ValueError, TypeError) as err:
        raise HomeAssistantError(str(err)) from err

    # The currently displayed week may be outside the coordinator's rolling window.
    # Refresh the standard entities best-effort; the weekly card re-queries its exact range.
    coordinator.async_force_meal_plan_refresh()
    try:
        await coordinator.async_request_refresh()
    except Exception:
        _LOGGER.warning("A Deglaze meal-plan edit succeeded, but summary refresh failed.")


async def _remove_meal_plan_item(call: ServiceCall) -> None:
    """Remove one planned item after explicit user confirmation in the card."""
    runtime = _get_runtime(call.hass)
    client = runtime["client"]
    coordinator: DeglazePOCCoordinator = runtime["coordinator"]
    item_id = call.data["item_id"].strip()
    if not item_id:
        raise HomeAssistantError("Meal-plan item ID cannot be blank.")
    try:
        await client.async_remove_meal_plan_item(item_id)
    except (DeglazePOCError, ValueError, TypeError) as err:
        raise HomeAssistantError(str(err)) from err

    coordinator.async_force_meal_plan_refresh()
    try:
        await coordinator.async_request_refresh()
    except Exception:
        _LOGGER.warning("A Deglaze meal-plan removal succeeded, but summary refresh failed.")


async def _set_recipe_collections(call: ServiceCall) -> None:
    """Set a recipe's memberships in visible existing user/system tag collections."""
    runtime = _get_runtime(call.hass)
    client = runtime["client"]
    coordinator: DeglazePOCCoordinator = runtime["coordinator"]
    recipe_id = call.data["recipe_id"].strip()
    raw_collection_ids = call.data["collection_ids"]
    if any(not isinstance(collection_id, str) or not collection_id.strip() for collection_id in raw_collection_ids):
        raise HomeAssistantError("Collection IDs must be non-empty strings.")
    desired_ids = {collection_id.strip() for collection_id in raw_collection_ids}
    data = coordinator.data or {}
    recipe = (data.get("recipes") or {}).get(recipe_id)
    if not isinstance(recipe, dict) or not recipe_is_active(recipe):
        raise HomeAssistantError("That recipe is not available in the active synchronized library.")

    recipe_meta = data.get("recipe_meta") or {}
    collections = normalize_recipe_collection_manifest(recipe_meta.get("collections"))
    visible_collection_ids = {item["id"] for item in collections}
    if desired_ids - visible_collection_ids:
        raise HomeAssistantError(
            "One or more selected collections are not available. Refresh the recipe library and try again."
        )

    current_ids = set(recipe_collection_ids(recipe, collections))
    changes = plan_recipe_collection_changes(current_ids, desired_ids)
    if not changes:
        return

    attempted = 0
    applied = 0
    failure: Exception | None = None
    for change in changes:
        try:
            # A timeout can happen after the server applied a mutation, so count the
            # request as attempted before awaiting it and refresh even on first failure.
            attempted += 1
            await client.async_edit_recipe_collection_membership(
                recipe_id=recipe_id,
                collection_id=change["collection_id"],
                action=change["action"],
            )
            applied += 1
        except Exception as err:  # Avoid surfacing arbitrary exception text in the UI.
            failure = err
            break

    # Always refresh after at least one remote mutation, including partial failure.
    if attempted:
        coordinator.async_force_recipe_refresh()
        try:
            await coordinator.async_request_refresh()
        except Exception:
            _LOGGER.warning(
                "Deglaze collection edit was sent, but Home Assistant could not refresh the recipe cache."
            )

    if failure is not None:
        _LOGGER.warning(
            "Deglaze recipe collection update failed after %s of %s membership operations.",
            applied, len(changes),
        )
        if attempted:
            raise HomeAssistantError(
                "The collection update did not complete cleanly; some changes may have been applied. "
                "The recipe library was refreshed where possible. Review the recipe's memberships before retrying."
            ) from None
        if isinstance(failure, DeglazePOCError):
            raise HomeAssistantError(str(failure)) from None
        raise HomeAssistantError(
            "Could not update recipe collections. Check Home Assistant logs for the safe error summary."
        ) from None

    # Only report success when the synchronized data reflects the requested visible memberships.
    refreshed_data = coordinator.data or {}
    refreshed_recipe = (refreshed_data.get("recipes") or {}).get(recipe_id)
    refreshed_meta = refreshed_data.get("recipe_meta") or {}
    refreshed_collections = normalize_recipe_collection_manifest(refreshed_meta.get("collections"))
    if not isinstance(refreshed_recipe, dict):
        raise HomeAssistantError(
            "Deglaze accepted the collection update, but the recipe was unavailable after refresh. "
            "Verify the membership on Deglaze before retrying."
        )
    actual_ids = set(recipe_collection_ids(refreshed_recipe, refreshed_collections))
    actual_visible_ids = actual_ids & visible_collection_ids
    if actual_visible_ids != desired_ids:
        raise HomeAssistantError(
            "Deglaze accepted the collection update, but the refreshed library does not yet reflect "
            "all changes. Refresh the recipe library and verify the memberships on Deglaze."
        )


async def _refresh(call: ServiceCall) -> None:
    runtime = _get_runtime(call.hass)
    coordinator: DeglazePOCCoordinator = runtime["coordinator"]
    coordinator.async_force_refresh_all()
    await coordinator.async_request_refresh()


async def _test_auth_renewal(call: ServiceCall) -> dict[str, Any]:
    """Force the ordinary expiry refresh path and verify a harmless Deglaze read."""
    runtime = _get_runtime(call.hass)
    client = runtime["client"]
    try:
        payload = await client.async_test_auth_renewal()
    except Exception as err:
        # Do not include arbitrary HTTP exception text here: transport exceptions
        # can contain request URLs. The client intentionally avoids logging tokens.
        failure_class = type(err).__name__
        # API-client exceptions use deliberately sanitized messages (status/path or
        # Firebase error code). Other exception text may include request URLs, so
        # for those log only the exception class.
        safe_detail = str(err)[:180] if isinstance(err, DeglazePOCError) else failure_class
        _LOGGER.warning(
            "Manual Deglaze authentication renewal test failed (%s): %s. Credentials were not logged.",
            failure_class,
            safe_detail,
        )
        raise HomeAssistantError(
            "Deglaze authentication renewal test failed. Check Settings → System → Logs "
            "for the safe failure summary; no access tokens or refresh tokens were logged."
        ) from None

    summary = summarize_grocery_response(payload)
    schema_recognized = summary.get("schema_recognized") is True
    result: dict[str, Any] = {
        "status": "passed" if schema_recognized else "partial",
        "authentication_refresh": "passed",
        "deglaze_read_request": "passed",
        "grocery_response_schema": "recognized" if schema_recognized else "unrecognized",
        "schema_recognized": schema_recognized,
        "list_count": summary.get("list_count"),
        "item_count": summary.get("item_count"),
        "pending_count": summary.get("pending_count"),
        "completed_count": summary.get("completed_count"),
        "read_only": True,
        "message": (
            "The integration forced its normal access-token renewal path, then successfully "
            "read the Deglaze grocery list. No grocery items were changed."
            if schema_recognized else
            "Token renewal and the read-only request succeeded, but the grocery response "
            "shape was not recognized. Authentication passed; review the integration version."
        ),
    }
    _LOGGER.info(
        "Manual Deglaze authentication renewal test passed: token refresh and GET /lists succeeded; "
        "grocery schema recognized=%s, lists=%s, items=%s, pending=%s, completed=%s. "
        "No credentials or item names were logged.",
        schema_recognized,
        summary.get("list_count"),
        summary.get("item_count"),
        summary.get("pending_count"),
        summary.get("completed_count"),
    )
    return result


async def _test_error_handling(call: ServiceCall) -> dict[str, Any]:
    """Simulate one local HTTP 503, then verify a real read-only recovery request."""
    runtime = _get_runtime(call.hass)
    client = runtime["client"]
    try:
        payload, diagnostics = await client.async_test_error_handling()
    except Exception as err:
        failure_class = type(err).__name__
        safe_detail = str(err)[:180] if isinstance(err, DeglazePOCError) else failure_class
        _LOGGER.warning(
            "Deglaze error-handling diagnostic failed (%s): %s. Credentials and response bodies were not logged.",
            failure_class,
            safe_detail,
        )
        raise HomeAssistantError(
            "Deglaze error-handling diagnostic failed. Check Settings → System → Logs "
            "for the safe failure summary; credentials and response bodies were not logged."
        ) from None

    summary = summarize_grocery_response(payload)
    schema_recognized = summary.get("schema_recognized") is True
    result: dict[str, Any] = {
        **diagnostics,
        "status": "passed" if schema_recognized else "partial",
        "grocery_response_schema": "recognized" if schema_recognized else "unrecognized",
        "schema_recognized": schema_recognized,
        "list_count": summary.get("list_count"),
        "item_count": summary.get("item_count"),
        "pending_count": summary.get("pending_count"),
        "completed_count": summary.get("completed_count"),
        "message": (
            "A local synthetic HTTP 503 was handled by the normal API error path without exposing its body. "
            "A subsequent real, read-only GET /lists succeeded. No failure was sent to Deglaze and no list items were changed."
            if schema_recognized else
            "The synthetic failure was handled safely and the read-only recovery request succeeded, but the grocery response shape was not recognized."
        ),
    }
    _LOGGER.info(
        "Deglaze error-handling diagnostic: local synthetic HTTP 503 handled safely; "
        "real GET /lists recovery succeeded; grocery schema recognized=%s, lists=%s, items=%s. "
        "No credentials, response bodies, or item names were logged.",
        schema_recognized,
        summary.get("list_count"),
        summary.get("item_count"),
    )
    return result

