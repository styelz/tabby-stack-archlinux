(() => {
  function score(item, query) {
    const q = String(query || "").trim().toLowerCase();
    const label = String(item.label || item.path || "").toLowerCase();
    const hint = String(item.hint || item.path || "").toLowerCase();
    if (!q) return 1;
    if (label === q || hint === q) return 100;
    if (label.startsWith(q) || hint.startsWith(q)) return 80;
    const name = label.split("/").pop() || "";
    if (name.startsWith(q)) return 70;
    if (label.includes(q) || hint.includes(q)) return 40;
    const parts = q.split(/\s+/).filter(Boolean);
    if (parts.length && parts.every((part) => label.includes(part) || hint.includes(part))) {
      return 20;
    }
    return 0;
  }

  function closePalette() {
    const wrap = document.querySelector(".tabby-palette");
    if (wrap) wrap.remove();
  }

  function openPalette(opts) {
    closePalette();
    const items = Array.isArray(opts && opts.items) ? opts.items.slice() : [];
    const wrap = document.createElement("div");
    wrap.className = "tabby-palette";
    wrap.setAttribute("role", "dialog");
    wrap.setAttribute("aria-modal", "true");
    wrap.innerHTML =
      '<div class="tabby-palette-card">' +
      `<p class="tabby-palette-title">${window.TabbyUI ? TabbyUI.escapeHtml((opts && opts.title) || "Jump to file") : "Jump to file"}</p>` +
      '<input type="search" class="tabby-palette-input" autocomplete="off" spellcheck="false" />' +
      '<ul class="tabby-palette-list" role="listbox"></ul>' +
      "</div>";
    const input = wrap.querySelector(".tabby-palette-input");
    const list = wrap.querySelector(".tabby-palette-list");
    input.placeholder = (opts && opts.placeholder) || "Filter…";
    let index = 0;
    let shown = [];

    function paint() {
      const query = input.value;
      shown = items
        .map((item) => ({ item, score: score(item, query) }))
        .filter((row) => row.score > 0)
        .sort((a, b) => b.score - a.score || String(a.item.label).localeCompare(String(b.item.label)))
        .slice(0, 60)
        .map((row) => row.item);
      if (index >= shown.length) index = Math.max(0, shown.length - 1);
      list.replaceChildren();
      if (!shown.length) {
        const empty = document.createElement("li");
        empty.className = "is-empty";
        empty.textContent = "No matches";
        list.appendChild(empty);
        return;
      }
      shown.forEach((item, i) => {
        const li = document.createElement("li");
        li.className = i === index ? "is-active" : "";
        li.innerHTML =
          `<span>${window.TabbyUI ? TabbyUI.escapeHtml(item.label || item.path || "") : item.label}</span>` +
          (item.hint
            ? `<kbd>${window.TabbyUI ? TabbyUI.escapeHtml(item.hint) : item.hint}</kbd>`
            : "");
        li.addEventListener("mousedown", (event) => {
          event.preventDefault();
          pick(item);
        });
        list.appendChild(li);
      });
    }

    function pick(item) {
      finish();
      if (item && typeof (opts && opts.onPick) === "function") opts.onPick(item);
    }

    function finish() {
      document.removeEventListener("keydown", onKey, true);
      wrap.remove();
    }

    function onKey(event) {
      if (!document.body.contains(wrap)) return;
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        finish();
        return;
      }
      if (event.key === "ArrowDown") {
        event.preventDefault();
        index = shown.length ? (index + 1) % shown.length : 0;
        paint();
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        index = shown.length ? (index - 1 + shown.length) % shown.length : 0;
        paint();
        return;
      }
      if (event.key === "Enter") {
        event.preventDefault();
        if (shown[index]) pick(shown[index]);
      }
    }

    wrap.addEventListener("click", (event) => {
      if (event.target === wrap) finish();
    });
    input.addEventListener("input", () => {
      index = 0;
      paint();
    });
    document.addEventListener("keydown", onKey, true);
    document.body.appendChild(wrap);
    paint();
    input.focus();
    if (opts && opts.query) {
      input.value = String(opts.query);
      paint();
    }
    return { close: finish, input };
  }

  window.TabbyPalette = { open: openPalette, close: closePalette };
})();
