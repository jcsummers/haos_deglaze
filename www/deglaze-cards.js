/* Deglaze Lovelace cards: grocery/store management, upcoming meals, weekly planner, and recipe browser. */

const deglazeEscape = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[char]));

const deglazeToday = () => {
  const now = new Date();
  now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
  return now.toISOString().slice(0, 10);
};

const deglazeMealLabel = (label) => {
  if (typeof label === "string") return label;
  if (label && typeof label === "object") {
    if (typeof label.label === "string") return label.label;
    if (label.label && typeof label.label.label === "string") return label.label.label;
  }
  return "Meal";
};

const deglazeMealOrder = (label) => {
  const normalized = deglazeMealLabel(label).toLowerCase();
  return ({ breakfast: 0, lunch: 1, dinner: 2, snack: 3 })[normalized] ?? 4;
};

const deglazeMealBadge = (label) => {
  const normalized = deglazeMealLabel(label).toLowerCase();
  return ({
    breakfast: "☀ Breakfast",
    lunch: "🥪 Lunch",
    dinner: "🍽 Dinner",
    snack: "🍎 Snack",
  })[normalized] || `🍴 ${deglazeMealLabel(label)}`;
};

const deglazeFormatDate = (dateValue) => {
  if (!dateValue) return "Date not set";
  const parsed = new Date(`${dateValue}T12:00:00`);
  if (Number.isNaN(parsed.getTime())) return String(dateValue);
  return new Intl.DateTimeFormat(undefined, {
    weekday: "short", day: "numeric", month: "short",
  }).format(parsed);
};

const deglazeBaseStyles = `
  :host { display:block; color:var(--primary-text-color); }
  .card { box-sizing:border-box; padding:16px; border-radius:var(--ha-card-border-radius,12px); background:var(--ha-card-background,var(--card-background-color)); box-shadow:var(--ha-card-box-shadow,0 2px 6px rgba(0,0,0,.12)); }
  h2 { font-size:1.15rem; line-height:1.35; font-weight:600; margin:0; }
  .muted { color:var(--secondary-text-color); font-size:.9rem; }
  button, input, select { font:inherit; }
  button { cursor:pointer; }
  button:disabled { cursor:default; opacity:.55; }
  .primary { border:0; border-radius:8px; padding:10px 14px; background:var(--primary-color); color:var(--text-primary-color,#fff); font-weight:600; }
  .secondary { border:1px solid var(--divider-color); border-radius:8px; padding:7px 10px; background:transparent; color:var(--primary-text-color); }
  input, select { box-sizing:border-box; min-width:0; width:100%; color:var(--primary-text-color); background:var(--secondary-background-color); border:1px solid var(--divider-color); border-radius:8px; padding:10px; }
  .message { min-height:1.2em; margin-top:8px; color:var(--secondary-text-color); font-size:.9rem; }
  .message.error { color:var(--error-color,#db4437); }
  .message.success { color:var(--success-color,#2e7d32); }
`;

class DeglazeGroceryAddCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = undefined;
    this._config = { title: "Grocery list", placeholder: "Ingredient or item…", service: "deglaze_poc.add_grocery_item", domain: "deglaze_poc", grid_columns: 6, default_group_by: "none", default_sort_by: "alpha" };
    this._items = [];
    this._stores = [];
    this._counts = { item_count: 0, pending_count: 0, completed_count: 0 };
    this._filter = "pending";
    this._query = "";
    this._storeFilter = "all";
    this._groupBy = "none";
    this._sortBy = "alpha";
    this._loadingList = false;
    this._lastLoadAt = 0;
    this._listError = "";
    this._listMessage = "";
    this._listMessageKind = "";
    this._manageStoresOpen = false;
    this._deleteConfirmId = "";
    this._busyAction = "";
    this._timer = undefined;
    // Recipe-to-grocery additions refresh the integration coordinator immediately.
    // Listen for a same-page event so this card doesn't wait for its normal poll.
    this._onRecipeGroceryChanged = () => {
      this._lastLoadAt = 0;
      void this._loadItems();
    };
  }

  setConfig(config) {
    this._config = {
      title: "Grocery list",
      placeholder: "Ingredient or item…",
      service: "deglaze_poc.add_grocery_item",
      domain: "deglaze_poc",
      default_filter: "pending",
      manual_category: "",
      grid_columns: 6,
      default_group_by: "none",
      default_sort_by: "alpha",
      ...config,
    };
    if (!["all", "pending", "completed"].includes(this._config.default_filter)) this._config.default_filter = "pending";
    if (!["none", "store", "category"].includes(this._config.default_group_by)) this._config.default_group_by = "none";
    if (!["alpha", "newest"].includes(this._config.default_sort_by)) this._config.default_sort_by = "alpha";
    this._groupBy = this._config.default_group_by;
    this._sortBy = this._config.default_sort_by;
    if (!this._config.service.includes(".")) throw new Error("service must be domain.service");
    if (!config?.domain && config?.service) this._config.domain = config.service.split(".", 1)[0];
    this._filter = this._config.default_filter;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    if (this.isConnected && (!this._lastLoadAt || Date.now() - this._lastLoadAt > 45000)) this._loadItems();
  }
  get hass() { return this._hass; }

  connectedCallback() {
    this._render();
    if (typeof window.addEventListener === "function") {
      window.addEventListener("deglaze-grocery-list-updated", this._onRecipeGroceryChanged);
    }
    this._loadItems();
    if (!this._timer) this._timer = window.setInterval(() => this._loadItems(), 60000);
  }

  disconnectedCallback() {
    if (typeof window.removeEventListener === "function") {
      window.removeEventListener("deglaze-grocery-list-updated", this._onRecipeGroceryChanged);
    }
    if (this._timer) window.clearInterval(this._timer);
    this._timer = undefined;
  }

  async _loadItems() {
    if (!this._hass || this._loadingList) return;
    this._loadingList = true;
    this._lastLoadAt = Date.now();
    this._render();
    try {
      const response = await this._hass.callWS({ type: `${this._config.domain}/grocery/list` });
      this._items = Array.isArray(response?.items) ? response.items : [];
      this._stores = Array.isArray(response?.stores) ? response.stores.filter((store) => store && typeof store.id === "string" && typeof store.name === "string") : [];
      this._counts = response?.counts || {
        item_count: this._items.length,
        pending_count: this._items.filter((item) => deglazeGroceryStatus(item) !== "completed").length,
        completed_count: this._items.filter((item) => deglazeGroceryStatus(item) === "completed").length,
      };
      this._listError = response?.sync_error || "";
      if (this._storeFilter !== "all" && this._storeFilter !== "__none" && !this._stores.some((store) => store.id === this._storeFilter)) this._storeFilter = "all";
    } catch (error) {
      this._listError = error?.message || "Could not load the Deglaze grocery list.";
    } finally {
      this._loadingList = false;
      this._render();
    }
  }

  _message(text, kind = "") {
    this._listMessage = text;
    this._listMessageKind = kind;
    const node = this.shadowRoot.querySelector("#message");
    if (node) {
      node.textContent = text;
      node.className = `message ${kind}`.trim();
    }
  }

  async _runStoreService(service, data, successMessage) {
    if (!this._hass || this._busyAction) return;
    this._busyAction = service;
    this._render();
    this._message("Saving store changes…");
    try {
      await this._hass.callService(this._config.domain, service, data);
      this._message(successMessage, "success");
      this._lastLoadAt = 0;
      await this._loadItems();
    } catch (error) {
      this._listMessage = error?.message || "The store change could not be confirmed. Refresh and verify Deglaze before retrying.";
      this._listMessageKind = "error";
      this._render();
    } finally {
      this._busyAction = "";
      this._render();
    }
  }

  async _submit(event) {
    event.preventDefault();
    if (!this._hass) return this._message("Home Assistant is not ready yet.", "error");
    const input = this.shadowRoot.querySelector("#item");
    const button = this.shadowRoot.querySelector("#submit");
    const text = input?.value.trim() || "";
    if (!text) return this._message("Enter an ingredient or item first.", "error");
    const [domain, service] = this._config.service.split(".", 2);
    const stores = [...this.shadowRoot.querySelectorAll('input[name="add-store"]:checked')].map((node) => node.value);
    const data = { text, stores };
    if (this._config.manual_category) data.manual_category = this._config.manual_category;
    if (button) button.disabled = true;
    this._message("Adding item…");
    try {
      await this._hass.callService(domain, service, data);
      if (input) input.value = "";
      this._message(`Added “${text}” to Deglaze.`, "success");
      this._lastLoadAt = 0;
      await this._loadItems();
    } catch (error) {
      this._message(error?.message || "Could not add the item. Check the integration status.", "error");
    } finally {
      const currentButton = this.shadowRoot.querySelector("#submit");
      if (currentButton) currentButton.disabled = false;
      this.shadowRoot.querySelector("#item")?.focus();
    }
  }

  async _toggleStatus(item) {
    if (!this._hass || !item?.id) return;
    const nextStatus = deglazeGroceryStatus(item) === "completed" ? "pending" : "completed";
    this._listMessage = `Marking item ${nextStatus === "completed" ? "completed" : "to buy"}…`;
    this._listMessageKind = "";
    this._render();
    try {
      await this._hass.callService(this._config.domain, "set_grocery_item_status", { item_id: item.id, status: nextStatus });
      this._listMessage = nextStatus === "completed" ? "Item marked as completed." : "Item moved back to the shopping list.";
      this._listMessageKind = "success";
      this._lastLoadAt = 0;
      await this._loadItems();
    } catch (error) {
      this._listMessage = error?.message || "Could not update this item's status.";
      this._listMessageKind = "error";
      this._render();
    }
  }

  async _saveItemStores(itemId) {
    if (!this._hass || !itemId || this._busyAction) return;
    const panel = [...this.shadowRoot.querySelectorAll(".assignment-panel")].find((node) => node.dataset.itemId === itemId);
    if (!panel) return;
    const storeIds = [...panel.querySelectorAll('input[type="checkbox"]:checked')].map((node) => node.value);
    await this._runStoreService("set_grocery_item_stores", { item_id: itemId, store_ids: storeIds }, "Store assignments saved.");
  }

  async _addStore(event) {
    event.preventDefault();
    const input = this.shadowRoot.querySelector("#new-store-name");
    const name = input?.value.trim() || "";
    if (!name) return this._message("Enter a store name.", "error");
    await this._runStoreService("create_grocery_store", { name }, `Created store “${name}”.`);
  }

  async _renameStore(storeId) {
    const row = [...this.shadowRoot.querySelectorAll(".store-management-row")].find((node) => node.dataset.storeId === storeId);
    const name = row?.querySelector("input")?.value.trim() || "";
    if (!name) return this._message("Store name cannot be blank.", "error");
    await this._runStoreService("rename_grocery_store", { store_id: storeId, name }, `Renamed store to “${name}”.`);
  }

  async _deleteStore(storeId) {
    if (this._deleteConfirmId !== storeId) {
      this._deleteConfirmId = storeId;
      this._render();
      return;
    }
    const store = this._stores.find((candidate) => candidate.id === storeId);
    this._deleteConfirmId = "";
    await this._runStoreService("delete_grocery_store", { store_id: storeId }, `Deleted store “${store?.name || "store"}”. Grocery items remain on your list.`);
  }

  _category(item) {
    const value = item?.category;
    if (value && typeof value === "object") {
      return {
        primary: deglazeCategoryLabel(value.primary || item.manualCategory || "Uncategorized"),
        sub: deglazeCategoryLabel(value.sub || ""),
      };
    }
    return { primary: deglazeCategoryLabel(value || item?.manualCategory || "Uncategorized"), sub: "" };
  }

  _storeIds(item) {
    const value = item?.stores;
    if (!Array.isArray(value)) return [];
    return [...new Set(value.map((store) => typeof store === "string" ? store : store?.id).filter((id) => typeof id === "string" && id))];
  }

  _sortItems(items) {
    const sorted = [...items];
    sorted.sort((a, b) => {
      if (this._sortBy === "newest") return deglazeCreatedTime(b) - deglazeCreatedTime(a) || String(a.text || "").localeCompare(String(b.text || ""));
      return String(a.text || a.ingredient || "").localeCompare(String(b.text || b.ingredient || ""), undefined, { sensitivity: "base" });
    });
    return sorted;
  }

  _renderItem(item, groupStoreId = "") {
    const status = deglazeGroceryStatus(item);
    const text = item.text || item.ingredient || "Unnamed item";
    const category = this._category(item);
    const storeIds = this._storeIds(item);
    const assignedStores = storeIds.map((id) => this._stores.find((store) => store.id === id)?.name || "").filter(Boolean);
    const itemKey = String(item.id || "");
    const assignmentLabel = assignedStores.length ? assignedStores.join(", ") : "No store assigned";
    return `<article class="item ${status === "completed" ? "completed" : "pending"}" role="listitem">
      <div class="item-line">
        <div class="item-main"><div class="item-name">${deglazeEscape(text)}</div><small class="item-meta">${deglazeEscape(category.primary)}${category.sub && category.sub.toLocaleLowerCase() !== category.primary.toLocaleLowerCase() ? ` · ${deglazeEscape(category.sub)}` : ""}</small>
          ${assignedStores.length ? `<div class="store-chips">${assignedStores.map((name) => `<span class="chip">${deglazeEscape(name)}</span>`).join("")}</div>` : `<small class="item-meta no-store">No store assigned</small>`}
        </div>
        <div class="item-actions"><button class="secondary status-toggle" data-id="${deglazeEscape(itemKey)}" ${!item.id ? "disabled" : ""}>${status === "completed" ? "Mark to buy" : "Mark bought"}</button></div>
      </div>
      <details class="assignment-details"><summary>Assign stores</summary>
        <div class="assignment-panel" data-item-id="${deglazeEscape(itemKey)}">
          ${this._stores.length ? `<div class="assignment-options">${this._stores.map((store) => `<label><input type="checkbox" value="${deglazeEscape(store.id)}" ${storeIds.includes(store.id) ? "checked" : ""} /> ${deglazeEscape(store.name)}</label>`).join("")}</div><button class="secondary save-item-stores" data-id="${deglazeEscape(itemKey)}" ${this._busyAction ? "disabled" : ""}>Save stores</button>` : `<p class="empty">Create a store above to assign items.</p>`}
        </div>
      </details>
    </article>`;
  }

  _render() {
    if (!this.shadowRoot || !this._config) return;
    const query = this._query.trim().toLocaleLowerCase();
    let filtered = this._items.filter((item) => {
      const status = deglazeGroceryStatus(item);
      const text = String(item.text || item.ingredient || "").toLocaleLowerCase();
      const storeIds = this._storeIds(item);
      const storeMatches = this._storeFilter === "all"
        || (this._storeFilter === "__none" ? storeIds.length === 0 : storeIds.includes(this._storeFilter));
      return (this._filter === "all" || status === this._filter) && text.includes(query) && storeMatches;
    });
    filtered = this._sortItems(filtered);

    let grouped = [];
    if (this._groupBy === "store") {
      const groupMap = new Map();
      for (const item of filtered) {
        const storeIds = this._storeIds(item);
        const ids = this._storeFilter !== "all" && this._storeFilter !== "__none"
          ? [this._storeFilter]
          : (storeIds.length ? storeIds : ["__none"]);
        for (const storeId of ids) {
          const name = storeId === "__none" ? "Unassigned" : (this._stores.find((store) => store.id === storeId)?.name || "Unassigned");
          if (!groupMap.has(name)) groupMap.set(name, []);
          if (!groupMap.get(name).some((candidate) => candidate.id === item.id)) groupMap.get(name).push(item);
        }
      }
      grouped = [...groupMap.entries()].sort((a, b) => a[0].localeCompare(b[0], undefined, { sensitivity: "base" })).map(([name, items]) => ({ name, items }));
    } else if (this._groupBy === "category") {
      const groupMap = new Map();
      for (const item of filtered) {
        const name = this._category(item).primary || "Uncategorized";
        if (!groupMap.has(name)) groupMap.set(name, []);
        groupMap.get(name).push(item);
      }
      grouped = [...groupMap.entries()].sort((a, b) => a[0].localeCompare(b[0], undefined, { sensitivity: "base" })).map(([name, items]) => ({ name, items }));
    } else {
      grouped = filtered.length ? [{ name: "", items: filtered }] : [];
    }

    const storeFilterOptions = [
      `<option value="all" ${this._storeFilter === "all" ? "selected" : ""}>All stores</option>`,
      `<option value="__none" ${this._storeFilter === "__none" ? "selected" : ""}>No store</option>`,
      ...this._stores.map((store) => `<option value="${deglazeEscape(store.id)}" ${this._storeFilter === store.id ? "selected" : ""}>${deglazeEscape(store.name)}</option>`),
    ].join("");
    const addStoreOptions = this._stores.length ? `<details class="add-store-details"><summary>Assign store on add (optional)</summary><div class="assignment-options add-store-options">${this._stores.map((store) => `<label><input type="checkbox" name="add-store" value="${deglazeEscape(store.id)}" /> ${deglazeEscape(store.name)}</label>`).join("")}</div></details>` : `<small class="muted">You can create stores below and assign them to items.</small>`;
    const storeManager = this._manageStoresOpen ? `<section class="stores-panel">
      <div class="panel-intro">Create and manage your Deglaze stores. Deleting a store removes its associations, but does not delete grocery items.</div>
      <form id="add-store-form" class="add-store-form"><input id="new-store-name" maxlength="100" placeholder="New store name…" aria-label="New store name" required /><button class="primary" type="submit" ${this._busyAction ? "disabled" : ""}>Add store</button></form>
      ${this._stores.length ? this._stores.map((store) => `<div class="store-management-row" data-store-id="${deglazeEscape(store.id)}"><input aria-label="Store name" value="${deglazeEscape(store.name)}" maxlength="100" /><button class="secondary rename-store" data-id="${deglazeEscape(store.id)}" ${this._busyAction ? "disabled" : ""}>Save name</button>${this._deleteConfirmId === store.id ? `<button class="secondary confirm-delete-store" data-id="${deglazeEscape(store.id)}" ${this._busyAction ? "disabled" : ""}>Confirm delete</button><button class="secondary cancel-delete-store" data-id="${deglazeEscape(store.id)}">Cancel</button>` : `<button class="secondary delete-store" data-id="${deglazeEscape(store.id)}" ${this._busyAction ? "disabled" : ""}>Delete</button>`}</div>`).join("") : `<p class="empty">No stores created yet.</p>`}
    </section>` : "";

    this.shadowRoot.innerHTML = `<style>${deglazeBaseStyles}
      .topline { display:flex; justify-content:space-between; align-items:center; gap:10px; margin:6px 0 12px; }
      .counts { font-size:.84rem; color:var(--secondary-text-color); }
      form.add-item-form { display:flex; gap:8px; align-items:stretch; margin-top:14px; }
      form.add-item-form input { flex:1; }
      .list-controls { display:grid; grid-template-columns:minmax(0,1fr) minmax(120px,.55fr); gap:8px; margin:12px 0 8px; }
      .extended-controls { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:8px; margin:8px 0 12px; }
      .control-label { display:block; font-size:.78rem; color:var(--secondary-text-color); margin:0 0 4px 2px; }
      .items { border-top:1px solid var(--divider-color); max-height:600px; overflow:auto; }
      .item { padding:10px 2px; border-bottom:1px solid var(--divider-color); }
      .item-line { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:10px; align-items:center; }
      .item-main { min-width:0; }
      .item-name { overflow-wrap:anywhere; font-weight:500; }
      .item.completed .item-name { text-decoration:line-through; color:var(--secondary-text-color); }
      .item-meta { display:block; margin-top:3px; color:var(--secondary-text-color); font-size:.77rem; }
      .no-store { opacity:.8; }
      .store-chips { display:flex; flex-wrap:wrap; gap:4px; margin-top:5px; }
      .chip { font-size:.73rem; background:var(--secondary-background-color); border:1px solid var(--divider-color); border-radius:999px; padding:2px 7px; }
      .item-actions { display:flex; gap:6px; flex-wrap:wrap; justify-content:flex-end; }
      details.assignment-details, details.add-store-details { margin-top:8px; }
      details summary { cursor:pointer; color:var(--secondary-text-color); font-size:.86rem; }
      .assignment-panel { padding:8px 0 2px; }
      .assignment-options { display:flex; flex-wrap:wrap; gap:8px 14px; margin:4px 0 10px; }
      .assignment-options label { display:inline-flex; align-items:center; gap:5px; font-size:.9rem; }
      .assignment-options input { width:auto; }
      .manage-header { display:flex; justify-content:space-between; align-items:center; gap:10px; margin:8px 0; }
      .stores-panel { border:1px solid var(--divider-color); border-radius:10px; padding:12px; margin:8px 0 12px; }
      .panel-intro { font-size:.84rem; color:var(--secondary-text-color); margin-bottom:10px; }
      form.add-store-form { display:flex; gap:8px; margin:0 0 10px; }
      .store-management-row { display:grid; grid-template-columns:minmax(0,1fr) auto auto auto; gap:6px; padding:8px 0; border-top:1px solid var(--divider-color); align-items:center; }
      .empty { padding:14px 0; color:var(--secondary-text-color); }
      .group-title { display:flex; justify-content:space-between; gap:8px; align-items:center; padding:10px 2px 3px; font-weight:600; }
      @media(max-width:560px) { form.add-item-form { flex-direction:column; } .list-controls,.extended-controls { grid-template-columns:1fr; } .item-line { grid-template-columns:minmax(0,1fr); } .item-actions { justify-content:flex-start; } .store-management-row { grid-template-columns:minmax(0,1fr) auto; } .store-management-row input { grid-column:1/-1; } }
    </style>
    <section class="card">
      <h2>${deglazeEscape(this._config.title)}</h2>
      <form id="form" class="add-item-form">
        <input id="item" name="item" type="text" maxlength="500" required autocomplete="off" placeholder="${deglazeEscape(this._config.placeholder)}" aria-label="Grocery item" />
        <button class="primary" id="submit" type="submit">Add item</button>
      </form>
      ${addStoreOptions}
      <div class="message ${deglazeEscape(this._listMessageKind || "")}" id="message" role="status" aria-live="polite">${deglazeEscape(this._listMessage || "")}</div>
      <div class="topline"><span class="counts">${this._counts.pending_count || 0} to buy · ${this._counts.completed_count || 0} completed · ${this._counts.item_count || 0} total</span><button class="secondary" id="refresh" ${this._loadingList ? "disabled" : ""}>${this._loadingList ? "Refreshing…" : "Refresh list"}</button></div>
      ${this._listError ? `<div class="message error" role="status">${deglazeEscape(this._listError)}</div>` : ""}
      <div class="list-controls">
        <input id="search" type="search" value="${deglazeEscape(this._query)}" placeholder="Search current list…" aria-label="Search grocery list" />
        <select id="filter" aria-label="Filter grocery items">
          <option value="all" ${this._filter === "all" ? "selected" : ""}>All items (${this._counts.item_count || 0})</option>
          <option value="pending" ${this._filter === "pending" ? "selected" : ""}>To buy (${this._counts.pending_count || 0})</option>
          <option value="completed" ${this._filter === "completed" ? "selected" : ""}>Completed (${this._counts.completed_count || 0})</option>
        </select>
      </div>
      <div class="extended-controls">
        <label><span class="control-label">Filter by store</span><select id="store-filter" aria-label="Filter by store">${storeFilterOptions}</select></label>
        <label><span class="control-label">Group items</span><select id="group-by" aria-label="Group grocery items"><option value="none" ${this._groupBy === "none" ? "selected" : ""}>No grouping</option><option value="store" ${this._groupBy === "store" ? "selected" : ""}>By store</option><option value="category" ${this._groupBy === "category" ? "selected" : ""}>By category</option></select></label>
        <label><span class="control-label">Sort items</span><select id="sort-by" aria-label="Sort grocery items"><option value="alpha" ${this._sortBy === "alpha" ? "selected" : ""}>Alphabetical</option><option value="newest" ${this._sortBy === "newest" ? "selected" : ""}>Newest first</option></select></label>
      </div>
      <div class="manage-header"><span class="muted">${this._stores.length} ${this._stores.length === 1 ? "store" : "stores"}</span><button class="secondary" id="manage-stores">${this._manageStoresOpen ? "Hide stores" : "Manage stores"}</button></div>
      ${storeManager}
      <div class="items" role="list" aria-label="Deglaze grocery list">
        ${this._loadingList && !this._items.length ? `<p class="empty">Loading grocery list…</p>` : ""}
        ${!this._loadingList && !this._listError && !filtered.length ? `<p class="empty">${this._items.length ? "No items match the current filters." : "No grocery items found."}</p>` : ""}
        ${grouped.map((group) => `${group.name ? `<div class="group-title"><span>${deglazeEscape(group.name)}</span><span class="muted">${group.items.length} ${group.items.length === 1 ? "item" : "items"}</span></div>` : ""}${group.items.map((item) => this._renderItem(item, "")).join("")}`).join("")}
      </div>
      ${this._groupBy === "store" && this._storeFilter === "all" ? `<small class="muted">Items assigned to multiple stores appear in each applicable group.</small>` : ""}
    </section>`;

    this.shadowRoot.querySelector("#form")?.addEventListener("submit", (event) => this._submit(event));
    this.shadowRoot.querySelector("#refresh")?.addEventListener("click", () => { this._lastLoadAt = 0; this._loadItems(); });
    this.shadowRoot.querySelector("#filter")?.addEventListener("change", (event) => { this._filter = event.target.value; this._render(); });
    this.shadowRoot.querySelector("#store-filter")?.addEventListener("change", (event) => { this._storeFilter = event.target.value; this._render(); });
    this.shadowRoot.querySelector("#group-by")?.addEventListener("change", (event) => { this._groupBy = event.target.value; this._render(); });
    this.shadowRoot.querySelector("#sort-by")?.addEventListener("change", (event) => { this._sortBy = event.target.value; this._render(); });
    this.shadowRoot.querySelector("#manage-stores")?.addEventListener("click", () => { this._manageStoresOpen = !this._manageStoresOpen; this._render(); });
    this.shadowRoot.querySelector("#add-store-form")?.addEventListener("submit", (event) => this._addStore(event));
    this.shadowRoot.querySelectorAll(".status-toggle").forEach((button) => button.addEventListener("click", () => {
      const item = this._items.find((candidate) => candidate.id === button.dataset.id);
      if (item) this._toggleStatus(item);
    }));
    this.shadowRoot.querySelectorAll(".save-item-stores").forEach((button) => button.addEventListener("click", () => this._saveItemStores(button.dataset.id)));
    this.shadowRoot.querySelectorAll(".rename-store").forEach((button) => button.addEventListener("click", () => this._renameStore(button.dataset.id)));
    this.shadowRoot.querySelectorAll(".delete-store").forEach((button) => button.addEventListener("click", () => { this._deleteConfirmId = button.dataset.id; this._render(); }));
    this.shadowRoot.querySelectorAll(".confirm-delete-store").forEach((button) => button.addEventListener("click", () => this._deleteStore(button.dataset.id)));
    this.shadowRoot.querySelectorAll(".cancel-delete-store").forEach((button) => button.addEventListener("click", () => { this._deleteConfirmId = ""; this._render(); }));
    this.shadowRoot.querySelectorAll("#search").forEach((input) => input.addEventListener("input", (event) => {
      const target = event.target;
      const caret = target.selectionStart;
      this._query = target.value;
      this._render();
      const next = this.shadowRoot.querySelector("#search");
      next?.focus();
      try { next?.setSelectionRange(caret, caret); } catch (_) { /* Browser support varies. */ }
    }));
  }

  static getConfigElement() { return document.createElement("deglaze-grocery-add-card-editor"); }
  static getStubConfig() { return { title: "Grocery list", default_filter: "pending", grid_columns: 6 }; }
  getGridOptions() {
    const columns = [3, 6, 9, 12].includes(Number(this._config.grid_columns)) ? Number(this._config.grid_columns) : 6;
    return { columns, rows: 6, min_columns: 3, max_columns: 12, min_rows: 3 };
  }
  getCardSize() { return 8; }
}

const deglazeCategoryLabel = (value) => {
  if (typeof value !== "string" || !value.trim()) return "Uncategorized";
  return value.trim().replace(/[_-]+/g, " ").replace(/\b\w/g, (char) => char.toLocaleUpperCase());
};

const deglazeCreatedTime = (item) => {
  if (typeof item?.created === "number" && Number.isFinite(item.created)) return item.created;
  if (typeof item?.created === "string") {
    const parsed = Date.parse(item.created);
    if (Number.isFinite(parsed)) return parsed;
    const numeric = Number(item.created);
    if (Number.isFinite(numeric)) return numeric;
  }
  return 0;
};

const deglazeGroceryStatus = (item) => {
  let value = item?.status_text ?? item?.status;
  if (value && typeof value === "object") value = value.status;
  return typeof value === "string" && value.toLowerCase() === "completed" ? "completed" : "pending";
};

class DeglazeUpcomingMealsCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = undefined;
    this._config = { count: 5, title: "Upcoming meals", domain: "deglaze_poc", entity: "sensor.deglaze_meal_plan", refresh_interval: 60, meal_types: ["Breakfast", "Lunch", "Dinner", "Snack"], grid_columns: 6 };
    this._plan = undefined;
    this._loading = false;
    this._lastLoadAt = 0;
    this._error = "";
    this._timer = undefined;
  }

  setConfig(config) {
    const previousRefreshInterval = this._config?.refresh_interval;
    this._config = { count: 5, title: "Upcoming meals", domain: "deglaze_poc", entity: "sensor.deglaze_meal_plan", refresh_interval: 60, meal_types: ["Breakfast", "Lunch", "Dinner", "Snack"], grid_columns: 6, ...config };
    this._config.count = Math.max(1, Math.min(20, Number.parseInt(this._config.count, 10) || 5));
    this._config.refresh_interval = Math.max(30, Math.min(300, Number.parseInt(this._config.refresh_interval, 10) || 60));
    if (this._timer && previousRefreshInterval !== this._config.refresh_interval) {
      window.clearInterval(this._timer);
      this._timer = window.setInterval(() => this._loadPlan(), this._config.refresh_interval * 1000);
    }
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    if (this.isConnected && (!this._lastLoadAt || Date.now() - this._lastLoadAt > this._config.refresh_interval * 1000)) this._loadPlan();
  }
  get hass() { return this._hass; }

  connectedCallback() {
    this._render();
    this._loadPlan();
    if (!this._timer) this._timer = window.setInterval(() => this._loadPlan(), this._config.refresh_interval * 1000);
  }

  disconnectedCallback() {
    if (this._timer) window.clearInterval(this._timer);
    this._timer = undefined;
  }

  async _loadPlan() {
    if (!this._hass || this._loading) return;
    this._loading = true;
    this._lastLoadAt = Date.now();
    this._render();
    try {
      this._plan = await this._hass.callWS({ type: `${this._config.domain}/meal-plan` });
      this._error = this._plan?.sync_error || "";
    } catch (error) {
      this._error = error?.message || "Could not load the Deglaze meal plan.";
    } finally {
      this._loading = false;
      this._render();
    }
  }

  async _refreshPlan() {
    if (!this._hass || this._loading) return;
    try {
      await this._hass.callService(this._config.domain, "refresh", {});
      this._lastLoadAt = 0;
      await this._loadPlan();
    } catch (error) {
      this._error = error?.message || "Could not refresh the meal plan.";
      this._render();
    }
  }

  _render() {
    if (!this.shadowRoot || !this._config) return;
    const fallbackState = this._hass?.states?.[this._config.entity];
    const fallbackAttributes = fallbackState?.attributes || {};
    const data = this._plan || (fallbackState ? fallbackAttributes : undefined);
    const items = Array.isArray(data?.items) ? data.items : [];
    const today = deglazeToday();
    const selectedMealTypes = Array.isArray(this._config.meal_types)
      ? this._config.meal_types.map((label) => String(label).toLocaleLowerCase())
      : [];
    const upcoming = items
      .filter((item) => item && item.deleted !== true && typeof item.date === "string" && item.date >= today)
      .filter((item) => !selectedMealTypes.length || selectedMealTypes.includes(deglazeMealLabel(item.label).toLocaleLowerCase()))
      .sort((a, b) => a.date.localeCompare(b.date) || deglazeMealOrder(a.label) - deglazeMealOrder(b.label))
      .slice(0, this._config.count);
    const error = this._error || data?.sync_error;
    this.shadowRoot.innerHTML = `<style>${deglazeBaseStyles}
      .header { display:flex; justify-content:space-between; gap:12px; align-items:center; margin-bottom:12px; }
      .count { font-size:.82rem; color:var(--secondary-text-color); white-space:nowrap; }
      .meal { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:8px 12px; padding:12px 0; border-top:1px solid var(--divider-color); }
      .meal:first-child { border-top:0; }
      .meal-name { font-weight:600; overflow-wrap:anywhere; }
      .date { color:var(--secondary-text-color); font-size:.88rem; margin-top:4px; }
      .badge { display:inline-flex; align-items:center; align-self:start; white-space:nowrap; border-radius:999px; padding:5px 9px; background:var(--secondary-background-color); border:1px solid var(--divider-color); font-size:.78rem; }
      .leftovers { display:inline-block; margin-top:5px; font-size:.76rem; color:var(--secondary-text-color); }
      .empty { padding:14px 0 4px; color:var(--secondary-text-color); }
      @media(max-width:440px) { .meal { grid-template-columns:1fr; } .badge { justify-self:start; } }
    </style>
    <section class="card">
      <div class="header"><h2>${deglazeEscape(this._config.title)}</h2><div><span class="count">${upcoming.length} shown</span> <button class="secondary" id="refresh" ${this._loading ? "disabled" : ""}>${this._loading ? "Loading…" : "Refresh"}</button></div></div>
      ${!data && this._loading ? `<p class="empty">Loading your meal plan…</p>` : ""}
      ${!data && !this._loading ? `<p class="empty">Meal-plan data is not available yet. Check the Deglaze integration's API Status sensor for sync errors.</p>` : ""}
      ${error ? `<p class="message error">Meal-plan issue: ${deglazeEscape(error)}</p>` : ""}
      ${data && !error && upcoming.length === 0 ? `<p class="empty">No upcoming meals found in the synchronized range.</p>` : ""}
      ${upcoming.map((item) => {
        const label = deglazeMealLabel(item.label);
        const title = item.recipe_title || item.title || "Planned recipe";
        return `<article class="meal">
          <div><div class="meal-name">${deglazeEscape(title)}</div><div class="date">${deglazeEscape(deglazeFormatDate(item.date))}</div>${item.isLeftovers ? `<span class="leftovers">Leftovers</span>` : ""}</div>
          <span class="badge">${deglazeEscape(deglazeMealBadge(label))}</span>
        </article>`;
      }).join("")}
      ${data ? `<div class="message">Range: ${deglazeEscape(data.start || "?")} – ${deglazeEscape(data.end || "?")}</div>` : ""}
    </section>`;
    this.shadowRoot.querySelector("#refresh")?.addEventListener("click", () => this._refreshPlan());
  }

  static getConfigElement() { return document.createElement("deglaze-upcoming-meals-card-editor"); }
  static getStubConfig() { return { title: "Upcoming meals", count: 5, meal_types: ["Breakfast", "Lunch", "Dinner", "Snack"], grid_columns: 6 }; }
  getGridOptions() {
    const columns = [3, 6, 9, 12].includes(Number(this._config.grid_columns)) ? Number(this._config.grid_columns) : 6;
    return { columns, rows: 4, min_columns: 3, max_columns: 12, min_rows: 2 };
  }
  getCardSize() { return Math.max(2, this._config.count + 1); }
}

const deglazeDateShift = (dateValue, offsetDays) => {
  const parsed = new Date(`${dateValue}T12:00:00`);
  if (Number.isNaN(parsed.getTime())) return dateValue;
  parsed.setDate(parsed.getDate() + offsetDays);
  return `${parsed.getFullYear()}-${String(parsed.getMonth() + 1).padStart(2, "0")}-${String(parsed.getDate()).padStart(2, "0")}`;
};

const deglazeWeekStart = (dateValue = deglazeToday()) => {
  const parsed = new Date(`${dateValue}T12:00:00`);
  if (Number.isNaN(parsed.getTime())) return dateValue;
  parsed.setDate(parsed.getDate() - ((parsed.getDay() + 6) % 7));
  return `${parsed.getFullYear()}-${String(parsed.getMonth() + 1).padStart(2, "0")}-${String(parsed.getDate()).padStart(2, "0")}`;
};

const deglazeDayHeading = (dateValue) => {
  const parsed = new Date(`${dateValue}T12:00:00`);
  if (Number.isNaN(parsed.getTime())) return dateValue;
  return new Intl.DateTimeFormat(undefined, { weekday: "short", day: "numeric", month: "short" }).format(parsed);
};

const deglazeClampDisplayDays = (value) => {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) ? Math.max(1, Math.min(7, parsed)) : 7;
};

const deglazeDisplayedDates = (weekStart, displayDays) =>
  Array.from({ length: deglazeClampDisplayDays(displayDays) }, (_, index) => deglazeDateShift(weekStart, index));

class DeglazeWeeklyMealPlannerCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = undefined;
    this._config = { title: "Weekly meal planner", domain: "deglaze_poc", grid_columns: 12, refresh_interval: 120, display_days: 7 };
    this._weekStart = deglazeWeekStart();
    this._plan = undefined;
    this._loading = false;
    this._savingId = "";
    this._removingId = "";
    this._editingId = "";
    this._confirmRemoveId = "";
    this._lastLoadAt = 0;
    this._error = "";
    this._message = "";
    this._timer = undefined;
  }

  setConfig(config) {
    const previousInterval = this._config?.refresh_interval;
    this._config = { title: "Weekly meal planner", domain: "deglaze_poc", grid_columns: 12, refresh_interval: 120, display_days: 7, ...config };
    this._config.refresh_interval = Math.max(60, Math.min(600, Number.parseInt(this._config.refresh_interval, 10) || 120));
    this._config.display_days = deglazeClampDisplayDays(this._config.display_days);
    if (this._timer && previousInterval !== this._config.refresh_interval) {
      window.clearInterval(this._timer);
      this._timer = window.setInterval(() => this._loadPlan(), this._config.refresh_interval * 1000);
    }
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    if (this.isConnected && (!this._lastLoadAt || Date.now() - this._lastLoadAt > this._config.refresh_interval * 1000)) this._loadPlan();
  }
  get hass() { return this._hass; }

  connectedCallback() {
    this._render();
    this._loadPlan();
    if (!this._timer) this._timer = window.setInterval(() => this._loadPlan(), this._config.refresh_interval * 1000);
  }

  disconnectedCallback() {
    if (this._timer) window.clearInterval(this._timer);
    this._timer = undefined;
  }

  get _weekEnd() { return deglazeDateShift(this._weekStart, 6); }

  async _loadPlan() {
    if (!this._hass || this._loading) return;
    this._loading = true;
    this._lastLoadAt = Date.now();
    this._render();
    try {
      this._plan = await this._hass.callWS({
        type: `${this._config.domain}/meal-plan/range`,
        start: this._weekStart,
        end: this._weekEnd,
      });
      this._error = this._plan?.sync_error || "";
    } catch (error) {
      this._error = error?.message || "Could not load this week's Deglaze meal plan.";
    } finally {
      this._loading = false;
      this._render();
    }
  }

  async _moveWeek(offset) {
    this._weekStart = deglazeDateShift(this._weekStart, offset * 7);
    this._editingId = "";
    this._confirmRemoveId = "";
    this._message = "";
    await this._loadPlan();
  }

  async _refreshCurrentWeek() {
    if (!this._hass || this._loading) return;
    this._message = "Refreshing this week…";
    try {
      await this._hass.callService(this._config.domain, "refresh", {});
    } catch (_error) {
      // The exact visible week is fetched below; a coordinator refresh may only cover the rolling window.
    }
    this._lastLoadAt = 0;
    await this._loadPlan();
    if (!this._error) this._message = "Week refreshed.";
    this._render();
  }

  async _savePlannedItem(item, form) {
    const itemId = item?.id;
    if (!itemId || !Number.isFinite(Number(item.version))) {
      this._message = "This meal is missing an ID or version, so it cannot be edited safely.";
      this._render();
      return;
    }
    const dateInput = form.querySelector('[data-field="date"]')?.value;
    const labelInput = form.querySelector('[data-field="label"]')?.value;
    const leftoversInput = Boolean(form.querySelector('[data-field="leftovers"]')?.checked);
    const updates = {};
    if (dateInput && dateInput !== item.date) updates.date = dateInput;
    const currentLabel = deglazeMealLabel(item.label);
    if (labelInput && labelInput !== currentLabel && ["Breakfast", "Lunch", "Dinner", "Snack"].includes(labelInput)) updates.label = labelInput;
    if (leftoversInput !== Boolean(item.isLeftovers)) updates.is_leftovers = leftoversInput;
    if (!Object.keys(updates).length) {
      this._message = "No changes to save.";
      this._editingId = "";
      this._render();
      return;
    }
    this._savingId = itemId;
    this._message = "Saving meal changes…";
    this._error = "";
    this._render();
    const serviceData = { item_id: itemId, item_type: item.type || "recipe", version: Number(item.version), ...updates };
    try {
      await this._hass.callService(this._config.domain, "update_meal_plan_item", serviceData);
      this._editingId = "";
      this._lastLoadAt = 0;
      await this._loadPlan();
      const updated = (this._plan?.items || []).find((candidate) => candidate.id === itemId);
      const displayEnd = deglazeDateShift(this._weekStart, this._config.display_days - 1);
      const expectedInWeek = updates.date ? (updates.date >= this._weekStart && updates.date <= this._weekEnd) : true;
      const expectedInDisplayedRange = updates.date ? (updates.date >= this._weekStart && updates.date <= displayEnd) : true;
      const correctDate = !updates.date || (expectedInWeek ? updated?.date === updates.date : !updated);
      const correctLabel = !expectedInWeek || !updates.label || deglazeMealLabel(updated?.label) === updates.label;
      const correctLeftovers = !expectedInWeek || updates.is_leftovers === undefined || Boolean(updated?.isLeftovers) === updates.is_leftovers;
      if (!this._error && correctDate && correctLabel && correctLeftovers && (expectedInWeek ? Boolean(updated) : true)) {
        if (!expectedInWeek) {
          this._message = "The meal was moved out of this week. Verify the updated slot and leftovers setting in Deglaze.";
        } else if (!expectedInDisplayedRange) {
          this._message = "Meal changes saved and verified. The meal is now on a day hidden by this card's displayed-days setting.";
        } else {
          this._message = "Meal changes saved and verified.";
        }
      } else {
        this._message = "The update was sent, but this week has not yet reflected every change. Refresh and verify on Deglaze before retrying.";
      }
    } catch (error) {
      this._message = error?.message || "Could not update the planned meal.";
    } finally {
      this._savingId = "";
      this._render();
    }
  }

  async _removePlannedItem(item) {
    const itemId = item?.id;
    if (!itemId) return;
    this._removingId = itemId;
    this._message = "Removing planned meal…";
    this._error = "";
    this._render();
    try {
      await this._hass.callService(this._config.domain, "remove_meal_plan_item", { item_id: itemId });
      this._confirmRemoveId = "";
      this._editingId = "";
      this._lastLoadAt = 0;
      await this._loadPlan();
      if (!(this._plan?.items || []).some((candidate) => candidate.id === itemId)) {
        this._message = "Planned meal removed and verified.";
      } else {
        this._message = "The removal was sent, but the meal is still present in the response. Refresh and verify on Deglaze before retrying.";
      }
    } catch (error) {
      this._message = error?.message || "Could not remove the planned meal.";
    } finally {
      this._removingId = "";
      this._render();
    }
  }

  _render() {
    if (!this.shadowRoot || !this._config) return;
    const items = Array.isArray(this._plan?.items) ? this._plan.items : [];
    const displayDayCount = deglazeClampDisplayDays(this._config.display_days);
    const displayedDates = deglazeDisplayedDates(this._weekStart, displayDayCount);
    const displayEnd = displayedDates[displayedDates.length - 1];
    const days = displayedDates.map((date) => {
      const dayItems = items.filter((item) => item && item.deleted !== true && item.date === date)
        .sort((a, b) => deglazeMealOrder(a.label) - deglazeMealOrder(b.label) || String(a.recipe_title || "").localeCompare(String(b.recipe_title || "")));
      return { date, items: dayItems };
    });
    const visibleItems = items.filter((item) => item && item.deleted !== true && item.date >= this._weekStart && item.date <= displayEnd);
    const weekHeading = displayDayCount === 1
      ? deglazeFormatDate(this._weekStart)
      : `${deglazeFormatDate(this._weekStart)} – ${deglazeFormatDate(displayEnd)}`;
    const labelOptions = ["Breakfast", "Lunch", "Dinner", "Snack"];
    const hasStandardSlot = (item) => labelOptions.some((label) => label.toLowerCase() === deglazeMealLabel(item.label).toLowerCase());
    // Keep the four familiar meal columns stable. If Deglaze returns an unexpected
    // custom label in the displayed days, preserve those entries in an additional Other column.
    const hasOtherSlotItems = visibleItems.some((item) => !hasStandardSlot(item));
    const slotColumns = hasOtherSlotItems ? [...labelOptions, "Other"] : labelOptions;
    const renderItem = (item, showSlotBadge = false) => {
      const id = String(item.id || "");
      const currentLabel = deglazeMealLabel(item.label);
      const editing = this._editingId === id;
      const confirmingRemoval = this._confirmRemoveId === id;
      const busy = this._savingId === id || this._removingId === id;
      const labelOptionsHtml = [...new Set([currentLabel, ...labelOptions].filter(Boolean))].map((label) =>
        `<option value="${deglazeEscape(label)}" ${label === currentLabel ? "selected" : ""}>${deglazeEscape(label)}</option>`).join("");
      return `<article class="meal-item" data-plan-id="${deglazeEscape(id)}">
        <div class="item-head">${showSlotBadge ? `<span class="badge">${deglazeEscape(deglazeMealBadge(currentLabel))}</span>` : ""}${item.isLeftovers ? `<span class="leftovers">Leftovers</span>` : ""}</div>
        <div class="recipe-title">${deglazeEscape(item.recipe_title || item.title || (item.type === "note" ? "Meal note" : "Planned recipe"))}</div>
        <div class="item-actions">${id ? `<button class="secondary" data-action="edit" ${busy ? "disabled" : ""}>Edit</button><button class="secondary danger" data-action="remove" ${busy ? "disabled" : ""}>Remove</button>` : `<span class="muted">No item ID</span>`}</div>
        ${editing ? `<div class="edit-form">
          <label>Date<input type="date" data-field="date" value="${deglazeEscape(item.date || this._weekStart)}" /></label>
          <label>Meal slot<select data-field="label">${labelOptionsHtml}</select></label>
          ${item.type !== "note" ? `<label class="check"><input type="checkbox" data-field="leftovers" ${item.isLeftovers ? "checked" : ""}/> Leftovers</label>` : ""}
          <div class="item-actions"><button class="primary" data-action="save" ${busy ? "disabled" : ""}>${busy ? "Saving…" : "Save changes"}</button><button class="secondary" data-action="cancel-edit">Cancel</button></div>
        </div>` : ""}
        ${confirmingRemoval ? `<div class="confirm-remove"><span>Remove this meal from the plan?</span><div class="item-actions"><button class="primary danger" data-action="confirm-remove" ${busy ? "disabled" : ""}>${busy ? "Removing…" : "Confirm remove"}</button><button class="secondary" data-action="cancel-remove">Cancel</button></div></div>` : ""}
      </article>`;
    };
    const slotContents = (day, slot) => {
      const matching = day.items.filter((item) => slot === "Other"
        ? !hasStandardSlot(item)
        : deglazeMealLabel(item.label).toLowerCase() === slot.toLowerCase());
      return matching.length
        ? matching.map((item) => renderItem(item, slot === "Other")).join("")
        : `<div class="empty-slot" aria-label="No ${deglazeEscape(slot.toLowerCase())} planned">—</div>`;
    };
    const plannerCells = `${`<div class="week-cell grid-corner">Day</div>`}${slotColumns.map((slot) => `<div class="week-cell slot-heading">${deglazeEscape(slot)}</div>`).join("")}${days.map((day) => `<div class="week-cell day-label"><span>${deglazeEscape(deglazeDayHeading(day.date))}</span></div>${slotColumns.map((slot) => `<div class="week-cell slot-cell">${slotContents(day, slot)}</div>`).join("")}`).join("")}`;
    this.shadowRoot.innerHTML = `<style>${deglazeBaseStyles}
      .header { display:flex; flex-wrap:wrap; justify-content:space-between; align-items:center; gap:10px; margin-bottom:12px; }
      .week-nav { display:flex; flex-wrap:wrap; align-items:center; gap:6px; }
      .week-title { font-weight:600; margin:0 5px; }
      .week-scroll { max-width:100%; overflow-x:auto; overscroll-behavior-x:contain; border:1px solid var(--divider-color); border-radius:10px; }
      .week-grid { display:grid; grid-template-columns:minmax(88px,.72fr) repeat(${slotColumns.length},minmax(132px,1fr)); min-width:${hasOtherSlotItems ? 780 : 620}px; align-items:stretch; }
      .week-cell { box-sizing:border-box; min-width:0; padding:8px; border-right:1px solid var(--divider-color); border-bottom:1px solid var(--divider-color); }
      .week-cell:nth-child(${slotColumns.length + 1}n) { border-right:0; }
      .grid-corner, .slot-heading { display:flex; align-items:center; min-height:42px; background:var(--secondary-background-color); font-weight:600; }
      .grid-corner { position:sticky; left:0; z-index:3; }
      .slot-heading { position:sticky; top:0; z-index:2; }
      .day-label { position:sticky; left:0; z-index:1; display:flex; align-items:flex-start; padding-top:13px; background:var(--secondary-background-color); font-weight:600; line-height:1.3; overflow-wrap:anywhere; }
      .slot-cell { display:flex; flex-direction:column; gap:8px; min-height:100px; background:var(--card-background-color, transparent); }
      .empty-slot { padding:9px 0; color:var(--secondary-text-color); text-align:center; opacity:.7; }
      .scroll-hint { display:none; margin:0 0 8px; font-size:.8rem; color:var(--secondary-text-color); }
      .meal-item { min-width:0; border:1px solid var(--divider-color); border-radius:8px; padding:8px; overflow-wrap:anywhere; background:var(--ha-card-background,var(--card-background-color)); }
      .item-head { display:flex; align-items:start; flex-wrap:wrap; gap:5px; min-height:3px; }
      .badge { border:1px solid var(--divider-color); border-radius:999px; padding:3px 7px; font-size:.74rem; background:var(--secondary-background-color); }
      .leftovers { font-size:.74rem; color:var(--secondary-text-color); }
      .recipe-title { font-weight:600; line-height:1.3; margin:5px 0; }
      .item-actions { display:flex; flex-wrap:wrap; gap:5px; margin-top:8px; }
      .item-actions button { padding:5px 7px; font-size:.78rem; }
      .edit-form { display:grid; gap:8px; margin-top:10px; padding-top:9px; border-top:1px solid var(--divider-color); }
      .edit-form label { display:grid; gap:4px; font-size:.82rem; }
      .edit-form .check { display:flex; align-items:center; gap:7px; }
      .edit-form .check input { width:auto; }
      .danger { border-color:var(--error-color,#db4437); }
      .confirm-remove { margin-top:8px; font-size:.86rem; }
      .message.error { color:var(--error-color,#db4437); }
      @container (max-width:680px) { .scroll-hint { display:block; } }
    </style>
    <section class="card" style="container-type:inline-size">
      <div class="header">
        <h2>${deglazeEscape(this._config.title)}</h2>
        <div class="week-nav">
          <button class="secondary" data-action="previous-week" aria-label="Previous week" ${this._loading ? "disabled" : ""}>‹</button>
          <button class="secondary" data-action="current-week" ${this._loading ? "disabled" : ""}>This week</button>
          <button class="secondary" data-action="next-week" aria-label="Next week" ${this._loading ? "disabled" : ""}>›</button>
          <span class="week-title">${deglazeEscape(weekHeading)}</span>
          <button class="secondary" data-action="refresh" ${this._loading ? "disabled" : ""}>${this._loading ? "Loading…" : "Refresh"}</button>
        </div>
      </div>
      ${!this._plan && this._loading ? `<p class="muted">Loading your weekly meal plan…</p>` : ""}
      ${!this._plan && !this._loading ? `<p class="muted">Meal-plan data is not available yet. Check the integration's API Status sensor.</p>` : ""}
      ${this._error ? `<p class="message error">Meal-plan issue: ${deglazeEscape(this._error)}</p>` : ""}
      ${this._plan ? `<p class="scroll-hint">Scroll horizontally to see all meal slots.</p><div class="week-scroll" role="region" aria-label="Weekly meal plan by day and meal slot" tabindex="0"><div class="week-grid">${plannerCells}</div></div>` : ""}
      ${this._message ? `<p class="message">${deglazeEscape(this._message)}</p>` : ""}
      ${this._plan ? `<p class="muted">Showing ${visibleItems.length} planned item${visibleItems.length === 1 ? "" : "s"} across ${displayDayCount} displayed day${displayDayCount === 1 ? "" : "s"}. Full Monday–Sunday plan loaded.</p>` : ""}
    </section>`;

    const action = (name) => this.shadowRoot.querySelectorAll(`[data-action="${name}"]`);
    action("previous-week").forEach((button) => button.addEventListener("click", () => this._moveWeek(-1)));
    action("next-week").forEach((button) => button.addEventListener("click", () => this._moveWeek(1)));
    action("current-week").forEach((button) => button.addEventListener("click", () => { this._weekStart = deglazeWeekStart(); this._message = ""; this._loadPlan(); }));
    action("refresh").forEach((button) => button.addEventListener("click", () => this._refreshCurrentWeek()));
    action("edit").forEach((button) => button.addEventListener("click", () => {
      const id = button.closest(".meal-item")?.dataset.planId;
      this._editingId = id || ""; this._confirmRemoveId = ""; this._render();
    }));
    action("cancel-edit").forEach((button) => button.addEventListener("click", () => { this._editingId = ""; this._render(); }));
    action("save").forEach((button) => button.addEventListener("click", () => {
      const article = button.closest(".meal-item");
      const item = items.find((candidate) => String(candidate.id || "") === article?.dataset.planId);
      if (item) this._savePlannedItem(item, article.querySelector(".edit-form"));
    }));
    action("remove").forEach((button) => button.addEventListener("click", () => {
      const id = button.closest(".meal-item")?.dataset.planId;
      this._confirmRemoveId = id || ""; this._editingId = ""; this._render();
    }));
    action("cancel-remove").forEach((button) => button.addEventListener("click", () => { this._confirmRemoveId = ""; this._render(); }));
    action("confirm-remove").forEach((button) => button.addEventListener("click", () => {
      const article = button.closest(".meal-item");
      const item = items.find((candidate) => String(candidate.id || "") === article?.dataset.planId);
      if (item) this._removePlannedItem(item);
    }));
  }

  static getConfigElement() { return document.createElement("deglaze-weekly-meal-planner-card-editor"); }
  static getStubConfig() { return { title: "Weekly meal planner", domain: "deglaze_poc", grid_columns: 12, refresh_interval: 120, display_days: 7 }; }
  getGridOptions() {
    const columns = [6, 9, 12].includes(Number(this._config.grid_columns)) ? Number(this._config.grid_columns) : 12;
    return { columns, rows: 8, min_columns: 6, max_columns: 12, min_rows: 4 };
  }
  getCardSize() { return 9; }
}


const deglazeContentLines = (value) => {
  const lines = [];
  const childKeys = ["sections", "items", "ingredients", "instructions", "steps", "directions", "parts"];
  const visit = (node) => {
    if (node === null || node === undefined) return;
    if (typeof node === "string" || typeof node === "number") {
      const text = String(node).trim();
      if (text) lines.push({ text, heading: false });
      return;
    }
    if (Array.isArray(node)) { node.forEach(visit); return; }
    if (typeof node !== "object") return;
    const nested = childKeys.filter((key) => Array.isArray(node[key]) || (node[key] && typeof node[key] === "object"));
    const labelValue = node.label && typeof node.label === "object" ? node.label.label : node.label;
    const heading = node.title || (nested.length ? node.name : null) || (nested.length ? labelValue : null);
    if (heading && nested.length) lines.push({ text: String(heading), heading: true });
    const textValue = node.text ?? node.ingredient ?? node.instruction ?? node.value;
    if (typeof textValue === "string" || typeof textValue === "number") {
      if (String(textValue).trim()) lines.push({ text: String(textValue).trim(), heading: false });
    } else if (!nested.length && (node.name || node.title || labelValue)) {
      lines.push({ text: String(node.name || node.title || labelValue), heading: false });
    }
    nested.forEach((key) => visit(node[key]));
  };
  visit(value);
  return lines;
};

const deglazeStructuredHtml = (value, emptyMessage) => {
  const lines = deglazeContentLines(value);
  if (!lines.length) return `<p class="muted">${deglazeEscape(emptyMessage)}</p>`;
  return lines.map((line) => line.heading
    ? `<h4>${deglazeEscape(line.text)}</h4>`
    : `<p class="content-line">${deglazeEscape(line.text)}</p>`).join("");
};

const deglazeIngredientDuplicateKey = (value) => {
  if (typeof value !== "string") return "";
  let text = value.normalize("NFKC").toLocaleLowerCase();
  text = text.replace(/\([^)]*\)/g, " ");
  text = text.replace(/^\s*(?:(?:\d+\s+)?\d+\s*[\/⁄]\s*\d+|\d+(?:[.,]\d+)?|[¼½¾⅓⅔⅛⅜⅝⅞])\s*/, " ");
  text = text.replace(/\b(?:a|an|of|for|to|the)\b/g, " ");
  const units = new Set([
    "g", "gram", "grams", "kg", "kilogram", "kilograms", "mg", "milligram", "milligrams",
    "ml", "milliliter", "milliliters", "millilitre", "millilitres", "l", "liter", "liters", "litre", "litres",
    "oz", "ounce", "ounces", "lb", "lbs", "pound", "pounds", "tsp", "teaspoon", "teaspoons",
    "tbsp", "tablespoon", "tablespoons", "cup", "cups", "pint", "pints", "quart", "quarts", "gallon", "gallons",
    "clove", "cloves", "bunch", "bunches", "can", "cans", "tin", "tins", "packet", "packets", "package", "packages",
    "slice", "slices", "sprig", "sprigs", "piece", "pieces", "serving", "servings", "handful", "handfuls",
    "pinch", "pinches", "dash", "dashes", "head", "heads", "stalk", "stalks",
  ]);
  const preparation = new Set([
    "finely", "roughly", "chopped", "diced", "minced", "grated", "crushed", "sliced", "ground",
    "drained", "reserved", "topping", "garnish", "garnishing", "optional",
  ]);
  const tokens = text.match(/[\p{L}\p{N}]+/gu) || [];
  const normalized = tokens.filter((token) => !units.has(token) && !preparation.has(token)).map((token) => {
    if (token.length > 4 && token.endsWith("ies")) return `${token.slice(0, -3)}y`;
    if (token.length > 4 && token.endsWith("oes")) return token.slice(0, -2);
    if (token.length > 3 && token.endsWith("s") && !/(ss|us|is)$/.test(token)) return token.slice(0, -1);
    return token;
  });
  return normalized.join(" ").trim();
};

class DeglazeRecipeLibraryCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = undefined;
    this._config = { title: "Recipe library", domain: "deglaze_poc", grid_columns: 12 };
    this._connection = undefined;
    this._recipes = [];
    this._collections = [];
    this._selectedCollectionId = "";
    this._selectedId = undefined;
    this._detail = undefined;
    this._query = "";
    this._loadingList = false;
    this._loadingDetail = false;
    this._loadingRecipeId = undefined;
    this._refreshing = false;
    this._error = "";
    this._message = "";
    this._addingMeal = false;
    this._collectionDraftIds = null;
    this._savingCollections = false;
    this._collectionMessage = "";
    this._collectionMessageType = "info";
    this._ingredientSelectionIds = null;
    this._ingredientReview = null;
    this._ingredientReviewLoading = false;
    this._addingIngredients = false;
    this._ingredientStoreIds = [];
    this._ingredientIncludeDuplicates = false;
    this._ingredientWorkflowMessage = "";
    this._ingredientWorkflowMessageType = "info";
  }

  setConfig(config) {
    this._config = { title: "Recipe library", domain: "deglaze_poc", grid_columns: 12, ...config };
    this._render();
  }

  set hass(hass) {
    const connectionChanged = Boolean(hass?.connection && this._connection !== hass.connection);
    const firstHass = !this._hass;
    this._hass = hass;
    if (firstHass || connectionChanged) this._render();
    if (this.isConnected && connectionChanged) {
      this._connection = hass.connection;
      this._loadRecipes();
    }
  }
  get hass() { return this._hass; }

  connectedCallback() {
    this._render();
    if (this._hass?.connection && this._connection !== this._hass.connection) {
      this._connection = this._hass.connection;
      this._loadRecipes();
    }
  }

  async _refreshLibrary() {
    if (!this._hass || this._refreshing || this._loadingList) return;
    this._refreshing = true;
    this._error = "";
    this._collectionDraftIds = null;
    this._collectionMessage = "";
    this._collectionMessageType = "info";
    this._render();
    try {
      await this._hass.callService(this._config.domain, "refresh", {});
      this._detail = undefined;
      await this._loadRecipes();
    } catch (error) {
      this._error = error?.message || "Could not refresh the Deglaze integration.";
    } finally {
      this._refreshing = false;
      this._render();
    }
  }

  async _loadRecipes() {
    if (!this._hass || this._loadingList) return;
    this._loadingList = true;
    this._error = "";
    this._render();
    try {
      const response = await this._hass.callWS({ type: `${this._config.domain}/recipes/list` });
      this._recipes = Array.isArray(response?.recipes) ? response.recipes : [];
      this._collections = Array.isArray(response?.collections) ? response.collections : [];
      if (this._selectedCollectionId && !this._collections.some((collection) => collection.id === this._selectedCollectionId)) {
        this._selectedCollectionId = "";
      }
      if (response?.sync_error) this._error = response.sync_error;
      const previousSelectedId = this._selectedId;
      const matchingRecipes = this._getFilteredRecipes();
      if (!matchingRecipes.some((recipe) => recipe.recipe_id === this._selectedId)) {
        this._selectedId = matchingRecipes[0]?.recipe_id;
        this._detail = undefined;
      }
      if (previousSelectedId !== this._selectedId) {
        this._collectionDraftIds = null;
        this._collectionMessage = "";
        this._collectionMessageType = "info";
      }
    } catch (error) {
      this._error = error?.message || "Could not load the recipe library.";
      this._recipes = [];
    } finally {
      this._loadingList = false;
      this._render();
    }
    if (this._selectedId && !this._detail && this._loadingRecipeId !== this._selectedId) {
      await this._loadRecipe(this._selectedId);
    }
  }

  async _loadRecipe(recipeId) {
    if (!this._hass || !recipeId) return;
    if (this._loadingRecipeId === recipeId) return;
    if (this._selectedId !== recipeId) {
      this._collectionDraftIds = null;
      this._collectionMessage = "";
      this._collectionMessageType = "info";
    }
    this._ingredientSelectionIds = null;
    this._ingredientReview = null;
    this._ingredientReviewLoading = false;
    this._addingIngredients = false;
    this._ingredientStoreIds = [];
    this._ingredientIncludeDuplicates = false;
    this._ingredientWorkflowMessage = "";
    this._ingredientWorkflowMessageType = "info";
    this._selectedId = recipeId;
    this._detail = undefined;
    this._loadingDetail = true;
    this._loadingRecipeId = recipeId;
    this._error = "";
    this._message = "";
    this._render();
    try {
      const response = await this._hass.callWS({ type: `${this._config.domain}/recipe`, recipe_id: recipeId });
      if (this._selectedId === recipeId) this._detail = response?.recipe;
    } catch (error) {
      if (this._selectedId === recipeId) this._error = error?.message || "Could not load recipe details.";
    } finally {
      if (this._loadingRecipeId === recipeId) {
        this._loadingDetail = false;
        this._loadingRecipeId = undefined;
        this._render();
      }
    }
  }

  _getFilteredRecipes() {
    const query = this._query.trim().toLocaleLowerCase();
    return this._recipes.filter((recipe) => {
      const titleMatches = String(recipe.title || "").toLocaleLowerCase().includes(query);
      const collectionMatches = !this._selectedCollectionId
        || (Array.isArray(recipe.collection_ids) && recipe.collection_ids.includes(this._selectedCollectionId));
      return titleMatches && collectionMatches;
    });
  }

  _getCollectionCounts() {
    const counts = new Map(this._collections.map((collection) => [collection.id, 0]));
    for (const recipe of this._recipes) {
      for (const collectionId of (Array.isArray(recipe.collection_ids) ? recipe.collection_ids : [])) {
        if (counts.has(collectionId)) counts.set(collectionId, counts.get(collectionId) + 1);
      }
    }
    return counts;
  }

  _getIngredientChoices() {
    const choices = this._detail?.ingredients_for_grocery;
    return Array.isArray(choices) ? choices.filter((choice) => choice && typeof choice.id === "string" && typeof choice.text === "string" && choice.text.trim()) : [];
  }

  _getSelectedIngredientChoices() {
    const choices = this._getIngredientChoices();
    if (!Array.isArray(this._ingredientSelectionIds)) return choices;
    const selected = new Set(this._ingredientSelectionIds);
    return choices.filter((choice) => selected.has(choice.id));
  }

  _renderIngredientChoices(choices) {
    if (!choices.length) return `<p class="blank">No individually selectable ingredients were found in this recipe.</p>`;
    const selectedIds = Array.isArray(this._ingredientSelectionIds) ? new Set(this._ingredientSelectionIds) : new Set(choices.map((choice) => choice.id));
    const groups = new Map();
    for (const choice of choices) {
      const section = typeof choice.section === "string" && choice.section.trim() ? choice.section.trim() : "Ingredients";
      if (!groups.has(section)) groups.set(section, []);
      groups.get(section).push(choice);
    }
    return [...groups.entries()].map(([section, items]) => `
      <div class="ingredient-choice-group">
        ${groups.size > 1 || section !== "Ingredients" ? `<div class="ingredient-section-title">${deglazeEscape(section)}</div>` : ""}
        ${items.map((choice) => `<label class="ingredient-option"><input class="ingredient-choice" type="checkbox" data-ingredient-id="${deglazeEscape(choice.id)}" ${selectedIds.has(choice.id) ? "checked" : ""} ${this._ingredientReviewLoading || this._ingredientReview || this._addingIngredients ? "disabled" : ""} /><span>${deglazeEscape(choice.text)}</span></label>`).join("")}
      </div>`).join("");
  }

  _renderIngredientReview() {
    const review = this._ingredientReview;
    if (!review || review.recipeId !== this._selectedId) return "";
    const duplicateById = review.duplicateById || {};
    const duplicateCount = review.choices.filter((choice) => (duplicateById[choice.id] || []).length).length;
    const plannedAddCount = this._ingredientIncludeDuplicates ? review.choices.length : review.choices.length - duplicateCount;
    const storeOptions = (review.stores || []).map((store) => `<label class="ingredient-store-option"><input class="ingredient-store-choice" type="checkbox" value="${deglazeEscape(store.id)}" ${this._ingredientStoreIds.includes(store.id) ? "checked" : ""} ${this._addingIngredients ? "disabled" : ""} /><span>${deglazeEscape(store.name)}</span></label>`).join("");
    const items = review.choices.map((choice) => {
      const duplicates = duplicateById[choice.id] || [];
      return `<div class="ingredient-review-item"><div>${deglazeEscape(choice.text)}</div>${duplicates.length ? `<div class="ingredient-warning">Possible duplicate of ${duplicates.map((item) => `“${deglazeEscape(item.text)}”${item.status === "completed" ? " (completed)" : ""}`).join(", ")}. ${this._ingredientIncludeDuplicates ? "Will be added anyway." : "Will be skipped by default."}</div>` : ""}</div>`;
    }).join("");
    return `<section class="ingredient-review" aria-label="Review grocery additions">
      <h5>Review before adding</h5>
      <p class="muted">${review.choices.length} selected · ${plannedAddCount} will be added${duplicateCount && !this._ingredientIncludeDuplicates ? ` · ${duplicateCount} possible duplicate(s) will be skipped` : ""}.</p>
      <div class="ingredient-review-list">${items}</div>
      ${review.stores?.length ? `<div class="ingredient-store-section"><div class="ingredient-section-title">Assign to store(s) (optional)</div><div class="ingredient-store-options">${storeOptions}</div></div>` : `<p class="muted">No stores are configured. Ingredients will be added without a store assignment.</p>`}
      ${duplicateCount ? `<label class="ingredient-duplicate-toggle"><input id="include-ingredient-duplicates" type="checkbox" ${this._ingredientIncludeDuplicates ? "checked" : ""} ${this._addingIngredients ? "disabled" : ""} /><span>Add ingredients flagged as possible duplicates anyway</span></label>` : ""}
      <div class="ingredient-review-actions"><button class="secondary" id="cancel-ingredient-review" ${this._addingIngredients ? "disabled" : ""}>Back to recipe</button><button class="primary" id="confirm-add-ingredients" ${this._addingIngredients || plannedAddCount < 1 ? "disabled" : ""}>${this._addingIngredients ? "Adding ingredients…" : `Confirm and add ${plannedAddCount} ingredient(s)`}</button></div>
    </section>`;
  }

  async _reviewSelectedIngredients() {
    const selectedChoices = this._getSelectedIngredientChoices();
    if (!selectedChoices.length || this._ingredientReviewLoading || this._addingIngredients || !this._hass) return;
    this._ingredientReviewLoading = true;
    this._ingredientWorkflowMessage = "Checking the current grocery list for possible duplicates…";
    this._ingredientWorkflowMessageType = "info";
    this._render();
    const recipeId = this._selectedId;
    try {
      const response = await this._hass.callWS({ type: `${this._config.domain}/grocery/list` });
      if (!Array.isArray(response?.items)) throw new Error("The current grocery list could not be read.");
      if (this._selectedId !== recipeId) return;
      const existing = response.items.map((item) => ({
        text: String(item.text || item.ingredient || "").trim(),
        status: String(item.status_text || (typeof item.status === "string" ? item.status : item.status?.status) || "pending").toLocaleLowerCase(),
      })).filter((item) => item.text);
      const duplicateById = {};
      for (const choice of selectedChoices) {
        const key = deglazeIngredientDuplicateKey(choice.text);
        duplicateById[choice.id] = key ? existing.filter((item) => deglazeIngredientDuplicateKey(item.text) === key).slice(0, 5) : [];
      }
      this._ingredientReview = {
        recipeId,
        choices: selectedChoices,
        duplicateById,
        stores: Array.isArray(response.stores) ? response.stores : [],
      };
      this._ingredientStoreIds = [];
      this._ingredientIncludeDuplicates = false;
      this._ingredientWorkflowMessage = "Review the selected ingredients and confirm the grocery additions.";
      this._ingredientWorkflowMessageType = "info";
    } catch (error) {
      this._ingredientWorkflowMessage = error?.message || "Could not check the grocery list. No ingredients were added.";
      this._ingredientWorkflowMessageType = "error";
    } finally {
      this._ingredientReviewLoading = false;
      this._render();
    }
  }

  async _confirmAddIngredients() {
    const review = this._ingredientReview;
    if (!this._hass || !review || review.recipeId !== this._selectedId || this._addingIngredients) return;
    const duplicateById = review.duplicateById || {};
    const duplicateCount = review.choices.filter((choice) => (duplicateById[choice.id] || []).length).length;
    const expectedCount = this._ingredientIncludeDuplicates ? review.choices.length : review.choices.length - duplicateCount;
    if (expectedCount < 1) return;
    this._addingIngredients = true;
    this._ingredientWorkflowMessage = "Adding selected ingredients to Deglaze…";
    this._ingredientWorkflowMessageType = "info";
    this._render();
    try {
      const response = await this._hass.callWS({
        type: `${this._config.domain}/recipe/add-ingredients`,
        recipe_id: review.recipeId,
        ingredient_ids: review.choices.map((choice) => choice.id),
        store_ids: this._ingredientStoreIds,
        include_duplicates: this._ingredientIncludeDuplicates,
      });
      // The backend refreshes and verifies the list after any write. Tell another
      // grocery card on this dashboard to reload immediately instead of waiting
      // for its 60-second polling interval. Partial results may include real adds.
      if (["passed", "partial"].includes(response?.status)
          && typeof window !== "undefined"
          && typeof window.dispatchEvent === "function"
          && typeof CustomEvent === "function") {
        window.dispatchEvent(new CustomEvent("deglaze-grocery-list-updated"));
      }
      this._ingredientWorkflowMessage = response?.message || "The ingredient-add request completed. Check the result against Deglaze.";
      this._ingredientWorkflowMessageType = response?.status === "passed" || response?.status === "skipped" ? "success" : "error";
      this._ingredientSelectionIds = [];
      this._ingredientReview = null;
      this._ingredientStoreIds = [];
      this._ingredientIncludeDuplicates = false;
    } catch (error) {
      this._ingredientWorkflowMessage = error?.message || "Could not add recipe ingredients. Refresh the grocery list before retrying.";
      this._ingredientWorkflowMessageType = "error";
      this._ingredientReview = null;
    } finally {
      this._addingIngredients = false;
      this._render();
    }
  }

  _chooseCollection(collectionId) {
    const previousSelectedId = this._selectedId;
    this._selectedCollectionId = collectionId || "";
    const filtered = this._getFilteredRecipes();
    if (!filtered.some((recipe) => recipe.recipe_id === this._selectedId)) {
      this._selectedId = filtered[0]?.recipe_id;
      this._detail = undefined;
    }
    if (previousSelectedId !== this._selectedId) {
      this._collectionDraftIds = null;
      this._collectionMessage = "";
      this._collectionMessageType = "info";
    }
    this._render();
    if (this._selectedId && !this._detail && this._loadingRecipeId !== this._selectedId) {
      this._loadRecipe(this._selectedId);
    }
  }

  _changeSearch(query) {
    const previousSelectedId = this._selectedId;
    this._query = query;
    const filtered = this._getFilteredRecipes();
    if (!filtered.some((recipe) => recipe.recipe_id === this._selectedId)) {
      this._selectedId = filtered[0]?.recipe_id;
      this._detail = undefined;
    }
    if (previousSelectedId !== this._selectedId) {
      this._collectionDraftIds = null;
      this._collectionMessage = "";
      this._collectionMessageType = "info";
    }
    this._render();
    if (this._selectedId && !this._detail && this._loadingRecipeId !== this._selectedId) {
      this._loadRecipe(this._selectedId);
    }
  }

  _isCollectionDraftDirty(currentIds) {
    if (!Array.isArray(this._collectionDraftIds)) return false;
    const normalized = (ids) => [...new Set((ids || []).filter((id) => typeof id === "string"))].sort();
    return JSON.stringify(normalized(this._collectionDraftIds)) !== JSON.stringify(normalized(currentIds));
  }

  _render() {
    if (!this.shadowRoot || !this._config) return;
    const filtered = this._getFilteredRecipes();
    const selected = filtered.find((recipe) => recipe.recipe_id === this._selectedId);
    const detail = this._detail;
    const date = deglazeToday();
    const collectionCounts = this._getCollectionCounts();
    const userCollections = this._collections
      .filter((collection) => collection.tag_type === "user")
      .sort((a, b) => String(a.name).localeCompare(String(b.name)));
    const systemCollections = this._collections
      .filter((collection) => collection.tag_type === "system")
      .sort((a, b) => String(a.name).localeCompare(String(b.name)));
    const collectionOption = (collection) => `<option value="${deglazeEscape(collection.id)}" ${this._selectedCollectionId === collection.id ? "selected" : ""}>${deglazeEscape(collection.name)} (${collectionCounts.get(collection.id) || 0})</option>`;
    const collectionNames = Array.isArray(selected?.collection_names) ? selected.collection_names : [];
    const selectedCollection = this._collections.find((collection) => collection.id === this._selectedCollectionId);
    const scopeLabel = selectedCollection ? `Collection: ${selectedCollection.name}` : "All recipes";
    const selectedCollectionIds = Array.isArray(selected?.collection_ids) ? selected.collection_ids : [];
    const draftCollectionIds = Array.isArray(this._collectionDraftIds) ? this._collectionDraftIds : selectedCollectionIds;
    const draftCollectionSet = new Set(draftCollectionIds);
    const collectionMembershipDirty = this._isCollectionDraftDirty(selectedCollectionIds);
    const ingredientChoices = Array.isArray(detail?.ingredients_for_grocery) ? detail.ingredients_for_grocery : [];
    const selectedIngredientCount = this._getSelectedIngredientChoices().length;
    const membershipOptions = (collections) => collections.map((collection) => `<label class="membership-option"><input class="membership-checkbox" type="checkbox" data-collection-id="${deglazeEscape(collection.id)}" ${draftCollectionSet.has(collection.id) ? "checked" : ""} ${this._savingCollections ? "disabled" : ""} /><span>${deglazeEscape(collection.name)}</span></label>`).join("");
    this.shadowRoot.innerHTML = `<style>${deglazeBaseStyles}
      .recipe-card { container-type:inline-size; }
      .header { display:flex; justify-content:space-between; align-items:center; gap:10px; margin-bottom:12px; }
      .layout { display:grid; grid-template-columns:minmax(180px, .72fr) minmax(0, 1.6fr); gap:16px; }
      .browser { min-width:0; }
      .list { max-height:440px; overflow:auto; margin-top:8px; border-top:1px solid var(--divider-color); }
      .recipe-option { display:block; width:100%; text-align:left; border:0; border-bottom:1px solid var(--divider-color); padding:10px 8px; background:transparent; color:var(--primary-text-color); overflow-wrap:anywhere; }
      .recipe-option[aria-current="true"] { background:var(--secondary-background-color); border-left:3px solid var(--primary-color); font-weight:600; }
      .recipe-option small { display:block; color:var(--secondary-text-color); margin-top:3px; font-weight:400; }
      .collection-chips { display:flex; flex-wrap:wrap; gap:4px; margin-top:5px; }
      .collection-chip { display:inline-block; border-radius:999px; border:1px solid var(--divider-color); padding:2px 6px; font-size:.72rem; color:var(--secondary-text-color); font-weight:400; }
      .collection-select { box-sizing:border-box; width:100%; margin:5px 0 10px; border:1px solid var(--divider-color); background:var(--card-background-color); color:var(--primary-text-color); border-radius:6px; padding:9px; font:inherit; }
      .details { border-left:1px solid var(--divider-color); padding-left:16px; min-width:0; }
      .details h3 { margin:0 0 8px; font-size:1.12rem; overflow-wrap:anywhere; }
      .description { color:var(--secondary-text-color); white-space:pre-wrap; margin:0 0 12px; line-height:1.45; }
      .detail-grid { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
      .detail-grid h4 { margin:12px 0 6px; font-size:.96rem; }
      .content-line { margin:0 0 6px; line-height:1.45; white-space:pre-wrap; overflow-wrap:anywhere; }
      .controls { border-top:1px solid var(--divider-color); padding-top:12px; margin-top:14px; }
      .controls-row { display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-top:8px; }
      .checkrow { display:flex; align-items:center; gap:8px; margin:10px 0; font-size:.9rem; }
      .membership-list { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:4px 12px; max-height:220px; overflow:auto; padding:4px 0 8px; }
      .membership-group-title { grid-column:1 / -1; color:var(--secondary-text-color); font-size:.82rem; font-weight:600; margin-top:6px; }
      .membership-option { display:flex; align-items:flex-start; gap:8px; min-width:0; padding:5px 0; overflow-wrap:anywhere; }
      .membership-option input { width:auto; margin-top:3px; flex:0 0 auto; }
      .membership-option span { min-width:0; }
      .checkrow input { width:auto; }
      .ingredient-picker { margin-top:8px; }
      .ingredient-choice-group { margin:8px 0 10px; }
      .ingredient-section-title { font-size:.82rem; font-weight:600; color:var(--secondary-text-color); margin:6px 0; }
      .ingredient-option { display:flex; align-items:flex-start; gap:8px; margin:7px 0; line-height:1.4; overflow-wrap:anywhere; }
      .ingredient-option input, .ingredient-store-option input, .ingredient-duplicate-toggle input { width:auto; flex:0 0 auto; margin-top:3px; }
      .ingredient-option span, .ingredient-store-option span { min-width:0; }
      .ingredient-selection-actions { display:flex; gap:8px; flex-wrap:wrap; margin:8px 0; }
      .ingredient-review { border:1px solid var(--divider-color); border-radius:9px; padding:10px; margin-top:10px; }
      .ingredient-review h5 { margin:0 0 5px; font-size:.94rem; }
      .ingredient-review-list { max-height:220px; overflow:auto; margin:8px 0; }
      .ingredient-review-item { padding:7px 0; border-bottom:1px solid var(--divider-color); overflow-wrap:anywhere; }
      .ingredient-warning { margin-top:4px; font-size:.8rem; color:var(--warning-color,var(--secondary-text-color)); }
      .ingredient-store-section { margin-top:10px; }
      .ingredient-store-options { display:flex; flex-wrap:wrap; gap:7px 14px; margin:7px 0; }
      .ingredient-store-option { display:flex; align-items:flex-start; gap:6px; font-size:.88rem; }
      .ingredient-duplicate-toggle { display:flex; gap:8px; align-items:flex-start; margin:10px 0; font-size:.87rem; }
      .ingredient-review-actions { display:flex; flex-wrap:wrap; gap:8px; justify-content:flex-end; margin-top:10px; }
      .source { font-size:.82rem; color:var(--secondary-text-color); margin:4px 0 12px; }
      .blank { color:var(--secondary-text-color); padding:12px 0; }
      @container (max-width:650px) { .layout { grid-template-columns:1fr; } .list { max-height:220px; } .details { border-left:0; border-top:1px solid var(--divider-color); padding:14px 0 0; } .detail-grid { grid-template-columns:1fr; gap:8px; } .membership-list { grid-template-columns:1fr; } }
      @media(max-width:650px) { .layout { grid-template-columns:1fr; } .list { max-height:220px; } .details { border-left:0; border-top:1px solid var(--divider-color); padding:14px 0 0; } .detail-grid { grid-template-columns:1fr; gap:8px; } .membership-list { grid-template-columns:1fr; } }
    </style>
    <section class="card recipe-card">
      <div class="header"><h2>${deglazeEscape(this._config.title)}</h2><div><button class="secondary" id="refresh" ${this._loadingList || this._refreshing ? "disabled" : ""}>${this._refreshing ? "Refreshing…" : this._loadingList ? "Loading…" : "Refresh"}</button></div></div>
      <div class="muted">${filtered.length} shown · ${this._recipes.length} total · ${deglazeEscape(scopeLabel)}</div>
      ${!this._collections.length && this._recipes.length ? `<p class="blank">No visible tag collections were returned; all recipes remain available.</p>` : ""}
      ${this._error ? `<div class="message error" role="status">${deglazeEscape(this._error)}</div>` : ""}
      <div class="layout">
        <div class="browser">
          <label class="muted" for="collection-filter">Browse collections</label>
          <select class="collection-select" id="collection-filter" aria-label="Filter recipes by collection">
            <option value="" ${!this._selectedCollectionId ? "selected" : ""}>All recipes (${this._recipes.length})</option>
            ${userCollections.length ? `<optgroup label="Your collections">${userCollections.map(collectionOption).join("")}</optgroup>` : ""}
            ${systemCollections.length ? `<optgroup label="Built-in categories">${systemCollections.map(collectionOption).join("")}</optgroup>` : ""}
          </select>
          <label class="muted" for="search">Search recipes</label>
          <input id="search" type="search" placeholder="Search by title…" value="${deglazeEscape(this._query)}" />
          <div class="list" role="listbox" aria-label="Recipes">
            ${this._loadingList && !this._recipes.length ? `<p class="blank">Loading recipes…</p>` : ""}
            ${!this._loadingList && !filtered.length ? `<p class="blank">No matching recipes.</p>` : ""}
            ${filtered.map((recipe) => `<button class="recipe-option" data-id="${deglazeEscape(recipe.recipe_id)}" aria-current="${recipe.recipe_id === this._selectedId ? "true" : "false"}" role="option">${deglazeEscape(recipe.title || "Untitled recipe")}${recipe.time ? `<small>${deglazeEscape(recipe.time)}</small>` : ""}${Array.isArray(recipe.collection_names) && recipe.collection_names.length ? `<span class="collection-chips">${recipe.collection_names.slice(0, 4).map((name) => `<span class="collection-chip">${deglazeEscape(name)}</span>`).join("")}${recipe.collection_names.length > 4 ? `<span class="collection-chip">+${recipe.collection_names.length - 4}</span>` : ""}</span>` : ""}</button>`).join("")}
          </div>
        </div>
        <article class="details">
          ${!selected ? `<p class="blank">Choose a recipe to view details.</p>` : this._loadingDetail ? `<p class="blank">Loading recipe details…</p>` : !detail ? `<p class="blank">Recipe details are not available yet.</p>` : `
            <h3>${deglazeEscape(detail.title || selected.title || "Recipe")}</h3>
            ${collectionNames.length ? `<div class="collection-chips" aria-label="Recipe collections">${collectionNames.map((name) => `<span class="collection-chip">${deglazeEscape(name)}</span>`).join("")}</div>` : ""}
            ${detail.source ? `<div class="source">Source: ${deglazeEscape(typeof detail.source === "string" ? detail.source : (detail.source.title || detail.source.name || "See source details"))}</div>` : ""}
            ${detail.description ? `<p class="description">${deglazeEscape(detail.description)}</p>` : ""}
            <div class="detail-grid">
              <section><h4>Ingredients</h4>
                ${ingredientChoices.length ? `<p class="muted">Select ingredients to add to your grocery list. Original quantities and wording are preserved.</p>
                  <div class="ingredient-picker" aria-label="Select recipe ingredients">
                    ${this._renderIngredientChoices(ingredientChoices)}
                    <div class="ingredient-selection-actions"><button class="secondary" id="select-all-ingredients" ${this._ingredientReviewLoading || this._ingredientReview || this._addingIngredients ? "disabled" : ""}>Select all</button><button class="secondary" id="clear-ingredients" ${this._ingredientReviewLoading || this._ingredientReview || this._addingIngredients ? "disabled" : ""}>Clear</button></div>
                    <button class="primary" id="review-ingredients" ${!selectedIngredientCount || this._ingredientReviewLoading || this._ingredientReview || this._addingIngredients ? "disabled" : ""}>${this._ingredientReviewLoading ? "Checking grocery list…" : `Review selected ingredients (${selectedIngredientCount})`}</button>
                    <div class="message ${deglazeEscape(this._ingredientWorkflowMessageType)}" role="status" aria-live="polite">${deglazeEscape(this._ingredientWorkflowMessage)}</div>
                    ${this._ingredientReviewLoading && !this._ingredientReview ? `<p class="muted">Checking existing grocery items…</p>` : this._renderIngredientReview()}
                  </div>` : deglazeStructuredHtml(detail.ingredients, "No ingredient details in the synchronized record.")}
              </section>
              <section><h4>Instructions</h4>${deglazeStructuredHtml(detail.instructions, "No instructions in the synchronized record.")}</section>
            </div>
            <div class="controls collection-controls">
              <h4>Organize collections</h4>
              <p class="muted">Choose all collections this recipe should belong to. Changes are saved to Deglaze.</p>
              ${userCollections.length || systemCollections.length ? `<div class="membership-list" aria-label="Recipe collections">
                ${userCollections.length ? `<div class="membership-group-title">Your collections</div>${membershipOptions(userCollections)}` : ""}
                ${systemCollections.length ? `<div class="membership-group-title">Built-in categories</div>${membershipOptions(systemCollections)}` : ""}
              </div>` : `<p class="blank">No editable tag collections are available.</p>`}
              <button class="primary" id="save-collections" ${!collectionMembershipDirty || this._savingCollections ? "disabled" : ""}>${this._savingCollections ? "Saving…" : "Save memberships"}</button>
              <div class="message ${deglazeEscape(this._collectionMessageType)}" id="collection-message" role="status" aria-live="polite">${deglazeEscape(this._collectionMessage)}</div>
            </div>
            <div class="controls">
              <h4>Add to meal plan</h4>
              <div class="controls-row"><label class="muted">Date<input id="meal-date" type="date" value="${date}" /></label><label class="muted">Meal type<select id="meal-label"><option>Breakfast</option><option>Lunch</option><option>Dinner</option><option>Snack</option></select></label></div>
              <label class="checkrow"><input id="leftovers" type="checkbox" /> Add as leftovers</label>
              <button class="primary" id="add-meal" ${this._addingMeal ? "disabled" : ""}>${this._addingMeal ? "Adding…" : "Add to plan"}</button>
              <div class="message" id="add-message" role="status" aria-live="polite">${deglazeEscape(this._message)}</div>
            </div>`}
        </article>
      </div>
    </section>`;

    this.shadowRoot.querySelector("#refresh")?.addEventListener("click", () => this._refreshLibrary());
    this.shadowRoot.querySelector("#collection-filter")?.addEventListener("change", (event) => {
      this._chooseCollection(event.target.value);
    });
    this.shadowRoot.querySelector("#search")?.addEventListener("input", (event) => {
      const target = event.target;
      const caret = target.selectionStart;
      this._changeSearch(target.value);
      const next = this.shadowRoot.querySelector("#search");
      next?.focus();
      try { next?.setSelectionRange(caret, caret); } catch (_) { /* search input implementation varies */ }
    });
    this.shadowRoot.querySelectorAll(".recipe-option").forEach((button) => {
      button.addEventListener("click", () => this._loadRecipe(button.dataset.id));
    });
    this.shadowRoot.querySelectorAll(".ingredient-choice").forEach((checkbox) => {
      checkbox.addEventListener("change", () => {
        this._ingredientSelectionIds = [...this.shadowRoot.querySelectorAll(".ingredient-choice")]
          .filter((candidate) => candidate.checked)
          .map((candidate) => candidate.dataset.ingredientId);
        this._ingredientWorkflowMessage = "";
        this._render();
      });
    });
    this.shadowRoot.querySelector("#select-all-ingredients")?.addEventListener("click", () => {
      this._ingredientSelectionIds = null;
      this._ingredientWorkflowMessage = "";
      this._render();
    });
    this.shadowRoot.querySelector("#clear-ingredients")?.addEventListener("click", () => {
      this._ingredientSelectionIds = [];
      this._ingredientWorkflowMessage = "";
      this._render();
    });
    this.shadowRoot.querySelector("#review-ingredients")?.addEventListener("click", () => this._reviewSelectedIngredients());
    this.shadowRoot.querySelectorAll(".ingredient-store-choice").forEach((checkbox) => {
      checkbox.addEventListener("change", () => {
        this._ingredientStoreIds = [...this.shadowRoot.querySelectorAll(".ingredient-store-choice")]
          .filter((candidate) => candidate.checked)
          .map((candidate) => candidate.value);
        this._render();
      });
    });
    this.shadowRoot.querySelector("#include-ingredient-duplicates")?.addEventListener("change", (event) => {
      this._ingredientIncludeDuplicates = Boolean(event.target.checked);
      this._render();
    });
    this.shadowRoot.querySelector("#cancel-ingredient-review")?.addEventListener("click", () => {
      this._ingredientReview = null;
      this._ingredientStoreIds = [];
      this._ingredientIncludeDuplicates = false;
      this._ingredientWorkflowMessage = "";
      this._ingredientWorkflowMessageType = "info";
      this._render();
    });
    this.shadowRoot.querySelector("#confirm-add-ingredients")?.addEventListener("click", () => this._confirmAddIngredients());
    this.shadowRoot.querySelectorAll(".membership-checkbox").forEach((checkbox) => {
      checkbox.addEventListener("change", (event) => {
        const collectionId = event.target.dataset.collectionId;
        const baseIds = Array.isArray(selected?.collection_ids) ? selected.collection_ids : [];
        const draft = new Set(Array.isArray(this._collectionDraftIds) ? this._collectionDraftIds : baseIds);
        if (event.target.checked) draft.add(collectionId);
        else draft.delete(collectionId);
        this._collectionDraftIds = [...draft];
        const dirty = this._isCollectionDraftDirty(baseIds);
        this._collectionMessage = dirty ? "Unsaved collection changes." : "";
        this._collectionMessageType = "info";
        const saveButton = this.shadowRoot.querySelector("#save-collections");
        if (saveButton) saveButton.disabled = !dirty || this._savingCollections;
        const message = this.shadowRoot.querySelector("#collection-message");
        if (message) {
          message.textContent = this._collectionMessage;
          message.className = `message ${this._collectionMessageType}`;
        }
      });
    });
    this.shadowRoot.querySelector("#save-collections")?.addEventListener("click", () => this._saveCollections());
    this.shadowRoot.querySelector("#add-meal")?.addEventListener("click", () => this._addMeal());
  }

  async _saveCollections() {
    const selected = this._getFilteredRecipes().find((recipe) => recipe.recipe_id === this._selectedId);
    const currentIds = Array.isArray(selected?.collection_ids) ? selected.collection_ids : [];
    const collectionIds = Array.isArray(this._collectionDraftIds) ? [...new Set(this._collectionDraftIds)] : currentIds;
    if (!this._hass || !selected?.recipe_id || !this._isCollectionDraftDirty(currentIds) || this._savingCollections) return;

    this._savingCollections = true;
    this._collectionMessage = "Saving collection memberships…";
    this._collectionMessageType = "info";
    this._render();
    let failed = false;
    try {
      await this._hass.callService(this._config.domain, "set_recipe_collections", {
        recipe_id: selected.recipe_id,
        collection_ids: collectionIds,
      });
      this._collectionDraftIds = null;
      this._detail = undefined;
      await this._loadRecipes();
      this._collectionMessage = "Collection memberships saved to Deglaze.";
      this._collectionMessageType = "success";
    } catch (error) {
      failed = true;
      const errorMessage = error?.message || "Could not save collection memberships.";
      this._collectionDraftIds = null;
      // A service error can mean a partial remote update, so force a read after it fails.
      try { await this._hass.callService(this._config.domain, "refresh", {}); } catch (_) { /* keep the original error */ }
      this._detail = undefined;
      try { await this._loadRecipes(); } catch (_) { /* _loadRecipes normally handles and displays its own errors */ }
      this._collectionMessage = errorMessage;
      this._collectionMessageType = "error";
    } finally {
      this._savingCollections = false;
      if (failed) this._collectionMessageType = "error";
      this._render();
    }
  }

  async _addMeal() {
    const detail = this._detail;
    const date = this.shadowRoot.querySelector("#meal-date")?.value;
    const label = this.shadowRoot.querySelector("#meal-label")?.value;
    const isLeftovers = Boolean(this.shadowRoot.querySelector("#leftovers")?.checked);
    if (!this._hass || !detail?.id || !date || !label) {
      this._message = "Select a recipe, date, and meal type first.";
      this._render();
      return;
    }
    this._addingMeal = true;
    const button = this.shadowRoot.querySelector("#add-meal");
    const message = this.shadowRoot.querySelector("#add-message");
    if (button) {
      button.disabled = true;
      button.textContent = "Adding…";
    }
    if (message) {
      message.textContent = "Adding to meal plan…";
      message.className = "message";
    }
    let failed = false;
    try {
      await this._hass.callService(this._config.domain, "add_meal_plan_item", {
        recipe_id: detail.id,
        date,
        label,
        is_leftovers: isLeftovers,
      });
      this._message = `Added to ${label} on ${date}.`;
    } catch (error) {
      failed = true;
      this._message = error?.message || "Could not add the recipe to the meal plan.";
    } finally {
      this._addingMeal = false;
      if (button) {
        button.disabled = false;
        button.textContent = "Add to plan";
      }
      if (message) {
        message.textContent = this._message;
        message.className = `message ${failed ? "error" : "success"}`;
      }
    }
  }

  static getConfigElement() { return document.createElement("deglaze-recipe-library-card-editor"); }
  static getStubConfig() { return { title: "Recipe library", grid_columns: 12 }; }
  getGridOptions() {
    const columns = [6, 9, 12].includes(Number(this._config.grid_columns)) ? Number(this._config.grid_columns) : 12;
    return { columns, rows: 8, min_columns: 6, max_columns: 12, min_rows: 4 };
  }
  getCardSize() { return 8; }
}


class DeglazeCardEditorBase extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
  }

  setConfig(config) {
    this._config = { ...this.constructor.defaults, ...(config || {}) };
    this._render();
  }

  get hass() { return this._hass; }
  set hass(value) { this._hass = value; }

  _fieldValue(field) {
    const value = this._config[field.key] ?? field.default ?? "";
    if (field.type === "multi_select") {
      const selected = Array.isArray(value) ? value : [];
      return `<div class="choices" data-group="${deglazeEscape(field.key)}">${field.options.map((option) => `
        <label class="choice"><input type="checkbox" data-group-key="${deglazeEscape(field.key)}" value="${deglazeEscape(option.value)}" ${selected.includes(option.value) ? "checked" : ""}> <span>${deglazeEscape(option.label)}</span></label>`).join("")}</div>`;
    }
    if (field.type === "select") {
      return `<select id="cfg-${deglazeEscape(field.key)}" data-key="${deglazeEscape(field.key)}">${field.options.map((option) => `
        <option value="${deglazeEscape(option.value)}" ${String(value) === String(option.value) ? "selected" : ""}>${deglazeEscape(option.label)}</option>`).join("")}</select>`;
    }
    if (field.type === "number") {
      return `<input id="cfg-${deglazeEscape(field.key)}" data-key="${deglazeEscape(field.key)}" type="number" value="${deglazeEscape(value)}" ${field.min !== undefined ? `min="${field.min}"` : ""} ${field.max !== undefined ? `max="${field.max}"` : ""} ${field.step ? `step="${field.step}"` : ""}>`;
    }
    return `<input id="cfg-${deglazeEscape(field.key)}" data-key="${deglazeEscape(field.key)}" type="text" value="${deglazeEscape(value)}" placeholder="${deglazeEscape(field.placeholder || "")}">`;
  }

  _render() {
    if (!this.shadowRoot) return;
    const fields = this.constructor.fields || [];
    this.shadowRoot.innerHTML = `<style>
      :host { display:block; color:var(--primary-text-color); }
      .editor { display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:12px; padding:8px 0; }
      .field { display:flex; flex-direction:column; gap:5px; min-width:0; }
      .field-label { font-weight:500; }
      .helper { color:var(--secondary-text-color); font-size:.82rem; line-height:1.4; }
      input, select { box-sizing:border-box; width:100%; min-width:0; border:1px solid var(--divider-color); background:var(--secondary-background-color); color:var(--primary-text-color); border-radius:6px; padding:9px 10px; font:inherit; }
      .choices { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; padding:4px 0; }
      .choice { display:flex; align-items:center; gap:7px; font-weight:400; }
      .choice input { width:auto; }
      .full { grid-column:1/-1; }
    </style><div class="editor">${fields.map((field) => `
      <div class="field ${field.full ? "full" : ""}">${field.type === "multi_select" ? `<div class="field-label">${deglazeEscape(field.label)}</div>${this._fieldValue(field)}` : `<label class="field-label" for="cfg-${deglazeEscape(field.key)}">${deglazeEscape(field.label)}</label>${this._fieldValue(field)}`}${field.helper ? `<small class="helper">${deglazeEscape(field.helper)}</small>` : ""}</div>`).join("")}</div>`;

    this.shadowRoot.querySelectorAll("[data-key]").forEach((control) => {
      const eventName = control.tagName === "SELECT" ? "change" : "change";
      control.addEventListener(eventName, () => {
        const field = fields.find((candidate) => candidate.key === control.dataset.key);
        if (!field) return;
        let value = control.value;
        if (field.type === "number" || field.valueType === "number") {
          value = Number.parseInt(value, 10);
          if (!Number.isFinite(value)) value = field.default;
          if (field.min !== undefined) value = Math.max(field.min, value);
          if (field.max !== undefined) value = Math.min(field.max, value);
        }
        this._publish({ [field.key]: value });
      });
    });
    this.shadowRoot.querySelectorAll("[data-group-key]").forEach((control) => {
      control.addEventListener("change", () => {
        const key = control.dataset.groupKey;
        const value = [...this.shadowRoot.querySelectorAll(`[data-group-key="${key}"]`)]
          .filter((checkbox) => checkbox.checked)
          .map((checkbox) => checkbox.value);
        this._publish({ [key]: value });
      });
    });
  }

  _publish(patch) {
    this._config = { ...this._config, ...patch };
    const event = new CustomEvent("config-changed", {
      bubbles: true,
      composed: true,
      detail: { config: { ...this._config } },
    });
    this.dispatchEvent(event);
  }
}

class DeglazeGroceryAddCardEditor extends DeglazeCardEditorBase {
  static defaults = { title: "Grocery list", placeholder: "Ingredient or item…", service: "deglaze_poc.add_grocery_item", domain: "deglaze_poc", default_filter: "pending", manual_category: "", grid_columns: 6, default_group_by: "none", default_sort_by: "alpha" };
  static fields = [
    { key: "title", label: "Card title", type: "text", default: "Grocery list" },
    { key: "placeholder", label: "Input placeholder", type: "text", default: "Ingredient or item…" },
    { key: "default_filter", label: "Initial list view", type: "select", default: "pending", options: [{ value: "pending", label: "To buy" }, { value: "all", label: "All items" }, { value: "completed", label: "Completed" }] },
    { key: "default_group_by", label: "Initial grouping", type: "select", default: "none", options: [{ value: "none", label: "No grouping" }, { value: "store", label: "By store" }, { value: "category", label: "By category" }] },
    { key: "default_sort_by", label: "Initial sorting", type: "select", default: "alpha", options: [{ value: "alpha", label: "Alphabetical" }, { value: "newest", label: "Newest first" }] },
    { key: "manual_category", label: "Optional grocery category", type: "text", default: "", placeholder: "Leave blank to use Deglaze defaults" },
    { key: "service", label: "Add-item service", type: "text", default: "deglaze_poc.add_grocery_item" },
    { key: "domain", label: "Integration domain", type: "text", default: "deglaze_poc" },
    { key: "grid_columns", label: "Preferred width in Sections dashboards", type: "select", valueType: "number", default: 6, options: [{ value: 3, label: "3 columns — compact" }, { value: 6, label: "6 columns — half width" }, { value: 9, label: "9 columns — wide" }, { value: 12, label: "12 columns — full width" }], helper: "Sets the preferred width. You can also resize the card in dashboard edit mode; masonry dashboards do not use grid columns." },
  ];
}

class DeglazeUpcomingMealsCardEditor extends DeglazeCardEditorBase {
  static defaults = { title: "Upcoming meals", domain: "deglaze_poc", count: 5, refresh_interval: 60, meal_types: ["Breakfast", "Lunch", "Dinner", "Snack"], grid_columns: 6 };
  static fields = [
    { key: "title", label: "Card title", type: "text", default: "Upcoming meals" },
    { key: "count", label: "Number of meals to show", type: "number", min: 1, max: 20, default: 5 },
    { key: "refresh_interval", label: "Refresh interval (seconds)", type: "number", min: 30, max: 300, default: 60 },
    { key: "meal_types", label: "Meal types to include", type: "multi_select", default: ["Breakfast", "Lunch", "Dinner", "Snack"], options: [{ value: "Breakfast", label: "Breakfast" }, { value: "Lunch", label: "Lunch" }, { value: "Dinner", label: "Dinner" }, { value: "Snack", label: "Snack" }], helper: "Select the meal types to show. Leaving all unchecked shows all types." , full: true },
    { key: "domain", label: "Integration domain", type: "text", default: "deglaze_poc" },
    { key: "grid_columns", label: "Preferred width in Sections dashboards", type: "select", valueType: "number", default: 6, options: [{ value: 3, label: "3 columns — compact" }, { value: 6, label: "6 columns — half width" }, { value: 9, label: "9 columns — wide" }, { value: 12, label: "12 columns — full width" }], helper: "Sets the preferred width. You can also resize the card in dashboard edit mode; masonry dashboards do not use grid columns." },
  ];
}

class DeglazeRecipeLibraryCardEditor extends DeglazeCardEditorBase {
  static defaults = { title: "Recipe library", domain: "deglaze_poc", grid_columns: 12 };
  static fields = [
    { key: "title", label: "Card title", type: "text", default: "Recipe library" },
    { key: "domain", label: "Integration domain", type: "text", default: "deglaze_poc" },
    { key: "grid_columns", label: "Preferred width in Sections dashboards", type: "select", valueType: "number", default: 12, options: [{ value: 6, label: "6 columns — half width" }, { value: 9, label: "9 columns — wide" }, { value: 12, label: "12 columns — full width" }], helper: "Defaults to full width because the browser and recipe details need room. You can also resize the card in dashboard edit mode; masonry dashboards do not use grid columns." },
  ];
}

class DeglazeWeeklyMealPlannerCardEditor extends DeglazeCardEditorBase {
  static defaults = { title: "Weekly meal planner", domain: "deglaze_poc", grid_columns: 12, refresh_interval: 120, display_days: 7 };
  static fields = [
    { key: "title", label: "Card title", type: "text", default: "Weekly meal planner" },
    { key: "display_days", label: "Number of days to display", type: "number", min: 1, max: 7, default: 7, helper: "Displays the first 1–7 days of the selected week. Deglaze is still queried for the full Monday–Sunday week; week navigation continues to move by seven days." },
    { key: "refresh_interval", label: "Refresh interval (seconds)", type: "number", min: 60, max: 600, default: 120 },
    { key: "domain", label: "Integration domain", type: "text", default: "deglaze_poc" },
    { key: "grid_columns", label: "Preferred width in Sections dashboards", type: "select", valueType: "number", default: 12, options: [{ value: 6, label: "6 columns — half width" }, { value: 9, label: "9 columns — wide" }, { value: 12, label: "12 columns — full width" }], helper: "A full-width layout is recommended for the seven-day grid." },
  ];
}

if (!customElements.get("deglaze-grocery-add-card-editor")) customElements.define("deglaze-grocery-add-card-editor", DeglazeGroceryAddCardEditor);
if (!customElements.get("deglaze-upcoming-meals-card-editor")) customElements.define("deglaze-upcoming-meals-card-editor", DeglazeUpcomingMealsCardEditor);
if (!customElements.get("deglaze-weekly-meal-planner-card-editor")) customElements.define("deglaze-weekly-meal-planner-card-editor", DeglazeWeeklyMealPlannerCardEditor);
if (!customElements.get("deglaze-recipe-library-card-editor")) customElements.define("deglaze-recipe-library-card-editor", DeglazeRecipeLibraryCardEditor);

if (!customElements.get("deglaze-grocery-add-card")) customElements.define("deglaze-grocery-add-card", DeglazeGroceryAddCard);
if (!customElements.get("deglaze-upcoming-meals-card")) customElements.define("deglaze-upcoming-meals-card", DeglazeUpcomingMealsCard);
if (!customElements.get("deglaze-weekly-meal-planner-card")) customElements.define("deglaze-weekly-meal-planner-card", DeglazeWeeklyMealPlannerCard);
if (!customElements.get("deglaze-recipe-library-card")) customElements.define("deglaze-recipe-library-card", DeglazeRecipeLibraryCard);

window.customCards = window.customCards || [];
for (const item of [
  { type: "deglaze-grocery-add-card", name: "Deglaze Grocery Quick Add", description: "Add ingredients, view grocery items, and mark them bought or pending.", documentationURL: "https://developers.home-assistant.io/docs/frontend/custom-ui/custom-card/" },
  { type: "deglaze-upcoming-meals-card", name: "Deglaze Upcoming Meals", description: "Show upcoming meals loaded directly from the Deglaze integration.", documentationURL: "https://developers.home-assistant.io/docs/frontend/custom-ui/custom-card/" },
  { type: "deglaze-weekly-meal-planner-card", name: "Deglaze Weekly Meal Planner", description: "Browse a week of planned meals and edit dates, meal slots, leftovers, or remove items.", documentationURL: "https://developers.home-assistant.io/docs/frontend/custom-ui/custom-card/" },
  { type: "deglaze-recipe-library-card", name: "Deglaze Recipe Library", description: "Search recipes, manage collections, add them to meal plans, and add selected ingredients to groceries.", documentationURL: "https://developers.home-assistant.io/docs/frontend/custom-ui/custom-card/" },
]) {
  if (!window.customCards.some((existing) => existing.type === item.type)) window.customCards.push(item);
}
