/* Lightweight Node regression tests for recipe collection filtering logic. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const customElementRegistry = new Map();
const windowEvents = [];
const windowListeners = new Map();
const context = {
  HTMLElement: class HTMLElement {},
  CustomEvent: class CustomEvent { constructor(type, options = {}) { this.type = type; this.detail = options.detail; } },
  customElements: {
    get(name) { return customElementRegistry.get(name); },
    define(name, value) { customElementRegistry.set(name, value); },
  },
  window: {
    customCards: [],
    addEventListener(type, listener) { windowListeners.set(type, listener); },
    removeEventListener(type, listener) { if (windowListeners.get(type) === listener) windowListeners.delete(type); },
    dispatchEvent(event) {
      windowEvents.push(event.type);
      const listener = windowListeners.get(event.type);
      if (listener) listener(event);
      return true;
    },
  },
};
const source = fs.readFileSync(new URL("../www/deglaze-cards.js", `file://${__filename}`), "utf8");
vm.runInNewContext(`${source}\nglobalThis.TestGroceryCard = DeglazeGroceryAddCard; globalThis.TestRecipeCard = DeglazeRecipeLibraryCard; globalThis.TestWeeklyCard = DeglazeWeeklyMealPlannerCard; globalThis.TestWeekStart = deglazeWeekStart; globalThis.TestDateShift = deglazeDateShift; globalThis.TestClampDisplayDays = deglazeClampDisplayDays; globalThis.TestDisplayedDates = deglazeDisplayedDates; globalThis.TestIngredientDuplicateKey = deglazeIngredientDuplicateKey;`, context);

const card = Object.create(context.TestRecipeCard.prototype);
card._recipes = [
  { recipe_id: "r1", title: "Cuban Black Beans", collection_ids: ["cuban", "beans"], collection_names: ["Cuban", "Beans/Lentils"] },
  { recipe_id: "r2", title: "Creamy Peppercorn Pasta", collection_ids: ["liked", "main"], collection_names: ["Cooked & Liked", "Main Course"] },
  { recipe_id: "r3", title: "Cuban Rice", collection_ids: ["cuban", "rice"], collection_names: ["Cuban", "Rice"] },
];
card._collections = [
  { id: "cuban", name: "Cuban", tag_type: "user" },
  { id: "liked", name: "Cooked & Liked", tag_type: "user" },
  { id: "beans", name: "Beans/Lentils", tag_type: "system" },
  { id: "main", name: "Main Course", tag_type: "system" },
  { id: "rice", name: "Rice", tag_type: "system" },
];
card._query = "";
card._selectedCollectionId = "";

assert.deepEqual(card._getFilteredRecipes().map((recipe) => recipe.recipe_id), ["r1", "r2", "r3"]);
card._selectedCollectionId = "cuban";
assert.deepEqual(card._getFilteredRecipes().map((recipe) => recipe.recipe_id), ["r1", "r3"]);
card._query = "rice";
assert.deepEqual(card._getFilteredRecipes().map((recipe) => recipe.recipe_id), ["r3"]);
card._query = "pasta";
assert.deepEqual(card._getFilteredRecipes(), []);
card._query = "";
card._selectedCollectionId = "beans";
assert.deepEqual(card._getFilteredRecipes().map((recipe) => recipe.recipe_id), ["r1"]);
assert.equal(card._getCollectionCounts().get("cuban"), 2);
assert.equal(card._getCollectionCounts().get("liked"), 1);
assert.equal(card._getCollectionCounts().get("main"), 1);

// Collection membership editor drafts compare IDs without relying on array order.
card._collectionDraftIds = null;
assert.equal(card._isCollectionDraftDirty(["cuban", "beans"]), false);
card._collectionDraftIds = ["beans", "cuban"];
assert.equal(card._isCollectionDraftDirty(["cuban", "beans"]), false);
card._collectionDraftIds = ["cuban", "liked"];
assert.equal(card._isCollectionDraftDirty(["cuban", "beans"]), true);
card._collectionDraftIds = [];
assert.equal(card._isCollectionDraftDirty(["cuban"]), true);

// The weekly planner uses Monday-Sunday ranges and can navigate them deterministically.
assert.equal(context.TestWeekStart("2026-10-11"), "2026-10-05"); // Sunday -> previous Monday
assert.equal(context.TestWeekStart("2026-10-12"), "2026-10-12"); // Monday stays Monday
assert.equal(context.TestDateShift("2026-10-05", 6), "2026-10-11");
assert.equal(context.TestClampDisplayDays(undefined), 7);
assert.equal(context.TestClampDisplayDays(1), 1);
assert.equal(context.TestClampDisplayDays(5), 5);
assert.equal(context.TestClampDisplayDays(0), 1);
assert.equal(context.TestClampDisplayDays(8), 7);
assert.deepEqual(Array.from(context.TestDisplayedDates("2026-11-16", 3)), ["2026-11-16", "2026-11-17", "2026-11-18"]);
assert.deepEqual(Array.from(context.TestDisplayedDates("2026-11-16", 5)), ["2026-11-16", "2026-11-17", "2026-11-18", "2026-11-19", "2026-11-20"]);
assert.equal(context.TestDisplayedDates("2026-11-16", 7).length, 7);
const weekly = Object.create(context.TestWeeklyCard.prototype);
weekly._weekStart = "2026-11-16";
weekly._config = { display_days: 3 };
assert.equal(weekly._weekEnd, "2026-11-22"); // Retrieval/navigation remains a full week even when displaying 3 days.



// Grocery store management and shopping-list grouping helpers.
const grocery = Object.create(context.TestGroceryCard.prototype);
grocery._stores = [
  { id: "store-market", name: "Market", version: 3 },
  { id: "store-coop", name: "Co-op", version: 1 },
];
grocery._sortBy = "alpha";
assert.deepEqual(Array.from(grocery._storeIds({ stores: ["store-market", { id: "store-coop" }, "store-market"] })), ["store-market", "store-coop"]);
assert.deepEqual({ ...grocery._category({ category: { primary: "produce", sub: "leafy_greens" } }) }, { primary: "Produce", sub: "Leafy Greens" });
assert.equal(grocery._category({ category: null }).primary, "Uncategorized");
const alphaItems = grocery._sortItems([{ text: "Zucchini" }, { text: "apples" }, { text: "Milk" }]);
assert.deepEqual(Array.from(alphaItems, (item) => item.text), ["apples", "Milk", "Zucchini"]);
grocery._sortBy = "newest";
const newestItems = grocery._sortItems([{ text: "Old", created: 100 }, { text: "New", created: 200 }]);
assert.deepEqual(Array.from(newestItems, (item) => item.text), ["New", "Old"]);

// Rendering keeps the normal To Buy filter and offers store filters, grouping,
// sorting, store management and item assignment without exposing full data as sensor attributes.
grocery._config = { title: "Grocery list", placeholder: "Item", domain: "deglaze_poc", service: "deglaze_poc.add_grocery_item", default_filter: "pending", default_group_by: "store", default_sort_by: "alpha" };
grocery._items = [
  { id: "item-1", text: "Apples", status: { status: "pending" }, category: { primary: "produce", sub: "fruit" }, stores: ["store-market"], created: 300 },
  { id: "item-2", text: "Milk", status: { status: "pending" }, category: { primary: "dairy" }, stores: [], created: 200 },
];
grocery._counts = { item_count: 2, pending_count: 2, completed_count: 0 };
grocery._query = "";
grocery._filter = "pending";
grocery._storeFilter = "all";
grocery._groupBy = "store";
grocery._sortBy = "alpha";
grocery._loadingList = false;
grocery._listError = "";
grocery._listMessage = "";
grocery._listMessageKind = "";
grocery._manageStoresOpen = true;
grocery._deleteConfirmId = "";
grocery._busyAction = "";
grocery.shadowRoot = { innerHTML: "", querySelector() { return null; }, querySelectorAll() { return []; } };
grocery._render();
assert.match(grocery.shadowRoot.innerHTML, /Filter by store/);
assert.match(grocery.shadowRoot.innerHTML, /Group items/);
assert.match(grocery.shadowRoot.innerHTML, /Sort items/);
assert.match(grocery.shadowRoot.innerHTML, /Hide stores|Manage stores/);
assert.match(grocery.shadowRoot.innerHTML, /Market/);
assert.match(grocery.shadowRoot.innerHTML, /Unassigned/);
assert.match(grocery.shadowRoot.innerHTML, /Assign stores/);
assert.match(grocery.shadowRoot.innerHTML, /Save stores/);


// Recipe-to-grocery workflow keeps exact recipe wording, finds conservative duplicates,
// lets users assign stores, and sends an explicit confirmation request to the backend.
const recipeCard = Object.create(context.TestRecipeCard.prototype);
recipeCard._detail = {
  ingredients_for_grocery: [
    { id: "section-0:garlic", text: "2 cloves garlic, minced", section: "For the sauce" },
    { id: "section-0:onion", text: "1 onion, diced", section: "For the sauce" },
  ],
};
recipeCard._selectedId = "recipe-one";
recipeCard._ingredientSelectionIds = null;
recipeCard._ingredientReview = null;
recipeCard._ingredientReviewLoading = false;
recipeCard._addingIngredients = false;
recipeCard._ingredientStoreIds = [];
recipeCard._ingredientIncludeDuplicates = false;
recipeCard._ingredientWorkflowMessage = "";
recipeCard._ingredientWorkflowMessageType = "info";
recipeCard._config = { domain: "deglaze_poc" };
recipeCard._render = () => {};
assert.equal(recipeCard._getIngredientChoices().length, 2);
assert.deepEqual(Array.from(recipeCard._getSelectedIngredientChoices(), (choice) => choice.id), ["section-0:garlic", "section-0:onion"]);
assert.equal(context.TestIngredientDuplicateKey("2 tbsp chopped garlic"), "garlic");
assert.equal(context.TestIngredientDuplicateKey("Garlic"), "garlic");
assert.equal(context.TestIngredientDuplicateKey("1 scallion (for topping)"), "scallion");
assert.equal(context.TestIngredientDuplicateKey("1 jalapeño, chopped"), context.TestIngredientDuplicateKey("jalapeños"));
assert.equal(context.TestIngredientDuplicateKey("香菜"), "香菜");

const wsCalls = [];
recipeCard._hass = {
  async callWS(payload) {
    wsCalls.push(payload);
    if (payload.type === "deglaze_poc/grocery/list") {
      return {
        items: [{ id: "old-garlic", text: "Garlic", status_text: "pending" }],
        stores: [{ id: "store-a", name: "Market" }],
      };
    }
    if (payload.type === "deglaze_poc/recipe/add-ingredients") {
      return { status: "passed", added_count: 1, skipped_duplicate_count: 1, message: "Added 1 ingredient; skipped 1 possible duplicate." };
    }
    throw new Error(`Unexpected test WebSocket command: ${payload.type}`);
  },
};
(async () => {
  await recipeCard._reviewSelectedIngredients();
  assert.equal(recipeCard._ingredientReview.choices.length, 2);
  assert.equal(recipeCard._ingredientReview.duplicateById["section-0:garlic"][0].text, "Garlic");
  recipeCard._ingredientStoreIds = ["store-a"];
  await recipeCard._confirmAddIngredients();
  assert.equal(wsCalls[1].type, "deglaze_poc/recipe/add-ingredients");
  assert.deepEqual(Array.from(wsCalls[1].ingredient_ids), ["section-0:garlic", "section-0:onion"]);
  assert.deepEqual(Array.from(wsCalls[1].store_ids), ["store-a"]);
  assert.equal(wsCalls[1].include_duplicates, false);
  assert.equal(recipeCard._ingredientWorkflowMessageType, "success");
  assert.ok(windowEvents.includes("deglaze-grocery-list-updated"), "successful recipe ingredient additions notify grocery cards to refresh");
  assert.match(context.TestGroceryCard.toString(), /deglaze-grocery-list-updated/);
  console.log("Recipe collection, weekly meal planner, grocery/store, and recipe-to-grocery card tests passed.");
})().catch((error) => { console.error(error); process.exitCode = 1; });
