"""Unofficial Deglaze Home Assistant integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import DeglazeApiClient
from .const import (
    CONF_DEVICE_ID,
    CONF_EMAIL,
    CONF_FIREBASE_API_KEY,
    CONF_REFRESH_TOKEN,
    CONF_USER_ID,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import DeglazePOCCoordinator
from .services import async_register_services, async_remove_services
from .websocket import register_websocket_commands


def _make_refresh_token_callback(hass: HomeAssistant, entry: ConfigEntry):
    """Persist a rotated refresh token in the config entry when Firebase returns one."""
    def update_refresh_token(new_refresh_token: str) -> None:
        if new_refresh_token and new_refresh_token != entry.data.get(CONF_REFRESH_TOKEN):
            hass.config_entries.async_update_entry(
                entry, data={**entry.data, CONF_REFRESH_TOKEN: new_refresh_token}
            )
    return update_refresh_token


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Deglaze using the saved Firebase refresh token and sync endpoints."""
    session = async_get_clientsession(hass)
    client = DeglazeApiClient(
        session=session,
        email=entry.data[CONF_EMAIL],
        firebase_api_key=entry.data[CONF_FIREBASE_API_KEY],
        refresh_token=entry.data[CONF_REFRESH_TOKEN],
        device_id=entry.data[CONF_DEVICE_ID],
        on_refresh_token=_make_refresh_token_callback(hass, entry),
        time_zone=hass.config.time_zone,
    )
    client.user_id = entry.data.get(CONF_USER_ID)
    coordinator = DeglazePOCCoordinator(hass, client)
    # Recipe/meal-plan failures are surfaced in status sensors but do not block the
    # already-working grocery path from loading.
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "client": client,
        "coordinator": coordinator,
    }
    await async_register_services(hass)
    register_websocket_commands(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload platforms and integration runtime cleanly."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        if not hass.data.get(DOMAIN):
            async_remove_services(hass)
    return unload_ok
