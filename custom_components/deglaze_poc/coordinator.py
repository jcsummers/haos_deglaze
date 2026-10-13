"""Data coordinator for the Deglaze proof of concept."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import DeglazePOCError, DeglazeApiClient, summarize_grocery_response
from .const import DOMAIN, UPDATE_INTERVAL


class DeglazePOCCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Poll Deglaze's grocery-list endpoint and retain a safe summary."""

    def __init__(self, hass: HomeAssistant, client: DeglazeApiClient) -> None:
        super().__init__(
            hass,
            logger=__import__("logging").getLogger(__name__),
            name=f"{DOMAIN} grocery list",
            update_interval=UPDATE_INTERVAL,
        )
        self.client = client

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            payload = await self.client.async_get_grocery_list()
        except DeglazePOCError as err:
            raise UpdateFailed(str(err)) from err
        except Exception as err:
            raise UpdateFailed("Unexpected error calling Deglaze GET /v1/lists.") from err

        summary = summarize_grocery_response(payload)
        summary["last_checked"] = datetime.now(timezone.utc).isoformat()
        return summary
