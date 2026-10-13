"""UI setup flow for the unofficial Deglaze integration."""
from __future__ import annotations

from typing import Any
from uuid import uuid4

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    DeglazeApiClient,
    DeglazeAPIError,
    FirebaseAuthError,
    InvalidSignInLink,
)
from .const import (
    CONF_DEVICE_ID,
    CONF_EMAIL,
    CONF_FIREBASE_API_KEY,
    CONF_REFRESH_TOKEN,
    CONF_USER_ID,
    DOMAIN,
)


class DeglazePOCConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure Deglaze using a one-time Firebase email sign-in link."""

    VERSION = 1

    def __init__(self) -> None:
        self._email: str | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Collect the Deglaze account email."""
        if user_input is not None:
            email = user_input[CONF_EMAIL].strip()
            if "@" not in email or len(email) > 255:
                return self.async_show_form(
                    step_id="user",
                    data_schema=vol.Schema({vol.Required(CONF_EMAIL, default=email): cv.string}),
                    errors={"base": "invalid_email"},
                )
            self._email = email
            return await self.async_step_link()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_EMAIL): cv.string}),
        )

    async def async_step_link(self, user_input: dict[str, Any] | None = None):
        """Exchange a pasted email link and verify the grocery-list endpoint."""
        if self._email is None:
            return await self.async_step_user()

        if user_input is not None:
            device_id = str(uuid4())
            client = DeglazeApiClient(
                session=async_get_clientsession(self.hass),
                email=self._email,
                device_id=device_id,
                time_zone=self.hass.config.time_zone,
            )
            try:
                await client.async_exchange_sign_in_link(user_input["sign_in_link"])
                # The proof is complete only when the exchanged ID token can call Deglaze.
                payload = await client.async_get_grocery_list()
                if not isinstance(payload, dict):
                    raise DeglazeAPIError("Deglaze did not return a JSON object for GET /v1/lists.")
                if not client.firebase_api_key or not client.refresh_token or not client.user_id:
                    raise FirebaseAuthError("Firebase did not return the required session details.")
            except InvalidSignInLink:
                return self.async_show_form(
                    step_id="link",
                    data_schema=vol.Schema({vol.Required("sign_in_link"): cv.string}),
                    errors={"base": "invalid_link"},
                )
            except FirebaseAuthError as err:
                code = str(err)
                base_error = "invalid_auth" if "INVALID_OOB_CODE" in code or "EXPIRED_OOB_CODE" in code else "auth_failed"
                return self.async_show_form(
                    step_id="link",
                    data_schema=vol.Schema({vol.Required("sign_in_link"): cv.string}),
                    errors={"base": base_error},
                )
            except DeglazeAPIError:
                return self.async_show_form(
                    step_id="link",
                    data_schema=vol.Schema({vol.Required("sign_in_link"): cv.string}),
                    errors={"base": "cannot_connect"},
                )
            except Exception:
                # Network/timeout failures should result in a safe form error, not a traceback.
                return self.async_show_form(
                    step_id="link",
                    data_schema=vol.Schema({vol.Required("sign_in_link"): cv.string}),
                    errors={"base": "cannot_connect"},
                )

            await self.async_set_unique_id(client.user_id)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title="Deglaze",
                data={
                    CONF_EMAIL: self._email,
                    CONF_FIREBASE_API_KEY: client.firebase_api_key,
                    CONF_REFRESH_TOKEN: client.refresh_token,
                    CONF_USER_ID: client.user_id,
                    CONF_DEVICE_ID: device_id,
                },
            )

        return self.async_show_form(
            step_id="link",
            data_schema=vol.Schema({vol.Required("sign_in_link"): cv.string}),
        )
