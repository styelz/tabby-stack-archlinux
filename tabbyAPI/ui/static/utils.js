async function api(path, options = {}) {
  const headers = Object.assign({ Accept: "application/json" }, options.headers || {});
  if (options.body && typeof options.body !== "string" && !(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(options.body);
  }
  const response = await fetch(path, Object.assign({ credentials: "same-origin" }, options, { headers }));
  if (response.status === 401 && !path.startsWith("/ui/auth/login")) {
    window.location.href = "/ui/login";
    throw new Error("Not authenticated");
  }
  const type = response.headers.get("content-type") || "";
  const data = type.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    const message = (data && data.detail) || (typeof data === "string" ? data : "Request failed");
    throw new Error(Array.isArray(message) ? message[0]?.msg || "Request failed" : message);
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

function renderMarkdown(text) {
  const raw = String(text || "");
  const escaped = escapeHtml(raw);
  const withCode = escaped.replace(/`([^`]+)`/g, "<code>$1</code>");
  const withBold = withCode.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  const withBreaks = withBold.replace(/\n/g, "<br>");
  return withBreaks.replace(
    /(https?:\/\/[^\s<]+|\/ui\/gallery\/file\/[^\s<]+|\/v1\/images\/generated-[^\s<]+)/g,
    (url) => {
      if (/\.(png|jpg|jpeg|webp)(\?|$)/i.test(url) || url.includes("/gallery/file/") || url.includes("/v1/images/")) {
        return `<a href="${url}" target="_blank" rel="noreferrer"><img src="${url}" alt=""></a>`;
      }
      return `<a href="${url}" target="_blank" rel="noreferrer">${url}</a>`;
    }
  );
}

window.TabbyUI = {
  api,
  $,
  $all,
  escapeHtml,
  escapeHtml: escapeHtml,
  formatBytes,
  formatBytes: formatBytes,
  formatDuration,
  formatDuration: formatDuration,
  renderMarkdown,
  renderMarkdown: renderMarkdown,
};
