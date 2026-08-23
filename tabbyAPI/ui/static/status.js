function mountStatus(root) {
  root.innerHTML = `
    <div class="toolbar">
      <button class="btn" id="status-refresh">Refresh</button>
      <span class="spacer"></span>
      <span class="muted" id="status-stamp"></span>
    </div>
    <div class="cards" id="status-cards"></div>
    <div class="card metrics-panel" style="margin-top:12px">
      <div class="metrics-head">
        <div>
          <h2>Host graphs</h2>
          <p class="muted">GPU util / VRAM / temp, plus CPU, load, and RAM. Samples every ~30s while TabbyAPI is up.</p>
        </div>
        <div class="metrics-controls">
          <div class="range-presets" role="group" aria-label="Time range">
            <button type="button" class="btn range-btn" data-hours="1">1h</button>
            <button type="button" class="btn range-btn" data-hours="6">6h</button>
            <button type="button" class="btn range-btn is-active" data-hours="24">24h</button>
            <button type="button" class="btn range-btn" data-days="7">7d</button>
            <button type="button" class="btn range-btn" data-days="30">30d</button>
          </div>
          <form class="range-custom" id="metrics-custom">
            <label>Hours <input type="number" id="metrics-hours" min="0.25" max="720" step="0.25" placeholder="e.g. 12" /></label>
            <label>Days <input type="number" id="metrics-days" min="1" max="30" step="1" placeholder="e.g. 3" /></label>
            <button type="submit" class="btn">Apply</button>
          </form>
          <span class="muted" id="metrics-meta"></span>
        </div>
      </div>
      <div class="charts">
        <figure class="chart-card">
          <figcaption>
            <strong>GPU</strong>
            <span class="legend">
              <span class="swatch" style="--c:#7aa2ff"></span>util %
              <span class="swatch" style="--c:#8b5cf6"></span>VRAM %
              <span class="swatch" style="--c:#f5c542"></span>°C
            </span>
          </figcaption>
          <canvas id="chart-gpu" width="900" height="220" aria-label="GPU chart"></canvas>
        </figure>
        <figure class="chart-card">
          <figcaption>
            <strong>Host</strong>
            <span class="legend">
              <span class="swatch" style="--c:#3dd68c"></span>CPU %
              <span class="swatch" style="--c:#ff6b7a"></span>RAM %
              <span class="swatch" style="--c:#9aa3b5"></span>load×10
            </span>
          </figcaption>
          <canvas id="chart-host" width="900" height="220" aria-label="Host chart"></canvas>
        </figure>
      </div>
    </div>
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
  const meta = root.querySelector("#metrics-meta");
  const hoursInput = root.querySelector("#metrics-hours");
  const daysInput = root.querySelector("#metrics-days");
  let range = { hours: 24, days: null };
  let lastSeries = [];

  function card(title, value, extra = "") {
    return `<article class="card"><h2>${TabbyUI.escapeHtml(title)}</h2><div class="stat">${value}</div><div class="muted">${extra}</div></article>`;
  }

  function setActivePreset() {
    root.querySelectorAll(".range-btn").forEach((btn) => {
      const h = btn.dataset.hours ? Number(btn.dataset.hours) : null;
      const d = btn.dataset.days ? Number(btn.dataset.days) : null;
      const on =
        range.days != null
          ? d === range.days
          : h != null && range.hours === h && range.days == null;
      btn.classList.toggle("is-active", on);
    });
  }

  function metricsQuery() {
    if (range.days != null) return `days=${encodeURIComponent(range.days)}`;
    return `hours=${encodeURIComponent(range.hours)}`;
  }

  function formatAxisTime(ts, windowS) {
    const d = new Date(ts * 1000);
    if (windowS > 48 * 3600) {
      return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit" });
    }
    if (windowS > 3 * 3600) {
      return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
    }
    return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  }

  function drawChart(canvas, series, lines, yMaxHint, windowS) {
    const ctx = canvas.getContext("2d");
    const dpr = window.devicePixelRatio || 1;
    const cssW = canvas.clientWidth || 900;
    const cssH = canvas.clientHeight || 220;
    canvas.width = Math.floor(cssW * dpr);
    canvas.height = Math.floor(cssH * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, cssW, cssH);

    const pad = { l: 44, r: 12, t: 14, b: 28 };
    const w = cssW - pad.l - pad.r;
    const h = cssH - pad.t - pad.b;
    ctx.fillStyle = "rgba(255,255,255,0.02)";
    ctx.fillRect(pad.l, pad.t, w, h);

    let yMax = yMaxHint || 100;
    for (const line of lines) {
      for (const row of series) {
        const v = row[line.key];
        if (typeof v === "number" && Number.isFinite(v)) yMax = Math.max(yMax, v);
      }
    }
    yMax = Math.max(1, Math.ceil(yMax / 10) * 10);

    ctx.strokeStyle = "rgba(255,255,255,0.08)";
    ctx.fillStyle = "#9aa3b5";
    ctx.font = "11px ui-monospace, Menlo, Consolas, monospace";
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    for (let i = 0; i <= 4; i++) {
      const y = pad.t + (h * i) / 4;
      const val = Math.round(yMax * (1 - i / 4));
      ctx.beginPath();
      ctx.moveTo(pad.l, y);
      ctx.lineTo(pad.l + w, y);
      ctx.stroke();
      ctx.fillText(String(val), pad.l - 8, y);
    }

    if (!series.length) {
      ctx.textAlign = "center";
      ctx.fillStyle = "#9aa3b5";
      ctx.fillText("Collecting samples… leave Status open or wait ~30s", pad.l + w / 2, pad.t + h / 2);
      return;
    }

    const t0 = series[0].t;
    const t1 = series[series.length - 1].t;
    const span = Math.max(1, t1 - t0);

    function xAt(t) {
      return pad.l + ((t - t0) / span) * w;
    }
    function yAt(v) {
      return pad.t + h * (1 - Math.min(yMax, Math.max(0, v)) / yMax);
    }

    for (const line of lines) {
      const pts = [];
      for (const row of series) {
        const v = row[line.key];
        if (typeof v !== "number" || !Number.isFinite(v)) continue;
        pts.push([xAt(row.t), yAt(line.scale ? v * line.scale : v)]);
      }
      if (pts.length < 2) continue;
      ctx.beginPath();
      ctx.strokeStyle = line.color;
      ctx.lineWidth = 1.8;
      ctx.lineJoin = "round";
      pts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
      ctx.stroke();
    }

    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    ctx.fillStyle = "#9aa3b5";
    const ticks = Math.min(5, series.length);
    for (let i = 0; i < ticks; i++) {
      const row = series[Math.round((i * (series.length - 1)) / Math.max(1, ticks - 1))];
      ctx.fillText(formatAxisTime(row.t, windowS), xAt(row.t), pad.t + h + 8);
    }
  }

  function paintCharts(payload) {
    const series = payload.series || [];
    lastSeries = series;
    const windowS = payload.window_s || range.hours * 3600;
    drawChart(
      root.querySelector("#chart-gpu"),
      series,
      [
        { key: "gpu", color: "#7aa2ff" },
        { key: "vram", color: "#8b5cf6" },
        { key: "temp", color: "#f5c542" },
      ],
      100,
      windowS
    );
    drawChart(
      root.querySelector("#chart-host"),
      series,
      [
        { key: "cpu", color: "#3dd68c" },
        { key: "ram", color: "#ff6b7a" },
        { key: "load1", color: "#9aa3b5", scale: 10 },
      ],
      100,
      windowS
    );
    const hoursLabel = payload.hours >= 24 ? `${payload.days}d` : `${payload.hours}h`;
    meta.textContent = series.length
      ? `${series.length} points · window ${hoursLabel} · sample ~${payload.interval_s || 30}s`
      : `No samples in this window yet (keeps ~30 days).`;
  }

  async function refreshMetrics() {
    const data = await TabbyUI.api(`metrics?${metricsQuery()}&max_points=720`);
    paintCharts(data);
    return data;
  }

  async function refresh() {
    const data = await TabbyUI.api("status");
    const gpu = data.gpu || {};
    const host = data.host || {};
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
      card(
        "CPU / load",
        host.cpu_pct != null ? `${host.cpu_pct}%` : "—",
        host.load1 != null ? `load ${host.load1}` : ""
      ),
      card("RAM", host.ram_pct != null ? `${host.ram_pct}%` : "—", ""),
    ].join("");
    const profiles = data.profiles || [];
    select.innerHTML = profiles.map((name) => `<option value="${TabbyUI.escapeHtml(name)}">${TabbyUI.escapeHtml(name)}</option>`).join("");
    if (data.profile) select.value = data.profile;
    root.querySelector("#status-stamp").textContent = data.now || "";
    TabbyUI.paintGpuChip(data);
    await refreshMetrics().catch((err) => {
      meta.textContent = err.message;
    });
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

  root.querySelectorAll(".range-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.dataset.days) {
        range = { hours: null, days: Number(btn.dataset.days) };
        daysInput.value = String(range.days);
        hoursInput.value = "";
      } else {
        range = { hours: Number(btn.dataset.hours), days: null };
        hoursInput.value = String(range.hours);
        daysInput.value = "";
      }
      setActivePreset();
      refreshMetrics().catch((err) => {
        meta.textContent = err.message;
      });
    });
  });

  root.querySelector("#metrics-custom").addEventListener("submit", (ev) => {
    ev.preventDefault();
    const daysVal = daysInput.value.trim();
    const hoursVal = hoursInput.value.trim();
    if (daysVal) {
      const days = Number(daysVal);
      if (!Number.isFinite(days) || days <= 0) {
        meta.textContent = "Days must be a positive number (max 30).";
        return;
      }
      range = { hours: null, days: Math.min(30, days) };
      daysInput.value = String(range.days);
      hoursInput.value = "";
    } else if (hoursVal) {
      const hours = Number(hoursVal);
      if (!Number.isFinite(hours) || hours <= 0) {
        meta.textContent = "Hours must be a positive number (max 720).";
        return;
      }
      range = { hours: Math.min(720, hours), days: null };
      hoursInput.value = String(range.hours);
      daysInput.value = "";
    } else {
      meta.textContent = "Enter hours or days.";
      return;
    }
    setActivePreset();
    refreshMetrics().catch((err) => {
      meta.textContent = err.message;
    });
  });

  const onResize = () => {
    if (!lastSeries.length) return;
    paintCharts({
      series: lastSeries,
      window_s: range.days != null ? range.days * 86400 : range.hours * 3600,
      hours: range.days != null ? range.days * 24 : range.hours,
      days: range.days != null ? range.days : (range.hours || 0) / 24,
      interval_s: 30,
    });
  };
  window.addEventListener("resize", onResize);

  setActivePreset();
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
      window.removeEventListener("resize", onResize);
    },
  };
}

window.mountStatus = mountStatus;
