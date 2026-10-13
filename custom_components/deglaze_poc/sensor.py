"""Diagnostic sensor for the Deglaze proof of concept."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_USER_ID, DOMAIN
from .coordinator import DeglazePOCCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the single diagnostic sensor."""
    coordinator: DeglazePOCCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([DeglazePOCStatusSensor(coordinator, entry)])


class DeglazePOCStatusSensor(CoordinatorEntity[DeglazePOCCoordinator], SensorEntity):
    """Show whether Firebase auth and the Deglaze grocery endpoint are working."""

    _attr_has_entity_name = True
    _attr_name = "Grocery API Status"
    _attr_icon = "mdi:cloud-check"

    def __init__(self, coordinator: DeglazePOCCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.data[CONF_USER_ID]}_grocery_api_status"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.data[CONF_USER_ID])},
            name="Deglaze POC",
            manufacturer="Deglaze (unofficial integration POC)",
            model="Email-link authentication and grocery API test",
        )

    @property
    def native_value(self) -> str:
        """Return an easy-to-read endpoint status."""
        return "connected"

    @property
    def extra_state_attributes(self) -> dict:
        """Expose response-shape diagnostics without exposing grocery item names."""
        return dict(self.coordinator.data)
