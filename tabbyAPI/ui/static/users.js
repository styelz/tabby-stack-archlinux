function mountUsers(root) {
  root.innerHTML = `
    <div class="users-page">
      <div class="card">
        <h2>Create account</h2>
        <p class="muted">Tabby-only users. They are not Linux accounts. Extra users can use Chat, Status, Gallery, and Logs, but cannot create users.</p>
        <form id="user-create" class="users-form">
          <label>Username
            <input id="new-username" name="username" autocomplete="off" required minlength="3" maxlength="32" />
          </label>
          <label>Password
            <input id="new-password" name="password" type="password" required minlength="8" />
          </label>
          <button class="btn primary" type="submit">Create</button>
        </form>
        <p class="error" id="user-error" hidden></p>
        <p class="muted" id="user-ok" hidden></p>
      </div>
      <div class="card">
        <h2>Accounts</h2>
        <div class="toolbar">
          <button class="btn" type="button" id="users-refresh">Refresh</button>
        </div>
        <table class="users-table">
          <thead>
            <tr><th>Username</th><th>Created</th><th></th></tr>
          </thead>
          <tbody id="users-body"></tbody>
        </table>
        <p class="muted" id="users-empty" hidden>No extra accounts yet.</p>
      </div>
    </div>
  `;
  const form = root.querySelector("#user-create");
  const err = root.querySelector("#user-error");
  const ok = root.querySelector("#user-ok");
  const body = root.querySelector("#users-body");
  const empty = root.querySelector("#users-empty");

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

  async function load() {
    showError("");
    const data = await TabbyUI.api("users");
    const rows = data.users || [];
    empty.hidden = rows.length > 0;
    body.innerHTML = rows
      .map((user) => {
        const name = TabbyUI.escapeHtml(user.username);
        const created = TabbyUI.escapeHtml(user.created_at || "");
        return `<tr data-name="${name}">
          <td>${name}</td>
          <td class="muted">${created}</td>
          <td class="users-actions">
            <button class="btn" type="button" data-reset="${name}">Reset password</button>
            <button class="btn danger" type="button" data-del="${name}">Delete</button>
          </td>
        </tr>`;
      })
      .join("");
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    showError("");
    showOk("");
    try {
      const username = root.querySelector("#new-username").value.trim();
      const password = root.querySelector("#new-password").value;
      await TabbyUI.api("users", { method: "POST", body: { username, password } });
      form.reset();
      showOk(`Created ${username}.`);
      await load();
    } catch (exc) {
      showError(exc.message || "Could not create user.");
    }
  });

  body.addEventListener("click", async (event) => {
    const reset = event.target.closest("[data-reset]");
    const del = event.target.closest("[data-del]");
    try {
      if (reset) {
        const username = reset.dataset.reset;
        const password = window.prompt(`New password for ${username}`);
        if (!password) return;
        await TabbyUI.api(`users/${encodeURIComponent(username)}/password`, {
          method: "POST",
          body: { password },
        });
        showOk(`Password updated for ${username}.`);
      } else if (del) {
        const username = del.dataset.del;
        if (!window.confirm(`Delete ${username}? Their chats are removed. Gallery files stay for admin.`)) return;
        await TabbyUI.api(`users/${encodeURIComponent(username)}`, { method: "DELETE" });
        showOk(`Deleted ${username}.`);
        await load();
      }
    } catch (exc) {
      showError(exc.message || "Request failed.");
    }
  });

  root.querySelector("#users-refresh").addEventListener("click", () => {
    load().catch((exc) => showError(exc.message));
  });

  load().catch((exc) => showError(exc.message));
  return {
    resume() {
      load().catch(() => {});
    },
    destroy() {},
  };
}

window.mountUsers = mountUsers;
