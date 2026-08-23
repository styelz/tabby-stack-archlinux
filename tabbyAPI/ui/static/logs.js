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
  const MAX_LINES = 1200;
  const TRIM_TO = 900;

  let paused = false;
  let active = true;
  let stick = true;
  let buffer = [];
  let source = null;
  let pending = [];
  let raf = 0;
  let filterQ = "";
  let hydrated = false;
  let hydrateBusy = false;

  function levelClass(line) {
    if (/\b(ERROR|CRITICAL)\b/i.test(line)) return "lvl-error";
    if (/\bWARN(ING)?\b/i.test(line)) return "lvl-warning";
    if (/\bDEBUG\b/i.test(line)) return "lvl-debug";
    return "lvl-info";
  }

  function makeLineNode(line) {
    const span = document.createElement("span");
    span.className = levelClass(line);
    span.textContent = line;
    return span;
  }

  function trimBuffer() {
    if (buffer.length <= MAX_LINES) return 0;
    const drop = buffer.length - TRIM_TO;
    buffer.splice(0, drop);
    return drop;
  }

  function trimView(drop) {
    if (!drop || filterQ) return;
    // Each line is a <span> plus a newline text node.
    let remove = drop * 2;
    while (remove > 0 && view.firstChild) {
      view.removeChild(view.firstChild);
      remove -= 1;
    }
  }

  function renderFull() {
    const frag = document.createDocumentFragment();
    const lines = filterQ
      ? buffer.filter((line) => line.toLowerCase().includes(filterQ))
      : buffer;
    for (const line of lines) {
      frag.appendChild(makeLineNode(line));
      frag.appendChild(document.createTextNode("\n"));
    }
    view.replaceChildren(frag);
    if (stick) view.scrollTop = view.scrollHeight;
  }

  function appendVisible(lines) {
    if (!lines.length) return;
    if (filterQ) {
      const matched = lines.filter((line) => line.toLowerCase().includes(filterQ));
      if (!matched.length) return;
      const frag = document.createDocumentFragment();
      for (const line of matched) {
        frag.appendChild(makeLineNode(line));
        frag.appendChild(document.createTextNode("\n"));
      }
      view.appendChild(frag);
    } else {
      const frag = document.createDocumentFragment();
      for (const line of lines) {
        frag.appendChild(makeLineNode(line));
        frag.appendChild(document.createTextNode("\n"));
      }
      view.appendChild(frag);
    }
    if (stick) view.scrollTop = view.scrollHeight;
  }

  function flush() {
    raf = 0;
    if (!pending.length) return;
    const batch = pending;
    pending = [];
    buffer.push(...batch);
    const drop = trimBuffer();
    if (!active || paused) {
      return;
    }
    if (filterQ) {
      // Filtering needs a full pass when the query is set; keep it cheap by
      // only rebuilding when the user is watching.
      appendVisible(batch);
      return;
    }
    trimView(drop);
    appendVisible(batch);
  }

  function queue(line) {
    if (!line && line !== "") return;
    pending.push(line);
    if (!raf) raf = requestAnimationFrame(flush);
  }

  function disconnect() {
    if (source) {
      source.close();
      source = null;
    }
    if (raf) {
      cancelAnimationFrame(raf);
      raf = 0;
    }
    if (pending.length) {
      buffer.push(...pending);
      pending = [];
      trimBuffer();
    }
  }

  function connect() {
    if (source || !active) return;
    state.textContent = "connecting…";
    source = new EventSource(TabbyUI.path("logs/stream"));
    source.addEventListener("log", (event) => {
      try {
        queue(JSON.parse(event.data).line || event.data);
      } catch {
        queue(event.data);
      }
    });
    source.onopen = () => {
      state.textContent = paused ? "paused" : "live";
      if (!hydrated) loadHistory();
    };
    source.onerror = () => {
      state.textContent = active ? "reconnecting…" : "idle";
    };
  }

  view.addEventListener("scroll", () => {
    stick = view.scrollTop + view.clientHeight >= view.scrollHeight - 24;
  }, { passive: true });

  let filterTimer = 0;
  filter.addEventListener("input", () => {
    filterQ = (filter.value || "").toLowerCase();
    if (filterTimer) clearTimeout(filterTimer);
    filterTimer = setTimeout(() => {
      filterTimer = 0;
      renderFull();
    }, 120);
  });

  root.querySelector("#log-pause").addEventListener("click", (event) => {
    paused = !paused;
    event.currentTarget.textContent = paused ? "Resume" : "Pause";
    if (paused) {
      disconnect();
      state.textContent = "paused";
    } else {
      connect();
      renderFull();
    }
  });
  root.querySelector("#log-clear").addEventListener("click", () => {
    buffer = [];
    pending = [];
    view.replaceChildren();
  });
  root.querySelector("#log-latest").addEventListener("click", () => {
    stick = true;
    view.scrollTop = view.scrollHeight;
  });

  async function loadHistory() {
    if (hydrateBusy || hydrated) return;
    hydrateBusy = true;
    try {
      const data = await TabbyUI.api("logs/history?lines=300");
      const lines = Array.isArray(data.lines) ? data.lines.slice(-MAX_LINES) : [];
      hydrated = true;
      if (!buffer.length) {
        buffer = lines;
        renderFull();
      }
    } catch {
      if (!buffer.length) state.textContent = "waiting for API…";
    } finally {
      hydrateBusy = false;
    }
  }

  loadHistory().then(() => {
    if (active && !paused) connect();
  });

  function onVisibility() {
    if (document.hidden) {
      if (source) {
        disconnect();
        state.textContent = "idle";
      }
    } else if (active && !paused) {
      connect();
    }
  }
  document.addEventListener("visibilitychange", onVisibility);

  return {
    pause() {
      active = false;
      disconnect();
      state.textContent = "idle";
    },
    resume() {
      active = true;
      if (!paused && !document.hidden) connect();
    },
    destroy() {
      active = false;
      disconnect();
      document.removeEventListener("visibilitychange", onVisibility);
      if (filterTimer) clearTimeout(filterTimer);
    },
  };
}

window.mountLogs = mountLogs;
