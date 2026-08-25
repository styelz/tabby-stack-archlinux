(() => {
  const HOVER_WAIT_MS = 420;
  const CHANGE_WAIT_MS = 280;

  function editorBox() {
    return document.querySelector("#chat-editor .chat-files-edit");
  }

  function offsetToPos(text, offset) {
    const slice = String(text || "").slice(0, Math.max(0, offset));
    const lines = slice.split("\n");
    return { line: Math.max(0, lines.length - 1), character: lines[lines.length - 1].length };
  }

  function wsUrl(suffix) {
    const href = new URL(window.TabbyUI.path(suffix), window.location.href);
    href.protocol = href.protocol === "https:" ? "wss:" : "ws:";
    return href.href;
  }

  const state = {
    socket: null,
    chatId: "",
    path: "",
    version: 1,
    req: 0,
    pending: Object.create(null),
    changeTimer: 0,
    hoverTimer: 0,
    popup: null,
    hover: null,
    marks: [],
  };

  function activeChatId() {
    const title = document.querySelector("#chat-title");
    return (window.TabbyUI && window.TabbyUI.activeChatId) || (title && title.dataset.chatId) || "";
  }

  function ensurePopup() {
    if (state.popup) return state.popup;
    const node = document.createElement("div");
    node.className = "chat-lsp-popup";
    node.hidden = true;
    document.body.appendChild(node);
    state.popup = node;
    return node;
  }

  function ensureHover() {
    if (state.hover) return state.hover;
    const node = document.createElement("div");
    node.className = "chat-lsp-hover";
    node.hidden = true;
    document.body.appendChild(node);
    state.hover = node;
    return node;
  }

  function hidePopups() {
    if (state.popup) state.popup.hidden = true;
    if (state.hover) state.hover.hidden = true;
  }

  function connect(chatId) {
    if (!chatId) return;
    if (state.socket && state.chatId === chatId && state.socket.readyState < 2) return;
    resetSocket();
    state.chatId = chatId;
    const socket = new WebSocket(wsUrl(`workspace/${encodeURIComponent(chatId)}/lsp`));
    state.socket = socket;
    socket.onmessage = (event) => {
      let message;
      try {
        message = JSON.parse(event.data);
      } catch {
        return;
      }
      if (!message || typeof message !== "object") return;
      if (message.type === "diagnostics") {
        paintDiagnostics(message.path, message.items || []);
        return;
      }
      const pending = state.pending[message.id];
      if (pending) {
        delete state.pending[message.id];
        pending(message);
      }
    };
    socket.onclose = () => {
      if (state.socket === socket) state.socket = null;
    };
  }

  function resetSocket() {
    if (state.socket) {
      try {
        state.socket.close();
      } catch {
        /* ignore */
      }
    }
    state.socket = null;
    state.pending = Object.create(null);
  }

  function send(payload) {
    if (!state.socket || state.socket.readyState !== 1) return false;
    state.socket.send(JSON.stringify(payload));
    return true;
  }

  function request(payload) {
    return new Promise((resolve) => {
      const id = (state.req += 1);
      state.pending[id] = resolve;
      if (!send(Object.assign({ id }, payload))) {
        delete state.pending[id];
        resolve({ type: "unavailable" });
      }
    });
  }

  function paintDiagnostics(path, items) {
    const box = editorBox();
    const gutter = document.querySelector("#chat-editor .code-edit-gutter");
    if (!box || !gutter) return;
    const tabPath = box.closest("#chat-editor") && document.querySelector(".chat-tab.is-active")
      ? (document.querySelector(".chat-tab.is-active") || {}).title
      : "";
    gutter.querySelectorAll(".chat-lsp-mark").forEach((node) => node.remove());
    const lines = String(box.value || "").split("\n").length;
    (items || []).forEach((item) => {
      const range = item && item.range;
      const line = range && range.start ? Number(range.start.line) + 1 : 0;
      if (!line || line > lines) return;
      const mark = document.createElement("span");
      mark.className = "chat-lsp-mark is-" + (Number(item.severity) === 1 ? "err" : "warn");
      mark.style.top = `${(line - 1) * (parseFloat(getComputedStyle(box).lineHeight) || 18)}px`;
      mark.title = String(item.message || "");
      gutter.appendChild(mark);
    });
  }

  function insertCompletion(item) {
    const box = editorBox();
    if (!box || !item) return;
    const start = box.selectionStart;
    const text = box.value;
    let from = start;
    while (from > 0 && /[\w$.-]/.test(text[from - 1])) from -= 1;
    box.setRangeText(String(item.insert || item.label || ""), from, start, "end");
    box.dispatchEvent(new Event("input", { bubbles: true }));
    hidePopups();
    box.focus();
  }

  async function complete() {
    const box = editorBox();
    if (!box || !state.path) return;
    const pos = offsetToPos(box.value, box.selectionStart);
    const reply = await request({
      type: "completion",
      path: state.path,
      line: pos.line,
      character: pos.character,
    });
    const items = (reply && reply.items) || [];
    const popup = ensurePopup();
    popup.replaceChildren();
    if (!items.length) {
      popup.hidden = true;
      return;
    }
    items.slice(0, 20).forEach((item, idx) => {
      const row = document.createElement("button");
      row.type = "button";
      row.className = "chat-lsp-item" + (idx === 0 ? " is-active" : "");
      row.textContent = item.label + (item.detail ? `  ${item.detail}` : "");
      row.addEventListener("mousedown", (event) => {
        event.preventDefault();
        insertCompletion(item);
      });
      popup.appendChild(row);
    });
    const rect = box.getBoundingClientRect();
    popup.style.left = `${rect.left + 16}px`;
    popup.style.top = `${rect.top + 36}px`;
    popup.hidden = false;
  }

  async function hoverAt(event) {
    const box = editorBox();
    if (!box || !state.path) return;
    const pos = offsetToPos(box.value, box.selectionStart);
    const reply = await request({
      type: "hover",
      path: state.path,
      line: pos.line,
      character: pos.character,
    });
    const text = reply && reply.contents;
    const tip = ensureHover();
    if (!text) {
      tip.hidden = true;
      return;
    }
    tip.textContent = text;
    tip.style.left = `${event.clientX + 12}px`;
    tip.style.top = `${event.clientY + 16}px`;
    tip.hidden = false;
  }

  function bindEditor() {
    const root = document.querySelector("#chat-editor");
    if (!root || root.dataset.lspBound) return;
    root.dataset.lspBound = "1";
    root.addEventListener("mousemove", (event) => {
      if (!event.target.classList.contains("chat-files-edit")) return;
      if (state.hoverTimer) clearTimeout(state.hoverTimer);
      state.hoverTimer = setTimeout(() => hoverAt(event), HOVER_WAIT_MS);
    });
    root.addEventListener("mouseleave", () => {
      if (state.hover) state.hover.hidden = true;
    });
    document.addEventListener("keydown", (event) => {
      if (!state.popup || state.popup.hidden) return;
      if (event.key === "Escape") {
        hidePopups();
        return;
      }
      if (event.key === "Enter") {
        const item = state.popup.querySelector(".chat-lsp-item.is-active");
        if (item) {
          event.preventDefault();
          item.dispatchEvent(new Event("mousedown"));
        }
      }
    });
  }

  window.TabbyLsp = {
    didOpen(path, text) {
      const chatId = (document.querySelector("#chat-shell") || {}).dataset.chatId || state.chatId;
      bindEditor();
      if (!path) return;
      connect(state.chatId || chatId);
      state.path = path;
      state.version += 1;
      send({ type: "didOpen", path, text: String(text || ""), version: state.version });
    },
    didChange(path, text) {
      if (!path) return;
      state.path = path;
      if (state.changeTimer) clearTimeout(state.changeTimer);
      state.changeTimer = setTimeout(() => {
        state.version += 1;
        send({ type: "didChange", path, text: String(text || ""), version: state.version });
      }, CHANGE_WAIT_MS);
    },
    didSave(path, text) {
      if (!path) return;
      send({ type: "didSave", path, text: String(text || "") });
    },
    complete,
    reset() {
      hidePopups();
      resetSocket();
      state.path = "";
      state.chatId = "";
    },
    setChat(chatId) {
      state.chatId = chatId || "";
      if (chatId) connect(chatId);
    },
  };
})();
