(function () {
  const pages = {
    logs: { el: document.getElementById("page-logs"), mount: window.mountLogs, title: "Logs" },
    chat: { el: document.getElementById("page-chat"), mount: window.mountChat, title: "Chat" },
    status: { el: document.getElementById("page-status"), mount: window.mountStatus, title: "Status" },
    gallery: { el: document.getElementById("page-gallery"), mount: window.mountGallery, title: "Gallery" },
    users: { el: document.getElementById("page-users"), mount: window.mountUsers, title: "Users" },
  };
  let isAdmin = false;
  const handles = {};

  function currentName() {
    const hash = (location.hash || "#chat").replace("#", "");
    if (hash === "users" && !isAdmin) return "chat";
    return pages[hash] ? hash : "chat";
  }

  function show(name) {
    if (window.TabbyUI && TabbyUI.hideContextMenu) TabbyUI.hideContextMenu();
    closeUserMenu();
    const key = pages[name] ? name : "chat";
    Object.entries(pages).forEach(([id, page]) => {
      const on = id === key;
      page.el.hidden = !on;
      page.el.classList.toggle("is-active", on);
      if (on) {
        if (!handles[id]) handles[id] = page.mount(page.el);
        else if (typeof handles[id].resume === "function") handles[id].resume();
      } else if (handles[id] && typeof handles[id].pause === "function") {
        handles[id].pause();
      }
    });
    document.querySelectorAll(".tab").forEach((tab) => {
      tab.classList.toggle("is-active", tab.dataset.page === key);
    });
    const title = document.getElementById("header-title");
    if (title) title.textContent = pages[key].title;
  }

  const gpuChip = document.getElementById("gpu-chip");
  if (gpuChip) {
    gpuChip.addEventListener("contextmenu", (event) => {
      TabbyUI.showContextMenu(event, [
        { label: "Copy status", run: () => TabbyUI.copyText(gpuChip.textContent || "") },
      ]);
    });
  }

  const userChip = document.getElementById("user-chip");
  const userMenu = document.getElementById("user-menu");
  const userPanel = document.getElementById("user-menu-panel");
  const themeBtn = document.getElementById("user-menu-theme");
  const modeBtn = document.getElementById("user-menu-mode");
  const themeFly = document.getElementById("user-menu-theme-flyout");
  const modeFly = document.getElementById("user-menu-mode-flyout");
  const themeHint = document.getElementById("user-menu-theme-hint");
  const modeHint = document.getElementById("user-menu-mode-hint");
  const zoomInput = document.getElementById("user-menu-zoom");
  const zoomHint = document.getElementById("user-menu-zoom-hint");
  const restartItem = document.getElementById("user-menu-restart");
  let userMenuOpen = false;

  function closeFlyouts() {
    if (themeFly) themeFly.hidden = true;
    if (modeFly) modeFly.hidden = true;
    if (themeBtn) themeBtn.setAttribute("aria-expanded", "false");
    if (modeBtn) modeBtn.setAttribute("aria-expanded", "false");
  }

  function closeUserMenu() {
    userMenuOpen = false;
    if (userPanel) userPanel.hidden = true;
    if (userChip) userChip.setAttribute("aria-expanded", "false");
    closeFlyouts();
  }

  function paintUserMenuHints() {
    if (themeHint) themeHint.textContent = TabbyUI.THEME_LABELS[TabbyUI.getTheme()] || "Midnight";
    if (modeHint) modeHint.textContent = TabbyUI.MODE_LABELS[TabbyUI.getMode()] || "Dark";
    if (themeFly) {
      themeFly.querySelectorAll("[data-theme-family]").forEach((btn) => {
        btn.classList.toggle("is-on", btn.dataset.themeFamily === TabbyUI.getTheme());
      });
    }
    if (modeFly) {
      modeFly.querySelectorAll("[data-theme-mode]").forEach((btn) => {
        btn.classList.toggle("is-on", btn.dataset.themeMode === TabbyUI.getMode());
      });
    }
    const fsBtn = userPanel && userPanel.querySelector('[data-user-act="fullscreen"]');
    if (fsBtn) fsBtn.textContent = document.fullscreenElement ? "Exit full screen" : "Full screen";
    const pct = TabbyUI.getZoom();
    if (zoomInput) zoomInput.value = String(pct);
    if (zoomHint) zoomHint.textContent = `${pct}%`;
  }

  function fillThemeFlyout() {
    if (!themeFly) return;
    themeFly.replaceChildren();
    TabbyUI.THEME_FAMILIES.forEach((id) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "user-menu-item user-menu-theme";
      btn.dataset.themeFamily = id;
      const swatch = document.createElement("span");
      swatch.className = "theme-swatch";
      swatch.dataset.family = id;
      swatch.innerHTML = "<i></i><i></i>";
      const label = document.createElement("span");
      label.textContent = TabbyUI.THEME_LABELS[id] || id;
      const mark = document.createElement("kbd");
      mark.textContent = "✓";
      btn.append(swatch, label, mark);
      btn.addEventListener("click", (ev) => {
        ev.preventDefault();
        TabbyUI.setTheme(id);
        paintUserMenuHints();
      });
      themeFly.appendChild(btn);
    });
  }

  function fillModeFlyout() {
    if (!modeFly) return;
    modeFly.replaceChildren();
    TabbyUI.THEME_MODES.forEach((id) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "user-menu-item";
      btn.dataset.themeMode = id;
      const label = document.createElement("span");
      label.textContent = TabbyUI.MODE_LABELS[id] || id;
      const mark = document.createElement("kbd");
      mark.textContent = "✓";
      btn.append(label, mark);
      btn.addEventListener("click", (ev) => {
        ev.preventDefault();
        TabbyUI.setMode(id);
        paintUserMenuHints();
      });
      modeFly.appendChild(btn);
    });
  }

  function openUserMenu() {
    userMenuOpen = true;
    if (userPanel) userPanel.hidden = false;
    if (userChip) userChip.setAttribute("aria-expanded", "true");
    paintUserMenuHints();
  }

  fillThemeFlyout();
  fillModeFlyout();
  paintUserMenuHints();
  document.addEventListener("tabby-theme-change", paintUserMenuHints);
  document.addEventListener("fullscreenchange", paintUserMenuHints);

  if (userChip) {
    userChip.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      if (userMenuOpen) closeUserMenu();
      else openUserMenu();
    });
    userChip.addEventListener("contextmenu", (event) => {
      const nameEl = document.getElementById("user-chip-name");
      const name = (nameEl && nameEl.textContent) || "";
      if (!name) return;
      TabbyUI.showContextMenu(event, [
        { label: "Copy username", run: () => TabbyUI.copyText(name) },
      ]);
    });
  }

  if (themeBtn && themeFly) {
    themeBtn.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const open = themeFly.hidden;
      closeFlyouts();
      themeFly.hidden = !open;
      themeBtn.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }
  if (modeBtn && modeFly) {
    modeBtn.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const open = modeFly.hidden;
      closeFlyouts();
      modeFly.hidden = !open;
      modeBtn.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }
  if (zoomInput) {
    zoomInput.addEventListener("input", () => {
      TabbyUI.setZoom(zoomInput.value);
      paintUserMenuHints();
    });
  }

  async function logout() {
    try {
      const response = await fetch(TabbyUI.path("auth/logout"), {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
      });
      if (!response.ok) throw new Error(`Logout failed (${response.status})`);
      TabbyUI.redirectToLogin();
    } catch (err) {
      console.error(err);
    }
  }

  async function restartApi() {
    closeUserMenu();
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
    } catch (err) {
      modal.setBusy(false);
      modal.setTitle("Restart");
      modal.setNote((err && err.message) || "Restart failed.");
      modal.setActions([{ label: "Close", primary: true, run: () => modal.close() }]);
    }
  }

  if (userPanel) {
    userPanel.addEventListener("click", (event) => {
      const act = event.target.closest("[data-user-act]");
      if (!act) return;
      event.preventDefault();
      const name = act.dataset.userAct;
      if (name === "keys") {
        closeUserMenu();
        TabbyUI.showShortcuts();
      } else if (name === "copy") {
        const nameEl = document.getElementById("user-chip-name");
        TabbyUI.copyText((nameEl && nameEl.textContent) || "");
        closeUserMenu();
      } else if (name === "fullscreen") {
        if (document.fullscreenElement) document.exitFullscreen();
        else document.documentElement.requestFullscreen().catch(() => {});
      } else if (name === "restart") {
        restartApi();
      } else if (name === "logout") {
        closeUserMenu();
        logout();
      }
    });
  }

  document.addEventListener("pointerdown", (event) => {
    if (!userMenuOpen || !userMenu) return;
    if (userMenu.contains(event.target)) return;
    closeUserMenu();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && userMenuOpen) closeUserMenu();
  });

  TabbyUI.api("auth/check")
    .then((data) => {
      const nameEl = document.getElementById("user-chip-name");
      const name = data.username || data.stack_user || "";
      if (nameEl) nameEl.textContent = name;
      const chip = document.getElementById("user-chip");
      if (chip && name) chip.setAttribute("aria-label", name);
      isAdmin = Boolean(data.is_admin);
      const tab = document.getElementById("tab-users");
      if (tab) tab.hidden = !isAdmin;
      if (restartItem) restartItem.hidden = !isAdmin;
      if (!isAdmin && (location.hash || "").replace("#", "") === "users") {
        location.hash = "#chat";
      }
    })
    .catch(() => {});

  let headerTimer = 0;
  let headerFailing = false;

  async function refreshHeaderStatus() {
    try {
      const data = await TabbyUI.api("status");
      headerFailing = false;
      TabbyUI.paintGpuChip(data);
    } catch (err) {
      headerFailing = true;
      TabbyUI.paintApiDown(err);
    } finally {
      if (headerTimer) clearTimeout(headerTimer);
      headerTimer = setTimeout(refreshHeaderStatus, headerFailing ? 3000 : 15000);
    }
  }
  refreshHeaderStatus();

  window.addEventListener("hashchange", () => show(currentName()));
  show(currentName());
  if (typeof TABBY_REVEAL_UI === "function") TABBY_REVEAL_UI();
})();
