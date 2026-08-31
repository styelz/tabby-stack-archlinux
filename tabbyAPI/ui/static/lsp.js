(() => {
  const CHANGE_WAIT_MS = 280;
  const LANGS = ["python", "javascript", "typescript", "html", "css", "json"];

  function wsUrl(suffix) {
    const href = new URL(window.TabbyUI.path(suffix), window.location.href);
    href.protocol = href.protocol === "https:" ? "wss:" : "ws:";
    return href.href;
  }

  function preferHttp() {
    try {
      const base = window.TabbyUI.path("");
      return Boolean(base && !base.startsWith("/v1/ui"));
    } catch {
      return false;
    }
  }

  const state = {
    socket: null,
    chatId: "",
    path: "",
    version: 1,
    req: 0,
    pending: Object.create(null),
    changeTimer: 0,
    queue: [],
    providers: false,
    http: preferHttp(),
  };

  function applyMessage(message) {
    if (!message || typeof message !== "object") return;
    if (message.type === "diagnostics") {
      if (window.TabbyMonaco) window.TabbyMonaco.setMarkers(message.path, message.items || []);
      return;
    }
    const pending = state.pending[message.id];
    if (pending) {
      delete state.pending[message.id];
      pending(message);
    }
  }

  async function sendHttp(payload) {
    const chatId = state.chatId;
    if (!chatId || !window.TabbyUI) return { type: "unavailable" };
    try {
      const data = await window.TabbyUI.api(
        `workspace/${encodeURIComponent(chatId)}/lsp`,
        { method: "POST", body: payload }
      );
      (data.events || []).forEach(applyMessage);
      return data.reply || { type: "unavailable" };
    } catch {
      return { type: "unavailable" };
    }
  }

  function send(payload) {
    if (state.http) {
      const id = payload.id;
      sendHttp(payload).then((reply) => {
        if (id && state.pending[id]) {
          const pending = state.pending[id];
          delete state.pending[id];
          pending(reply || { type: "unavailable" });
        }
      });
      return true;
    }
    if (!state.socket || state.socket.readyState !== 1) {
      state.queue.push(payload);
      return false;
    }
    state.socket.send(JSON.stringify(payload));
    return true;
  }

  function flushQueue() {
    while (state.queue.length) {
      if (!state.http && !(state.socket && state.socket.readyState === 1)) return;
      send(state.queue.shift());
    }
  }

  const REQUEST_MS = 8000;

  function settlePending(id, value) {
    const resolve = state.pending[id];
    if (!resolve) return;
    delete state.pending[id];
    resolve(value);
  }

  function request(payload) {
    return new Promise((resolve) => {
      const id = (state.req += 1);
      state.pending[id] = resolve;
      send(Object.assign({ id }, payload));
      setTimeout(() => settlePending(id, { type: "unavailable" }), REQUEST_MS);
    });
  }

  function connect(chatId) {
    if (!chatId) return;
    if (state.http) {
      state.chatId = chatId;
      flushQueue();
      return;
    }
    if (state.socket && state.chatId === chatId && state.socket.readyState < 2) return;
    resetSocket(false);
    state.chatId = chatId;
    const socket = new WebSocket(wsUrl(`workspace/${encodeURIComponent(chatId)}/lsp`));
    state.socket = socket;
    let opened = false;
    socket.onopen = () => {
      opened = true;
      flushQueue();
    };
    socket.onmessage = (event) => {
      let message;
      try {
        message = JSON.parse(event.data);
      } catch {
        return;
      }
      applyMessage(message);
    };
    socket.onclose = () => {
      if (state.socket !== socket) return;
      state.socket = null;
      if (!opened) {
        state.http = true;
        flushQueue();
      }
    };
  }

  function resetSocket(clearChat) {
    if (state.socket) {
      try {
        state.socket.close();
      } catch {
        /* ignore */
      }
    }
    state.socket = null;
    const pending = state.pending;
    state.pending = Object.create(null);
    Object.keys(pending).forEach((id) => {
      try {
        pending[id]({ type: "unavailable" });
      } catch {
        /* ignore */
      }
    });
    state.queue = [];
    if (clearChat) state.chatId = "";
  }

  function monacoKind(item) {
    const monaco = window.monaco;
    if (!monaco) return 1;
    const kinds = monaco.languages.CompletionItemKind;
    const raw = String((item && (item.kind || item.label)) || "").toLowerCase();
    if (raw.includes("fn") || raw.includes("method")) return kinds.Method;
    if (raw.includes("class")) return kinds.Class;
    if (raw.includes("prop")) return kinds.Property;
    if (raw.includes("var")) return kinds.Variable;
    return kinds.Text;
  }

  function pathFromModel(model) {
    if (window.TabbyMonaco && typeof TabbyMonaco.pathForModel === "function") {
      return TabbyMonaco.pathForModel(model);
    }
    const value = model && model.uri && (model.uri.path || model.uri.fsPath || "");
    return String(value || "").replace(/^\/+/, "");
  }

  function locationToMonaco(item) {
    const monaco = window.monaco;
    if (!monaco || !item || !item.path) return null;
    const line = Number(item.line) || 0;
    const character = Number(item.character) || 0;
    const uri = monaco.Uri.parse(`inmemory://tabby/${String(item.path).replace(/^\/+/, "")}`);
    const pos = new monaco.Range(line + 1, character + 1, line + 1, character + 1);
    return { uri, range: pos };
  }

  function registerProviders() {
    if (state.providers || !window.monaco) return;
    state.providers = true;
    const monaco = window.monaco;
    LANGS.forEach((language) => {
      monaco.languages.registerCompletionItemProvider(language, {
        triggerCharacters: [".", "<", '"', "'", "/", "-", ":", "("],
        provideCompletionItems: async (model, position) => {
          const path = pathFromModel(model);
          const reply = await request({
            type: "completion",
            path,
            line: position.lineNumber - 1,
            character: position.column - 1,
          });
          const items = (reply && reply.items) || [];
          return {
            suggestions: items.slice(0, 40).map((item) => ({
              label: item.label,
              insertText: String(item.insert || item.label || ""),
              detail: item.detail || "",
              kind: monacoKind(item),
              range: {
                startLineNumber: position.lineNumber,
                startColumn: position.column,
                endLineNumber: position.lineNumber,
                endColumn: position.column,
              },
            })),
          };
        },
      });
      monaco.languages.registerHoverProvider(language, {
        provideHover: async (model, position) => {
          const path = pathFromModel(model);
          const reply = await request({
            type: "hover",
            path,
            line: position.lineNumber - 1,
            character: position.column - 1,
          });
          const text = reply && reply.contents;
          if (!text) return null;
          return { contents: [{ value: String(text) }] };
        },
      });
      monaco.languages.registerDefinitionProvider(language, {
        provideDefinition: async (model, position) => {
          const path = pathFromModel(model);
          const reply = await request({
            type: "definition",
            path,
            line: position.lineNumber - 1,
            character: position.column - 1,
          });
          return (reply && reply.locations || []).map(locationToMonaco).filter(Boolean);
        },
      });
      monaco.languages.registerReferenceProvider(language, {
        provideReferences: async (model, position) => {
          const path = pathFromModel(model);
          const reply = await request({
            type: "references",
            path,
            line: position.lineNumber - 1,
            character: position.column - 1,
          });
          return (reply && reply.locations || []).map(locationToMonaco).filter(Boolean);
        },
      });
      monaco.languages.registerDocumentFormattingEditProvider(language, {
        provideDocumentFormattingEdits: async (model, options) => {
          const path = pathFromModel(model);
          const reply = await request({
            type: "format",
            path,
            tabSize: options && options.tabSize,
            insertSpaces: !(options && options.insertSpaces === false),
          });
          const edits = (reply && reply.edits) || [];
          return edits.map((item) => ({
            range: new monaco.Range(
              (item.startLine || 0) + 1,
              (item.startCharacter || 0) + 1,
              (item.endLine || 0) + 1,
              (item.endCharacter || 0) + 1
            ),
            text: String(item.text || ""),
          }));
        },
      });
    });
    if (typeof monaco.editor.registerEditorOpener === "function") {
      monaco.editor.registerEditorOpener({
        openCodeEditor(_source, resource, selection) {
          const path = String((resource && resource.path) || "").replace(/^\/+/, "");
          if (!path) return false;
          if (typeof window.tabbyOpenWorkspaceFile === "function") {
            const line = selection && (selection.startLineNumber || selection.selectionStartLineNumber);
            const column = selection && (selection.startColumn || selection.selectionStartColumn);
            window.tabbyOpenWorkspaceFile(path, line, column);
            return true;
          }
          return false;
        },
      });
    }
  }

  window.TabbyLsp = {
    didOpen(path, text) {
      const chatId = state.chatId;
      if (!path) return;
      if (chatId) connect(chatId);
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
    complete() {
      const ed = window.TabbyMonaco && window.TabbyMonaco.getEditor();
      if (ed) ed.trigger("tabby", "editor.action.triggerSuggest", {});
    },
    attachMonaco(path, editor) {
      registerProviders();
      if (editor && path) {
        state.path = path;
        this.didOpen(path, editor.getValue());
      }
    },
    format() {
      const ed = window.TabbyMonaco && window.TabbyMonaco.getEditor();
      if (ed) ed.getAction("editor.action.formatDocument").run();
    },
    reset() {
      resetSocket(true);
      state.path = "";
    },
    setChat(chatId) {
      state.chatId = chatId || "";
      if (chatId) connect(chatId);
    },
  };
})();
