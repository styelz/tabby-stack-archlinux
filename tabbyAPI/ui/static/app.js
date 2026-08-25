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
  if (userChip) {
    userChip.addEventListener("contextmenu", (event) => {
      const name = userChip.textContent || "";
      if (!name) return;
      TabbyUI.showContextMenu(event, [
        { label: "Copy username", run: () => TabbyUI.copyText(name) },
      ]);
    });
  }

  document.getElementById("logout-btn").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    if (button.disabled) return;
    button.disabled = true;
    try {
      const response = await fetch(TabbyUI.path("auth/logout"), {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
      });
      if (!response.ok) throw new Error(`Logout failed (${response.status})`);
      TabbyUI.redirectToLogin();
    } catch (err) {
      button.disabled = false;
      console.error(err);
    }
  });

  TabbyUI.api("auth/check")
    .then((data) => {
      const chip = document.getElementById("user-chip");
      if (chip) chip.textContent = data.username || data.stack_user || "";
      isAdmin = Boolean(data.is_admin);
      const tab = document.getElementById("tab-users");
      if (tab) tab.hidden = !isAdmin;
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
