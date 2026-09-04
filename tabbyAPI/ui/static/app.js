(function () {
  const pages = {
    logs: { el: document.getElementById("page-logs"), mount: window.mountLogs, title: "Logs" },
    chat: { el: document.getElementById("page-chat"), mount: window.mountChat, title: "Chat" },
    status: { el: document.getElementById("page-status"), mount: window.mountStatus, title: "Status" },
    gallery: { el: document.getElementById("page-gallery"), mount: window.mountGallery, title: "Gallery" },
    users: { el: document.getElementById("page-users"), mount: window.mountUsers, title: "Users" },
    settings: { el: document.getElementById("page-settings"), mount: window.mountSettings, title: "Settings" },
  };
  let isAdmin = false;
  const handles = {};

  function currentName() {
    const hash = (location.hash || "#chat").replace("#", "");
    if ((hash === "users" || hash === "settings") && !isAdmin) return "chat";
    return pages[hash] ? hash : "chat";
  }

  function show(name) {
    if (window.TabbyUI && TabbyUI.hideContextMenu) TabbyUI.hideContextMenu();
    closeUserMenu();
    closeGpuMenu();
    closeContextMenu();
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
  const gpuMenu = document.getElementById("gpu-menu");
  const gpuPanel = document.getElementById("gpu-menu-panel");
  const contextChip = document.getElementById("context-chip");
  const contextMenu = document.getElementById("context-menu");
  const contextPanel = document.getElementById("context-menu-panel");
  let gpuMenuOpen = false;
  let contextMenuOpen = false;
  let gpuSwitchBusy = false;
  let gpuSwitchTarget = "";

  function gpuChipText() {
    const labelEl = document.getElementById("gpu-chip-label");
    return (labelEl && labelEl.textContent) || (gpuChip && gpuChip.textContent) || "";
  }

  function currentGpuMode(data) {
    if (!data || data.down) return "";
    const mode = String(data.gpu_mode || "").toLowerCase();
    if (mode && mode !== "llm") return "comfy";
    if (data.comfy_up && !data.tabby_model) return "comfy";
    return data.profile || "";
  }

  function gpuMenuBusy(data) {
    if (gpuSwitchBusy) return true;
    if (!data || data.down) return true;
    return Boolean(data.switching || data.restarting);
  }

  function statusWithLocalSwitch(data) {
    if (!gpuSwitchBusy) return data;
    const queue = (data && data.stack_queue) || {};
    if (queue.queued || (queue.busy && !(data && data.switching))) {
      return Object.assign({}, data || {}, {
        gpu_waiting: true,
        switch_target: (data && data.switch_target) || gpuSwitchTarget,
      });
    }
    return Object.assign({}, data || {}, {
      switching: true,
      busy: true,
      switch_target: (data && data.switch_target) || gpuSwitchTarget,
    });
  }

  function makeGpuItem(label, mode, on, busy, hint, note) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "user-menu-item" + (on ? " is-on" : "");
    btn.setAttribute("role", "menuitem");
    btn.dataset.gpuMode = mode;
    btn.disabled = Boolean(busy);
    const copy = document.createElement("span");
    copy.className = "gpu-item-copy";
    const name = document.createElement("span");
    name.textContent = label;
    copy.append(name);
    if (note && note !== label) {
      const sub = document.createElement("span");
      sub.className = "gpu-item-note";
      sub.textContent = note;
      copy.append(sub);
    }
    const mark = document.createElement("kbd");
    mark.textContent = on ? "✓" : hint || "";
    btn.append(copy, mark);
    btn.addEventListener("click", (event) => {
      event.preventDefault();
      if (on) {
        closeGpuMenu();
        return;
      }
      switchGpu(mode);
    });
    return btn;
  }

  function fillGpuMenu(data) {
    if (!gpuPanel) return;
    gpuPanel.replaceChildren();
    const switchLocked = gpuMenuBusy(data);
    const occupied = Boolean(data && data.stack_queue && data.stack_queue.busy);
    const current = currentGpuMode(data);
    const profiles = (data && data.profiles) || [];
    const labels = (data && data.profile_labels) || {};
    if (profiles.length) {
      profiles.forEach((name) => {
        gpuPanel.appendChild(
          makeGpuItem(
            name,
            name,
            current === name,
            switchLocked,
            occupied && !switchLocked && current !== name ? "Wait" : "",
            labels[name] || ""
          )
        );
      });
    } else {
      const empty = document.createElement("p");
      empty.className = "gpu-menu-empty";
      empty.textContent = data && data.down ? "API unavailable" : "No profiles yet";
      gpuPanel.appendChild(empty);
    }
    const sep = document.createElement("div");
    sep.className = "user-menu-sep";
    gpuPanel.appendChild(sep);
    gpuPanel.appendChild(
      makeGpuItem(
        "Comfy",
        "comfy",
        current === "comfy",
        switchLocked,
        occupied && !switchLocked && current !== "comfy" ? "Wait" : "Images"
      )
    );
    const copySep = document.createElement("div");
    copySep.className = "user-menu-sep";
    gpuPanel.appendChild(copySep);
    const copyBtn = document.createElement("button");
    copyBtn.type = "button";
    copyBtn.className = "user-menu-item";
    copyBtn.setAttribute("role", "menuitem");
    copyBtn.textContent = "Copy status";
    copyBtn.addEventListener("click", (event) => {
      event.preventDefault();
      TabbyUI.copyText(gpuChipText());
      closeGpuMenu();
    });
    gpuPanel.appendChild(copyBtn);
  }

  function closeGpuMenu() {
    gpuMenuOpen = false;
    if (gpuPanel) gpuPanel.hidden = true;
    if (gpuChip) gpuChip.setAttribute("aria-expanded", "false");
  }

  function closeContextMenu() {
    contextMenuOpen = false;
    if (contextPanel) contextPanel.hidden = true;
    if (contextChip) contextChip.setAttribute("aria-expanded", "false");
  }

  function openContextMenu() {
    if (!contextChip || contextChip.hidden) return;
    closeUserMenu();
    closeGpuMenu();
    contextMenuOpen = true;
    if (contextPanel) contextPanel.hidden = false;
    contextChip.setAttribute("aria-expanded", "true");
  }

  async function openGpuMenu() {
    closeUserMenu();
    closeContextMenu();
    gpuMenuOpen = true;
    if (gpuPanel) gpuPanel.hidden = false;
    if (gpuChip) gpuChip.setAttribute("aria-expanded", "true");
    fillGpuMenu(TabbyUI.lastGpuStatus);
    if (TabbyUI.lastGpuStatus && (TabbyUI.lastGpuStatus.profiles || []).length) return;
    try {
      TabbyUI.paintGpuChip(statusWithLocalSwitch(await TabbyUI.api("status")));
    } catch (err) {
      TabbyUI.paintApiDown(err);
    }
  }

  async function switchGpu(mode) {
    const token = String(mode || "").trim().toLowerCase();
    if (!token || gpuSwitchBusy) return;
    const data = TabbyUI.lastGpuStatus || {};
    if (currentGpuMode(data) === token) {
      closeGpuMenu();
      return;
    }
    if (gpuMenuBusy(data) && !gpuSwitchBusy) {
      closeGpuMenu();
      return;
    }
    closeGpuMenu();
    gpuSwitchBusy = true;
    gpuSwitchTarget = token;
    const queue = data.stack_queue || {};
    const waiting = Boolean(queue.busy) && !data.switching && !data.restarting;
    TabbyUI.paintGpuChip(
      Object.assign({}, data, waiting
        ? { gpu_waiting: true, switch_target: token }
        : {
            switching: true,
            busy: true,
            switch_target: token,
            profile: token === "comfy" ? data.profile : token,
          })
    );
    kickHeaderStatus(400);
    try {
      await TabbyUI.api("gpu", { method: "POST", body: { mode: token } });
      await refreshHeaderStatus();
    } catch (err) {
      TabbyUI.paintApiDown(err);
    } finally {
      gpuSwitchBusy = false;
      gpuSwitchTarget = "";
    }
  }

  if (gpuChip) {
    gpuChip.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      if (gpuMenuOpen) closeGpuMenu();
      else openGpuMenu();
    });
    gpuChip.addEventListener("contextmenu", (event) => {
      TabbyUI.showContextMenu(event, [
        { label: "Copy status", run: () => TabbyUI.copyText(gpuChipText()) },
      ]);
    });
  }
  window.addEventListener("tabby-gpu-status", () => {
    if (gpuMenuOpen) fillGpuMenu(TabbyUI.lastGpuStatus);
  });

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
  const settingsItem = document.getElementById("user-menu-settings");
  const settingsBtn = document.getElementById("settings-btn");
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
    closeGpuMenu();
    closeContextMenu();
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

  if (settingsBtn) {
    settingsBtn.addEventListener("click", (event) => {
      event.preventDefault();
      closeUserMenu();
      closeGpuMenu();
      closeContextMenu();
      location.hash = "#settings";
    });
  }

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
    if (TabbyUI.flushPrefs) await TabbyUI.flushPrefs();
    try {
      const response = await fetch(TabbyUI.path("auth/logout"), {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
      });
      if (!response.ok) throw new Error(`Logout failed (${response.status})`);
      TabbyUI.redirectToLogin();
    } catch (err) {
      closeUserMenu();
      TabbyUI.confirmModal({
        title: "Log out failed",
        text: (err && err.message) || "Could not log out. Try again.",
        yes: "OK",
        no: "Close",
      });
    }
  }

  async function downloadBackup() {
    closeUserMenu();
    const yes = await TabbyUI.confirmModal({
      title: "Download backup?",
      text: "Downloads this account's chats, Code files, prefs, and gallery images. Other accounts and model weights are not included. Keep this tab open until the download finishes.",
      yes: "Download",
      no: "Cancel",
    });
    if (!yes) return;
    const link = document.createElement("a");
    link.href = TabbyUI.path("backup");
    link.download = "";
    document.body.appendChild(link);
    link.click();
    link.remove();
  }

  async function restoreBackupFile(file) {
    if (!file) return;
    const yes = await TabbyUI.confirmModal({
      title: "Restore this backup?",
      text: "This replaces this account's chats, Code files, prefs, and gallery images. Other accounts are not changed. If the zip was made by another user, it is imported into this account.",
      yes: "Restore",
      no: "Cancel",
    });
    if (!yes) return;
    if (TabbyUI.suspendPersistence) TabbyUI.suspendPersistence();
    const modal = TabbyUI.progressModal({
      title: "Restoring backup",
      note: "Uploading and restoring this account's data.",
    });
    try {
      const response = await fetch(TabbyUI.path("backup/restore"), {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/zip" },
        body: file,
      });
      const type = response.headers.get("content-type") || "";
      const data = type.includes("application/json") ? await response.json() : await response.text();
      if (response.status === 401) {
        TabbyUI.redirectToLogin();
        throw new Error("Not authenticated");
      }
      if (!response.ok) {
        throw new Error(TabbyUI.httpErrorMessage(response, data));
      }
      modal.setBusy(false);
      modal.setTitle("Backup restored");
      modal.setNote("Reloading this account's chats, Code files, and gallery.");
      modal.setActions([]);
      location.reload();
    } catch (err) {
      modal.setBusy(false);
      modal.setTitle("Restore failed");
      modal.setNote((err && err.message) || "Could not restore the backup.");
      modal.setActions([{ label: "Close", primary: true, run: () => modal.close() }]);
    }
  }

  function pickBackupFile() {
    closeUserMenu();
    const input = document.getElementById("user-backup-file");
    if (!input) return;
    input.value = "";
    input.click();
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
      } else if (name === "settings") {
        closeUserMenu();
        location.hash = "#settings";
      } else if (name === "backup") {
        downloadBackup();
      } else if (name === "restore") {
        pickBackupFile();
      } else if (name === "restart") {
        restartApi();
      } else if (name === "logout") {
        closeUserMenu();
        logout();
      }
    });
  }

  const backupFile = document.getElementById("user-backup-file");
  if (backupFile) {
    backupFile.addEventListener("change", () => {
      const file = backupFile.files && backupFile.files[0];
      backupFile.value = "";
      restoreBackupFile(file);
    });
  }

  if (contextChip) {
    contextChip.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      if (contextMenuOpen) closeContextMenu();
      else openContextMenu();
    });
    contextChip.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      if (contextMenuOpen) closeContextMenu();
      else openContextMenu();
    });
  }
  const contextHandoff = document.getElementById("context-handoff");
  if (contextHandoff) {
    contextHandoff.addEventListener("click", (event) => {
      event.preventDefault();
      closeContextMenu();
      if (typeof window.tabbyContinueInNewChat === "function") window.tabbyContinueInNewChat();
    });
  }

  document.addEventListener("pointerdown", (event) => {
    if (userMenuOpen && userMenu && !userMenu.contains(event.target)) closeUserMenu();
    if (gpuMenuOpen && gpuMenu && !gpuMenu.contains(event.target)) closeGpuMenu();
    if (contextMenuOpen && contextMenu && !contextMenu.contains(event.target)) closeContextMenu();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (gpuMenuOpen) closeGpuMenu();
    if (userMenuOpen) closeUserMenu();
    if (contextMenuOpen) closeContextMenu();
  });

  TabbyUI.api("auth/check")
    .then((data) => {
      const nameEl = document.getElementById("user-chip-name");
      const name = data.username || data.stack_user || "";
      if (nameEl) nameEl.textContent = name;
      const chip = document.getElementById("user-chip");
      if (chip && name) chip.setAttribute("aria-label", name);
      isAdmin = Boolean(data.is_admin);
      const usersTab = document.getElementById("tab-users");
      const settingsTab = document.getElementById("tab-settings");
      if (usersTab) usersTab.hidden = !isAdmin;
      if (settingsTab) settingsTab.hidden = !isAdmin;
      if (settingsBtn) settingsBtn.hidden = !isAdmin;
      if (settingsItem) settingsItem.hidden = !isAdmin;
      if (restartItem) restartItem.hidden = !isAdmin;
      const hash = (location.hash || "").replace("#", "");
      if (!isAdmin && (hash === "users" || hash === "settings")) {
        location.hash = "#chat";
      }
      show(currentName());
    })
    .catch(() => {});

  let headerTimer = 0;
  let headerFailing = false;

  function kickHeaderStatus(delay) {
    if (headerTimer) clearTimeout(headerTimer);
    headerTimer = setTimeout(refreshHeaderStatus, delay);
  }

  async function refreshHeaderStatus() {
    try {
      const data = await TabbyUI.api("status");
      headerFailing = false;
      TabbyUI.paintGpuChip(statusWithLocalSwitch(data));
    } catch (err) {
      headerFailing = true;
      TabbyUI.paintApiDown(err);
    } finally {
      const data = TabbyUI.lastGpuStatus;
      const switching = gpuSwitchBusy || (data && (data.switching || data.restarting || data.busy));
      const occupied = Boolean(data && data.stack_queue && (data.stack_queue.busy || data.stack_queue.queued));
      kickHeaderStatus(headerFailing ? 3000 : switching || occupied ? 2000 : 15000);
    }
  }
  refreshHeaderStatus();

  window.addEventListener("hashchange", () => {
    const hash = (location.hash || "").replace("#", "");
    if (!isAdmin && (hash === "users" || hash === "settings")) {
      location.hash = "#chat";
      return;
    }
    show(currentName());
  });
  show(currentName());
  if (typeof TABBY_REVEAL_UI === "function") TABBY_REVEAL_UI();
})();
