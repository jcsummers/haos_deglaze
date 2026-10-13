"""Authenticated WebSocket data endpoints for Deglaze Lovelace cards."""
from __future__ import annotations

from datetime import date
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from .api import (
    DeglazePOCError,
    extract_recipe_ingredient_choices,
    normalize_recipe_collection_manifest,
    recipe_collection_ids,
    recipe_is_active,
)
from .const import DOMAIN
from .services import add_recipe_ingredients_from_selection


def _runtime(hass: HomeAssistant) -> dict[str, Any] | None:
    for runtime in hass.data.get(DOMAIN, {}).values():
        if isinstance(runtime, dict) and runtime.get("coordinator") and runtime.get("client"):
            return runtime
    return None


def _summary(
    recipe_id: str,
    recipe: dict[str, Any],
    collections: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return compact metadata; full ingredients load only when a recipe is selected."""
    result: dict[str, Any] = {
        "recipe_id": recipe_id,
        "title": recipe.get("title") or "Untitled recipe",
    }
    for key in ("time", "recipeYield", "type", "version"):
        value = recipe.get(key)
        if isinstance(value, (str, int, float, bool)):
            result[key] = value
    source = recipe.get("source")
    if isinstance(source, str):
        result["source"] = source[:300]
    collection_ids = recipe_collection_ids(recipe, collections)
    collection_names = {
        collection["id"]: collection["name"]
        for collection in collections
        if isinstance(collection.get("id"), str) and isinstance(collection.get("name"), str)
    }
    result["collection_ids"] = collection_ids
    result["collection_names"] = [collection_names[item] for item in collection_ids if item in collection_names]
    return result


def _item_status(item: dict[str, Any]) -> str:
    value = item.get("status")
    if isinstance(value, dict):
        value = value.get("status")
    return value.lower() if isinstance(value, str) else "pending"


def _compact_grocery_item(item: dict[str, Any]) -> dict[str, Any]:
    """Return only the fields needed for list display/actions."""
    keys = (
        "id", "text", "type", "status", "category", "version", "listId",
        "stores", "created", "suggestionId", "manualCategory", "ingredient",
        "textGroupKey",
    )
    compact = {key: item[key] for key in keys if key in item}
    compact["status_text"] = _item_status(item)
    return compact


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/grocery/list"}
)
@callback
def websocket_get_grocery_list(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return grocery items from the last successful coordinator refresh."""
    runtime = _runtime(hass)
    if runtime is None:
        connection.send_error(msg["id"], "not_found", "Deglaze integration is not loaded.")
        return
    data = runtime["coordinator"].data or {}
    grocery = data.get("grocery") or {}
    items = grocery.get("items")
    if not isinstance(items, list):
        connection.send_error(msg["id"], "not_found", "Grocery data is not available yet.")
        return
    compact_items = [_compact_grocery_item(item) for item in items if isinstance(item, dict)]
    lists = grocery.get("lists") if isinstance(grocery.get("lists"), list) else []
    expected_list_id = runtime["client"].default_grocery_list_id
    selected_list = next((item for item in lists if isinstance(item, dict) and item.get("id") == expected_list_id), None)
    if selected_list is None and len(lists) == 1 and isinstance(lists[0], dict):
        selected_list = lists[0]
    stores: list[dict[str, Any]] = []
    if isinstance(selected_list, dict) and isinstance(selected_list.get("stores"), list):
        seen_store_ids: set[str] = set()
        for store in selected_list["stores"]:
            if not isinstance(store, dict):
                continue
            store_id, name = store.get("id"), store.get("name")
            if not isinstance(store_id, str) or not store_id or not isinstance(name, str) or not name.strip() or store_id in seen_store_ids:
                continue
            seen_store_ids.add(store_id)
            compact_store = {"id": store_id, "name": name.strip()}
            version = store.get("version")
            if isinstance(version, int) and version >= 0:
                compact_store["version"] = version
            stores.append(compact_store)
    stores.sort(key=lambda store: store["name"].casefold())
    counts = {
        "item_count": len(compact_items),
        "pending_count": sum(item["status_text"] == "pending" for item in compact_items),
        "completed_count": sum(item["status_text"] == "completed" for item in compact_items),
    }
    connection.send_result(
        msg["id"],
        {
            "items": compact_items,
            "stores": stores,
            "counts": counts,
            "list_count": (grocery.get("summary") or {}).get("list_count"),
            "last_updated": grocery.get("last_updated"),
            "sync_error": (data.get("errors") or {}).get("grocery"),
        },
    )


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/meal-plan"}
)
@callback
def websocket_get_meal_plan(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return planned meals from coordinator data, independent of entity ID naming."""
    runtime = _runtime(hass)
    if runtime is None:
        connection.send_error(msg["id"], "not_found", "Deglaze integration is not loaded.")
        return
    data = runtime["coordinator"].data or {}
    meal_plan = data.get("meal_plan") or {}
    raw_items = meal_plan.get("items")
    if not isinstance(raw_items, list):
        connection.send_error(msg["id"], "not_found", "Meal-plan data is not available yet.")
        return
    recipe_map = data.get("recipes") or {}
    items: list[dict[str, Any]] = []
    for item in raw_items:
        if not isinstance(item, dict) or item.get("deleted") is True:
            continue
        summary = {
            key: item[key]
            for key in ("id", "type", "date", "recipeId", "label", "isLeftovers", "version")
            if key in item
        }
        recipe = recipe_map.get(item.get("recipeId"), {})
        if isinstance(recipe, dict) and recipe.get("title"):
            summary["recipe_title"] = recipe["title"]
        items.append(summary)
    connection.send_result(
        msg["id"],
        {
            "items": items,
            "start": meal_plan.get("start"),
            "end": meal_plan.get("end"),
            "last_synced": meal_plan.get("last_synced"),
            "sync_error": (data.get("errors") or {}).get("meal_plan"),
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/meal-plan/range",
        vol.Required("start"): vol.Match(r"^\d{4}-\d{2}-\d{2}$"),
        vol.Required("end"): vol.Match(r"^\d{4}-\d{2}-\d{2}$"),
    }
)
@websocket_api.async_response
async def websocket_get_meal_plan_range(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Fetch a specific meal-plan range for the weekly planner without writing data."""
    runtime = _runtime(hass)
    if runtime is None:
        connection.send_error(msg["id"], "not_found", "Deglaze integration is not loaded.")
        return
    try:
        start = date.fromisoformat(msg["start"])
        end = date.fromisoformat(msg["end"])
        if end < start:
            connection.send_error(msg["id"], "invalid_format", "The end date must not be before the start date.")
            return
        if (end - start).days > 13:
            connection.send_error(msg["id"], "invalid_format", "Meal-plan range cannot exceed 14 days.")
            return
        payload = await runtime["client"].async_get_meal_plan(start.isoformat(), end.isoformat())
        meal_data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(meal_data, dict) or not isinstance(meal_data.get("items"), list):
            connection.send_error(msg["id"], "unknown_error", "Deglaze returned an unrecognized meal-plan response.")
            return
        data = runtime["coordinator"].data or {}
        recipe_map = data.get("recipes") or {}
        items: list[dict[str, Any]] = []
        for item in meal_data["items"]:
            if not isinstance(item, dict) or item.get("deleted") is True:
                continue
            summary = {
                key: item[key]
                for key in ("id", "type", "date", "recipeId", "label", "isLeftovers", "version")
                if key in item
            }
            recipe = recipe_map.get(item.get("recipeId"), {})
            if isinstance(recipe, dict) and recipe.get("title"):
                summary["recipe_title"] = recipe["title"]
            items.append(summary)
        connection.send_result(
            msg["id"],
            {
                "items": items,
                "start": meal_data.get("start", start.isoformat()),
                "end": meal_data.get("end", end.isoformat()),
                "last_synced": dt_util.utcnow().isoformat(),
                "sync_error": None,
            },
        )
    except (ValueError, TypeError):
        connection.send_error(msg["id"], "invalid_format", "Use valid ISO dates in YYYY-MM-DD format.")
    except Exception as err:
        detail = str(err)[:180] if isinstance(err, DeglazePOCError) else "The meal-plan range could not be loaded."
        connection.send_error(msg["id"], "unknown_error", detail)


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/recipes/list"}
)
@callback
def websocket_list_recipes(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return active recipe metadata from the coordinator cache."""
    runtime = _runtime(hass)
    if runtime is None:
        connection.send_error(msg["id"], "not_found", "Deglaze integration is not loaded.")
        return
    data = runtime["coordinator"].data or {}
    recipes = data.get("recipes", {})
    meta = data.get("recipe_meta", {})
    collections = normalize_recipe_collection_manifest(meta.get("collections"))
    summaries = [
        _summary(recipe_id, recipe, collections)
        for recipe_id, recipe in recipes.items()
        if isinstance(recipe_id, str) and isinstance(recipe, dict) and recipe_is_active(recipe)
    ]
    summaries.sort(key=lambda recipe: str(recipe.get("title", "")).casefold())
    public_collections = [
        {key: collection[key] for key in ("id", "name", "tag_type", "source", "display_if_empty")}
        for collection in collections
    ]
    connection.send_result(
        msg["id"],
        {
            "recipes": summaries,
            "collections": public_collections,
            "version": meta.get("version"),
            "last_synced": meta.get("last_synced"),
            "sync_error": (data.get("errors") or {}).get("recipes"),
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/recipe",
        vol.Required("recipe_id"): vol.All(str, vol.Length(min=1, max=512)),
    }
)
@callback
def websocket_get_recipe(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return one full recipe from the synchronized cache, without recording a view."""
    runtime = _runtime(hass)
    if runtime is None:
        connection.send_error(msg["id"], "not_found", "Deglaze integration is not loaded.")
        return
    data = runtime["coordinator"].data or {}
    recipe = (data.get("recipes") or {}).get(msg["recipe_id"])
    if not isinstance(recipe, dict) or recipe.get("deleted") is True:
        connection.send_error(msg["id"], "not_found", "Recipe was not found in the synchronized library.")
        return
    details = {
        key: recipe[key]
        for key in (
            "id", "title", "description", "ingredients", "instructions", "source",
            "photo", "time", "recipeYield", "author", "publisher", "tags", "version",
        )
        if key in recipe
    }
    details["ingredients_for_grocery"] = extract_recipe_ingredient_choices(recipe.get("ingredients"))
    connection.send_result(msg["id"], {"recipe": details})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/recipe/add-ingredients",
        vol.Required("recipe_id"): vol.All(str, vol.Length(min=1, max=512)),
        vol.Required("ingredient_ids"): vol.All(
            list, vol.Length(min=1, max=300),
            [vol.All(str, vol.Length(min=1, max=512))],
        ),
        vol.Optional("store_ids", default=[]): vol.All(
            list, vol.Length(max=100),
            [vol.All(str, vol.Length(min=1, max=256))],
        ),
        vol.Optional("include_duplicates", default=False): bool,
    }
)
@websocket_api.async_response
async def websocket_add_recipe_ingredients(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Add selected ingredients from a cached recipe to the grocery list."""
    runtime = _runtime(hass)
    if runtime is None:
        connection.send_error(msg["id"], "not_found", "Deglaze integration is not loaded.")
        return
    try:
        result = await add_recipe_ingredients_from_selection(
            runtime["client"],
            runtime["coordinator"],
            msg["recipe_id"],
            msg["ingredient_ids"],
            msg.get("store_ids", []),
            msg.get("include_duplicates", False),
        )
        connection.send_result(msg["id"], result)
    except Exception as err:
        detail = str(err)[:220] if isinstance(err, (DeglazePOCError, HomeAssistantError, ValueError)) else "The selected recipe ingredients could not be added. Check the integration log and grocery list before retrying."
        connection.send_error(msg["id"], "unknown_error", detail or "Could not add recipe ingredients.")


def register_websocket_commands(hass: HomeAssistant) -> None:
    """Register recipe, grocery, and meal-plan WebSocket commands."""
    websocket_api.async_register_command(hass, websocket_get_grocery_list)
    websocket_api.async_register_command(hass, websocket_get_meal_plan)
    websocket_api.async_register_command(hass, websocket_get_meal_plan_range)
    websocket_api.async_register_command(hass, websocket_list_recipes)
    websocket_api.async_register_command(hass, websocket_get_recipe)
    websocket_api.async_register_command(hass, websocket_add_recipe_ingredients)
