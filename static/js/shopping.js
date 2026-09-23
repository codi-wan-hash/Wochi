/* Einkaufsliste: abhaken, schnell hinzufügen, löschen mit Rückgängig.
 *
 * Alles wird sofort in der Seite umgesetzt und erst danach an den Server
 * geschickt; schlägt das fehl, wird die Änderung zurückgenommen. Die Zeilen
 * kommen immer als fertig escaptes HTML vom Server (_item_row.html).
 */
(function () {
  "use strict";

  const addForm = document.getElementById("quick-add");
  const nameInput = document.getElementById("id_name");
  const qtyInput = document.getElementById("id_quantity");
  let pending = 0;
  let lastInteraction = 0;

  function el(id) { return document.getElementById(id); }

  function touch() { lastInteraction = Date.now(); }

  function rowFromHtml(html) {
    const template = document.createElement("template");
    template.innerHTML = html.trim();
    return template.content.firstElementChild;
  }

  function updateCounts() {
    const openList = el("open-items");
    const boughtList = el("bought-items");
    const openCount = openList ? openList.children.length : 0;
    const boughtCount = boughtList ? boughtList.children.length : 0;
    const empty = el("open-empty");
    if (empty) {
      empty.hidden = openCount > 0;
      empty.textContent = boughtCount > 0
        ? "Alles erledigt."
        : "Die Einkaufsliste ist leer – oben einfach lostippen.";
    }
    const section = el("bought-section");
    if (section) section.hidden = boughtCount === 0;
    const counter = el("bought-count");
    if (counter) counter.textContent = boughtCount;
  }

  function placeRow(row, bought) {
    row.classList.toggle("is-bought", bought);
    const toggle = row.querySelector(".shop-item-toggle");
    if (toggle) toggle.setAttribute("aria-pressed", bought ? "true" : "false");
    if (bought) {
      el("bought-items").prepend(row);
    } else {
      el("open-items").append(row);
    }
    updateCounts();
  }

  async function withPending(promise) {
    pending++;
    try {
      return await promise;
    } finally {
      pending--;
    }
  }

  // ── Abhaken ────────────────────────────────────────────────────────────
  document.addEventListener("click", async (event) => {
    const toggle = event.target.closest(".shop-item-toggle");
    if (!toggle) return;
    touch();
    const row = toggle.closest(".shop-item");
    const wasBought = row.classList.contains("is-bought");
    placeRow(row, !wasBought);
    try {
      const data = await withPending(wochii.post(toggle.dataset.url));
      if (data && data.is_bought !== !wasBought) placeRow(row, data.is_bought);
    } catch (err) {
      placeRow(row, wasBought);
    }
  });

  // ── Löschen mit Rückgängig ────────────────────────────────────────────
  document.addEventListener("click", async (event) => {
    const button = event.target.closest(".shop-item-delete");
    if (!button) return;
    touch();
    const row = button.closest(".shop-item");
    const parent = row.parentElement;
    const next = row.nextElementSibling;
    const name = row.dataset.name;
    const quantity = row.dataset.quantity;
    row.remove();
    updateCounts();
    try {
      await withPending(wochii.post(button.dataset.url));
    } catch (err) {
      parent.insertBefore(row, next);
      updateCounts();
      return;
    }
    wochii.toast(`„${name}“ gelöscht`, {
      actionLabel: "Rückgängig",
      onAction: () => addItem(name, quantity, true),
      duration: 6000,
    });
  });

  // ── Hinzufügen ────────────────────────────────────────────────────────
  async function addItem(name, quantity, force) {
    const body = new FormData();
    body.append("name", name);
    body.append("quantity", quantity || "");
    if (force) body.append("force", "true");
    const data = await withPending(wochii.post(addForm.action, body));
    if (data.status === "added") {
      const existing = el(`item-${data.id}`);
      const row = rowFromHtml(data.html);
      if (existing) existing.remove();
      el("open-items").prepend(row);
      updateCounts();
    } else if (data.status === "duplicate") {
      const extra = data.new_quantity;
      wochii.toast(`„${data.name}“ steht schon auf der Liste`, extra ? {
        actionLabel: "Menge addieren",
        onAction: () => mergeQuantity(data.existing_id, extra),
        duration: 7000,
      } : {
        actionLabel: "Trotzdem hinzufügen",
        onAction: () => addItem(name, quantity, true),
        duration: 7000,
      });
      const row = el(`item-${data.existing_id}`);
      if (row) {
        row.classList.add("is-highlighted");
        setTimeout(() => row.classList.remove("is-highlighted"), 1600);
      }
    }
    return data;
  }

  async function mergeQuantity(itemId, extra) {
    const body = new FormData();
    body.append("extra_quantity", extra);
    const data = await withPending(wochii.post(`/shopping/${itemId}/merge/`, body));
    const row = el(`item-${itemId}`);
    if (row && data && data.html) {
      const updated = rowFromHtml(data.html);
      row.replaceWith(updated);
    }
  }

  if (addForm) {
    addForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      touch();
      const name = nameInput.value.trim();
      if (!name) return;
      const button = addForm.querySelector("button[type=submit]");
      button.disabled = true;
      try {
        const data = await addItem(name, qtyInput.value.trim(), false);
        if (data && data.status === "added") {
          nameInput.value = "";
          qtyInput.value = "";
        }
      } catch (err) {
        // Meldung kommt aus wochii.post; Eingabe bleibt zum erneuten Senden stehen.
      } finally {
        button.disabled = false;
        // Tastatur bleibt offen: mehrere Artikel nacheinander eintippen.
        nameInput.focus();
      }
    });
  }

  // ── Erledigte entfernen / Einkauf beenden ────────────────────────────
  document.addEventListener("submit", async (event) => {
    const form = event.target;
    if (form.dataset.confirm && !window.confirm(form.dataset.confirm)) {
      event.preventDefault();
      return;
    }
    if (form.id !== "clear-bought-form") return;
    event.preventDefault();
    const count = el("bought-items").children.length;
    if (!window.confirm(`${count} erledigte Artikel von der Liste entfernen?`)) return;
    try {
      const data = await withPending(wochii.post(form.action));
      el("bought-items").replaceChildren();
      updateCounts();
      wochii.toast(`${data.removed} erledigte Artikel entfernt`);
    } catch (err) {
      /* Meldung kommt aus wochii.post */
    }
  });

  // ── Aktualisieren, wenn man zurück in den Tab kommt ───────────────────
  async function refresh() {
    if (document.hidden || pending > 0 || Date.now() - lastInteraction < 4000) return;
    if (document.activeElement && document.activeElement.closest("#shopping-list-body")) return;
    try {
      const response = await fetch(`${window.location.pathname}?partial=1`, {
        credentials: "same-origin",
        headers: { "X-Requested-With": "XMLHttpRequest" },
      });
      if (!response.ok || response.redirected) return;
      const html = await response.text();
      const current = el("shopping-list-body");
      if (current && pending === 0 && Date.now() - lastInteraction >= 4000) {
        const wasOpen = el("bought-section") && el("bought-section").open;
        current.outerHTML = html;
        if (wasOpen && el("bought-section")) el("bought-section").open = true;
      }
    } catch (err) {
      /* offline – beim nächsten Mal */
    }
  }

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) refresh();
  });
  setInterval(refresh, 30000);
})();
