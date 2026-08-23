function mountChat(root) {
  root.innerHTML = `
    <div class="chat-wrap">
      <div class="toolbar chat-toolbar">
        <button class="btn" type="button" id="chat-new">New chat</button>
        <button class="btn danger" type="button" id="chat-clear">Clear history</button>
        <span class="chat-title" id="chat-title">New chat</span>
        <span class="spacer"></span>
        <span class="muted" id="chat-hint">Tab previous chats · ↑↓ scroll</span>
      </div>
      <div class="chat-log" id="chat-log" tabindex="0"></div>
      <div class="chat-compose">
        <ul class="slash-menu" id="history-menu" hidden></ul>
        <ul class="slash-menu" id="slash-menu" hidden></ul>
        <form class="chat-form" id="chat-form">
          <textarea id="chat-input" rows="2" placeholder="Talk to the loaded model. Type / for commands. Tab loads previous chats."></textarea>
          <button class="btn primary" type="submit">Send</button>
        </form>
      </div>
    </div>
  `;
  const log = root.querySelector("#chat-log");
  const form = root.querySelector("#chat-form");
  const input = root.querySelector("#chat-input");
  const menu = root.querySelector("#slash-menu");
  const historyMenu = root.querySelector("#history-menu");
  const titleEl = root.querySelector("#chat-title");
  const SYSTEM = { role: "system", content: "Console chat. No file tools." };
  const STORAGE_KEY = "tabby-ui-chat-store";
  const MAX_CHATS = 50;

  function newId() {
    if (globalThis.crypto && typeof crypto.randomUUID === "function") return crypto.randomUUID();
    return `c-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }

  function emptyChat() {
    return {
      id: newId(),
      title: "New chat",
      updatedAt: Date.now(),
      messages: [{ ...SYSTEM }],
    };
  }

  function cloneMessages(list) {
    return (Array.isArray(list) ? list : []).map((item) => ({
      role: item.role === "assistant" || item.role === "system" ? item.role : "user",
      content: String(item.content || ""),
    }));
  }

  function titleFromMessages(list) {
    const first = (list || []).find((item) => item.role === "user" && String(item.content || "").trim());
    if (!first) return "New chat";
    return String(first.content).replace(/\s+/g, " ").trim().slice(0, 56);
  }

  function hasUserTurn(chat) {
    return (chat.messages || []).some((item) => item.role === "user" && String(item.content || "").trim());
  }

  function normalizeStore(raw) {
    const chats = [];
    const seen = new Set();
    const incoming = raw && Array.isArray(raw.chats) ? raw.chats : [];
    incoming.forEach((item) => {
      if (!item || typeof item !== "object") return;
      const id = String(item.id || newId());
      if (seen.has(id)) return;
      seen.add(id);
      const messages = cloneMessages(item.messages);
      if (!messages.some((msg) => msg.role === "system")) messages.unshift({ ...SYSTEM });
      chats.push({
        id,
        title: String(item.title || titleFromMessages(messages) || "New chat"),
        updatedAt: Number(item.updatedAt) || Date.now(),
        messages,
      });
    });
    if (!chats.length) chats.push(emptyChat());
    let activeId = String((raw && raw.activeId) || "");
    if (!chats.some((chat) => chat.id === activeId)) activeId = chats[0].id;
    return { version: 1, activeId, chats };
  }

  function readStore() {
    try {
      return normalizeStore(JSON.parse(localStorage.getItem(STORAGE_KEY) || "null"));
    } catch {
      return normalizeStore(null);
    }
  }

  let store = readStore();
  let messages = cloneMessages(store.chats.find((chat) => chat.id === store.activeId).messages);
  const STATIC_COMMANDS = [
    { slash: "/help", send: "help", hint: "Usage guide" },
    { slash: "/list models", send: "list models", hint: "Installed profiles" },
    { slash: "/restart", send: "restart", hint: "Bounce the API" },
    { slash: "/comfy", send: "switch to comfy", hint: "Unload LLM; image gen" },
    { slash: "/flux", send: "switch to flux", hint: "Same as comfy" },
    { slash: "/llm", send: "switch to llm", hint: "Reload last coding model" },
    { slash: "/image", send: "generate an image of ", hint: "Describe a picture", keepOpen: true },
  ];
  let commands = STATIC_COMMANDS.slice();
  let menuItems = [];
  let menuIndex = 0;
  let historyItems = [];
  let historyIndex = 0;

  TabbyUI.api("status")
    .then((data) => {
      const profiles = data.profiles || [];
      const extra = profiles.map((name) => ({
        slash: `/${name}`,
        send: `switch to ${name}`,
        hint: data.profile === name ? "Loaded now" : "Switch model",
      }));
      commands = [...STATIC_COMMANDS.slice(0, 3), ...extra, ...STATIC_COMMANDS.slice(3)];
      if (input.value.startsWith("/")) renderMenu();
    })
    .catch(() => {});

  function activeChat() {
    return store.chats.find((chat) => chat.id === store.activeId);
  }

  function listedChats() {
    const ordered = store.chats
      .filter((chat) => chat.id === store.activeId || hasUserTurn(chat))
      .sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0));
    return ordered;
  }

  function persist() {
    const chat = activeChat();
    if (chat) {
      chat.messages = cloneMessages(messages);
      chat.title = titleFromMessages(chat.messages);
    }
    store.chats = store.chats.filter((item) => item.id === store.activeId || hasUserTurn(item));
    if (store.chats.length > MAX_CHATS) {
      const extras = store.chats
        .filter((item) => item.id !== store.activeId)
        .sort((a, b) => (a.updatedAt || 0) - (b.updatedAt || 0));
      const drop = new Set(extras.slice(0, store.chats.length - MAX_CHATS).map((item) => item.id));
      store.chats = store.chats.filter((item) => !drop.has(item.id));
    }
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(store));
    } catch {
      /* quota — keep working in memory */
    }
    paintToolbar();
  }

  function touchActive() {
    const chat = activeChat();
    if (chat) chat.updatedAt = Date.now();
  }

  function paintToolbar() {
    const chat = activeChat();
    const list = listedChats();
    const idx = Math.max(0, list.findIndex((item) => item.id === store.activeId));
    const title = (chat && chat.title) || "New chat";
    titleEl.textContent = list.length > 1 ? `${idx + 1}/${list.length} · ${title}` : title;
    titleEl.title = title;
  }

  function addBubble(role, text, stick) {
    const node = document.createElement("div");
    node.className = `bubble ${role}`;
    node.innerHTML = TabbyUI.renderMarkdown(text);
    log.appendChild(node);
    if (stick !== false) log.scrollTop = log.scrollHeight;
    return node;
  }

  function renderLog(stickToEnd) {
    log.replaceChildren();
    messages.forEach((item) => {
      if (item.role === "user" || item.role === "assistant") addBubble(item.role, item.content, false);
    });
    if (stickToEnd !== false) log.scrollTop = log.scrollHeight;
  }

  function loadChat(id, stickToEnd) {
    persist();
    const chat = store.chats.find((item) => item.id === id);
    if (!chat) return;
    store.activeId = id;
    messages = cloneMessages(chat.messages);
    if (!messages.some((item) => item.role === "system")) messages.unshift({ ...SYSTEM });
    persist();
    renderLog(stickToEnd !== false);
    input.focus();
  }

  function startNewChat() {
    persist();
    if (!hasUserTurn({ messages })) {
      renderLog();
      input.focus();
      return;
    }
    const chat = emptyChat();
    store.chats.unshift(chat);
    store.activeId = chat.id;
    messages = cloneMessages(chat.messages);
    persist();
    renderLog();
    hideHistoryMenu();
    input.focus();
  }

  function clearHistory() {
    if (store.chats.some(hasUserTurn) || hasUserTurn({ messages })) {
      if (!window.confirm("Delete all saved console chats on this browser?")) return;
    }
    const chat = emptyChat();
    store = { version: 1, activeId: chat.id, chats: [chat] };
    messages = cloneMessages(chat.messages);
    persist();
    renderLog();
    hideHistoryMenu();
    input.focus();
  }

  function hideHistoryMenu() {
    historyMenu.hidden = true;
    historyMenu.replaceChildren();
    historyItems = [];
    historyIndex = 0;
  }

  function renderHistoryMenu() {
    historyItems = listedChats();
    if (historyItems.length < 2) {
      hideHistoryMenu();
      return;
    }
    const current = historyItems.findIndex((item) => item.id === store.activeId);
    historyIndex = current >= 0 ? current : 0;
    const frag = document.createDocumentFragment();
    historyItems.forEach((item, idx) => {
      const li = document.createElement("li");
      li.className = idx === historyIndex ? "is-active" : "";
      const when = timeLabel(item.updatedAt);
      li.innerHTML = `<span class="history-title">${TabbyUI.escapeHtml(item.title || "New chat")}</span><span class="slash-hint">${TabbyUI.escapeHtml(when)}</span>`;
      li.addEventListener("mousedown", (event) => {
        event.preventDefault();
        loadChat(item.id);
        renderHistoryMenu();
      });
      frag.appendChild(li);
    });
    historyMenu.replaceChildren(frag);
    historyMenu.hidden = false;
    const active = historyMenu.querySelector(".is-active");
    if (active && typeof active.scrollIntoView === "function") {
      active.scrollIntoView({ block: "nearest" });
    }
  }

  function timeLabel(ts) {
    const delta = Date.now() - (Number(ts) || 0);
    if (delta < 60_000) return "just now";
    if (delta < 3_600_000) return `${Math.floor(delta / 60_000)}m ago`;
    if (delta < 86_400_000) return `${Math.floor(delta / 3_600_000)}h ago`;
    try {
      return new Date(ts).toLocaleDateString();
    } catch {
      return "";
    }
  }

  function cycleHistory(delta) {
    persist();
    const list = listedChats();
    if (list.length < 2) return false;
    hideMenu();
    let idx = list.findIndex((item) => item.id === store.activeId);
    if (idx < 0) idx = 0;
    idx = (idx + delta + list.length) % list.length;
    loadChat(list[idx].id);
    renderHistoryMenu();
    return true;
  }

  function scrollLog(dir) {
    const amount = Math.max(80, Math.floor(log.clientHeight * 0.7));
    log.scrollBy({ top: dir * amount, behavior: "smooth" });
  }

  function caretAtStart() {
    return input.selectionStart === 0 && input.selectionEnd === 0;
  }

  function caretAtEnd() {
    const n = input.value.length;
    return input.selectionStart === n && input.selectionEnd === n;
  }

  function expandSlash(text) {
    const raw = String(text || "").trim();
    if (!raw.startsWith("/")) return raw;
    const image = raw.match(/^\/image(?:\s+of)?\s+([\s\S]+)$/i);
    if (image) return `generate an image of ${image[1].trim()}`;
    const exact = commands.find((item) => item.slash.toLowerCase() === raw.toLowerCase());
    if (exact && !exact.keepOpen) return exact.send;
    return raw;
  }

  function filteredCommands() {
    const typed = input.value.trim();
    if (!typed.startsWith("/")) return [];
    const q = typed.toLowerCase();
    return commands.filter((item) => item.slash.toLowerCase().startsWith(q) || item.send.toLowerCase().includes(q.slice(1)));
  }

  function hideMenu() {
    menu.hidden = true;
    menu.replaceChildren();
    menuItems = [];
    menuIndex = 0;
  }

  function renderMenu() {
    menuItems = filteredCommands();
    if (!menuItems.length) {
      hideMenu();
      return;
    }
    hideHistoryMenu();
    if (menuIndex >= menuItems.length) menuIndex = 0;
    const frag = document.createDocumentFragment();
    menuItems.forEach((item, idx) => {
      const li = document.createElement("li");
      li.className = idx === menuIndex ? "is-active" : "";
      li.innerHTML = `<span class="slash-cmd">${TabbyUI.escapeHtml(item.slash)}</span><span class="slash-hint">${TabbyUI.escapeHtml(item.hint)}</span>`;
      li.addEventListener("mousedown", (event) => {
        event.preventDefault();
        applyCommand(item, true);
      });
      frag.appendChild(li);
    });
    menu.replaceChildren(frag);
    menu.hidden = false;
  }

  function applyCommand(item, submitAfter) {
    if (item.keepOpen) {
      input.value = item.send;
      hideMenu();
      input.focus();
      input.setSelectionRange(item.send.length, item.send.length);
      return false;
    }
    input.value = item.send;
    hideMenu();
    if (submitAfter) form.requestSubmit();
    return true;
  }

  function consumeSseBuffer(buffer, onDelta) {
    let rest = buffer;
    let idx;
    while ((idx = rest.indexOf("\n\n")) >= 0) {
      const chunk = rest.slice(0, idx);
      rest = rest.slice(idx + 2);
      const dataLines = chunk
        .split("\n")
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trim());
      if (!dataLines.length) continue;
      const payload = dataLines.join("\n");
      if (payload === "[DONE]") continue;
      let json;
      try {
        json = JSON.parse(payload);
      } catch {
        onDelta(payload);
        continue;
      }
      if (json.error) {
        const msg = json.error.message || json.error;
        throw new Error(typeof msg === "string" ? msg : "Chat failed");
      }
      const delta = json.choices?.[0]?.delta?.content || json.choices?.[0]?.message?.content || json.line;
      if (delta) onDelta(delta);
    }
    return rest;
  }

  async function send(text) {
    const outboundText = expandSlash(text);
    messages.push({ role: "user", content: outboundText });
    touchActive();
    persist();
    addBubble("user", outboundText);
    const bubble = addBubble("assistant", "");
    let assembled = "";
    const outbound = messages.filter((m) => m.role !== "system");
    const response = await fetch(TabbyUI.path("chat"), {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream, application/json" },
      body: JSON.stringify({ messages: outbound, stream: true }),
    });
    if (response.status === 401) {
      persist();
      window.location.href = TabbyUI.path("login");
      return;
    }
    const type = response.headers.get("content-type") || "";
    try {
      if (type.includes("application/json")) {
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "Chat failed");
        assembled = data.choices?.[0]?.message?.content || data.message || JSON.stringify(data);
      } else {
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buf = "";
        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          buf += decoder.decode(value, { stream: true });
          buf = consumeSseBuffer(buf, (delta) => {
            assembled += delta;
            bubble.innerHTML = TabbyUI.renderMarkdown(assembled);
            log.scrollTop = log.scrollHeight;
          });
        }
      }
    } catch (err) {
      assembled = assembled || `Error: ${err.message}`;
    }
    bubble.innerHTML = TabbyUI.renderMarkdown(assembled || "(empty reply)");
    messages.push({ role: "assistant", content: assembled });
    persist();
  }

  root.querySelector("#chat-new").addEventListener("click", startNewChat);
  root.querySelector("#chat-clear").addEventListener("click", clearHistory);

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!menu.hidden && menuItems[menuIndex]) {
      if (!applyCommand(menuItems[menuIndex])) return;
    }
    hideHistoryMenu();
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    hideMenu();
    try {
      await send(text);
    } catch (err) {
      addBubble("assistant", `Error: ${err.message}`);
      persist();
    }
  });
  input.addEventListener("input", () => {
    if (input.value.startsWith("/")) {
      hideHistoryMenu();
      renderMenu();
    } else {
      hideMenu();
      if (!historyMenu.hidden && input.value) hideHistoryMenu();
    }
  });
  input.addEventListener("keydown", (event) => {
    if (!menu.hidden && menuItems.length) {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        menuIndex = (menuIndex + 1) % menuItems.length;
        renderMenu();
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        menuIndex = (menuIndex - 1 + menuItems.length) % menuItems.length;
        renderMenu();
        return;
      }
      if (event.key === "Tab") {
        event.preventDefault();
        applyCommand(menuItems[menuIndex], true);
        return;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        hideMenu();
        return;
      }
    }
    if (event.key === "Tab") {
      event.preventDefault();
      cycleHistory(event.shiftKey ? -1 : 1);
      return;
    }
    if (!historyMenu.hidden && (event.key === "Escape" || event.key === "Enter")) {
      event.preventDefault();
      hideHistoryMenu();
      return;
    }
    if (event.key === "ArrowUp" && !event.shiftKey && !event.altKey && !event.ctrlKey && !event.metaKey) {
      if (!input.value || caretAtStart()) {
        event.preventDefault();
        scrollLog(-1);
        return;
      }
    }
    if (event.key === "ArrowDown" && !event.shiftKey && !event.altKey && !event.ctrlKey && !event.metaKey) {
      if (!input.value || caretAtEnd()) {
        event.preventDefault();
        scrollLog(1);
        return;
      }
    }
    if (event.key === "Escape") {
      hideHistoryMenu();
      hideMenu();
      return;
    }
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      form.requestSubmit();
    }
  });

  window.addEventListener("beforeunload", persist);
  renderLog();
  paintToolbar();
  return {
    destroy() {
      persist();
      window.removeEventListener("beforeunload", persist);
    },
  };
}

window.mountChat = mountChat;
