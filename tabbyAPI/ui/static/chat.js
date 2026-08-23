function mountChat(root) {
  root.innerHTML = `
    <div class="chat-wrap">
      <div class="chat-log" id="chat-log"></div>
      <form class="chat-form" id="chat-form">
        <textarea id="chat-input" rows="2" placeholder="Talk to the loaded model. Images show inline. This console does not write project files."></textarea>
        <button class="btn primary" type="submit">Send</button>
      </form>
    </div>
  `;
  const log = root.querySelector("#chat-log");
  const form = root.querySelector("#chat-form");
  const input = root.querySelector("#chat-input");
  const messages = [{ role: "system", content: "Console chat. No file tools." }];

  function addBubble(role, text) {
    const node = document.createElement("div");
    node.className = `bubble ${role}`;
    node.innerHTML = TabbyUI.renderMarkdown(text);
    log.appendChild(node);
    log.scrollTop = log.scrollHeight;
    return node;
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
      try {
        const json = JSON.parse(payload);
        const delta = json.choices?.[0]?.delta?.content || json.choices?.[0]?.message?.content || json.line;
        if (delta) onDelta(delta);
      } catch {
        onDelta(payload);
      }
    }
    return rest;
  }

  async function send(text) {
    messages.push({ role: "user", content: text });
    addBubble("user", text);
    const bubble = addBubble("assistant", "");
    let assembled = "";
    const response = await fetch(TabbyUI.path("chat"), {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream, application/json" },
      body: JSON.stringify({ messages: messages.filter((m) => m.role !== "system").concat([{ role: "user", content: text }]), stream: true }),
    });
    if (response.status === 401) {
      window.location.href = TabbyUI.path("login");
      return;
    }
    const type = response.headers.get("content-type") || "";
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
    bubble.innerHTML = TabbyUI.renderMarkdown(assembled || "(empty reply)");
    messages.push({ role: "assistant", content: assembled });
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    try {
      await send(text);
    } catch (err) {
      addBubble("assistant", `Error: ${err.message}`);
    }
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      form.requestSubmit();
    }
  });
  return { destroy() {} };
}

window.mountChat = mountChat;
