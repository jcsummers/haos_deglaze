# Deglaze Home Assistant integration — 1.0.0 stable release

## Start here: install, sign in, or update

**New to the integration?** Follow [`INSTALLATION.md`](INSTALLATION.md) for the complete first-time setup, including copying the files, adding Deglaze in Home Assistant, requesting the email sign-in link, pasting it into the setup form, and registering the Lovelace cards.

**Already have Deglaze installed?** Follow [`UPDATING.md`](UPDATING.md) when installing a newer release. It covers backups, replacing the integration/card files, updating the JavaScript resource, verifying the upgrade, and rolling back if necessary.

**Want to create your own custom cards & automations?** Follow [`CARDS_ENTITIES_ACTIONS.md`](CARDS_ENTITIES_ACTIONS.md) This appendix supplements the Deglaze Home Assistant integration `README.md` for **version 1.0.0**. It documents the four custom Lovelace cards, their visual and YAML configuration, the summary sensors, registered service actions, and card-internal WebSocket commands.

### Release status

**Version 1.0.0 is the first stable release.** It was promoted from the `1.0.0-rc.1` candidate after the live release checks passed in Home Assistant. The stable package has the same runtime code and frontend as the validated candidate; only release metadata and documentation changed. Keep your previous known-working package as a rollback/reference copy.

## Lovelace cards at a glance

| Card | Custom card type | Main functions | Recommended Sections width |
|---|---|---|---:|
| Grocery List | `custom:deglaze-grocery-add-card` | Add items, view and search the list, filter status, mark bought/to buy, manage stores, assign stores, group and sort | 6–12 columns |
| Upcoming Meals | `custom:deglaze-upcoming-meals-card` | Show a configurable number of upcoming meals and filter by meal type | 6 columns |
| Weekly Meal Planner | `custom:deglaze-weekly-meal-planner-card` | Browse a week, display 1–7 days, edit meal date/slot/leftovers, and remove a planned meal after confirmation | 12 columns |
| Recipe Library | `custom:deglaze-recipe-library-card` | Search and browse recipes, filter collections, view ingredients/instructions, edit collection membership, add meals to the plan, and add selected ingredients to groceries | 12 columns |

The cards use one frontend resource: `/local/deglaze-cards.js`. Register it as a **JavaScript Module** under **Settings → Dashboards → Resources**. After updating the JavaScript, change its URL's version query (for example, `/local/deglaze-cards.js?v=1.0.0`) and hard-refresh the browser to avoid cached code.

## Troubleshooting guide

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

## Safety and behavior notes

- The integration reuses passwordless Firebase sign-in. A sign-in email link is a one-time credential; do not open it before the configured setup flow asks you to paste it, and do not share it.
- The integration's observed Deglaze API is undocumented. Endpoints and payloads can change independently of Home Assistant.
- Grocery item removal is not implemented; use pending/completed status. Deleting a **store definition** is supported and removes its association from items but leaves the items intact.
- The recipe-to-grocery flow preserves the wording/quantities supplied by Deglaze. Automatic scaling, pantry-staple exclusion, and recipe replacement in an already-planned meal are not included.
- Diagnostic actions make read-only grocery-list requests. `test_error_handling` substitutes a local synthetic HTTP 503 for one request; that failure is not sent to Deglaze.
- Keep the small, summary-only Grocery List sensor attributes to avoid Home Assistant Recorder attribute-size warnings. The full grocery item list is obtained through the card's authenticated WebSocket command.

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
