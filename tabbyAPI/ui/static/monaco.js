(() => {
  const VERSION = "0.52.2";
  const CDN = `https://cdn.jsdelivr.net/npm/monaco-editor@${VERSION}/min/vs`;

  let loadPromise = null;
  let editor = null;
  let diffEditor = null;
  let originalModel = null;
  let modifiedModel = null;
  let onChange = null;
  let onSave = null;
  let ignoreChange = false;
  let currentPath = "";

  function localVs() {
    return window.TabbyUI ? window.TabbyUI.path("assets/vs") : "/v1/ui/assets/vs";
  }

  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const node = document.createElement("script");
      node.src = src;
      node.onload = resolve;
      node.onerror = reject;
      document.head.appendChild(node);
    });
  }

  function loadCss(href) {
    if (document.querySelector(`link[data-monaco="${href}"]`)) return;
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = href;
    link.dataset.monaco = href;
    document.head.appendChild(link);
  }

  async function ensure() {
    if (window.monaco) return window.monaco;
    if (loadPromise) return loadPromise;
    loadPromise = (async () => {
      let vs = localVs();
      try {
        await loadScript(`${vs}/loader.js`);
      } catch {
        vs = CDN;
        await loadScript(`${vs}/loader.js`);
      }
      loadCss(`${vs}/editor/editor.main.css`);
      window.require.config({ paths: { vs } });
      await new Promise((resolve) => window.require(["vs/editor/editor.main"], resolve));
      window.monaco.editor.defineTheme("tabby", {
        base: "vs-dark",
        inherit: true,
        rules: [],
        colors: {
          "editor.background": "#12151c",
          "editor.foreground": "#e8ecf4",
          "editorLineNumber.foreground": "#5a6379",
          "editorGutter.background": "#0e1218",
          "editor.lineHighlightBackground": "#1a2030",
          "diffEditor.insertedTextBackground": "#1c3d2a66",
          "diffEditor.removedTextBackground": "#4a1f2466",
          "diffEditor.insertedLineBackground": "#1c3d2a33",
          "diffEditor.removedLineBackground": "#4a1f2433",
        },
      });
      window.monaco.editor.setTheme("tabby");
      return window.monaco;
    })();
    return loadPromise;
  }

  function languageFor(path) {
    const ext = String(path || "").split(".").pop().toLowerCase();
    const map = {
      html: "html",
      htm: "html",
      css: "css",
      js: "javascript",
      mjs: "javascript",
      jsx: "javascript",
      ts: "typescript",
      tsx: "typescript",
      json: "json",
      md: "markdown",
      py: "python",
      sh: "shell",
      xml: "xml",
      svg: "xml",
      yml: "yaml",
      yaml: "yaml",
      php: "php",
      txt: "plaintext",
      csv: "plaintext",
      toml: "ini",
      ini: "ini",
      conf: "ini",
    };
    return map[ext] || "plaintext";
  }

  function modelUri(path) {
    const clean = String(path || "untitled").replace(/^\/+/, "");
    return window.monaco.Uri.parse(`inmemory://tabby/${clean}`);
  }

  function disposeModels() {
    if (originalModel) {
      originalModel.dispose();
      originalModel = null;
    }
    if (modifiedModel) {
      modifiedModel.dispose();
      modifiedModel = null;
    }
  }

  function disposeEditors() {
    if (editor) {
      editor.dispose();
      editor = null;
    }
    if (diffEditor) {
      diffEditor.dispose();
      diffEditor = null;
    }
    disposeModels();
  }

  const common = {
    theme: "tabby",
    automaticLayout: true,
    fontSize: 13,
    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace',
    minimap: { enabled: true, maxColumn: 80 },
    scrollBeyondLastLine: false,
    tabSize: 2,
    insertSpaces: true,
    wordWrap: "off",
    renderWhitespace: "selection",
    smoothScrolling: true,
    padding: { top: 8 },
    mouseWheelZoom: true,
    contextmenu: true,
    folding: true,
    glyphMargin: true,
    lineNumbers: "on",
    renderLineHighlight: "all",
    bracketPairColorization: { enabled: true },
    autoClosingBrackets: "languageDefined",
    formatOnPaste: true,
    links: true,
    find: { addExtraSpaceOnTop: false, seedSearchStringFromSelection: "always" },
  };

  function bindSave(ed) {
    if (!ed || !window.monaco) return;
    ed.addCommand(window.monaco.KeyMod.CtrlCmd | window.monaco.KeyCode.KeyS, () => {
      if (typeof onSave === "function") onSave();
    });
  }

  function getEditEditor() {
    if (editor) return editor;
    if (diffEditor) return diffEditor.getModifiedEditor();
    return null;
  }

  async function showFile(el, opts) {
    if (!el) return;
    const monaco = await ensure();
    currentPath = opts.path || "";
    disposeEditors();
    el.innerHTML = "";
    const uri = modelUri(currentPath);
    const existing = monaco.editor.getModel(uri);
    if (existing) existing.dispose();
    modifiedModel = monaco.editor.createModel(
      opts.text || "",
      languageFor(currentPath),
      uri
    );
    editor = monaco.editor.create(el, {
      ...common,
      model: modifiedModel,
      readOnly: Boolean(opts.readOnly),
    });
    editor.onDidChangeModelContent(() => {
      if (ignoreChange || typeof onChange !== "function") return;
      onChange(editor.getValue());
    });
    bindSave(editor);
    if (Array.isArray(opts.caret) && modifiedModel) {
      const pos = modifiedModel.getPositionAt(Math.max(0, opts.caret[0] || 0));
      editor.setPosition(pos);
      editor.revealPositionInCenter(pos);
    }
    editor.focus();
    if (window.TabbyLsp) window.TabbyLsp.attachMonaco(currentPath, editor);
  }

  async function showDiff(el, opts) {
    if (!el) return;
    const monaco = await ensure();
    currentPath = opts.path || "";
    disposeEditors();
    el.innerHTML = "";
    originalModel = monaco.editor.createModel(
      opts.original || "",
      languageFor(currentPath)
    );
    modifiedModel = monaco.editor.createModel(
      opts.modified || "",
      languageFor(currentPath),
      modelUri(currentPath)
    );
    diffEditor = monaco.editor.createDiffEditor(el, {
      ...common,
      originalEditable: false,
      renderSideBySide: !window.matchMedia("(max-width: 1100px)").matches,
      useInlineViewWhenSpaceIsLimited: true,
      readOnly: false,
    });
    diffEditor.setModel({ original: originalModel, modified: modifiedModel });
    const modified = diffEditor.getModifiedEditor();
    modified.onDidChangeModelContent(() => {
      if (ignoreChange || typeof onChange !== "function") return;
      onChange(modified.getValue());
    });
    bindSave(modified);
    modified.focus();
    if (window.TabbyLsp) window.TabbyLsp.attachMonaco(currentPath, modified);
  }

  window.TabbyMonaco = {
    ready: ensure,
    languageFor,
    showFile,
    showDiff,
    getValue() {
      const ed = getEditEditor();
      return ed ? ed.getValue() : "";
    },
    setValue(text) {
      const ed = getEditEditor();
      if (!ed) return;
      ignoreChange = true;
      ed.setValue(String(text || ""));
      ignoreChange = false;
    },
    getCaret() {
      const ed = getEditEditor();
      const model = ed && ed.getModel();
      const sel = ed && ed.getSelection();
      if (!model || !sel) return null;
      return [model.getOffsetAt(sel.getStartPosition()), model.getOffsetAt(sel.getEndPosition())];
    },
    layout() {
      if (editor) editor.layout();
      if (diffEditor) diffEditor.layout();
    },
    find() {
      const ed = getEditEditor();
      if (!ed) return;
      const action = ed.getAction("actions.find");
      if (action) action.run();
    },
    setMarkers(path, items) {
      if (!window.monaco) return;
      const model = window.monaco.editor.getModel(modelUri(path));
      if (!model) return;
      const markers = (items || []).map((item) => {
        const range = item.range || {};
        const start = range.start || {};
        const end = range.end || start;
        return {
          severity:
            Number(item.severity) === 1
              ? window.monaco.MarkerSeverity.Error
              : Number(item.severity) === 2
                ? window.monaco.MarkerSeverity.Warning
                : window.monaco.MarkerSeverity.Info,
          message: String(item.message || ""),
          startLineNumber: (start.line || 0) + 1,
          startColumn: (start.character || 0) + 1,
          endLineNumber: (end.line || start.line || 0) + 1,
          endColumn: (end.character || start.character || 0) + 1,
        };
      });
      window.monaco.editor.setModelMarkers(model, "tabby-lsp", markers);
    },
    onChange(fn) {
      onChange = fn;
    },
    onSave(fn) {
      onSave = fn;
    },
    dispose: disposeEditors,
    getEditor: getEditEditor,
    path() {
      return currentPath;
    },
  };
})();
