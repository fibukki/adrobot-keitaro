// Small vanilla widgets. All handlers are delegated on `document`, so they also work
// inside fragments swapped in by htmx without re-initialisation.
"use strict";

(() => {
  const flash = (html) => {
    const box = document.getElementById("flash");
    if (box) box.innerHTML = html;
  };
  const escapeHtml = (s) =>
    String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const errorHtml = (msg) => `<div class="alert alert-error" role="alert">${escapeHtml(msg)}</div>`;

  // ---------------------------------------------------------------- offer autocomplete
  const debounceTimers = new WeakMap();

  const pickerParts = (el) => {
    const root = el.closest(".offer-picker");
    return {
      root,
      search: root.querySelector(".offer-search"),
      hidden: root.querySelector('input[name="offer_id"]'),
      list: root.querySelector(".offer-results"),
    };
  };

  const renderResults = (parts, offers) => {
    parts.list.innerHTML = offers.length
      ? offers
          .map(
            (o, i) =>
              `<li role="option" data-id="${o.id}" data-label="${escapeHtml(o.label)}"` +
              `${i === 0 ? ' class="active"' : ""}>${escapeHtml(o.label)}` +
              `${o.state && o.state !== "active" ? ` <span class="muted">(${escapeHtml(o.state)})</span>` : ""}</li>`
          )
          .join("")
      : '<li class="muted empty">Nothing found</li>';
    parts.list.hidden = false;
  };

  const choose = (parts, li) => {
    if (!li || !li.dataset.id) return;
    parts.hidden.value = li.dataset.id;
    parts.search.value = li.dataset.label;
    parts.search.classList.remove("invalid");
    parts.list.hidden = true;
  };

  const search = async (parts) => {
    const q = parts.search.value.trim();
    try {
      const resp = await fetch(`/api/offers?q=${encodeURIComponent(q)}`, { headers: { Accept: "application/json" } });
      const body = await resp.json();
      if (!resp.ok) throw new Error(body.detail || `HTTP ${resp.status}`);
      if (parts.search.value.trim() === q) renderResults(parts, body);
    } catch (err) {
      flash(errorHtml(`Offer search failed: ${err.message}`));
    }
  };

  document.addEventListener("input", (e) => {
    if (!e.target.matches(".offer-search")) return;
    const parts = pickerParts(e.target);
    parts.hidden.value = ""; // typed text is not a selection until an item is picked
    clearTimeout(debounceTimers.get(parts.root));
    debounceTimers.set(parts.root, setTimeout(() => search(parts), 200));
  });

  document.addEventListener("focusin", (e) => {
    if (e.target.matches(".offer-search") && !pickerParts(e.target).hidden.value) {
      search(pickerParts(e.target));
    }
  });

  document.addEventListener("focusout", (e) => {
    if (!e.target.matches(".offer-search")) return;
    const parts = pickerParts(e.target);
    setTimeout(() => (parts.list.hidden = true), 150);
  });

  document.addEventListener("mousedown", (e) => {
    const li = e.target.closest(".offer-results li");
    if (li) {
      e.preventDefault();
      choose(pickerParts(li), li);
    }
  });

  document.addEventListener("keydown", (e) => {
    if (e.target.matches(".offer-search")) {
      const parts = pickerParts(e.target);
      const items = [...parts.list.querySelectorAll("li[data-id]")];
      const current = items.findIndex((li) => li.classList.contains("active"));
      if (parts.list.hidden || !items.length) return;
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        const next = (current + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
        items.forEach((li, i) => li.classList.toggle("active", i === next));
      } else if (e.key === "Enter") {
        e.preventDefault();
        choose(parts, items[Math.max(current, 0)]);
      } else if (e.key === "Escape") {
        parts.list.hidden = true;
      }
    } else if (e.target.matches(".geo-input") && (e.key === "Enter" || e.key === ",")) {
      e.preventDefault();
      addGeo(e.target);
    }
  });

  const offerMissing = (form) => {
    const hidden = form.querySelector('.offer-picker input[name="offer_id"]');
    if (!hidden || hidden.value) return false;
    const search = form.querySelector(".offer-search");
    search.classList.add("invalid");
    search.focus();
    flash(errorHtml("Pick an offer from the suggestions list"));
    return true;
  };

  // htmx forms: cancel the request if no offer was picked.
  document.addEventListener("htmx:beforeRequest", (e) => {
    const form = e.detail.elt;
    if (form.matches && form.matches("form.needs-offer") && offerMissing(form)) e.preventDefault();
  });

  // ---------------------------------------------------------------------- geo chips
  const countryCodes = () => new Set([...document.querySelectorAll("#countries option")].map((o) => o.value));

  const addGeo = (input) => {
    const picker = input.closest(".geo-picker");
    const chips = picker.querySelector(".chips");
    const known = countryCodes();
    const present = new Set([...chips.querySelectorAll('input[name="geo"]')].map((i) => i.value));
    const rejected = [];
    for (const token of input.value.split(/[\s,;]+/).filter(Boolean)) {
      const code = token.toUpperCase();
      if (!known.has(code)) {
        rejected.push(token);
        continue;
      }
      if (present.has(code)) continue;
      present.add(code);
      chips.insertAdjacentHTML(
        "beforeend",
        `<span class="chip">${code}<input type="hidden" name="geo" value="${code}">` +
          `<button type="button" class="chip-remove" aria-label="Remove ${code}">×</button></span>`
      );
    }
    input.value = rejected.join(", ");
    input.classList.toggle("invalid", rejected.length > 0);
    if (rejected.length) flash(errorHtml(`Unknown country code: ${rejected.join(", ")} (use ISO 3166-1 alpha-2, e.g. MX)`));
  };

  document.addEventListener("change", (e) => {
    if (e.target.matches(".geo-input")) addGeo(e.target);
  });

  document.addEventListener("click", (e) => {
    if (e.target.matches(".chip-remove")) e.target.closest(".chip").remove();
  });

  // Plain (non-htmx) creation form.
  document.addEventListener("submit", (e) => {
    const form = e.target;
    if (form.id !== "create-form") return;
    const geoInput = form.querySelector(".geo-input");
    if (geoInput.value.trim()) addGeo(geoInput);
    if (!form.querySelector('input[name="geo"]')) {
      e.preventDefault();
      geoInput.classList.add("invalid");
      geoInput.focus();
      flash(errorHtml("Add at least one country"));
      return;
    }
    if (offerMissing(form)) e.preventDefault();
  });

  // -------------------------------------------------------------- htmx error display
  document.addEventListener("htmx:beforeSwap", (e) => {
    const status = e.detail.xhr.status;
    if (status >= 400) {
      // Errors come back as an alert fragment: show it in the flash area instead.
      e.detail.shouldSwap = true;
      e.detail.isError = false;
      e.detail.target = document.getElementById("flash");
      e.detail.swapOverride = "innerHTML";
    } else if (e.detail.target && e.detail.target.id !== "flash") {
      flash("");
    }
  });

  document.addEventListener("htmx:sendError", () => flash(errorHtml("Server is unreachable, try again")));
})();
