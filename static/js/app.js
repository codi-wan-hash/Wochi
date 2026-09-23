/* Gemeinsame Helfer für die Seiten-Skripte.
 *
 * wochii.post(url, body)   POST mit CSRF-Token. Wirft bei Fehlern und zeigt
 *                          selbst eine verständliche Meldung an (kein Netz,
 *                          Sitzung abgelaufen, Serverfehler).
 * wochii.toast(text, opts) Kurze Meldung unten am Bildschirm, optional mit
 *                          Aktion ("Rückgängig").
 * wochii.escapeHtml(text)  Für die seltenen Fälle, in denen HTML gebaut wird –
 *                          Nutzerdaten nie ungeprüft in innerHTML schreiben.
 */
(function () {
  "use strict";

  function csrfToken() {
    const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    if (match) return decodeURIComponent(match[1]);
    const input = document.querySelector("input[name=csrfmiddlewaretoken]");
    return input ? input.value : "";
  }

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function toastRoot() {
    let root = document.getElementById("wochii-toasts");
    if (!root) {
      root = document.createElement("div");
      root.id = "wochii-toasts";
      root.className = "wochii-toasts";
      root.setAttribute("aria-live", "polite");
      document.body.appendChild(root);
    }
    return root;
  }

  function toast(text, opts) {
    opts = opts || {};
    const el = document.createElement("div");
    el.className = "wochii-toast" + (opts.variant === "danger" ? " is-danger" : "");
    el.setAttribute("role", opts.variant === "danger" ? "alert" : "status");
    const label = document.createElement("span");
    label.textContent = text;
    el.appendChild(label);
    let timer = null;
    const close = () => {
      clearTimeout(timer);
      el.remove();
    };
    if (opts.actionLabel && opts.onAction) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "wochii-toast-action";
      button.textContent = opts.actionLabel;
      button.addEventListener("click", () => {
        close();
        opts.onAction();
      });
      el.appendChild(button);
    }
    toastRoot().appendChild(el);
    timer = setTimeout(() => {
      el.remove();
      if (opts.onTimeout) opts.onTimeout();
    }, opts.duration || 4000);
    return { close };
  }

  async function post(url, body) {
    let response;
    try {
      response = await fetch(url, {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-CSRFToken": csrfToken(), "X-Requested-With": "XMLHttpRequest" },
        body: body,
      });
    } catch (err) {
      toast("Keine Verbindung. Bitte später noch einmal versuchen.", { variant: "danger" });
      throw err;
    }
    // Abgelaufene Sitzung: Django leitet zur Anmeldung um, fetch folgt still.
    if (response.redirected && response.url.indexOf("/accounts/login/") !== -1) {
      toast("Deine Sitzung ist abgelaufen. Bitte neu anmelden.", { variant: "danger" });
      setTimeout(() => { window.location.href = response.url; }, 1200);
      throw new Error("session expired");
    }
    const type = response.headers.get("content-type") || "";
    const data = type.indexOf("json") !== -1 ? await response.json().catch(() => null) : null;
    if (!response.ok) {
      const message = (data && (data.error || data.detail)) || "Das hat nicht geklappt. Bitte erneut versuchen.";
      toast(message, { variant: "danger" });
      const error = new Error("HTTP " + response.status);
      error.data = data;
      throw error;
    }
    return data;
  }

  window.wochii = { post: post, toast: toast, csrfToken: csrfToken, escapeHtml: escapeHtml };
})();
