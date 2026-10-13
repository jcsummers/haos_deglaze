"""Small, testable API client for the Deglaze authentication/list POC.

This is an unofficial client for observed web-app endpoints. Do not log sign-in links,
Firebase one-time codes, ID tokens, or refresh tokens.
"""
from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit

from .const import (
    ALLOWED_ACTION_HOST,
    ALLOWED_ACTION_PATH,
    ALLOWED_CONTINUE_HOST,
    DEGLAZE_LISTS_URL,
    DEGLAZE_WEB_BUILD_HASH,
    FIREBASE_REFRESH_URL,
    FIREBASE_SIGN_IN_URL,
)


class DeglazePOCError(Exception):
    """Base exception with safe-to-display messages."""


class InvalidSignInLink(DeglazePOCError):
    """The pasted URL is not a recognized Deglaze Firebase sign-in link."""


class FirebaseAuthError(DeglazePOCError):
    """Firebase rejected the sign-in link or refresh token."""


class DeglazeAPIError(DeglazePOCError):
    """Deglaze returned an HTTP error or an unexpected response."""


@dataclass(frozen=True)
class ParsedSignInLink:
    api_key: str
    oob_code: str


def parse_sign_in_link(link: str) -> ParsedSignInLink:
    """Validate a Deglaze Firebase email action URL and extract its credentials.

    The link itself is sensitive and must never be included in logs or error text.
    """
    try:
        parsed = urlsplit(link.strip())
        query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=False)
    except ValueError as err:
        raise InvalidSignInLink("The sign-in link could not be parsed.") from err

    if (
        parsed.scheme != "https"
        or parsed.hostname != ALLOWED_ACTION_HOST
        or parsed.path != ALLOWED_ACTION_PATH
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
    ):
        raise InvalidSignInLink(
            "Expected a Deglaze Firebase link from deglaze-prod.firebaseapp.com."
        )

    if query.get("mode", [None])[0] != "signIn":
        raise InvalidSignInLink("The link is not an email sign-in action.")

    api_key = query.get("apiKey", [""])[0]
    oob_code = query.get("oobCode", [""])[0]
    if not api_key.startswith("AIza") or not oob_code:
        raise InvalidSignInLink("The link is missing its Firebase key or one-time code.")

    # If present, the continue URL should be Deglaze's own web application.
    continue_url = query.get("continueUrl", [None])[0]
    if continue_url:
        try:
            continued = urlsplit(continue_url)
        except ValueError as err:
            raise InvalidSignInLink("The link contains an invalid return address.") from err
        if continued.scheme != "https" or continued.hostname != ALLOWED_CONTINUE_HOST:
            raise InvalidSignInLink("The link's return address is not a Deglaze website.")

    return ParsedSignInLink(api_key=api_key, oob_code=oob_code)


def summarize_grocery_response(payload: dict[str, Any]) -> dict[str, Any]:
    """Summarize the observed response without retaining grocery item names.

    The exported conversation did not include the actual GET response body, so this
    helper accepts the expected data.lists[].items shape plus a few common variants.
    It also reports whether the shape was recognized rather than silently inventing 0.
    """
    data = payload.get("data")
    lists: list[Any] | None = None
    items: list[Any] | None = None

    if isinstance(data, dict):
        candidate = data.get("lists")
        if isinstance(candidate, list):
            lists = candidate
        elif isinstance(data.get("items"), list):
            lists = [data]
    elif isinstance(data, list):
        # Some APIs return the list records directly under data.
        lists = data
    elif isinstance(payload.get("lists"), list):
        lists = payload["lists"]
    elif isinstance(payload.get("items"), list):
        lists = [payload]

    if lists is not None:
        if lists:
            first = lists[0]
            if isinstance(first, dict) and isinstance(first.get("items"), list):
                items = first["items"]
        else:
            items = []

    # Unknown response variants should be visible as unknown, not falsely reported as 0.
    recognized = items is not None
    safe_items = [item for item in items if isinstance(item, dict)] if items is not None else []
    statuses: list[str] = []
    for item in safe_items:
        status_obj = item.get("status")
        if isinstance(status_obj, dict):
            status = status_obj.get("status")
        else:
            status = status_obj
        if isinstance(status, str):
            statuses.append(status.lower())

    data_keys = sorted(data.keys()) if isinstance(data, dict) else []
    item_keys = sorted({key for item in safe_items for key in item.keys()})
    return {
        "schema_recognized": recognized,
        "response_top_level_keys": sorted(payload.keys()),
        "response_data_keys": data_keys,
        "list_count": len(lists) if lists is not None else None,
        "item_count": len(items) if items is not None else None,
        "pending_count": statuses.count("pending") if recognized else None,
        "completed_count": statuses.count("completed") if recognized else None,
        "item_field_names": item_keys,
    }


class DeglazeApiClient:
    """Minimal asynchronous Firebase + Deglaze client."""

    def __init__(
        self,
        session: Any,
        email: str,
        firebase_api_key: str | None = None,
        refresh_token: str | None = None,
        device_id: str = "home-assistant-deglaze-poc",
        on_refresh_token: Callable[[str], None] | None = None,
        time_zone: str = "UTC",
    ) -> None:
        self.session = session
        self.email = email.strip()
        self.firebase_api_key = firebase_api_key
        self.refresh_token = refresh_token
        self.device_id = device_id
        self.on_refresh_token = on_refresh_token
        self.time_zone = time_zone
        self.user_id: str | None = None
        self._id_token: str | None = None
        self._id_token_expires_at: float = 0

    async def async_exchange_sign_in_link(self, link: str) -> None:
        """Exchange a fresh Deglaze email action link for Firebase tokens."""
        parsed_link = parse_sign_in_link(link)
        self.firebase_api_key = parsed_link.api_key
        url = FIREBASE_SIGN_IN_URL
        body = {"email": self.email, "oobCode": parsed_link.oob_code}

        async with self.session.post(url, params={"key": self.firebase_api_key}, json=body) as response:
            data = await _read_json(response, FirebaseAuthError, "Firebase rejected the sign-in link")
            if response.status >= 400:
                raise FirebaseAuthError(_firebase_error_code(data) or "Firebase rejected the sign-in link")

        if not isinstance(data, dict):
            raise FirebaseAuthError("Firebase returned an unexpected sign-in response.")
        id_token = data.get("idToken")
        refresh_token = data.get("refreshToken")
        user_id = data.get("localId")
        if not id_token or not refresh_token or not user_id:
            raise FirebaseAuthError("Firebase's sign-in response did not contain the expected tokens.")

        self._id_token = id_token
        self.refresh_token = refresh_token
        self.user_id = user_id
        try:
            expires_in = int(data.get("expiresIn", "3600"))
        except (TypeError, ValueError):
            expires_in = 3600
        self._id_token_expires_at = time.time() + expires_in

    async def async_get_id_token(self, force_refresh: bool = False) -> str:
        """Return a usable ID token, refreshing it as necessary."""
        if not force_refresh and self._id_token and time.time() < self._id_token_expires_at - 60:
            return self._id_token
        if not self.firebase_api_key or not self.refresh_token:
            raise FirebaseAuthError("No saved Firebase refresh token is available; sign in again.")

        async with self.session.post(
            FIREBASE_REFRESH_URL,
            params={"key": self.firebase_api_key},
            data={"grant_type": "refresh_token", "refresh_token": self.refresh_token},
        ) as response:
            data = await _read_json(response, FirebaseAuthError, "Firebase token refresh failed")
            if response.status >= 400:
                raise FirebaseAuthError(_firebase_error_code(data) or "Firebase token refresh failed")

        if not isinstance(data, dict):
            raise FirebaseAuthError("Firebase returned an unexpected token-refresh response.")
        new_id_token = data.get("id_token")
        new_refresh_token = data.get("refresh_token") or self.refresh_token
        if not new_id_token:
            raise FirebaseAuthError("Firebase token refresh response did not contain an ID token.")

        self._id_token = new_id_token
        self.refresh_token = new_refresh_token
        self.user_id = data.get("user_id") or self.user_id
        try:
            expires_in = int(data.get("expires_in", "3600"))
        except (TypeError, ValueError):
            expires_in = 3600
        self._id_token_expires_at = time.time() + expires_in

        if self.on_refresh_token and new_refresh_token:
            self.on_refresh_token(new_refresh_token)
        return self._id_token

    async def async_get_grocery_list(self) -> dict[str, Any]:
        """Call Deglaze GET /v1/lists and return its JSON object."""
        token = await self.async_get_id_token()
        payload = await self._request_grocery_list(token)
        return payload

    async def _request_grocery_list(self, token: str) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "x-platform": "web",
            "x-dev": "0",
            "x-sha": DEGLAZE_WEB_BUILD_HASH,
            "x-device-id": self.device_id,
            "x-device-type": "Home Assistant Deglaze POC",
            "x-tz": self.time_zone,
            "x-locale": "en-US",
            "Origin": "https://web.deglaze.app",
            "Referer": "https://web.deglaze.app/",
        }
        async with self.session.get(DEGLAZE_LISTS_URL, headers=headers) as response:
            status = response.status
            if status != 401:
                payload = await _read_json(
                    response, DeglazeAPIError, "Deglaze grocery-list request failed"
                )
            else:
                payload = None

        if status == 401:
            # Retry once after refreshing in case the token expired early.
            fresh_token = await self.async_get_id_token(force_refresh=True)
            async with self.session.get(
                DEGLAZE_LISTS_URL,
                headers={**headers, "Authorization": f"Bearer {fresh_token}"},
            ) as retry_response:
                retry_status = retry_response.status
                if retry_status >= 400:
                    raise DeglazeAPIError(
                        f"Deglaze returned HTTP {retry_status} for GET /v1/lists."
                    )
                retry_payload = await _read_json(
                    retry_response, DeglazeAPIError, "Deglaze grocery-list request failed"
                )
            if not isinstance(retry_payload, dict):
                raise DeglazeAPIError(
                    "Deglaze returned an unexpected JSON response for GET /v1/lists."
                )
            return retry_payload

        if status >= 400:
            raise DeglazeAPIError(f"Deglaze returned HTTP {status} for GET /v1/lists.")
        if not isinstance(payload, dict):
            raise DeglazeAPIError(
                "Deglaze returned an unexpected JSON response for GET /v1/lists."
            )
        return payload


async def _read_json(response: Any, error_type: type[Exception], fallback: str) -> Any:
    """Read JSON and raise safe errors without including URLs or credentials."""
    try:
        payload = await response.json(content_type=None)
    except Exception as err:  # Invalid JSON / HTML response; don't log response body.
        if response.status >= 400:
            raise error_type(f"{fallback} (HTTP {response.status}).") from err
        raise error_type("The server returned a non-JSON response.") from err
    if not isinstance(payload, (dict, list)):
        raise error_type("The server returned an unexpected response format.")
    return payload


def _firebase_error_code(payload: Any) -> str | None:
    """Return Firebase's short error code only, not the full response."""
    if not isinstance(payload, dict):
        return None
    error = payload.get("error")
    if not isinstance(error, dict):
        return None
    message = error.get("message")
    if isinstance(message, str):
        # Keep errors short and avoid displaying any request details.
        return message.split(" ", maxsplit=1)[0][:80]
    return None
