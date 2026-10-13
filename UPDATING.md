# Deglaze Home Assistant — Updating an existing installation

Use this guide when installing a newer Deglaze integration release over an existing installation. These are manual update steps for the unofficial community integration; they do not require deleting your Home Assistant integration entry or signing in again for every update.

> **Keep a rollback copy.** The API used by this integration is undocumented and may change when Deglaze updates its app. Keep the current working ZIP or a copy of the existing integration folder and card JavaScript until the new release is verified.

## Before you update

1. Read the new release notes and any version-specific upgrade notes.
2. Create a Home Assistant backup from **Settings → System → Backups** (the exact menu placement may vary by Home Assistant version).
3. Save the current working release ZIP, or copy these current files somewhere outside the live integration folder:
   - `/config/custom_components/deglaze_poc/`
   - `/config/www/deglaze-cards.js`
4. Note your current dashboard resource URL and confirm the installed integration is working before changing anything.

## Install the updated files

1. Download the new release ZIP and extract it on your computer.
2. Open the extracted release folder. The archive may contain a version-named top-level directory; copy the files **inside that release directory**, not the outer directory itself.
3. Replace `/config/custom_components/deglaze_poc/` with the new release's `custom_components/deglaze_poc/` folder. Keep the folder name exactly `deglaze_poc`; it is the integration domain used by your existing configuration entry.
4. Replace `/config/www/deglaze-cards.js` with the new release's `www/deglaze-cards.js`. If the new release has no frontend changes, follow its release notes about whether a card update is needed; when a new file is supplied, use it to keep frontend and backend releases matched.
5. **Do not delete and re-add the Deglaze integration as a routine update.** The existing configuration entry stores the session information used to refresh authentication. Removing the entry may discard that configuration and make you go through sign-in again.
6. Restart Home Assistant fully. Reloading a dashboard or reloading the browser does not reload Python integration code.

## Update the frontend resource

1. Open **Settings → Dashboards → Resources**. The menu may be available from the dashboard edit menu in some Home Assistant layouts.
2. Find the existing resource for `/local/deglaze-cards.js`.
3. Edit it so the URL includes the new release version as a cache-busting suffix. For stable 1.0.0, the URL is:

   ```text
   /local/deglaze-cards.js?v=1.0.0
   ```

   For a later version, replace `1.0.0` with that release's version, for example `/local/deglaze-cards.js?v=1.1.0`.
4. Keep the resource type set to **JavaScript Module**.
5. Edit the existing resource rather than adding a second resource pointing to the same file.
6. Save and hard-refresh your browser. If the card still shows old behavior, close/reopen the dashboard and verify the URL and file path again.

## Verify the update

1. Open **Settings → Devices & services → Deglaze**. Confirm the existing integration entry loaded and the device/entities are present.
2. Check that **API Status** returns to `connected`. If it shows `partial` or `degraded`, inspect its `errors`, `recipe_sync_error`, and `meal_plan_sync_error` attributes.
3. Open **Settings → System → Logs** and look for new startup/import errors, WebSocket coroutine warnings, or repeated API failures.
4. Check the Grocery List sensor's attributes. It should contain summary counts and metadata, not the full `items` array. Confirm there are no new Recorder oversized-attribute warnings.
5. Run a safe functional smoke test:
   - Grocery card: load the list, search, change an item's status, and verify the change on Deglaze.
   - Stores: view the store list and verify existing assignments. Avoid deleting a store just to test an upgrade.
   - Recipe Library: search for a recipe, open details, and confirm ingredients/instructions show.
   - Collections: select a collection and confirm its recipes appear.
   - Recipe-to-grocery: select one or two low-stakes ingredients, inspect duplicate warnings, optionally choose a store, confirm, and verify the result on Deglaze.
   - Meal planning: navigate the weekly view, verify meal labels and leftovers, and only perform an edit if you can safely verify the result on Deglaze.
6. If the release notes recommend the diagnostic actions, or you are investigating an authentication/API issue, run `deglaze_poc.test_auth_renewal` and/or `deglaze_poc.test_error_handling` from **Developer Tools → Actions**. These diagnostics are designed not to modify grocery items.
7. Use the integration normally for a little while and confirm that the logs remain clear of new recurring errors.

## Roll back if the update fails

1. Copy the previous known-good `/config/custom_components/deglaze_poc/` folder back into place.
2. Restore the matching previous `/config/www/deglaze-cards.js` file.
3. Set the existing JavaScript Module resource URL back to the matching version suffix, for example `/local/deglaze-cards.js?v=0.9.1` if rolling back to 0.9.1.
4. Restart Home Assistant fully and hard-refresh the browser.
5. Confirm API Status returns to `connected` and the cards load. Restore the Home Assistant backup only if file-level rollback is insufficient or the release instructions explicitly require it.

Do not re-enter a passwordless login link simply because a routine file upgrade failed. Re-authenticate only if the integration reports a specific authentication/refresh-token failure and the log or release notes indicate that a fresh sign-in is required.

## Troubleshooting

| Symptom after update | Suggested solution |
|---|---|
| Integration fails during import | Re-check that the files were copied from the release's inner `custom_components/deglaze_poc/` folder, with no extra nesting. Read the first traceback in Settings → System → Logs. If it is a new-version regression, roll back. |
| Old card UI remains | Verify the `www/deglaze-cards.js` file was replaced, edit the existing resource to use `?v=<new-version>`, and hard-refresh. |
| `Custom element doesn't exist` | Check the resource is registered as **JavaScript Module**, its URL begins `/local/deglaze-cards.js`, and the file exists in `/config/www/`. |
| Card loads but remains on a loading message | Check logs for unknown WebSocket command, missing handler, or coroutine warnings. Fully restart Home Assistant after replacing Python code; a browser refresh is not enough. |
| API Status is `partial` or `degraded` | Inspect the sensor's error attributes and the first corresponding log entry. A recipe or meal-plan issue may coexist with working grocery synchronization. |
| Authentication refresh fails | Check the specific log error first. Routine updates should not require a new email link; if the refresh token was rejected, follow the integration's sign-in recovery instructions and request a fresh link. Do not reuse or share an old link. |
| New Recorder oversized-attribute warning | Verify that Grocery List sensor attributes do not include a full `items` list and that the updated integration folder is installed. Check only warnings occurring after the update. |
| A write times out or reports a partial/uncertain result | Refresh the relevant card and compare with Deglaze before retrying. The remote write may have succeeded even if Home Assistant did not receive confirmation. |

When asking for support, share only sanitized errors and relevant card behavior. Never share a Deglaze sign-in URL, access token, refresh token, or private account details.
