"""Grocery, recipe-library, meal-plan, and API-status sensors."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_USER_ID, DOMAIN
from .coordinator import DeglazePOCCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up a small set of summary entities, not one entity per recipe."""
    runtime = hass.data[DOMAIN][entry.entry_id]
    coordinator: DeglazePOCCoordinator = runtime["coordinator"]
    user_id = entry.data[CONF_USER_ID]
    device = _device_info(user_id)
    # Remove recipe-per-entity entries created by earlier test builds. The recipe
    # library is now browsed through the custom Lovelace card/WebSocket API.
    registry = er.async_get(hass)
    legacy_prefix = f"{user_id}_recipe_"
    for registered in er.async_entries_for_config_entry(registry, entry.entry_id):
        if registered.domain == "sensor" and registered.unique_id.startswith(legacy_prefix):
            registry.async_remove(registered.entity_id)

    async_add_entities(
        [
            DeglazeGroceryListSensor(coordinator, entry, device),
            DeglazeRecipeLibrarySensor(coordinator, entry, device),
            DeglazeMealPlanSensor(coordinator, entry, device),
            DeglazeAPIStatusSensor(coordinator, entry, device),
        ]
    )


def _device_info(user_id: str) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, user_id)},
        name="Deglaze",
        manufacturer="Deglaze (unofficial integration)",
        model="Grocery, recipes, and meal planning",
    )


def _status(item: dict[str, Any]) -> str | None:
    value = item.get("status")
    if isinstance(value, dict):
        value = value.get("status")
    return value.lower() if isinstance(value, str) else None


def _active_meal_items(coordinator: DeglazePOCCoordinator) -> list[dict[str, Any]]:
    raw_items = (coordinator.data or {}).get("meal_plan", {}).get("items", [])
    return [item for item in raw_items if item.get("deleted") is not True]


class DeglazeGroceryListSensor(CoordinatorEntity[DeglazePOCCoordinator], SensorEntity):
    """Single-store-section-aware view of the current grocery list."""

    _attr_has_entity_name = True
    _attr_name = "Grocery List"
    _attr_icon = "mdi:cart-outline"
    _attr_native_unit_of_measurement = "items"

    def __init__(self, coordinator: DeglazePOCCoordinator, entry: ConfigEntry, device: DeviceInfo):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.data[CONF_USER_ID]}_grocery_list"
        self._attr_device_info = device

    @property
    def native_value(self) -> int | None:
        summary = (self.coordinator.data or {}).get("grocery", {}).get("summary", {})
        return summary.get("pending_count") if summary.get("schema_recognized") else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        grocery = (self.coordinator.data or {}).get("grocery", {})
        summary = grocery.get("summary", {})
        items = grocery.get("items", [])
        statuses = [_status(item) for item in items]
        return {
            "pending_count": statuses.count("pending"),
            "completed_count": statuses.count("completed"),
            "item_count": len(items),
            "list_count": summary.get("list_count"),
            "schema_recognized": summary.get("schema_recognized", False),
            "list_id": self.coordinator.client.default_grocery_list_id,
            # Keep entity attributes deliberately small. The full list is returned
            # to the Lovelace card over the integration's authenticated WebSocket API.
            "last_updated": grocery.get("last_updated"),
        }


class DeglazeRecipeLibrarySensor(CoordinatorEntity[DeglazePOCCoordinator], SensorEntity):
    """A single summary entity for the browsable recipe library."""

    _attr_has_entity_name = True
    _attr_name = "Recipe Library"
    _attr_icon = "mdi:book-open-variant"
    _attr_native_unit_of_measurement = "recipes"

    def __init__(self, coordinator: DeglazePOCCoordinator, entry: ConfigEntry, device: DeviceInfo):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.data[CONF_USER_ID]}_recipe_library"
        self._attr_device_info = device

    @property
    def native_value(self) -> int:
        return int((self.coordinator.data or {}).get("active_recipe_count", 0))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        meta = data.get("recipe_meta", {})
        errors = data.get("errors", {})
        return {
            "version": meta.get("version"),
            "last_synced": meta.get("last_synced"),
            "last_page_count": meta.get("pages"),
            "last_received_count": meta.get("received"),
            "last_sync_was_full": meta.get("full_sync"),
            "archived_count": data.get("archived_recipe_count", 0),
            "deleted_count": data.get("deleted_recipe_count", 0),
            "sync_error": errors.get("recipes"),
        }


class DeglazeMealPlanSensor(CoordinatorEntity[DeglazePOCCoordinator], SensorEntity):
    """Meal count for the synchronized range; deleted entries are omitted."""

    _attr_has_entity_name = True
    _attr_name = "Meal Plan"
    _attr_icon = "mdi:calendar-month-outline"
    _attr_native_unit_of_measurement = "meals"

    def __init__(self, coordinator: DeglazePOCCoordinator, entry: ConfigEntry, device: DeviceInfo):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.data[CONF_USER_ID]}_meal_plan"
        self._attr_device_info = device

    @property
    def native_value(self) -> int:
        return len(_active_meal_items(self.coordinator))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        meal_plan = (self.coordinator.data or {}).get("meal_plan", {})
        recipe_map = (self.coordinator.data or {}).get("recipes", {})
        items = []
        for item in _active_meal_items(self.coordinator):
            summary = {
                key: item[key]
                for key in ("id", "type", "date", "recipeId", "label", "isLeftovers", "version")
                if key in item
            }
            recipe = recipe_map.get(item.get("recipeId"), {})
            if recipe.get("title"):
                summary["recipe_title"] = recipe["title"]
            items.append(summary)
        return {
            "start": meal_plan.get("start"),
            "end": meal_plan.get("end"),
            "version": meal_plan.get("version"),
            "last_synced": meal_plan.get("last_synced"),
            "sync_error": (self.coordinator.data or {}).get("errors", {}).get("meal_plan"),
            "items": items,
        }


class DeglazeAPIStatusSensor(CoordinatorEntity[DeglazePOCCoordinator], SensorEntity):
    """Diagnostic status for the combined integration."""

    _attr_has_entity_name = True
    _attr_name = "API Status"
    _attr_icon = "mdi:cloud-check"

    def __init__(self, coordinator: DeglazePOCCoordinator, entry: ConfigEntry, device: DeviceInfo):
        super().__init__(coordinator)
        # Preserve the original POC unique ID so its entity registry entry is reused.
        self._attr_unique_id = f"{entry.data[CONF_USER_ID]}_grocery_api_status"
        self._attr_device_info = device

    @property
    def native_value(self) -> str:
        errors = (self.coordinator.data or {}).get("errors", {})
        if "grocery" in errors:
            return "degraded"
        if errors:
            return "partial"
        return "connected"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        summary = data.get("grocery", {}).get("summary", {})
        return {
            **summary,
            "recipe_count": data.get("active_recipe_count", 0),
            "recipe_sync_error": data.get("errors", {}).get("recipes"),
            "meal_plan_sync_error": data.get("errors", {}).get("meal_plan"),
            "last_checked": data.get("last_checked"),
            "errors": dict(data.get("errors", {})),
        }

