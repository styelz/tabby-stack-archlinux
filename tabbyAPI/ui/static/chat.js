function tabbyChatComposeAction(inFlight, typed, queued) {
  const text = String(typed || "").trim();
  const hasQueue = Boolean(String(queued || "").trim());
  if (!inFlight) return { mode: "send", label: "Send", showSteer: false };
  if (text) return { mode: "queue", label: "Queue", showSteer: hasQueue };
  return { mode: "stop", label: "Stop", showSteer: hasQueue };
}

function tabbyLooksLikeChatNotImage(raw) {
  const text = String(raw || "").trim();
  if (!text) return false;
  if (/^qwen-image:/i.test(text)) return false;
  if (/^(?:please\s+)?(?:can you\s+|could you\s+)?(?:generate|draw|imagine|create|make|render)\b/i.test(text)) {
    return false;
  }
  const asksImage = /\b(?:images?|pictures?|photos?|pics?|posters?|logos?|icons?|banners?|pngs?)\b/i.test(text);
  const question = /^(?:what(?:'s|s)?|why|who|when|where|which|how\s+(?:are|do|does|did|can|to|is|come))\b/i.test(text);
  if (asksImage && !question) return false;
  return (
    /^(?:hi|hello|hey|yo|sup|thanks|thank you|thx|good (?:morning|afternoon|evening)|ok(?:ay)?|sure|yes|no|yep|nope|got it|cool|great)(?:\s|[!.]|$)/i.test(text)
    || /^(?:please\s+)?(?:tell me|explain|help(?:\s+me)?)\b/i.test(text)
    || /^(?:i(?:'m|m)?\s+(?:just\s+)?(?:have|need|want|think|wonder)|i have a question)\b/i.test(text)
    || /^(?:what(?:'s|s)?|why|who|when|where|which)\b/i.test(text)
    || /^(?:is|are|do|does|did|am)\s+(?:the|this|that|it|there|you|we|they|i|these|those)\b/i.test(text)
    || /^(?:can|could|would|should|will)\s+you\s+(?:explain|tell|help|show me how)\b/i.test(text)
    || /^how\s+(?:are|do|does|did|can|to|is|come)\b/i.test(text)
  );
}

function mountChat(root) {
  root.innerHTML = `
    <div class="chat-shell" id="chat-shell">
      <button type="button" class="chat-backdrop" id="chat-backdrop" hidden aria-label="Close chats"></button>
      <aside class="chat-sidebar" id="chat-sidebar">
        <div class="chat-side-head">
          <button class="btn primary" type="button" id="chat-new">New chat</button>
        </div>
        <div class="chat-side-search">
          <input id="chat-search" type="search" placeholder="Search chats" autocomplete="off" />
        </div>
        <div class="chat-nav-list" id="chat-nav-list"></div>
        <div class="chat-side-foot">
          <button class="btn danger" type="button" id="chat-clear">Clear history</button>
        </div>
      </aside>
      <div class="chat-wrap">
        <div class="toolbar chat-toolbar">
          <button class="btn ghost chat-icon" type="button" id="chat-sidebar-toggle" aria-label="Hide sidebar" title="Hide sidebar">‹</button>
          <span class="chat-title" id="chat-title">New chat</span>
          <div class="chat-mode" id="chat-mode" role="group" aria-label="Chat mode">
            <button type="button" class="chat-mode-btn is-active" data-mode="chat">Chat</button>
            <button type="button" class="chat-mode-btn" data-mode="code">Code</button>
          </div>
          <span class="spacer"></span>
          <span class="muted" id="chat-hint">Tab chats · ↑↓ recall · Enter send</span>
          <div class="chat-more">
            <button class="btn ghost" type="button" id="chat-more" aria-haspopup="true" aria-expanded="false">More</button>
            <div class="chat-more-menu" id="chat-more-menu" hidden>
              <button type="button" data-more="rename">Rename</button>
              <button type="button" data-more="pin">Pin</button>
              <button type="button" data-more="export">Export markdown</button>
              <button type="button" data-more="copy">Copy conversation</button>
              <button type="button" data-more="regen">Regenerate last reply</button>
              <button type="button" data-more="settings">Sampling</button>
              <button type="button" data-more="keys">Keyboard shortcuts</button>
              <button type="button" data-more="sidebar">Hide sidebar</button>
              <button type="button" data-more="delete">Delete this chat</button>
            </div>
          </div>
        </div>
        <div class="chat-log-wrap">
          <div class="chat-empty" id="chat-empty" hidden>
            <h2 id="chat-empty-title">Console chat</h2>
            <p id="chat-empty-copy">Talk to the loaded model. Slash commands switch models and start pictures. Pasted images stay on this host.</p>
            <div class="chat-suggests" id="chat-suggests">
              <button type="button" data-suggest="help">Usage guide</button>
              <button type="button" data-suggest="list models">List models</button>
              <button type="button" data-suggest="What model is loaded?">What's loaded?</button>
              <button type="button" data-suggest="generate an image of a harbor at dusk">Harbor at dusk</button>
            </div>
          </div>
          <div class="chat-log" id="chat-log"></div>
          <button class="btn chat-jump" type="button" id="chat-jump" hidden>Return to bottom</button>
        </div>
        <div class="chat-compose">
          <ul class="slash-menu" id="history-menu" hidden></ul>
          <ul class="slash-menu" id="slash-menu" hidden></ul>
          <div class="chat-edit-bar" id="chat-edit-bar" hidden>
            <span>Editing a sent message. Send replaces that turn.</span>
            <button class="btn ghost" type="button" id="chat-edit-cancel">Cancel</button>
          </div>
          <div class="chat-attach" id="chat-attach" hidden>
            <img id="chat-attach-img" alt="" />
            <span class="chat-attach-name" id="chat-attach-name"></span>
            <button class="btn ghost chat-queue-clear" type="button" id="chat-attach-clear" aria-label="Remove image">×</button>
          </div>
          <div class="chat-queue" id="chat-queue" hidden>
            <span class="chat-queue-mark">Queued</span>
            <span class="chat-queue-text" id="chat-queue-text"></span>
            <button class="btn" type="button" id="chat-steer" hidden>Steer</button>
            <button class="btn ghost chat-queue-clear" type="button" id="chat-queue-clear" aria-label="Remove queued message">×</button>
          </div>
          <div class="chat-loading" id="chat-loading" hidden>
            <span class="chat-loading-mark">Loading</span>
            <span class="chat-loading-text" id="chat-loading-text">The model is loading. Chat is paused until it is ready.</span>
            <span class="chat-loading-time" id="chat-loading-time"></span>
          </div>
          <div class="chat-comfy-hint" id="chat-comfy-hint" hidden>
            <span class="chat-comfy-hint-mark">Comfy</span>
            <span class="chat-comfy-hint-text" id="chat-comfy-hint-text">This looks like a chat, not a picture. Switch to the coding model?</span>
            <button class="btn primary" type="button" id="chat-switch-llm">Switch to LLM</button>
          </div>
          <form class="chat-form" id="chat-form">
            <textarea id="chat-input" rows="3" placeholder="Talk to the loaded model. Type / for commands. ↑↓ recalls what you sent."></textarea>
            <input id="chat-file" type="file" accept="image/png,image/jpeg,image/webp,image/gif" hidden />
            <div class="chat-form-actions">
              <button class="btn ghost chat-icon" type="button" id="chat-attach-btn" aria-label="Attach image" title="Attach image">📎</button>
              <button class="btn ghost chat-icon" type="button" id="chat-mic" hidden aria-label="Voice input" title="Voice input">🎤</button>
              <span id="chat-count"></span>
              <span class="chat-keys"><kbd>Enter</kbd> send · <kbd>Shift</kbd>+<kbd>Enter</kbd> line · <kbd>Esc</kbd> close</span>
              <button class="btn primary chat-send" type="submit" id="chat-send">Send</button>
            </div>
          </form>
        </div>
      </div>
      <aside class="chat-files" id="chat-files" hidden>
        <div class="chat-files-head">
          <span>Files</span>
          <span class="chat-files-count" id="chat-files-count"></span>
          <span class="spacer"></span>
          <button class="btn ghost chat-icon" type="button" id="chat-files-refresh" aria-label="Refresh files" title="Refresh files">⟳</button>
          <button class="btn" type="button" id="chat-files-site">Open site</button>
          <button class="btn ghost" type="button" id="chat-files-zip">Zip</button>
          <button class="btn ghost" type="button" id="chat-files-clear">Clear</button>
        </div>
        <div class="chat-files-tree" id="chat-files-tree"></div>
        <div class="chat-files-preview" id="chat-files-preview">
          <p class="muted">Select a file</p>
        </div>
      </aside>
    </div>
  `;
  const shell = root.querySelector("#chat-shell");
  const log = root.querySelector("#chat-log");
  const emptyEl = root.querySelector("#chat-empty");
  const jumpBtn = root.querySelector("#chat-jump");
  const form = root.querySelector("#chat-form");
  const input = root.querySelector("#chat-input");
  const sendBtn = root.querySelector("#chat-send");
  const queueBar = root.querySelector("#chat-queue");
  const queueTextEl = root.querySelector("#chat-queue-text");
  const steerBtn = root.querySelector("#chat-steer");
  const queueClearBtn = root.querySelector("#chat-queue-clear");
  const navList = root.querySelector("#chat-nav-list");
  const searchEl = root.querySelector("#chat-search");
  const moreBtn = root.querySelector("#chat-more");
  const moreMenu = root.querySelector("#chat-more-menu");
  const editBar = root.querySelector("#chat-edit-bar");
  const attachBar = root.querySelector("#chat-attach");
  const attachImg = root.querySelector("#chat-attach-img");
  const attachName = root.querySelector("#chat-attach-name");
  const fileInput = root.querySelector("#chat-file");
  const micBtn = root.querySelector("#chat-mic");
  const countEl = root.querySelector("#chat-count");
  const loadingBar = root.querySelector("#chat-loading");
  const loadingTextEl = root.querySelector("#chat-loading-text");
  const loadingTimeEl = root.querySelector("#chat-loading-time");
  const comfyHint = root.querySelector("#chat-comfy-hint");
  const switchLlmBtn = root.querySelector("#chat-switch-llm");
  const filesPane = root.querySelector("#chat-files");
  const filesTree = root.querySelector("#chat-files-tree");
  const filesPreview = root.querySelector("#chat-files-preview");
  const filesZipBtn = root.querySelector("#chat-files-zip");
  const filesClearBtn = root.querySelector("#chat-files-clear");
  const filesRefreshBtn = root.querySelector("#chat-files-refresh");
  const filesCountEl = root.querySelector("#chat-files-count");
  const filesSiteBtn = root.querySelector("#chat-files-site");
  const DEFAULT_PLACEHOLDER = input.getAttribute("placeholder") || "";
  let filesListing = [];
  let filesSelected = "";
  let filesEntry = "";
  let previewPath = "";
  let previewChat = "";
  let previewSize = -1;
  let previewOriginal = null;
  let previewDirty = false;
  let previewBusy = false;
  const menu = root.querySelector("#slash-menu");
  const historyMenu = root.querySelector("#history-menu");
  const titleEl = root.querySelector("#chat-title");
  const SYSTEM = { role: "system", content: "Console chat. No file tools." };
  const CODE_PLACEHOLDER = "Describe the page or files to create. They land in Files; download a zip when you want a copy.";
  const STORAGE_KEY = "tabby-ui-chat-store";
  const SETTINGS_KEY = "tabby-ui-chat-settings";
  const SIDEBAR_KEY = "tabby-ui-chat-sidebar";
  const MAX_CHATS = 50;

  function newId() {
    if (globalThis.crypto && typeof crypto.randomUUID === "function") return crypto.randomUUID();
    return `c-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }

  function emptyChat(mode) {
    return {
      id: newId(),
      title: "New chat",
      updatedAt: Date.now(),
      pinned: false,
      titleLocked: false,
      mode: mode === "code" ? "code" : "chat",
      messages: [{ ...SYSTEM }],
    };
  }

  function chatMode(chat) {
    return chat && chat.mode === "code" ? "code" : "chat";
  }

  function activeMode() {
    return chatMode(activeChat());
  }

  function cloneMessages(list) {
    return (Array.isArray(list) ? list : []).map((item) => {
      const out = {
        role: item.role === "assistant" || item.role === "system" ? item.role : "user",
        content: String(item.content || ""),
      };
      if (out.role === "assistant" && item.reasoning) {
        out.reasoning = String(item.reasoning);
      }
      if (out.role === "assistant") {
        const elapsed = Number(item.elapsed_s);
        if (Number.isFinite(elapsed) && elapsed > 0) out.elapsed_s = Math.round(elapsed);
        if (item.status_label) out.status_label = String(item.status_label);
      }
      if (item.createdAt) out.createdAt = Number(item.createdAt) || 0;
      if (item.imageData && String(item.imageData).startsWith("data:image")) {
        out.imageData = String(item.imageData);
      }
      if (item.imagePreview) out.imagePreview = String(item.imagePreview);
      if (item.imageName) out.imageName = String(item.imageName);
      return out;
    });
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
        pinned: Boolean(item.pinned),
        titleLocked: Boolean(item.titleLocked),
        mode: item.mode === "code" ? "code" : "chat",
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

  let persistReady = false;
  let store = normalizeStore(null);
  let messages = cloneMessages(store.chats.find((chat) => chat.id === store.activeId).messages);
  let pendingEditIndex = -1;
  let pendingImage = null;
  let renaming = false;
  let settings = { temperature: null };
  try {
    const raw = JSON.parse(localStorage.getItem(SETTINGS_KEY) || "null");
    if (raw && typeof raw === "object" && (raw.temperature == null || Number.isFinite(Number(raw.temperature)))) {
      settings.temperature = raw.temperature == null ? null : Number(raw.temperature);
    }
  } catch {
    /* ignore */
  }
  try {
    if (localStorage.getItem(SIDEBAR_KEY) === "hidden") {
      shell.classList.add("is-sidebar-hidden");
    }
  } catch {
    /* ignore */
  }
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
  let recallIndex = -1;
  let recallDraft = "";

  TabbyUI.api("status")
    .then((data) => {
      rememberGpu(data);
      const profiles = data.profiles || [];
      const extra = profiles.map((name) => ({
        slash: `/${name}`,
        send: `switch to ${name}`,
        hint: data.profile === name ? "Loaded now" : "Switch model",
      }));
      commands = [...STATIC_COMMANDS.slice(0, 3), ...extra, ...STATIC_COMMANDS.slice(3)];
      if (input.value.startsWith("/")) renderMenu();
      paintCompose();
    })
    .catch(() => {});

  function activeChat() {
    return store.chats.find((chat) => chat.id === store.activeId);
  }

  function listedChats() {
    const q = String((searchEl && searchEl.value) || "").trim().toLowerCase();
    return store.chats
      .filter((chat) => chat.id === store.activeId || hasUserTurn(chat))
      .filter((chat) => {
        if (!q) return true;
        if (String(chat.title || "").toLowerCase().includes(q)) return true;
        return (chat.messages || []).some((msg) => String(msg.content || "").toLowerCase().includes(q));
      })
      .sort((a, b) => {
        const pin = Number(Boolean(b.pinned)) - Number(Boolean(a.pinned));
        if (pin) return pin;
        return (b.updatedAt || 0) - (a.updatedAt || 0);
      });
  }

  function persist() {
    const chat = activeChat();
    if (chat) {
      chat.messages = cloneMessages(messages);
      if (!chat.titleLocked) chat.title = titleFromMessages(chat.messages);
    }
    const before = new Set(store.chats.map((item) => item.id));
    store.chats = store.chats.filter((item) => item.id === store.activeId || hasUserTurn(item) || item.pinned);
    if (store.chats.length > MAX_CHATS) {
      const extras = store.chats
        .filter((item) => item.id !== store.activeId && !item.pinned)
        .sort((a, b) => (a.updatedAt || 0) - (b.updatedAt || 0));
      const drop = new Set(extras.slice(0, store.chats.length - MAX_CHATS).map((item) => item.id));
      store.chats = store.chats.filter((item) => !drop.has(item.id));
    }
    const kept = new Set(store.chats.map((item) => item.id));
    paintToolbar();
    renderSidebar();
    if (!persistReady) return;
    before.forEach((id) => {
      if (!kept.has(id)) dropWorkspace(id);
    });
    TabbyUI.api("chats", { method: "PUT", body: store }).catch(() => {});
  }

  function touchActive() {
    const chat = activeChat();
    if (chat) chat.updatedAt = Date.now();
  }

  function paintToolbar() {
    const chat = activeChat();
    const title = (chat && chat.title) || "New chat";
    if (!renaming) {
      titleEl.textContent = title;
      titleEl.title = "Click to rename";
    }
    const pinBtn = moreMenu && moreMenu.querySelector('[data-more="pin"]');
    if (pinBtn) pinBtn.textContent = chat && chat.pinned ? "Unpin" : "Pin";
    const sideBtn = moreMenu && moreMenu.querySelector('[data-more="sidebar"]');
    if (sideBtn) {
      sideBtn.textContent = shell.classList.contains("is-sidebar-hidden") ? "Show sidebar" : "Hide sidebar";
    }
    const toggleBtn = root.querySelector("#chat-sidebar-toggle");
    if (toggleBtn) {
      const hidden = isNarrowChat()
        ? !shell.classList.contains("is-sidebar-open")
        : shell.classList.contains("is-sidebar-hidden");
      toggleBtn.textContent = hidden ? "›" : "‹";
      toggleBtn.setAttribute("aria-label", hidden ? "Show sidebar" : "Hide sidebar");
      toggleBtn.title = hidden ? "Show sidebar" : "Hide sidebar";
    }
    paintMode();
    paintEmpty();
  }

  function paintMode() {
    const mode = activeMode();
    shell.classList.toggle("is-code", mode === "code");
    root.querySelectorAll(".chat-mode-btn").forEach((btn) => {
      const on = btn.dataset.mode === mode;
      btn.classList.toggle("is-active", on);
      btn.setAttribute("aria-pressed", on ? "true" : "false");
    });
    if (filesPane) filesPane.hidden = mode !== "code";
    const hint = root.querySelector("#chat-hint");
    if (hint) {
      hint.textContent = mode === "code"
        ? "Code mode · files stay on this host · zip from Files"
        : "Tab chats · ↑↓ recall · Enter send";
    }
  }

  function setChatMode(mode) {
    const next = mode === "code" ? "code" : "chat";
    const chat = activeChat();
    if (!chat || chatMode(chat) === next) return;
    chat.mode = next;
    touchActive();
    persist();
    paintCompose();
    filesSelected = "";
    refreshFiles();
  }

  function renderSidebar() {
    if (!navList) return;
    const list = listedChats();
    if (!list.length) {
      navList.innerHTML = '<div class="chat-nav-empty">No chats match.</div>';
      return;
    }
    const frag = document.createDocumentFragment();
    list.forEach((item) => {
      const btn = document.createElement("div");
      btn.className = "chat-nav" + (item.id === store.activeId ? " is-active" : "") + (item.pinned ? " is-pinned" : "");
      btn.dataset.id = item.id;
      btn.setAttribute("role", "button");
      btn.tabIndex = 0;
      const tag = chatMode(item) === "code" ? '<span class="chat-nav-tag">Code</span>' : "";
      btn.innerHTML =
        `<span class="chat-nav-pin" aria-hidden="true">${item.pinned ? "★" : "☆"}</span>` +
        `<span class="chat-nav-title">${TabbyUI.escapeHtml(item.title || "New chat")}</span>` +
        `<span class="chat-nav-when">${tag}${TabbyUI.escapeHtml(timeLabel(item.updatedAt))}</span>` +
        `<span class="chat-nav-tools">` +
        `<button type="button" class="btn ghost chat-icon" data-nav="pin" aria-label="${item.pinned ? "Unpin" : "Pin"}">★</button>` +
        `<button type="button" class="btn ghost chat-icon" data-nav="rename" aria-label="Rename">✎</button>` +
        `<button type="button" class="btn ghost chat-icon danger" data-nav="delete" aria-label="Delete chat">×</button>` +
        `</span>`;
      frag.appendChild(btn);
    });
    navList.replaceChildren(frag);
  }

  function paintEmpty() {
    if (!emptyEl) return;
    const empty = !messages.some((item) => item.role !== "system" && String(item.content || "").trim());
    emptyEl.hidden = !empty;
    if (!empty) return;
    const code = activeMode() === "code";
    const title = emptyEl.querySelector("#chat-empty-title");
    const copy = emptyEl.querySelector("#chat-empty-copy");
    const suggests = emptyEl.querySelector("#chat-suggests");
    if (title) title.textContent = code ? "Code mode" : "Console chat";
    if (copy) {
      copy.textContent = code
        ? "Ask for a page, logo, or set of files. The model writes them into this chat's Files pane. Images also show in Gallery. Download a zip when you want a copy."
        : "Talk to the loaded model. Slash commands switch models and start pictures. Pasted images stay on this host.";
    }
    if (suggests) {
      suggests.innerHTML = code
        ? '<button type="button" data-suggest="Create a simple landing page with a logo and a header photo">Landing page</button>' +
          '<button type="button" data-suggest="qwen-image: a logo that says Cafe">Cafe logo</button>' +
          '<button type="button" data-suggest="Write a small HTML/CSS/JS todo app">Todo app</button>'
        : '<button type="button" data-suggest="help">Usage guide</button>' +
          '<button type="button" data-suggest="list models">List models</button>' +
          '<button type="button" data-suggest="What model is loaded?">What\'s loaded?</button>' +
          '<button type="button" data-suggest="generate an image of a harbor at dusk">Harbor at dusk</button>';
    }
  }

  function dropWorkspace(chatId) {
    if (!chatId) return;
    TabbyUI.api(`workspace/${encodeURIComponent(chatId)}`, { method: "DELETE" }).catch(() => {});
  }

  function fileUrl(chatId, path) {
    return TabbyUI.path(`workspace/${encodeURIComponent(chatId)}/file?path=${encodeURIComponent(path)}`);
  }

  function selectedRow() {
    return filesListing.find((row) => row.path === filesSelected) || null;
  }

  function paintFilesHead() {
    const total = filesListing.reduce((sum, row) => sum + (Number(row.size) || 0), 0);
    if (filesCountEl) {
      filesCountEl.textContent = filesListing.length
        ? `${filesListing.length} · ${TabbyUI.formatBytes(total)}`
        : "";
    }
    if (filesZipBtn) filesZipBtn.disabled = !filesListing.length;
    if (filesClearBtn) filesClearBtn.disabled = !filesListing.length;
    if (filesSiteBtn) {
      filesSiteBtn.disabled = !filesEntry;
      const row = selectedRow();
      const target = row && row.page ? row.path : filesEntry;
      filesSiteBtn.title = target ? `Open ${target} in a new tab` : "No HTML page yet";
    }
  }

  function paintFilesTree() {
    if (!filesTree) return;
    if (!filesListing.length) {
      filesTree.innerHTML =
        '<p class="muted chat-files-empty">No files yet. Ask for a page and they land here.</p>';
      return;
    }
    const frag = document.createDocumentFragment();
    filesListing.forEach((row) => {
      const item = document.createElement("div");
      item.className = "chat-file" + (row.path === filesSelected ? " is-active" : "");
      item.dataset.path = row.path;
      item.innerHTML =
        `<button type="button" class="chat-file-open" data-file="open" title="${TabbyUI.escapeHtml(row.path)}">${TabbyUI.escapeHtml(row.path)}</button>` +
        `<span class="chat-file-size">${TabbyUI.escapeHtml(TabbyUI.formatBytes(row.size))}</span>` +
        `<button type="button" class="btn ghost chat-icon" data-file="download" aria-label="Download file" title="Download">↓</button>` +
        `<button type="button" class="btn ghost chat-icon danger" data-file="delete" aria-label="Delete file" title="Delete">×</button>`;
      frag.appendChild(item);
    });
    filesTree.replaceChildren(frag);
  }

  function previewHeadHtml(row, tools) {
    return (
      `<div class="chat-files-name"><strong>${TabbyUI.escapeHtml(row.path)}</strong>` +
      `<span>${TabbyUI.escapeHtml(TabbyUI.formatBytes(row.size))}</span>` +
      `<span class="spacer"></span>${tools || ""}</div>`
    );
  }

  function paintEditorState() {
    const save = filesPreview && filesPreview.querySelector("[data-edit='save']");
    const revert = filesPreview && filesPreview.querySelector("[data-edit='revert']");
    if (save) {
      save.disabled = !previewDirty || previewBusy;
      save.textContent = previewBusy ? "Saving" : previewDirty ? "Save" : "Saved";
    }
    if (revert) revert.hidden = !previewDirty;
  }

  function setPreviewNote(text) {
    const note = filesPreview && filesPreview.querySelector(".chat-files-note");
    if (note) note.textContent = text || "";
  }

  function confirmDropEdits() {
    return TabbyUI.confirmModal({
      title: "Discard changes?",
      text: `${previewPath} has edits you have not saved.`,
      yes: "Discard",
      no: "Keep editing",
    });
  }

  function renderEditor(row, text) {
    if (!filesPreview) return;
    previewPath = row.path;
    previewChat = store.activeId;
    previewSize = Number(row.size) || 0;
    previewOriginal = text;
    previewDirty = false;
    filesPreview.classList.add("is-editing");
    filesPreview.innerHTML =
      previewHeadHtml(
        row,
        '<button type="button" class="btn ghost" data-edit="revert" hidden>Revert</button>' +
          '<button type="button" class="btn primary" data-edit="save" disabled>Saved</button>'
      ) +
      // The leading newline is eaten by the parser, so a file that starts with
      // a blank line keeps it.
      `<textarea class="chat-files-edit" spellcheck="false" aria-label="File contents">\n${TabbyUI.escapeHtml(text)}</textarea>` +
      '<p class="muted chat-files-note"></p>';
    paintEditorState();
  }

  function renderStaticPreview(row, html) {
    if (!filesPreview) return;
    previewPath = row.path;
    previewChat = store.activeId;
    previewSize = Number(row.size) || 0;
    previewOriginal = null;
    previewDirty = false;
    filesPreview.classList.remove("is-editing");
    filesPreview.innerHTML = previewHeadHtml(row, "") + html;
  }

  function paintPreview() {
    if (!filesPreview) return;
    const row = selectedRow();
    if (!row) {
      previewPath = "";
      previewChat = "";
      previewOriginal = null;
      previewDirty = false;
      filesPreview.classList.remove("is-editing");
      filesPreview.innerHTML = filesListing.length
        ? '<p class="muted">Select a file to view or edit it.</p>'
        : '<p class="muted">Nothing to preview yet.</p>';
      return;
    }
    const shown = row.path === previewPath && previewChat === store.activeId;
    // A code turn writing files must not wipe out unsaved edits.
    if (shown && (previewDirty || previewBusy)) {
      paintEditorState();
      return;
    }
    // Same file, same size: nothing new to load. A rewrite changes the size.
    if (shown && (Number(row.size) || 0) === previewSize) return;
    const chatId = store.activeId;
    if (row.kind === "image") {
      const src = `${fileUrl(chatId, row.path)}&v=${Number(row.size) || 0}`;
      renderStaticPreview(row, `<img alt="" src="${TabbyUI.escapeHtml(src)}" />`);
      return;
    }
    if (!row.editable) {
      renderStaticPreview(row, '<p class="muted">Download this file to open it.</p>');
      return;
    }
    fetch(fileUrl(chatId, row.path), { credentials: "same-origin" })
      .then((res) => (res.ok ? res.text() : Promise.reject(new Error("Could not read file"))))
      .then((text) => {
        if (filesSelected !== row.path || chatId !== store.activeId) return;
        renderEditor(row, text);
      })
      .catch(() => {
        if (filesSelected !== row.path || chatId !== store.activeId) return;
        renderStaticPreview(row, '<p class="muted">Could not read this file.</p>');
      });
  }

  function paintFiles() {
    paintFilesHead();
    paintFilesTree();
    paintPreview();
  }

  async function savePreview() {
    const row = selectedRow();
    const editor = filesPreview && filesPreview.querySelector(".chat-files-edit");
    if (!row || !editor || !previewDirty || previewBusy) return;
    const chatId = store.activeId;
    const contents = editor.value;
    previewBusy = true;
    paintEditorState();
    setPreviewNote("");
    try {
      const data = await TabbyUI.api(
        `workspace/${encodeURIComponent(chatId)}/file?path=${encodeURIComponent(row.path)}`,
        { method: "PUT", body: { contents } }
      );
      previewBusy = false;
      if (chatId !== store.activeId) return;
      filesListing = Array.isArray(data.files) ? data.files : filesListing;
      filesEntry = typeof data.entry === "string" ? data.entry : filesEntry;
      previewOriginal = contents;
      previewDirty = false;
      const saved = filesListing.find((item) => item.path === row.path);
      previewSize = saved ? Number(saved.size) || 0 : previewSize;
      paintFilesHead();
      paintFilesTree();
      paintEditorState();
      setPreviewNote("Saved.");
    } catch (err) {
      previewBusy = false;
      paintEditorState();
      setPreviewNote(err.message);
    }
  }

  function revertPreview() {
    const editor = filesPreview && filesPreview.querySelector(".chat-files-edit");
    if (!editor || previewOriginal === null) return;
    editor.value = previewOriginal;
    previewDirty = false;
    paintEditorState();
    setPreviewNote("");
  }

  async function openSite() {
    const row = selectedRow();
    const wanted = row && row.page ? row.path : "";
    if (!filesEntry && !wanted) return;
    const chatId = store.activeId;
    // Open the tab on the click itself; a tab opened after the await is a popup.
    const tab = window.open("about:blank", "_blank");
    try {
      const data = await TabbyUI.api(`workspace/${encodeURIComponent(chatId)}/preview`, {
        method: "POST",
        body: { path: wanted },
      });
      // about:blank resolves relative URLs against itself, so hand it an absolute one.
      const url = new URL(TabbyUI.path(data.url), window.location.href).href;
      if (tab) tab.location.replace(url);
      else addBubble("assistant", `Error: Allow pop-ups for this site, or open ${url} yourself.`);
    } catch (err) {
      if (tab) tab.close();
      addBubble("assistant", `Error: ${err.message}`);
    }
  }

  let filesRefreshTimer = 0;

  async function refreshFiles() {
    const chatId = store.activeId;
    if (activeMode() !== "code" || !chatId) {
      filesListing = [];
      filesSelected = "";
      filesEntry = "";
      paintFiles();
      return;
    }
    try {
      const data = await TabbyUI.api(`workspace/${encodeURIComponent(chatId)}`);
      if (chatId !== store.activeId) return;
      filesListing = Array.isArray(data.files) ? data.files : [];
      filesEntry = typeof data.entry === "string" ? data.entry : "";
      if (filesSelected && !filesListing.some((row) => row.path === filesSelected)) {
        filesSelected = "";
      }
    } catch {
      if (chatId !== store.activeId) return;
      filesListing = [];
      filesEntry = "";
    }
    paintFiles();
  }

  /** Code turns stream one status per write, so coalesce the listing calls. */
  function refreshFilesSoon() {
    if (filesRefreshTimer) return;
    filesRefreshTimer = setTimeout(() => {
      filesRefreshTimer = 0;
      refreshFiles();
    }, 600);
  }

  let followLog = true;

  function nearBottom() {
    return log.scrollHeight - log.scrollTop - log.clientHeight < 48;
  }

  function paintJump() {
    if (!jumpBtn) return;
    const overflow = log.scrollHeight > log.clientHeight + 8;
    jumpBtn.hidden = !overflow || followLog || nearBottom();
  }

  function stickLog(force) {
    if (force) followLog = true;
    if (followLog) log.scrollTop = log.scrollHeight;
    paintJump();
  }

  function resizeInput() {
    input.style.height = "auto";
    const minH = parseFloat(getComputedStyle(input).minHeight) || 0;
    input.style.height = `${Math.min(Math.max(input.scrollHeight, minH), 180)}px`;
    if (countEl) {
      const n = input.value.length;
      countEl.textContent = n >= 400 ? `${n.toLocaleString()} chars` : "";
    }
  }

  function hideMoreMenu() {
    if (!moreMenu || !moreBtn) return;
    moreMenu.hidden = true;
    moreBtn.setAttribute("aria-expanded", "false");
  }

  function setSidebarOpen(open) {
    shell.classList.toggle("is-sidebar-open", open);
    const backdrop = root.querySelector("#chat-backdrop");
    if (backdrop) backdrop.hidden = !open;
    paintToolbar();
  }

  function isNarrowChat() {
    return window.matchMedia("(max-width: 900px)").matches;
  }

  function setSidebarHidden(hidden) {
    shell.classList.toggle("is-sidebar-hidden", hidden);
    try {
      localStorage.setItem(SIDEBAR_KEY, hidden ? "hidden" : "shown");
    } catch {
      /* ignore */
    }
    paintToolbar();
  }

  function copyText(text, btn) {
    const value = String(text || "");
    const done = () => {
      if (!btn) return;
      const prev = btn.textContent;
      btn.textContent = "Copied";
      setTimeout(() => {
        btn.textContent = prev;
      }, 1200);
    };
    const fail = () => {
      if (!btn) return;
      const prev = btn.textContent;
      btn.textContent = "Copy failed";
      setTimeout(() => {
        btn.textContent = prev;
      }, 1200);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(value).then(done).catch(fail);
      return;
    }
    try {
      const ta = document.createElement("textarea");
      ta.value = value;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
      done();
    } catch {
      fail();
    }
  }

  function lastAssistantIndex() {
    for (let i = messages.length - 1; i >= 0; i -= 1) {
      if (messages[i].role === "assistant") return i;
    }
    return -1;
  }

  function stampLabel(ts) {
    if (!ts) return "";
    try {
      return new Date(ts).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
    } catch {
      return "";
    }
  }

  function attachMsgActions(host, role, idx, text) {
    if (!host || idx == null || idx < 0) return;
    host.querySelectorAll(".chat-meta").forEach((node) => node.remove());
    const meta = document.createElement("div");
    meta.className = "chat-meta";
    const actions = document.createElement("div");
    actions.className = "chat-actions";
    const add = (act, label, hint) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "btn ghost";
      btn.dataset.act = act;
      btn.dataset.idx = String(idx);
      btn.textContent = label;
      btn.setAttribute("aria-label", hint || label);
      if (hint) btn.title = hint;
      actions.appendChild(btn);
    };
    add("copy", "Copy");
    if (role === "user") {
      add("edit", "Edit");
      add("delete", "Delete");
    } else {
      if (idx === lastAssistantIndex()) add("regen", "Regen");
      if (/^Error:/i.test(String(text || ""))) add("retry", "Retry");
    }
    if (canSplit(idx)) add("split", "Split", "Move this turn and later messages to a new chat");
    meta.appendChild(actions);
    const item = messages[idx];
    if (item && item.createdAt) {
      const stamp = document.createElement("span");
      stamp.className = "chat-stamp";
      stamp.textContent = stampLabel(item.createdAt);
      meta.appendChild(stamp);
    }
    host.appendChild(meta);
  }

  function cancelEdit() {
    pendingEditIndex = -1;
    if (editBar) editBar.hidden = true;
    paintCompose();
  }

  function beginEdit(idx) {
    if (inFlight || modelLoading) return;
    const item = messages[idx];
    if (!item || item.role !== "user") return;
    pendingEditIndex = idx;
    setCompose(item.content);
    if (item.imageData) {
      pendingImage = {
        name: item.imageName || "image",
        dataUrl: item.imageData,
        preview: item.imagePreview || item.imageData,
      };
      paintAttach();
    } else {
      clearPendingImage();
    }
    if (editBar) editBar.hidden = false;
    resizeInput();
    paintCompose();
    input.focus();
  }

  function deleteTurn(idx) {
    if (inFlight || modelLoading) return;
    const item = messages[idx];
    if (!item || item.role !== "user") return;
    const next = messages[idx + 1];
    const drop = next && next.role === "assistant" ? 2 : 1;
    messages.splice(idx, drop);
    persist();
    renderLog();
  }

  function splitStartIndex(idx) {
    const item = messages[idx];
    if (!item || item.role === "system") return -1;
    if (item.role === "assistant" && idx > 0 && messages[idx - 1].role === "user") {
      return idx - 1;
    }
    return idx;
  }

  function canSplit(idx) {
    if (inFlight || modelLoading) return false;
    const start = splitStartIndex(idx);
    if (start < 0) return false;
    return messages.slice(0, start).some((msg) => msg.role !== "system");
  }

  function splitAfterTurn(idx) {
    if (inFlight || modelLoading) return;
    const start = splitStartIndex(idx);
    if (start < 0) return;
    const tail = cloneMessages(messages.slice(start)).filter((msg) => msg.role !== "system");
    const kept = messages.slice(0, start);
    if (!kept.some((msg) => msg.role !== "system") || !tail.length) return;
    cancelEdit();
    clearPendingImage();
    const mode = activeMode();
    messages = kept;
    if (!messages.some((msg) => msg.role === "system")) messages.unshift({ ...SYSTEM });
    touchActive();
    persist();
    const chat = emptyChat(mode);
    chat.messages = [{ ...SYSTEM }, ...tail];
    chat.title = titleFromMessages(chat.messages);
    chat.updatedAt = Date.now();
    store.chats.unshift(chat);
    store.activeId = chat.id;
    messages = cloneMessages(chat.messages);
    persist();
    resetRecall();
    renderLog();
    refreshFiles();
    hideHistoryMenu();
    hideMoreMenu();
    setSidebarOpen(false);
    input.focus();
  }

  function regenerateLast() {
    if (inFlight || modelLoading) return;
    if (messages.length && messages[messages.length - 1].role === "assistant") {
      messages.pop();
    }
    const lastUser = [...messages].reverse().find((item) => item.role === "user");
    if (!lastUser) return;
    persist();
    renderLog();
    runLoop(lastUser.content, { replay: true }).catch((err) => {
      addBubble("assistant", `Error: ${err.message}`);
      persist();
    });
  }

  function conversationMarkdown() {
    return messages
      .filter((item) => item.role === "user" || item.role === "assistant")
      .map((item) => {
        const who = item.role === "user" ? "You" : "Assistant";
        const body = item.role === "assistant" && TabbyUI.formatAssistantContent
          ? TabbyUI.formatAssistantContent(item.content)
          : item.content;
        return `## ${who}\n\n${String(body || "").trim()}\n`;
      })
      .join("\n");
  }

  function saveUrl(url, filename) {
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.rel = "noreferrer";
    document.body.appendChild(link);
    link.click();
    link.remove();
  }

  function downloadStem() {
    const chat = activeChat();
    const title = (chat && chat.title) || "chat";
    return title.replace(/[^\w.-]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 48) || "chat";
  }

  function exportChat() {
    const blob = new Blob([conversationMarkdown()], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    saveUrl(url, `${downloadStem()}.md`);
    setTimeout(() => URL.revokeObjectURL(url), 10_000);
  }

  function beginRename(id) {
    const chat = store.chats.find((item) => item.id === (id || store.activeId));
    if (!chat || renaming) return;
    renaming = true;
    const field = document.createElement("input");
    field.className = "chat-title-edit";
    field.value = chat.title || "New chat";
    field.setAttribute("aria-label", "Chat title");
    titleEl.replaceWith(field);
    field.focus();
    field.select();
    const finish = (save) => {
      if (!renaming) return;
      renaming = false;
      const next = String(field.value || "").replace(/\s+/g, " ").trim().slice(0, 80);
      if (save && next) {
        chat.title = next;
        chat.titleLocked = true;
        persist();
      }
      field.replaceWith(titleEl);
      paintToolbar();
    };
    field.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        finish(true);
      }
      if (event.key === "Escape") {
        event.preventDefault();
        finish(false);
      }
    });
    field.addEventListener("blur", () => finish(true));
  }

  function togglePin(id) {
    const chat = store.chats.find((item) => item.id === (id || store.activeId));
    if (!chat) return;
    chat.pinned = !chat.pinned;
    persist();
  }

  function paintAttach() {
    const on = Boolean(pendingImage);
    if (attachBar) attachBar.hidden = !on;
    if (attachImg) attachImg.src = (pendingImage && (pendingImage.preview || pendingImage.dataUrl)) || "";
    if (attachName) attachName.textContent = (pendingImage && pendingImage.name) || "";
  }

  function clearPendingImage() {
    pendingImage = null;
    if (fileInput) fileInput.value = "";
    paintAttach();
  }

  function resizeDataUrl(dataUrl, maxEdge, quality) {
    return new Promise((resolve) => {
      const img = new Image();
      img.onload = () => {
        let w = img.width;
        let h = img.height;
        const edge = Math.max(w, h) || 1;
        if (edge > maxEdge) {
          const scale = maxEdge / edge;
          w = Math.round(w * scale);
          h = Math.round(h * scale);
        }
        const canvas = document.createElement("canvas");
        canvas.width = w;
        canvas.height = h;
        const ctx = canvas.getContext("2d");
        ctx.fillStyle = "#111318";
        ctx.fillRect(0, 0, w, h);
        ctx.drawImage(img, 0, 0, w, h);
        resolve(canvas.toDataURL("image/jpeg", quality));
      };
      img.onerror = () => resolve(dataUrl);
      img.src = dataUrl;
    });
  }

  async function setPendingImageFromFile(file) {
    if (!file || modelLoading) return;
    if (!/^image\//.test(file.type || "")) {
      addBubble("assistant", "Error: Attach a PNG, JPEG, WebP, or GIF.");
      return;
    }
    if (file.size > 8 * 1024 * 1024) {
      addBubble("assistant", "Error: Image must be under 8 MB.");
      return;
    }
    const dataUrl = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result || ""));
      reader.onerror = () => reject(new Error("Could not read image."));
      reader.readAsDataURL(file);
    });
    const preview = await resizeDataUrl(dataUrl, 320, 0.72);
    const compact = await resizeDataUrl(dataUrl, 1280, 0.82);
    pendingImage = { name: file.name || "image", dataUrl: compact, preview };
    paintAttach();
  }

  function outboundMessages() {
    return messages
      .filter((item) => item.role !== "system")
      .map((item) => {
        if (item.role === "user" && item.imageData) {
          return {
            role: "user",
            content: [
              { type: "text", text: String(item.content || "") },
              { type: "image_url", image_url: { url: item.imageData } },
            ],
          };
        }
        return { role: item.role, content: item.content };
      });
  }

  function saveSettings() {
    try {
      localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
    } catch {
      /* ignore */
    }
  }

  function showDialog({ title, html, yes = "Close" }) {
    return new Promise((resolve) => {
      const wrap = document.createElement("div");
      wrap.className = "dialog-modal";
      wrap.setAttribute("role", "dialog");
      wrap.setAttribute("aria-modal", "true");
      wrap.innerHTML =
        '<div class="dialog-card">' +
        "<h2></h2>" +
        '<div class="dialog-body"></div>' +
        '<div class="dialog-actions">' +
        '<button type="button" class="btn primary dialog-yes"></button>' +
        "</div></div>";
      wrap.querySelector("h2").textContent = title || "";
      wrap.querySelector(".dialog-body").innerHTML = html || "";
      wrap.querySelector(".dialog-yes").textContent = yes;
      const finish = () => {
        document.removeEventListener("keydown", onKey);
        wrap.remove();
        resolve();
      };
      const onKey = (ev) => {
        if (ev.key === "Escape") finish();
      };
      wrap.querySelector(".dialog-yes").addEventListener("click", finish);
      wrap.addEventListener("click", (ev) => {
        if (ev.target === wrap) finish();
      });
      document.addEventListener("keydown", onKey);
      document.body.appendChild(wrap);
      wrap.querySelector(".dialog-yes").focus();
    });
  }

  function showShortcuts() {
    return showDialog({
      title: "Keyboard shortcuts",
      html:
        '<ul class="shortcuts-list">' +
        "<li><span>Send</span><kbd>Enter</kbd></li>" +
        "<li><span>New line</span><kbd>Shift</kbd>+<kbd>Enter</kbd></li>" +
        "<li><span>Stop / close menus</span><kbd>Esc</kbd></li>" +
        "<li><span>Cycle chats</span><kbd>Tab</kbd></li>" +
        "<li><span>Recall sent text</span><kbd>↑</kbd> <kbd>↓</kbd></li>" +
        "<li><span>Search chats</span><kbd>Ctrl</kbd>+<kbd>K</kbd></li>" +
        "<li><span>New chat</span><kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>O</kbd></li>" +
        "<li><span>Slash commands</span><kbd>/</kbd></li>" +
        "</ul>",
    });
  }

  function showSettings() {
    const current = settings.temperature;
    const value = current == null ? 0.7 : current;
    const wrap = document.createElement("div");
    wrap.className = "dialog-modal";
    wrap.setAttribute("role", "dialog");
    wrap.setAttribute("aria-modal", "true");
    wrap.innerHTML =
      '<div class="dialog-card"><h2>Sampling</h2>' +
      '<label>Temperature <strong id="chat-temp-val"></strong><input id="chat-temp" type="range" min="0" max="2" step="0.1" /></label>' +
      '<p class="muted">Leave at model default unless you want a fixed value for this browser.</p>' +
      '<div class="dialog-actions">' +
      '<button type="button" class="btn" id="chat-temp-default">Model default</button>' +
      '<button type="button" class="btn primary" id="chat-temp-save">Save</button>' +
      "</div></div>";
    const range = wrap.querySelector("#chat-temp");
    const label = wrap.querySelector("#chat-temp-val");
    range.value = String(value);
    label.textContent = settings.temperature == null ? "default" : String(settings.temperature);
    range.addEventListener("input", () => {
      label.textContent = range.value;
    });
    const close = () => {
      document.removeEventListener("keydown", onKey);
      wrap.remove();
    };
    const onKey = (ev) => {
      if (ev.key === "Escape") close();
    };
    wrap.querySelector("#chat-temp-default").addEventListener("click", () => {
      settings.temperature = null;
      saveSettings();
      close();
    });
    wrap.querySelector("#chat-temp-save").addEventListener("click", () => {
      settings.temperature = Number(range.value);
      saveSettings();
      close();
    });
    wrap.addEventListener("click", (ev) => {
      if (ev.target === wrap) close();
    });
    document.addEventListener("keydown", onKey);
    document.body.appendChild(wrap);
  }

  function addBubble(role, text, stick, reasoning, idx, extra) {
    if (role === "assistant") {
      const cleaned = TabbyUI.formatAssistantContent ? TabbyUI.formatAssistantContent(text) : text;
      const isImage = looksLikeImageReply(cleaned);
      const turn = addAssistantTurn({
        content: text,
        reasoning,
        live: false,
        activity: isImage ? { kind: "image" } : undefined,
        elapsed_s: extra && extra.elapsed_s,
        status_label: extra && extra.status_label,
      });
      attachSwitchLlm(turn.bubble || turn.node, text);
      attachMsgActions(turn.node, "assistant", idx, text);
      if (stick !== false) stickLog(true);
      return turn.node;
    }
    const row = document.createElement("div");
    row.className = "chat-row";
    const node = document.createElement("div");
    node.className = `bubble ${role}`;
    node.innerHTML = TabbyUI.renderMarkdown(text);
    const preview = extra && (extra.imagePreview || extra.imageData);
    if (preview) {
      const img = document.createElement("img");
      img.className = "chat-thumb";
      img.src = preview;
      img.alt = (extra && extra.imageName) || "Attached image";
      node.appendChild(img);
    }
    row.appendChild(node);
    attachMsgActions(row, "user", idx, text);
    log.appendChild(row);
    if (stick !== false) stickLog(true);
    return row;
  }

  function activityFromPrompt(text) {
    const raw = String(text || "").trim();
    const lower = raw.toLowerCase();
    if (/^restart$/i.test(lower) || lower === "/restart") {
      return { label: "Restarting", kind: "restart", processing: true, target: "restart" };
    }
    const sw = lower.match(/^switch to (\S+)/) || lower.match(/^\/(qwen\d*|gemma\d*|glm|comfy|flux|llm)\b/);
    if (sw) {
      const name = sw[1];
      return { label: `Loading ${name}`, kind: "switch", processing: true, target: name };
    }
    if (
      /^(generate an image|qwen-image:)/i.test(raw) ||
      /^\/image\b/i.test(raw) ||
      /\b(generate|draw|paint|render|create|make)\b[\s\S]{0,80}\b(image|picture|logo|poster|icon|svg)\b/i.test(lower) ||
      /\b(svg|png|jpg|jpeg|webp)\b.+\b(image|picture|logo|of)\b/i.test(lower)
    ) {
      return {
        label: "Starting the picture",
        kind: "image",
        processing: true,
        note: "Preparing the GPU.",
      };
    }
    if (/^(help|list models)$/i.test(lower) || lower === "/help" || lower === "/list models") {
      return { label: "Working", kind: "cmd", processing: true };
    }
    return { label: "Thinking", kind: "chat", processing: false };
  }

  function visibleAnswerText(text) {
    const cleaned = TabbyUI.formatAssistantContent
      ? TabbyUI.formatAssistantContent(text)
      : String(text || "");
    return cleaned.replace(/\s+/g, " ").trim();
  }

  function displayAnswer(text) {
    const cleaned = TabbyUI.formatAssistantContent
      ? TabbyUI.formatAssistantContent(text)
      : String(text || "");
    return TabbyUI.renderMarkdown(cleaned);
  }

  function looksLikeImageReply(text) {
    const cleaned = TabbyUI.formatAssistantContent
      ? TabbyUI.formatAssistantContent(text)
      : String(text || "");
    return /here's the picture|here are the \d+ pictures|\/v1\/images\/generated-/i.test(cleaned);
  }

  function labelForJob(job) {
    if (!job) return "";
    const phase = String(job.phase || job.status || "");
    const status = String(job.status || "");
    if (status === "done" || phase === "done") return "";
    if (status === "error" || phase === "error") return "";
    const count = Number(job.count) || 0;
    const index = (Number(job.current_index) || 0) + 1;
    if (phase === "queued") return "Queued";
    if (phase === "writing_code" || phase === "coding") return "Planning the picture";
    if (phase === "starting_comfy") return "Starting Comfy";
    if (phase === "generating" || phase === "running") {
      if (count > 1) return `Rendering image ${Math.min(index, count)} of ${count}`;
      return "Rendering in Comfy";
    }
    if (phase === "restoring_llm") return "Reloading the coding model";
    if (status === "queued" || status === "running" || status === "coding") {
      return "Working on the picture";
    }
    return "";
  }

  function detailForJob(job) {
    if (!job) return "";
    const phase = String(job.phase || job.status || "");
    const status = String(job.status || "");
    if (status === "done" || phase === "done" || status === "error" || phase === "error") {
      return "";
    }
    if (phase === "queued") {
      return "Waiting to start. Next: unload the coding model and hand the GPU to Comfy.";
    }
    if (phase === "writing_code" || phase === "coding") return "Figuring out what to render.";
    if (phase === "starting_comfy") return "Unloading the coding model so Comfy can use the GPU.";
    if (phase === "generating" || phase === "running") {
      return "Comfy is rendering the picture on the GPU.";
    }
    if (phase === "restoring_llm") {
      return "The picture is ready. Reloading the coding model onto the GPU.";
    }
    return "";
  }

  function addAssistantTurn({ content, reasoning, live, activity, elapsed_s, status_label }) {
    const turn = document.createElement("div");
    turn.className = live ? "chat-turn assistant is-working" : "chat-turn assistant";
    turn.setAttribute("aria-live", live ? "polite" : "off");
    if (live) turn.setAttribute("aria-busy", "true");

    const head = document.createElement(live ? "div" : "button");
    if (!live) {
      head.type = "button";
      head.className = "think-head";
    } else {
      head.className = "think-head is-live";
    }
    const icon = document.createElement("span");
    icon.className = "think-icon";
    icon.setAttribute("aria-hidden", "true");
    const spark = document.createElement("span");
    spark.className = "think-spark";
    icon.appendChild(spark);
    const chevron = document.createElement("span");
    chevron.className = "think-chevron";
    chevron.hidden = true;
    chevron.setAttribute("aria-hidden", "true");
    const label = document.createElement("span");
    label.className = "think-label";
    label.textContent = String(status_label || (activity && activity.label) || "Thinking");
    const timeEl = document.createElement("span");
    timeEl.className = "think-time";
    head.append(icon, chevron, label, timeEl);

    const thought = document.createElement("div");
    thought.className = "think-body";
    thought.hidden = true;

    const bubble = document.createElement("div");
    bubble.className = "bubble assistant";
    // Never leave an empty styled bubble in the DOM while waiting.
    let bubbleMounted = false;

    function ensureBubble() {
      if (bubbleMounted) return;
      turn.appendChild(bubble);
      bubbleMounted = true;
    }

    function showAnswer(html, raw) {
      const markup = String(html || "").trim();
      if (!markup) return false;
      ensureBubble();
      bubble.innerHTML = markup;
      bubble.hidden = false;
      turn.classList.add("has-answer");
      attachSwitchLlm(bubble, raw);
      return true;
    }

    turn.append(head, thought);
    if (visibleAnswerText(content)) {
      showAnswer(displayAnswer(content), content);
    }

    let reasoningText = reasoning ? String(reasoning) : "";
    let finished = !live;
    let expanded = false;
    let processing = Boolean(activity && activity.processing);
    const started = Date.now();
    let ticker = null;
    const kind = (activity && activity.kind) || "";
    let statusNotes = [];
    let lastNote = "";
    const storedElapsed = Number(elapsed_s);
    let elapsedSec = Number.isFinite(storedElapsed) && storedElapsed > 0
      ? Math.max(1, Math.round(storedElapsed))
      : null;

    function setProcessing(on) {
      processing = Boolean(on);
      icon.classList.toggle("is-processing", processing);
    }

    function paintThought() {
      if (!reasoningText) {
        thought.hidden = true;
        thought.innerHTML = "";
        return;
      }
      thought.innerHTML = TabbyUI.renderMarkdown(reasoningText);
      thought.hidden = finished ? !expanded : false;
    }

    function addStatusNote(note) {
      const line = String(note || "").trim();
      if (!line || line === lastNote) return;
      lastNote = line;
      if (!statusNotes.includes(line)) statusNotes.push(line);
      if (finished) return;
      reasoningText = line;
      paintThought();
      thought.hidden = false;
      stickLog();
    }

    function foldNotesIntoThought() {
      if (!statusNotes.length) {
        if (!reasoningText && lastNote) reasoningText = lastNote;
        return;
      }
      const notes = statusNotes.join("\n\n");
      if (!reasoningText || kind === "image") reasoningText = notes;
    }

    function stopWorking() {
      setProcessing(false);
      icon.classList.remove("is-processing");
      turn.classList.remove("is-working");
      head.classList.remove("is-live");
      turn.removeAttribute("aria-busy");
      turn.setAttribute("aria-live", "off");
    }

    function settleThought(seconds) {
      stopWorking();
      if (ticker) {
        clearInterval(ticker);
        ticker = null;
      }
      if (seconds != null) elapsedSec = seconds;
      head.hidden = false;
      const canExpand = Boolean(reasoningText);
      chevron.hidden = !canExpand;
      head.classList.toggle("is-clickable", canExpand);
      if (canExpand) {
        if (head.tagName !== "BUTTON") {
          head.setAttribute("role", "button");
          head.tabIndex = 0;
        }
      } else {
        head.removeAttribute("role");
        head.removeAttribute("tabindex");
      }
      if (kind === "image") {
        icon.hidden = false;
        icon.classList.remove("is-processing");
        icon.classList.add("is-done");
      } else {
        icon.hidden = true;
        icon.classList.remove("is-done");
      }
      timeEl.textContent = seconds != null ? TabbyUI.formatDuration(seconds) : "";
      thought.hidden = true;
      expanded = false;
      head.classList.remove("is-open");
    }

    if (live) {
      setProcessing(processing);
      if (activity && activity.note) addStatusNote(activity.note);
      ticker = setInterval(() => {
        const s = Math.floor((Date.now() - started) / 1000);
        if (s >= 1) timeEl.textContent = TabbyUI.formatDuration(s);
      }, 250);
    } else if (reasoningText || elapsedSec) {
      settleThought(elapsedSec);
      paintThought();
    } else {
      head.hidden = true;
    }

    function toggleThought() {
      if (!finished || !reasoningText) return;
      expanded = !expanded;
      thought.hidden = !expanded;
      head.classList.toggle("is-open", expanded);
      head.setAttribute("aria-expanded", expanded ? "true" : "false");
    }
    head.addEventListener("click", toggleThought);
    head.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        toggleThought();
      }
    });

    log.appendChild(turn);

    return {
      node: turn,
      bubble,
      setActivity(text, opts) {
        if (finished || !text) return;
        label.textContent = text;
        head.hidden = false;
        if (opts && opts.processing != null) setProcessing(opts.processing);
        if (opts && opts.note) addStatusNote(opts.note);
      },
      addStatusNote,
      setReasoning(text) {
        if (!text) return;
        reasoningText = text;
        if (!finished) {
          label.textContent = "Thinking";
          head.hidden = false;
          setProcessing(false);
        }
        paintThought();
        stickLog();
      },
      setAnswer(text) {
        const value = visibleAnswerText(text);
        if (!value) return;
        showAnswer(displayAnswer(text), text);
        if (kind === "image" && looksLikeImageReply(String(text || ""))) {
          const seconds = Math.max(1, Math.round((Date.now() - started) / 1000));
          foldNotesIntoThought();
          finished = true;
          settleThought(seconds);
          paintThought();
        } else if (reasoningText || statusNotes.length) {
          thought.hidden = true;
        }
        stickLog();
      },
      finish({ content: finalContent, reasoning: finalReasoning } = {}) {
        if (finished && !live) {
          return { reasoning: reasoningText, elapsed_s: elapsedSec, status_label: label.textContent };
        }
        const alreadySettled = finished;
        finished = true;
        if (ticker) {
          clearInterval(ticker);
          ticker = null;
        }
        stopWorking();
        if (kind === "image") {
          foldNotesIntoThought();
        } else if (finalReasoning) {
          reasoningText = String(finalReasoning);
        } else {
          foldNotesIntoThought();
        }
        const seconds = Math.max(1, Math.round((Date.now() - started) / 1000));
        if (!alreadySettled) elapsedSec = seconds;
        const answer = visibleAnswerText(finalContent);
        if (answer) {
          showAnswer(displayAnswer(finalContent), finalContent);
        } else if (!bubbleMounted || !visibleAnswerText(bubble.textContent)) {
          showAnswer(TabbyUI.renderMarkdown("(empty reply)"));
        }
        if (!alreadySettled) {
          settleThought(seconds);
          paintThought();
        } else if (kind === "image") {
          icon.hidden = false;
          icon.classList.remove("is-processing");
          icon.classList.add("is-done");
        } else {
          icon.hidden = true;
          icon.classList.remove("is-processing");
        }
        stickLog();
        return { reasoning: reasoningText, elapsed_s: elapsedSec, status_label: label.textContent };
      },
      stopClock() {
        if (ticker) {
          clearInterval(ticker);
          ticker = null;
        }
      },
      discard() {
        finished = true;
        if (ticker) {
          clearInterval(ticker);
          ticker = null;
        }
        stopWorking();
        turn.remove();
      },
    };
  }

  function addWorkingReply(activity) {
    return addAssistantTurn({ live: true, activity });
  }

  function renderLog(stickToEnd) {
    log.replaceChildren();
    messages.forEach((item, idx) => {
      if (item.role === "user") addBubble("user", item.content, false, null, idx, item);
      else if (item.role === "assistant") addBubble("assistant", item.content, false, item.reasoning, idx, item);
    });
    paintEmpty();
    if (stickToEnd !== false) stickLog(true);
    else paintJump();
  }

  function loadChat(id, stickToEnd) {
    abortSession("stop");
    persist();
    const chat = store.chats.find((item) => item.id === id);
    if (!chat) return;
    store.activeId = id;
    messages = cloneMessages(chat.messages);
    if (!messages.some((item) => item.role === "system")) messages.unshift({ ...SYSTEM });
    cancelEdit();
    persist();
    resetRecall();
    renderLog(stickToEnd !== false);
    refreshFiles();
    input.focus();
    setSidebarOpen(false);
  }

  async function deleteChat(id) {
    const chat = store.chats.find((item) => item.id === id);
    if (!chat) return;
    const hasContent = hasUserTurn(chat) || (id === store.activeId && hasUserTurn({ messages }));
    if (hasContent) {
      const named = String(chat.title || "").replace(/\s+/g, " ").trim() || "this chat";
      const yes = await TabbyUI.confirmModal({
        title: "Delete chat",
        text: `Delete “${named}”? This cannot be undone.`,
        yes: "Delete",
        no: "Cancel",
      });
      if (!yes) return;
    }
    if (id === store.activeId || id === flightChatId) abortSession("stop");
    if (id === store.activeId) cancelEdit();
    persist();
    const mode = activeMode();
    store.chats = store.chats.filter((item) => item.id !== id);
    dropWorkspace(id);
    if (!store.chats.length) {
      const chat = emptyChat(mode);
      store = { version: 1, activeId: chat.id, chats: [chat] };
      messages = cloneMessages(chat.messages);
    } else if (store.activeId === id) {
      const next = listedChats()[0] || store.chats[0];
      store.activeId = next.id;
      messages = cloneMessages(next.messages);
      if (!messages.some((item) => item.role === "system")) messages.unshift({ ...SYSTEM });
    }
    persist();
    resetRecall();
    renderLog();
    renderHistoryMenu();
    refreshFiles();
    input.focus();
  }

  function startNewChat() {
    abortSession("stop");
    persist();
    cancelEdit();
    clearPendingImage();
    if (!hasUserTurn({ messages })) {
      resetRecall();
      renderLog();
      input.focus();
      return;
    }
    const chat = emptyChat(activeMode());
    store.chats.unshift(chat);
    store.activeId = chat.id;
    messages = cloneMessages(chat.messages);
    persist();
    resetRecall();
    renderLog();
    filesSelected = "";
    refreshFiles();
    hideHistoryMenu();
    input.focus();
  }

  async function clearHistory() {
    if (store.chats.some(hasUserTurn) || hasUserTurn({ messages })) {
      const yes = await TabbyUI.confirmModal({
        title: "Clear history",
        text: "Delete all saved console chats for this account?",
        yes: "Delete all",
        no: "Cancel",
      });
      if (!yes) return;
    }
    abortSession("stop");
    cancelEdit();
    clearPendingImage();
    const chat = emptyChat(activeMode());
    store = { version: 1, activeId: chat.id, chats: [chat] };
    messages = cloneMessages(chat.messages);
    persist();
    resetRecall();
    renderLog();
    hideHistoryMenu();
    refreshFiles();
    input.focus();
  }

  function hideHistoryMenu() {
    historyMenu.hidden = true;
    historyMenu.replaceChildren();
    historyItems = [];
    historyIndex = 0;
  }

  function renderHistoryMenu(keepIndex) {
    historyItems = listedChats();
    if (!historyItems.length) {
      hideHistoryMenu();
      return;
    }
    if (!(keepIndex && historyIndex >= 0 && historyIndex < historyItems.length)) {
      const current = historyItems.findIndex((item) => item.id === store.activeId);
      historyIndex = current >= 0 ? current : 0;
    }
    const frag = document.createDocumentFragment();
    historyItems.forEach((item, idx) => {
      const li = document.createElement("li");
      li.className = idx === historyIndex ? "is-active" : "";
      const when = timeLabel(item.updatedAt);
      const main = document.createElement("span");
      main.className = "history-main";
      main.innerHTML = `<span class="history-title">${TabbyUI.escapeHtml(item.title || "New chat")}</span><span class="slash-hint">${TabbyUI.escapeHtml(when)}</span>`;
      const del = document.createElement("button");
      del.type = "button";
      del.className = "history-delete";
      del.setAttribute("aria-label", "Delete chat");
      del.textContent = "×";
      del.addEventListener("mousedown", (event) => {
        event.preventDefault();
        event.stopPropagation();
        deleteChat(item.id);
      });
      li.append(main, del);
      li.addEventListener("mousedown", (event) => {
        if (event.target.closest(".history-delete")) return;
        event.preventDefault();
        loadChat(item.id);
        renderHistoryMenu();
      });
      frag.appendChild(li);
    });
    historyMenu.replaceChildren(frag);
    historyMenu.hidden = false;
    highlightMenu(historyMenu, historyIndex);
  }

  function onPointerDownAway(event) {
    const target = event.target;
    if (!(target instanceof Node)) return;
    if (!historyMenu.hidden && !historyMenu.contains(target)) hideHistoryMenu();
    if (moreMenu && moreBtn && !moreMenu.hidden && !moreMenu.contains(target) && !moreBtn.contains(target)) {
      hideMoreMenu();
    }
  }

  function onGlobalKey(event) {
    if (event.key === "Escape") {
      if (shell.classList.contains("is-sidebar-open")) {
        setSidebarOpen(false);
        event.preventDefault();
        return;
      }
      hideMoreMenu();
      hideHistoryMenu();
      hideMenu();
      if (pendingEditIndex >= 0) {
        cancelEdit();
        event.preventDefault();
        return;
      }
      if (inFlight && !input.value.trim()) {
        abortSession("stop");
        event.preventDefault();
      }
      return;
    }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      if (searchEl) {
        setSidebarOpen(true);
        searchEl.focus();
        searchEl.select();
      }
      return;
    }
    if ((event.ctrlKey || event.metaKey) && event.shiftKey && event.key.toLowerCase() === "o") {
      event.preventDefault();
      startNewChat();
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
    if (!list.length) return false;
    hideMenu();
    if (historyMenu.hidden) {
      renderHistoryMenu();
      return true;
    }
    if (list.length >= 2) {
      let idx = historyIndex;
      if (idx < 0 || idx >= list.length) {
        idx = list.findIndex((item) => item.id === store.activeId);
        if (idx < 0) idx = 0;
      }
      const highlighted = list[idx];
      if (highlighted && highlighted.id !== store.activeId) {
        loadChat(highlighted.id);
      } else {
        idx = (idx + delta + list.length) % list.length;
        loadChat(list[idx].id);
      }
    }
    renderHistoryMenu();
    return true;
  }

  function moveHistoryHighlight(delta) {
    if (historyMenu.hidden || !historyItems.length) return false;
    historyIndex = (historyIndex + delta + historyItems.length) % historyItems.length;
    highlightMenu(historyMenu, historyIndex);
    return true;
  }

  function applyHistorySelection() {
    const item = historyItems[historyIndex];
    if (!item) {
      hideHistoryMenu();
      return false;
    }
    if (item.id !== store.activeId) loadChat(item.id);
    hideHistoryMenu();
    return true;
  }

  function userSentTexts() {
    return messages.filter((item) => item.role === "user").map((item) => item.content);
  }

  function resetRecall() {
    recallIndex = -1;
    recallDraft = "";
  }

  function setCompose(text) {
    input.value = String(text || "");
    const n = input.value.length;
    input.setSelectionRange(n, n);
  }

  function caretOnFirstLine() {
    const start = input.selectionStart;
    return start === input.selectionEnd && !input.value.slice(0, start).includes("\n");
  }

  function caretOnLastLine() {
    const end = input.selectionEnd;
    return input.selectionStart === end && !input.value.slice(end).includes("\n");
  }

  function stepRecall(dir) {
    const list = userSentTexts();
    if (recallIndex < 0) {
      if (dir > 0 || !list.length) return false;
      recallDraft = input.value;
      recallIndex = list.length;
    }
    const next = recallIndex + dir;
    if (next < 0) return true;
    if (next >= list.length) {
      recallIndex = -1;
      setCompose(recallDraft);
      return true;
    }
    recallIndex = next;
    setCompose(list[recallIndex]);
    return true;
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

  function scrollMenuItemIntoView(listEl, itemEl) {
    if (!listEl || !itemEl) return;
    const pad = 6;
    const listBox = listEl.getBoundingClientRect();
    const itemBox = itemEl.getBoundingClientRect();
    if (itemBox.top < listBox.top + pad) {
      listEl.scrollTop -= listBox.top + pad - itemBox.top;
    } else if (itemBox.bottom > listBox.bottom - pad) {
      listEl.scrollTop += itemBox.bottom - (listBox.bottom - pad);
    }
  }

  function highlightMenu(listEl, index) {
    const nodes = listEl.querySelectorAll("li");
    nodes.forEach((li, idx) => li.classList.toggle("is-active", idx === index));
    scrollMenuItemIntoView(listEl, nodes[index]);
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
    highlightMenu(menu, menuIndex);
  }

  function applyCommand(item, submitAfter) {
    if (modelLoading) {
      hideMenu();
      return false;
    }
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

  function consumeSseBuffer(buffer, onEvent) {
    let rest = buffer;
    let idx;
    while ((idx = rest.indexOf("\n\n")) >= 0) {
      const chunk = rest.slice(0, idx);
      rest = rest.slice(idx + 2);
      const comments = chunk
        .split("\n")
        .filter((line) => line.startsWith(":"))
        .map((line) => line.slice(1).trim());
      const comment = comments.join("\n");
      if (
        comment.includes("tabby-image-job:") ||
        comment.includes("tabby-image-status:")
      ) {
        onEvent({ comment });
      }
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
        onEvent({ content: payload });
        continue;
      }
      if (json.error) {
        const msg = json.error.message || json.error;
        throw new Error(typeof msg === "string" ? msg : "Chat failed");
      }
      const choice = json.choices?.[0] || {};
      const delta = choice.delta || {};
      const message = choice.message || {};
      const content = delta.content || message.content || json.line || "";
      const reasoning = delta.reasoning_content || message.reasoning_content || "";
      if (content || reasoning) onEvent({ content, reasoning });
    }
    return rest;
  }

  function startStatusPoll(working, kind) {
    let stopped = false;
    async function tick() {
      if (stopped) return;
      try {
        const data = await TabbyUI.api("status");
        if (stopped) return;
        rememberGpu(data);
        if (kind === "image") {
          const job = data && data.job;
          const next = labelForJob(job);
          const note = detailForJob(job);
          if (next) working.setActivity(next, { processing: true, note });
          else if (note) working.addStatusNote(note);
          const wait = job && String(job.wait_text || "").trim();
          if (wait) working.addStatusNote(wait);
          const prompt = job && String(job.prompt || "").trim();
          if (prompt) working.addStatusNote(`Prompt: ${prompt}`);
          return;
        }
        if (kind === "switch" || kind === "restart") {
          const busy = statusIsBusy(data);
          const name = (data && data.switch_target) || "";
          if (busy && kind === "switch") {
            working.setActivity(loadingLabel("switch", name), {
              processing: true,
              note: loadingHint("switch", name),
            });
          } else if (busy && kind === "restart") {
            working.setActivity("Restarting", {
              processing: true,
              note: loadingHint("restart", name),
            });
          }
        }
      } catch {
        /* still waiting */
      }
    }
    const id = setInterval(tick, 1500);
    tick();
    return {
      stop() {
        stopped = true;
        clearInterval(id);
      },
    };
  }

  let abortController = null;
  let inFlight = false;
  let queuedText = "";
  let stopKind = "";
  let loopBusy = false;
  let flightChatId = "";
  let gpuMode = "";
  let comfyUp = false;
  let modelLoading = false;
  let modelWait = null;
  let modelLoadStarted = 0;
  let modelLoadTicker = null;
  let loadingHintText = "";

  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  function rememberGpu(data) {
    if (!data) return;
    gpuMode = String(data.gpu_mode || "").toLowerCase();
    comfyUp = Boolean(data.comfy_up);
  }

  function comfyOwnsGpu() {
    return gpuMode === "comfy" || (comfyUp && gpuMode !== "llm");
  }

  function hasSwitchLlmMark(text) {
    return /\btabby-switch-llm\b/i.test(String(text || ""));
  }

  function startLlmSwitch() {
    if (modelLoading) return;
    if (inFlight) {
      queueFollowup("switch to llm");
      return;
    }
    runLoop("switch to llm");
  }

  function attachSwitchLlm(host, text) {
    if (!host || !hasSwitchLlmMark(text)) return;
    if (host.querySelector("[data-switch-llm]")) return;
    const row = document.createElement("div");
    row.className = "chat-switch-llm";
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn primary";
    btn.dataset.switchLlm = "1";
    btn.textContent = "Switch to LLM";
    btn.addEventListener("click", startLlmSwitch);
    row.appendChild(btn);
    host.appendChild(row);
  }

  function paintComfyHint() {
    if (!comfyHint) return;
    if (modelLoading || inFlight) {
      comfyHint.hidden = true;
      return;
    }
    const typed = String((input && input.value) || "").trim();
    const show = comfyOwnsGpu() && tabbyLooksLikeChatNotImage(typed);
    comfyHint.hidden = !show;
  }

  function statusIsBusy(data) {
    return Boolean(data && (data.switching || data.restarting || data.busy));
  }

  function loadingHint(kind, name) {
    if (kind === "restart" || name === "restart") {
      return "Restarting. Chat is paused until the API is ready.";
    }
    const label = String(name || "").trim();
    return label
      ? `Loading ${label}. Chat is paused until the model is ready.`
      : "The model is loading. Chat is paused until it is ready.";
  }

  function loadingLabel(kind, name) {
    if (kind === "restart" || name === "restart") return "Restarting";
    const label = String(name || "").trim();
    if (label === "comfy" || label === "flux") return "Loading Comfy";
    return label ? `Loading ${label}` : "Loading the model";
  }

  function paintLoadingElapsed() {
    const elapsed = modelLoadStarted ? Math.floor((Date.now() - modelLoadStarted) / 1000) : 0;
    const clock = elapsed >= 1 ? TabbyUI.formatDuration(elapsed) : "";
    if (loadingTimeEl) loadingTimeEl.textContent = clock;
    if (loadingTextEl && loadingHintText) {
      loadingTextEl.textContent = clock
        ? `${loadingHintText} ${clock} elapsed.`
        : loadingHintText;
    }
  }

  function startLoadingClock() {
    if (!modelLoadStarted) modelLoadStarted = Date.now();
    if (modelLoadTicker) return;
    paintLoadingElapsed();
    modelLoadTicker = setInterval(paintLoadingElapsed, 250);
  }

  function stopLoadingClock() {
    if (modelLoadTicker) {
      clearInterval(modelLoadTicker);
      modelLoadTicker = null;
    }
    modelLoadStarted = 0;
    loadingHintText = "";
    if (loadingTimeEl) loadingTimeEl.textContent = "";
  }

  function setLoadingBanner(text) {
    loadingHintText = String(text || "");
    if (loadingHintText) startLoadingClock();
    else stopLoadingClock();
    paintLoadingElapsed();
    if (loadingBar) loadingBar.hidden = !modelLoading;
  }

  function modelLooksReady(data, activity) {
    if (!data || statusIsBusy(data)) return false;
    const dest = String((activity && activity.target) || data.switch_target || "").toLowerCase();
    if (dest === "comfy" || dest === "flux") return Boolean(data.comfy_up);
    if (dest === "restart") {
      return Boolean(data.ok) && (Boolean(data.tabby_model) || Boolean(data.comfy_up) || Boolean(data.health && data.health.healthy));
    }
    return Boolean(data.tabby_model) || Boolean(data.model && (data.model.id || data.model.max_seq_len));
  }

  async function waitForModelReady(working, activity) {
    const target = (activity && activity.target) || "";
    const kind = (activity && activity.kind) || "switch";
    const started = Date.now();
    const deadline = started + 4 * 60 * 1000;
    let sawBusy = false;
    setLoadingBanner(loadingHint(kind, target));
    if (working) {
      working.setActivity(loadingLabel(kind, target), {
        processing: true,
        note: loadingHint(kind, target),
      });
    }
    while (Date.now() < deadline) {
      try {
        const data = await TabbyUI.api("status");
        rememberGpu(data);
        const name = (data && data.switch_target) || target;
        const nextKind = data && data.restarting ? "restart" : kind;
        if (statusIsBusy(data)) {
          sawBusy = true;
          setLoadingBanner(loadingHint(nextKind, name));
          if (working) {
            working.setActivity(loadingLabel(nextKind, name), {
              processing: true,
              note: loadingHint(nextKind, name),
            });
          }
        } else if (sawBusy) {
          if (working) working.setActivity("Ready", { processing: false, note: "The model is ready." });
          return true;
        } else if (Date.now() - started > 2500 && modelLooksReady(data, activity)) {
          if (working) working.setActivity("Ready", { processing: false, note: "The model is ready." });
          return true;
        }
      } catch {
        sawBusy = true;
        setLoadingBanner(loadingHint(kind, target));
        if (working) {
          working.setActivity(loadingLabel(kind, target), {
            processing: true,
            note: loadingHint(kind, target),
          });
        }
      }
      await sleep(1500);
    }
    if (working) {
      working.setActivity("Still loading", {
        processing: false,
        note: "The model is taking longer than expected.",
      });
    }
    return false;
  }

  function ensureModelWait(working, activity) {
    if (modelWait) return modelWait;
    modelLoading = true;
    paintCompose();
    modelWait = waitForModelReady(working, activity || { kind: "switch" }).finally(() => {
      modelWait = null;
      modelLoading = false;
      setLoadingBanner("");
      stopLoadingClock();
      paintCompose();
    });
    return modelWait;
  }

  async function syncModelGate() {
    if (modelWait) return;
    try {
      const data = await TabbyUI.api("status");
      rememberGpu(data);
      paintCompose();
      if (!statusIsBusy(data)) return;
      const target = data.switch_target || "";
      const kind = data.restarting ? "restart" : "switch";
      await ensureModelWait(null, { kind, target });
    } catch {
      /* status unavailable */
    }
  }

  function abortSession(kind) {
    stopKind = kind || "stop";
    if (abortController) abortController.abort();
  }

  function takeQueue() {
    const text = queuedText;
    queuedText = "";
    return text;
  }

  function queueFollowup(text) {
    queuedText = String(text || "").trim();
    paintCompose();
  }

  function paintCompose() {
    if (form) form.classList.toggle("is-loading", modelLoading);
    if (modelLoading) {
      if (queueBar) queueBar.hidden = true;
      if (comfyHint) comfyHint.hidden = true;
      if (steerBtn) {
        steerBtn.hidden = true;
        steerBtn.disabled = true;
      }
      if (loadingBar) loadingBar.hidden = false;
      if (!sendBtn) return;
      sendBtn.disabled = true;
      sendBtn.classList.add("primary");
      sendBtn.classList.remove("danger", "is-stop");
      sendBtn.setAttribute("aria-label", "Loading");
      sendBtn.textContent = "Loading";
      input.disabled = true;
      input.placeholder = "The model is loading. Chat is paused until it is ready.";
      if (editBar) editBar.hidden = pendingEditIndex < 0;
      return;
    }
    input.disabled = false;
    if (loadingBar) loadingBar.hidden = true;
    const action = tabbyChatComposeAction(inFlight, input.value, queuedText);
    const hasQueue = Boolean(queuedText);
    if (queueBar) queueBar.hidden = !hasQueue;
    if (queueTextEl) queueTextEl.textContent = queuedText;
    if (steerBtn) {
      steerBtn.hidden = !action.showSteer;
      steerBtn.disabled = !(inFlight && hasQueue);
    }
    if (!sendBtn) return;
    sendBtn.disabled = false;
    sendBtn.classList.toggle("primary", action.mode !== "stop");
    sendBtn.classList.toggle("danger", action.mode === "stop");
    sendBtn.classList.toggle("is-stop", action.mode === "stop");
    sendBtn.setAttribute("aria-label", action.label);
    if (action.mode === "stop") {
      sendBtn.innerHTML = `<span class="chat-stop-icon" aria-hidden="true"></span>${action.label}`;
    } else {
      sendBtn.textContent = action.label;
    }
    input.placeholder = inFlight
      ? hasQueue
        ? "Session running. Steer the queued message or type a replacement."
        : "Session running. Type a follow-up to queue it."
      : comfyOwnsGpu()
        ? "Describe a picture, or type a question to switch back to the LLM."
        : activeMode() === "code"
          ? CODE_PLACEHOLDER
          : DEFAULT_PLACEHOLDER;
    if (editBar) editBar.hidden = pendingEditIndex < 0;
    paintComfyHint();
  }

  function appendAssistantToChat(chatId, item) {
    if (store.activeId === chatId) {
      messages.push(item);
      persist();
      return;
    }
    const chat = store.chats.find((c) => c.id === chatId);
    if (!chat) return;
    chat.messages = cloneMessages(chat.messages);
    chat.messages.push(item);
    chat.title = titleFromMessages(chat.messages);
    chat.updatedAt = Date.now();
    if (persistReady) TabbyUI.api("chats", { method: "PUT", body: store }).catch(() => {});
  }

  async function send(text, opts) {
    const replay = Boolean(opts && opts.replay);
    const chatId = store.activeId;
    flightChatId = chatId;
    abortController = new AbortController();
    const outboundText = expandSlash(text);
    if (!replay) {
      if (pendingEditIndex >= 0) {
        const idx = pendingEditIndex;
        pendingEditIndex = -1;
        if (editBar) editBar.hidden = true;
        messages = messages.slice(0, idx);
        if (!messages.some((item) => item.role === "system")) messages.unshift({ ...SYSTEM });
      }
      const userItem = { role: "user", content: outboundText, createdAt: Date.now() };
      if (pendingImage) {
        userItem.imageData = pendingImage.dataUrl;
        userItem.imagePreview = pendingImage.preview || pendingImage.dataUrl;
        userItem.imageName = pendingImage.name;
      }
      messages.push(userItem);
      clearPendingImage();
      touchActive();
      persist();
      renderLog();
    } else {
      persist();
      renderLog();
    }
    const activity = activityFromPrompt(outboundText);
    const working = addWorkingReply(activity);
    const poll = startStatusPoll(working, activity.kind);
    let assembled = "";
    let reasoning = "";
    let elapsedSec = null;
    let statusLabel = "";
    const outbound = outboundMessages();
    const body = { messages: outbound, stream: true };
    if (settings.temperature != null) body.temperature = settings.temperature;
    if (activeMode() === "code") {
      body.mode = "code";
      body.chat_id = chatId;
    }
    try {
      const response = await fetch(TabbyUI.path("chat"), {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", Accept: "text/event-stream, application/json" },
        body: JSON.stringify(body),
        signal: abortController.signal,
      });
      if (response.status === 401) {
        poll.stop();
        working.stopClock();
        persist();
        window.location.href = TabbyUI.path("login");
        return;
      }
      const type = response.headers.get("content-type") || "";
      if (type.includes("application/json")) {
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "Chat failed");
        assembled = data.choices?.[0]?.message?.content || data.message || JSON.stringify(data);
        reasoning = data.choices?.[0]?.message?.reasoning_content || "";
        if (reasoning) working.setReasoning(reasoning);
        if (assembled) working.setAnswer(assembled);
      } else {
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buf = "";
        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          buf += decoder.decode(value, { stream: true });
          buf = consumeSseBuffer(buf, (event) => {
            if (event.comment && event.comment.includes("tabby-image-status:")) {
              const label = event.comment.replace(/^[\s\S]*tabby-image-status:\s*/i, "").trim();
              if (label) working.setActivity(label, { processing: true });
              if (/^(?:Writing|Editing|Deleting) \S/.test(label) && store.activeId === chatId) {
                refreshFilesSoon();
              }
            }
            if (event.reasoning) {
              reasoning += event.reasoning;
              working.setReasoning(reasoning);
            }
            if (visibleAnswerText(event.content)) {
              assembled += event.content;
              working.setAnswer(assembled);
            } else if (event.content) {
              // Preserve whitespace-only chunks for final assembly without
              // promoting an empty bubble.
              assembled += event.content;
            }
          });
        }
      }
    } catch (err) {
      const aborted = Boolean(err && err.name === "AbortError");
      if (aborted) {
        if (!stopKind) stopKind = "stop";
      } else {
        assembled = assembled || `Error: ${err.message}`;
      }
    }
    let stoppedEmpty = false;
    poll.stop();
    const waitingOnModel = activity.kind === "switch" || activity.kind === "restart";
    if (waitingOnModel) {
      await ensureModelWait(working, activity);
    }
    stoppedEmpty = Boolean(stopKind) && !waitingOnModel && !String(assembled || "").trim() && !reasoning;
    if (stoppedEmpty) {
      working.discard();
    } else {
      const done = working.finish({ content: assembled, reasoning });
      if (done && done.reasoning) reasoning = done.reasoning;
      if (done && done.elapsed_s) elapsedSec = done.elapsed_s;
      if (done && done.status_label) statusLabel = done.status_label;
    }
    if (String(assembled || "").trim() || reasoning) {
      const item = { role: "assistant", content: assembled, createdAt: Date.now() };
      if (reasoning) item.reasoning = reasoning;
      if (elapsedSec) item.elapsed_s = elapsedSec;
      if (statusLabel) item.status_label = statusLabel;
      appendAssistantToChat(chatId, item);
      if (store.activeId === chatId && !stoppedEmpty) {
        attachMsgActions(working.node, "assistant", messages.length - 1, assembled);
      }
    } else if (store.activeId === chatId) {
      persist();
    }
    if (chatMode(store.chats.find((item) => item.id === chatId)) === "code") {
      refreshFiles();
    }
  }

  async function runLoop(firstText, opts) {
    if (modelLoading && !loopBusy) return;
    if (loopBusy) {
      if (modelLoading) return;
      if (firstText && !(opts && opts.replay)) queueFollowup(firstText);
      return;
    }
    loopBusy = true;
    inFlight = true;
    paintCompose();
    try {
      let next = firstText;
      let sendOpts = opts;
      while (next) {
        stopKind = "";
        await send(next, sendOpts);
        sendOpts = undefined;
        if (stopKind === "steer") {
          next = takeQueue();
          continue;
        }
        if (stopKind === "stop") {
          if (queuedText && store.activeId === flightChatId && !input.value.trim()) {
            input.value = takeQueue();
          } else {
            queuedText = "";
          }
          break;
        }
        next = takeQueue();
      }
    } finally {
      inFlight = false;
      loopBusy = false;
      abortController = null;
      flightChatId = "";
      paintCompose();
      input.focus();
    }
  }

  root.querySelector("#chat-new").addEventListener("click", startNewChat);
  root.querySelector("#chat-clear").addEventListener("click", clearHistory);

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (modelLoading) return;
    if (!menu.hidden && menuItems[menuIndex]) {
      if (!applyCommand(menuItems[menuIndex])) return;
    }
    hideHistoryMenu();
    const text = input.value.trim();
    if (inFlight) {
      if (text) {
        resetRecall();
        input.value = "";
        hideMenu();
        queueFollowup(text);
      }
      return;
    }
    if (!text && !pendingImage) return;
    resetRecall();
    input.value = "";
    resizeInput();
    hideMenu();
    runLoop(text).catch((err) => {
      addBubble("assistant", `Error: ${err.message}`);
      persist();
    });
  });
  if (switchLlmBtn) {
    switchLlmBtn.addEventListener("click", () => {
      startLlmSwitch();
    });
  }
  sendBtn.addEventListener("click", (event) => {
    if (!inFlight) return;
    if (input.value.trim()) return;
    event.preventDefault();
    abortSession("stop");
  });
  steerBtn.addEventListener("click", () => {
    if (!inFlight || !queuedText) return;
    abortSession("steer");
  });
  queueClearBtn.addEventListener("click", () => {
    queuedText = "";
    paintCompose();
    input.focus();
  });
  input.addEventListener("input", () => {
    if (input.value.startsWith("/")) {
      hideHistoryMenu();
      renderMenu();
    } else {
      hideMenu();
      if (!historyMenu.hidden && input.value) hideHistoryMenu();
    }
    paintCompose();
    resizeInput();
  });
  input.addEventListener("keydown", (event) => {
    if (!menu.hidden && menuItems.length) {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        menuIndex = (menuIndex + 1) % menuItems.length;
        highlightMenu(menu, menuIndex);
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        menuIndex = (menuIndex - 1 + menuItems.length) % menuItems.length;
        highlightMenu(menu, menuIndex);
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
    if (!historyMenu.hidden) {
      if (event.key === "ArrowDown" && !event.altKey && !event.ctrlKey && !event.metaKey) {
        event.preventDefault();
        moveHistoryHighlight(1);
        return;
      }
      if (event.key === "ArrowUp" && !event.altKey && !event.ctrlKey && !event.metaKey) {
        event.preventDefault();
        moveHistoryHighlight(-1);
        return;
      }
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        applyHistorySelection();
        return;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        hideHistoryMenu();
        return;
      }
    }
    if (event.key === "ArrowUp" && !event.shiftKey && !event.altKey && !event.ctrlKey && !event.metaKey) {
      if (recallIndex >= 0 || !input.value || caretOnFirstLine()) {
        if (stepRecall(-1)) {
          event.preventDefault();
          hideHistoryMenu();
          return;
        }
      }
    }
    if (event.key === "ArrowDown" && !event.shiftKey && !event.altKey && !event.ctrlKey && !event.metaKey) {
      if (recallIndex >= 0 || !input.value || caretOnLastLine()) {
        if (stepRecall(1)) {
          event.preventDefault();
          hideHistoryMenu();
          return;
        }
      }
    }
    if (event.key === "Escape") {
      hideHistoryMenu();
      hideMenu();
      hideMoreMenu();
      if (pendingEditIndex >= 0) cancelEdit();
      return;
    }
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (modelLoading) return;
      form.requestSubmit();
    }
  });

  log.addEventListener("click", (event) => {
    const actBtn = event.target.closest("[data-act]");
    if (actBtn && log.contains(actBtn)) {
      event.preventDefault();
      const act = actBtn.dataset.act;
      const idx = Number(actBtn.dataset.idx);
      const item = messages[idx];
      if (act === "copy" && item) {
        const text = item.role === "assistant" && TabbyUI.formatAssistantContent
          ? TabbyUI.formatAssistantContent(item.content)
          : item.content;
        copyText(text, actBtn);
        return;
      }
      if (act === "edit") beginEdit(idx);
      if (act === "delete") deleteTurn(idx);
      if (act === "split") splitAfterTurn(idx);
      if (act === "regen" || act === "retry") regenerateLast();
      return;
    }
    const btn = event.target.closest(".md-code-copy");
    if (!btn || !log.contains(btn)) return;
    event.preventDefault();
    const block = btn.closest(".md-code");
    const code = block && block.querySelector("code");
    if (!code) return;
    copyText(code.textContent || "", btn);
  });
  log.addEventListener("mouseup", (event) => {
    if (event.target.closest("button, a, textarea, input")) return;
    const sel = window.getSelection();
    if (sel && String(sel).trim()) return;
    if (!followLog && !nearBottom()) return;
    input.focus();
  });
  log.addEventListener("scroll", () => {
    followLog = nearBottom();
    paintJump();
  }, { passive: true });
  if (jumpBtn) {
    jumpBtn.addEventListener("click", () => {
      stickLog(true);
      input.focus();
    });
  }
  titleEl.addEventListener("click", () => beginRename());
  root.querySelector("#chat-sidebar-toggle").addEventListener("click", () => {
    if (isNarrowChat()) {
      setSidebarOpen(!shell.classList.contains("is-sidebar-open"));
      return;
    }
    setSidebarHidden(!shell.classList.contains("is-sidebar-hidden"));
  });
  root.querySelector("#chat-backdrop").addEventListener("click", () => setSidebarOpen(false));
  if (searchEl) {
    searchEl.addEventListener("input", () => renderSidebar());
  }
  navList.addEventListener("click", (event) => {
    const tool = event.target.closest("[data-nav]");
    const row = event.target.closest(".chat-nav");
    if (!row) return;
    const id = row.dataset.id;
    if (tool) {
      event.preventDefault();
      event.stopPropagation();
      if (tool.dataset.nav === "pin") togglePin(id);
      if (tool.dataset.nav === "rename") {
        loadChat(id);
        beginRename(id);
      }
      if (tool.dataset.nav === "delete") deleteChat(id);
      return;
    }
    loadChat(id);
  });
  navList.addEventListener("keydown", (event) => {
    const row = event.target.closest(".chat-nav");
    if (!row || event.target.closest("[data-nav]")) return;
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      loadChat(row.dataset.id);
    }
  });
  moreBtn.addEventListener("click", () => {
    const open = moreMenu.hidden;
    hideHistoryMenu();
    moreMenu.hidden = !open;
    moreBtn.setAttribute("aria-expanded", open ? "true" : "false");
  });
  moreMenu.addEventListener("click", (event) => {
    const btn = event.target.closest("[data-more]");
    if (!btn) return;
    hideMoreMenu();
    const act = btn.dataset.more;
    if (act === "rename") beginRename();
    if (act === "pin") togglePin();
    if (act === "export") exportChat();
    if (act === "copy") copyText(conversationMarkdown(), btn);
    if (act === "regen") regenerateLast();
    if (act === "settings") showSettings();
    if (act === "keys") showShortcuts();
    if (act === "sidebar") {
      setSidebarHidden(!shell.classList.contains("is-sidebar-hidden"));
    }
    if (act === "delete") deleteChat(store.activeId);
  });
  root.querySelector("#chat-mode").addEventListener("click", (event) => {
    const btn = event.target.closest("[data-mode]");
    if (!btn || modelLoading) return;
    setChatMode(btn.dataset.mode);
  });
  if (filesTree) {
    filesTree.addEventListener("click", async (event) => {
      const btn = event.target.closest("[data-file]");
      if (!btn) return;
      const row = btn.closest(".chat-file");
      const path = row && row.dataset.path;
      if (!path) return;
      if (btn.dataset.file === "open") {
        if (path === filesSelected) return;
        if (previewDirty && !(await confirmDropEdits())) return;
        filesSelected = path;
        previewPath = "";
        previewOriginal = null;
        previewDirty = false;
        paintFiles();
        return;
      }
      if (btn.dataset.file === "download") {
        saveUrl(fileUrl(store.activeId, path), path.split("/").pop() || "file");
        return;
      }
      if (btn.dataset.file === "delete") {
        try {
          const data = await TabbyUI.api(
            `workspace/${encodeURIComponent(store.activeId)}/file?path=${encodeURIComponent(path)}`,
            { method: "DELETE" }
          );
          filesListing = Array.isArray(data.files) ? data.files : [];
          filesEntry = typeof data.entry === "string" ? data.entry : "";
          if (filesSelected === path) {
            filesSelected = "";
            previewPath = "";
            previewOriginal = null;
            previewDirty = false;
          }
          paintFiles();
        } catch (err) {
          addBubble("assistant", `Error: ${err.message}`);
        }
      }
    });
  }
  if (filesPreview) {
    filesPreview.addEventListener("input", (event) => {
      if (!event.target.classList.contains("chat-files-edit")) return;
      const next = previewOriginal !== null && event.target.value !== previewOriginal;
      if (next === previewDirty) return;
      previewDirty = next;
      paintEditorState();
      setPreviewNote("");
    });
    filesPreview.addEventListener("keydown", (event) => {
      if (!event.target.classList.contains("chat-files-edit")) return;
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        savePreview();
        return;
      }
      // Tab indents code instead of leaving the box; Shift+Tab still moves focus out.
      if (
        event.key === "Tab" &&
        !event.shiftKey &&
        !event.ctrlKey &&
        !event.metaKey &&
        !event.altKey
      ) {
        event.preventDefault();
        const box = event.target;
        const at = box.selectionStart;
        box.setRangeText("  ", at, box.selectionEnd, "end");
        box.dispatchEvent(new Event("input", { bubbles: true }));
      }
    });
    filesPreview.addEventListener("click", (event) => {
      const btn = event.target.closest("[data-edit]");
      if (!btn) return;
      if (btn.dataset.edit === "save") savePreview();
      if (btn.dataset.edit === "revert") revertPreview();
    });
  }
  if (filesSiteBtn) {
    filesSiteBtn.addEventListener("click", () => openSite());
  }
  if (filesRefreshBtn) {
    filesRefreshBtn.addEventListener("click", () => refreshFiles());
  }
  if (filesZipBtn) {
    filesZipBtn.addEventListener("click", async () => {
      if (!filesListing.length) return;
      try {
        const response = await fetch(TabbyUI.path(`workspace/${encodeURIComponent(store.activeId)}/zip`), {
          credentials: "same-origin",
        });
        if (!response.ok) throw new Error("Could not download the zip.");
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        saveUrl(url, `${downloadStem()}.zip`);
        setTimeout(() => URL.revokeObjectURL(url), 10_000);
      } catch (err) {
        addBubble("assistant", `Error: ${err.message}`);
      }
    });
  }
  if (filesClearBtn) {
    filesClearBtn.addEventListener("click", async () => {
      const yes = await TabbyUI.confirmModal({
        title: "Clear files",
        text: "Delete every file in this chat's project?",
        yes: "Clear",
        no: "Cancel",
      });
      if (!yes) return;
      try {
        await TabbyUI.api(`workspace/${encodeURIComponent(store.activeId)}`, { method: "DELETE" });
        filesListing = [];
        filesSelected = "";
        filesEntry = "";
        previewDirty = false;
        paintFiles();
      } catch (err) {
        addBubble("assistant", `Error: ${err.message}`);
      }
    });
  }
  emptyEl.addEventListener("click", (event) => {
    const btn = event.target.closest("[data-suggest]");
    if (!btn || modelLoading) return;
    input.value = btn.dataset.suggest || "";
    resizeInput();
    form.requestSubmit();
  });
  root.querySelector("#chat-edit-cancel").addEventListener("click", cancelEdit);
  root.querySelector("#chat-attach-btn").addEventListener("click", () => {
    if (modelLoading) return;
    if (fileInput) fileInput.click();
  });
  root.querySelector("#chat-attach-clear").addEventListener("click", () => {
    clearPendingImage();
    input.focus();
  });
  fileInput.addEventListener("change", () => {
    const file = fileInput.files && fileInput.files[0];
    setPendingImageFromFile(file).catch((err) => {
      addBubble("assistant", `Error: ${err.message}`);
    });
  });
  input.addEventListener("paste", (event) => {
    const items = event.clipboardData && event.clipboardData.items;
    if (!items) return;
    for (const item of items) {
      if (item.kind === "file" && /^image\//.test(item.type)) {
        event.preventDefault();
        setPendingImageFromFile(item.getAsFile()).catch((err) => {
          addBubble("assistant", `Error: ${err.message}`);
        });
        return;
      }
    }
  });
  form.addEventListener("dragover", (event) => {
    if (Array.from(event.dataTransfer.types || []).includes("Files")) {
      event.preventDefault();
      form.classList.add("is-drop");
    }
  });
  form.addEventListener("dragleave", () => form.classList.remove("is-drop"));
  form.addEventListener("drop", (event) => {
    event.preventDefault();
    form.classList.remove("is-drop");
    const file = event.dataTransfer && event.dataTransfer.files && event.dataTransfer.files[0];
    setPendingImageFromFile(file).catch((err) => {
      addBubble("assistant", `Error: ${err.message}`);
    });
  });
  const Speech = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (Speech && micBtn) {
    micBtn.hidden = false;
    let rec = null;
    micBtn.addEventListener("click", () => {
      if (rec) {
        rec.stop();
        rec = null;
        micBtn.classList.remove("is-live");
        return;
      }
      rec = new Speech();
      rec.lang = navigator.language || "en-US";
      rec.interimResults = true;
      rec.onresult = (ev) => {
        let spoken = "";
        for (let i = ev.resultIndex; i < ev.results.length; i += 1) {
          spoken += ev.results[i][0].transcript;
        }
        if (spoken) {
          input.value = input.value ? `${input.value.trim()} ${spoken}` : spoken;
          resizeInput();
          paintCompose();
        }
      };
      rec.onend = () => {
        rec = null;
        micBtn.classList.remove("is-live");
      };
      rec.onerror = () => {
        rec = null;
        micBtn.classList.remove("is-live");
      };
      rec.start();
      micBtn.classList.add("is-live");
    });
  }

  window.addEventListener("beforeunload", persist);
  document.addEventListener("pointerdown", onPointerDownAway);
  document.addEventListener("keydown", onGlobalKey);
  async function loadStore() {
    let incoming = null;
    try {
      incoming = await TabbyUI.api("chats");
    } catch {
      incoming = null;
    }
    const serverEmpty = !incoming || !Array.isArray(incoming.chats) || !incoming.chats.some(hasUserTurn);
    if (serverEmpty) {
      const legacy = readStore();
      if (legacy.chats.some(hasUserTurn)) incoming = legacy;
    }
    try {
      localStorage.removeItem(STORAGE_KEY);
    } catch {
      /* ignore */
    }
    store = normalizeStore(incoming);
    messages = cloneMessages(store.chats.find((chat) => chat.id === store.activeId).messages);
    persistReady = true;
    persist();
    renderLog();
    paintToolbar();
    renderSidebar();
    paintCompose();
    resizeInput();
    refreshFiles();
    syncModelGate();
  }
  loadStore();
  return {
    pause() {
      hideHistoryMenu();
      hideMoreMenu();
      setSidebarOpen(false);
    },
    resume() {
      syncModelGate();
      refreshFiles();
    },
    destroy() {
      abortSession("stop");
      stopLoadingClock();
      if (filesRefreshTimer) clearTimeout(filesRefreshTimer);
      persist();
      hideHistoryMenu();
      hideMoreMenu();
      document.removeEventListener("pointerdown", onPointerDownAway);
      document.removeEventListener("keydown", onGlobalKey);
      window.removeEventListener("beforeunload", persist);
    },
  };
}

window.mountChat = mountChat;
window.tabbyChatComposeAction = tabbyChatComposeAction;
window.tabbyLooksLikeChatNotImage = tabbyLooksLikeChatNotImage;
