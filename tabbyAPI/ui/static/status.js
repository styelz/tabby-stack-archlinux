function mountStatus(root) {
  root.innerHTML = `
    <div class="toolbar">
      <button class="btn" id="status-refresh">Refresh</button>
      <span class="spacer"></span>
      <span class="muted" id="status-stamp"></span>
    </div>
    <div class="cards" id="status-cards"></div>
    <div class="card" style="margin-top:12px">
      <h2>Actions</h2>
      <p class="muted">Restart bounces TabbyAPI (and Comfy if it owns the GPU). Update runs update.sh from the stack root.</p>
      <div class="row">
        <select id="profile-select"></select>
        <button class="btn" id="switch-llm">Load LLM</button>
        <button class="btn" id="switch-comfy">Hand GPU to Comfy</button>
        <button class="btn danger" id="restart-btn">Restart stack</button>
        <button class="btn" id="update-git">Update git</button>
        <button class="btn" id="update-all">Update all</button>
      </div>
      <p class="muted" id="action-msg"></p>
    </div>
  `;
  const cards = root.querySelector("#status-cards");
  const select = root.querySelector("#profile-select");
  const msg = root.querySelector("#action-msg");

  function card(title, value, extra = "") {
    return `<article class="card"><h2>${TabbyUI.escapeHtml(title)}</h2><div class="stat">${value}</div><div class="muted">${extra}</div></article>`;
  }

  async function refresh() {
    const data = await TabbyUI.api("status");
    const gpu = data.gpu || {};
    const model = data.model || {};
    const health = data.health || {};
    cards.innerHTML = [
      card("GPU mode", data.gpu_mode || "unknown", data.comfy_up ? "Comfy is up" : "Comfy idle"),
      card("Profile", data.profile || "—", data.tabby_model || "LLM unloaded"),
      card("Context", model.max_seq_len || "—", model.cache_mode ? `cache ${model.cache_mode}` : ""),
      card("Health", health.healthy ? "healthy" : "unhealthy", (health.issues || []).join("; ") || "no issues"),
      card("Uptime", TabbyUI.formatDuration(data.uptime_s), data.api_base || ""),
      card(
        "NVIDIA",
        gpu.name || "n/a",
        gpu.memory_total_mib
          ? `${gpu.memory_used_mib} / ${gpu.memory_total_mib} MiB · ${gpu.utilization_pct}% · ${gpu.temperature_c}°C`
          : ""
      ),
    ].join("");
    const profiles = data.profiles || [];
    select.innerHTML = profiles.map((name) => `<option value="${TabbyUI.escapeHtml(name)}">${TabbyUI.escapeHtml(name)}</option>`).join("");
    if (data.profile) select.value = data.profile;
    root.querySelector("#status-stamp").textContent = data.now || "";
    const chip = document.getElementById("gpu-chip");
    if (chip) {
      chip.textContent = `${(data.gpu_mode || "gpu").toUpperCase()} · ${data.profile || data.tabby_model || "idle"}`;
      chip.className = "chip" + (data.gpu_mode === "llm" ? " ok" : " warn");
    }
    return data;
  }

  async function act(fn) {
    msg.textContent = "Working…";
    try {
      const result = await fn();
      msg.textContent = result.message || result.detail || "Done.";
      await refresh();
    } catch (err) {
      msg.textContent = err.message;
    }
  }

  root.querySelector("#status-refresh").addEventListener("click", () => refresh().catch((err) => (msg.textContent = err.message)));
  root.querySelector("#switch-llm").addEventListener("click", () =>
    act(() => TabbyUI.api("gpu", { method: "POST", body: { mode: select.value || "llm" } }))
  );
  root.querySelector("#switch-comfy").addEventListener("click", () =>
    act(() => TabbyUI.api("gpu", { method: "POST", body: { mode: "comfy" } }))
  );
  root.querySelector("#restart-btn").addEventListener("click", () => {
    if (!confirm("Restart TabbyAPI now? The UI will drop for about a minute.")) return;
    act(() => TabbyUI.api("restart", { method: "POST", body: {} }));
  });
  root.querySelector("#update-git").addEventListener("click", () => {
    if (!confirm("Run update.sh --git --restart?")) return;
    act(() => TabbyUI.api("update", { method: "POST", body: { full: false } }));
  });
  root.querySelector("#update-all").addEventListener("click", () => {
    if (!confirm("Run a full update (git + deps) and restart?")) return;
    act(() => TabbyUI.api("update", { method: "POST", body: { full: true } }));
  });

  refresh().catch((err) => {
    msg.textContent = err.message;
  });
  let timer = setInterval(() => refresh().catch(() => {}), 15000);
  return {
    pause() {
      if (timer) {
        clearInterval(timer);
        timer = 0;
      }
    },
    resume() {
      if (!timer) {
        refresh().catch(() => {});
        timer = setInterval(() => refresh().catch(() => {}), 15000);
      }
    },
    destroy() {
      if (timer) clearInterval(timer);
      timer = 0;
    },
  };
}

window.mountStatus = mountStatus;
