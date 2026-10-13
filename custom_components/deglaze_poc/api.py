"""Async Firebase and Deglaze API client for the unofficial HA integration.

The Deglaze endpoints are undocumented web-app endpoints. Keep requests minimal,
avoid logging response bodies, and never log email sign-in links or Firebase tokens.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import re
import time
from typing import Any, Callable
import unicodedata
from urllib.parse import parse_qs, urlsplit

import aiohttp

from .const import (
    ALLOWED_ACTION_HOST,
    ALLOWED_ACTION_PATH,
    ALLOWED_CONTINUE_HOST,
    DEGLAZE_BASE_URL,
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
    """Validate a Deglaze Firebase email action URL and extract its credentials."""
    try:
        parsed = urlsplit(link.strip())
        query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=False)
        port = parsed.port
    except ValueError as err:
        raise InvalidSignInLink("The sign-in link could not be parsed.") from err

    if (
        parsed.scheme != "https"
        or parsed.hostname != ALLOWED_ACTION_HOST
        or parsed.path != ALLOWED_ACTION_PATH
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
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

    continue_url = query.get("continueUrl", [None])[0]
    if continue_url:
        try:
            continued = urlsplit(continue_url)
        except ValueError as err:
            raise InvalidSignInLink("The link contains an invalid return address.") from err
        if continued.scheme != "https" or continued.hostname != ALLOWED_CONTINUE_HOST:
            raise InvalidSignInLink("The link's return address is not a Deglaze website.")

    return ParsedSignInLink(api_key=api_key, oob_code=oob_code)


def _data_object(payload: Any, endpoint: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise DeglazeAPIError(f"Deglaze returned an unexpected response for {endpoint}.")
    data = payload.get("data")
    if isinstance(data, dict):
        return data
    raise DeglazeAPIError(f"Deglaze returned an unexpected response for {endpoint}.")


def extract_grocery_lists(payload: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Return grocery lists when a known response shape is present."""
    data = payload.get("data")
    if isinstance(data, dict) and isinstance(data.get("lists"), list):
        return [item for item in data["lists"] if isinstance(item, dict)]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(payload.get("lists"), list):
        return [item for item in payload["lists"] if isinstance(item, dict)]
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return [data]
    if isinstance(payload.get("items"), list):
        return [payload]
    return None


def extract_grocery_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten grocery items from all returned list records."""
    lists = extract_grocery_lists(payload) or []
    flattened: list[dict[str, Any]] = []
    for grocery_list in lists:
        items = grocery_list.get("items")
        if not isinstance(items, list):
            continue
        list_id = grocery_list.get("id")
        for item in items:
            if isinstance(item, dict):
                normalized = dict(item)
                if list_id and not normalized.get("listId"):
                    normalized["listId"] = list_id
                flattened.append(normalized)
    return flattened


def extract_grocery_stores(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten valid store records from the observed grocery-list response."""
    stores: dict[str, dict[str, Any]] = {}
    for grocery_list in extract_grocery_lists(payload) or []:
        raw_stores = grocery_list.get("stores")
        if not isinstance(raw_stores, list):
            continue
        for store in raw_stores:
            if not isinstance(store, dict):
                continue
            store_id = store.get("id")
            name = store.get("name")
            if not isinstance(store_id, str) or not store_id or not isinstance(name, str) or not name.strip():
                continue
            normalized = {"id": store_id, "name": name.strip()}
            version = store.get("version")
            if isinstance(version, int) and version >= 0:
                normalized["version"] = version
            stores[store_id] = normalized
    return sorted(stores.values(), key=lambda store: store["name"].casefold())


def grocery_item_store_ids(item: dict[str, Any]) -> list[str]:
    """Normalize item store associations, which are normally a list of store IDs."""
    raw_stores = item.get("stores")
    if not isinstance(raw_stores, list):
        return []
    result: list[str] = []
    for store in raw_stores:
        store_id = store if isinstance(store, str) else store.get("id") if isinstance(store, dict) else None
        if isinstance(store_id, str) and store_id and store_id not in result:
            result.append(store_id)
    return result


def summarize_grocery_response(payload: dict[str, Any]) -> dict[str, Any]:
    """Return counts and structure diagnostics without grocery names or IDs."""
    lists = extract_grocery_lists(payload)
    items = extract_grocery_items(payload) if lists is not None else None
    statuses: list[str] = []
    for item in items or []:
        status_obj = item.get("status")
        status = status_obj.get("status") if isinstance(status_obj, dict) else status_obj
        if isinstance(status, str):
            statuses.append(status.lower())
    data = payload.get("data")
    data_keys = sorted(data.keys()) if isinstance(data, dict) else []
    item_keys = sorted({key for item in items or [] for key in item.keys()})
    return {
        "schema_recognized": items is not None,
        "response_top_level_keys": sorted(payload.keys()),
        "response_data_keys": data_keys,
        "list_count": len(lists) if lists is not None else None,
        "item_count": len(items) if items is not None else None,
        "pending_count": statuses.count("pending") if items is not None else None,
        "completed_count": statuses.count("completed") if items is not None else None,
        "item_field_names": item_keys,
    }


def recipe_is_active(recipe: dict[str, Any]) -> bool:
    """Whether a library recipe should appear as an active recipe entity."""
    return recipe.get("deleted") is not True and recipe.get("archived") is not True


def extract_recipe_ingredient_choices(ingredients: Any) -> list[dict[str, str]]:
    """Flatten a Deglaze ingredient tree into stable, selectable grocery entries.

    The observed recipe schema uses ``ingredients.sections[].items[]`` where each
    ingredient has an ID and a display string in ``text``. IDs are namespaced by
    section so that even malformed data with repeated item IDs remains unambiguous.
    A deterministic index-based ID is used if the source omits an ingredient ID.
    The ingredient text is preserved verbatim; quantities and notes are not parsed
    or scaled by the integration.
    """
    root = ingredients
    if isinstance(root, dict) and isinstance(root.get("ingredients"), (dict, list)):
        root = root["ingredients"]

    sections: list[Any] = []
    if isinstance(root, dict) and isinstance(root.get("sections"), list):
        sections = root["sections"]
    elif isinstance(root, dict) and isinstance(root.get("items"), list):
        sections = [{"items": root["items"]}]
    elif isinstance(root, list):
        # A flat array is treated as one unnamed ingredient section.
        sections = [{"items": root}]
    else:
        return []

    result: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for section_index, section in enumerate(sections):
        if isinstance(section, dict):
            section_title = section.get("title") or section.get("name") or ""
            raw_items = section.get("items")
            if not isinstance(raw_items, list):
                raw_items = section.get("ingredients")
        elif isinstance(section, list):
            section_title, raw_items = "", section
        else:
            continue
        if not isinstance(raw_items, list):
            continue
        section_key = f"section-{section_index}"
        for item_index, item in enumerate(raw_items):
            if isinstance(item, str):
                text = item.strip()
                item_id = f"item-{item_index}"
            elif isinstance(item, dict):
                raw_text = item.get("text")
                if not isinstance(raw_text, str):
                    raw_text = item.get("ingredient")
                if not isinstance(raw_text, str):
                    raw_text = item.get("value")
                text = raw_text.strip() if isinstance(raw_text, str) else ""
                raw_id = item.get("id")
                item_id = raw_id.strip() if isinstance(raw_id, str) and raw_id.strip() else f"item-{item_index}"
            else:
                continue
            if not text:
                continue
            choice_id = f"{section_key}:{item_id}"
            # Stable even if a source response unexpectedly repeats an ID.
            if choice_id in seen_ids:
                choice_id = f"{choice_id}:{item_index}"
            seen_ids.add(choice_id)
            choice: dict[str, str] = {"id": choice_id, "text": text}
            if isinstance(section_title, str) and section_title.strip():
                choice["section"] = section_title.strip()
            result.append(choice)
    return result


_GROCERY_UNIT_WORDS = {
    "g", "gram", "grams", "kg", "kilogram", "kilograms", "mg", "milligram", "milligrams",
    "ml", "milliliter", "milliliters", "millilitre", "millilitres", "l", "liter", "liters",
    "litre", "litres", "oz", "ounce", "ounces", "lb", "lbs", "pound", "pounds",
    "tsp", "teaspoon", "teaspoons", "tbsp", "tablespoon", "tablespoons", "cup", "cups",
    "pint", "pints", "quart", "quarts", "gallon", "gallons", "clove", "cloves", "bunch",
    "bunches", "can", "cans", "tin", "tins", "packet", "packets", "package", "packages",
    "slice", "slices", "sprig", "sprigs", "piece", "pieces", "serving", "servings", "handful",
    "handfuls", "pinch", "pinches", "dash", "dashes", "head", "heads", "stalk", "stalks",
}
_GROCERY_PREPARATION_WORDS = {
    "finely", "roughly", "chopped", "diced", "minced", "grated", "crushed", "sliced",
    "ground", "drained", "reserved", "topping", "garnish", "garnishing", "optional",
}


def normalize_grocery_item_key(value: Any) -> str:
    """Normalize recipe and list text for conservative duplicate warnings.

    This is a heuristic for warnings, not a claim that two different quantities
    are interchangeable. The original display text is never changed. Parenthetical
    notes, leading quantities, measurement units, and common prep terms are removed
    so entries such as ``2 tbsp chopped garlic`` and ``garlic`` can be recognized.
    """
    if not isinstance(value, str):
        return ""
    text = unicodedata.normalize("NFKC", value).casefold()
    text = re.sub(r"\([^)]*\)", " ", text)
    # Handle integers, decimals, fractions, and mixed quantities at the beginning.
    text = re.sub(r"^\s*(?:(?:\d+\s+)?\d+\s*[\/⁄]\s*\d+|\d+(?:[.,]\d+)?|[¼½¾⅓⅔⅛⅜⅝⅞])\s*", " ", text)
    text = re.sub(r"\b(?:a|an|of|for|to|the)\b", " ", text)
    tokens = re.findall(r"[^\W_]+", text, flags=re.UNICODE)
    tokens = [token for token in tokens if token not in _GROCERY_UNIT_WORDS and token not in _GROCERY_PREPARATION_WORDS]
    if not tokens:
        return ""
    # Very small plural normalization for common grocery labels.
    singularized: list[str] = []
    for token in tokens:
        if len(token) > 4 and token.endswith("ies"):
            token = token[:-3] + "y"
        elif len(token) > 4 and token.endswith("oes"):
            token = token[:-2]
        elif len(token) > 3 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
            token = token[:-1]
        singularized.append(token)
    return " ".join(singularized)


def plan_recipe_ingredient_additions(
    choices: list[dict[str, str]],
    ingredient_ids: list[str],
    existing_items: list[dict[str, Any]],
    include_duplicates: bool = False,
) -> dict[str, Any]:
    """Validate a user's ingredient selection and plan conservative duplicate skips.

    This helper is deliberately side-effect free so selection and duplicate logic
    can be covered independently of Home Assistant or live Deglaze requests.
    """
    choice_by_id = {choice["id"]: choice for choice in choices if isinstance(choice, dict) and choice.get("id") and choice.get("text")}
    requested_ids = list(dict.fromkeys(ingredient_ids))
    if not requested_ids:
        raise ValueError("Select at least one recipe ingredient to add.")
    if any(ingredient_id not in choice_by_id for ingredient_id in requested_ids):
        raise ValueError("One or more selected ingredients are no longer available. Reload the recipe and try again.")

    existing_by_key: dict[str, list[dict[str, Any]]] = {}
    for item in existing_items:
        if not isinstance(item, dict):
            continue
        key = normalize_grocery_item_key(item.get("text") or item.get("ingredient"))
        if key:
            existing_by_key.setdefault(key, []).append(item)

    candidates: list[dict[str, str]] = []
    duplicates: list[dict[str, Any]] = []
    for ingredient_id in requested_ids:
        choice = choice_by_id[ingredient_id]
        key = normalize_grocery_item_key(choice["text"])
        matches = existing_by_key.get(key, []) if key else []
        if matches:
            duplicates.append({
                "ingredient_id": ingredient_id,
                "ingredient": choice["text"],
                "matches": [
                    {
                        "text": str(item.get("text") or item.get("ingredient") or "Existing item"),
                        "status": (
                            item.get("status", {}).get("status", "pending")
                            if isinstance(item.get("status"), dict)
                            else item.get("status", "pending")
                        ),
                    }
                    for item in matches[:5]
                ],
            })
            if not include_duplicates:
                continue
        candidates.append(choice)

    return {
        "selected": [choice_by_id[ingredient_id] for ingredient_id in requested_ids],
        "candidates": candidates,
        "duplicates": duplicates,
    }


def _normalized_tag_token(value: Any) -> str | None:
    """Normalize a collection tag for comparisons without altering its display name."""
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.casefold().split())
    return normalized or None


def normalize_recipe_collection_manifest(raw_collections: Any) -> list[dict[str, Any]]:
    """Extract visible user and built-in tag collections from the observed manifest.

    Deglaze returns a wrapper like {"collections": [...], "layout": {...}}. Filters
    such as Recently Added are not recipe tags, so this helper intentionally leaves
    them out of the recipe-library collection selector.
    """
    if isinstance(raw_collections, dict):
        raw_collections = raw_collections.get("collections")
    if not isinstance(raw_collections, list):
        return []

    result: list[dict[str, Any]] = []
    for entry in raw_collections:
        if not isinstance(entry, dict) or entry.get("type", "tag") != "tag":
            continue
        if entry.get("deleted") is True or entry.get("hidden") is True:
            continue
        tag_type = entry.get("tagType") or entry.get("tag_type")
        collection_id = entry.get("id")
        name = entry.get("name")
        if (
            tag_type not in ("user", "system")
            or not isinstance(collection_id, str)
            or not collection_id
        ):
            continue
        if not isinstance(name, str) or not name.strip():
            continue
        user_tags = entry.get("userTags", [])
        system_tags = entry.get("systemTags", [])
        result.append(
            {
                "id": collection_id,
                "name": name.strip(),
                "tag_type": tag_type,
                "source": (
                    entry.get("source")
                    if isinstance(entry.get("source"), str)
                    else tag_type
                ),
                "display_if_empty": entry.get("displayIfEmpty") is True,
                # Private aliases are used only to associate recipe tags with collections.
                "_user_tags": [
                    token for item in user_tags
                    if (token := _normalized_tag_token(item))
                ] if isinstance(user_tags, list) else [],
                "_system_tags": [
                    token for item in system_tags
                    if (token := _normalized_tag_token(item))
                ] if isinstance(system_tags, list) else [],
            }
        )
    return result


def plan_recipe_collection_changes(
    current_ids: list[str] | set[str], desired_ids: list[str] | set[str]
) -> list[dict[str, str]]:
    """Create idempotent collection membership operations for one recipe.

    Removals precede additions so a failed update is easy to describe and
    recover from by refreshing the recipe record. The helper makes no calls.
    """
    current = {item for item in current_ids if isinstance(item, str) and item}
    desired = {item for item in desired_ids if isinstance(item, str) and item}
    return (
        [{"action": "remove", "collection_id": item} for item in sorted(current - desired)]
        + [{"action": "add", "collection_id": item} for item in sorted(desired - current)]
    )


def recipe_collection_ids(
    recipe: dict[str, Any], collections: list[dict[str, Any]]
) -> list[str]:
    """Map a recipe's structured tags to known collection IDs.

    Observed recipe records use tags shaped like {"type": "user", "tag": "Cuban"}
    or {"type": "system", "tag": "main"}. Older/string-only tags are supported
    conservatively by matching the token against any known collection alias.
    """
    raw_tags = recipe.get("tags")
    if not isinstance(raw_tags, list):
        return []
    normalized_tags: list[tuple[str | None, str]] = []
    for tag in raw_tags:
        if isinstance(tag, str):
            token = _normalized_tag_token(tag)
            tag_type = None
        elif isinstance(tag, dict):
            token = _normalized_tag_token(tag.get("tag") or tag.get("name") or tag.get("id"))
            kind = tag.get("type") or tag.get("tagType") or tag.get("tag_type")
            tag_type = kind if kind in ("user", "system") else None
        else:
            continue
        if token:
            normalized_tags.append((tag_type, token))

    matched: list[str] = []
    for collection in collections:
        collection_id = collection.get("id")
        tag_type = collection.get("tag_type")
        if not isinstance(collection_id, str) or tag_type not in ("user", "system"):
            continue
        aliases = {
            token for token in (
                _normalized_tag_token(collection.get("name")),
                *(collection.get("_user_tags", []) if tag_type == "user" else collection.get("_system_tags", [])),
            ) if token
        }
        if any(
            (kind is None or kind == tag_type) and token in aliases
            for kind, token in normalized_tags
        ):
            matched.append(collection_id)
    return matched


class DeglazeApiClient:
    """Asynchronous Firebase + Deglaze client using Home Assistant's aiohttp session."""

    def __init__(
        self,
        session: Any,
        email: str,
        firebase_api_key: str | None = None,
        refresh_token: str | None = None,
        device_id: str = "home-assistant-deglaze",
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
        body = {"email": self.email, "oobCode": parsed_link.oob_code}
        try:
            async with self.session.post(
                FIREBASE_SIGN_IN_URL,
                params={"key": self.firebase_api_key},
                json=body,
            ) as response:
                data = await _read_json(
                    response, FirebaseAuthError, "Firebase rejected the sign-in link"
                )
                if response.status >= 400:
                    raise FirebaseAuthError(
                        _firebase_error_code(data) or "Firebase rejected the sign-in link"
                    )
        except (asyncio.TimeoutError, aiohttp.ClientError):
            raise FirebaseAuthError(
                "Firebase sign-in could not complete because of a network or timeout error."
            ) from None

        if not isinstance(data, dict):
            raise FirebaseAuthError("Firebase returned an unexpected sign-in response.")
        id_token = data.get("idToken")
        refresh_token = data.get("refreshToken")
        user_id = data.get("localId")
        if not id_token or not refresh_token or not user_id:
            raise FirebaseAuthError(
                "Firebase's sign-in response did not contain the expected tokens."
            )
        self._id_token = id_token
        self.refresh_token = refresh_token
        self.user_id = user_id
        self._id_token_expires_at = time.time() + _int_or_default(data.get("expiresIn"), 3600)

    async def async_get_id_token(self, force_refresh: bool = False) -> str:
        """Return a usable ID token, refreshing it as necessary."""
        if (
            not force_refresh
            and self._id_token
            and time.time() < self._id_token_expires_at - 60
        ):
            return self._id_token
        if not self.firebase_api_key or not self.refresh_token:
            raise FirebaseAuthError("No saved Firebase refresh token is available; sign in again.")

        try:
            async with self.session.post(
                FIREBASE_REFRESH_URL,
                params={"key": self.firebase_api_key},
                data={"grant_type": "refresh_token", "refresh_token": self.refresh_token},
            ) as response:
                data = await _read_json(
                    response, FirebaseAuthError, "Firebase token refresh failed"
                )
                if response.status >= 400:
                    raise FirebaseAuthError(
                        _firebase_error_code(data) or "Firebase token refresh failed"
                    )
        except (asyncio.TimeoutError, aiohttp.ClientError):
            raise FirebaseAuthError(
                "Firebase token refresh could not complete because of a network or timeout error."
            ) from None

        if not isinstance(data, dict):
            raise FirebaseAuthError("Firebase returned an unexpected token-refresh response.")
        new_id_token = data.get("id_token")
        new_refresh_token = data.get("refresh_token") or self.refresh_token
        if not new_id_token:
            raise FirebaseAuthError("Firebase token refresh response did not contain an ID token.")
        self._id_token = new_id_token
        self.refresh_token = new_refresh_token
        self.user_id = data.get("user_id") or self.user_id
        self._id_token_expires_at = time.time() + _int_or_default(data.get("expires_in"), 3600)
        if self.on_refresh_token and new_refresh_token:
            self.on_refresh_token(new_refresh_token)
        return self._id_token

    @property
    def default_grocery_list_id(self) -> str:
        """The household list ID observed in Deglaze requests."""
        if not self.user_id:
            raise FirebaseAuthError("The signed-in Deglaze user ID is not available.")
        return f"household:hh-{self.user_id}:d"

    async def async_get_grocery_list(self) -> dict[str, Any]:
        return await self._request_json("GET", "/lists")

    async def async_test_auth_renewal(self) -> dict[str, Any]:
        """Exercise the normal expiry-triggered refresh path and a read-only request.

        Only the in-memory expiry timestamp is moved into the past. No token is
        edited or revoked, and the subsequent GET does not modify Deglaze data.
        """
        self._id_token_expires_at = 0
        return await self.async_get_grocery_list()

    async def async_test_error_handling(
        self,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Inject a local HTTP 503 into one read, then verify a real read recovers.

        The synthetic error never reaches Deglaze. A temporary session wrapper
        intercepts exactly the first GET /lists and supplies a fake 503 response;
        the next GET is delegated to the real Home Assistant session. The same
        request and error-handling code used for ordinary API calls handles both.
        """
        token = await self.async_get_id_token()
        probe_session = _FailFirstListReadSession(self.session)
        probe = DeglazeApiClient(
            probe_session,
            email=self.email,
            firebase_api_key=self.firebase_api_key,
            refresh_token=self.refresh_token,
            device_id=self.device_id,
            on_refresh_token=self.on_refresh_token,
            time_zone=self.time_zone,
        )
        probe.user_id = self.user_id
        probe._id_token = token
        # We already resolved a usable token above. Keep the diagnostic probe
        # from performing a separate token refresh while testing API error flow.
        probe._id_token_expires_at = time.time() + 3600

        try:
            await probe.async_get_grocery_list()
        except DeglazeAPIError as err:
            if str(err) != "Deglaze returned HTTP 503 for GET /lists.":
                raise DeglazeAPIError(
                    "The simulated API failure did not follow the expected safe error path."
                ) from None
        else:
            raise DeglazeAPIError("The simulated HTTP 503 failure was not triggered.")

        payload = await probe.async_get_grocery_list()
        diagnostics = {
            "simulated_failure": "HTTP 503",
            "simulated_failure_origin": "local-only",
            "simulated_failure_handled": True,
            "failure_message_sanitized": True,
            "recovery_read_request": "passed",
            "read_only": True,
        }
        return payload, diagnostics

    async def async_add_grocery_item(
        self,
        text: str,
        *,
        item_id: str,
        suggestion_id: str | None = None,
        manual_category: str | None = None,
        stores: list[Any] | None = None,
    ) -> dict[str, Any]:
        """Add a manual grocery item (there is no observed delete operation)."""
        body: dict[str, Any] = {
            "listId": self.default_grocery_list_id,
            "itemId": item_id,
            "text": text.strip(),
            "ts": int(time.time() * 1000),
            "stores": stores or [],
        }
        if suggestion_id:
            body["suggestionId"] = suggestion_id
        if manual_category:
            body["manualCategory"] = manual_category
        return await self._request_json("POST", "/lists/item", body)

    async def async_create_grocery_store(self, name: str, *, store_id: str) -> dict[str, Any]:
        """Create a store using the request shape observed in Deglaze's web app."""
        name = name.strip()
        store_id = store_id.strip()
        if not name:
            raise ValueError("Store name cannot be blank.")
        if not store_id:
            raise ValueError("Store ID cannot be blank.")
        payload = await self._request_json("POST", "/lists/stores", {"id": store_id, "name": name})
        _data_object(payload, "POST /lists/stores")
        return payload

    async def async_update_grocery_store(
        self, store_id: str, name: str, version: int
    ) -> dict[str, Any]:
        """Rename an existing store using its current version."""
        store_id = store_id.strip()
        name = name.strip()
        if not store_id:
            raise ValueError("Store ID cannot be blank.")
        if not name:
            raise ValueError("Store name cannot be blank.")
        if int(version) < 0:
            raise ValueError("Store version must be non-negative.")
        payload = await self._request_json(
            "POST", "/lists/stores/update", {"id": store_id, "name": name, "version": int(version)}
        )
        _data_object(payload, "POST /lists/stores/update")
        return payload

    async def async_delete_grocery_store(self, store_id: str) -> dict[str, Any]:
        """Delete an existing store definition; associated grocery items remain."""
        store_id = store_id.strip()
        if not store_id:
            raise ValueError("Store ID cannot be blank.")
        payload = await self._request_json("POST", "/lists/stores/delete", {"id": store_id})
        if "data" not in payload or payload.get("data") is False or payload.get("data") is None:
            raise DeglazeAPIError("Deglaze returned an unexpected response for POST /lists/stores/delete.")
        return payload

    async def async_set_grocery_item_stores(
        self, item_id: str, version: int, store_ids: list[str], list_id: str | None = None
    ) -> dict[str, Any]:
        """Set item store associations using the current item version."""
        item_id = item_id.strip()
        if not item_id:
            raise ValueError("Grocery item ID cannot be blank.")
        if int(version) < 0:
            raise ValueError("Grocery item version must be non-negative.")
        normalized_ids: list[str] = []
        for store_id in store_ids:
            if not isinstance(store_id, str) or not store_id.strip():
                raise ValueError("Store IDs must be non-empty strings.")
            store_id = store_id.strip()
            if store_id not in normalized_ids:
                normalized_ids.append(store_id)
        payload = await self._request_json(
            "PATCH",
            "/lists/item",
            {
                "listId": list_id or self.default_grocery_list_id,
                "itemId": item_id,
                "version": int(version),
                "updates": {"stores": normalized_ids},
            },
        )
        _data_object(payload, "PATCH /lists/item")
        return payload

    async def async_set_grocery_item_status(
        self, item_id: str, version: int, status: str, list_id: str | None = None
    ) -> dict[str, Any]:
        """Mark a grocery item pending/completed using its current concurrency version."""
        if status not in ("pending", "completed"):
            raise ValueError("Grocery status must be 'pending' or 'completed'.")
        body = {
            "listId": list_id or self.default_grocery_list_id,
            "itemId": item_id,
            "version": int(version),
            "updates": {"status": {"status": status, "ts": int(time.time() * 1000)}},
        }
        return await self._request_json("PATCH", "/lists/item", body)

    async def async_get_meal_plan(self, start: str, end: str) -> dict[str, Any]:
        """Get a meal-plan range. Both dates are required by the observed endpoint."""
        if end < start:
            raise ValueError("Meal-plan end date must not be before the start date.")
        return await self._request_json(
            "POST", "/planning/get-meal-plan", {"start": start, "end": end}
        )

    async def async_add_meal_plan_item(
        self,
        *,
        recipe_id: str,
        date: str,
        label: str,
        is_leftovers: bool = False,
        plan_item_id: str,
    ) -> dict[str, Any]:
        """Add a recipe to a meal-plan date using the observed payload shape."""
        body = {
            "type": "recipe",
            "id": plan_item_id,
            "date": date,
            "recipeId": recipe_id,
            "label": {"type": "system", "label": label},
            "isLeftovers": bool(is_leftovers),
        }
        return await self._request_json("POST", "/planning/add-item", body)

    async def async_update_meal_plan_item(
        self, *, item_id: str, item_type: str, version: int, updates: dict[str, Any]
    ) -> dict[str, Any]:
        """Update a planned item using the request shape observed in Deglaze's web app."""
        item_id = item_id.strip()
        if not item_id:
            raise ValueError("Meal-plan item ID cannot be blank.")
        if item_type not in ("recipe", "note"):
            raise ValueError("Unsupported meal-plan item type.")
        if int(version) < 0:
            raise ValueError("Meal-plan item version must be non-negative.")
        allowed_keys = {"date", "label", "isLeftovers"}
        if not isinstance(updates, dict) or not updates or set(updates) - allowed_keys:
            raise ValueError("Meal-plan updates must contain only date, label, or isLeftovers.")
        body = {"id": item_id, "type": item_type, "version": int(version), "updates": updates}
        payload = await self._request_json("POST", "/planning/update-item", body)
        _data_object(payload, "POST /planning/update-item")
        return payload

    async def async_remove_meal_plan_item(self, item_id: str) -> dict[str, Any]:
        """Remove a planned item using the observed Deglaze web-app request shape."""
        item_id = item_id.strip()
        if not item_id:
            raise ValueError("Meal-plan item ID cannot be blank.")
        payload = await self._request_json("POST", "/planning/remove-item", {"id": item_id})
        _data_object(payload, "POST /planning/remove-item")
        return payload

    async def async_edit_recipe_collection_membership(
        self, *, recipe_id: str, collection_id: str, action: str
    ) -> dict[str, Any]:
        """Add or remove one recipe from an existing Deglaze tag collection.

        The payload matches the web app's observed /recipes/bulk-edit action:
        {type: bulkAddRemoveTag, action: add|remove, collectionId, recipeIds}.
        It only edits membership; collection definitions themselves are untouched.
        """
        recipe_id = recipe_id.strip()
        collection_id = collection_id.strip()
        if not recipe_id:
            raise ValueError("Recipe ID cannot be blank.")
        if not collection_id:
            raise ValueError("Collection ID cannot be blank.")
        if action not in ("add", "remove"):
            raise ValueError("Collection action must be 'add' or 'remove'.")
        payload = await self._request_json(
            "POST",
            "/recipes/bulk-edit",
            {
                "type": "bulkAddRemoveTag",
                "action": action,
                "collectionId": collection_id,
                "recipeIds": [recipe_id],
            },
        )
        # The web app consumes response.data.recipeVersions after this operation.
        # Requiring the observed data object avoids treating a malformed 200 as success.
        _data_object(payload, "POST /recipes/bulk-edit")
        return payload

    async def async_sync_recipes(
        self,
        existing: dict[str, dict[str, Any]] | None = None,
        version: int | None = None,
        existing_collections: Any = None,
    ) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
        """Fetch the personal recipe library with cursor pagination and version overlap.

        The Deglaze web bundle sends an unversioned first load, then uses
        max(0, previous_version - 5000) for incremental loads. A 5-second overlap
        helps avoid missing adjacent updates when a recipe and library version race.
        """
        recipe_cache = dict(existing or {})
        is_full_sync = version is None or version <= 0 or not recipe_cache
        since_version = None if is_full_sync else max(0, int(version) - 5000)
        cursor: str | None = None
        seen_cursors: set[str] = set()
        pages = 0
        latest_version = int(version or 0)
        # A paged/incremental response may omit collection metadata. Keep the last
        # known manifest in that case so a missing optional field does not clear the UI.
        collections: Any = existing_collections
        limit_info: Any = None
        received = 0

        while True:
            body: dict[str, Any] = {}
            if since_version is not None:
                body["sinceVersion"] = since_version
            if cursor:
                body["start"] = cursor
            payload = await self._request_json("POST", "/recipes/get-list", body)
            data = _data_object(payload, "POST /recipes/get-list")
            page_recipes = data.get("recipes")
            if not isinstance(page_recipes, list):
                raise DeglazeAPIError(
                    "Deglaze returned no recipe array from POST /recipes/get-list."
                )
            pages += 1
            latest_version = max(latest_version, _int_or_default(data.get("version"), 0))
            for recipe in page_recipes:
                if isinstance(recipe, dict) and isinstance(recipe.get("id"), str):
                    recipe_cache[recipe["id"]] = recipe
                    latest_version = max(
                        latest_version, _int_or_default(recipe.get("version"), 0)
                    )
                    received += 1
            if data.get("collections") is not None:
                collections = data["collections"]
            if "limit" in data:
                limit_info = data["limit"]
            next_cursor = data.get("next")
            if not isinstance(next_cursor, str) or not next_cursor:
                break
            if next_cursor in seen_cursors:
                raise DeglazeAPIError("Deglaze repeated a recipe pagination cursor.")
            seen_cursors.add(next_cursor)
            cursor = next_cursor
            if pages >= 100:
                raise DeglazeAPIError("Recipe synchronization stopped after 100 pages.")

        meta = {
            "version": latest_version,
            "pages": pages,
            "received": received,
            "full_sync": is_full_sync,
            "collections": collections,
            "limit": limit_info,
        }
        return recipe_cache, meta

    async def _request_json(
        self, method: str, path: str, body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Issue a Deglaze request and retry one time after a 401/token refresh."""
        token = await self.async_get_id_token()
        status, payload = await self._do_deglaze_request(method, path, token, body)
        if status == 401:
            token = await self.async_get_id_token(force_refresh=True)
            status, payload = await self._do_deglaze_request(method, path, token, body)
        if status >= 400:
            raise DeglazeAPIError(f"Deglaze returned HTTP {status} for {method} {path}.")
        if not isinstance(payload, dict):
            raise DeglazeAPIError(f"Deglaze returned an unexpected JSON response for {method} {path}.")
        return payload

    async def _do_deglaze_request(
        self, method: str, path: str, token: str, body: dict[str, Any] | None
    ) -> tuple[int, Any]:
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
        url = DEGLAZE_BASE_URL + path
        verb = method.upper()
        try:
            if verb == "GET":
                request = self.session.get(url, headers=headers)
            elif verb == "POST":
                request = self.session.post(url, headers=headers, json=body or {})
            elif verb == "PATCH":
                request = self.session.patch(url, headers=headers, json=body or {})
            else:
                raise ValueError(f"Unsupported HTTP method: {verb}")

            async with request as response:
                if response.status == 401:
                    return response.status, None
                payload = await _read_json(
                    response, DeglazeAPIError, f"Deglaze request {verb} {path} failed"
                )
                return response.status, payload
        except (asyncio.TimeoutError, aiohttp.ClientError):
            raise DeglazeAPIError(
                f"Deglaze request {verb} {path} failed due to a network or timeout error."
            ) from None


class _SyntheticResponse:
    """Minimal HTTP response used only by the safe error-handling diagnostic."""

    def __init__(self, status: int, payload: dict[str, Any]) -> None:
        self.status = status
        self._payload = payload

    async def __aenter__(self) -> "_SyntheticResponse":
        return self

    async def __aexit__(self, *_args: Any) -> bool:
        return False

    async def json(self, content_type: Any = None) -> dict[str, Any]:
        return self._payload


class _FailFirstListReadSession:
    """Intercept one GET /lists with a local 503; delegate every other call."""

    def __init__(self, session: Any) -> None:
        self._session = session
        self._did_inject_failure = False

    def get(self, url: str, **kwargs: Any) -> Any:
        if not self._did_inject_failure and url == DEGLAZE_BASE_URL + "/lists":
            self._did_inject_failure = True
            # Deliberately private-looking body proves response content is not surfaced.
            return _SyntheticResponse(503, {"error": "SIMULATED_PRIVATE_RESPONSE_BODY"})
        return self._session.get(url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> Any:
        return self._session.post(url, **kwargs)

    def patch(self, url: str, **kwargs: Any) -> Any:
        return self._session.patch(url, **kwargs)


async def _read_json(response: Any, error_type: type[Exception], fallback: str) -> Any:
    """Read JSON and raise safe errors without including response bodies or credentials."""
    try:
        payload = await response.json(content_type=None)
    except (asyncio.TimeoutError, aiohttp.ClientError):
        raise error_type(f"{fallback} due to a network or timeout error.") from None
    except Exception:
        if response.status >= 400:
            raise error_type(f"{fallback} (HTTP {response.status}).") from None
        raise error_type("The server returned a non-JSON response.") from None
    if not isinstance(payload, (dict, list)):
        raise error_type("The server returned an unexpected response format.")
    return payload


def _firebase_error_code(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    error = payload.get("error")
    if not isinstance(error, dict):
        return None
    message = error.get("message")
    if isinstance(message, str):
        return message.split(" ", maxsplit=1)[0][:80]
    return None


def _int_or_default(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
