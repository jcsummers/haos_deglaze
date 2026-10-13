# Deglaze Home Assistant integration — 1.0.0 stable release

## Release status

**Version 1.0.0 is the first stable release.** It was promoted from the `1.0.0-rc.1` candidate after it was confirmed that the live release checks passed in their Home Assistant environment.

### Installation and post-upgrade check

1. Back up Home Assistant and retain the known-working 0.9.1 package for rollback.
2. Extract the package and replace `config/custom_components/deglaze_poc/` with the included folder; keep the folder name unchanged.
3. Copy `www/deglaze-cards.js` to `config/www/deglaze-cards.js`. In **Settings → Dashboards → Resources**, edit the existing JavaScript Module resource to `/local/deglaze-cards.js?v=1.0.0` rather than creating a duplicate.
4. Restart Home Assistant fully and hard-refresh the browser. Confirm the existing configuration entry reconnects and the logs contain no new startup/import errors.
5. Confirm the grocery sensor stores summary attributes only and that grocery, store, recipe, collection, and meal-planning workflows remain functional.
6. Keep a backup and check logs periodically for errors caused by changes to Deglaze's undocumented API.

---

## Files

- `custom_components/deglaze_poc/` — Home Assistant integration
- `www/deglaze-cards.js` — all four custom Lovelace cards (one dashboard resource)
- `lovelace-dashboard-example.yaml` — copy/paste dashboard example
- `tests/` — local API tests

## Install or upgrade in a test environment

1. **Back up your Home Assistant configuration.** Prefer a staging/test instance. Do not replace your known-working production build before validating this UI build.
2. Extract the archive. Copy `custom_components/deglaze_poc/` into your Home Assistant configuration directory at `config/custom_components/deglaze_poc/`, replacing the existing folder while preserving the folder name exactly.
3. Copy `www/deglaze-cards.js` into `config/www/deglaze-cards.js`. Create the `www` directory if it does not exist.
4. Restart Home Assistant. Confirm the existing Deglaze config entry still loads and check the API Status sensor. The Recipe Library sensor should remain a count sensor, not hundreds of recipe sensors.
5. Register the frontend resource. In **Settings → Dashboards → Resources**, add URL `/local/deglaze-cards.js?v=1.0.0` with resource type **JavaScript Module**. If a resource for `/local/deglaze-cards.js` already exists, edit it to append `?v=1.0.0` so the browser does not keep using the previously cached JavaScript. If you have just created `www`, restarting first is recommended; then hard-refresh the browser.
6. Add the cards using the example YAML below or from `lovelace-dashboard-example.yaml`. All four custom cards have visual configuration editors. In the card editor, set the title, integration domain, card-specific options, and preferred Sections width. The recipe browser defaults to 12 columns. Use native dashboard resize handles for per-card sizing in Sections views. The updated meals card no longer requires an `entity` option. The legacy `entity` option is still accepted only as a fallback if the WebSocket command is unavailable.

## Lovelace configuration examples

### 1. Grocery list, store management, and ingredient quick add

```yaml
type: custom:deglaze-grocery-add-card
title: Grocery list
placeholder: e.g. chickpeas
default_filter: pending
default_group_by: none
default_sort_by: alpha
```

Press Enter or click **Add item**. The card also loads the current list, shows pending/completed counts, supports search and status filters, and exposes **Mark bought** / **Mark to buy** actions. It can manage stores, assign one or more stores to an item, filter by store, group by store/category, and sort alphabetically or newest-first. The default filter is **To buy**; use `default_filter: all` or `default_filter: completed` to change the initial view. Optional settings `default_group_by: store|category|none` and `default_sort_by: alpha|newest` configure the initial presentation. The optional `service` configuration can override the `domain.service` string if your local integration domain differs. `manual_category` can optionally be configured for the service call. There is intentionally no grocery-item delete button.

### 2. Upcoming meals

```yaml
type: custom:deglaze-upcoming-meals-card
title: Upcoming meals
domain: deglaze_poc
count: 5
```

`count` is customizable from 1 to 20, and the visual editor can restrict results to selected meal types. Leaving all meal types unchecked shows all types. The card retrieves synchronized meal-plan items over Home Assistant WebSocket, independently of the sensor entity ID, filters out deleted entries and dates before today, and offers a manual Refresh button. Since the observed API returns date-level entries rather than specific meal times, it shows all entries for today as upcoming. The optional `entity` setting from earlier versions is retained as a fallback only.

### 3. Weekly meal planner (aligned day rows in 0.7.2; configurable displayed days in 0.7.3; async handler fixed in 0.7.1)

```yaml
type: custom:deglaze-weekly-meal-planner-card
title: Weekly meal planner
domain: deglaze_poc
display_days: 7
grid_columns: 12
refresh_interval: 120
```

The planner opens to the current Monday–Sunday week. Use the arrows to move backward/forward seven days, **This week** to return, or **Refresh** to reload the selected range. Edit a meal to change its date, choose Breakfast/Lunch/Dinner/Snack, or toggle leftovers. Choose **Remove**, then **Confirm remove**, to delete the planned meal from Deglaze. The card uses `deglaze_poc/meal-plan/range`, `deglaze_poc.update_meal_plan_item`, and `deglaze_poc.remove_meal_plan_item`. A save is verified against a refreshed copy of the visible week. If a meal is moved out of the displayed week, the card asks you to verify any other edits on Deglaze. Recipe replacement is not supported yet; use the current recipe card to add the intended replacement after removing the old planned item.

### 4. Recipe library / detail viewer / add to meal plan

```yaml
type: custom:deglaze-recipe-library-card
title: Recipe library
```

This card calls the integration's authenticated WebSocket commands to get the recipe list, visible collection definitions, and full details for the selected recipe. Use **Browse collections** to choose one of your own collections (such as Cuban or Cooked & Liked) or a built-in category (such as Breakfast or Main Course). Collection selection and title search work together; choosing **All recipes** clears the collection filter. Counts are shown beside collection names, and recipe collection badges appear in the list and selected recipe details. Hidden/deleted collections and non-tag filters are excluded. In 0.6.0, the selected recipe also has an **Organize collections** checklist that can add or remove membership in existing visible collections. Saving calls the integration's `set_recipe_collections` action, which uses the observed bulk-edit request shape, refreshes recipe data, and verifies the resulting membership before reporting success. The card's **Refresh** button calls the integration's refresh service first. The **Add to plan** action uses `deglaze_poc.add_meal_plan_item`.

## Visual card editors and sizing

- **Grocery editor:** title, placeholder, initial list filter, initial grouping (none/store/category), initial sorting (alphabetical/newest), optional manual category, service/domain, and preferred grid columns.
- **Upcoming meals editor:** title, meal count, refresh interval, included meal types, integration domain, and preferred grid columns.
- **Weekly meal planner editor:** title, displayed days (1–7, default 7), refresh interval, integration domain, and preferred grid columns. Full width (12 columns) is recommended for the meal-slot matrix.
- **Recipe library editor:** title, integration domain, and preferred grid columns (6, 9, or 12). It defaults to 12 columns to give the recipe browser and details room.
- **Sections dashboards:** the cards expose `getGridOptions()` so Home Assistant offers native resizing with appropriate minimum widths. Preferred columns initialize the card size; the dashboard resize control remains the best way to fine-tune a particular card. Masonry dashboards do not honor grid-column sizing. The recipe card uses CSS container queries to stack the recipe list/details when the actual card width is narrow.

If an existing card does not immediately show the visual editor after upgrading, hard-refresh the dashboard browser after updating the JavaScript resource URL.

## Existing service actions

- `deglaze_poc.add_grocery_item`: `text`, optional `suggestion_id`, optional `manual_category`, and optional `stores` (list of existing store IDs).
- `deglaze_poc.create_grocery_store`: `name`.
- `deglaze_poc.rename_grocery_store`: `store_id`, `name`; the integration retrieves the current store version before calling Deglaze.
- `deglaze_poc.delete_grocery_store`: `store_id`; only the store definition is removed, not the grocery items. The card confirms before invoking it.
- `deglaze_poc.set_grocery_item_stores`: `item_id`, `store_ids` (complete desired set; empty list clears all assignments). The integration fetches a current item version, validates the store IDs, submits a version-aware PATCH, and verifies the refreshed result.
- `deglaze_poc.set_grocery_item_status`: `item_id` from the grocery card/WebSocket list response, and `status` of `pending` or `completed`. The sensor intentionally no longer exposes the full item list as attributes.
- `deglaze_poc.add_meal_plan_item`: full `recipe_id`, `date` as `YYYY-MM-DD`, `label` as `Breakfast`, `Lunch`, `Dinner`, or `Snack`, optional `is_leftovers`.
- `deglaze_poc.update_meal_plan_item`: `item_id`, `item_type`, and current `version`, plus at least one of `date`, `label`, or `is_leftovers`. It only updates these supported fields; don't supply a recipe ID through this service.
- `deglaze_poc.remove_meal_plan_item`: `item_id` of a planned meal. This permanently removes that plan entry from the Deglaze plan; the Lovelace card asks for confirmation first.
- `deglaze_poc.set_recipe_collections`: a `recipe_id` and `collection_ids` array representing the complete desired set of existing visible collection IDs. The service changes membership only; it does not create or delete collection definitions. The recipe card invokes this when you save its **Organize collections** checklist.
- `deglaze_poc.refresh`: manually refresh grocery data, recipe library, and meal plan.
- `deglaze_poc.test_auth_renewal`: a no-input diagnostic action that simulates an expired cached access token in memory, runs the usual Firebase refresh-token exchange, and validates the resulting ID token with a read-only grocery-list request. It supports an action response so the test result can be viewed in Home Assistant. It does not add, complete, or remove items.
- `deglaze_poc.test_error_handling`: a no-input diagnostic action that intercepts exactly one `GET /lists` in a temporary client wrapper and substitutes a synthetic HTTP 503 response locally. It checks that the ordinary API request path converts the error into a sanitized integration error, then makes one real read-only `GET /lists` request. The synthetic error is not sent to Deglaze; no grocery items are changed. It supports an action response.

## Detailed test: authentication renewal without waiting

This test is intended for the local/test Home Assistant instance. It uses the existing saved Firebase refresh token; it does not require a new magic link or change the token itself.

### Before you start

1. Back up the Home Assistant configuration. The test does not change remote data, but keep the known-working integration build available in case an upgrade needs to be rolled back.
2. Install/upgrade the integration files from this package in `custom_components/deglaze_poc/` and restart Home Assistant. Keep the folder/domain name `deglaze_poc` unchanged.
3. Confirm the Deglaze integration loads normally and the API Status sensor reports connected before running the test. If the integration is already unavailable, resolve that first; the diagnostic is intended to test renewal on a functioning account.

### Run the action

1. Open **Developer Tools → Actions** in Home Assistant.
2. Find and select **Deglaze: Test authentication renewal** (service/action ID `deglaze_poc.test_auth_renewal`). You may search for `test_auth_renewal` in the action picker.
3. Leave the action data empty; it takes no inputs.
4. If the UI offers a response option, enable **Return response**. Press **Perform action**.
5. Wait for the action to complete. A successful call should return a structured response similar to the following (the counts vary with your current grocery list):

```json
{
  "status": "passed",
  "authentication_refresh": "passed",
  "deglaze_read_request": "passed",
  "grocery_response_schema": "recognized",
  "schema_recognized": true,
  "list_count": 1,
  "item_count": 51,
  "pending_count": 12,
  "completed_count": 39,
  "read_only": true,
  "message": "The integration forced its normal access-token renewal path, then successfully read the Deglaze grocery list. No grocery items were changed."
}
```

The numbers above are illustrative, not expected values. Compare the counts with the current list on Deglaze. The important pass criteria are:

- `status` is `passed`.
- `authentication_refresh` and `deglaze_read_request` both say `passed`.
- `schema_recognized` is `true` and `grocery_response_schema` is `recognized`.
- `read_only` is `true`; the test has not changed list items.
- The list/item/pending/completed counts match the current Deglaze list.

### Verify the log and continued operation

1. Open **Settings → System → Logs**.
2. Find the entry from `custom_components.deglaze_poc.services` that says `Manual Deglaze authentication renewal test passed`.
3. Confirm the log records a successful refresh and `GET /lists` request, and that schema recognition/counts are sensible. It must not contain an access token, refresh token, magic link, or grocery-item names.
4. Return to the dashboard and verify the API Status sensor remains connected and the grocery, recipe, and meal-plan cards still load. Optionally call `deglaze_poc.refresh` as a separate final check.

### If the test fails

- **Action/service not found:** verify the integration folder is `custom_components/deglaze_poc`, the manifest version is 1.0.0, then restart Home Assistant. Merely reloading the dashboard JavaScript is not enough to load a Python action added to the integration.
- **Refresh-token/Firebase error:** inspect the log message from `custom_components.deglaze_poc.services`. A rejected or revoked refresh token may require reconfiguring the integration using a fresh Deglaze email sign-in link. Only do this if the log specifically points to an authentication failure.
- **Deglaze HTTP/read error:** check internet connectivity and whether Deglaze is operational. The refresh might have worked but the follow-up grocery-list request could have failed.
- **`status` is `partial` or schema is `unrecognized`:** token refresh and the read-only request succeeded, but the returned grocery-list response didn't match the integration's known response structure. This is a response-shape compatibility issue, not necessarily an authentication failure.
- **Response option is not visible:** run the action anyway; then inspect the integration log for the test result. If the action service does not exist after restart, use the first troubleshooting step.

The action deliberately sets only the client's in-memory token expiry timestamp to the past. It then goes through the same normal code path used when a token naturally approaches expiry. It does not invalidate the saved refresh token and does not wait for or simulate server-side revocation. The existing automated tests separately cover the HTTP 401 → refresh → retry path; the live action checks that Firebase accepts the actual saved refresh token and that Deglaze accepts a request authenticated with the renewed ID token.

## Detailed test: error handling and recovery

This diagnostic is intended for the local/test Home Assistant instance after the integration is connected. It does not deliberately break the real connection or send a failed request to Deglaze. Instead, it injects a synthetic HTTP 503 response locally into a temporary wrapper, uses the same `_request_json` path as normal requests, and then verifies a real read-only recovery request.

### Run the action

1. Back up your Home Assistant configuration and install/upgrade the integration files from this build in `custom_components/deglaze_poc/`. Keep the domain folder name unchanged.
2. Restart Home Assistant and confirm the Deglaze API Status sensor is connected.
3. Open **Developer Tools → Actions**.
4. Select **Deglaze: Test error handling and recovery** (`deglaze_poc.test_error_handling`). Search for `test_error_handling` if needed.
5. Leave the action data empty. Enable **Return response** if your Home Assistant version offers that option, then perform the action.

### Expected result

A successful response should resemble this (the grocery counts depend on your list):

```json
{
  "status": "passed",
  "simulated_failure": "HTTP 503",
  "simulated_failure_origin": "local-only",
  "simulated_failure_handled": true,
  "failure_message_sanitized": true,
  "recovery_read_request": "passed",
  "read_only": true,
  "grocery_response_schema": "recognized",
  "schema_recognized": true,
  "list_count": 1,
  "item_count": 55,
  "pending_count": 3,
  "completed_count": 52,
  "message": "A local synthetic HTTP 503 was handled by the normal API error path without exposing its body. A subsequent real, read-only GET /lists succeeded. No failure was sent to Deglaze and no list items were changed."
}
```

Check all of the following:

- `status` is `passed`. If it is `partial`, the recovery request worked but the returned list shape wasn't recognized.
- `simulated_failure_origin` is `local-only`; the synthetic failure was not sent to Deglaze.
- `simulated_failure_handled` and `failure_message_sanitized` are `true`.
- `recovery_read_request` is `passed`, and the counts are plausible/current.
- `read_only` is `true`; no grocery or meal-plan items should have changed.

### Verify logs and normal recovery

1. Open **Settings → System → Logs**. Find the success entry from `custom_components.deglaze_poc.services` describing the local synthetic HTTP 503 and successful recovery.
2. Confirm logs contain no access token, refresh token, magic link, full response body, or grocery-item names.
3. Return to your dashboard and confirm the grocery, recipe, and upcoming-meals cards still work. The diagnostic makes a real read-only list request but does not change remote data.

If the action fails, check that the integration is loaded, connected, and updated to manifest version `1.0.0`. A failure before the synthetic 503 test usually indicates a token or connection problem; a failure during the recovery read means the diagnostic couldn't confirm live API recovery. The log should report a sanitized reason. Do not share any raw authentication headers or tokens when reporting errors.

## Test collection membership editing (0.6.0)

**Use a low-stakes recipe in a collection you can safely restore.** The request format is based on the Deglaze web bundle, but it is an undocumented API operation and must be verified against your account before relying on it.

1. If collection editing has not previously been validated, back up your Home Assistant configuration, install the current `1.0.0` release, restart Home Assistant, and update the card resource to `/local/deglaze-cards.js?v=1.0.0`. In the prior 0.6.0 release, collection membership editing was confirmed by the user against Deglaze; this section remains as a regression checklist.
2. Open the Recipe Library and select a recipe whose memberships you can safely change. Note the current collection chips and compare them with Deglaze.
3. In **Organize collections**, check one existing collection that the recipe does not belong to, then select **Save memberships**. Wait for the success message.
4. Verify the new membership on the Deglaze website, then press **Refresh** in Home Assistant and confirm the collection chip and collection count update.
5. Uncheck that same collection in Home Assistant, save again, and verify the membership and count are removed on Deglaze and Home Assistant.
6. If the operation reports that a change may have partially applied, do not repeatedly click Save. Refresh the library, compare the recipe's memberships on Deglaze, and reconcile them before retrying.
7. Confirm that recipe ingredients/instructions, collection filtering, adding to the meal plan, and grocery actions still work.

The card shows a success message only if the immediate synchronized recipe data reflects the requested visible memberships. A mismatch can occur if the endpoint changes or Deglaze takes time to publish a library update; in that case, verify the website rather than assuming either success or failure.

## Test weekly meal planning (0.7.0)

Use a planned recipe you can safely reschedule. The update/removal endpoints are based on Deglaze's own web-app bundle; because they are undocumented, verify the behavior against the website before relying on them.

1. Back up Home Assistant, install the `1.0.0` release, restart, and update the card resource to `/local/deglaze-cards.js?v=1.0.0`.
2. Add a `custom:deglaze-weekly-meal-planner-card` in the visual editor or use the example YAML. Full width is recommended.
3. In the visual editor, set **Number of days to display** to 3, save, and verify only Monday–Wednesday are shown while the card continues to fetch the full Monday–Sunday week. Try 5 days and then 7 days. Confirm the meal titles/slots match Deglaze. Navigate to previous week, next week, and back to **This week**; navigation should advance by seven days regardless of the displayed-day setting.
4. For a low-stakes planned meal, select **Edit**, change only its date within the displayed week, and save. Confirm that the item moves to the new day in Home Assistant and Deglaze. Then test changing its meal slot and toggling the leftovers marker separately.
5. Test changing the date to a different week. The item should disappear from the original week after the refresh; navigate to the destination week to verify it appears there.
6. Select **Remove**, check that the confirmation prompt appears, and cancel once to verify cancellation is safe. Repeat on a low-stakes item and choose **Confirm remove**; verify the item disappears in both Home Assistant and Deglaze.
7. Confirm the existing Upcoming Meals card, Recipe Library, grocery card, collection editor, authentication renewal, error diagnostic, and Recorder attribute behavior still work.

If an update reports that the change was sent but not fully verified, refresh the selected week and check Deglaze before retrying. Do not repeatedly submit an ambiguous update: a timeout can occur after the server has already applied a change. Recipe replacement is intentionally not offered through the update service; the observed app flow supports date, label, and leftovers updates.

## Test grocery store management and assignment (0.8.0)

Because the store endpoints are undocumented, run this sequence with a temporary store and a low-stakes grocery item before relying on it for the main shopping workflow.

1. Back up Home Assistant and install this build. Restart the integration and confirm the existing grocery list loads with the correct To Buy count.
2. In the Grocery List card, open **Manage stores**, create a temporary store such as `HA Store Test`, and verify it appears both in Home Assistant and on the Deglaze website.
3. Rename that temporary store. The integration reads the latest store version before sending the rename; verify the new name on Deglaze and in the card.
4. Expand **Assign stores** for a low-stakes item. Select the temporary store, save, and confirm the association on Deglaze. Then uncheck it, save, and verify the assignment is removed.
5. Add a harmless temporary grocery item and select **Assign store on add** before submitting. Verify the new item and store association on Deglaze.
6. Try **Filter by store** and **Group items → By store**. Then use **Group items → By category**, **Alphabetical**, and **Newest first**. If an item has multiple store assignments, it intentionally appears in each matching store group; item counts near the top remain counts of real list items, not group rows.
7. Delete the temporary store only after verifying the warning and selecting **Confirm delete**. Deglaze's observed behavior removes that store association but leaves all grocery items in place. Verify that the temporary store disappears and the items remain.
8. Confirm that the To Buy default, search, status toggle, item counts, recipe library, meal planner, and small grocery-sensor attributes continue working. Check Settings → System → Logs for any new Recorder warnings.

If a write reports an ambiguous outcome, refresh the card and verify Deglaze before retrying. Do not repeatedly submit a rename, create, delete, or assignment after a timeout; the server may have applied the first request even if Home Assistant did not receive confirmation.

## Live validation checklist

- Confirm the recipe count and displayed titles match Deglaze.
- Confirm user-created collections (for example, Cuban and Cooked & Liked) and built-in categories appear in separate selector groups.
- Select each of those collections and compare its recipe titles/count with Deglaze. Search within a collection, then select All recipes and confirm the full title list returns.
- Confirm recipes assigned to multiple collections appear in each applicable collection and display the corresponding badges.
- Open multiple recipes and compare ingredient and instruction sections with the website.
- Add a harmless test ingredient with the grocery card and verify it appears on Deglaze.
- Add one recipe to a future date/slot using the recipe card and verify it on Deglaze and in the Upcoming Meals card.
- Confirm the meal labels and leftovers marker render correctly.
- From a recipe, select a few ingredients, review possible duplicates, optionally choose a store, confirm the add, and verify the items appear in Deglaze and Home Assistant.
- Verify duplicates are skipped by default, the explicit duplicate override works as intended, and a partial/ambiguous result instructs you to refresh and compare before retrying.
- Test after a token refresh / longer uptime. Local tests do not prove that undocumented Deglaze endpoints will remain stable.

## Compatibility and security notes

This integration uses observed, undocumented Deglaze web-app endpoints and an observed frontend header value. Those may change without notice. Grocery actions, recipe synchronization/detail display, meal-plan operations, auth renewal, and the controlled error-recovery diagnostic have been verified in a Home Assistant environment. Collection filtering was added in 0.5.0; membership editing was added in 0.6.0 and has been confirmed by the user against Deglaze. The weekly meal planner and planned-item write endpoints were introduced in 0.7.0 and were added in 0.7.0 and were confirmed by the user against Deglaze in subsequent testing. Membership edits do not call the recipe-viewed endpoint or intentionally change Deglaze viewing history.

The Firebase email sign-in link is a one-time credential: request a fresh link and paste it into the config flow without opening it first. Do not share sign-in links or tokens. Protect Home Assistant configuration files and backups because the refresh token is stored in the config entry.

## Local tests

Tests make no network calls and do not require Home Assistant to be installed:

```bash
python -m unittest discover -s tests -v
python -m compileall -q custom_components tests
node tests/test_recipe_collection_card.js
node --check www/deglaze-cards.js
```

The tests cover token renewal, safe handling of HTTP errors and transport timeouts, recovery on a subsequent request, the local synthetic-503 diagnostic, grocery/meal request payloads including planned-item update/removal, collection manifest parsing, structured user/system tag mapping, collection change planning, the observed bulk-edit request shape for add/remove, multi-collection membership, and retention of collection metadata during incremental sync. Node regression checks cover combined collection/title filtering, per-collection counts, unsaved membership state comparison, and Monday–Sunday week navigation. Static checks also verify that all four cards/editors, native sizing, and grocery/meal-plan/recipe WebSocket handlers remain present, that grocery sensor attributes do not include the full item array, and that the grocery card defaults to To Buy. They do not start Home Assistant or validate the live remote endpoint behavior. Run them with `python -m unittest discover -s tests -v`, `node tests/test_recipe_collection_card.js`, and `node --check www/deglaze-cards.js`.
