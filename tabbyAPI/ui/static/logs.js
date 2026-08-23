function mountLogs(root) {
  root.innerHTML = `
    <div class="toolbar">
      <button class="btn" id="log-pause">Pause</button>
      <button class="btn" id="log-clear">Clear</button>
      <button class="btn" id="log-latest">Jump to latest</button>
      <input class="search" id="log-filter" placeholder="Filter logs" />
      <span class="spacer"></span>
      <span class="muted" id="log-state">connecting…</span>
    </div>
    <pre class="log-view" id="log-view"></pre>
  `;
  const view = root.querySelector("#log-view");
  const state = root.querySelector("#log-state");
  const filter = root.querySelector("#log-filter");
  let paused = false;
  let stick = true;
  let buffer = [];
  let source = null;

  function levelClass(line) {
    if (/\b(ERROR|CRITICAL)\b/i.test(line)) return "lvl-error";
    if (/\bWARN(ING)?\b/i.test(line)) return "lvl-warning";
    if (/\bDEBUG\b/i.test(line)) return "lvl-debug";
    return "lvl-info";
  }

  function render() {
    const q = (filter.value || "").toLowerCase();
    const lines = q ? buffer.filter((line) => line.toLowerCase().includes(q)) : buffer;
    view.innerHTML = lines
      .map((line) => `<span class="${levelClass(line)}">${TabbyUI.escapeHtml(line)}</span>`)
      .join("\n");
    if (stick) view.scrollTop = view.scrollHeight;
  }

  function push(line) {
    buffer.push(line);
    if (buffer.length > 4000) buffer = buffer.slice(-3000);
    if (!paused) render();
  }

  view.addEventListener("scroll", () => {
    stick = view.scrollTop + view.clientHeight >= view.scrollHeight - 24;
  });
  filter.addEventListener("input", render);
  root.querySelector("#log-pause").addEventListener("click", (event) => {
    paused = !paused;
    event.currentTarget.textContent = paused ? "Resume" : "Pause";
    if (!paused) render();
  });
  root.querySelector("#log-clear").addEventListener("click", () => {
    buffer = [];
    render();
  });
  root.querySelector("#log-latest").addEventListener("click", () => {
    stick = true;
    view.scrollTop = view.scrollHeight;
  });

  async function hydrate() {
    try {
      const data = await TabbyUI.api("logs/history?lines=400");
      (data.lines || []).forEach(push);
    } catch (err) {
      push(`history: ${err.message}`);
    }
    source = new EventSource(TabbyUI.path("logs/stream"));
    source.addEventListener("log", (event) => {
      try {
        push(JSON.parse(event.data).line || event.data);
      } catch {
        push(event.data);
      }
    });
    source.onopen = () => {
      state.textContent = "live";
    };
    source.onerror = () => {
      state.textContent = "reconnecting…";
    };
  }

  hydrate();
  return {
    destroy() {
      if (source) source.close();
    },
  };
}

window.mountLogs = mountLogs;
