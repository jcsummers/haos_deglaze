# Appendix — Lovelace cards, entities, actions, and troubleshooting

This appendix supplements the Deglaze Home Assistant integration `README.md` for **version 1.0.0**. It documents the four custom Lovelace cards, their visual and YAML configuration, the summary sensors, registered service actions, card-internal WebSocket commands, and common troubleshooting steps.

> **Important:** This is an unofficial community integration for Deglaze. Deglaze's API is undocumented and can change. Back up Home Assistant before upgrading, use a low-stakes item for write-operation tests, and verify ambiguous writes on the Deglaze website before retrying them.

## 1. Lovelace cards at a glance

| Card | Custom card type | Main functions | Recommended Sections width |
|---|---|---|---:|
| Grocery List | `custom:deglaze-grocery-add-card` | Add items, view and search the list, filter status, mark bought/to buy, manage stores, assign stores, group and sort | 6–12 columns |
| Upcoming Meals | `custom:deglaze-upcoming-meals-card` | Show a configurable number of upcoming meals and filter by meal type | 6 columns |
| Weekly Meal Planner | `custom:deglaze-weekly-meal-planner-card` | Browse a week, display 1–7 days, edit meal date/slot/leftovers, and remove a planned meal after confirmation | 12 columns |
| Recipe Library | `custom:deglaze-recipe-library-card` | Search and browse recipes, filter collections, view ingredients/instructions, edit collection membership, add meals to the plan, and add selected ingredients to groceries | 12 columns |

The cards use one frontend resource: `/local/deglaze-cards.js`. Register it as a **JavaScript Module** under **Settings → Dashboards → Resources**. After updating the JavaScript, change its URL's version query (for example, `/local/deglaze-cards.js?v=1.0.0`) and hard-refresh the browser to avoid cached code.

## 2. Editing cards: visual editor and YAML

### Visual editor (recommended for routine changes)

1. Open the dashboard containing the Deglaze card.
2. Select the dashboard menu and choose **Edit dashboard**.
3. Select the card and choose **Edit**.
4. Use the card's configuration form to change its title and card-specific settings.
5. Save the card, then save the dashboard.

All four cards provide visual configuration editors. The available controls are:

- **Grocery List:** title, input placeholder, initial filter, initial grouping, initial sorting, optional manual category, service/domain settings, and preferred grid width.
- **Upcoming Meals:** title, number of meals, refresh interval, included meal types, integration domain, and preferred grid width.
- **Weekly Meal Planner:** title, number of days displayed (1–7), refresh interval, integration domain, and preferred grid width.
- **Recipe Library:** title, integration domain, and preferred grid width.

For **Sections** dashboards, the preferred-width setting supplies an initial column preference and Home Assistant's native resize controls can then adjust the card. The recipe library and weekly planner default to full width because their content benefits from space. Masonry dashboards do not use the cards' grid-column sizing values.

### Manual YAML editing

In dashboard edit mode, open the card's YAML/code editor (the label varies slightly by Home Assistant version). Paste or edit the relevant example below and save. Keep the `type` value exactly as shown.

#### Grocery List

```yaml
type: custom:deglaze-grocery-add-card
title: Grocery list
placeholder: e.g. chickpeas
default_filter: pending
default_group_by: none
default_sort_by: alpha
grid_columns: 6
```

Supported initial filters: `pending`, `all`, `completed`.

Supported initial grouping: `none`, `store`, `category`.

Supported initial sorting: `alpha`, `newest`.

Other optional settings include `manual_category`, `service`, and `domain`. The card defaults to the **To Buy** view. It intentionally does not provide a grocery-item delete button; Deglaze's supported grocery workflow marks items complete rather than deleting them.

#### Upcoming Meals

```yaml
type: custom:deglaze-upcoming-meals-card
title: Upcoming meals
domain: deglaze_poc
count: 5
refresh_interval: 60
meal_types:
  - Breakfast
  - Lunch
  - Dinner
  - Snack
grid_columns: 6
```

`count` can be from 1 to 20. `refresh_interval` is in seconds. If no meal types are selected, the card shows all types. It retrieves meal data through the integration's WebSocket API rather than relying on a particular sensor entity ID. An older `entity` option remains only as a fallback.

#### Weekly Meal Planner

```yaml
type: custom:deglaze-weekly-meal-planner-card
title: Weekly meal planner
domain: deglaze_poc
display_days: 7
refresh_interval: 120
grid_columns: 12
```

`display_days` accepts 1–7 and defaults to 7. The integration still retrieves the full Monday–Sunday week; the option only limits visible day rows. Previous/next navigation moves by a full week. The grid has aligned day rows with Breakfast, Lunch, Dinner, and Snack columns, plus an Other column when needed. Users can edit date, meal slot, and leftovers; removal asks for confirmation. Replacing a planned recipe directly is not supported: remove the old plan item and add the intended recipe from the Recipe Library card.

#### Recipe Library

```yaml
type: custom:deglaze-recipe-library-card
title: Recipe library
domain: deglaze_poc
grid_columns: 12
```

The card supports title search and collection filtering. It distinguishes user-created collections from built-in categories, shows collection counts and membership badges, displays recipe ingredients/instructions, and provides controls to organize a recipe's membership in existing visible collections. It also allows adding a selected recipe to the meal plan and selecting ingredients to add to the grocery list.

## 3. Integration sensors

The integration creates four summary sensors. Their **entity IDs can vary** if Home Assistant previously assigned or you manually changed an ID; check **Developer Tools → States** or **Settings → Devices & services → Entities** for the exact IDs in your installation. The device is named **Deglaze**.

### Grocery List sensor

- **Display name:** `Grocery List`
- **Typical ID pattern:** `sensor.*_grocery_list` (for example, the existing installation may use `sensor.kitchen_deglaze_grocery_list`).
- **State:** number of pending/to-buy grocery items, in `items`.
- **Attributes:** `pending_count`, `completed_count`, `item_count`, `list_count`, `schema_recognized`, `list_id`, and `last_updated`.
- **Important:** the sensor deliberately does **not** store the full grocery `items` array in its attributes. The full list is fetched over the authenticated WebSocket API by the card, which avoids oversized Recorder attributes.

### Recipe Library sensor

- **Display name:** `Recipe Library`
- **Typical ID pattern:** `sensor.*_recipe_library`.
- **State:** number of active recipes, in `recipes`.
- **Attributes:** recipe synchronization metadata including `version`, `last_synced`, `last_page_count`, `last_received_count`, `last_sync_was_full`, `archived_count`, `deleted_count`, and `sync_error`.
- This is a count/diagnostic sensor, not one entity per recipe. Recipe details are browsed in the Recipe Library card.

### Meal Plan sensor

- **Display name:** `Meal Plan`
- **Typical ID pattern:** `sensor.*_meal_plan`.
- **State:** count of active planned meals in the currently synchronized meal-plan range, in `meals`.
- **Attributes:** `start`, `end`, `version`, `last_synced`, `sync_error`, and compact `items` summaries with fields such as item ID/type/date/recipe ID/label/leftovers/version and recipe title where available.
- The Weekly Meal Planner requests its selected date range directly, so it is not limited to the sensor's synchronized range.

### API Status sensor

- **Display name:** `API Status`
- **Existing ID:** the original POC ID is preserved where applicable; it may appear as `sensor.deglaze_poc_grocery_api_status`.
- **State:** `connected`, `partial`, or `degraded`. `degraded` indicates a grocery error; `partial` indicates errors in one or more other data areas; `connected` indicates no recorded coordinator errors.
- **Attributes:** grocery summary fields, `recipe_count`, `recipe_sync_error`, `meal_plan_sync_error`, `last_checked`, and an `errors` mapping.

An entity that is unavailable or showing stale counts does not always mean all features have failed. Inspect the API Status attributes and logs to see whether the error is limited to groceries, recipes, or meal planning.

## 4. Registered service actions

The service domain is **`deglaze_poc`**. In Home Assistant, use **Developer Tools → Actions** and select the action name below. The fields listed are the expected inputs. IDs should be copied from the current integration/card data rather than guessed.

| Service action | Required fields | Optional fields / behavior |
|---|---|---|
| `deglaze_poc.add_grocery_item` | `text` | `suggestion_id`, `manual_category`, `stores` (list of existing store IDs). Adds an item; does not delete items. |
| `deglaze_poc.set_grocery_item_status` | `item_id`, `status` | `status` is `pending` or `completed`. |
| `deglaze_poc.create_grocery_store` | `name` | Creates a store definition. |
| `deglaze_poc.rename_grocery_store` | `store_id`, `name` | Retrieves the current store version before updating. |
| `deglaze_poc.delete_grocery_store` | `store_id` | Deletes the store definition only. Grocery items remain, but lose that store association. The card asks for confirmation. |
| `deglaze_poc.set_grocery_item_stores` | `item_id`, `store_ids` | `store_ids` is the complete desired set; an empty list clears assignments. Uses the current item version and verifies the refreshed result. |
| `deglaze_poc.add_meal_plan_item` | `recipe_id`, `date`, `label` | `is_leftovers` optional. `date` uses `YYYY-MM-DD`; `label` is Breakfast, Lunch, Dinner, or Snack. `recipe_id` must be the full namespaced ID from the Recipe Library. |
| `deglaze_poc.update_meal_plan_item` | `item_id`, `item_type`, `version` | At least one of `date`, `label`, `is_leftovers`; `item_type` is `recipe` or `note`. Uses the current version. This service does not replace the recipe ID. |
| `deglaze_poc.remove_meal_plan_item` | `item_id` | Removes the planned meal entry from Deglaze. This is not a grocery-item deletion service. |
| `deglaze_poc.set_recipe_collections` | `recipe_id`, `collection_ids` | `collection_ids` is the complete desired list of IDs for existing visible collections. Changes membership; does not create/delete collections. |
| `deglaze_poc.refresh` | None | Refreshes grocery, recipe-library, and meal-plan data. |
| `deglaze_poc.test_auth_renewal` | None | Diagnostic action with response: forces the cached token's expiry time to the past in memory, runs normal Firebase refresh, then verifies a read-only grocery request. Does not change grocery items. |
| `deglaze_poc.test_error_handling` | None | Diagnostic action with response: injects a local synthetic HTTP 503 into one grocery read, checks safe error handling, then makes a real read-only recovery request. The synthetic failure is not sent to Deglaze. |

The Recipe Library's **select ingredients → review → confirm** workflow is implemented through the integration's authenticated WebSocket command rather than a separate Developer Tools service action. It checks for possible duplicates, skips duplicate candidates by default, can optionally assign selected ingredients to existing stores, adds items sequentially, and refreshes/verifies the result. If a write times out or verification fails, refresh and compare with Deglaze before retrying; do not assume the write failed.

## 5. Card-internal WebSocket commands

These are used by the Lovelace cards and are **not** normal Developer Tools service actions:

- `deglaze_poc/grocery/list` — returns the current compact grocery item list, store choices, counts, and sync status.
- `deglaze_poc/meal-plan` — returns synchronized planned meals and compact recipe-title metadata.
- `deglaze_poc/meal-plan/range` — fetches a requested date range for the Weekly Meal Planner.
- `deglaze_poc/recipes/list` — returns active recipe summaries and collection definitions.
- `deglaze_poc/recipe` — returns the selected recipe details, including normalized ingredient choices, without deliberately recording a recipe view.
- `deglaze_poc/recipe/add-ingredients` — validates and adds selected recipe ingredients through the recipe-to-grocery workflow.

If a card reports an unknown/missing command after an integration update, perform a full Home Assistant restart to load the Python handlers, verify that the frontend resource points to the intended JavaScript version, and hard-refresh the browser.

## 6. Troubleshooting guide

### The integration fails to load during startup

- Check **Settings → System → Logs** for the first traceback line that points into `custom_components/deglaze_poc`.
- Confirm the folder is named exactly `custom_components/deglaze_poc`; do not rename the `deglaze_poc` domain.
- Replace the complete integration folder with the files from the release package instead of mixing files from several versions, then fully restart Home Assistant.
- The `vol.ensure_list` import failure seen in 0.9.0 was fixed in 0.9.1. Do not use the 0.9.0 package; use 1.0.0 or newer compatible builds.

### A card says “Custom element doesn't exist”

- In **Settings → Dashboards → Resources**, confirm `/local/deglaze-cards.js?v=1.0.0` is registered as **JavaScript Module**.
- Confirm `www/deglaze-cards.js` exists under the Home Assistant configuration directory.
- Hard-refresh the browser and check the browser developer console for JavaScript syntax or loading errors.
- Avoid duplicate resource entries pointing to old versions of the same file.

### A card stays on “Loading…” indefinitely

- Check whether the card shows a specific message and inspect the Home Assistant logs for WebSocket warnings/errors.
- Fully restart Home Assistant after replacing Python integration code; refreshing the dashboard alone does not register new backend commands.
- The weekly planner's “coroutine was never awaited” issue in 0.7.0 was fixed in 0.7.1. Use a release containing the async WebSocket handler fix.
- If only one feature fails (for example, weekly range loading), inspect that command's error before changing the entire integration.

### The card loads but reports “Unknown command”, “not found”, or no data

- Ensure the integration config entry is loaded and the API Status sensor is not unavailable.
- Restart Home Assistant after any Python integration update.
- Verify that the card's `domain` setting is `deglaze_poc` unless the integration domain was deliberately changed.
- Check the relevant sync error in the API Status, Recipe Library, or Meal Plan sensor attributes.

### Authentication has expired or API Status is degraded/partial

1. Inspect **Settings → System → Logs** for the integration's sanitized error.
2. Run `deglaze_poc.test_auth_renewal` from Developer Tools → Actions. A passing result verifies the stored refresh token and a read-only `GET /lists` request.
3. If Firebase explicitly rejects the saved refresh token, reconfigure the integration using a fresh Deglaze email sign-in link. Do not paste the full magic link or any access/refresh token into chat or logs; the link contains a one-time credential.
4. If token refresh succeeds but the read request fails, investigate connectivity or a Deglaze API response error instead of repeatedly signing in.

### The grocery card shows no items or stale counts

- Press the card's Refresh button or run `deglaze_poc.refresh`.
- Check the Grocery List sensor and the API Status `errors` attribute.
- The complete grocery list is delivered over WebSocket; it is intentionally not stored in Grocery List sensor attributes. Do not expect an `items` attribute on the Grocery List sensor.
- If the sensor has an oversized-attributes Recorder warning, confirm the installed version is using the summary-only sensor implementation. Replace any older sensor code and restart.

### A write operation returns an error or an uncertain/partial result

- Refresh the grocery list or meal-plan week and compare it with Deglaze before trying the action again. A timeout can occur after a remote write has succeeded.
- For stale grocery-item versions, reload the list so the integration gets the latest item version, then retry only after checking the remote state.
- Recipe-to-grocery duplicate detection is heuristic, not perfect. Similar items may be false positives and differently worded duplicates may be missed. Duplicate candidates are skipped by default; use the override only when intentional.
- Ingredient additions are sequential. If a batch stops partway through, inspect which items arrived before confirming or retrying another batch.

### A store assignment or store filter appears wrong

- Refresh the grocery list and verify the store exists in Deglaze.
- Confirm the item is associated with the intended store; an item can belong to multiple stores and will appear in multiple store groups.
- Deleting a store removes its store definition and association, not the grocery items themselves.
- Items without a store or category should remain visible under **Unassigned** or **Uncategorized** rather than disappearing.

### A meal edit does not appear where expected

- Refresh the week and verify the date/slot on Deglaze.
- The Weekly Meal Planner displays only the first `display_days` of the selected seven-day week. A meal moved to a hidden day may still be in the fetched week but outside the displayed rows; temporarily set `display_days: 7` to inspect the whole week.
- Week navigation moves by seven days. The card currently edits date, meal slot, and leftovers; changing the recipe itself is not supported through the update action.
- Removing a planned meal permanently removes that plan entry. Verify that the correct item was selected before confirming removal.

### The recipe count or collection memberships differ from Deglaze

- Press Refresh in the Recipe Library card and allow the synchronization to finish.
- Check the Recipe Library sensor's `sync_error`, `last_synced`, and `last_sync_was_full` attributes.
- Collections show existing visible collection definitions and recipe tag memberships. Hidden/deleted collections and non-tag filters may not appear in the selector.
- Collection membership editing applies to existing visible collections; it does not create, rename, hide, or delete collection definitions.

### Card width or visual editor options look wrong

- Hard-refresh the dashboard after updating the JavaScript resource version.
- Use the card's visual editor for per-card options, then save both the card and dashboard.
- In Sections dashboards, preferred grid columns are sizing hints; use Home Assistant's resize controls to fine-tune card width. Masonry dashboards do not honor `grid_columns`.
- The Recipe Library defaults to full width. The Weekly Meal Planner is also best tested at 12 columns; narrower cards may use horizontal scrolling for the meal-slot matrix.

### How to collect useful diagnostics safely

Include the integration version, the exact card message, which action was run, the relevant sanitized log lines, and whether the API Status sensor is `connected`, `partial`, or `degraded`. Do **not** include Firebase magic links, `oobCode` values, access tokens, refresh tokens, API credentials, or private grocery/recipe content unless item text is essential and has been redacted.

## 7. Safety and behavior notes

- The integration reuses passwordless Firebase sign-in. A sign-in email link is a one-time credential; do not open it before the configured setup flow asks you to paste it, and do not share it.
- The integration's observed Deglaze API is undocumented. Endpoints and payloads can change independently of Home Assistant.
- Grocery item removal is not implemented; use pending/completed status. Deleting a **store definition** is supported and removes its association from items but leaves the items intact.
- The recipe-to-grocery flow preserves the wording/quantities supplied by Deglaze. Automatic scaling, pantry-staple exclusion, and recipe replacement in an already-planned meal are not included.
- Diagnostic actions make read-only grocery-list requests. `test_error_handling` substitutes a local synthetic HTTP 503 for one request; that failure is not sent to Deglaze.
- Keep the small, summary-only Grocery List sensor attributes to avoid Home Assistant Recorder attribute-size warnings. The full grocery item list is obtained through the card's authenticated WebSocket command.
