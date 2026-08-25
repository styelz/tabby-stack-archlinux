function tabbyChatComposeAction(inFlight, typed, queued) {
  const text = String(typed || "").trim();
  const hasQueue = Boolean(String(queued || "").trim());
  if (!inFlight) return { mode: "send", label: "Send", showSteer: false };
  if (text) return { mode: "queue", label: "Queue", showSteer: hasQueue };
  return { mode: "stop", label: "Stop", showSteer: hasQueue };
}

// sse-starlette keep-alives look like "ping - 2026-08-24 21:42:59.522485+00:00".
function tabbyIsSsePing(text) {
  return /^ping\s*-\s*\d{4}-\d{2}-\d{2}[T\s]\d/i.test(String(text || "").trim());
}

function tabbyCleanStatusLabel(text) {
  return String(text || "")
    .split(/\r?\n/)
    .map((line) => line.replace(/^:\s*/, "").trim())
    .filter((line) => line && !tabbyIsSsePing(line))
    .join(" ")
    .trim();
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

// One left-pointing chevron; the rail toggles rotate it to mean "collapse"
// or "expand" on whichever side they sit.
const CHEVRON_SVG =
  '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="m15 5-7 7 7 7" /></svg>';

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
          <button class="rail-toggle" type="button" id="chat-sidebar-toggle" aria-label="Hide sidebar" title="Hide sidebar">${CHEVRON_SVG}</button>
          <span class="chat-title" id="chat-title">New chat</span>
          <div class="chat-mode" id="chat-mode" role="group" aria-label="Chat mode">
            <button type="button" class="chat-mode-btn is-active" data-mode="chat">Chat</button>
            <button type="button" class="chat-mode-btn" data-mode="code">Code</button>
          </div>
          <span class="spacer"></span>
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
          <button class="rail-toggle" type="button" id="chat-files-toggle" hidden aria-expanded="true" aria-controls="chat-files" aria-label="Hide files" title="Hide files">${CHEVRON_SVG}</button>
        </div>
        <div class="chat-view">
          <div class="chat-tabs" id="chat-tabs" role="tablist" aria-label="Open files" hidden></div>
          <div class="chat-log-wrap" id="chat-log-wrap">
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
          <section class="chat-editor" id="chat-editor" aria-label="File editor" hidden></section>
        </div>
        <div class="chat-compose">
          <ul class="slash-menu" id="history-menu" hidden></ul>
          <ul class="slash-menu" id="slash-menu" hidden></ul>
          <div class="chat-edit-bar" id="chat-edit-bar" hidden>
            <span>Editing a sent message. Send replaces that turn.</span>
            <button class="btn ghost" type="button" id="chat-edit-cancel">Cancel</button>
          </div>
          <div class="chat-attach" id="chat-attach" hidden>
            <div class="chat-attach-list" id="chat-attach-list"></div>
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
          <div class="chat-loading" id="chat-waiting" hidden>
            <span class="chat-loading-mark">Queued</span>
            <span class="chat-loading-text" id="chat-waiting-text">The stack is being used. You are in a queue.</span>
            <span class="chat-loading-time" id="chat-waiting-time"></span>
          </div>
          <div class="chat-comfy-hint" id="chat-comfy-hint" hidden>
            <span class="chat-comfy-hint-mark">Comfy</span>
            <span class="chat-comfy-hint-text" id="chat-comfy-hint-text">This looks like a chat, not a picture. Switch to the coding model?</span>
            <button class="btn primary" type="button" id="chat-switch-llm">Switch to LLM</button>
          </div>
          <form class="chat-form" id="chat-form">
            <textarea id="chat-input" rows="3" placeholder="Talk to the loaded model. Type / for commands. ↑↓ recalls what you sent."></textarea>
            <input id="chat-file" type="file" accept="image/png,image/jpeg,image/webp,image/gif" hidden />
            <input id="chat-upload" type="file" multiple accept=".html,.htm,.css,.js,.mjs,.json,.jsx,.ts,.tsx,.md,.txt,.svg,.xml,.yml,.yaml,.csv,.py,.sh,.php,.toml,.ini,.conf,.png,.jpg,.jpeg,.webp,.gif,image/png,image/jpeg,image/webp,image/gif,text/plain,text/html,text/css,text/javascript,application/json" hidden />
            <div class="chat-form-actions">
              <div class="chat-attach-wrap">
                <button class="btn ghost chat-icon" type="button" id="chat-attach-btn" aria-haspopup="true" aria-expanded="false" aria-label="Attach image" title="Attach image">📎</button>
                <div class="chat-attach-menu" id="chat-attach-menu" hidden></div>
              </div>
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
          <button class="btn ghost" type="button" id="chat-files-new" title="Create a new text file">New</button>
          <button class="btn ghost" type="button" id="chat-files-upload" title="Add files from this computer">Upload</button>
          <button class="btn ghost chat-icon" type="button" id="chat-files-refresh" aria-label="Refresh files" title="Refresh files">⟳</button>
          <button class="btn" type="button" id="chat-files-site">Open site</button>
          <button class="btn ghost" type="button" id="chat-files-zip">Zip</button>
          <button class="btn ghost" type="button" id="chat-files-clear">Clear</button>
          <button class="btn ghost chat-icon chat-files-close" type="button" id="chat-files-close" aria-label="Hide files" title="Hide files">×</button>
        </div>
        <div class="chat-files-tree" id="chat-files-tree"></div>
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
  const attachList = root.querySelector("#chat-attach-list");
  const attachBtn = root.querySelector("#chat-attach-btn");
  const attachMenu = root.querySelector("#chat-attach-menu");
  const fileInput = root.querySelector("#chat-file");
  const uploadInput = root.querySelector("#chat-upload");
  const micBtn = root.querySelector("#chat-mic");
  const countEl = root.querySelector("#chat-count");
  const loadingBar = root.querySelector("#chat-loading");
  const loadingTextEl = root.querySelector("#chat-loading-text");
  const loadingTimeEl = root.querySelector("#chat-loading-time");
  const waitingBar = root.querySelector("#chat-waiting");
  const waitingTextEl = root.querySelector("#chat-waiting-text");
  const waitingTimeEl = root.querySelector("#chat-waiting-time");
  const comfyHint = root.querySelector("#chat-comfy-hint");
  const switchLlmBtn = root.querySelector("#chat-switch-llm");
  const filesPane = root.querySelector("#chat-files");
  const filesTree = root.querySelector("#chat-files-tree");
  const tabsBar = root.querySelector("#chat-tabs");
  const logWrap = root.querySelector("#chat-log-wrap");
  const editorPane = root.querySelector("#chat-editor");
  const filesZipBtn = root.querySelector("#chat-files-zip");
  const filesClearBtn = root.querySelector("#chat-files-clear");
  const filesNewBtn = root.querySelector("#chat-files-new");
  const filesUploadBtn = root.querySelector("#chat-files-upload");
  const filesRefreshBtn = root.querySelector("#chat-files-refresh");
  const filesCountEl = root.querySelector("#chat-files-count");
  const filesSiteBtn = root.querySelector("#chat-files-site");
  const filesToggleBtn = root.querySelector("#chat-files-toggle");
  const filesCloseBtn = root.querySelector("#chat-files-close");
  const DEFAULT_PLACEHOLDER = input.getAttribute("placeholder") || "";
  let filesListing = [];
  let filesSelected = "";
  let filesEntry = "";
  // Code mode opens files as tabs beside Chat in the main column. Each tab keeps
  // its own buffer so switching away does not throw away unsaved edits.
  let openTabs = [];
  let activeTab = "";
  let tabsChat = "";
  let logScroll = 0;
  // Chat ids the server says own project files. Drives the sidebar badge in
  // both modes, so it survives a reload and covers chats not opened yet.
  let codeChats = new Set();
  const menu = root.querySelector("#slash-menu");
  const historyMenu = root.querySelector("#history-menu");
  const titleEl = root.querySelector("#chat-title");
  const SYSTEM = { role: "system", content: "Console chat. No file tools." };
  const CODE_PLACEHOLDER = "Describe the page or files to create, or attach files from the Files pane.";
  const TEXT_SUFFIXES = new Set([
    ".html", ".htm", ".css", ".js", ".mjs", ".json", ".jsx", ".ts", ".tsx",
    ".md", ".txt", ".svg", ".xml", ".yml", ".yaml", ".csv", ".py", ".sh",
    ".php", ".toml", ".ini", ".conf",
  ]);
  const IMAGE_SUFFIXES = new Set([".png", ".jpg", ".jpeg", ".webp", ".gif"]);
  const ATTACH_TEXT_LIMIT = 80_000;
  const MAX_ATTACH = 12;
  const STORAGE_KEY = "tabby-ui-chat-store";
  const SETTINGS_KEY = "tabby-ui-chat-settings";
  const SIDEBAR_KEY = "tabby-ui-chat-sidebar";
  const FILES_KEY = "tabby-ui-chat-files";
  const MAX_CHATS = 50;
  const narrowChat = window.matchMedia("(max-width: 900px)");
  // Below 900px the pane is a bottom sheet over the chat, so it starts closed
  // there no matter what the desktop preference says.
  let filesOpen = narrowChat.matches ? false : readFilesOpen();

  function readFilesOpen() {
    try {
      return localStorage.getItem(FILES_KEY) !== "closed";
    } catch {
      return true;
    }
  }

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

  function emptyLastByMode(raw) {
    const last = raw && raw.lastByMode && typeof raw.lastByMode === "object" ? raw.lastByMode : {};
    return {
      chat: String(last.chat || ""),
      code: String(last.code || ""),
    };
  }

  function activeMode() {
    return chatMode(activeChat());
  }

  function rememberActiveMode() {
    const chat = activeChat();
    if (!chat) return;
    if (!store.lastByMode) store.lastByMode = emptyLastByMode(null);
    store.lastByMode[chatMode(chat)] = chat.id;
  }

  function chatForMode(mode) {
    const want = mode === "code" ? "code" : "chat";
    const remembered = store.lastByMode && store.lastByMode[want];
    const hit = remembered
      && store.chats.find((item) => item.id === remembered && chatMode(item) === want);
    if (hit && (hasUserTurn(hit) || hit.pinned || hit.id === store.activeId)) return hit;
    return store.chats
      .filter((item) => chatMode(item) === want && (hasUserTurn(item) || item.pinned))
      .sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0))[0] || null;
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
        const status = tabbyCleanStatusLabel(item.status_label);
        if (status) out.status_label = status;
      }
      if (item.createdAt) out.createdAt = Number(item.createdAt) || 0;
      if (item.imageData && String(item.imageData).startsWith("data:image")) {
        out.imageData = String(item.imageData);
      }
      if (item.imagePreview) out.imagePreview = String(item.imagePreview);
      if (item.imageName) out.imageName = String(item.imageName);
      if (Array.isArray(item.attachedFiles) && item.attachedFiles.length) {
        out.attachedFiles = item.attachedFiles.slice(0, MAX_ATTACH).map((file) => {
          const path = String((file && file.path) || "").slice(0, 240);
          const kind = file && file.kind === "image" ? "image" : "text";
          const row = { path, kind };
          if (kind === "text" && typeof file.text === "string") {
            row.text = file.text.length > ATTACH_TEXT_LIMIT
              ? `${file.text.slice(0, ATTACH_TEXT_LIMIT)}\n…(truncated)`
              : file.text;
          }
          if (kind === "image") {
            if (file.dataUrl && String(file.dataUrl).startsWith("data:image")) {
              row.dataUrl = String(file.dataUrl);
            }
            if (file.preview) row.preview = String(file.preview);
          }
          return row;
        }).filter((file) => file.path);
      }
      return out;
    });
  }

  function titleFromMessages(list) {
    const first = (list || []).find((item) => item.role === "user" && userTurnHasContent(item));
    if (!first) return "New chat";
    const text = String(first.content || "").replace(/\s+/g, " ").trim();
    if (text) return text.slice(0, 56);
    const names = (first.attachedFiles || []).map((file) => file.path).filter(Boolean);
    return names.length ? names.join(", ").slice(0, 56) : "New chat";
  }

  function userTurnHasContent(item) {
    if (!item || item.role !== "user") return false;
    if (String(item.content || "").trim()) return true;
    if (item.imageData) return true;
    return Array.isArray(item.attachedFiles) && item.attachedFiles.length > 0;
  }

  function hasUserTurn(chat) {
    return (chat.messages || []).some((item) => userTurnHasContent(item));
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
    const lastByMode = emptyLastByMode(raw);
    if (!chats.some((chat) => chat.id === lastByMode.chat && chatMode(chat) === "chat")) {
      lastByMode.chat = "";
    }
    if (!chats.some((chat) => chat.id === lastByMode.code && chatMode(chat) === "code")) {
      lastByMode.code = "";
    }
    return { version: 1, activeId, chats, lastByMode };
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
  let pendingFiles = [];
  let uploadWantsAttach = false;
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
    const mode = activeMode();
    const q = String((searchEl && searchEl.value) || "").trim().toLowerCase();
    return store.chats
      .filter((chat) => chatMode(chat) === mode)
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
    rememberActiveMode();
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
      // Points at the edge it would move the pane toward.
      toggleBtn.classList.toggle("is-flipped", hidden);
      toggleBtn.setAttribute("aria-expanded", hidden ? "false" : "true");
      toggleBtn.setAttribute("aria-label", hidden ? "Show sidebar" : "Hide sidebar");
      toggleBtn.title = hidden ? "Show sidebar" : "Hide sidebar";
    }
    paintMode();
    paintEmpty();
  }

  function paintMode() {
    const mode = activeMode();
    const code = mode === "code";
    shell.classList.toggle("is-code", code);
    shell.classList.toggle("is-files-open", code && filesOpen);
    root.querySelectorAll(".chat-mode-btn").forEach((btn) => {
      const on = btn.dataset.mode === mode;
      btn.classList.toggle("is-active", on);
      btn.setAttribute("aria-pressed", on ? "true" : "false");
    });
    if (filesPane) filesPane.hidden = !code || !filesOpen;
    if (attachBtn) {
      attachBtn.setAttribute("aria-label", code ? "Attach files" : "Attach image");
      attachBtn.title = code ? "Attach image or project files" : "Attach image";
    }
    if (searchEl) searchEl.placeholder = code ? "Search code chats" : "Search chats";
    const newBtn = root.querySelector("#chat-new");
    if (newBtn) newBtn.textContent = code ? "New code chat" : "New chat";
    paintTabs();
    paintFilesToggle();
  }

  function paintFilesToggle() {
    if (!filesToggleBtn) return;
    const code = activeMode() === "code";
    filesToggleBtn.hidden = !code;
    if (!code) return;
    const count = filesListing.length;
    // Open means the chevron points right, the way the pane would fold away.
    filesToggleBtn.classList.toggle("is-flipped", filesOpen);
    // The file count lives in the pane header, so a closed pane keeps a dot.
    filesToggleBtn.classList.toggle("is-marked", !filesOpen && count > 0);
    filesToggleBtn.setAttribute("aria-expanded", filesOpen ? "true" : "false");
    const files = count === 1 ? "1 file" : `${count} files`;
    filesToggleBtn.setAttribute("aria-label", filesOpen ? "Hide files" : "Show files");
    filesToggleBtn.title = filesOpen ? "Hide the files pane" : `Show the files pane (${files})`;
  }

  function setFilesOpen(open) {
    filesOpen = !!open;
    // A phone visit should not overwrite the desktop choice.
    if (!narrowChat.matches) {
      try {
        localStorage.setItem(FILES_KEY, filesOpen ? "open" : "closed");
      } catch {
        /* ignore */
      }
    }
    paintMode();
    if (filesOpen) refreshFiles();
  }

  function setChatMode(mode) {
    const next = mode === "code" ? "code" : "chat";
    if (activeMode() === next) return;
    persist();
    const existing = chatForMode(next);
    if (existing) {
      loadChat(existing.id);
      return;
    }
    cancelEdit();
    clearPendingImage();
    const chat = emptyChat(next);
    store.chats.unshift(chat);
    store.activeId = chat.id;
    messages = cloneMessages(chat.messages);
    persist();
    resetRecall();
    renderLog();
    filesSelected = "";
    refreshFiles();
    hideHistoryMenu();
    hideMoreMenu();
    paintCompose();
    input.focus();
  }

  function renderSidebar() {
    if (!navList) return;
    const list = listedChats();
    if (!list.length) {
      navList.innerHTML = activeMode() === "code"
        ? '<div class="chat-nav-empty">No code chats match.</div>'
        : '<div class="chat-nav-empty">No chats match.</div>';
      return;
    }
    const frag = document.createDocumentFragment();
    list.forEach((item) => {
      const btn = document.createElement("div");
      btn.className = "chat-nav" + (item.id === store.activeId ? " is-active" : "") + (item.pinned ? " is-pinned" : "");
      btn.dataset.id = item.id;
      btn.setAttribute("role", "button");
      btn.tabIndex = 0;
      btn.innerHTML =
        `<span class="chat-nav-pin" aria-hidden="true">${item.pinned ? "★" : "☆"}</span>` +
        `<span class="chat-nav-title">${TabbyUI.escapeHtml(item.title || "New chat")}</span>` +
        `<span class="chat-nav-when">${TabbyUI.escapeHtml(timeLabel(item.updatedAt))}</span>` +
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
    const empty = !messages.some((item) => item.role === "assistant" || userTurnHasContent(item));
    emptyEl.hidden = !empty;
    if (!empty) return;
    const code = activeMode() === "code";
    const title = emptyEl.querySelector("#chat-empty-title");
    const copy = emptyEl.querySelector("#chat-empty-copy");
    const suggests = emptyEl.querySelector("#chat-suggests");
    if (title) title.textContent = code ? "Code mode" : "Console chat";
    if (copy) {
      copy.textContent = code
        ? "Ask for a page, logo, or set of files. Create or upload files in the Files pane, attach them to a message, or let the model write them. Images also show in Gallery."
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

  async function refreshCodeChats() {
    try {
      const data = await TabbyUI.api("workspaces");
      const next = new Set(Array.isArray(data.code) ? data.code.map(String) : []);
      if (next.size === codeChats.size && [...next].every((id) => codeChats.has(id))) return;
      codeChats = next;
      renderSidebar();
    } catch {
      /* the badge is cosmetic; leave what we already know */
    }
  }

  /** A listing we just fetched is authoritative for that one chat. */
  function noteChatFiles(chatId, hasFiles) {
    if (!chatId || codeChats.has(chatId) === Boolean(hasFiles)) return;
    if (hasFiles) codeChats.add(chatId);
    else codeChats.delete(chatId);
    renderSidebar();
  }

  function dropWorkspace(chatId) {
    if (!chatId) return;
    codeChats.delete(chatId);
    TabbyUI.api(`workspace/${encodeURIComponent(chatId)}`, { method: "DELETE" }).catch(() => {});
  }

  function fileUrl(chatId, path) {
    return TabbyUI.path(`workspace/${encodeURIComponent(chatId)}/file?path=${encodeURIComponent(path)}`);
  }

  function fileSuffix(path) {
    const name = String(path || "").split("/").pop() || "";
    const at = name.lastIndexOf(".");
    return at >= 0 ? name.slice(at).toLowerCase() : "";
  }

  function isPendingFile(path) {
    return pendingFiles.some((file) => file.path === path);
  }

  function applyListing(data) {
    filesListing = Array.isArray(data.files) ? data.files : filesListing;
    filesEntry = typeof data.entry === "string" ? data.entry : filesEntry;
    noteChatFiles(store.activeId, filesListing.length > 0);
    paintFiles();
  }

  function selectedRow() {
    return filesListing.find((row) => row.path === filesSelected) || null;
  }

  function paintFilesHead() {
    paintFilesToggle();
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
        '<p class="muted chat-files-empty">No files yet. Create one, upload, or ask for a page.</p>';
      return;
    }
    const frag = document.createDocumentFragment();
    filesListing.forEach((row) => {
      const item = document.createElement("div");
      item.className =
        "chat-file" +
        (row.path === filesSelected ? " is-active" : "") +
        (findTab(row.path) ? " is-open" : "") +
        (isPendingFile(row.path) ? " is-attached" : "");
      item.dataset.path = row.path;
      item.innerHTML =
        `<button type="button" class="chat-file-open" data-file="open" title="${TabbyUI.escapeHtml(row.path)}">${TabbyUI.escapeHtml(row.path)}</button>` +
        `<span class="chat-file-size">${TabbyUI.escapeHtml(TabbyUI.formatBytes(row.size))}</span>` +
        `<span class="chat-file-tools">` +
        `<button type="button" class="btn ghost chat-icon${isPendingFile(row.path) ? " is-on" : ""}" data-file="attach" aria-label="Add to chat" title="Add to chat">📎</button>` +
        `<button type="button" class="btn ghost chat-icon" data-file="download" aria-label="Download file" title="Download">↓</button>` +
        `<button type="button" class="btn ghost chat-icon danger" data-file="delete" aria-label="Delete file" title="Delete">×</button>` +
        `</span>`;
      frag.appendChild(item);
    });
    filesTree.replaceChildren(frag);
  }

  // Past this many characters the editor drops the highlight overlay; retinting
  // a huge file on every keystroke costs more than the colour is worth.
  const HIGHLIGHT_LIMIT = 120_000;

  function fileLang(path) {
    return window.TabbyHighlight ? window.TabbyHighlight.pathLanguage(path) : "";
  }

  function fileHighlight(path, text) {
    return window.TabbyHighlight
      ? window.TabbyHighlight.highlight(fileLang(path), text)
      : TabbyUI.escapeHtml(text);
  }

  function findTab(path) {
    return openTabs.find((tab) => tab.path === path) || null;
  }

  function activeTabRow() {
    return activeTab ? findTab(activeTab) : null;
  }

  function editorBox() {
    return editorPane ? editorPane.querySelector(".chat-files-edit") : null;
  }

  function tabLabel(tab) {
    const base = tab.path.split("/").pop() || tab.path;
    const clash = openTabs.some((other) => other !== tab && (other.path.split("/").pop() || "") === base);
    return clash ? tab.path : base;
  }

  function confirmDropEdits(path) {
    return TabbyUI.confirmModal({
      title: "Discard changes?",
      text: `${path} has edits you have not saved.`,
      yes: "Discard",
      no: "Keep editing",
    });
  }

  /** Keep the live textarea in the tab so a re-render or tab switch restores it. */
  function stashEditor() {
    const tab = activeTabRow();
    const box = editorBox();
    if (!tab || !box) return;
    tab.text = box.value;
    tab.scrollTop = box.scrollTop;
    tab.scrollLeft = box.scrollLeft;
    tab.caret = [box.selectionStart, box.selectionEnd];
  }

  function paintTabs() {
    if (!tabsBar) return;
    const show = activeMode() === "code" && openTabs.length > 0;
    tabsBar.hidden = !show;
    if (!show) return;
    const frag = document.createDocumentFragment();
    const chatTab = document.createElement("div");
    chatTab.className = "chat-tab" + (activeTab ? "" : " is-active");
    chatTab.dataset.tab = "";
    chatTab.innerHTML = '<button type="button" class="chat-tab-open">Chat</button>';
    frag.appendChild(chatTab);
    openTabs.forEach((tab) => {
      const name = TabbyUI.escapeHtml(tabLabel(tab));
      const item = document.createElement("div");
      item.className =
        "chat-tab" + (tab.path === activeTab ? " is-active" : "") + (tab.dirty ? " is-dirty" : "");
      item.dataset.tab = tab.path;
      item.innerHTML =
        `<button type="button" class="chat-tab-open" title="${TabbyUI.escapeHtml(tab.path)}">${name}</button>` +
        `<button type="button" class="chat-tab-close" data-tab-close aria-label="Close ${name}">×</button>`;
      frag.appendChild(item);
    });
    tabsBar.replaceChildren(frag);
  }

  function paintEditorHead() {
    if (!editorPane) return;
    const tab = activeTabRow();
    if (!tab) return;
    const size = editorPane.querySelector(".chat-editor-size");
    if (size) size.textContent = TabbyUI.formatBytes(tab.size);
    const note = editorPane.querySelector(".chat-editor-note");
    if (note) note.textContent = tab.gone && !tab.note ? "This file is no longer in the project." : tab.note;
    const save = editorPane.querySelector("[data-edit='save']");
    if (save) {
      save.disabled = !tab.dirty || tab.busy;
      save.textContent = tab.busy ? "Saving" : tab.dirty ? "Save" : "Saved";
    }
    const revert = editorPane.querySelector("[data-edit='revert']");
    if (revert) revert.hidden = !tab.dirty;
  }

  /** A reload keeps showing the text it already has instead of flashing. */
  function tabView(tab) {
    return tab.state === "loading" && tab.rev > 0 ? "ready" : tab.state;
  }

  function editorBodyHtml(tab, view) {
    if (view === "image") {
      const src = `${fileUrl(store.activeId, tab.path)}&v=${tab.size}`;
      return `<div class="chat-editor-body is-image"><img alt="" src="${TabbyUI.escapeHtml(src)}" /></div>`;
    }
    if (view === "binary") {
      return '<div class="chat-editor-body"><p class="muted">Download this file to open it.</p></div>';
    }
    if (view === "error") {
      return '<div class="chat-editor-body"><p class="muted">Could not read this file.</p></div>';
    }
    if (view !== "ready") {
      return '<div class="chat-editor-body"><p class="muted">Loading…</p></div>';
    }
    const plain = tab.text.length > HIGHLIGHT_LIMIT || !fileLang(tab.path);
    return (
      `<div class="code-edit${plain ? " is-plain" : ""}">` +
      '<div class="code-edit-gutter" aria-hidden="true"></div>' +
      '<div class="code-edit-main">' +
      '<pre class="code-hl" aria-hidden="true"><code></code></pre>' +
      '<textarea class="chat-files-edit" spellcheck="false" wrap="off" aria-label="File contents"></textarea>' +
      "</div></div>"
    );
  }

  function renderEditorPane() {
    if (!editorPane) return;
    const tab = activeTabRow();
    if (!tab) return;
    // Code turns repaint the listing every 600 ms; only rebuild when the file,
    // its state, or a reloaded revision actually changed, so typing survives.
    const view = tabView(tab);
    const key = `${store.activeId}|${tab.path}|${view}|${tab.rev}`;
    if (editorPane.dataset.key === key) {
      paintEditorHead();
      return;
    }
    editorPane.dataset.key = key;
    const lang = fileLang(tab.path);
    const tools =
      view === "ready"
        ? '<button type="button" class="btn ghost" data-edit="revert" hidden>Revert</button>' +
          '<button type="button" class="btn primary" data-edit="save" disabled>Saved</button>'
        : "";
    editorPane.innerHTML =
      '<div class="chat-editor-head">' +
      `<strong>${TabbyUI.escapeHtml(tab.path)}</strong>` +
      '<span class="chat-editor-size"></span>' +
      (lang ? `<span class="chat-editor-lang">${TabbyUI.escapeHtml(lang)}</span>` : "") +
      '<span class="spacer"></span>' +
      '<button type="button" class="btn ghost chat-icon" data-edit="download" aria-label="Download file" title="Download">↓</button>' +
      tools +
      "</div>" +
      editorBodyHtml(tab, view) +
      '<p class="muted chat-editor-note"></p>';
    const box = editorBox();
    if (box) {
      box.value = tab.text;
      paintHighlight();
      if (tab.caret) box.setSelectionRange(tab.caret[0], tab.caret[1]);
      box.scrollTop = tab.scrollTop || 0;
      box.scrollLeft = tab.scrollLeft || 0;
      syncEditorScroll();
    }
    paintEditorHead();
  }

  function syncEditorScroll() {
    const box = editorBox();
    if (!box) return;
    const pre = editorPane.querySelector(".code-hl");
    const gutter = editorPane.querySelector(".code-edit-gutter");
    if (pre) {
      pre.scrollTop = box.scrollTop;
      pre.scrollLeft = box.scrollLeft;
    }
    if (gutter) gutter.scrollTop = box.scrollTop;
  }

  function paintHighlight() {
    const tab = activeTabRow();
    const box = editorBox();
    if (!tab || !box) return;
    const wrap = editorPane.querySelector(".code-edit");
    const text = box.value;
    const gutter = editorPane.querySelector(".code-edit-gutter");
    if (gutter) {
      const lines = text.split("\n").length;
      if (gutter.dataset.lines !== String(lines)) {
        gutter.dataset.lines = String(lines);
        let acc = "";
        for (let n = 1; n <= lines; n += 1) acc += `${n}\n`;
        gutter.textContent = acc;
      }
    }
    const code = editorPane.querySelector(".code-hl code");
    if (code && wrap && !wrap.classList.contains("is-plain")) {
      // The trailing newline keeps the overlay as tall as the textarea.
      code.innerHTML = `${fileHighlight(tab.path, text)}\n`;
    }
    syncEditorScroll();
  }

  let highlightFrame = 0;

  function queueHighlight() {
    if (highlightFrame) return;
    highlightFrame = requestAnimationFrame(() => {
      highlightFrame = 0;
      paintHighlight();
    });
  }

  function ensureTabLoaded(tab) {
    if (!tab || tab.state !== "loading" || tab.loading) return;
    if (tab.kind === "image") {
      tab.state = "image";
      return;
    }
    if (!tab.editable) {
      tab.state = "binary";
      return;
    }
    const chatId = store.activeId;
    tab.loading = true;
    fetch(fileUrl(chatId, tab.path), { credentials: "same-origin" })
      .then((res) => (res.ok ? res.text() : Promise.reject(new Error("read"))))
      .then((text) => {
        tab.loading = false;
        if (chatId !== store.activeId || !findTab(tab.path)) return;
        tab.original = text;
        tab.text = text;
        tab.dirty = false;
        tab.state = "ready";
        tab.rev += 1;
        tab.caret = null;
        tab.scrollTop = 0;
        tab.scrollLeft = 0;
        if (activeTab === tab.path) renderEditorPane();
        paintTabs();
      })
      .catch(() => {
        tab.loading = false;
        if (chatId !== store.activeId || !findTab(tab.path)) return;
        tab.state = "error";
        tab.rev += 1;
        if (activeTab === tab.path) renderEditorPane();
      });
  }

  function paintView() {
    const tab = activeTabRow();
    if (activeTab && !tab) activeTab = "";
    const showEditor = Boolean(tab);
    const wasEditor = Boolean(logWrap && logWrap.hidden);
    if (!wasEditor && showEditor) logScroll = log.scrollTop;
    if (logWrap) logWrap.hidden = showEditor;
    if (editorPane) editorPane.hidden = !showEditor;
    if (showEditor) {
      ensureTabLoaded(tab);
      renderEditorPane();
      return;
    }
    if (editorPane) editorPane.dataset.key = "";
    // display:none drops the scroll offset, so put the log back where it was.
    if (wasEditor) {
      log.scrollTop = followLog ? log.scrollHeight : logScroll;
      paintJump();
    }
  }

  function paintTabsAndFiles() {
    paintFilesHead();
    paintFilesTree();
    paintTabs();
    paintView();
  }

  function activateTab(path) {
    if (activeTab === path) return;
    stashEditor();
    activeTab = path;
    filesSelected = path;
    paintTabsAndFiles();
  }

  function openFileTab(path) {
    const row = filesListing.find((item) => item.path === path);
    if (!row) return;
    stashEditor();
    if (!findTab(path)) {
      openTabs.push({
        path,
        size: Number(row.size) || 0,
        kind: row.kind,
        editable: Boolean(row.editable),
        state: "loading",
        rev: 0,
        original: "",
        text: "",
        dirty: false,
        busy: false,
        note: "",
        gone: false,
        caret: null,
        scrollTop: 0,
        scrollLeft: 0,
      });
    }
    activeTab = path;
    filesSelected = path;
    paintTabsAndFiles();
    // On a phone the files pane covers the chat column the tab just opened in.
    if (narrowChat.matches && filesOpen) setFilesOpen(false);
  }

  async function closeTab(path) {
    const tab = findTab(path);
    if (!tab) return;
    if (activeTab === path) stashEditor();
    if (tab.dirty && !(await confirmDropEdits(tab.path))) return;
    const at = openTabs.indexOf(tab);
    if (at < 0) return;
    openTabs.splice(at, 1);
    if (activeTab === path) {
      const next = openTabs[at] || openTabs[at - 1] || null;
      activeTab = next ? next.path : "";
      filesSelected = activeTab;
      if (editorPane) editorPane.dataset.key = "";
    }
    paintTabsAndFiles();
  }

  function resetTabs() {
    openTabs = [];
    activeTab = "";
    if (editorPane) editorPane.dataset.key = "";
  }

  /** Fold a fresh listing into the open tabs: drop gone files, reload rewrites. */
  function syncTabs() {
    for (let i = openTabs.length - 1; i >= 0; i -= 1) {
      const tab = openTabs[i];
      const row = filesListing.find((item) => item.path === tab.path);
      if (!row) {
        if (tab.dirty) tab.gone = true;
        else openTabs.splice(i, 1);
        continue;
      }
      tab.gone = false;
      tab.kind = row.kind;
      tab.editable = Boolean(row.editable);
      const size = Number(row.size) || 0;
      if (size === tab.size) continue;
      tab.size = size;
      // A code turn rewrote the file. Unsaved edits win until the user decides.
      if (!tab.dirty && !tab.busy) tab.state = "loading";
    }
    if (activeTab && !findTab(activeTab)) activeTab = "";
    // The tree highlights whichever file the open tab is showing.
    filesSelected = activeTab;
  }

  function paintFiles() {
    syncTabs();
    paintTabsAndFiles();
  }

  async function saveTab() {
    const tab = activeTabRow();
    const box = editorBox();
    if (!tab || !box || !tab.dirty || tab.busy) return;
    const chatId = store.activeId;
    const contents = box.value;
    tab.busy = true;
    tab.note = "";
    paintEditorHead();
    try {
      const data = await TabbyUI.api(
        `workspace/${encodeURIComponent(chatId)}/file?path=${encodeURIComponent(tab.path)}`,
        { method: "PUT", body: { contents } }
      );
      tab.busy = false;
      if (chatId !== store.activeId || !findTab(tab.path)) return;
      filesListing = Array.isArray(data.files) ? data.files : filesListing;
      filesEntry = typeof data.entry === "string" ? data.entry : filesEntry;
      noteChatFiles(chatId, filesListing.length > 0);
      tab.original = contents;
      tab.text = contents;
      tab.dirty = false;
      tab.gone = false;
      tab.note = "Saved.";
      const saved = filesListing.find((item) => item.path === tab.path);
      tab.size = saved ? Number(saved.size) || 0 : tab.size;
      paintFilesHead();
      paintFilesTree();
      paintTabs();
      paintEditorHead();
    } catch (err) {
      tab.busy = false;
      tab.note = err.message;
      paintEditorHead();
    }
  }

  function revertTab() {
    const tab = activeTabRow();
    if (!tab || !tab.dirty) return;
    tab.dirty = false;
    tab.note = "";
    tab.caret = null;
    // Read the file again: a code turn may have rewritten it while we edited,
    // and the buffer we started from is then no longer what is on disk.
    tab.state = "loading";
    paintTabs();
    paintView();
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
    // Tabs belong to one chat's project; another chat starts from Chat again.
    if (tabsChat !== chatId) {
      tabsChat = chatId;
      resetTabs();
    }
    if (activeMode() !== "code" || !chatId) {
      filesListing = [];
      filesSelected = "";
      filesEntry = "";
      resetTabs();
      paintFiles();
      return;
    }
    try {
      const data = await TabbyUI.api(`workspace/${encodeURIComponent(chatId)}`);
      if (chatId !== store.activeId) return;
      filesListing = Array.isArray(data.files) ? data.files : [];
      filesEntry = typeof data.entry === "string" ? data.entry : "";
      noteChatFiles(chatId, filesListing.length > 0);
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

  function hidePopovers() {
    hideMoreMenu();
    hideAttachMenu();
    if (TabbyUI.hideContextMenu) TabbyUI.hideContextMenu();
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
    TabbyUI.copyText(value).then(done).catch(fail);
  }

  function chatMessages(id) {
    const want = id || store.activeId;
    if (want === store.activeId) return messages;
    const chat = store.chats.find((item) => item.id === want);
    return chat ? chat.messages : [];
  }

  function insertCompose(text, { replace = false } = {}) {
    const chunk = String(text || "");
    if (!chunk) return;
    const cur = input.value;
    setCompose(replace ? chunk : cur ? `${cur.replace(/\s+$/, "")}\n\n${chunk}` : chunk);
    input.focus();
  }

  function quoteCompose(text) {
    const quoted = String(text || "")
      .trim()
      .split("\n")
      .map((line) => `> ${line}`)
      .join("\n");
    insertCompose(quoted);
  }

  function messagePlain(idx) {
    const item = messages[idx];
    if (!item) return "";
    if (item.role === "assistant" && TabbyUI.formatAssistantContent) {
      return TabbyUI.formatAssistantContent(item.content);
    }
    return String(item.content || "");
  }

  function langExt(lang) {
    const key = String(lang || "").trim().toLowerCase();
    const map = {
      html: ".html",
      htm: ".html",
      css: ".css",
      js: ".js",
      javascript: ".js",
      mjs: ".mjs",
      json: ".json",
      jsx: ".jsx",
      ts: ".ts",
      typescript: ".ts",
      tsx: ".tsx",
      md: ".md",
      markdown: ".md",
      py: ".py",
      python: ".py",
      sh: ".sh",
      bash: ".sh",
      shell: ".sh",
      yml: ".yml",
      yaml: ".yaml",
      svg: ".svg",
      xml: ".xml",
      csv: ".csv",
      php: ".php",
      toml: ".toml",
      ini: ".ini",
      conf: ".conf",
      txt: ".txt",
    };
    return map[key] || ".txt";
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
    } else {
      pendingImage = null;
      if (fileInput) fileInput.value = "";
    }
    pendingFiles = Array.isArray(item.attachedFiles)
      ? item.attachedFiles.map((file) => ({ ...file }))
      : [];
    paintAttach();
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

  function conversationMarkdown(id) {
    return chatMessages(id)
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

  function exportChat(id) {
    const chat = store.chats.find((item) => item.id === (id || store.activeId));
    const title = (chat && chat.title) || "chat";
    const stem = title.replace(/[^\w.-]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 48) || "chat";
    const blob = new Blob([conversationMarkdown(id)], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    saveUrl(url, `${stem}.md`);
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
    const on = Boolean(pendingImage || pendingFiles.length);
    if (attachBar) attachBar.hidden = !on;
    if (!attachList) return;
    const frag = document.createDocumentFragment();
    if (pendingImage) {
      frag.appendChild(attachChip({
        key: "image",
        kind: "image",
        name: pendingImage.name || "image",
        preview: pendingImage.preview || pendingImage.dataUrl,
      }));
    }
    pendingFiles.forEach((file) => {
      frag.appendChild(attachChip({
        key: file.path,
        kind: file.kind,
        name: file.path,
        preview: file.preview,
      }));
    });
    attachList.replaceChildren(frag);
    paintFilesTree();
  }

  function attachChip(item) {
    const chip = document.createElement("div");
    chip.className = "chat-attach-chip";
    chip.dataset.key = item.key;
    if (item.kind === "image" && item.preview) {
      const img = document.createElement("img");
      img.alt = "";
      img.src = item.preview;
      chip.appendChild(img);
    }
    const name = document.createElement("span");
    name.className = "chat-attach-name";
    name.textContent = item.name;
    chip.appendChild(name);
    const clear = document.createElement("button");
    clear.className = "btn ghost chat-queue-clear";
    clear.type = "button";
    clear.dataset.detach = item.key;
    clear.setAttribute("aria-label", `Remove ${item.name}`);
    clear.textContent = "×";
    chip.appendChild(clear);
    return chip;
  }

  function hideAttachMenu() {
    if (!attachMenu || !attachBtn) return;
    attachMenu.hidden = true;
    attachBtn.setAttribute("aria-expanded", "false");
  }

  function paintAttachMenu() {
    if (!attachMenu) return;
    const frag = document.createDocumentFragment();
    const add = (key, label, extra) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.dataset.attach = key;
      if (extra) Object.assign(btn.dataset, extra);
      btn.textContent = label;
      frag.appendChild(btn);
    };
    add("image", "Attach image");
    add("upload", "Upload files to project");
    if (filesListing.length) {
      const mark = document.createElement("div");
      mark.className = "chat-attach-label";
      mark.textContent = "Project files";
      frag.appendChild(mark);
      filesListing.forEach((row) => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.dataset.attach = "file";
        btn.dataset.path = row.path;
        btn.className = isPendingFile(row.path) ? "is-on" : "";
        btn.textContent = row.path;
        frag.appendChild(btn);
      });
    }
    attachMenu.replaceChildren(frag);
  }

  function toggleAttachMenu() {
    if (modelLoading) return;
    if (activeMode() !== "code") {
      hideAttachMenu();
      if (fileInput) fileInput.click();
      return;
    }
    const open = Boolean(attachMenu && attachMenu.hidden);
    hideMoreMenu();
    if (!open) {
      hideAttachMenu();
      return;
    }
    paintAttachMenu();
    attachMenu.hidden = false;
    if (attachBtn) attachBtn.setAttribute("aria-expanded", "true");
  }

  function clearPendingImage() {
    pendingImage = null;
    pendingFiles = [];
    if (fileInput) fileInput.value = "";
    if (uploadInput) uploadInput.value = "";
    paintAttach();
  }

  function detachPending(key) {
    if (key === "image") {
      pendingImage = null;
      if (fileInput) fileInput.value = "";
    } else {
      pendingFiles = pendingFiles.filter((file) => file.path !== key);
    }
    paintAttach();
  }

  function blobToDataUrl(blob) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result || ""));
      reader.onerror = () => reject(new Error("Could not read file."));
      reader.readAsDataURL(blob);
    });
  }

  async function blobToBase64(blob) {
    const dataUrl = await blobToDataUrl(blob);
    const at = dataUrl.indexOf(",");
    return at >= 0 ? dataUrl.slice(at + 1) : dataUrl;
  }

  async function attachProjectFile(path, opts) {
    const row = filesListing.find((item) => item.path === path);
    if (!row) return;
    if (isPendingFile(path)) {
      if (!opts || opts.toggle !== false) detachPending(path);
      return;
    }
    if (pendingFiles.length >= MAX_ATTACH) {
      addBubble("assistant", "Error: Too many attached files.");
      return;
    }
    if (row.kind === "image") {
      const res = await fetch(fileUrl(store.activeId, path), { credentials: "same-origin" });
      if (!res.ok) throw new Error("Could not read that file.");
      const dataUrl = await blobToDataUrl(await res.blob());
      const preview = await resizeDataUrl(dataUrl, 320, 0.72);
      pendingFiles.push({ path, kind: "image", dataUrl, preview });
    } else if (row.editable) {
      const tab = findTab(path);
      let text = tab && tab.state === "ready" ? String(tab.text || "") : "";
      if (!(tab && tab.state === "ready")) {
        const res = await fetch(fileUrl(store.activeId, path), { credentials: "same-origin" });
        if (!res.ok) throw new Error("Could not read that file.");
        text = await res.text();
      }
      if (text.length > ATTACH_TEXT_LIMIT) text = `${text.slice(0, ATTACH_TEXT_LIMIT)}\n…(truncated)`;
      pendingFiles.push({ path, kind: "text", text });
    } else {
      addBubble("assistant", "Error: That file cannot be attached.");
      return;
    }
    paintAttach();
  }

  function defaultNewPath() {
    const names = new Set(filesListing.map((row) => row.path));
    if (!names.has("untitled.txt")) return "untitled.txt";
    for (let i = 2; i < 100; i += 1) {
      const name = `untitled-${i}.txt`;
      if (!names.has(name)) return name;
    }
    return `untitled-${Date.now()}.txt`;
  }

  async function createUserFile() {
    const raw = await TabbyUI.promptModal({
      title: "New file",
      text: "Relative path in this chat's project.",
      label: "Path",
      yes: "Create",
      value: defaultNewPath(),
      placeholder: "index.html",
    });
    if (raw == null) return;
    let path = String(raw).trim().replace(/\\/g, "/").replace(/^\/+/, "");
    if (!path || path.includes("..") || path.startsWith("~")) {
      addBubble("assistant", "Error: Enter a relative path such as index.html.");
      return;
    }
    if (!fileSuffix(path)) path = `${path}.txt`;
    if (!TEXT_SUFFIXES.has(fileSuffix(path))) {
      addBubble("assistant", "Error: Use a text file type such as .html, .css, .js, or .txt.");
      return;
    }
    if (filesListing.some((row) => row.path === path)) {
      openFileTab(path);
      return;
    }
    try {
      const data = await TabbyUI.api(
        `workspace/${encodeURIComponent(store.activeId)}/file?path=${encodeURIComponent(path)}`,
        { method: "PUT", body: { contents: "" } }
      );
      applyListing(data);
      openFileTab(data.path || path);
    } catch (err) {
      addBubble("assistant", `Error: ${err.message}`);
    }
  }

  function retargetPath(from, to) {
    if (!from || !to || from === to) return;
    const tab = findTab(from);
    if (tab) {
      tab.path = to;
      if (activeTab === from) activeTab = to;
      if (editorPane && editorPane.dataset.key === from) editorPane.dataset.key = to;
    }
    if (filesSelected === from) filesSelected = to;
    pendingFiles.forEach((file) => {
      if (file.path === from) file.path = to;
    });
  }

  function nextCopyPath(path) {
    const slash = String(path || "").lastIndexOf("/");
    const dir = slash >= 0 ? path.slice(0, slash + 1) : "";
    const name = slash >= 0 ? path.slice(slash + 1) : path;
    const at = name.lastIndexOf(".");
    const stem = at > 0 ? name.slice(0, at) : name;
    const ext = at > 0 ? name.slice(at) : "";
    const names = new Set(filesListing.map((row) => row.path));
    for (let i = 1; i < 100; i += 1) {
      const dest = `${dir}${stem}-copy${i === 1 ? "" : `-${i}`}${ext}`;
      if (!names.has(dest)) return dest;
    }
    return `${dir}${stem}-copy-${Date.now()}${ext}`;
  }

  async function renameProjectFile(path) {
    const raw = await TabbyUI.promptModal({
      title: "Rename file",
      text: "Relative path in this chat's project.",
      label: "Path",
      yes: "Rename",
      value: path,
    });
    if (raw == null) return;
    const dest = String(raw).trim().replace(/\\/g, "/").replace(/^\/+/, "");
    if (!dest || dest === path) return;
    if (dest.includes("..") || dest.startsWith("~")) {
      addBubble("assistant", "Error: Enter a relative path such as styles.css.");
      return;
    }
    try {
      const data = await TabbyUI.api(
        `workspace/${encodeURIComponent(store.activeId)}/rename`,
        { method: "POST", body: { path, to: dest } }
      );
      retargetPath(path, data.path || dest);
      applyListing(data);
      paintAttach();
    } catch (err) {
      addBubble("assistant", `Error: ${err.message}`);
    }
  }

  async function duplicateProjectFile(path) {
    const dest = nextCopyPath(path);
    try {
      const response = await fetch(fileUrl(store.activeId, path), { credentials: "same-origin" });
      if (!response.ok) throw new Error("Could not read that file.");
      const bytesB64 = await blobToBase64(await response.blob());
      const data = await TabbyUI.api(
        `workspace/${encodeURIComponent(store.activeId)}/file`,
        { method: "POST", body: { path: dest, bytes_b64: bytesB64 } }
      );
      applyListing(data);
      const written = data.path || dest;
      if (TEXT_SUFFIXES.has(fileSuffix(written))) openFileTab(written);
    } catch (err) {
      addBubble("assistant", `Error: ${err.message}`);
    }
  }

  async function deleteProjectFile(path) {
    const yes = await TabbyUI.confirmModal({
      title: "Delete file",
      text: `Delete “${path}”? This cannot be undone.`,
      yes: "Delete",
      no: "Cancel",
    });
    if (!yes) return;
    try {
      const data = await TabbyUI.api(
        `workspace/${encodeURIComponent(store.activeId)}/file?path=${encodeURIComponent(path)}`,
        { method: "DELETE" }
      );
      filesListing = Array.isArray(data.files) ? data.files : [];
      filesEntry = typeof data.entry === "string" ? data.entry : "";
      noteChatFiles(store.activeId, filesListing.length > 0);
      const open = findTab(path);
      if (open) open.dirty = false;
      if (filesSelected === path) filesSelected = "";
      pendingFiles = pendingFiles.filter((file) => file.path !== path);
      paintAttach();
      paintFiles();
    } catch (err) {
      addBubble("assistant", `Error: ${err.message}`);
    }
  }

  async function saveCodeAsFile(code, lang) {
    const ext = langExt(lang);
    const suggested = defaultNewPath().replace(/untitled(?:-\d+)?\.txt$/, `snippet${ext}`);
    const raw = await TabbyUI.promptModal({
      title: "Save as file",
      text: "Relative path in this chat's project.",
      label: "Path",
      yes: "Save",
      value: suggested.endsWith(ext) ? suggested : `snippet${ext}`,
      placeholder: `snippet${ext}`,
    });
    if (raw == null) return;
    let path = String(raw).trim().replace(/\\/g, "/").replace(/^\/+/, "");
    if (!path || path.includes("..") || path.startsWith("~")) {
      addBubble("assistant", "Error: Enter a relative path such as snippet.js.");
      return;
    }
    if (!fileSuffix(path)) path = `${path}${ext}`;
    if (!TEXT_SUFFIXES.has(fileSuffix(path))) {
      addBubble("assistant", "Error: Use a text file type such as .html, .css, .js, or .txt.");
      return;
    }
    try {
      const data = await TabbyUI.api(
        `workspace/${encodeURIComponent(store.activeId)}/file?path=${encodeURIComponent(path)}`,
        { method: "PUT", body: { contents: String(code || "") } }
      );
      applyListing(data);
      openFileTab(data.path || path);
    } catch (err) {
      addBubble("assistant", `Error: ${err.message}`);
    }
  }

  async function closeOtherTabs(path) {
    const keep = path || activeTab;
    const drop = openTabs.filter((tab) => tab.path !== keep).map((tab) => tab.path);
    for (const item of drop) {
      await closeTab(item);
    }
  }

  async function closeAllTabs() {
    const drop = openTabs.map((tab) => tab.path);
    for (const item of drop) {
      await closeTab(item);
    }
  }

  function downloadZip() {
    if (!filesListing.length) return;
    fetch(TabbyUI.path(`workspace/${encodeURIComponent(store.activeId)}/zip`), {
      credentials: "same-origin",
    })
      .then((response) => {
        if (!response.ok) throw new Error("Could not download the zip.");
        return response.blob();
      })
      .then((blob) => {
        const url = URL.createObjectURL(blob);
        saveUrl(url, `${downloadStem()}.zip`);
        setTimeout(() => URL.revokeObjectURL(url), 10_000);
      })
      .catch((err) => {
        addBubble("assistant", `Error: ${err.message}`);
      });
  }

  async function clearProjectFiles() {
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
      pendingFiles = [];
      resetTabs();
      noteChatFiles(store.activeId, false);
      paintAttach();
      paintFiles();
    } catch (err) {
      addBubble("assistant", `Error: ${err.message}`);
    }
  }

  async function pasteCompose() {
    try {
      const text = await navigator.clipboard.readText();
      if (text) insertCompose(text);
    } catch {
      /* clipboard permission denied */
    }
  }

  async function uploadLocalFiles(fileList, { attach = false, open = false } = {}) {
    const chatId = store.activeId;
    const files = Array.from(fileList || []).filter(Boolean);
    let lastText = "";
    for (const file of files) {
      const name = String(file.name || "file").split(/[/\\]/).pop();
      const suffix = fileSuffix(name);
      if (!TEXT_SUFFIXES.has(suffix) && !IMAGE_SUFFIXES.has(suffix)) {
        addBubble("assistant", `Error: ${name} is not a text or image file.`);
        continue;
      }
      if (TEXT_SUFFIXES.has(suffix) && file.size > 1 * 1024 * 1024) {
        addBubble("assistant", `Error: ${name} is larger than 1 MB.`);
        continue;
      }
      if (IMAGE_SUFFIXES.has(suffix) && file.size > 8 * 1024 * 1024) {
        addBubble("assistant", `Error: ${name} must be under 8 MB.`);
        continue;
      }
      const bytesB64 = await blobToBase64(file);
      const data = await TabbyUI.api(
        `workspace/${encodeURIComponent(chatId)}/file`,
        { method: "POST", body: { path: name, bytes_b64: bytesB64 } }
      );
      applyListing(data);
      const path = data.path || name;
      if (attach) await attachProjectFile(path, { toggle: false });
      if (TEXT_SUFFIXES.has(fileSuffix(path))) lastText = path;
    }
    if (open && lastText && files.length === 1) openFileTab(lastText);
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

  function outboundUserText(item) {
    let text = String(item.content || "");
    const files = Array.isArray(item.attachedFiles) ? item.attachedFiles : [];
    const blocks = files
      .filter((file) => file.kind !== "image" && file.path && typeof file.text === "string")
      .map((file) => `Attached file \`${file.path}\`:\n\`\`\`\n${file.text}\n\`\`\``);
    if (blocks.length) text = text ? `${text}\n\n${blocks.join("\n\n")}` : blocks.join("\n\n");
    return text;
  }

  function outboundMessages() {
    return messages
      .filter((item) => item.role !== "system")
      .map((item) => {
        if (item.role !== "user") return { role: item.role, content: item.content };
        const text = outboundUserText(item);
        const images = [];
        if (item.imageData) images.push(item.imageData);
        (item.attachedFiles || []).forEach((file) => {
          if (file.kind === "image" && file.dataUrl && !images.includes(file.dataUrl)) {
            images.push(file.dataUrl);
          }
        });
        if (!images.length) return { role: "user", content: text };
        const content = [];
        if (text) content.push({ type: "text", text });
        images.forEach((url) => content.push({ type: "image_url", image_url: { url } }));
        return { role: "user", content };
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

  function shortcutRow(label, keysHtml) {
    return "<li><span>" + label + '</span><span class="shortcut-keys">' + keysHtml + "</span></li>";
  }

  function showShortcuts() {
    return showDialog({
      title: "Keyboard shortcuts",
      html:
        '<div class="shortcuts">' +
        '<section><h3>Composer</h3><ul class="shortcuts-list">' +
        shortcutRow("Send", "<kbd>Enter</kbd>") +
        shortcutRow("New line", "<kbd>Shift</kbd>+<kbd>Enter</kbd>") +
        shortcutRow("Slash commands", "<kbd>/</kbd>") +
        shortcutRow("Recall sent text", "<kbd>↑</kbd><kbd>↓</kbd>") +
        "</ul></section>" +
        '<section><h3>Chats</h3><ul class="shortcuts-list">' +
        shortcutRow("Cycle chats", "<kbd>Tab</kbd>") +
        shortcutRow("Search chats", "<kbd>Ctrl</kbd>+<kbd>K</kbd>") +
        shortcutRow("New chat", "<kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>O</kbd>") +
        shortcutRow("Stop or close", "<kbd>Esc</kbd>") +
        "</ul></section>" +
        '<section><h3>Workspace</h3><ul class="shortcuts-list">' +
        shortcutRow("Save file", "<kbd>Ctrl</kbd>+<kbd>S</kbd>") +
        shortcutRow("More actions", "<kbd>Right-click</kbd>") +
        "</ul></section>" +
        "</div>",
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
      if (idx != null && idx >= 0) turn.node.dataset.msgIdx = String(idx);
      attachSwitchLlm(turn.bubble || turn.node, text);
      attachMsgActions(turn.node, "assistant", idx, text);
      if (stick !== false) stickLog(true);
      return turn.node;
    }
    const row = document.createElement("div");
    row.className = "chat-row";
    if (idx != null && idx >= 0) row.dataset.msgIdx = String(idx);
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
    const attached = extra && Array.isArray(extra.attachedFiles) ? extra.attachedFiles : [];
    if (attached.length) {
      const rowFiles = document.createElement("div");
      rowFiles.className = "chat-msg-files";
      attached.forEach((file) => {
        if (file.kind === "image" && file.preview) {
          const img = document.createElement("img");
          img.className = "chat-thumb";
          img.src = file.preview;
          img.alt = file.path || "Attached image";
          node.appendChild(img);
          return;
        }
        const chip = document.createElement("span");
        chip.className = "chat-msg-file";
        chip.textContent = file.path || "file";
        rowFiles.appendChild(chip);
      });
      if (rowFiles.childNodes.length) node.appendChild(rowFiles);
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
    return TabbyUI.renderMarkdown(cleaned, { inlineImages: activeMode() !== "code" });
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

  // Labels a settled header may keep across a reload. Anything else was a
  // transient live status ("Rendering image 2 of 3", "Writing index.html").
  const SETTLED_LABEL = /^(Generated|Replied|Thought|Restarted|Loaded |Still loading$)/;

  function settledLabel({ kind, target, reasoning, answer }) {
    if (kind === "image") return looksLikeImageReply(answer) ? "Generated" : "Replied";
    if (kind === "restart" || target === "restart") return "Restarted";
    if (kind === "switch") {
      const name = String(target || "").trim();
      if (name === "comfy" || name === "flux") return "Loaded Comfy";
      return name ? `Loaded ${name}` : "Loaded the model";
    }
    return reasoning ? "Thought" : "Replied";
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
    const initialLabel = tabbyCleanStatusLabel(status_label) || (activity && activity.label) || "Thinking";
    label.textContent = String(initialLabel);
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
    let answerText = String(content || "");

    function ensureBubble() {
      if (bubbleMounted) return;
      turn.appendChild(bubble);
      bubbleMounted = true;
    }

    function showAnswer(html, raw) {
      const markup = String(html || "").trim();
      if (!markup) return false;
      if (raw != null) answerText = String(raw);
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
    const target = (activity && activity.target) || "";
    const storedLabel = tabbyCleanStatusLabel(status_label);
    const keptLabel = !live && SETTLED_LABEL.test(storedLabel) ? storedLabel : "";
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

    // Every finished reply keeps the same static icon, whatever it was doing.
    function markSettledIcon() {
      icon.hidden = false;
      icon.classList.remove("is-processing");
      icon.classList.add("is-done");
    }

    function headLabel() {
      if (keptLabel) return keptLabel;
      if (label.textContent === "Still loading") return "Still loading";
      return settledLabel({ kind, target, reasoning: reasoningText, answer: answerText });
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
      const line = tabbyCleanStatusLabel(note);
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
        if (head.tagName !== "BUTTON") head.setAttribute("role", "button");
        head.tabIndex = 0;
        head.setAttribute("aria-expanded", "false");
      } else {
        if (head.tagName !== "BUTTON") head.removeAttribute("role");
        head.tabIndex = -1;
        head.removeAttribute("aria-expanded");
      }
      markSettledIcon();
      label.textContent = headLabel();
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
    } else {
      settleThought(elapsedSec);
      paintThought();
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
        const next = tabbyCleanStatusLabel(text);
        if (!next) return;
        label.textContent = next;
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
        } else {
          markSettledIcon();
          label.textContent = headLabel();
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
      isLive() {
        return Boolean(live && !finished);
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
    if (inFlight && store.activeId === flightChatId && flightWorking && flightWorking.isLive()) {
      log.appendChild(flightWorking.node);
    }
    paintEmpty();
    if (stickToEnd !== false) stickLog(true);
    else paintJump();
  }

  function loadChat(id, stickToEnd) {
    if (id === store.activeId) {
      if (stickToEnd !== false) stickLog(true);
      input.focus();
      setSidebarOpen(false);
      return;
    }
    persist();
    const chat = store.chats.find((item) => item.id === id);
    if (!chat) return;
    store.activeId = id;
    messages = cloneMessages(chat.messages);
    if (!messages.some((item) => item.role === "system")) messages.unshift({ ...SYSTEM });
    cancelEdit();
    clearPendingImage();
    persist();
    resetRecall();
    renderLog(stickToEnd !== false);
    refreshFiles();
    paintCompose();
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
    const mode = chatMode(chat);
    store.chats = store.chats.filter((item) => item.id !== id);
    dropWorkspace(id);
    if (store.activeId === id) {
      const next = store.chats
        .filter((item) => chatMode(item) === mode && (hasUserTurn(item) || item.pinned))
        .sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0))[0];
      if (next) {
        store.activeId = next.id;
        messages = cloneMessages(next.messages);
        if (!messages.some((item) => item.role === "system")) messages.unshift({ ...SYSTEM });
      } else {
        const fresh = emptyChat(mode);
        store.chats.unshift(fresh);
        store.activeId = fresh.id;
        messages = cloneMessages(fresh.messages);
      }
    }
    persist();
    resetRecall();
    renderLog();
    renderHistoryMenu();
    refreshFiles();
    paintCompose();
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
    const mode = activeMode();
    const doomed = store.chats.filter((item) => chatMode(item) === mode);
    if (doomed.some(hasUserTurn) || hasUserTurn({ messages })) {
      const yes = await TabbyUI.confirmModal({
        title: "Clear history",
        text: mode === "code"
          ? "Delete all saved Code chats for this account?"
          : "Delete all saved Chat conversations for this account?",
        yes: "Delete all",
        no: "Cancel",
      });
      if (!yes) return;
    }
    abortSession("stop");
    cancelEdit();
    clearPendingImage();
    doomed.forEach((item) => dropWorkspace(item.id));
    const kept = store.chats.filter((item) => chatMode(item) !== mode);
    const chat = emptyChat(mode);
    store = {
      version: 1,
      activeId: chat.id,
      chats: [chat, ...kept],
      lastByMode: {
        chat: mode === "chat" ? chat.id : (store.lastByMode && store.lastByMode.chat) || "",
        code: mode === "code" ? chat.id : (store.lastByMode && store.lastByMode.code) || "",
      },
    };
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
    if (
      attachMenu &&
      attachBtn &&
      !attachMenu.hidden &&
      !attachMenu.contains(target) &&
      !attachBtn.contains(target)
    ) {
      hideAttachMenu();
    }
  }

  function onGlobalKey(event) {
    if (event.key === "Escape") {
      if (shell.classList.contains("is-sidebar-open")) {
        setSidebarOpen(false);
        event.preventDefault();
        return;
      }
      hidePopovers();
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
        .map((line) => line.slice(1).trim())
        .filter((line) => line && !tabbyIsSsePing(line));
      const comment = comments.join("\n");
      if (
        comment.includes("tabby-image-job:") ||
        comment.includes("tabby-image-status:") ||
        comment.includes("tabby-stack-queue:")
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
        const queue = data && data.stack_queue;
        if (queue && queue.queued) {
          showStackQueue(queue.hint || "", working);
          return;
        }
        if (stackWaiting && !(queue && queue.queued)) {
          hideStackQueue(working, {
            label: kind === "image" ? "Starting the picture" : "Thinking",
            processing: kind === "image",
          });
        }
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
  let flightWorking = null;
  let gpuMode = "";
  let comfyUp = false;
  let modelLoading = false;
  let modelWait = null;
  let modelLoadStarted = 0;
  let modelLoadTicker = null;
  let loadingHintText = "";
  let stackWaiting = false;
  let stackWaitStarted = 0;
  let stackWaitTicker = null;
  let stackWaitHint = "";
  let gateTicker = null;

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

  function comfyIsStarting(data) {
    if (!data || data.comfy_up) return false;
    const target = String(data.switch_target || "").toLowerCase();
    if (target === "comfy" || target === "flux") return true;
    if (data.units && data.units.comfyui) return true;
    const phase = data.job && String(data.job.phase || "");
    return phase === "starting_comfy";
  }

  function statusIsBusy(data) {
    return Boolean(
      data && (data.switching || data.restarting || data.busy || comfyIsStarting(data))
    );
  }

  function loadingHint(kind, name) {
    if (kind === "restart" || name === "restart") {
      return "Restarting. Chat is paused until the API is ready.";
    }
    const label = String(name || "").trim();
    const key = label.toLowerCase();
    if (key === "comfy" || key === "flux") {
      return "Loading Comfy. Chat is paused until it is ready.";
    }
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

  const STACK_QUEUE_HINT = "The stack is being used. You are in a queue.";

  function paintStackWaitElapsed() {
    const elapsed = stackWaitStarted ? Math.floor((Date.now() - stackWaitStarted) / 1000) : 0;
    const clock = elapsed >= 1 ? TabbyUI.formatDuration(elapsed) : "";
    if (waitingTimeEl) waitingTimeEl.textContent = clock;
    if (waitingTextEl && stackWaitHint) {
      waitingTextEl.textContent = clock
        ? `${stackWaitHint} ${clock} elapsed.`
        : stackWaitHint;
    }
  }

  function startStackWaitClock() {
    if (!stackWaitStarted) stackWaitStarted = Date.now();
    if (stackWaitTicker) return;
    paintStackWaitElapsed();
    stackWaitTicker = setInterval(paintStackWaitElapsed, 250);
  }

  function stopStackWaitClock() {
    if (stackWaitTicker) {
      clearInterval(stackWaitTicker);
      stackWaitTicker = null;
    }
    stackWaitStarted = 0;
    stackWaitHint = "";
    if (waitingTimeEl) waitingTimeEl.textContent = "";
  }

  function showStackQueue(hint, working) {
    stackWaitHint = String(hint || "").trim() || STACK_QUEUE_HINT;
    stackWaiting = true;
    startStackWaitClock();
    paintStackWaitElapsed();
    if (waitingBar) waitingBar.hidden = false;
    if (working) {
      working.setActivity("Queued", { processing: true, note: stackWaitHint });
    }
    paintCompose();
  }

  function hideStackQueue(working, resume) {
    if (!stackWaiting && !stackWaitTicker) {
      if (waitingBar) waitingBar.hidden = true;
      return;
    }
    stackWaiting = false;
    stopStackWaitClock();
    if (waitingBar) waitingBar.hidden = true;
    if (working && resume) {
      working.setActivity(resume.label || "Thinking", {
        processing: resume.processing,
        note: resume.note,
      });
    }
    paintCompose();
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
    // An API restart has no useful client-side timeout: keep the composer
    // locked and the reconnecting message visible until status answers again.
    while (kind === "restart" || Date.now() < deadline) {
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
        } else if (modelLooksReady(data, activity) && (sawBusy || Date.now() - started > 2500)) {
          const dest = String((activity && activity.target) || name || "").toLowerCase();
          const readyNote = dest === "comfy" || dest === "flux" ? "Comfy is ready." : "The model is ready.";
          if (working) working.setActivity("Ready", { processing: false, note: readyNote });
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
      const target = data.switch_target || (comfyIsStarting(data) ? "comfy" : "");
      const kind = data.restarting ? "restart" : "switch";
      await ensureModelWait(null, { kind, target });
    } catch {
      // The process may disappear before status reports its restart lock.
      // Treat an unreachable API as a restart and hold chat until it returns.
      await ensureModelWait(null, { kind: "restart", target: "restart" });
    }
  }

  function startGatePoll() {
    if (gateTicker) return;
    syncModelGate();
    gateTicker = setInterval(() => {
      if (!modelWait) syncModelGate();
    }, 1500);
  }

  function stopGatePoll() {
    if (!gateTicker) return;
    clearInterval(gateTicker);
    gateTicker = null;
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
    if (waitingBar) waitingBar.hidden = modelLoading || !stackWaiting;
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
      input.placeholder = loadingHintText || "The model is loading. Chat is paused until it is ready.";
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
      if (pendingFiles.length) {
        userItem.attachedFiles = pendingFiles.map((file) => ({ ...file }));
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
    flightWorking = working;
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
            if (event.comment && event.comment.includes("tabby-stack-queue:")) {
              const raw = String(event.comment)
                .split(/\r?\n/)
                .map((line) => line.trim())
                .filter((line) => /tabby-stack-queue:/i.test(line))
                .pop() || "";
              const hint = tabbyCleanStatusLabel(raw.replace(/^[\s\S]*tabby-stack-queue:\s*/i, ""));
              showStackQueue(hint, working);
            }
            if (event.comment && event.comment.includes("tabby-image-status:")) {
              hideStackQueue(working);
              const raw = String(event.comment)
                .split(/\r?\n/)
                .map((line) => line.trim())
                .filter((line) => /tabby-image-status:/i.test(line))
                .pop() || "";
              const label = tabbyCleanStatusLabel(raw.replace(/^[\s\S]*tabby-image-status:\s*/i, ""));
              if (label) working.setActivity(label, { processing: true });
              if (/^(?:Writing|Editing|Deleting) \S/.test(label) && store.activeId === chatId) {
                refreshFilesSoon();
              }
            }
            if (event.reasoning) {
              hideStackQueue(working, { label: "Thinking", processing: false });
              reasoning += event.reasoning;
              working.setReasoning(reasoning);
            }
            if (visibleAnswerText(event.content)) {
              hideStackQueue(working, { label: activity.label || "Thinking", processing: false });
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
    hideStackQueue();
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
    if (flightWorking === working) flightWorking = null;
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
    if (!text && !pendingImage && !pendingFiles.length) return;
    resetRecall();
    input.value = "";
    resizeInput();
    hideMenu();
    // The reply lands in the log, so bring it back into view.
    activateTab("");
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

  function openCtx(event, items) {
    hideMoreMenu();
    hideAttachMenu();
    hideHistoryMenu();
    hideMenu();
    return TabbyUI.showContextMenu(event, items);
  }

  function busyLocked() {
    return Boolean(inFlight || modelLoading);
  }

  function navMenuItems(id) {
    const chat = store.chats.find((item) => item.id === id);
    if (!chat) return [];
    return [
      { label: "Open", run: () => loadChat(id) },
      { label: "Rename", run: () => { loadChat(id); beginRename(id); } },
      { label: chat.pinned ? "Unpin" : "Pin", run: () => togglePin(id) },
      { sep: true },
      { label: "Copy conversation", run: () => copyText(conversationMarkdown(id)) },
      { label: "Export markdown", run: () => exportChat(id) },
      { sep: true },
      { label: "Delete chat", danger: true, run: () => deleteChat(id) },
    ];
  }

  function messageMenuItems(idx, extra) {
    const item = messages[idx];
    if (!item) return extra || [];
    const text = messagePlain(idx);
    const items = [];
    const picked = extra && extra.picked;
    if (picked) items.push({ label: "Copy selection", run: () => copyText(picked) });
    items.push({ label: picked ? "Copy message" : "Copy", run: () => copyText(text) });
    if (text) items.push({ label: "Quote in compose", run: () => quoteCompose(text) });
    if (item.role === "user") {
      items.push(
        { label: "Edit", disabled: busyLocked(), run: () => beginEdit(idx) },
        { label: "Delete turn", danger: true, disabled: busyLocked(), run: () => deleteTurn(idx) }
      );
    } else {
      if (idx === lastAssistantIndex()) {
        items.push({ label: "Regenerate", disabled: busyLocked(), run: () => regenerateLast() });
      }
      if (/^Error:/i.test(String(item.content || ""))) {
        items.push({ label: "Retry", disabled: busyLocked(), run: () => regenerateLast() });
      }
    }
    if (canSplit(idx)) {
      items.push({ label: "Split to new chat", disabled: busyLocked(), run: () => splitAfterTurn(idx) });
    }
    if (extra && extra.after) items.push({ sep: true }, ...extra.after);
    return items;
  }

  function fileMenuItems(path) {
    const attached = isPendingFile(path);
    const row = filesListing.find((item) => item.path === path);
    return [
      { label: "Open", run: () => openFileTab(path) },
      { label: attached ? "Remove from chat" : "Add to chat", run: () => {
        attachProjectFile(path).catch((err) => addBubble("assistant", `Error: ${err.message}`));
      } },
      { sep: true },
      { label: "Copy path", run: () => copyText(path) },
      { label: "Insert path", run: () => insertCompose(path) },
      { label: "Download", run: () => saveUrl(fileUrl(store.activeId, path), path.split("/").pop() || "file") },
      { sep: true },
      { label: "Rename", run: () => renameProjectFile(path) },
      { label: "Duplicate", run: () => duplicateProjectFile(path) },
      { label: "Delete", danger: true, run: () => deleteProjectFile(path) },
      row && row.page ? { sep: true } : null,
      row && row.page ? { label: "Open in site", run: () => openSite() } : null,
    ];
  }

  function filesPaneMenuItems() {
    return [
      { label: "New file", run: () => {
        createUserFile().catch((err) => addBubble("assistant", `Error: ${err.message}`));
      } },
      { label: "Upload files", run: () => {
        uploadWantsAttach = false;
        if (uploadInput) uploadInput.click();
      } },
      { label: "Refresh", run: () => refreshFiles() },
      { sep: true },
      { label: "Download zip", disabled: !filesListing.length, run: () => downloadZip() },
      { label: "Clear files", danger: true, disabled: !filesListing.length, run: () => clearProjectFiles() },
    ];
  }

  function tabMenuItems(path) {
    if (!path) {
      return [
        { label: "Show chat", run: () => activateTab("") },
        openTabs.length ? { label: "Close all files", run: () => closeAllTabs() } : null,
      ];
    }
    const tab = findTab(path);
    return [
      { label: "Open", run: () => activateTab(path) },
      { label: "Close", run: () => closeTab(path) },
      { label: "Close others", disabled: openTabs.length < 2, run: () => closeOtherTabs(path) },
      { label: "Close all", run: () => closeAllTabs() },
      { sep: true },
      { label: "Copy path", run: () => copyText(path) },
      { label: "Download", run: () => saveUrl(fileUrl(store.activeId, path), path.split("/").pop() || "file") },
      tab && tab.dirty ? { label: "Revert", run: () => { activateTab(path); revertTab(); } } : null,
    ];
  }

  function composeExtras() {
    return [
      { label: "Clear", disabled: !input.value, run: () => { setCompose(""); input.focus(); } },
      { label: "Attach image", run: () => { if (fileInput) fileInput.click(); } },
      activeMode() === "code"
        ? { label: "Attach project file", run: () => toggleAttachMenu() }
        : null,
    ];
  }

  function onChatContextMenu(event) {
    if (event.target.closest(".dialog-modal, .chat-title-edit, .ctx-menu")) return;

    const field = event.target.closest("textarea, input");
    if (field && field.closest(".chat-compose")) {
      openCtx(event, TabbyUI.inputMenuItems(field, composeExtras()));
      return;
    }
    if (field && field.id === "chat-search") {
      openCtx(event, TabbyUI.inputMenuItems(field, [
        { label: "Clear", disabled: !field.value, run: () => { field.value = ""; renderSidebar(); field.focus(); } },
      ]));
      return;
    }
    if (field && field.classList.contains("chat-files-edit")) {
      const tab = activeTabRow();
      openCtx(event, TabbyUI.inputMenuItems(field, [
        { label: "Save", disabled: !tab || !tab.dirty || tab.busy, kbd: "Ctrl+S", run: () => saveTab() },
        { label: "Revert", disabled: !tab || !tab.dirty, run: () => revertTab() },
        tab ? { label: "Copy path", run: () => copyText(tab.path) } : null,
        tab ? { label: "Download", run: () => saveUrl(fileUrl(store.activeId, tab.path), tab.path.split("/").pop() || "file") } : null,
      ]));
      return;
    }
    if (field) return;

    const chip = event.target.closest(".chat-attach-chip");
    if (chip && chip.dataset.key) {
      openCtx(event, [
        { label: "Remove attachment", run: () => {
          detachPending(chip.dataset.key);
          input.focus();
        } },
      ]);
      return;
    }

    const nav = event.target.closest(".chat-nav");
    if (nav && navList.contains(nav) && nav.dataset.id) {
      openCtx(event, navMenuItems(nav.dataset.id));
      return;
    }
    if (event.target.closest("#chat-nav-list, #chat-sidebar")) {
      openCtx(event, [
        { label: "New chat", run: () => startNewChat() },
        { label: "Search chats", kbd: "Ctrl+K", run: () => { if (searchEl) { searchEl.focus(); searchEl.select(); } } },
        { label: "Clear history", danger: true, run: () => clearHistory() },
      ]);
      return;
    }

    const fileRow = event.target.closest(".chat-file");
    if (fileRow && filesTree && filesTree.contains(fileRow) && fileRow.dataset.path) {
      filesSelected = fileRow.dataset.path;
      paintFilesTree();
      openCtx(event, fileMenuItems(fileRow.dataset.path));
      return;
    }
    if (event.target.closest("#chat-files")) {
      openCtx(event, filesPaneMenuItems());
      return;
    }

    const tabEl = event.target.closest("[data-tab]");
    if (tabEl && tabsBar && tabsBar.contains(tabEl)) {
      openCtx(event, tabMenuItems(tabEl.dataset.tab));
      return;
    }

    const code = event.target.closest(".md-code");
    if (code && log.contains(code)) {
      const body = code.querySelector("code");
      const text = body ? body.textContent || "" : "";
      const lang = ((code.querySelector(".md-code-lang") || {}).textContent || "").trim();
      const picked = TabbyUI.selectionIn(code);
      openCtx(event, [
        picked ? { label: "Copy selection", run: () => copyText(picked) } : null,
        { label: "Copy code", run: () => copyText(text) },
        { label: "Copy as markdown", run: () => copyText("```" + lang + "\n" + text.replace(/\n$/, "") + "\n```") },
        { label: "Insert into compose", run: () => insertCompose(text) },
        activeMode() === "code" ? { label: "Save as file", run: () => saveCodeAsFile(text, lang) } : null,
      ]);
      return;
    }

    const img = event.target.closest("img");
    if (img && log.contains(img) && img.src) {
      const href = img.src;
      const name = (img.alt && img.alt !== "Attached image") ? img.alt : "image.png";
      openCtx(event, [
        { label: "Open image", run: () => window.open(href, "_blank", "noreferrer") },
        { label: "Copy image URL", run: () => copyText(href) },
        { label: "Download", run: () => saveUrl(href, name.split("/").pop() || "image.png") },
      ]);
      return;
    }

    const link = event.target.closest("a[href]");
    if (link && log.contains(link)) {
      const href = link.href;
      openCtx(event, [
        { label: "Open link", run: () => window.open(href, "_blank", "noreferrer") },
        { label: "Copy URL", run: () => copyText(href) },
      ]);
      return;
    }

    const working = event.target.closest(".chat-turn.is-working");
    if (working && log.contains(working)) {
      const bubble = working.querySelector(".bubble");
      const text = bubble ? bubble.innerText || "" : "";
      openCtx(event, [
        { label: "Stop", danger: true, run: () => abortSession("stop") },
        text ? { label: "Copy", run: () => copyText(text) } : null,
      ]);
      return;
    }

    const msg = event.target.closest("[data-msg-idx]");
    if (msg && log.contains(msg)) {
      const idx = Number(msg.dataset.msgIdx);
      const picked = TabbyUI.selectionIn(msg);
      openCtx(event, messageMenuItems(idx, { picked }));
      return;
    }

    if (event.target.closest("#chat-title")) {
      const chat = activeChat();
      openCtx(event, [
        { label: "Rename", run: () => beginRename() },
        chat ? { label: chat.pinned ? "Unpin" : "Pin", run: () => togglePin() } : null,
        { label: "Copy conversation", run: () => copyText(conversationMarkdown()) },
        { label: "Export markdown", run: () => exportChat() },
        { sep: true },
        { label: "Delete this chat", danger: true, run: () => deleteChat(store.activeId) },
      ]);
      return;
    }

    if (event.target.closest("#chat-queue")) {
      openCtx(event, [
        { label: "Steer now", disabled: !(inFlight && queuedText), run: () => {
          if (steerBtn) steerBtn.click();
        } },
        { label: "Clear queue", run: () => {
          queuedText = "";
          paintCompose();
        } },
      ]);
      return;
    }

    if (event.target.closest("#chat-editor")) {
      const tab = activeTabRow();
      openCtx(event, [
        tab ? { label: "Save", disabled: !tab.dirty || tab.busy, kbd: "Ctrl+S", run: () => saveTab() } : null,
        tab ? { label: "Revert", disabled: !tab.dirty, run: () => revertTab() } : null,
        tab ? { label: "Copy path", run: () => copyText(tab.path) } : null,
        tab ? { label: "Download", run: () => saveUrl(fileUrl(store.activeId, tab.path), tab.path.split("/").pop() || "file") } : null,
        { sep: true },
        { label: "Close file", disabled: !tab, run: () => closeTab(activeTab) },
      ]);
      return;
    }

    if (event.target.closest("#chat-log-wrap, #chat-empty")) {
      const picked = TabbyUI.selectedText();
      openCtx(event, [
        picked ? { label: "Copy selection", run: () => copyText(picked) } : null,
        { label: "Paste into compose", run: () => pasteCompose() },
        { label: "New chat", kbd: "Ctrl+Shift+O", run: () => startNewChat() },
        { label: "Keyboard shortcuts", run: () => showShortcuts() },
      ]);
    }
  }

  shell.addEventListener("contextmenu", onChatContextMenu);

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
    hideAttachMenu();
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
        openFileTab(path);
        return;
      }
      if (btn.dataset.file === "attach") {
        attachProjectFile(path).catch((err) => {
          addBubble("assistant", `Error: ${err.message}`);
        });
        return;
      }
      if (btn.dataset.file === "download") {
        saveUrl(fileUrl(store.activeId, path), path.split("/").pop() || "file");
        return;
      }
      if (btn.dataset.file === "delete") {
        deleteProjectFile(path);
      }
    });
  }
  if (tabsBar) {
    tabsBar.addEventListener("click", (event) => {
      const item = event.target.closest("[data-tab]");
      if (!item) return;
      if (event.target.closest("[data-tab-close]")) {
        closeTab(item.dataset.tab);
        return;
      }
      activateTab(item.dataset.tab);
    });
  }
  if (editorPane) {
    editorPane.addEventListener("input", (event) => {
      if (!event.target.classList.contains("chat-files-edit")) return;
      const tab = activeTabRow();
      if (!tab) return;
      tab.text = event.target.value;
      queueHighlight();
      const next = tab.text !== tab.original;
      if (next === tab.dirty) return;
      tab.dirty = next;
      tab.note = "";
      paintEditorHead();
      paintTabs();
    });
    // A textarea's scroll event does not bubble, so catch it on the way down.
    editorPane.addEventListener("scroll", (event) => {
      if (event.target.classList && event.target.classList.contains("chat-files-edit")) {
        syncEditorScroll();
      }
    }, true);
    editorPane.addEventListener("keydown", (event) => {
      if (!event.target.classList.contains("chat-files-edit")) return;
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        saveTab();
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
    editorPane.addEventListener("click", (event) => {
      const btn = event.target.closest("[data-edit]");
      if (!btn) return;
      const tab = activeTabRow();
      if (btn.dataset.edit === "save") saveTab();
      if (btn.dataset.edit === "revert") revertTab();
      if (btn.dataset.edit === "download" && tab) {
        saveUrl(fileUrl(store.activeId, tab.path), tab.path.split("/").pop() || "file");
      }
    });
  }
  if (filesSiteBtn) {
    filesSiteBtn.addEventListener("click", () => openSite());
  }
  if (filesToggleBtn) {
    filesToggleBtn.addEventListener("click", () => setFilesOpen(!filesOpen));
  }
  if (filesCloseBtn) {
    filesCloseBtn.addEventListener("click", () => setFilesOpen(false));
  }
  // Crossing the breakpoint flips the pane between a column and a bottom sheet,
  // so pick the sensible default for the new shape.
  narrowChat.addEventListener("change", (event) => {
    setFilesOpen(event.matches ? false : readFilesOpen());
    paintToolbar();
  });
  if (filesNewBtn) {
    filesNewBtn.addEventListener("click", () => {
      createUserFile().catch((err) => {
        addBubble("assistant", `Error: ${err.message}`);
      });
    });
  }
  if (filesUploadBtn) {
    filesUploadBtn.addEventListener("click", () => {
      uploadWantsAttach = false;
      if (uploadInput) uploadInput.click();
    });
  }
  if (filesRefreshBtn) {
    filesRefreshBtn.addEventListener("click", () => refreshFiles());
  }
  if (filesZipBtn) {
    filesZipBtn.addEventListener("click", () => downloadZip());
  }
  if (filesClearBtn) {
    filesClearBtn.addEventListener("click", () => clearProjectFiles());
  }
  emptyEl.addEventListener("click", (event) => {
    const btn = event.target.closest("[data-suggest]");
    if (!btn || modelLoading) return;
    input.value = btn.dataset.suggest || "";
    resizeInput();
    form.requestSubmit();
  });
  root.querySelector("#chat-edit-cancel").addEventListener("click", cancelEdit);
  attachBtn.addEventListener("click", () => {
    toggleAttachMenu();
  });
  if (attachMenu) {
    attachMenu.addEventListener("click", (event) => {
      const btn = event.target.closest("[data-attach]");
      if (!btn) return;
      hideAttachMenu();
      if (btn.dataset.attach === "image") {
        if (fileInput) fileInput.click();
        return;
      }
      if (btn.dataset.attach === "upload") {
        uploadWantsAttach = true;
        if (uploadInput) uploadInput.click();
        return;
      }
      if (btn.dataset.attach === "file" && btn.dataset.path) {
        attachProjectFile(btn.dataset.path).catch((err) => {
          addBubble("assistant", `Error: ${err.message}`);
        });
      }
    });
  }
  if (attachList) {
    attachList.addEventListener("click", (event) => {
      const btn = event.target.closest("[data-detach]");
      if (!btn) return;
      detachPending(btn.dataset.detach);
      input.focus();
    });
  }
  fileInput.addEventListener("change", () => {
    const file = fileInput.files && fileInput.files[0];
    setPendingImageFromFile(file).catch((err) => {
      addBubble("assistant", `Error: ${err.message}`);
    });
  });
  if (uploadInput) {
    uploadInput.addEventListener("change", () => {
      const files = uploadInput.files;
      const attach = uploadWantsAttach;
      uploadWantsAttach = false;
      uploadLocalFiles(files, { attach, open: !attach && files.length === 1 })
        .catch((err) => {
          addBubble("assistant", `Error: ${err.message}`);
        })
        .finally(() => {
          uploadInput.value = "";
        });
    });
  }
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
    const files = event.dataTransfer && event.dataTransfer.files;
    if (!files || !files.length) return;
    if (activeMode() === "code") {
      uploadLocalFiles(files, { attach: true, open: files.length === 1 }).catch((err) => {
        addBubble("assistant", `Error: ${err.message}`);
      });
      return;
    }
    setPendingImageFromFile(files[0]).catch((err) => {
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
    refreshCodeChats();
    startGatePoll();
  }
  loadStore();
  return {
    pause() {
      stopGatePoll();
      hideHistoryMenu();
      hideMoreMenu();
      setSidebarOpen(false);
    },
    resume() {
      startGatePoll();
      refreshFiles();
      refreshCodeChats();
    },
    destroy() {
      abortSession("stop");
      stopGatePoll();
      stopLoadingClock();
      hideStackQueue();
      if (filesRefreshTimer) clearTimeout(filesRefreshTimer);
      if (highlightFrame) cancelAnimationFrame(highlightFrame);
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
