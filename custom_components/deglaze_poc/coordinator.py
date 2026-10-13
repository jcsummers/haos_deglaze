"""Polling coordinator for grocery items, the recipe library, and meal planning."""
from __future__ import annotations

from datetime import timedelta
import logging
import time
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    DeglazeAPIError,
    DeglazePOCError,
    DeglazeApiClient,
    extract_grocery_items,
    extract_grocery_lists,
    recipe_is_active,
    summarize_grocery_response,
)
from .const import (
    DOMAIN,
    MEAL_PLAN_DAYS_AHEAD,
    MEAL_PLAN_SYNC_INTERVAL,
    RECIPE_SYNC_INTERVAL,
    UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


class DeglazePOCCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Poll verified grocery data and separately track recipe/meal-plan sync status."""

    def __init__(self, hass: HomeAssistant, client: DeglazeApiClient) -> None:
        super().__init__(
            hass,
            logger=_LOGGER,
            name=f"{DOMAIN} data",
            update_interval=UPDATE_INTERVAL,
        )
        self.client = client
        self._last_recipe_attempt = 0.0
        self._recipe_attempt_succeeded = False
        self._last_meal_plan_attempt = 0.0

    def async_force_refresh_all(self) -> None:
        """Make recipe and meal-plan refreshes due before requesting coordinator refresh."""
        self._last_recipe_attempt = 0.0
        self._last_meal_plan_attempt = 0.0

    def async_force_meal_plan_refresh(self) -> None:
        """Make a meal-plan refresh due before requesting coordinator refresh."""
        self._last_meal_plan_attempt = 0.0

    def async_force_recipe_refresh(self) -> None:
        """Make a recipe-library refresh due before requesting coordinator refresh."""
        self._last_recipe_attempt = 0.0

    async def _async_update_data(self) -> dict[str, Any]:
        previous = self.data or {}
        data: dict[str, Any] = {
            "grocery": previous.get("grocery", {}),
            "recipes": previous.get("recipes", {}),
            "recipe_meta": previous.get("recipe_meta", {}),
            "meal_plan": previous.get("meal_plan", {}),
            "errors": dict(previous.get("errors", {})),
        }
        now_mono = time.monotonic()

        # Grocery access is the original proven path and remains the setup requirement.
        try:
            grocery_payload = await self.client.async_get_grocery_list()
            lists = extract_grocery_lists(grocery_payload)
            if lists is None:
                raise DeglazeAPIError("Deglaze's grocery-list response shape was not recognized.")
            grocery_items = extract_grocery_items(grocery_payload)
            grocery_summary = summarize_grocery_response(grocery_payload)
            data["grocery"] = {
                "lists": lists,
                "items": grocery_items,
                "summary": grocery_summary,
                "last_updated": dt_util.utcnow().isoformat(),
            }
            data["errors"].pop("grocery", None)
        except Exception as err:
            if not data["grocery"]:
                if isinstance(err, DeglazePOCError):
                    raise UpdateFailed(str(err)) from err
                raise UpdateFailed("Unable to retrieve Deglaze grocery list.") from err
            data["errors"]["grocery"] = _safe_error_message(err, "Grocery-list refresh failed")
            _LOGGER.warning("Deglaze grocery refresh failed; keeping last successful data")

        # Keep the 5-minute grocery poll while avoiding that frequency for recipe pages.
        recipe_interval = (
            RECIPE_SYNC_INTERVAL.total_seconds()
            if self._recipe_attempt_succeeded
            else min(600.0, RECIPE_SYNC_INTERVAL.total_seconds())
        )
        if (
            self._last_recipe_attempt == 0.0
            or now_mono - self._last_recipe_attempt >= recipe_interval
        ):
            self._last_recipe_attempt = now_mono
            try:
                merged, meta = await self.client.async_sync_recipes(
                    data["recipes"],
                    data["recipe_meta"].get("version"),
                    data["recipe_meta"].get("collections"),
                )
                meta["last_synced"] = dt_util.utcnow().isoformat()
                data["recipes"] = merged
                data["recipe_meta"] = meta
                self._recipe_attempt_succeeded = True
                data["errors"].pop("recipes", None)
            except Exception as err:
                self._recipe_attempt_succeeded = False
                data["errors"]["recipes"] = _safe_error_message(
                    err, "Recipe-library synchronization failed"
                )
                _LOGGER.warning("Deglaze recipe synchronization failed")

        if (
            self._last_meal_plan_attempt == 0.0
            or now_mono - self._last_meal_plan_attempt >= MEAL_PLAN_SYNC_INTERVAL.total_seconds()
        ):
            self._last_meal_plan_attempt = now_mono
            try:
                local_now = dt_util.as_local(dt_util.utcnow())
                start = local_now.date()
                end = start + timedelta(days=MEAL_PLAN_DAYS_AHEAD)
                payload = await self.client.async_get_meal_plan(
                    start.isoformat(), end.isoformat()
                )
                meal_data = payload.get("data")
                if not isinstance(meal_data, dict) or not isinstance(meal_data.get("items"), list):
                    raise DeglazeAPIError(
                        "Deglaze's meal-plan response shape was not recognized."
                    )
                data["meal_plan"] = {
                    "start": meal_data.get("start", start.isoformat()),
                    "end": meal_data.get("end", end.isoformat()),
                    "for": meal_data.get("for"),
                    "version": meal_data.get("version"),
                    "items": [item for item in meal_data["items"] if isinstance(item, dict)],
                    "last_synced": dt_util.utcnow().isoformat(),
                }
                data["errors"].pop("meal_plan", None)
            except Exception as err:
                data["errors"]["meal_plan"] = _safe_error_message(
                    err, "Meal-plan refresh failed"
                )
                _LOGGER.warning("Deglaze meal-plan refresh failed")

        data["last_checked"] = dt_util.utcnow().isoformat()
        data["active_recipe_count"] = sum(
            1 for recipe in data["recipes"].values() if recipe_is_active(recipe)
        )
        data["archived_recipe_count"] = sum(
            1 for recipe in data["recipes"].values() if recipe.get("archived") is True
        )
        data["deleted_recipe_count"] = sum(
            1 for recipe in data["recipes"].values() if recipe.get("deleted") is True
        )
        return data


def _safe_error_message(err: Exception, fallback: str) -> str:
    """Return short error messages without request/response bodies or credentials."""
    if isinstance(err, DeglazePOCError):
        return str(err)[:240]
    return fallback
