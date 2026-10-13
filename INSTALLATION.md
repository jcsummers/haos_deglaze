# Deglaze Home Assistant — First-time installation

This guide walks through installing the unofficial Deglaze integration and its four custom Lovelace cards on an existing Home Assistant installation. It is written for Home Assistant users, not integration developers.

> **Important:** Deglaze uses a one-time email sign-in link. Copy the link from your email into Home Assistant without opening/clicking it first. Opening it can consume the one-time code. Never share the link with anyone; treat it like a password.

## What you need

- A running Home Assistant instance and access to its configuration files (for example, through your usual File Editor, Samba share, SSH, or another file-access method).
- A Deglaze account and access to the email inbox registered to that account.
- The release ZIP, `deglaze_home_assistant_1_0_0.zip`.
- Internet access from Home Assistant.

This package is installed manually; these instructions do not use HACS.

## Part 1 — Install the integration files

1. **Download the release ZIP** to your computer.
2. **Extract the ZIP.** The archive contains a top-level `deglaze_1_0_0/` folder. Open that folder before copying files; do not create an extra nested `deglaze_1_0_0` directory inside your Home Assistant configuration.
3. In your Home Assistant configuration directory (normally `/config`), create `custom_components` if it does not already exist.
4. Copy the included folder `deglaze_1_0_0/custom_components/deglaze_poc/` to `/config/custom_components/deglaze_poc/`. The file path should end up like this:

   ```text
   /config/custom_components/deglaze_poc/manifest.json
   /config/custom_components/deglaze_poc/config_flow.py
   /config/custom_components/deglaze_poc/__init__.py
   ```

5. Create `/config/www/` if it does not already exist.
6. Copy `deglaze_1_0_0/www/deglaze-cards.js` to `/config/www/deglaze-cards.js`.
7. **Restart Home Assistant fully.** A dashboard refresh alone does not load a newly installed Python integration.

## Part 2 — Add Deglaze in Home Assistant

1. In Home Assistant, open **Settings → Devices & services**.
2. Select **Add integration**.
3. Search for **Deglaze** and select it.
4. On the **Connect Deglaze** form, enter the email address used for your Deglaze account. Select **Submit/Continue**.
5. Home Assistant will display the **Complete email-link sign-in** step. Keep this form open while you request the email link in the next steps.
6. In a separate browser tab, visit [Deglaze](https://web.deglaze.app) and request a sign-in email for the same email address you entered in Home Assistant. Follow Deglaze's normal sign-in flow to send the email.
7. Open the email, but **do not click or open the sign-in link**. Copy the full destination URL from the link instead. Depending on your email client, you may be able to right-click or long-press the link and select **Copy link address**. Copy the entire URL, not only the visible link text.
8. Return to Home Assistant's **Complete email-link sign-in** form. Paste the full URL into **Full sign-in link from the Deglaze email**, then submit it.
9. Wait for Home Assistant to validate the link and test a read-only grocery-list request. If successful, the Deglaze integration entry will be created.

The email link is a one-time credential. Do not paste it into chat, issue trackers, or logs. Home Assistant exchanges it during setup; it is not intended to be saved for future use.

### If the sign-in link is rejected

- If the form says the link is expired or already used, return to Deglaze and request a **new** sign-in email. Copy its link without opening it.
- If the form says the link is not recognized, copy the **full URL** from the email rather than the link's displayed text.
- Make sure the Home Assistant form and Deglaze email use the same account address.
- If Home Assistant cannot connect, check that Home Assistant has internet access and try again with a fresh link.
- If Home Assistant says the account is already configured, return to **Settings → Devices & services** and open the existing Deglaze integration rather than adding a duplicate.

## Part 3 — Register the Lovelace cards

The integration entities work without the custom cards, but the four cards provide the interactive grocery, meal-planning, and recipe-library interfaces.

1. In Home Assistant, open **Settings → Dashboards → Resources**. Depending on your Home Assistant layout, Resources may be available from the dashboard edit menu.
2. Select **Add resource**.
3. Enter this URL:

   ```text
   /local/deglaze-cards.js?v=1.0.0
   ```

4. Set the resource type to **JavaScript Module** and save it.
5. If a resource for `/local/deglaze-cards.js` already exists, **edit that entry instead of adding a duplicate**.
6. Hard-refresh the Home Assistant browser tab. If the cards do not appear, close and reopen the dashboard or clear the browser's cached page for Home Assistant.

The path `/local/deglaze-cards.js` corresponds to the file `/config/www/deglaze-cards.js`.

## Part 4 — Add cards to a dashboard

1. Open the dashboard where you want Deglaze.
2. Select **Edit dashboard → Add card**.
3. Choose the Deglaze custom card if it appears in the card picker. Each card has a visual configuration editor.
4. Configure the title and card-specific settings, then save.
5. If you prefer YAML, use the examples in the main [README](README.md) or the included `lovelace-dashboard-example.yaml` file.

The four cards are:

- **Grocery List:** view and search items, default to **To Buy**, add items, mark them bought/to buy, manage stores, assign items to stores, and group/filter/sort the list.
- **Upcoming Meals:** show a configurable number of planned meals with meal-slot labels and leftovers markers.
- **Weekly Meal Planner:** show 1–7 days from the selected Monday–Sunday week in aligned Breakfast/Lunch/Dinner/Snack columns, and edit supported meal fields.
- **Recipe Library:** search/browse recipes and collections, view ingredients and instructions, edit collection memberships, add recipes to the meal plan, and select ingredients to add to the grocery list.

For a Sections dashboard, the Recipe Library and Weekly Meal Planner are usually most comfortable at full width. Native grid resizing works in Sections dashboards; Masonry dashboards determine widths themselves.

## Part 5 — Confirm the installation

1. Open **Settings → Devices & services → Deglaze** and confirm the integration is loaded.
2. Open its device and find the summary sensors. Exact entity IDs can vary by your Home Assistant naming/area setup:
   - **Grocery List** — pending item count and small summary attributes (the full item array is intentionally not stored in Recorder attributes).
   - **Recipe Library** — active recipe count and sync metadata.
   - **Meal Plan** — count and summary of synchronized planned meals.
   - **API Status** — expected to show `connected` when all synchronized parts are healthy; `partial` means a non-grocery part has a sync error, and `degraded` indicates a grocery error.
3. Open the Grocery List card and confirm the list loads and the **To Buy** view is selected.
4. Open the Recipe Library card and confirm recipe titles load. Open one recipe and compare its ingredients and instructions with Deglaze.
5. Open Upcoming Meals and the Weekly Meal Planner; confirm the selected week loads and the labels look right.
6. If you want a live write test, add one harmless grocery item and verify that it appears in Deglaze. Remove or mark it complete afterward using Deglaze's supported workflow if appropriate.
7. Check **Settings → System → Logs** for new startup/import errors or repeated API errors.

For optional diagnostics, see the authentication-renewal and error-handling test sections in the main README. Both are designed not to change grocery items.

## Troubleshooting quick reference

| Symptom | Suggested solution |
|---|---|
| Deglaze does not appear in **Add integration** | Confirm `/config/custom_components/deglaze_poc/manifest.json` exists at that exact path, then fully restart Home Assistant. Avoid an extra nested release folder. |
| `Invalid link` or link expired/already used | Request a fresh Deglaze sign-in email and copy the whole link without opening it. |
| `Cannot connect` during setup | Verify the account email and Home Assistant internet connectivity; retry with a fresh link. |
| Card says custom element does not exist | Verify `/config/www/deglaze-cards.js`, check the JavaScript Module resource URL/type, and hard-refresh the browser. |
| Card keeps loading after Python code was updated | Fully restart Home Assistant, then hard-refresh the browser. Frontend refresh alone does not reload Python WebSocket handlers. |
| API Status is `partial` or `degraded` | Open the sensor's `errors`, `recipe_sync_error`, and `meal_plan_sync_error` attributes, then inspect Home Assistant logs for the corresponding request failure. |
| Recorder warns that grocery attributes are too large | Check the Grocery List sensor's attributes. The current integration should not include a full `items` array. Ensure the current version's `custom_components/deglaze_poc` folder was installed and that you are looking at new warnings after restart. |

If the issue persists, share the relevant sanitized log message and the card's visible error. Never share the email sign-in link, access/refresh tokens, or private authentication details.
