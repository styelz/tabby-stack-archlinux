(() => {
  const MARKER = "/v1/ui";

  function uiBase() {
    const path = window.location.pathname || "";
    const idx = path.indexOf(MARKER);
    if (idx >= 0) return path.slice(0, idx + MARKER.length);
    return MARKER;
  }

  function uiPath(suffix) {
    const base = uiBase();
    const part = String(suffix || "").replace(/^\/+/, "");
    return part ? `${base}/${part}` : `${base}/`;
  }

  /** Map server paths (/v1/ui/...) onto the browser's proxy prefix. */
  function resolveUiUrl(url) {
    const value = String(url || "");
    if (value.startsWith(MARKER)) return uiBase() + value.slice(MARKER.length);
    if (value.startsWith("/ui/")) return uiBase() + value.slice(3);
    if (value === "/ui") return `${uiBase()}/`;
    return value;
  }

  function apiUrl(path) {
    const value = String(path || "");
    if (value.startsWith("http")) return value;
    if (value.startsWith(uiBase() + "/") || value === uiBase()) return value;
    if (value.startsWith(MARKER + "/")) return uiBase() + value.slice(MARKER.length);
    if (value.startsWith("/ui/")) return uiBase() + value.slice(3);
    if (value.startsWith("/")) return uiPath(value.slice(1));
    return uiPath(value);
  }

  function compactText(value, max = 180) {
    return String(value || "").replace(/\s+/g, " ").trim().slice(0, max);
  }

  function looksLikeHtml(value) {
    return /<\s*(?:html|body|head|h[1-6]|!doctype)\b/i.test(String(value || ""));
  }

  /** Proxy 502/503/504 pages are HTML; never dump that markup into the UI. */
  function httpErrorMessage(response, data) {
    const status = response && response.status;
    const unavailable = status === 502 || status === 503 || status === 504;
    if (unavailable) {
      return `API unavailable (${status}) — service may be restarting`;
    }
    if (data && typeof data === "object") {
      const detail = data.detail;
      if (Array.isArray(detail) && detail.length) {
        const first = detail[0];
        const msg = (first && (first.msg || first.message)) || first;
        if (msg) return compactText(msg);
      } else if (typeof detail === "string" && detail.trim()) {
        return compactText(detail);
      }
      if (typeof data.message === "string" && data.message.trim()) {
        return compactText(data.message);
      }
    }
    if (typeof data === "string" && data.trim()) {
      if (looksLikeHtml(data)) {
        const heading = data.match(/<\s*h[1-6][^>]*>([\s\S]*?)<\s*\/\s*h[1-6]>/i);
        const stripped = (heading ? heading[1] : data).replace(/<[^>]+>/g, " ");
        return compactText(stripped) || `Request failed (${status})`;
      }
      return compactText(data);
    }
    return status ? `Request failed (${status})` : "Request failed";
  }

  async function api(path, options = {}) {
    const headers = Object.assign({ Accept: "application/json" }, options.headers || {});
    if (options.body && typeof options.body !== "string" && !(options.body instanceof FormData)) {
      headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(options.body);
    }
    const url = apiUrl(path);
    let response;
    try {
      response = await fetch(url, Object.assign({ credentials: "same-origin" }, options, { headers }));
    } catch (err) {
      if (err && err.name === "AbortError") throw err;
      throw new Error("API unreachable — service may be restarting");
    }
    if (response.status === 401 && !String(url).includes("/auth/login")) {
      window.location.href = uiPath("login");
      throw new Error("Not authenticated");
    }
    const type = response.headers.get("content-type") || "";
    const data = type.includes("application/json") ? await response.json() : await response.text();
    if (!response.ok) {
      throw new Error(httpErrorMessage(response, data));
    }
    return data;
  }

  function $(sel, root = document) {
    return root.querySelector(sel);
  }

  function $all(sel, root = document) {
    return Array.from(root.querySelectorAll(sel));
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function formatBytes(n) {
    if (!n) return "0 B";
    const units = ["B", "KB", "MB", "GB"];
    let i = 0;
    let v = n;
    while (v >= 1024 && i < units.length - 1) {
      v /= 1024;
      i += 1;
    }
    return `${v.toFixed(v >= 10 || i === 0 ? 0 : 1)} ${units[i]}`;
  }

  function formatDuration(seconds) {
    const s = Math.max(0, Number(seconds) || 0);
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = s % 60;
    if (h) return `${h}h ${m}m`;
    if (m) return `${m}m ${sec}s`;
    return `${sec}s`;
  }

  function formatAssistantContent(text) {
    let out = String(text || "");
    out = out.replace(/^[ \t]*tabby-image-job:\s*[0-9a-fA-F-]{4,}[ \t]*\n?/gim, "");
    out = out.replace(/^\d+\s+image\(s\) from this turn:\s*$/gim, "");
    out = out.replace(/^\d+\.\s+generated-\d{8}-\d{6}-\d+\.png\s*$/gim, "");
    out = out.replace(/^These URLs are on this API host\.[^\n]*$/gim, "");
    out = out.replace(/^Another picture:\s*[^\n]+$/gim, "");
    out = out.replace(/^This picture:\s*/gim, "");
    out = out.replace(/\n{3,}/g, "\n\n");
    return out.trim();
  }

  function isImageHref(href) {
    return (
      /\.(png|jpg|jpeg|webp)(\?|$)/i.test(href) ||
      href.includes("/gallery/file/") ||
      href.includes("/v1/images/")
    );
  }

  function markdownImage(href, alt) {
    const resolved = resolveUiUrl(href);
    const safeHref = escapeHtml(resolved);
    const safeAlt = escapeHtml(alt || "");
    return `<a href="${safeHref}" target="_blank" rel="noreferrer"><img src="${safeHref}" alt="${safeAlt}"></a>`;
  }

  function renderMarkdown(text) {
    const raw = String(text || "");
    const used = new Set();
    const placeholders = [];
    const withMd = raw.replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g, (_, alt, url) => {
      const href = String(url || "").trim();
      used.add(href);
      used.add(resolveUiUrl(href));
      const token = `@@IMG${placeholders.length}@@`;
      placeholders.push(markdownImage(href, alt));
      return token;
    });
    let html = escapeHtml(withMd)
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/\n/g, "<br>");
    html = html.replace(
      /(https?:\/\/[^\s<]+|\/v1\/ui\/gallery\/file\/[^\s<]+|\/ui\/gallery\/file\/[^\s<]+|\/v1\/images\/generated-[^\s<]+)/g,
      (url) => {
        const href = resolveUiUrl(url);
        if (used.has(url) || used.has(href)) return "";
        if (isImageHref(href)) {
          used.add(href);
          used.add(url);
          return markdownImage(href, "");
        }
        return `<a href="${escapeHtml(href)}" target="_blank" rel="noreferrer">${escapeHtml(url)}</a>`;
      }
    );
    html = html.replace(/@@IMG(\d+)@@/g, (_, i) => placeholders[Number(i)] || "");
    return html.replace(/(<br>\s*){3,}/g, "<br><br>");
  }

  window.TabbyUI = {
    base: uiBase,
    path: uiPath,
    resolveUiUrl,
    api,
    $,
    $all,
    escapeHtml,
    formatBytes,
    formatDuration,
    formatAssistantContent,
    renderMarkdown,
    paintGpuChip(data) {
      const chip = document.getElementById("gpu-chip");
      if (!chip) return;
      if (!data) {
        this.paintApiDown();
        return;
      }
      const mode = data.gpu_mode || "gpu";
      const label = data.profile || data.tabby_model || "idle";
      chip.textContent = `${String(mode).toUpperCase()} · ${label}`;
      chip.className = "chip" + (mode === "llm" ? " ok" : " warn");
      chip.title = "";
    },
    paintApiDown(err) {
      const chip = document.getElementById("gpu-chip");
      if (!chip) return;
      const raw = (err && err.message) || "";
      let detail = "reconnecting";
      const status = raw.match(/\((\d{3})\)/);
      if (status) detail = status[1];
      else if (/unreachable/i.test(raw)) detail = "unreachable";
      else if (/restart/i.test(raw)) detail = "restarting";
      chip.textContent = `DOWN · ${detail}`;
      chip.className = "chip bad";
      chip.title = raw || "API unavailable";
    },
  };
})();
