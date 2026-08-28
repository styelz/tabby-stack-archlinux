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
  let mountGen = 0;

  function localVs() {
    const rel = window.TabbyUI ? window.TabbyUI.path("assets/vs") : "/v1/ui/assets/vs";
    try {
      return new URL(rel, window.location.href).href.replace(/\/+$/, "");
    } catch {
      return rel;
    }
  }

  function installWorkers(vs) {
    const base = String(vs || "").replace(/\/+$/, "");
    const workerMain = `${base}/base/worker/workerMain.js`;
    const body =
      `self.MonacoEnvironment={baseUrl:${JSON.stringify(`${base}/`)}};` +
      `importScripts(${JSON.stringify(workerMain)});`;
    const workerUrl = URL.createObjectURL(new Blob([body], { type: "text/javascript" }));
    window.MonacoEnvironment = {
      getWorkerUrl() {
        return workerUrl;
      },
    };
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

  function hexByte(n) {
    return Math.max(0, Math.min(255, Math.round(Number(n) || 0)))
      .toString(16)
      .padStart(2, "0");
  }

  function channelByte(value) {
    const raw = String(value || "").trim();
    if (raw.endsWith("%")) return (parseFloat(raw) / 100) * 255;
    return Number(raw);
  }

  function alphaByte(value) {
    const raw = String(value || "").trim();
    if (!raw) return 255;
    if (raw.endsWith("%")) return (parseFloat(raw) / 100) * 255;
    const n = Number(raw);
    return n <= 1 ? n * 255 : n;
  }

  // Monaco token colors must be #hex. getComputedStyle returns rgb()/rgba().
  function toMonacoHex(value, fallback) {
    const raw = String(value || "").trim();
    if (!raw) return fallback;
    if (/^#[0-9a-f]{3,8}$/i.test(raw)) {
      if (raw.length === 4) {
        return `#${raw[1]}${raw[1]}${raw[2]}${raw[2]}${raw[3]}${raw[3]}`.toLowerCase();
      }
      if (raw.length === 5) {
        return `#${raw[1]}${raw[1]}${raw[2]}${raw[2]}${raw[3]}${raw[3]}${raw[4]}${raw[4]}`.toLowerCase();
      }
      return raw.toLowerCase();
    }
    const rgb = raw.match(
      /^rgba?\(\s*([\d.]+%?)\s*[, ]\s*([\d.]+%?)\s*[, ]\s*([\d.]+%?)(?:\s*[,/]\s*([\d.]+%?))?\s*\)$/i
    );
    if (rgb) {
      const r = hexByte(channelByte(rgb[1]));
      const g = hexByte(channelByte(rgb[2]));
      const b = hexByte(channelByte(rgb[3]));
      if (rgb[4] === undefined) return `#${r}${g}${b}`;
      const a = hexByte(alphaByte(rgb[4]));
      return a === "ff" ? `#${r}${g}${b}` : `#${r}${g}${b}${a}`;
    }
    return fallback;
  }

  function cssColor(name, fallback) {
    const probe = document.createElement("span");
    probe.style.backgroundColor = `var(${name})`;
    document.documentElement.appendChild(probe);
    const resolved = getComputedStyle(probe).backgroundColor;
    probe.remove();
    if (resolved && resolved !== "transparent" && resolved !== "rgba(0, 0, 0, 0)") {
      return toMonacoHex(resolved, fallback);
    }
    const value =
      window.TabbyUI && TabbyUI.cssVar
        ? TabbyUI.cssVar(name)
        : getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return toMonacoHex(value, fallback);
  }

  function applyMonacoTheme() {
    if (!window.monaco) return;
    const id = document.documentElement.getAttribute("data-theme") || "midnight-dark";
    const light = /-light$/.test(id);
    window.monaco.editor.defineTheme("tabby", {
      base: light ? "vs" : "vs-dark",
      inherit: true,
      rules: [],
      colors: {
        "editor.background": cssColor("--bg-elev", "#12151c"),
        "editor.foreground": cssColor("--text", "#e8ecf4"),
        "editorLineNumber.foreground": cssColor("--editor-muted", "#5a6379"),
        "editorGutter.background": cssColor("--editor-gutter", "#0e1218"),
        "editor.lineHighlightBackground": cssColor("--editor-line", "#1a2030"),
        "diffEditor.insertedTextBackground": cssColor("--diff-add-text", "#3dd68c73"),
        "diffEditor.removedTextBackground": cssColor("--diff-del-text", "#ff6b7a73"),
        "diffEditor.insertedLineBackground": cssColor("--diff-add-line", "#3dd68c4d"),
        "diffEditor.removedLineBackground": cssColor("--diff-del-line", "#ff6b7a4d"),
        "diffEditorGutter.insertedLineBackground": cssColor("--diff-add-line", "#3dd68c4d"),
        "diffEditorGutter.removedLineBackground": cssColor("--diff-del-line", "#ff6b7a4d"),
        "diffEditorOverview.insertedForeground": cssColor("--diff-add-gutter", "#3dd68cbf"),
        "diffEditorOverview.removedForeground": cssColor("--diff-del-gutter", "#ff6b7abf"),
        "editorGutter.addedBackground": cssColor("--diff-add-gutter", "#3dd68cbf"),
        "editorGutter.deletedBackground": cssColor("--diff-del-gutter", "#ff6b7abf"),
        "minimapGutter.addedBackground": cssColor("--diff-add-gutter", "#3dd68cbf"),
        "minimapGutter.deletedBackground": cssColor("--diff-del-gutter", "#ff6b7abf"),
        "scrollbar.shadow": "#00000000",
        "scrollbarSlider.background": cssColor("--scroll-thumb", "#7aa2ff66"),
        "scrollbarSlider.hoverBackground": cssColor("--scroll-thumb-hover", "#7aa2ffad"),
        "scrollbarSlider.activeBackground": cssColor("--scroll-thumb-active", "#7aa2ffe0"),
        "minimapSlider.background": cssColor("--scroll-thumb", "#7aa2ff66"),
        "minimapSlider.hoverBackground": cssColor("--scroll-thumb-hover", "#7aa2ffad"),
        "minimapSlider.activeBackground": cssColor("--scroll-thumb-active", "#7aa2ffe0"),
      },
    });
    window.monaco.editor.setTheme("tabby");
  }

  async function ensure() {
    if (window.monaco) return window.monaco;
    if (loadPromise) return loadPromise;
    loadPromise = (async () => {
      try {
        let vs = localVs();
        try {
          await loadScript(`${vs}/loader.js`);
        } catch {
          vs = CDN;
          await loadScript(`${vs}/loader.js`);
        }
        loadCss(`${vs}/editor/editor.main.css`);
        installWorkers(vs);
        window.require.config({ paths: { vs } });
        await new Promise((resolve, reject) => {
          try {
            window.require(["vs/editor/editor.main"], resolve);
          } catch (err) {
            reject(err);
          }
        });
        applyMonacoTheme();
        return window.monaco;
      } catch (err) {
        loadPromise = null;
        throw err;
      }
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

  function zoomFactor() {
    if (window.TabbyUI && typeof TabbyUI.getZoom === "function") {
      return TabbyUI.getZoom() / 100;
    }
    const raw = parseFloat(
      getComputedStyle(document.documentElement).getPropertyValue("--ui-zoom")
    );
    return Number.isFinite(raw) && raw > 0 ? raw : 1;
  }

  function editorFontSize() {
    return Math.max(8, Math.round(13 * zoomFactor()));
  }

  function editorPadding() {
    return { top: Math.max(4, Math.round(8 * zoomFactor())) };
  }

  function applyEditorZoom() {
    const opts = { fontSize: editorFontSize(), padding: editorPadding() };
    if (editor) editor.updateOptions(opts);
    if (diffEditor) {
      diffEditor.updateOptions(opts);
      const modified = diffEditor.getModifiedEditor && diffEditor.getModifiedEditor();
      const original = diffEditor.getOriginalEditor && diffEditor.getOriginalEditor();
      if (modified) modified.updateOptions(opts);
      if (original) original.updateOptions(opts);
    }
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
    scrollbar: {
      useShadows: false,
      verticalScrollbarSize: 10,
      horizontalScrollbarSize: 10,
    },
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

  window.addEventListener("tabby-zoom-change", applyEditorZoom);

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
    const gen = ++mountGen;
    const monaco = await ensure();
    if (gen !== mountGen) return;
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
      fontSize: editorFontSize(),
      padding: editorPadding(),
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
    const gen = ++mountGen;
    const monaco = await ensure();
    if (gen !== mountGen) return;
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
      fontSize: editorFontSize(),
      padding: editorPadding(),
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

  document.addEventListener("tabby-theme-change", applyMonacoTheme);

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
