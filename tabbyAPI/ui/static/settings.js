function mountSettings(root) {
  root.innerHTML = `
    <div class="settings-page">
      <div class="toolbar">
        <button class="btn primary" type="button" id="settings-save">Save</button>
        <button class="btn" type="button" id="settings-reload">Reload</button>
        <button class="btn danger" type="button" id="settings-restart">Restart API</button>
        <span class="spacer"></span>
        <span class="muted" id="settings-stamp"></span>
      </div>
      <p class="error" id="settings-error" hidden></p>
      <p class="muted" id="settings-ok" hidden></p>
      <div class="settings-layout">
        <nav class="settings-nav" id="settings-nav" aria-label="Settings sections"></nav>
        <div class="settings-body" id="settings-body"></div>
      </div>
    </div>
  `;
  const nav = root.querySelector("#settings-nav");
  const body = root.querySelector("#settings-body");
  const err = root.querySelector("#settings-error");
  const ok = root.querySelector("#settings-ok");
  const stamp = root.querySelector("#settings-stamp");
  let payload = null;

  function showError(message) {
    err.hidden = !message;
    err.textContent = message || "";
    if (message) ok.hidden = true;
  }

  function showOk(message) {
    ok.hidden = !message;
    ok.textContent = message || "";
    if (message) err.hidden = true;
  }

  function fieldId(section, name) {
    return `set-${section}-${name}`;
  }

  function helpText(text) {
    return String(text || "").replace(/\n+/g, " ").trim();
  }

  function formatValue(value) {
    if (value == null) return "";
    if (typeof value === "object") return JSON.stringify(value);
    return String(value);
  }

  function sameValue(a, b) {
    return JSON.stringify(a) === JSON.stringify(b);
  }

  function inputFor(section, field) {
    const id = fieldId(section, field.name);
    const kind = field.kind;
    const value = field.value;
    if (kind === "bool") {
      const on = value === true || value === "true";
      return `<input id="${id}" type="checkbox"${on ? " checked" : ""} />`;
    }
    if (kind === "select") {
      const choices = field.choices || [];
      const current = value == null || value === "" ? "" : String(value);
      const blank = field.blank != null ? `<option value="">${TabbyUI.escapeHtml(field.blank)}</option>` : "";
      const opts = choices
        .map((choice) => {
          const picked = current === String(choice) ? " selected" : "";
          return `<option value="${TabbyUI.escapeHtml(String(choice))}"${picked}>${TabbyUI.escapeHtml(String(choice))}</option>`;
        })
        .join("");
      return `<select id="${id}">${blank}${opts}</select>`;
    }
    if (kind === "json") {
      const text = value == null || value === "" ? "" : JSON.stringify(value, null, 2);
      return `<textarea id="${id}" rows="5" spellcheck="false">${TabbyUI.escapeHtml(text)}</textarea>`;
    }
    if (kind === "list_text" || kind === "list_number") {
      const text = Array.isArray(value) ? value.join(", ") : formatValue(value);
      return `<input id="${id}" type="text" value="${TabbyUI.escapeHtml(text)}" />`;
    }
    if (kind === "int" || kind === "float") {
      const text = value == null ? "" : String(value);
      const step = kind === "int" ? "1" : "any";
      return `<input id="${id}" type="number" step="${step}" value="${TabbyUI.escapeHtml(text)}" />`;
    }
    const type = field.secret ? "password" : "text";
    const placeholder = field.secret && field.set ? "leave blank to keep" : "";
    return `<input id="${id}" type="${type}" value="${field.secret ? "" : TabbyUI.escapeHtml(formatValue(value))}" placeholder="${TabbyUI.escapeHtml(placeholder)}" autocomplete="off" />`;
  }

  function fieldHtml(section, field) {
    const id = fieldId(section, field.name);
    const help = helpText(field.description);
    const live = field.secret ? "" : field.live;
    const fileVal = field.secret ? null : field.value;
    const showLive = !field.secret && live != null && !sameValue(live, fileVal);
    const env = field.env;
    const notes = [];
    if (field.secret && field.set) notes.push("saved");
    if (env) notes.push("env override");
    if (showLive) notes.push(`active: ${formatValue(live)}`);
    const note = notes.length
      ? `<span class="settings-note">${TabbyUI.escapeHtml(notes.join(" · "))}</span>`
      : "";
    const clear = field.secret && field.set
      ? `<label class="settings-clear"><input type="checkbox" data-clear="${TabbyUI.escapeHtml(field.name)}" /> Clear</label>`
      : "";
    return `
      <div class="settings-field${field.kind === "bool" ? " is-check" : ""}" data-section="${TabbyUI.escapeHtml(section)}" data-name="${TabbyUI.escapeHtml(field.name)}" data-kind="${TabbyUI.escapeHtml(field.kind)}">
        <div class="settings-field-head">
          <label for="${id}">${TabbyUI.escapeHtml(field.label || field.name)}</label>
          ${note}
          ${clear}
        </div>
        ${help ? `<p class="settings-help" title="${TabbyUI.escapeHtml(field.description || "")}">${TabbyUI.escapeHtml(help)}</p>` : ""}
        ${inputFor(section, field)}
      </div>
    `;
  }

  function sectionCard(section) {
    const path = section.path ? `<p class="muted settings-path">${TabbyUI.escapeHtml(section.path)}</p>` : "";
    const fields = (section.fields || []).map((field) => fieldHtml(section.name, field)).join("");
    return `
      <section class="card settings-card" id="settings-sec-${TabbyUI.escapeHtml(section.name)}">
        <h2>${TabbyUI.escapeHtml(section.label || section.name)}</h2>
        ${section.description ? `<p class="muted">${TabbyUI.escapeHtml(section.description)}</p>` : ""}
        ${path}
        <div class="settings-fields">${fields}</div>
      </section>
    `;
  }

  function paint(data) {
    payload = data;
    const sections = [...(data.tabby || []), data.system].filter(Boolean);
    nav.innerHTML = sections
      .map((section) => (
        `<button type="button" class="settings-nav-item" data-sec="${TabbyUI.escapeHtml(section.name)}">${TabbyUI.escapeHtml(section.label || section.name)}</button>`
      ))
      .join("");
    body.innerHTML = sections.map(sectionCard).join("");
    const hint = data.restart_hint || "";
    const paths = data.paths || {};
    stamp.textContent = [paths.config, hint].filter(Boolean).join(" · ");
  }

  function parseField(wrap, spec) {
    const input = wrap.querySelector("input, select, textarea");
    if (!input) return undefined;
    const kind = spec.kind;
    if (spec.secret) {
      const clear = wrap.querySelector("[data-clear]");
      if (clear && clear.checked) return null;
      if (!String(input.value || "").trim()) return undefined;
      return input.value;
    }
    if (kind === "bool") return Boolean(input.checked);
    if (kind === "select") {
      const value = input.value;
      if (spec.blank != null && value === "") return null;
      if (spec.choices && spec.choices.length === 2 && spec.choices[0] === "true") {
        return value === "true";
      }
      return value;
    }
    if (kind === "json") {
      const text = String(input.value || "").trim();
      if (!text) return spec.optional ? null : {};
      return JSON.parse(text);
    }
    if (kind === "list_text") {
      return String(input.value || "")
        .split(",")
        .map((part) => part.trim())
        .filter(Boolean);
    }
    if (kind === "list_number") {
      return String(input.value || "")
        .split(",")
        .map((part) => part.trim())
        .filter(Boolean)
        .map((part) => {
          const n = part.includes(".") ? Number(part) : parseInt(part, 10);
          if (!Number.isFinite(n)) throw new Error("not a number");
          return n;
        });
    }
    if (kind === "int") {
      const text = String(input.value || "").trim();
      if (!text) return spec.optional ? null : 0;
      const n = parseInt(text, 10);
      if (!Number.isFinite(n)) throw new Error("not a number");
      return n;
    }
    if (kind === "float") {
      const text = String(input.value || "").trim();
      if (!text) return spec.optional ? null : 0;
      const n = Number(text);
      if (!Number.isFinite(n)) throw new Error("not a number");
      return n;
    }
    const text = String(input.value || "");
    if (!text.trim() && spec.optional) return null;
    return text;
  }

  function collect() {
    const specs = {};
    (payload.tabby || []).forEach((section) => {
      (section.fields || []).forEach((field) => {
        specs[`${section.name}.${field.name}`] = field;
      });
    });
    (payload.system && payload.system.fields || []).forEach((field) => {
      specs[`system.${field.name}`] = field;
    });
    const tabby = {};
    const system = {};
    body.querySelectorAll(".settings-field").forEach((wrap) => {
      const section = wrap.dataset.section;
      const name = wrap.dataset.name;
      const spec = specs[`${section}.${name}`];
      if (!spec) return;
      let value;
      try {
        value = parseField(wrap, spec);
      } catch (exc) {
        throw new Error(`${section}.${name}: ${exc.message || "invalid value"}`);
      }
      if (value === undefined) return;
      if (section === "system") system[name] = value;
      else {
        if (!tabby[section]) tabby[section] = {};
        tabby[section][name] = value;
      }
    });
    return { tabby, system };
  }

  async function load() {
    showError("");
    const data = await TabbyUI.api("settings");
    paint(data);
  }

  async function save() {
    showError("");
    showOk("");
    const bodyPayload = collect();
    const data = await TabbyUI.api("settings", { method: "PUT", body: bodyPayload });
    paint(data);
    showOk("Saved. Restart the API if network, model, or system values changed.");
  }

  async function restartApi() {
    const yes = await TabbyUI.confirmModal({
      title: "Restart API?",
      text: "Restart TabbyAPI now? The UI will drop for about a minute.",
      yes: "Restart",
      no: "Cancel",
    });
    if (!yes) return;
    const modal = TabbyUI.progressModal({
      title: "Restarting",
      note: "Restarting TabbyAPI. The UI will drop for about a minute.",
    });
    try {
      await TabbyUI.followRestart(modal);
      modal.setActions([
        { label: "Close", run: () => modal.close() },
        { label: "Reload UI", primary: true, run: () => location.reload() },
      ]);
    } catch (exc) {
      modal.setBusy(false);
      modal.setTitle("Restart");
      modal.setNote((exc && exc.message) || "Restart failed.");
      modal.setActions([{ label: "Close", primary: true, run: () => modal.close() }]);
    }
  }

  nav.addEventListener("click", (event) => {
    const btn = event.target.closest("[data-sec]");
    if (!btn) return;
    const target = root.querySelector(`#settings-sec-${btn.dataset.sec}`);
    if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
    nav.querySelectorAll(".settings-nav-item").forEach((item) => {
      item.classList.toggle("is-on", item === btn);
    });
  });

  root.querySelector("#settings-save").addEventListener("click", () => {
    save().catch((exc) => showError(exc.message || "Could not save."));
  });
  root.querySelector("#settings-reload").addEventListener("click", () => {
    load().catch((exc) => showError(exc.message || "Could not load."));
  });
  root.querySelector("#settings-restart").addEventListener("click", () => {
    restartApi().catch((exc) => showError(exc.message || "Restart failed."));
  });

  load().catch((exc) => showError(exc.message || "Could not load settings."));
  return {
    resume() {
      load().catch(() => {});
    },
    destroy() {},
  };
}

window.mountSettings = mountSettings;
