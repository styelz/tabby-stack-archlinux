function mountChat(root) {
  root.innerHTML = `
    <div class="chat-wrap">
      <div class="chat-log" id="chat-log"></div>
      <div class="chat-compose">
        <ul class="slash-menu" id="slash-menu" hidden></ul>
        <form class="chat-form" id="chat-form">
          <textarea id="chat-input" rows="2" placeholder="Talk to the loaded model. Type / for commands."></textarea>
          <button class="btn primary" type="submit">Send</button>
        </form>
      </div>
    </div>
  `;
  const log = root.querySelector("#chat-log");
  const form = root.querySelector("#chat-form");
  const input = root.querySelector("#chat-input");
  const menu = root.querySelector("#slash-menu");
  const messages = [{ role: "system", content: "Console chat. No file tools." }];
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

  function addBubble(role, text) {
    const node = document.createElement("div");
    node.className = `bubble ${role}`;
    node.innerHTML = TabbyUI.renderMarkdown(text);
    log.appendChild(node);
    log.scrollTop = log.scrollHeight;
    return node;
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
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!menu.hidden && menuItems[menuIndex]) {
      if (!applyCommand(menuItems[menuIndex])) return;
    }
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    hideMenu();
    try {
      await send(text);
    } catch (err) {
      addBubble("assistant", `Error: ${err.message}`);
    }
  });
  input.addEventListener("input", () => {
    if (input.value.startsWith("/")) renderMenu();
    else hideMenu();
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
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      form.requestSubmit();
    }
  });
  return { destroy() {} };
}

window.mountChat = mountChat;
