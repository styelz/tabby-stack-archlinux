function mountChat(root) {
  root.innerHTML = `
    <div class="chat-wrap">
      <div class="toolbar chat-toolbar">
        <button class="btn" type="button" id="chat-new">New chat</button>
        <button class="btn danger" type="button" id="chat-clear">Clear history</button>
        <span class="chat-title" id="chat-title">New chat</span>
        <span class="spacer"></span>
        <span class="muted" id="chat-hint">Tab previous chats · ↑↓ recall</span>
      </div>
      <div class="chat-log" id="chat-log"></div>
      <div class="chat-compose">
        <ul class="slash-menu" id="history-menu" hidden></ul>
        <ul class="slash-menu" id="slash-menu" hidden></ul>
        <form class="chat-form" id="chat-form">
          <textarea id="chat-input" rows="2" placeholder="Talk to the loaded model. Type / for commands. ↑↓ recalls what you sent."></textarea>
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
    return (Array.isArray(list) ? list : []).map((item) => {
      const out = {
        role: item.role === "assistant" || item.role === "system" ? item.role : "user",
        content: String(item.content || ""),
      };
      if (out.role === "assistant" && item.reasoning) {
        out.reasoning = String(item.reasoning);
      }
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
  let recallIndex = -1;
  let recallDraft = "";

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

  function addBubble(role, text, stick, reasoning) {
    if (role === "assistant") {
      const turn = addAssistantTurn({ content: text, reasoning, live: false });
      if (stick !== false) log.scrollTop = log.scrollHeight;
      return turn.node;
    }
    const node = document.createElement("div");
    node.className = `bubble ${role}`;
    node.innerHTML = TabbyUI.renderMarkdown(text);
    log.appendChild(node);
    if (stick !== false) log.scrollTop = log.scrollHeight;
    return node;
  }

  function activityFromPrompt(text) {
    const raw = String(text || "").trim();
    const lower = raw.toLowerCase();
    if (/^restart$/i.test(lower) || lower === "/restart") {
      return { label: "Restarting", kind: "restart", processing: true };
    }
    const sw = lower.match(/^switch to (\S+)/) || lower.match(/^\/(qwen\d*|gemma\d*|glm|comfy|flux|llm)\b/);
    if (sw) {
      const name = sw[1];
      return { label: `Switching to ${name}`, kind: "switch", processing: true };
    }
    if (
      /^(generate an image|qwen-image:)/i.test(raw) ||
      /^\/image\b/i.test(raw) ||
      /\b(generate|draw|paint|render|create|make)\b[\s\S]{0,80}\b(image|picture|logo|poster|icon|svg)\b/i.test(lower) ||
      /\b(svg|png|jpg|jpeg|webp)\b.+\b(image|picture|logo|of)\b/i.test(lower)
    ) {
      return { label: "Generating image", kind: "image", processing: true };
    }
    if (/^(help|list models)$/i.test(lower) || lower === "/help" || lower === "/list models") {
      return { label: "Working", kind: "cmd", processing: true };
    }
    return { label: "Thinking", kind: "chat", processing: false };
  }

  function visibleAnswerText(text) {
    return String(text || "").replace(/\s+/g, " ").trim();
  }

  function labelForJob(job) {
    if (!job) return "";
    const phase = String(job.phase || job.status || "");
    const count = Number(job.count) || 0;
    const done = Number(job.done_count) || 0;
    if (phase === "queued") return "Queued";
    if (phase === "writing_code" || phase === "coding") return "Planning the image";
    if (phase === "starting_comfy") return "Handing GPU to Comfy";
    if (phase === "generating" || phase === "running") {
      if (count > 1) return `Generating image ${Math.min(done + 1, count)} of ${count}`;
      return "Generating image";
    }
    if (phase === "restoring_llm") return "Reloading the model";
    if (job.status === "queued" || job.status === "running" || job.status === "coding") {
      return "Generating image";
    }
    return "";
  }

  function addAssistantTurn({ content, reasoning, live, activity }) {
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
    label.textContent = (activity && activity.label) || "Thinking";
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

    function showAnswer(html) {
      const markup = String(html || "").trim();
      if (!markup) return false;
      ensureBubble();
      bubble.innerHTML = markup;
      bubble.hidden = false;
      turn.classList.add("has-answer");
      return true;
    }

    turn.append(head, thought);
    if (visibleAnswerText(content)) {
      showAnswer(TabbyUI.renderMarkdown(content));
    }

    let reasoningText = reasoning ? String(reasoning) : "";
    let finished = !live;
    let expanded = false;
    let processing = Boolean(activity && activity.processing);
    const started = Date.now();
    let ticker = null;

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

    function settleThought(seconds) {
      head.hidden = false;
      head.classList.remove("is-live");
      icon.hidden = true;
      chevron.hidden = false;
      head.classList.add("is-clickable");
      if (head.tagName !== "BUTTON") {
        head.setAttribute("role", "button");
        head.tabIndex = 0;
      }
      label.textContent = seconds != null ? `Thought for ${seconds}s` : "Thought";
      timeEl.textContent = "";
      thought.hidden = true;
      expanded = false;
      head.classList.remove("is-open");
    }

    if (live) {
      setProcessing(processing);
      ticker = setInterval(() => {
        const s = Math.round((Date.now() - started) / 1000);
        if (s >= 2) timeEl.textContent = `${s}s`;
      }, 250);
    } else if (reasoningText) {
      settleThought();
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
      setActivity(text, opts) {
        if (finished || !text) return;
        label.textContent = text;
        head.hidden = false;
        if (opts && opts.processing != null) setProcessing(opts.processing);
      },
      setReasoning(text) {
        if (!text) return;
        reasoningText = text;
        if (!finished) {
          label.textContent = "Thinking";
          head.hidden = false;
          setProcessing(false);
        }
        paintThought();
        log.scrollTop = log.scrollHeight;
      },
      setAnswer(text) {
        const value = visibleAnswerText(text);
        if (!value) return;
        showAnswer(TabbyUI.renderMarkdown(String(text || "")));
        if (reasoningText) {
          thought.hidden = true;
        } else {
          // Real answer tokens replace the working status line.
          turn.classList.remove("is-working");
          head.hidden = true;
        }
        log.scrollTop = log.scrollHeight;
      },
      finish({ content: finalContent, reasoning: finalReasoning } = {}) {
        if (finished && !live) return;
        finished = true;
        if (ticker) {
          clearInterval(ticker);
          ticker = null;
        }
        turn.classList.remove("is-working");
        head.classList.remove("is-live");
        turn.removeAttribute("aria-busy");
        turn.setAttribute("aria-live", "off");
        if (finalReasoning) reasoningText = String(finalReasoning);
        const seconds = Math.max(1, Math.round((Date.now() - started) / 1000));
        const answer = visibleAnswerText(finalContent);
        if (answer) {
          showAnswer(TabbyUI.renderMarkdown(String(finalContent || "")));
        } else if (!bubbleMounted || !visibleAnswerText(bubble.textContent)) {
          showAnswer(TabbyUI.renderMarkdown("(empty reply)"));
        }
        if (reasoningText) {
          settleThought(seconds);
          paintThought();
        } else {
          head.hidden = true;
          thought.hidden = true;
        }
        log.scrollTop = log.scrollHeight;
      },
      stopClock() {
        if (ticker) {
          clearInterval(ticker);
          ticker = null;
        }
      },
    };
  }

  function addWorkingReply(activity) {
    return addAssistantTurn({ live: true, activity });
  }

  function renderLog(stickToEnd) {
    log.replaceChildren();
    messages.forEach((item) => {
      if (item.role === "user") addBubble("user", item.content, false);
      else if (item.role === "assistant") addBubble("assistant", item.content, false, item.reasoning);
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
    resetRecall();
    renderLog(stickToEnd !== false);
    input.focus();
  }

  function startNewChat() {
    persist();
    if (!hasUserTurn({ messages })) {
      resetRecall();
      renderLog();
      input.focus();
      return;
    }
    const chat = emptyChat();
    store.chats.unshift(chat);
    store.activeId = chat.id;
    messages = cloneMessages(chat.messages);
    persist();
    resetRecall();
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
    resetRecall();
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
    highlightMenu(historyMenu, historyIndex);
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
      if (comment.includes("tabby-image-job:")) onEvent({ comment });
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
        if (kind === "image") {
          const next = labelForJob(data && data.job);
          if (next) working.setActivity(next, { processing: true });
          return;
        }
        if (kind === "switch" || kind === "restart") {
          const model = data && data.model;
          const busy = data && (data.switching || data.restarting || data.busy);
          if (busy && kind === "switch") {
            const name = (model && (model.profile || model.name)) || "";
            working.setActivity(name ? `Switching to ${name}` : "Switching", { processing: true });
          } else if (busy && kind === "restart") {
            working.setActivity("Restarting", { processing: true });
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

  async function send(text) {
    const outboundText = expandSlash(text);
    messages.push({ role: "user", content: outboundText });
    touchActive();
    persist();
    addBubble("user", outboundText);
    const activity = activityFromPrompt(outboundText);
    const working = addWorkingReply(activity);
    const poll = startStatusPoll(working, activity.kind);
    let assembled = "";
    let reasoning = "";
    const outbound = messages.filter((m) => m.role !== "system");
    try {
      const response = await fetch(TabbyUI.path("chat"), {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", Accept: "text/event-stream, application/json" },
        body: JSON.stringify({ messages: outbound, stream: true }),
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
            if (event.comment && event.comment.includes("tabby-image-job:")) {
              working.setActivity("Generating image", { processing: true });
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
      assembled = assembled || `Error: ${err.message}`;
    } finally {
      poll.stop();
      working.finish({ content: assembled, reasoning });
    }
    const item = { role: "assistant", content: assembled };
    if (reasoning) item.reasoning = reasoning;
    messages.push(item);
    persist();
  }

  root.querySelector("#chat-new").addEventListener("click", startNewChat);
  root.querySelector("#chat-clear").addEventListener("click", clearHistory);

  let inFlight = false;
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (inFlight) return;
    if (!menu.hidden && menuItems[menuIndex]) {
      if (!applyCommand(menuItems[menuIndex])) return;
    }
    hideHistoryMenu();
    const text = input.value.trim();
    if (!text) return;
    resetRecall();
    input.value = "";
    hideMenu();
    inFlight = true;
    const sendBtn = form.querySelector("button[type=submit]");
    if (sendBtn) sendBtn.disabled = true;
    try {
      await send(text);
    } catch (err) {
      addBubble("assistant", `Error: ${err.message}`);
      persist();
    } finally {
      inFlight = false;
      if (sendBtn) sendBtn.disabled = false;
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
    if (!historyMenu.hidden && (event.key === "Escape" || event.key === "Enter")) {
      event.preventDefault();
      hideHistoryMenu();
      return;
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
      return;
    }
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      form.requestSubmit();
    }
  });

  log.addEventListener("mouseup", () => {
    const sel = window.getSelection();
    if (sel && String(sel).trim()) return;
    input.focus();
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
