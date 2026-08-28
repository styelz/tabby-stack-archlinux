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
const NAV_STAR_SVG =
  '<svg viewBox="0 0 16 16" aria-hidden="true" focusable="false"><path d="m8 1.8 1.85 3.75 4.15.6-3 2.92.7 4.13L8 11.3l-3.7 1.9.7-4.13-3-2.92 4.15-.6z" /></svg>';
const NAV_RENAME_SVG =
  '<svg viewBox="0 0 16 16" aria-hidden="true" focusable="false"><path d="M3.5 12.5 12 4l1.5 1.5-8.5 8.5H3.5z" /></svg>';
const NAV_CLOSE_SVG =
  '<svg viewBox="0 0 16 16" aria-hidden="true" focusable="false"><path d="M4 4l8 8M12 4l-8 8" /></svg>';
const TREE_FOLDER_SVG =
  '<svg viewBox="0 0 16 16" aria-hidden="true" focusable="false"><path d="M2 4.5A1.5 1.5 0 0 1 3.5 3H7l1.2 1.5H12.5A1.5 1.5 0 0 1 14 6v5.5A1.5 1.5 0 0 1 12.5 13h-9A1.5 1.5 0 0 1 2 11.5z" /></svg>';
const TREE_FILE_SVG =
  '<svg viewBox="0 0 16 16" aria-hidden="true" focusable="false"><path d="M4 2h5.2L12 4.8V14H4z" /></svg>';
const FILES_NEW_SVG =
  '<svg viewBox="0 0 16 16" aria-hidden="true" focusable="false"><path d="M8 3.5v9M3.5 8h9" /></svg>';
const FILES_UPLOAD_SVG =
  '<svg viewBox="0 0 16 16" aria-hidden="true" focusable="false"><path d="M8 11.5V3.5M4.5 7 8 3.5 11.5 7"/><path d="M3 13h10" /></svg>';
const FILES_PREVIEW_SVG =
  '<svg viewBox="0 0 16 16" aria-hidden="true" focusable="false"><path d="M1.5 8s2.4-4.2 6.5-4.2S14.5 8 14.5 8s-2.4 4.2-6.5 4.2S1.5 8 1.5 8z"/><circle cx="8" cy="8" r="1.8" /></svg>';
const FILES_TERM_SVG =
  '<svg viewBox="0 0 16 16" aria-hidden="true" focusable="false"><path d="M2.5 3.5h11v9h-11z"/><path d="M5 6.5 7.2 8 5 9.5"/><path d="M8.2 9.5H11" /></svg>';
const MIC_SVG =
  '<svg viewBox="0 0 16 16" aria-hidden="true" focusable="false"><rect x="5.5" y="1.75" width="5" height="7.5" rx="2.5"/><path d="M3.5 8.25a4.5 4.5 0 0 0 9 0"/><path d="M8 12.75v1.75M5.5 14.5h5"/></svg>';

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
        <button type="button" class="chat-resize" id="chat-sidebar-resize" aria-label="Resize chat list" title="Drag to resize"></button>
      </aside>
      <div class="chat-wrap">
        <div class="toolbar chat-toolbar">
          <button class="rail-toggle" type="button" id="chat-sidebar-toggle" aria-label="Hide sidebar" title="Hide sidebar">${CHEVRON_SVG}</button>
          <span class="chat-title" id="chat-title">New chat</span>
          <span class="spacer"></span>
          <div class="chat-mode" id="chat-mode" role="group" aria-label="Chat mode">
            <button type="button" class="chat-mode-btn is-active" data-mode="chat">Chat</button>
            <button type="button" class="chat-mode-btn" data-mode="code">Code</button>
          </div>
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
              <button type="button" data-more="thread" hidden>New chat in this workspace</button>
              <button type="button" data-more="delete">Delete this chat</button>
            </div>
          </div>
          <button class="rail-toggle" type="button" id="chat-files-toggle" hidden aria-expanded="true" aria-controls="chat-files" aria-label="Hide files" title="Hide files">${CHEVRON_SVG}</button>
        </div>
          <div class="chat-view">
          <div class="chat-stage" id="chat-stage">
          <div class="chat-tabs" id="chat-tabs" role="tablist" aria-label="Open files" hidden></div>
          <div class="chat-stage-main" id="chat-stage-main">
          <div class="chat-log-wrap" id="chat-log-wrap">
            <div class="chat-find" id="chat-find" hidden>
              <input id="chat-find-input" type="search" placeholder="Find in chat" autocomplete="off" />
              <span class="chat-find-count" id="chat-find-count"></span>
              <button type="button" class="btn ghost chat-icon" id="chat-find-prev" aria-label="Previous match" title="Previous match">↑</button>
              <button type="button" class="btn ghost chat-icon" id="chat-find-next" aria-label="Next match" title="Next match">↓</button>
              <button type="button" class="btn ghost chat-icon" id="chat-find-close" aria-label="Close find" title="Close find">×</button>
            </div>
            <div class="chat-empty" id="chat-empty" hidden>
              <h2 id="chat-empty-title">Console chat</h2>
              <p id="chat-empty-copy">Talk to the loaded model. Slash commands switch models and start pictures. Attach files for this chat only. Pasted images stay on this host.</p>
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
          <div class="chat-editor-col" id="chat-editor-col" hidden>
            <div class="chat-find" id="editor-find" hidden>
              <input id="editor-find-input" type="search" placeholder="Find in file" autocomplete="off" />
              <span class="chat-find-count" id="editor-find-count"></span>
              <button type="button" class="btn ghost chat-icon" id="editor-find-prev" aria-label="Previous match" title="Previous match">↑</button>
              <button type="button" class="btn ghost chat-icon" id="editor-find-next" aria-label="Next match" title="Next match">↓</button>
              <button type="button" class="btn ghost chat-icon" id="editor-find-close" aria-label="Close find" title="Close find">×</button>
            </div>
            <section class="chat-editor" id="chat-editor" aria-label="File editor"></section>
          </div>
          <section class="chat-preview" id="chat-preview" hidden>
            <button type="button" class="chat-resize" id="chat-preview-resize" aria-label="Resize preview" title="Drag to resize"></button>
            <div class="chat-preview-chrome">
              <div class="chat-preview-tabs-row">
                <div class="chat-preview-tabs" id="chat-preview-tabs" role="tablist" aria-label="Browser tabs"></div>
                <button type="button" class="btn ghost chat-icon" id="chat-preview-new" aria-label="New tab" title="New tab">+</button>
                <span class="spacer"></span>
                <button type="button" class="btn ghost" id="chat-preview-tab" title="Open preview as a tab">Tab</button>
                <button type="button" class="btn ghost chat-icon" id="chat-preview-close" aria-label="Close preview" title="Close preview">×</button>
              </div>
              <div class="chat-preview-head">
                <button type="button" class="btn ghost chat-icon" id="chat-preview-back" aria-label="Back" title="Back">←</button>
                <button type="button" class="btn ghost chat-icon" id="chat-preview-forward" aria-label="Forward" title="Forward">→</button>
                <button type="button" class="btn ghost chat-icon" id="chat-preview-reload" aria-label="Reload" title="Reload">↻</button>
                <input id="chat-preview-url" class="chat-preview-url" type="text" spellcheck="false" autocomplete="off" aria-label="Address" placeholder="Page path or URL" />
              </div>
            </div>
            <div class="chat-preview-frames" id="chat-preview-frames"></div>
          </section>
          </div>
          </div>
          <section class="chat-term" id="chat-term" hidden>
            <button type="button" class="chat-resize chat-resize-y" id="chat-term-resize" aria-label="Resize terminal" title="Drag to resize"></button>
            <div class="chat-term-head">
              <strong>Terminal</strong>
              <span class="muted" id="chat-term-note"></span>
              <span class="spacer"></span>
              <button type="button" class="btn ghost chat-icon" id="chat-term-close" aria-label="Close terminal" title="Close terminal">×</button>
            </div>
            <div class="chat-term-xterm" id="chat-term-xterm"></div>
          </section>
        </div>
        <div class="chat-compose">
          <button type="button" class="chat-resize chat-resize-y" id="chat-compose-resize" aria-label="Resize input" title="Drag to resize"></button>
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
          <div class="chat-loading" id="chat-flight-away" hidden>
            <span class="chat-loading-mark">Busy</span>
            <span class="chat-loading-text" id="chat-flight-away-text">A reply is still running in another chat.</span>
            <button class="btn" type="button" id="chat-flight-back">Switch back</button>
          </div>
          <div class="chat-loading" id="chat-loading" hidden>
            <span class="chat-loading-mark">Loading</span>
            <span class="chat-loading-text" id="chat-loading-text">The model is loading. Chat is paused until it is ready.</span>
            <span class="chat-loading-time" id="chat-loading-time"></span>
          </div>
            <div class="chat-loading" id="chat-waiting" hidden>
            <span class="chat-loading-mark" id="chat-waiting-mark">Queued</span>
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
            <input id="chat-context" type="file" multiple hidden />
            <input id="chat-upload" type="file" multiple accept=".html,.htm,.css,.js,.mjs,.json,.jsx,.ts,.tsx,.md,.txt,.svg,.xml,.yml,.yaml,.csv,.py,.sh,.php,.toml,.ini,.conf,.png,.jpg,.jpeg,.webp,.gif,image/png,image/jpeg,image/webp,image/gif,text/plain,text/html,text/css,text/javascript,application/json" hidden />
            <input id="chat-upload-dir" type="file" multiple webkitdirectory directory hidden />
            <div class="chat-form-actions">
              <div class="chat-attach-wrap">
                <button class="btn ghost chat-icon" type="button" id="chat-attach-btn" aria-haspopup="true" aria-expanded="false" aria-label="Attach image or files" title="Attach image or files">📎</button>
                <div class="chat-attach-menu" id="chat-attach-menu" hidden></div>
              </div>
              <button class="btn ghost chat-icon" type="button" id="chat-mic" hidden aria-pressed="false" aria-label="Voice input" title="Voice input">${MIC_SVG}</button>
              <span class="chat-mic-status" id="chat-mic-status" hidden>Listening</span>
              <span id="chat-count"></span>
              <span class="chat-keys"><kbd>Enter</kbd> send · <kbd>Shift</kbd>+<kbd>Enter</kbd> line · <kbd>Esc</kbd> close</span>
              <div class="chat-agent" id="chat-agent" hidden>
                <button type="button" class="btn ghost chat-agent-btn" id="chat-agent-btn" aria-haspopup="menu" aria-expanded="false" aria-label="Code prompt mode" title="Agent / Ask / Plan (Shift+Tab)">Agent</button>
                <div class="chat-agent-menu" id="chat-agent-menu" hidden role="menu">
                  <button type="button" role="menuitem" data-agent="agent">Agent<span class="chat-agent-hint">Edit files</span></button>
                  <button type="button" role="menuitem" data-agent="ask">Ask<span class="chat-agent-hint">Read-only</span></button>
                  <button type="button" role="menuitem" data-agent="plan">Plan<span class="chat-agent-hint">Design, then Build</span></button>
                </div>
              </div>
              <button class="btn primary chat-send" type="submit" id="chat-send">Send</button>
            </div>
          </form>
        </div>
      </div>
      <aside class="chat-files" id="chat-files" hidden>
        <button type="button" class="chat-resize" id="chat-files-resize" aria-label="Resize files pane" title="Drag to resize"></button>
        <div class="chat-files-head">
          <span>Files</span>
          <span class="chat-files-count" id="chat-files-count"></span>
          <span class="spacer"></span>
          <div class="chat-more chat-files-more">
            <button class="btn ghost chat-icon" type="button" id="chat-files-more" aria-haspopup="true" aria-expanded="false" aria-label="More file actions" title="More">⋯</button>
            <div class="chat-more-menu" id="chat-files-more-menu" hidden>
              <button type="button" data-files-more="refresh">Refresh</button>
              <button type="button" data-files-more="zip" id="chat-files-zip">Download zip</button>
              <button type="button" data-files-more="clear" id="chat-files-clear">Clear files</button>
            </div>
          </div>
          <button class="btn ghost chat-icon chat-files-close" type="button" id="chat-files-close" aria-label="Hide files" title="Hide files">×</button>
          <div class="chat-files-actions">
            <button class="btn ghost chat-icon" type="button" id="chat-files-new" aria-label="New">${FILES_NEW_SVG}</button>
            <div class="chat-more chat-files-upload-wrap">
              <button class="btn ghost chat-icon" type="button" id="chat-files-upload" aria-label="Upload" aria-haspopup="true" aria-expanded="false">${FILES_UPLOAD_SVG}</button>
              <div class="chat-more-menu" id="chat-files-upload-menu" hidden>
                <button type="button" data-upload="files">Files</button>
                <button type="button" data-upload="folder">Folder</button>
                <button type="button" data-upload="gallery">From gallery</button>
              </div>
            </div>
            <button class="btn" type="button" id="chat-files-site">Open site</button>
            <button class="btn ghost chat-icon" type="button" id="chat-files-preview" aria-label="Preview">${FILES_PREVIEW_SVG}</button>
            <button class="btn ghost chat-icon" type="button" id="chat-files-term" aria-label="Terminal" aria-keyshortcuts="Control+\`" title="Terminal (Ctrl+\`)">${FILES_TERM_SVG}</button>
          </div>
        </div>
        <div class="chat-files-tree" id="chat-files-tree"></div>
        <div class="chat-files-history" id="chat-files-changes">
          <button type="button" class="chat-resize chat-resize-y" id="chat-files-changes-resize" aria-label="Resize changes pane" title="Drag to resize"></button>
          <button type="button" class="chat-files-history-head" id="chat-files-changes-toggle" aria-expanded="true">
            <span class="chat-files-twist" aria-hidden="true"></span>
            <span class="chat-files-history-title">Changes</span>
            <span class="chat-files-history-count" id="chat-files-changes-count"></span>
          </button>
          <div class="chat-files-history-list" id="chat-files-changes-list"></div>
        </div>
        <div class="chat-files-history" id="chat-files-history">
          <button type="button" class="chat-resize chat-resize-y" id="chat-files-history-resize" aria-label="Resize history pane" title="Drag to resize"></button>
          <button type="button" class="chat-files-history-head" id="chat-files-history-toggle" aria-expanded="true">
            <span class="chat-files-twist" aria-hidden="true"></span>
            <span class="chat-files-history-title">History</span>
            <span class="chat-files-history-count" id="chat-files-history-count"></span>
          </button>
          <div class="chat-files-history-list" id="chat-files-history-list"></div>
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
  const agentWrap = root.querySelector("#chat-agent");
  const agentBtn = root.querySelector("#chat-agent-btn");
  const agentMenu = root.querySelector("#chat-agent-menu");
  const queueBar = root.querySelector("#chat-queue");
  const queueTextEl = root.querySelector("#chat-queue-text");
  const steerBtn = root.querySelector("#chat-steer");
  const queueClearBtn = root.querySelector("#chat-queue-clear");
  const flightAwayBar = root.querySelector("#chat-flight-away");
  const flightAwayText = root.querySelector("#chat-flight-away-text");
  const flightBackBtn = root.querySelector("#chat-flight-back");
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
  const contextInput = root.querySelector("#chat-context");
  const uploadInput = root.querySelector("#chat-upload");
  const uploadDirInput = root.querySelector("#chat-upload-dir");
  const micBtn = root.querySelector("#chat-mic");
  const micStatus = root.querySelector("#chat-mic-status");
  let stopMic = () => false;
  const countEl = root.querySelector("#chat-count");
  const loadingBar = root.querySelector("#chat-loading");
  const loadingTextEl = root.querySelector("#chat-loading-text");
  const loadingTimeEl = root.querySelector("#chat-loading-time");
  const waitingBar = root.querySelector("#chat-waiting");
  const waitingMark = root.querySelector("#chat-waiting-mark");
  const waitingTextEl = root.querySelector("#chat-waiting-text");
  const waitingTimeEl = root.querySelector("#chat-waiting-time");
  const comfyHint = root.querySelector("#chat-comfy-hint");
  const switchLlmBtn = root.querySelector("#chat-switch-llm");
  const filesPane = root.querySelector("#chat-files");
  const filesTree = root.querySelector("#chat-files-tree");
  const filesHistoryList = root.querySelector("#chat-files-history-list");
  const filesChangesList = root.querySelector("#chat-files-changes-list");
  const filesChangesToggle = root.querySelector("#chat-files-changes-toggle");
  const filesChangesPane = root.querySelector("#chat-files-changes");
  const tabsBar = root.querySelector("#chat-tabs");
  const logWrap = root.querySelector("#chat-log-wrap");
  const editorPane = root.querySelector("#chat-editor");
  const editorCol = root.querySelector("#chat-editor-col");
  const previewPane = root.querySelector("#chat-preview");
  const previewFrames = root.querySelector("#chat-preview-frames");
  const previewTabsEl = root.querySelector("#chat-preview-tabs");
  const previewUrlInput = root.querySelector("#chat-preview-url");
  const previewNewBtn = root.querySelector("#chat-preview-new");
  const previewBackBtn = root.querySelector("#chat-preview-back");
  const previewForwardBtn = root.querySelector("#chat-preview-forward");
  const previewReloadBtn = root.querySelector("#chat-preview-reload");
  const previewTabBtn = root.querySelector("#chat-preview-tab");
  const previewCloseBtn = root.querySelector("#chat-preview-close");
  const PREVIEW_SANDBOX = "allow-scripts allow-forms allow-modals allow-popups allow-top-navigation-by-user-activation";
  const termPane = root.querySelector("#chat-term");
  const termHost = root.querySelector("#chat-term-xterm");
  const termNote = root.querySelector("#chat-term-note");
  const termCloseBtn = root.querySelector("#chat-term-close");
  const filesPreviewBtn = root.querySelector("#chat-files-preview");
  const filesTermBtn = root.querySelector("#chat-files-term");
  const editorFindBar = root.querySelector("#editor-find");
  const editorFindInput = root.querySelector("#editor-find-input");
  const editorFindCountEl = root.querySelector("#editor-find-count");
  const editorFindPrevBtn = root.querySelector("#editor-find-prev");
  const editorFindNextBtn = root.querySelector("#editor-find-next");
  const editorFindCloseBtn = root.querySelector("#editor-find-close");
  const filesZipBtn = root.querySelector("#chat-files-zip");
  const filesClearBtn = root.querySelector("#chat-files-clear");
  const filesNewBtn = root.querySelector("#chat-files-new");
  const filesUploadBtn = root.querySelector("#chat-files-upload");
  const filesUploadMenu = root.querySelector("#chat-files-upload-menu");
  const filesMoreBtn = root.querySelector("#chat-files-more");
  const filesMoreMenu = root.querySelector("#chat-files-more-menu");
  const filesHistoryPane = root.querySelector("#chat-files-history");
  const filesHistoryToggle = root.querySelector("#chat-files-history-toggle");
  const filesChangesCountEl = root.querySelector("#chat-files-changes-count");
  const filesHistoryCountEl = root.querySelector("#chat-files-history-count");
  const filesCountEl = root.querySelector("#chat-files-count");
  const filesSiteBtn = root.querySelector("#chat-files-site");
  const filesToggleBtn = root.querySelector("#chat-files-toggle");
  const filesCloseBtn = root.querySelector("#chat-files-close");
  const findBar = root.querySelector("#chat-find");
  const findInput = root.querySelector("#chat-find-input");
  const findCountEl = root.querySelector("#chat-find-count");
  const findPrevBtn = root.querySelector("#chat-find-prev");
  const findNextBtn = root.querySelector("#chat-find-next");
  const findCloseBtn = root.querySelector("#chat-find-close");
  const DEFAULT_PLACEHOLDER = input.getAttribute("placeholder") || "";
  let filesListing = [];
  let filesSelected = "";
  let filesFocusDir = "";
  let filesOpenFolders = new Set();
  let filesSeenPaths = new Set();
  let filesRevealed = "";
  let filesTreeReady = false;
  let filesEntry = "";
  let filesHistory = [];
  let filesHistoryPath = "";
  let filesHistoryReq = 0;
  let filesChanged = [];
  const changesByChat = Object.create(null);
  const listingByChat = Object.create(null);
  // Code mode opens files as tabs beside Chat in the main column. Each tab keeps
  // its own buffer so switching away does not throw away unsaved edits.
  let openTabs = [];
  let activeTab = "";
  let tabsChat = "";
  let tabsByChat = Object.create(null);
  let logScroll = 0;
  let findQuery = "";
  let findHits = [];
  let findIndex = 0;
  let editorFindQuery = "";
  let editorFindHits = [];
  let editorFindIndex = 0;
  let previewOpen = false;
  let previewUrl = "";
  let previewRoot = "";
  let browserTabs = [];
  let activeBrowserTab = "";
  let browserTabSeq = 0;
  const PREVIEW_TAB = "__preview__";
  let termOpen = false;
  let termWanted = false;
  let termGen = 0;
  let termSocket = null;
  let termTerm = null;
  let termFit = null;
  let draftsTimer = 0;
  let draftsChat = "";
  const TREE_DRAG = "application/x-tabby-path";
  const menu = root.querySelector("#slash-menu");
  const historyMenu = root.querySelector("#history-menu");
  const titleEl = root.querySelector("#chat-title");
  const SYSTEM = { role: "system", content: "Console chat. No file tools." };
  const CODE_PLACEHOLDER = "Describe the page or files to create, or attach files from the Files pane.";
  const ASK_PLACEHOLDER = "Ask about the project. Files will not be changed.";
  const PLAN_PLACEHOLDER = "Describe what to plan. Review it, then click Build to implement.";
  const BUILD_PROMPT = "Implement the approved plan above. Do not wait for more confirmation.";
  const AGENT_KEY = "tabby-ui-code-agent";
  const AGENT_LABELS = { agent: "Agent", ask: "Ask", plan: "Plan" };
  const AGENT_ORDER = ["agent", "ask", "plan"];

  function normalizeAgent(value) {
    const kind = String(value || "").trim().toLowerCase();
    return AGENT_LABELS[kind] ? kind : "agent";
  }

  function isBuildPromptText(text) {
    return String(text || "").trim().startsWith(BUILD_PROMPT);
  }

  function looksLikeCodeProjectPrompt(text) {
    const lower = String(text || "").toLowerCase();
    return (
      /\bindex\.html\b/.test(lower)
      || /\bstyles\.css\b/.test(lower)
      || /\bapp\.js\b/.test(lower)
      || /\blanding page\b/.test(lower)
      || /\bone-pager\b/.test(lower)
    );
  }

  function readCodeAgent() {
    try {
      return normalizeAgent(localStorage.getItem(AGENT_KEY));
    } catch {
      return "agent";
    }
  }

  let codeAgent = readCodeAgent();

  function hideAgentMenu() {
    if (!agentMenu || !agentBtn) return;
    agentMenu.hidden = true;
    agentBtn.setAttribute("aria-expanded", "false");
  }

  function codePlaceholder() {
    if (codeAgent === "ask") return ASK_PLACEHOLDER;
    if (codeAgent === "plan") return PLAN_PLACEHOLDER;
    return CODE_PLACEHOLDER;
  }
  const TEXT_SUFFIXES = new Set([
    ".html", ".htm", ".css", ".js", ".mjs", ".json", ".jsx", ".ts", ".tsx",
    ".md", ".txt", ".svg", ".xml", ".yml", ".yaml", ".csv", ".py", ".sh",
    ".php", ".toml", ".ini", ".conf",
  ]);
  const IMAGE_SUFFIXES = new Set([".png", ".jpg", ".jpeg", ".webp", ".gif"]);
  const BINARY_SUFFIXES = new Set([
    ".zip", ".gz", ".tgz", ".tar", ".7z", ".rar", ".pdf", ".doc", ".docx",
    ".xls", ".xlsx", ".ppt", ".pptx", ".exe", ".dll", ".so", ".dylib", ".wasm",
    ".woff", ".woff2", ".ttf", ".otf", ".eot", ".mp3", ".mp4", ".webm", ".mov",
    ".avi", ".wav", ".ogg", ".flac", ".iso", ".bin", ".dat", ".db", ".sqlite",
    ".pkl", ".npy", ".pt", ".onnx", ".safetensors", ".gguf", ".whl", ".pyc",
  ]);
  const ATTACH_TEXT_LIMIT = 80_000;
  const MAX_ATTACH = 12;
  const STORAGE_KEY = "tabby-ui-chat-store";
  const SETTINGS_KEY = "tabby-ui-chat-settings";
  const SIDEBAR_KEY = "tabby-ui-chat-sidebar";
  const SIDEBAR_W_KEY = "tabby-ui-chat-sidebar-w";
  const FILES_KEY = "tabby-ui-chat-files";
  const FILES_W_KEY = "tabby-ui-chat-files-w";
  const PREVIEW_W_KEY = "tabby-ui-chat-preview-w";
  const TERM_H_KEY = "tabby-ui-chat-term-h";
  const COMPOSE_H_KEY = "tabby-ui-chat-compose-h";
  const FILES_FR_KEY = "tabby-ui-chat-files-fr";
  const SIDEBAR_W_MIN = 180;
  const SIDEBAR_W_MAX = 520;
  const SIDEBAR_W_DEFAULT = 268;
  const FILES_W_MIN = 160;
  const FILES_W_MAX = 560;
  const FILES_W_DEFAULT = 250;
  const PREVIEW_W_MIN = 22;
  const PREVIEW_W_MAX = 78;
  const PREVIEW_W_DEFAULT = 42;
  const TERM_H_MIN = 80;
  const TERM_H_DEFAULT = 220;
  const COMPOSE_H_MIN = 56;
  const COMPOSE_ROWS_MAX = 10;
  const FILES_SPLIT_MIN = 64;
  const CHAT_COL_MIN = 280;
  const HISTORY_KEY = "tabby-ui-chat-history";
  const CHANGES_KEY = "tabby-ui-chat-changes";
  const WS_OPEN_KEY = "tabby-ui-chat-ws-open";
  const LISTING_STORE_KEY = "tabby-ui-code-listings";
  const MAX_CHATS = 50;
  const narrowChat = window.matchMedia("(max-width: 900px)");
  // Below 900px the pane is a bottom sheet over the chat, so it starts closed
  // there no matter what the desktop preference says.
  let filesOpen = narrowChat.matches ? false : readFilesOpen();
  let historyOpen = readHistoryOpen();
  let changesOpen = readChangesOpen();

  function readFilesOpen() {
    try {
      return localStorage.getItem(FILES_KEY) !== "closed";
    } catch {
      return true;
    }
  }

  function readHistoryOpen() {
    try {
      return localStorage.getItem(HISTORY_KEY) !== "closed";
    } catch {
      return true;
    }
  }

  function readChangesOpen() {
    try {
      return localStorage.getItem(CHANGES_KEY) !== "closed";
    } catch {
      return true;
    }
  }

  function newId() {
    if (globalThis.crypto && typeof crypto.randomUUID === "function") return crypto.randomUUID();
    return `c-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }

  function emptyChat(mode, parentId) {
    const chat = {
      id: newId(),
      title: mode === "code" && !parentId ? "New workspace" : "New chat",
      updatedAt: Date.now(),
      pinned: false,
      titleLocked: false,
      mode: mode === "code" ? "code" : "chat",
      parentId: "",
      messages: [{ ...SYSTEM }],
    };
    if (mode === "code") {
      const parent = String(parentId || "").trim();
      if (parent && parent !== chat.id) chat.parentId = parent;
    }
    return chat;
  }

  function chatMode(chat) {
    return chat && chat.mode === "code" ? "code" : "chat";
  }

  function chatParentId(chat) {
    if (!chat || chatMode(chat) !== "code") return "";
    const parent = String(chat.parentId || "").trim();
    if (!parent || parent === chat.id) return "";
    return parent;
  }

  function workspaceId(chat) {
    if (!chat) return "";
    if (chatMode(chat) !== "code") return chat.id;
    return chatParentId(chat) || chat.id;
  }

  function activeWorkspaceId() {
    return workspaceId(activeChat());
  }

  function chatsShareWorkspace(chatId) {
    const other = store.chats.find((item) => item.id === chatId);
    if (!other) return store.activeId === chatId;
    return workspaceId(other) === activeWorkspaceId();
  }

  function isWorkspaceRoot(chat) {
    return chatMode(chat) === "code" && !chatParentId(chat);
  }

  function nestedChats(rootId) {
    return store.chats.filter((item) => chatParentId(item) === rootId);
  }

  function expandWorkspace(rootId) {
    if (!rootId) return;
    wsOpen[rootId] = true;
    try {
      localStorage.setItem(WS_OPEN_KEY, JSON.stringify(wsOpen));
    } catch {
      /* ignore */
    }
  }

  function addCodeWorkspace() {
    const root = emptyChat("code");
    const chat = emptyChat("code", root.id);
    store.chats.unshift(root);
    store.chats.unshift(chat);
    expandWorkspace(root.id);
    return chat;
  }

  function newestModeChat(mode, pred) {
    return store.chats
      .filter((item) => chatMode(item) === mode && pred(item))
      .sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0))[0] || null;
  }

  function fallbackCodeChat(preferParentId) {
    const parentId = String(preferParentId || "").trim();
    if (parentId) {
      const sibling = newestModeChat("code", (item) => chatParentId(item) === parentId);
      if (sibling) return sibling;
    }
    const other = newestModeChat("code", (item) => Boolean(chatParentId(item)));
    if (other) return other;
    const parent = parentId
      && store.chats.find((item) => item.id === parentId && isWorkspaceRoot(item));
    const root = parent || newestModeChat("code", isWorkspaceRoot);
    if (root) {
      const chat = emptyChat("code", root.id);
      store.chats.unshift(chat);
      expandWorkspace(root.id);
      return chat;
    }
    return addCodeWorkspace();
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

  function preferredCodeChat(chat) {
    if (!chat || !isWorkspaceRoot(chat)) return chat;
    const kids = nestedChats(chat.id)
      .filter((item) => hasUserTurn(item) || item.pinned)
      .sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0));
    return kids[0] || chat;
  }

  function chatForMode(mode) {
    const want = mode === "code" ? "code" : "chat";
    const remembered = store.lastByMode && store.lastByMode[want];
    const hit = remembered
      && store.chats.find((item) => item.id === remembered && chatMode(item) === want);
    if (hit) {
      const picked = want === "code" ? preferredCodeChat(hit) : hit;
      if (want === "code" && isWorkspaceRoot(picked)) return picked;
      if (hasUserTurn(picked) || picked.pinned || picked.id === store.activeId) return picked;
    }
    const fallback = store.chats
      .filter((item) => (
        chatMode(item) === want
        && (
          hasUserTurn(item)
          || item.pinned
          || (want === "code" && isWorkspaceRoot(item))
        )
      ))
      .sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0))[0] || null;
    return want === "code" ? preferredCodeChat(fallback) : fallback;
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
        const agent = normalizeAgent(item.agent);
        if (agent === "ask" || agent === "plan") out.agent = agent;
        if (item.origin) out.origin = String(item.origin);
      }
      if (item.hidden) out.hidden = true;
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

  function cloneUsage(raw) {
    if (!raw || typeof raw !== "object") return null;
    const prompt = Number(raw.prompt_tokens);
    const completion = Number(raw.completion_tokens);
    const total = Number(raw.total_tokens);
    const used = Number.isFinite(total) && total > 0
      ? Math.round(total)
      : Math.max(0, Math.round((Number.isFinite(prompt) ? prompt : 0) + (Number.isFinite(completion) ? completion : 0)));
    if (used <= 0) return null;
    const out = {
      prompt_tokens: Math.max(0, Math.round(Number.isFinite(prompt) ? prompt : 0)),
      completion_tokens: Math.max(0, Math.round(Number.isFinite(completion) ? completion : 0)),
      total_tokens: used,
    };
    if (raw.estimated) out.estimated = true;
    return out;
  }

  function estimateTokensFromMessages(list) {
    let chars = 0;
    (Array.isArray(list) ? list : []).forEach((item) => {
      if (!item || item.role === "system") return;
      chars += String(item.content || "").length;
      if (item.reasoning) chars += String(item.reasoning).length;
      (item.attachedFiles || []).forEach((file) => {
        chars += String((file && file.path) || "").length;
        chars += String((file && file.text) || "").length;
      });
    });
    return Math.max(0, Math.round(chars / 4));
  }

  function contextWindowMax(data) {
    const model = (data && data.model) || {};
    const n = Number(model.max_seq_len);
    return Number.isFinite(n) && n > 0 ? n : 0;
  }

  function contextUsageHidden(data) {
    if (!data || data.down) return true;
    if (!contextWindowMax(data)) return true;
    const mode = String(data.gpu_mode || "").toLowerCase();
    if (mode === "comfy") return true;
    if (data.comfy_up && !data.tabby_model) return true;
    return !data.tabby_model;
  }

  function usageFromChat(chat, list) {
    const stored = cloneUsage(chat && chat.usage);
    if (stored) return stored;
    const used = estimateTokensFromMessages(list || (chat && chat.messages) || []);
    if (used <= 0) {
      return { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0, estimated: true };
    }
    return { prompt_tokens: used, completion_tokens: 0, total_tokens: used, estimated: true };
  }

  function paintActiveContext() {
    const data = TabbyUI.lastGpuStatus;
    if (contextUsageHidden(data)) {
      TabbyUI.paintContextUsage({ hide: true });
      return;
    }
    const chat = activeChat();
    const list = chat && chat.id === store.activeId ? messages : (chat && chat.messages);
    const usage = usageFromChat(chat, list);
    if (chat && usage.estimated && usage.total_tokens > 0 && !cloneUsage(chat.usage)) {
      chat.usage = usage;
    }
    TabbyUI.paintContextUsage({
      used: usage.total_tokens,
      max: contextWindowMax(data),
      estimated: Boolean(usage.estimated),
    });
  }

  function applyUsage(raw, chatId) {
    const usage = cloneUsage(raw);
    if (!usage) return;
    const id = chatId || store.activeId;
    const chat = store.chats.find((item) => item.id === id);
    if (chat) chat.usage = usage;
    if (id === store.activeId) paintActiveContext();
  }

  function defaultChatTitle(chat) {
    if (isWorkspaceRoot(chat)) return "New workspace";
    return "New chat";
  }

  function isPlaceholderTitle(title) {
    const raw = String(title || "").trim();
    return !raw || raw === "New chat" || raw === "New workspace";
  }

  function isHiddenUserTurn(item) {
    if (!item || item.role !== "user") return false;
    if (item.hidden) return true;
    return isBuildPromptText(item.content);
  }

  function titleFromMessages(list, chat) {
    const first = (list || []).find(
      (item) => item.role === "user" && !isHiddenUserTurn(item) && userTurnHasContent(item)
    );
    if (!first) return chat ? defaultChatTitle(chat) : "New chat";
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
    return (chat.messages || []).some(
      (item) => userTurnHasContent(item) && !isHiddenUserTurn(item)
    );
  }

  // Clone-on-reload leftovers share a title and timestamp. This is not
  // "one folder per title" — distinct projects with the same name stay.
  function collapseDuplicateWorkspaces(chats, activeId, lastByMode) {
    const last = lastByMode && typeof lastByMode === "object" ? lastByMode : emptyLastByMode(null);
    const kids = new Map();
    chats.forEach((chat) => {
      const parent = chatParentId(chat);
      if (!parent) return;
      if (!kids.has(parent)) kids.set(parent, []);
      kids.get(parent).push(chat);
    });
    const groups = new Map();
    const drop = new Set();
    const remap = new Map();
    chats.forEach((chat) => {
      if (!isWorkspaceRoot(chat)) return;
      const title = String(chat.title || "").trim();
      if (isPlaceholderTitle(title)) return;
      const key = `${title}\0${Number(chat.updatedAt) || 0}`;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(chat);
    });
    groups.forEach((roots) => {
      if (roots.length < 2) return;
      const withKids = roots.filter((root) => kids.has(root.id));
      const kept = (withKids[0] || roots[0]);
      roots.forEach((root) => {
        if (root.id === kept.id) return;
        drop.add(root.id);
        remap.set(root.id, kept.id);
      });
    });
    const protect = new Set([activeId, last.code].filter(Boolean));
    chats.forEach((chat) => {
      if (protect.has(chat.id)) {
        const parent = chatParentId(chat);
        if (parent) protect.add(parent);
      }
    });
    chats.forEach((chat) => {
      if (!isWorkspaceRoot(chat) || drop.has(chat.id)) return;
      const title = String(chat.title || "").trim();
      if (!isPlaceholderTitle(title)) return;
      if (protect.has(chat.id) || kids.has(chat.id)) return;
      drop.add(chat.id);
    });
    chats.forEach((chat) => {
      const parent = chatParentId(chat);
      if (parent && remap.has(parent)) chat.parentId = remap.get(parent);
    });
    const next = chats.filter((chat) => !drop.has(chat.id));
    let nextActive = String(activeId || "");
    if (drop.has(nextActive)) nextActive = remap.get(nextActive) || (next[0] && next[0].id) || "";
    const nextLast = { chat: String(last.chat || ""), code: String(last.code || "") };
    if (drop.has(nextLast.code)) nextLast.code = remap.get(nextLast.code) || "";
    return { chats: next, activeId: nextActive, lastByMode: nextLast };
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
      const row = {
        id,
        title: String(item.title || titleFromMessages(messages, item) || "New chat"),
        updatedAt: Number(item.updatedAt) || Date.now(),
        pinned: Boolean(item.pinned),
        titleLocked: Boolean(item.titleLocked),
        mode: item.mode === "code" ? "code" : "chat",
        parentId: "",
        messages,
      };
      const usage = cloneUsage(item.usage);
      if (usage) row.usage = usage;
      chats.push(row);
      if (row.mode === "code") {
        const parent = String(item.parentId || "").trim();
        if (parent && parent !== id) row.parentId = parent;
      }
    });
    const roots = new Set(
      chats.filter((chat) => isWorkspaceRoot(chat)).map((chat) => chat.id)
    );
    for (let i = chats.length - 1; i >= 0; i -= 1) {
      const parent = chatParentId(chats[i]);
      if (parent && !roots.has(parent)) chats.splice(i, 1);
    }
    const collapsed = collapseDuplicateWorkspaces(
      chats,
      String((raw && raw.activeId) || ""),
      emptyLastByMode(raw)
    );
    chats.length = 0;
    chats.push(...collapsed.chats);
    if (!chats.length) chats.push(emptyChat());
    let activeId = collapsed.activeId || String((raw && raw.activeId) || "");
    if (!chats.some((chat) => chat.id === activeId)) activeId = chats[0].id;
    const lastByMode = collapsed.lastByMode || emptyLastByMode(raw);
    if (!chats.some((chat) => chat.id === lastByMode.chat && chatMode(chat) === "chat")) {
      lastByMode.chat = "";
    }
    if (!chats.some((chat) => chat.id === lastByMode.code && chatMode(chat) === "code")) {
      lastByMode.code = "";
    }
    chats.filter((chat) => isWorkspaceRoot(chat) && hasUserTurn(chat)).forEach((root) => {
      const lifted = emptyChat("code", root.id);
      lifted.messages = cloneMessages(root.messages);
      lifted.title = titleFromMessages(lifted.messages, lifted);
      lifted.updatedAt = root.updatedAt || Date.now();
      root.messages = [{ ...SYSTEM }];
      chats.unshift(lifted);
      if (activeId === root.id) activeId = lifted.id;
      if (lastByMode.code === root.id) lastByMode.code = lifted.id;
    });
    const isEmptyThread = (chat) => (
      Boolean(chatParentId(chat))
      && !hasUserTurn(chat)
      && !chat.pinned
      && isPlaceholderTitle(chat.title)
    );
    const threadForRoot = (rootId) => {
      const kids = chats
        .filter((chat) => chatParentId(chat) === rootId)
        .sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0));
      return kids.find((item) => hasUserTurn(item) || item.pinned) || kids[0] || null;
    };
    const active = chats.find((chat) => chat.id === activeId);
    if (active && isWorkspaceRoot(active)) {
      let thread = threadForRoot(active.id);
      if (!thread) {
        thread = emptyChat("code", active.id);
        chats.unshift(thread);
      }
      activeId = thread.id;
    }
    if (lastByMode.code) {
      const remembered = chats.find((chat) => chat.id === lastByMode.code);
      if (remembered && isWorkspaceRoot(remembered)) {
        const thread = threadForRoot(remembered.id);
        lastByMode.code = thread ? thread.id : "";
      }
    }
    for (let i = chats.length - 1; i >= 0; i -= 1) {
      if (chats[i].id === activeId || chats[i].id === lastByMode.code) continue;
      if (!isEmptyThread(chats[i])) continue;
      const parent = chatParentId(chats[i]);
      const others = chats.some((item, idx) => idx !== i && chatParentId(item) === parent);
      if (!others) continue;
      chats.splice(i, 1);
    }
    chats.filter((chat) => isWorkspaceRoot(chat)).forEach((root) => {
      if (threadForRoot(root.id)) return;
      chats.unshift(emptyChat("code", root.id));
    });
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
  let sessionRestoring = true;
  let store = normalizeStore(null);
  let messages = cloneMessages(store.chats.find((chat) => chat.id === store.activeId).messages);
  let pendingEditIndex = -1;
  let pendingImage = null;
  let pendingFiles = [];
  let uploadWantsAttach = false;
  let uploadWantsContext = false;
  let uploadTargetDir = "";
  const SKIP_UPLOAD_DIRS = new Set([".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache"]);
  const SKIP_UPLOAD_FILES = new Set([".ds_store", "thumbs.db"]);
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
  function readStoredWidth(key, fallback, min, max) {
    try {
      const n = Number.parseInt(localStorage.getItem(key) || "", 10);
      if (Number.isFinite(n)) return Math.min(max, Math.max(min, n));
    } catch {
      /* ignore */
    }
    return fallback;
  }
  function readFilesFr() {
    try {
      const parts = String(localStorage.getItem(FILES_FR_KEY) || "").split(",");
      if (parts.length === 3) {
        const nums = parts.map((n) => Number.parseFloat(n));
        if (nums.every((n) => Number.isFinite(n) && n >= 0.15 && n <= 20)) {
          return { tree: nums[0], changes: nums[1], history: nums[2] };
        }
      }
    } catch {
      /* ignore */
    }
    return { tree: 2, changes: 1, history: 1 };
  }
  let sidebarW = readStoredWidth(SIDEBAR_W_KEY, SIDEBAR_W_DEFAULT, SIDEBAR_W_MIN, SIDEBAR_W_MAX);
  let filesW = readStoredWidth(FILES_W_KEY, FILES_W_DEFAULT, FILES_W_MIN, FILES_W_MAX);
  let previewW = readStoredWidth(PREVIEW_W_KEY, PREVIEW_W_DEFAULT, PREVIEW_W_MIN, PREVIEW_W_MAX);
  let termH = readStoredWidth(TERM_H_KEY, TERM_H_DEFAULT, TERM_H_MIN, 800);
  let composeH = readStoredWidth(COMPOSE_H_KEY, 0, 0, 800);
  let filesFr = readFilesFr();
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
      const labels = data.profile_labels || {};
      const extra = profiles.map((name) => ({
        slash: `/${name}`,
        send: `switch to ${name}`,
        hint: data.profile === name ? "Loaded now" : labels[name] || "Switch model",
      }));
      commands = [...STATIC_COMMANDS.slice(0, 3), ...extra, ...STATIC_COMMANDS.slice(3)];
      if (input.value.startsWith("/")) renderMenu();
      paintCompose();
    })
    .catch(() => {});

  function activeChat() {
    return store.chats.find((chat) => chat.id === store.activeId);
  }

  function lastWorkspaceThread(parentId, chats) {
    const siblings = (chats || []).filter((other) => chatParentId(other) === parentId);
    if (!siblings.length) return null;
    if (siblings.some((other) => other.id === store.activeId || hasUserTurn(other) || other.pinned)) {
      return null;
    }
    return siblings.slice().sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0))[0] || null;
  }

  function chatIsKept(item, chats) {
    if (!item) return false;
    if (item.id === store.activeId || hasUserTurn(item) || item.pinned) return true;
    if (isWorkspaceRoot(item)) return true;
    const parent = chatParentId(item);
    if (!parent) return false;
    const last = lastWorkspaceThread(parent, chats || store.chats);
    return Boolean(last && last.id === item.id);
  }

  function listedChats() {
    const mode = activeMode();
    const q = String((searchEl && searchEl.value) || "").trim().toLowerCase();
    return store.chats
      .filter((chat) => chatMode(chat) === mode)
      .filter((chat) => chatIsKept(chat, store.chats))
      .filter((chat) => {
        if (!q) return true;
        if (String(chat.title || "").toLowerCase().includes(q)) return true;
        if ((chat.messages || []).some((msg) => String(msg.content || "").toLowerCase().includes(q))) {
          return true;
        }
        if (isWorkspaceRoot(chat)) {
          return store.chats.some((child) => (
            chatParentId(child) === chat.id
            && (
              String(child.title || "").toLowerCase().includes(q)
              || (child.messages || []).some((msg) => String(msg.content || "").toLowerCase().includes(q))
            )
          ));
        }
        return false;
      })
      .sort((a, b) => {
        const pinOf = (item) => {
          if (chatMode(item) === "chat") return Boolean(item.pinned);
          return Boolean(isWorkspaceRoot(item) && item.pinned);
        };
        const pin = Number(pinOf(b)) - Number(pinOf(a));
        if (pin) return pin;
        return (b.updatedAt || 0) - (a.updatedAt || 0);
      });
  }

  let persistTail = Promise.resolve();
  let persistGen = 0;

  function persist() {
    rememberActiveMode();
    const chat = activeChat();
    if (chat && !isWorkspaceRoot(chat)) {
      chat.messages = cloneMessages(messages);
      if (!chat.titleLocked) chat.title = titleFromMessages(chat.messages, chat);
      const root = store.chats.find((item) => item.id === workspaceId(chat));
      if (
        root
        && isWorkspaceRoot(root)
        && !root.titleLocked
        && isPlaceholderTitle(root.title)
        && !isPlaceholderTitle(chat.title)
      ) {
        root.title = chat.title;
      }
    }
    const previous = store.chats.slice();
    store.chats = store.chats.filter((item) => chatIsKept(item, store.chats));
    const units = store.chats.filter((item) => !chatParentId(item));
    if (units.length > MAX_CHATS) {
      const extras = units
        .filter((item) => (
          item.id !== store.activeId
          && item.id !== activeWorkspaceId()
          && !item.pinned
        ))
        .sort((a, b) => workspaceActivity(a) - workspaceActivity(b));
      const drop = new Set();
      let remaining = units.length;
      extras.forEach((item) => {
        if (remaining <= MAX_CHATS) return;
        drop.add(item.id);
        remaining -= 1;
        if (isWorkspaceRoot(item)) {
          store.chats.forEach((child) => {
            if (chatParentId(child) === item.id) drop.add(child.id);
          });
        }
      });
      store.chats = store.chats.filter((item) => !drop.has(item.id));
    }
    const kept = new Set(store.chats.map((item) => item.id));
    paintToolbar();
    renderSidebar();
    paintActiveContext();
    if (!persistReady) return persistTail;
    previous.forEach((item) => {
      if (kept.has(item.id)) return;
      forgetTabs(item.id);
    });
    const gen = (persistGen += 1);
    persistTail = persistTail
      .then(() => {
        if (gen !== persistGen) return;
        return TabbyUI.api("chats", { method: "PUT", body: store });
      })
      .catch(() => {});
    return persistTail;
  }

  function workspaceActivity(item) {
    if (!item) return 0;
    if (!isWorkspaceRoot(item)) return item.updatedAt || 0;
    return Math.max(
      item.updatedAt || 0,
      ...nestedChats(item.id).map((child) => child.updatedAt || 0)
    );
  }

  function touchActive() {
    const chat = activeChat();
    if (!chat || isWorkspaceRoot(chat)) return;
    chat.updatedAt = Date.now();
  }

  function paintToolbar() {
    const chat = activeChat();
    const title = chat
      ? (isWorkspaceRoot(chat) ? workspaceDisplayTitle(chat) : (chat.title || "New chat"))
      : (activeMode() === "code" ? "New workspace" : "New chat");
    if (!renaming) {
      titleEl.textContent = title;
      titleEl.title = "Click to rename";
    }
    const pinBtn = moreMenu && moreMenu.querySelector('[data-more="pin"]');
    if (pinBtn) {
      const target = pinTarget(store.activeId);
      pinBtn.hidden = !target;
      if (target) {
        pinBtn.textContent = isWorkspaceRoot(target)
          ? (target.pinned ? "Unpin workspace" : "Pin workspace")
          : (target.pinned ? "Unpin" : "Pin");
      }
    }
    const threadBtn = moreMenu && moreMenu.querySelector('[data-more="thread"]');
    if (threadBtn) {
      threadBtn.hidden = activeMode() !== "code";
    }
    const deleteBtn = moreMenu && moreMenu.querySelector('[data-more="delete"]');
    if (deleteBtn) {
      deleteBtn.textContent = isWorkspaceRoot(chat) ? "Delete this workspace" : "Delete this chat";
    }
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
      attachBtn.setAttribute("aria-label", code ? "Attach files" : "Attach image or files");
      attachBtn.title = code ? "Attach image or project files" : "Attach image or files";
    }
    if (searchEl) searchEl.placeholder = code ? "Search workspaces" : "Search chats";
    const newBtn = root.querySelector("#chat-new");
    if (newBtn) newBtn.textContent = code ? "New workspace" : "New chat";
    paintTabs();
    paintFilesToggle();
    paintCodeAgent();
  }

  function paintCodeAgent() {
    const code = activeMode() === "code";
    if (agentWrap) agentWrap.hidden = !code;
    if (agentBtn) {
      const label = AGENT_LABELS[codeAgent] || "Agent";
      agentBtn.textContent = label;
      agentBtn.dataset.agent = codeAgent;
      agentBtn.setAttribute("aria-label", `Code prompt mode: ${label}`);
      agentBtn.setAttribute("aria-keyshortcuts", "Shift+Tab");
      agentBtn.title = `${label} · Shift+Tab to cycle`;
    }
    if (agentMenu) {
      agentMenu.querySelectorAll("[data-agent]").forEach((item) => {
        item.classList.toggle("is-on", item.dataset.agent === codeAgent);
      });
    }
  }

  function setCodeAgent(agent) {
    codeAgent = normalizeAgent(agent);
    try {
      localStorage.setItem(AGENT_KEY, codeAgent);
    } catch {
      /* ignore */
    }
    hideAgentMenu();
    paintCodeAgent();
    paintCompose();
  }

  function cycleCodeAgent() {
    if (activeMode() !== "code") return;
    if (agentBtn && agentBtn.disabled) return;
    const idx = AGENT_ORDER.indexOf(codeAgent);
    const next = AGENT_ORDER[((idx < 0 ? 0 : idx) + 1) % AGENT_ORDER.length];
    setCodeAgent(next);
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
    reclampPaneWidths();
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
    const chat = next === "code" ? addCodeWorkspace() : emptyChat(next);
    if (next !== "code") store.chats.unshift(chat);
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

  function readWsOpen() {
    try {
      const raw = JSON.parse(localStorage.getItem(WS_OPEN_KEY) || "{}");
      return raw && typeof raw === "object" && !Array.isArray(raw) ? raw : {};
    } catch {
      return {};
    }
  }

  let wsOpen = readWsOpen();

  function setWorkspaceOpen(id, open) {
    if (!id) return;
    wsOpen[id] = Boolean(open);
    try {
      localStorage.setItem(WS_OPEN_KEY, JSON.stringify(wsOpen));
    } catch {
      /* ignore */
    }
    renderSidebar();
  }

  function workspaceExpanded(id) {
    const q = String((searchEl && searchEl.value) || "").trim();
    if (q) return true;
    if (Object.prototype.hasOwnProperty.call(wsOpen, id)) return wsOpen[id] === true;
    return true;
  }

  function workspaceDisplayTitle(root) {
    const raw = String((root && root.title) || "").trim();
    if (raw && !isPlaceholderTitle(raw)) return raw;
    const kids = nestedChats(root && root.id)
      .filter((item) => hasUserTurn(item) || item.pinned)
      .sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0));
    const fromChild = String((kids[0] && kids[0].title) || "").trim();
    if (fromChild && !isPlaceholderTitle(fromChild)) return fromChild;
    return "New workspace";
  }

  function listedWorkspaceKids(rootId, listed) {
    const pool = Array.isArray(listed) && listed.length ? listed : store.chats;
    return pool
      .filter((chat) => chatParentId(chat) === rootId)
      .sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0));
  }

  function listedWorkspaceRows() {
    const list = listedChats();
    const byId = new Map(store.chats.map((chat) => [chat.id, chat]));
    const roots = [];
    const seen = new Set();
    list.forEach((chat) => {
      const rootId = chatParentId(chat) || chat.id;
      if (seen.has(rootId)) return;
      seen.add(rootId);
      const root = byId.get(rootId);
      if (root && isWorkspaceRoot(root)) roots.push(root);
    });
    roots.sort((a, b) => {
      const pin = Number(Boolean(b.pinned)) - Number(Boolean(a.pinned));
      if (pin) return pin;
      return (b.updatedAt || 0) - (a.updatedAt || 0);
    });
    const rows = [];
    roots.forEach((root) => {
      const kids = listedWorkspaceKids(root.id, list);
      const showKids = kids.length > 0 && workspaceExpanded(root.id);
      rows.push({ chat: root, kind: "root", kids: kids.length, showKids });
      if (showKids) {
        kids.forEach((child) => rows.push({ chat: child, kind: "child", kids: 0, showKids: false }));
      }
    });
    return rows;
  }

  function navRowMeta(item, kind, kidCount) {
    const bits = [];
    if (kind === "root" && kidCount > 0) {
      bits.push(`${kidCount} chat${kidCount === 1 ? "" : "s"}`);
    }
    if (inFlight && item.id === flightChatId) bits.push("Generating");
    else bits.push(timeLabel(item.updatedAt));
    return bits.filter(Boolean).join(" · ");
  }

  function navRowTools(kind, pinned) {
    const thread = kind === "root"
      ? `<button type="button" class="btn ghost chat-icon" data-nav="thread" aria-label="New chat in this workspace" title="New chat">${FILES_NEW_SVG}</button>`
      : "";
    const pinLabel = kind === "root"
      ? (pinned ? "Unpin workspace" : "Pin workspace")
      : (pinned ? "Unpin" : "Pin");
    const pin = kind !== "child"
      ? `<button type="button" class="btn ghost chat-icon" data-nav="pin" aria-label="${pinLabel}" title="${pinLabel}">${NAV_STAR_SVG}</button>`
      : "";
    const delLabel = kind === "root" ? "Delete workspace" : "Delete chat";
    return `<span class="chat-nav-tools">`
      + thread
      + pin
      + `<button type="button" class="btn ghost chat-icon" data-nav="rename" aria-label="Rename" title="Rename">${NAV_RENAME_SVG}</button>`
      + `<button type="button" class="btn ghost chat-icon danger" data-nav="delete" aria-label="${delLabel}" title="${delLabel}">${NAV_CLOSE_SVG}</button>`
      + `</span>`;
  }

  function navRowHtml(item, kind, kidCount) {
    const canExpand = kind === "root" && kidCount > 0;
    const expanded = canExpand && workspaceExpanded(item.id);
    let twist = "";
    if (kind === "root") {
      twist = canExpand
        ? `<button type="button" class="chat-nav-twist${expanded ? " is-open" : ""}" data-nav="twist" aria-label="${expanded ? "Collapse workspace" : "Expand workspace"}"></button>`
        : `<span class="chat-nav-twist is-empty" aria-hidden="true"></span>`;
    }
    const fallback = kind === "root" ? "New workspace" : "New chat";
    const title = kind === "root" ? workspaceDisplayTitle(item) : (item.title || fallback);
    const pin = kind !== "child" && item.pinned
      ? `<span class="chat-nav-pin" title="Pinned">${NAV_STAR_SVG}</span>`
      : "";
    return twist
      + `<span class="chat-nav-title">${TabbyUI.escapeHtml(title)}</span>`
      + pin
      + `<span class="chat-nav-when">${TabbyUI.escapeHtml(navRowMeta(item, kind, kidCount))}</span>`
      + navRowTools(kind, item.pinned);
  }

  function navRowEl(row, active) {
    const item = row.chat;
    const isRoot = row.kind === "root";
    const current = isRoot && Boolean(active) && chatParentId(active) === item.id;
    const selected = item.id === store.activeId && !isRoot;
    const canExpand = isRoot && row.kids > 0;
    const expanded = canExpand && workspaceExpanded(item.id);
    const btn = document.createElement("div");
    btn.className = "chat-nav"
      + (selected ? " is-active" : "")
      + (current ? " is-current" : "")
      + (row.kind !== "child" && item.pinned ? " is-pinned" : "")
      + (inFlight && item.id === flightChatId ? " is-busy" : "")
      + (row.kind === "child" ? " is-child" : "")
      + (isRoot ? " is-workspace" : "")
      + (canExpand ? " is-branch" : "")
      + (expanded ? " is-open" : "");
    btn.dataset.id = item.id;
    btn.setAttribute("role", "button");
    btn.tabIndex = 0;
    if (row.kind === "root") {
      btn.setAttribute("aria-expanded", canExpand ? (expanded ? "true" : "false") : "false");
    }
    btn.innerHTML = navRowHtml(item, row.kind, row.kids || 0);
    return btn;
  }

  function openWorkspaceNav(id) {
    const kids = listedWorkspaceKids(id, listedChats());
    if (kids.length) {
      if (!workspaceExpanded(id)) expandWorkspace(id);
      const current = activeChat();
      if (current && !isWorkspaceRoot(current) && workspaceId(current) === id) {
        renderSidebar();
        return;
      }
      loadChat(kids[0].id);
      return;
    }
    startNestedChat(id);
  }

  function renderSidebar() {
    if (!navList) return;
    const code = activeMode() === "code";
    const rows = code ? listedWorkspaceRows() : listedChats().map((chat) => ({ chat, kind: "flat", kids: 0, showKids: false }));
    if (!rows.length) {
      navList.innerHTML = code
        ? '<div class="chat-nav-empty">No workspaces match.</div>'
        : '<div class="chat-nav-empty">No chats match.</div>';
      return;
    }
    const active = activeChat();
    const frag = document.createDocumentFragment();
    let group = null;
    rows.forEach((row) => {
      const btn = navRowEl(row, active);
      if (row.kind === "root") {
        group = document.createElement("div");
        group.className = "chat-nav-group"
          + (row.showKids ? " is-open" : "")
          + (row.kids > 0 ? " is-branch" : "")
          + (active && chatParentId(active) === row.chat.id ? " is-current" : "");
        group.dataset.id = row.chat.id;
        group.setAttribute("role", "group");
        group.setAttribute("aria-label", workspaceDisplayTitle(row.chat));
        group.appendChild(btn);
        frag.appendChild(group);
        return;
      }
      if (row.kind === "child" && group) {
        group.appendChild(btn);
        return;
      }
      group = null;
      frag.appendChild(btn);
    });
    navList.replaceChildren(frag);
  }

  function paintEmpty() {
    if (!emptyEl) return;
    const empty = !messages.some((item) => (
      item.role === "assistant" || (userTurnHasContent(item) && !isHiddenUserTurn(item))
    ));
    emptyEl.hidden = !empty;
    if (!empty) return;
    const code = activeMode() === "code";
    const title = emptyEl.querySelector("#chat-empty-title");
    const copy = emptyEl.querySelector("#chat-empty-copy");
    const suggests = emptyEl.querySelector("#chat-suggests");
    if (title) title.textContent = code ? "Code mode" : "Console chat";
    if (copy) {
      copy.textContent = code
        ? "A workspace is a project folder. Chats under it share those files. Agent edits files, Ask answers without changing them, and Plan writes a design you Build. Or create files in the Files pane."
        : "Talk to the loaded model. Slash commands switch models and start pictures. Attach files for this chat only. Pasted images stay on this host.";
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
    forgetTabs(chatId);
    TabbyUI.api(`workspace/${encodeURIComponent(chatId)}`, { method: "DELETE" }).catch(() => {});
  }

  function tabsAreDirty(tabs) {
    return (tabs || []).some((tab) => tab && tab.dirty);
  }

  function anyDirtyTabs() {
    if (tabsAreDirty(openTabs)) return true;
    return Object.keys(tabsByChat).some((id) => tabsAreDirty(tabsByChat[id] && tabsByChat[id].openTabs));
  }

  function cloneTab(tab) {
    if (!tab) return tab;
    const copy = { ...tab, loading: false };
    if (tab.cropBox) copy.cropBox = { ...tab.cropBox };
    if (Array.isArray(tab.punchSeeds)) copy.punchSeeds = tab.punchSeeds.map((seed) => ({ ...seed }));
    if (Array.isArray(tab.punchBoxes)) copy.punchBoxes = tab.punchBoxes.map((box) => ({ ...box }));
    if (tab.resizeNatural) copy.resizeNatural = { ...tab.resizeNatural };
    if (Array.isArray(tab.caret)) copy.caret = tab.caret.slice();
    if (Array.isArray(tab.diff)) copy.diff = tab.diff.slice();
    return copy;
  }

  function cloneOpenTabs(tabs) {
    return (tabs || []).map((tab) => cloneTab(tab));
  }

  function cloneListingRows(rows) {
    return (rows || []).map((row) => (row && typeof row === "object" ? { ...row } : row));
  }

  function stashCurrentTabs() {
    stashEditor();
    if (!tabsChat) return;
    tabsByChat[tabsChat] = {
      openTabs: cloneOpenTabs(openTabs),
      activeTab,
      browserTabs: browserTabs.map((tab) => ({
        id: tab.id,
        path: tab.path,
        title: tab.title,
        url: tab.url,
      })),
      activeBrowserTab,
    };
    changesByChat[tabsChat] = filesChanged.slice();
    rememberCurrentListing(tabsChat);
  }

  function persistListings() {
    try {
      sessionStorage.setItem(LISTING_STORE_KEY, JSON.stringify(listingByChat));
    } catch {
      /* ignore */
    }
  }

  function rememberCurrentListing(chatId) {
    if (!chatId) return;
    listingByChat[chatId] = {
      files: cloneListingRows(filesListing),
      selected: filesSelected,
      entry: filesEntry,
      focusDir: filesFocusDir,
      openFolders: Array.from(filesOpenFolders),
    };
    persistListings();
  }

  function restorePersistedListings() {
    try {
      const raw = sessionStorage.getItem(LISTING_STORE_KEY);
      if (!raw) return;
      const dump = JSON.parse(raw);
      Object.keys(dump || {}).forEach((id) => {
        const row = dump[id];
        if (!row || !Array.isArray(row.files) || listingByChat[id]) return;
        listingByChat[id] = {
          files: cloneListingRows(row.files),
          selected: row.selected || "",
          entry: row.entry || "",
          focusDir: row.focusDir || "",
          openFolders: Array.isArray(row.openFolders) ? row.openFolders : [],
        };
      });
    } catch {
      /* ignore */
    }
  }

  function reloadRestoredFileTabs() {
    openTabs.forEach((tab) => {
      if (!tab || isPreviewTab(tab) || isHistoryTab(tab) || tab.dirty) return;
      if (tab.kind === "image") return;
      tab.state = "loading";
      tab.loading = false;
      tab.rev = 0;
      tab.text = "";
      tab.original = "";
    });
  }

  function restoreTabsFor(chatId) {
    const saved = chatId ? tabsByChat[chatId] : null;
    if (!saved) {
      resetTabs();
      return;
    }
    openTabs = cloneOpenTabs(saved.openTabs);
    activeTab = saved.activeTab && openTabs.some((tab) => tab.path === saved.activeTab)
      ? saved.activeTab
      : "";
    restoreBrowserTabList(saved.browserTabs, saved.activeBrowserTab);
    reloadRestoredFileTabs();
    if (editorPane) editorPane.dataset.key = "";
  }

  function forgetTabs(chatId) {
    if (!chatId) return;
    delete tabsByChat[chatId];
    delete changesByChat[chatId];
    delete listingByChat[chatId];
    persistListings();
    if (tabsChat === chatId) {
      resetTabs();
      tabsChat = "";
    }
  }

  function switchWorkspaceTabs(chatId) {
    if (tabsChat === chatId) return;
    stashCurrentTabs();
    if (window.TabbyMonaco) window.TabbyMonaco.dispose();
    if (editorPane) editorPane.dataset.key = "";
    previewRoot = "";
    if (tabsChat) flushDrafts();
    tabsChat = chatId || "";
    restoreTabsFor(tabsChat);
    resetFilesTreeState();
    draftsChat = "";
    const savedListing = chatId && listingByChat[chatId];
    if (savedListing) {
      filesListing = cloneListingRows(savedListing.files);
      filesSelected = savedListing.selected || "";
      filesEntry = savedListing.entry || "";
      filesFocusDir = savedListing.focusDir || "";
      filesOpenFolders = new Set(savedListing.openFolders || []);
    } else {
      filesListing = [];
      filesSelected = "";
      filesEntry = "";
      filesFocusDir = "";
    }
    filesChanged = (chatId && changesByChat[chatId] ? changesByChat[chatId] : []).slice();
    paintFiles();
    paintFilesChanges();
    closeTerm();
    previewOpen = Boolean(findTab(PREVIEW_TAB));
    if (previewPane) previewPane.hidden = !previewOpen;
    if (filesPreviewBtn) filesPreviewBtn.classList.toggle("is-on", previewOpen);
    paintBrowserChrome();
    if (previewOpen) ensurePreviewLoaded();
    if (window.TabbyLsp) window.TabbyLsp.reset();
  }

  function warnDirtyUnload(event) {
    persist();
    flushDrafts(true);
    if (!anyDirtyTabs()) return;
    event.preventDefault();
    event.returnValue = "";
  }

  function fileUrl(chatId, path) {
    return TabbyUI.path(`workspace/${encodeURIComponent(chatId)}/file?path=${encodeURIComponent(path)}`);
  }

  function fileSuffix(path) {
    const name = String(path || "").split("/").pop() || "";
    const at = name.lastIndexOf(".");
    return at >= 0 ? name.slice(at).toLowerCase() : "";
  }

  function fileDir(path) {
    const text = String(path || "");
    const slash = text.lastIndexOf("/");
    return slash >= 0 ? text.slice(0, slash) : "";
  }

  function fileBase(path) {
    const text = String(path || "");
    const slash = text.lastIndexOf("/");
    return slash >= 0 ? text.slice(slash + 1) : text;
  }

  function folderAncestors(path) {
    const parts = String(path || "").split("/").filter(Boolean);
    const dirs = [];
    for (let i = 1; i < parts.length; i += 1) {
      dirs.push(parts.slice(0, i).join("/"));
    }
    return dirs;
  }

  function resetFilesTreeState() {
    filesOpenFolders.clear();
    filesSeenPaths = new Set();
    filesRevealed = "";
    filesFocusDir = "";
    filesTreeReady = false;
  }

  function buildFilesTree(rows) {
    const root = { name: "", path: "", kind: "dir", children: [] };
    const dirs = new Map([["", root]]);

    function ensureDir(path) {
      if (dirs.has(path)) return dirs.get(path);
      const parent = ensureDir(fileDir(path));
      const node = { name: fileBase(path), path, kind: "dir", children: [] };
      parent.children.push(node);
      dirs.set(path, node);
      return node;
    }

    rows.forEach((row) => {
      const path = String(row.path || "").replace(/\\/g, "/").replace(/^\/+/, "");
      if (!path) return;
      if (row.kind === "dir") {
        ensureDir(path);
        return;
      }
      ensureDir(fileDir(path)).children.push({
        name: fileBase(path),
        path,
        kind: "file",
        row,
      });
    });

    function sortNode(node) {
      node.children.sort((a, b) => {
        if (a.kind !== b.kind) return a.kind === "dir" ? -1 : 1;
        return a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: "base" });
      });
      node.children.forEach((child) => {
        if (child.kind === "dir") sortNode(child);
      });
    }
    sortNode(root);
    return root;
  }

  function syncTreeFolders(rows) {
    const paths = rows.map((row) => String(row.path || ""));
    filesSeenPaths = new Set(paths);
    const live = new Set();
    rows.forEach((row) => {
      const path = String(row.path || "");
      if (!path) return;
      if (row.kind === "dir") live.add(path);
      folderAncestors(path).forEach((dir) => live.add(dir));
    });
    [...filesOpenFolders].forEach((dir) => {
      if (!live.has(dir)) filesOpenFolders.delete(dir);
    });
    if (filesFocusDir && !live.has(filesFocusDir)) filesFocusDir = "";
  }

  function revealSelectedIfNeeded() {
    if (!filesTreeReady) {
      filesRevealed = filesSelected;
      filesTreeReady = true;
      return;
    }
    if (!filesSelected || filesSelected === filesRevealed) return;
    filesRevealed = filesSelected;
    folderAncestors(filesSelected).forEach((dir) => filesOpenFolders.add(dir));
  }

  function toggleFolder(path) {
    if (!path) return;
    if (filesOpenFolders.has(path)) filesOpenFolders.delete(path);
    else filesOpenFolders.add(path);
    paintFilesTree();
  }

  function expandAllFolders() {
    filesListing.forEach((row) => {
      const path = String(row.path || "");
      if (row.kind === "dir" && path) filesOpenFolders.add(path);
      folderAncestors(path).forEach((dir) => filesOpenFolders.add(dir));
    });
    paintFilesTree();
  }

  function collapseAllFolders() {
    filesOpenFolders.clear();
    filesRevealed = "";
    paintFilesTree();
  }

  function isPendingFile(path) {
    return pendingFiles.some((file) => file.path === path);
  }

  function applyListing(data) {
    const prev = filesListing;
    filesListing = Array.isArray(data.files) ? data.files : filesListing;
    filesEntry = typeof data.entry === "string" ? data.entry : filesEntry;
    noteNewListingFiles(prev, filesListing);
    paintFiles();
  }

  function selectedRow() {
    return filesListing.find((row) => row.path === filesSelected) || null;
  }

  function paintSectionCount(el, count) {
    if (!el) return;
    el.textContent = count ? String(count) : "";
  }

  function paintChangesPane() {
    if (filesChangesPane) filesChangesPane.classList.toggle("is-collapsed", !changesOpen);
    if (filesChangesToggle) filesChangesToggle.setAttribute("aria-expanded", changesOpen ? "true" : "false");
    paintSectionCount(filesChangesCountEl, changeRows().length);
  }

  function paintHistoryPane() {
    if (filesHistoryPane) filesHistoryPane.classList.toggle("is-collapsed", !historyOpen);
    if (filesHistoryToggle) {
      filesHistoryToggle.setAttribute("aria-expanded", historyOpen ? "true" : "false");
    }
    const n = filesSelected && filesHistoryPath === filesSelected ? filesHistory.length : 0;
    paintSectionCount(filesHistoryCountEl, n);
  }

  function setChangesOpen(open) {
    changesOpen = Boolean(open);
    try {
      localStorage.setItem(CHANGES_KEY, changesOpen ? "open" : "closed");
    } catch {
      /* ignore */
    }
    paintChangesPane();
  }

  function setHistoryOpen(open) {
    historyOpen = Boolean(open);
    try {
      localStorage.setItem(HISTORY_KEY, historyOpen ? "open" : "closed");
    } catch {
      /* ignore */
    }
    paintHistoryPane();
  }

  function paintFilesHead() {
    paintFilesToggle();
    paintHistoryPane();
    paintChangesPane();
    const fileRows = filesListing.filter((row) => row.kind !== "dir");
    const total = fileRows.reduce((sum, row) => sum + (Number(row.size) || 0), 0);
    if (filesCountEl) {
      filesCountEl.textContent = fileRows.length
        ? `${fileRows.length} · ${TabbyUI.formatBytes(total)}`
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
    if (filesPreviewBtn) {
      filesPreviewBtn.disabled = !filesEntry;
      filesPreviewBtn.classList.toggle("is-on", previewOpen);
    }
    if (filesTermBtn) filesTermBtn.classList.toggle("is-on", termOpen);
  }

  function paintFilesTree() {
    if (!filesTree) return;
    if (!filesListing.length) {
      filesOpenFolders.clear();
      filesSeenPaths = new Set();
      filesRevealed = "";
      filesTreeReady = false;
      filesTree.innerHTML =
        '<p class="muted chat-files-empty">No files yet. Create one, upload, or ask for a page.</p>';
      return;
    }
    syncTreeFolders(filesListing);
    revealSelectedIfNeeded();
    const frag = document.createDocumentFragment();
    const walk = (nodes, depth) => {
      nodes.forEach((node) => {
        const isDir = node.kind === "dir";
        const expanded = isDir && filesOpenFolders.has(node.path);
        const row = node.row;
        const item = document.createElement("div");
        item.className =
          "chat-file" +
          (isDir ? " is-dir" : "") +
          (expanded ? " is-expanded" : "") +
          (!isDir && node.path === filesSelected ? " is-active" : "") +
          (!isDir && findTab(node.path) ? " is-open" : "") +
          (!isDir && isPendingFile(node.path) ? " is-attached" : "");
        item.dataset.path = node.path;
        item.dataset.kind = node.kind;
        item.draggable = true;
        item.style.setProperty("--depth", String(depth));
        const action = isDir ? "toggle" : "open";
        const size = !isDir && row ? TabbyUI.formatBytes(row.size) : "";
        item.innerHTML =
          `<button type="button" class="chat-file-open" data-file="${action}" title="${TabbyUI.escapeHtml(node.path)}"${
            isDir ? ` aria-expanded="${expanded ? "true" : "false"}"` : ""
          }>` +
          `<span class="chat-file-icon" aria-hidden="true">${isDir ? TREE_FOLDER_SVG : TREE_FILE_SVG}</span>` +
          `<span class="chat-file-name">${TabbyUI.escapeHtml(node.name)}</span>` +
          `</button>` +
          (size ? `<span class="chat-file-size">${TabbyUI.escapeHtml(size)}</span>` : "<span></span>") +
          (isDir
            ? ""
            : `<span class="chat-file-tools">` +
              `<button type="button" class="btn ghost chat-icon${isPendingFile(node.path) ? " is-on" : ""}" data-file="attach" aria-label="Add to chat" title="Add to chat">📎</button>` +
              `<button type="button" class="btn ghost chat-icon" data-file="download" aria-label="Download file" title="Download">↓</button>` +
              `<button type="button" class="btn ghost chat-icon danger" data-file="delete" aria-label="Delete file" title="Delete">×</button>` +
              `</span>`);
        frag.appendChild(item);
        if (isDir && expanded) walk(node.children, depth + 1);
      });
    };
    walk(buildFilesTree(filesListing).children, 0);
    filesTree.replaceChildren(frag);
  }

  function isChangePath(path) {
    const clean = String(path || "").replace(/^\/+/, "");
    if (!clean || clean.startsWith("__")) return false;
    // The "Writing files" status is not a real path.
    if (clean === "files" && !listingHas(clean) && !findTab(clean)) return false;
    return true;
  }

  function noteChange(path, written) {
    const clean = String(path || "").replace(/^\/+/, "");
    if (!isChangePath(clean)) return;
    const prev = filesChanged.find((row) => row.path === clean);
    filesChanged = filesChanged.filter((row) => row.path !== clean);
    filesChanged.unshift({
      path: clean,
      ts: Date.now(),
      written: Boolean(written || (prev && prev.written)),
    });
    if (filesChanged.length > 40) filesChanged.length = 40;
    paintFilesChanges();
  }

  function dropChange(path) {
    const clean = String(path || "").replace(/^\/+/, "");
    if (!clean) return;
    filesChanged = filesChanged.filter((row) => row.path !== clean);
    paintFilesChanges();
  }

  function noteAgentWrite(path) {
    if (!path) return;
    noteChange(path, true);
    filesSelected = path;
    filesFocusDir = fileDir(path);
  }

  function changeRows() {
    filesChanged = filesChanged.filter((row) => row && isChangePath(row.path));
    const seen = new Set();
    const rows = [];
    filesChanged.forEach((row) => {
      if (seen.has(row.path)) return;
      seen.add(row.path);
      rows.push(row);
    });
    openTabs.forEach((tab) => {
      if (!tab || isHistoryTab(tab) || isPreviewTab(tab) || !tab.dirty) return;
      if (seen.has(tab.path)) return;
      seen.add(tab.path);
      rows.push({ path: tab.path, ts: Date.now(), written: false });
    });
    return rows;
  }

  function paintFilesChanges() {
    if (!filesChangesList) return;
    paintChangesPane();
    const rows = changeRows();
    if (!rows.length) {
      filesChangesList.innerHTML =
        '<p class="muted chat-files-empty">Edits from you and the model show up here.</p>';
      return;
    }
    const frag = document.createDocumentFragment();
    rows.forEach((row) => {
      const tab = findTab(row.path);
      const item = document.createElement("div");
      item.className =
        "chat-history" + (selectedPathFromTab(activeTab) === row.path && !isHistoryTab(activeTabRow()) ? " is-active" : "");
      item.dataset.path = row.path;
      const dirty = Boolean(tab && tab.dirty);
      item.innerHTML =
        `<button type="button" class="chat-history-open" data-change="open" title="Edit this file and its diff">${TabbyUI.escapeHtml(row.path)}</button>` +
        `<span class="chat-file-size">${dirty ? "unsaved" : "edited"}</span>` +
        `<span class="chat-file-tools">` +
        `<button type="button" class="btn ghost chat-icon" data-change="discard" aria-label="Discard changes" title="Discard changes">↩</button>` +
        `</span>`;
      frag.appendChild(item);
    });
    filesChangesList.replaceChildren(frag);
  }

  async function openChange(path) {
    if (!path) return;
    filesSelected = path;
    filesFocusDir = fileDir(path);
    await refreshHistory();
    if (filesHistory.length) openHistoryTab(path, filesHistory[0]);
    else openFileTab(path);
  }

  function historyTabKey(path, id) {
    return `__history__/${id}/${path}`;
  }

  function isHistoryTab(tab) {
    return Boolean(tab && tab.kind === "diff");
  }

  function isPreviewPath(path) {
    return path === PREVIEW_TAB;
  }

  function isPreviewTab(tab) {
    return Boolean(tab && (tab.kind === "preview" || tab.path === PREVIEW_TAB));
  }

  function selectedPathFromTab(path) {
    if (isPreviewPath(path)) return "";
    const tab = findTab(path);
    if (isHistoryTab(tab)) return tab.filePath || "";
    return path || "";
  }

  function activeHistoryId() {
    const tab = activeTabRow();
    return isHistoryTab(tab) ? tab.revId : "";
  }

  function paintFilesHistory() {
    if (!filesHistoryList) return;
    paintHistoryPane();
    if (!filesSelected) {
      filesHistoryList.innerHTML =
        '<p class="muted chat-files-empty">Select a file to see its history.</p>';
      return;
    }
    if (filesHistoryPath !== filesSelected) {
      filesHistoryList.innerHTML = '<p class="muted chat-files-empty">Loading…</p>';
      return;
    }
    if (!filesHistory.length) {
      filesHistoryList.innerHTML =
        '<p class="muted chat-files-empty">No history yet. Edits keep a version here.</p>';
      return;
    }
    const openId = activeHistoryId();
    const frag = document.createDocumentFragment();
    filesHistory.forEach((row) => {
      const item = document.createElement("div");
      item.className = "chat-history" + (row.id === openId ? " is-active" : "");
      item.dataset.id = row.id;
      item.innerHTML =
        `<button type="button" class="chat-history-open" data-history="open" title="Compare to the latest file">${TabbyUI.escapeHtml(timeLabel(row.ts))}</button>` +
        `<span class="chat-file-size">${TabbyUI.escapeHtml(TabbyUI.formatBytes(row.bytes))}</span>` +
        `<span class="chat-file-tools">` +
        `<button type="button" class="btn ghost chat-icon" data-history="restore" aria-label="Restore this version" title="Restore this version">↺</button>` +
        `</span>`;
      frag.appendChild(item);
    });
    filesHistoryList.replaceChildren(frag);
  }

  async function refreshHistory() {
    const chatId = activeWorkspaceId();
    const path = filesSelected;
    if (!path || activeMode() !== "code" || !chatId) {
      filesHistory = [];
      filesHistoryPath = "";
      paintFilesHistory();
      return;
    }
    const req = (filesHistoryReq += 1);
    try {
      const data = await TabbyUI.api(
        `workspace/${encodeURIComponent(chatId)}/history?path=${encodeURIComponent(path)}`
      );
      if (req !== filesHistoryReq || chatId !== activeWorkspaceId() || filesSelected !== path) return;
      filesHistory = Array.isArray(data.versions) ? data.versions : [];
      filesHistoryPath = path;
    } catch {
      if (req !== filesHistoryReq || chatId !== activeWorkspaceId()) return;
      filesHistory = [];
      filesHistoryPath = path;
    }
    paintFilesHistory();
  }

  // Past this many characters the editor drops the highlight overlay; retinting
  // a huge file on every keystroke costs more than the colour is worth.
  const HIGHLIGHT_LIMIT = 120_000;

  function fileLang(path) {
    return window.TabbyHighlight ? window.TabbyHighlight.pathLanguage(path) : "";
  }

  function editorLangLabel(tab, view) {
    if (isHistoryTab(tab)) return "vs previous";
    const suffix = fileSuffix(tab.path).replace(/^\./, "");
    if (view === "image" || tab.kind === "image" || IMAGE_SUFFIXES.has(fileSuffix(tab.path))) {
      if (suffix === "jpg" || suffix === "jpeg") return "jpeg";
      return suffix || "image";
    }
    if (view === "binary") return suffix || "binary";
    return fileLang(tab.path) || (window.TabbyMonaco ? window.TabbyMonaco.languageFor(tab.path) : "");
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
    if (isPreviewTab(tab)) return "Preview";
    if (isHistoryTab(tab)) {
      const base = (tab.filePath || tab.path).split("/").pop() || "file";
      return `${base} · ${timeLabel(tab.revTs)}`;
    }
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

  /** Keep the live editor buffer in the tab so a re-render or tab switch restores it. */
  function stashEditor() {
    const tab = activeTabRow();
    if (!tab || isPreviewTab(tab)) return;
    if (window.TabbyMonaco && window.TabbyMonaco.getEditor()) {
      tab.text = window.TabbyMonaco.getValue();
      tab.caret = window.TabbyMonaco.getCaret();
      return;
    }
    const box = editorBox();
    if (!box) return;
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
    const paintOne = (tab) => {
      const name = TabbyUI.escapeHtml(tabLabel(tab));
      const item = document.createElement("div");
      item.className =
        "chat-tab" + (tab.path === activeTab ? " is-active" : "") + (tab.dirty ? " is-dirty" : "");
      item.dataset.tab = tab.path;
      const title = isPreviewTab(tab) ? "Preview" : TabbyUI.escapeHtml(tab.path);
      item.innerHTML =
        `<button type="button" class="chat-tab-open" title="${title}">${name}</button>` +
        `<button type="button" class="chat-tab-close" data-tab-close aria-label="Close ${name}">×</button>`;
      frag.appendChild(item);
    };
    openTabs.forEach((tab) => {
      if (!isPreviewTab(tab)) paintOne(tab);
    });
    const preview = findTab(PREVIEW_TAB);
    if (preview) paintOne(preview);
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
    paintCropReadout(tab);
    const apply = editorPane.querySelector("[data-edit='crop-apply']");
    if (apply) {
      const box = tab.cropBox;
      apply.disabled = tab.busy || !box || box.w < 1 || box.h < 1;
      apply.textContent = tab.busy ? "Cropping" : "Apply";
    }
    paintPunchHead(tab);
    paintResizeHead(tab);
  }

  /** A reload keeps showing the text it already has instead of flashing. */
  function tabView(tab) {
    if (isHistoryTab(tab)) {
      return tab.state === "loading" && tab.rev > 0 ? "diff" : tab.state;
    }
    return tab.state === "loading" && tab.rev > 0 ? "ready" : tab.state;
  }

  function editorSpinnerHtml() {
    return (
      '<div class="chat-editor-spinner-host" role="status" aria-label="Loading">' +
      '<span class="chat-editor-spinner" aria-hidden="true"></span>' +
      "</div>"
    );
  }

  function editorBodyHtml(tab, view) {
    if (view === "image") {
      const src = `${fileUrl(activeWorkspaceId(), tab.path)}&v=${tab.size}`;
      const img = `<img alt="" src="${TabbyUI.escapeHtml(src)}" />`;
      if (tab.punching) {
        return (
          `<div class="chat-editor-body is-image is-punch"><div class="chat-punch-stage">${img}` +
          '<canvas class="chat-punch-canvas" data-punch-canvas></canvas>' +
          '<div class="chat-punch-marquee" hidden data-punch-marquee></div></div></div>'
        );
      }
      if (tab.resizing) {
        const handles = ["nw", "n", "ne", "w", "e", "sw", "s", "se"]
          .map((name) => `<button type="button" class="chat-crop-handle" data-resize-handle="${name}" aria-label="Resize ${name}"></button>`)
          .join("");
        return (
          `<div class="chat-editor-body is-image is-resize"><div class="chat-image-stage chat-resize-stage">${img}` +
          `<div class="chat-resize-box" data-resize-box>${handles}</div></div></div>`
        );
      }
      if (!tab.cropping) {
        return `<div class="chat-editor-body is-image"><div class="chat-image-stage">${img}</div></div>`;
      }
      const handles = ["nw", "n", "ne", "w", "e", "sw", "s", "se"]
        .map((name) => `<button type="button" class="chat-crop-handle" data-crop-handle="${name}" aria-label="Resize ${name}"></button>`)
        .join("");
      return (
        `<div class="chat-editor-body is-image is-crop"><div class="chat-crop-stage">${img}` +
        '<div class="chat-crop-shade" data-crop-shade="n"></div>' +
        '<div class="chat-crop-shade" data-crop-shade="s"></div>' +
        '<div class="chat-crop-shade" data-crop-shade="e"></div>' +
        '<div class="chat-crop-shade" data-crop-shade="w"></div>' +
        `<div class="chat-crop-box" data-crop-box>${handles}</div></div></div>`
      );
    }
    if (view === "binary") {
      return '<div class="chat-editor-body"><p class="muted">Download this file to open it.</p></div>';
    }
    if (view === "error") {
      return '<div class="chat-editor-body"><p class="muted">Could not read this file.</p></div>';
    }
    if (view !== "ready" && view !== "diff") {
      return `<div class="chat-editor-body is-loading">${editorSpinnerHtml()}</div>`;
    }
    if (!window.TabbyMonaco) {
      return (
        '<div class="chat-editor-body"><p class="muted">Code editor failed to load.</p>' +
        '<button type="button" class="btn" data-edit="retry-editor">Retry</button></div>'
      );
    }
    const spin = window.monaco ? "" : editorSpinnerHtml();
    return `<div class="chat-editor-body is-monaco"><div class="code-monaco">${spin}</div></div>`;
  }

  function renderEditorPane() {
    if (!editorPane) return;
    const tab = activeTabRow();
    if (!tab) return;
    // Code turns repaint the listing every 600 ms; only rebuild when the file,
    // its state, or a reloaded revision actually changed, so typing survives.
    const view = tabView(tab);
    const key = `${activeWorkspaceId()}|${tab.path}|${view}|${tab.rev}|${tab.cropping ? "crop" : tab.punching ? "punch" : tab.resizing ? "resize" : ""}`;
    if (editorPane.dataset.key === key) {
      paintEditorHead();
      return;
    }
    editorPane.dataset.key = key;
    const title = isHistoryTab(tab) ? tab.filePath || tab.path : tab.path;
    const lang = editorLangLabel(tab, view);
    const tools =
      view === "ready" || view === "diff"
        ? (view === "diff"
            ? '<button type="button" class="btn ghost" data-edit="restore">Restore old</button>'
            : '<button type="button" class="btn ghost" data-edit="compare">Changes</button>') +
          '<button type="button" class="btn ghost" data-edit="revert" hidden>Revert</button>' +
          '<button type="button" class="btn primary" data-edit="save" disabled>Saved</button>'
        : view === "image" && !isHistoryTab(tab)
          ? (tab.cropping
              ? '<span class="chat-crop-readout" data-crop-readout></span>' +
                '<button type="button" class="btn ghost" data-edit="crop-cancel">Cancel</button>' +
                '<button type="button" class="btn primary" data-edit="crop-apply">Apply</button>'
              : tab.punching
                ? '<span class="chat-crop-readout" data-punch-readout></span>' +
                  '<button type="button" class="btn ghost" data-edit="punch-cancel">Cancel</button>' +
                  '<button type="button" class="btn primary" data-edit="punch-apply">Make transparent</button>'
                : tab.resizing
                  ? '<span class="chat-crop-readout" data-resize-readout></span>' +
                    '<button type="button" class="btn ghost" data-edit="resize-cancel">Cancel</button>' +
                    '<button type="button" class="btn primary" data-edit="resize-apply">Apply</button>'
                  : '<button type="button" class="btn ghost" data-edit="crop">Crop</button>' +
                    '<button type="button" class="btn ghost" data-edit="resize">Resize</button>' +
                    '<button type="button" class="btn ghost" data-edit="punch">Make transparent</button>')
          : "";
    editorPane.innerHTML =
      '<div class="chat-editor-head">' +
      `<strong>${TabbyUI.escapeHtml(title)}</strong>` +
      '<span class="chat-editor-size"></span>' +
      (lang ? `<span class="chat-editor-lang">${TabbyUI.escapeHtml(lang)}</span>` : "") +
      '<span class="spacer"></span>' +
      (isHistoryTab(tab)
        ? ""
        : '<button type="button" class="btn ghost chat-icon" data-edit="download" aria-label="Download file" title="Download">↓</button>') +
      tools +
      "</div>" +
      (view === "image" && tab.punching
        ? '<div class="chat-punch-bar">' +
          "<span>Click a color or drag a box to erase. Click again to add more.</span>" +
          `<label class="chat-punch-tol">Tolerance <input type="range" min="0" max="80" value="${tab.punchTolerance ?? 28}" data-punch-tolerance /></label>` +
          '<button type="button" class="btn ghost" data-edit="punch-contiguous">Connected</button>' +
          "</div>"
        : view === "image" && tab.resizing
          ? '<div class="chat-resize-bar">' +
            '<label class="chat-resize-dim">Width <input type="number" min="1" max="8192" inputmode="numeric" data-resize-w /></label>' +
            '<label class="chat-resize-dim">Height <input type="number" min="1" max="8192" inputmode="numeric" data-resize-h /></label>' +
            '<button type="button" class="btn ghost" data-edit="resize-lock">Lock</button>' +
            "</div>"
          : "") +
      editorBodyHtml(tab, view) +
      '<p class="muted chat-editor-note"></p>';
    mountMonaco(tab, view);
    if (view === "image" && tab.cropping) mountCropOverlay(tab);
    if (view === "image" && tab.punching) mountPunchOverlay(tab);
    if (view === "image" && tab.resizing) mountResizePreview(tab);
    paintEditorHead();
  }

  function onMonacoChange(text) {
    const tab = activeTabRow();
    if (!tab) return;
    tab.text = text;
    queueDrafts();
    const path = isHistoryTab(tab) ? tab.filePath : tab.path;
    if (window.TabbyLsp && path) window.TabbyLsp.didChange(path, text);
    const next = text !== String(tab.original || "");
    if (next === tab.dirty) {
      paintEditorHead();
      return;
    }
    tab.dirty = next;
    tab.note = "";
    if (next && path) noteChange(path);
    paintEditorHead();
    paintTabs();
    paintFilesChanges();
  }

  function monacoLoadErrorHtml(message) {
    const detail = message ? `<p class="muted">${TabbyUI.escapeHtml(message)}</p>` : "";
    return (
      `<div class="chat-editor-body"><p class="muted">Code editor failed to load.</p>${detail}` +
      '<button type="button" class="btn" data-edit="retry-editor">Retry</button></div>'
    );
  }

  function remountEditor() {
    if (editorPane) editorPane.dataset.key = "";
    renderEditorPane();
  }

  function mountMonaco(tab, view) {
    const host = editorPane.querySelector(".code-monaco");
    if (!host) return;
    if (!window.TabbyMonaco) return;
    window.TabbyMonaco.onChange(onMonacoChange);
    window.TabbyMonaco.onSave(() => saveTab());
    const path = isHistoryTab(tab) ? tab.filePath || tab.path : tab.path;
    const pending =
      view === "diff"
        ? window.TabbyMonaco.showDiff(host, {
            path,
            original: tab.oldText || "",
            modified: tab.text || tab.original || "",
          })
        : window.TabbyMonaco.showFile(host, {
            path,
            text: tab.text || "",
            caret: tab.caret,
          });
    Promise.resolve(pending).catch((err) => {
      const body = editorPane.querySelector(".chat-editor-body");
      if (body) body.outerHTML = monacoLoadErrorHtml(err && err.message);
    });
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
    if (gutter && editorFindHits.length) {
      const marks = new Set(editorFindHits.map(([start]) => text.slice(0, start).split("\n").length));
      gutter.querySelectorAll(".is-find-line").forEach((node) => node.classList.remove("is-find-line"));
      // Gutter is plain text; a data attr is enough for CSS line tint via box-shadow later.
      gutter.dataset.findLines = [...marks].join(",");
    } else if (gutter) {
      gutter.dataset.findLines = "";
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
    if (!tab || isPreviewTab(tab) || tab.state !== "loading" || tab.loading) return;
    if (isHistoryTab(tab)) {
      const chatId = activeWorkspaceId();
      tab.loading = true;
      TabbyUI.api(
        `workspace/${encodeURIComponent(chatId)}/history/rev?path=${encodeURIComponent(tab.filePath || "")}&id=${encodeURIComponent(tab.revId || "")}`
      )
        .then((data) => {
          tab.loading = false;
          if (chatId !== activeWorkspaceId() || !findTab(tab.path)) return;
          tab.diff = Array.isArray(data.diff) ? data.diff : [];
          tab.oldText = String(data.contents || "");
          tab.original = String(data.latest || "");
          tab.text = String(data.latest || "");
          tab.size = Number(data.bytes) || tab.size;
          tab.revTs = Number(data.ts) || tab.revTs;
          tab.state = "diff";
          tab.rev += 1;
          if (activeTab === tab.path) renderEditorPane();
          paintTabs();
          paintFilesHistory();
        })
        .catch(() => {
          tab.loading = false;
          if (chatId !== activeWorkspaceId() || !findTab(tab.path)) return;
          tab.state = "error";
          tab.rev += 1;
          if (activeTab === tab.path) renderEditorPane();
        });
      return;
    }
    if (tab.kind === "image") {
      tab.state = "image";
      return;
    }
    // Drafts restored after a reload omit listing metadata. A missing
    // `editable` must not hide unsaved text behind the binary stub.
    const suffix = fileSuffix(tab.path);
    const editable =
      tab.editable ||
      TEXT_SUFFIXES.has(suffix) ||
      (tab.dirty && typeof tab.text === "string");
    if (!editable) {
      tab.state = "binary";
      return;
    }
    tab.editable = true;
    if (!tab.kind) tab.kind = "text";
    const chatId = activeWorkspaceId();
    tab.loading = true;
    fetch(fileUrl(chatId, tab.path), { credentials: "same-origin" })
      .then((res) => (res.ok ? res.text() : Promise.reject(new Error("read"))))
      .then((text) => {
        tab.loading = false;
        if (chatId !== activeWorkspaceId() || !findTab(tab.path)) return;
        tab.original = text;
        if (tab.dirty && typeof tab.text === "string" && tab.text !== text) {
          tab.dirty = true;
        } else {
          tab.text = text;
          tab.dirty = false;
          tab.caret = null;
          tab.scrollTop = 0;
          tab.scrollLeft = 0;
        }
        tab.state = "ready";
        tab.rev += 1;
        if (activeTab === tab.path) renderEditorPane();
        paintTabs();
      })
      .catch(() => {
        tab.loading = false;
        if (chatId !== activeWorkspaceId() || !findTab(tab.path)) return;
        if (tab.dirty && typeof tab.text === "string") {
          tab.state = "ready";
          tab.gone = true;
        } else {
          tab.state = "error";
        }
        tab.rev += 1;
        if (activeTab === tab.path) renderEditorPane();
      });
  }

  function paintPreviewDock() {
    if (!previewTabBtn) return;
    const asTab = previewOpen && isPreviewTab(activeTabRow());
    previewTabBtn.textContent = asTab ? "Side" : "Tab";
    previewTabBtn.title = asTab ? "Show preview beside the editor" : "Open preview as a tab";
    previewTabBtn.setAttribute("aria-label", previewTabBtn.title);
  }

  function paintView() {
    const tab = activeTabRow();
    if (activeTab && !tab) activeTab = "";
    const previewAsTab = previewOpen && isPreviewTab(tab);
    const showEditor = Boolean(tab) && !previewAsTab;
    const showLog = !showEditor && !previewAsTab;
    const logWasHidden = Boolean(logWrap && logWrap.hidden);
    if (!logWasHidden && !showLog) logScroll = log.scrollTop;
    if (logWrap) logWrap.hidden = !showLog;
    if (editorCol) editorCol.hidden = !showEditor;
    if (editorPane) editorPane.hidden = !showEditor;
    if (previewPane) {
      previewPane.hidden = !previewOpen;
      previewPane.classList.toggle("is-tab", previewAsTab);
    }
    paintPreviewDock();
    if (showEditor) {
      ensureTabLoaded(tab);
      renderEditorPane();
      return;
    }
    if (editorPane) editorPane.dataset.key = "";
    if (window.TabbyMonaco) window.TabbyMonaco.dispose();
    // display:none drops the scroll offset, so put the log back where it was.
    if (logWasHidden && showLog) {
      if (followLog) stickLog();
      else {
        log.scrollTop = logScroll;
        paintJump();
      }
    }
  }

  function paintTabsAndFiles() {
    paintFilesHead();
    paintFilesTree();
    paintFilesHistory();
    paintFilesChanges();
    paintTabs();
    paintView();
  }

  function activateTab(path) {
    if (activeTab === path) return;
    stashEditor();
    activeTab = path;
    if (!isPreviewPath(path)) {
      filesSelected = selectedPathFromTab(path);
      if (filesSelected) filesFocusDir = fileDir(filesSelected);
    }
    paintTabsAndFiles();
    if (!isPreviewPath(path)) refreshHistory();
  }

  function listingHas(path) {
    return filesListing.some((row) => row.path === path);
  }

  function resolveWorkspaceImage(hint, href) {
    const clean = String(hint || "").replace(/\\/g, "/").replace(/^\/+/, "");
    if (clean && listingHas(clean)) return clean;
    if (clean) {
      const webp = clean.replace(/\.(png|jpe?g|gif)$/i, ".webp");
      if (webp !== clean && listingHas(webp)) return webp;
      const png = clean.replace(/\.webp$/i, ".png");
      if (png !== clean && listingHas(png)) return png;
      const base = (clean.split("/").pop() || "").toLowerCase();
      const stem = base.replace(/\.[^.]+$/, "");
      const match = filesListing.find((row) => {
        if (row.kind !== "image") return false;
        const name = (row.path.split("/").pop() || "").toLowerCase();
        return name === base || name.replace(/\.[^.]+$/, "") === stem;
      });
      if (match) return match.path;
    }
    const fromHref = String(href || "").split(/[?#]/, 1)[0].split("/").pop() || "";
    if (fromHref && listingHas(fromHref)) return fromHref;
    const hrefMatch = filesListing.find((row) => (row.path.split("/").pop() || "") === fromHref);
    return hrefMatch ? hrefMatch.path : "";
  }

  async function openImageFromLink(link) {
    const hinted = (link.getAttribute("data-file") || "").trim();
    const href = link.getAttribute("href") || "";
    let path = resolveWorkspaceImage(hinted, href);
    if (!path || !filesListing.length) {
      await refreshFiles();
      path = resolveWorkspaceImage(hinted, href);
    }
    if (path) openFileTab(path);
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
    refreshHistory();
    // On a phone the files pane covers the chat column the tab just opened in.
    if (narrowChat.matches && filesOpen) setFilesOpen(false);
  }

  function openHistoryTab(path, version) {
    const key = historyTabKey(path, version.id);
    stashEditor();
    if (!findTab(key)) {
      openTabs.push({
        path: key,
        filePath: path,
        revId: version.id,
        revTs: Number(version.ts) || 0,
        size: Number(version.bytes) || 0,
        kind: "diff",
        editable: false,
        state: "loading",
        rev: 0,
        original: "",
        text: "",
        diff: [],
        dirty: false,
        busy: false,
        note: "",
        gone: false,
        caret: null,
        scrollTop: 0,
        scrollLeft: 0,
      });
    }
    activeTab = key;
    filesSelected = path;
    paintTabsAndFiles();
    if (narrowChat.matches && filesOpen) setFilesOpen(false);
  }

  async function loadFileHistory(path) {
    const chatId = activeWorkspaceId();
    if (!path || activeMode() !== "code" || !chatId) return [];
    const data = await TabbyUI.api(
      `workspace/${encodeURIComponent(chatId)}/history?path=${encodeURIComponent(path)}`
    );
    return Array.isArray(data.versions) ? data.versions : [];
  }

  async function applyRestore(path, revId, options) {
    const data = await TabbyUI.api(
      `workspace/${encodeURIComponent(activeWorkspaceId())}/history/restore`,
      { method: "POST", body: { path, id: revId } }
    );
    const tab = findTab(path);
    if (tab) {
      tab.dirty = false;
      tab.state = "loading";
    }
    openTabs.forEach((item) => {
      if (isHistoryTab(item) && item.filePath === path) {
        item.state = "loading";
        item.rev += 1;
      }
    });
    applyListing(data);
    if (!options || options.open !== false) openFileTab(data.path || path);
    refreshHistory();
  }

  async function restoreHistory(path, revId) {
    if (!path || !revId) return;
    const yes = await TabbyUI.confirmModal({
      title: "Restore this version?",
      text: `Replace “${path}” with this older version? The current file is kept in history.`,
      yes: "Restore",
      no: "Cancel",
    });
    if (!yes) return;
    try {
      await applyRestore(path, revId);
    } catch (err) {
      addBubble("assistant", `Error: ${err.message}`);
    }
  }

  async function discardChange(path, options) {
    const opts = options || {};
    const clean = String(path || "").replace(/^\/+/, "");
    if (!clean) return false;
    const row = filesChanged.find((item) => item.path === clean);
    const tab = findTab(clean);
    const written = Boolean(row && row.written);
    if (!opts.skipConfirm) {
      const yes = await TabbyUI.confirmModal({
        title: "Discard changes?",
        text: written
          ? `Undo the last write to “${clean}”? The current file is kept in History.`
          : `Discard unsaved edits to “${clean}”?`,
        yes: "Discard",
        no: "Cancel",
      });
      if (!yes) return false;
    }
    try {
      if (written) {
        if (tab) tab.dirty = false;
        const versions = await loadFileHistory(clean);
        if (versions.length) {
          await applyRestore(clean, versions[0].id, { open: false });
        } else if (filesListing.some((item) => item.path === clean)) {
          await deleteProjectFile(clean, { skipConfirm: true });
        }
      } else if (tab && tab.dirty) {
        revertTabAt(clean);
      }
    } catch (err) {
      addBubble("assistant", `Error: ${err.message}`);
      return false;
    }
    dropChange(clean);
    return true;
  }

  async function discardAllChanges() {
    const rows = changeRows();
    if (!rows.length) return;
    const yes = await TabbyUI.confirmModal({
      title: "Discard all changes?",
      text: `Undo changes to ${rows.length} file${rows.length === 1 ? "" : "s"}? Unsaved edits and last writes are thrown away.`,
      yes: "Discard",
      no: "Cancel",
    });
    if (!yes) return;
    for (const row of rows) {
      await discardChange(row.path, { skipConfirm: true });
    }
  }

  async function closeTab(path) {
    if (isPreviewPath(path) || isPreviewTab(findTab(path))) {
      hidePreview();
      return;
    }
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
      filesSelected = isPreviewPath(activeTab) ? filesSelected : selectedPathFromTab(activeTab);
      if (editorPane) editorPane.dataset.key = "";
    }
    paintTabsAndFiles();
  }

  function resetTabs() {
    openTabs = [];
    activeTab = "";
    if (editorPane) editorPane.dataset.key = "";
    previewOpen = false;
    if (previewPane) {
      previewPane.hidden = true;
      previewPane.classList.remove("is-tab");
    }
    clearBrowserTabs();
    if (filesPreviewBtn) filesPreviewBtn.classList.remove("is-on");
  }

  /** Fold a fresh listing into the open tabs: drop gone files, reload rewrites. */
  function syncTabs() {
    for (let i = openTabs.length - 1; i >= 0; i -= 1) {
      const tab = openTabs[i];
      if (isHistoryTab(tab) || isPreviewTab(tab)) continue;
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
    // Keep a tree/history selection when Chat is showing so a deleted file
    // can still be restored from History.
    if (activeTab && !isPreviewPath(activeTab)) filesSelected = selectedPathFromTab(activeTab);
  }

  function paintFiles() {
    syncTabs();
    paintTabsAndFiles();
    refreshHistory();
  }

  let cropDrag = null;
  let cropResize = null;

  function isImageTab(tab) {
    return Boolean(tab && (tab.kind === "image" || IMAGE_SUFFIXES.has(fileSuffix(tab.path))));
  }

  function clampCropBox(box, nw, nh) {
    let x = Math.round(box.x);
    let y = Math.round(box.y);
    let w = Math.round(box.w);
    let h = Math.round(box.h);
    if (w < 1) w = 1;
    if (h < 1) h = 1;
    if (x < 0) {
      w += x;
      x = 0;
    }
    if (y < 0) {
      h += y;
      y = 0;
    }
    if (x + w > nw) w = nw - x;
    if (y + h > nh) h = nh - y;
    if (w < 1) {
      w = 1;
      x = Math.max(0, Math.min(x, nw - 1));
    }
    if (h < 1) {
      h = 1;
      y = Math.max(0, Math.min(y, nh - 1));
    }
    return { x, y, w, h };
  }

  function resizeCropBox(origin, handle, dx, dy, natural, square) {
    const nw = natural.w;
    const nh = natural.h;
    if (handle === "move") {
      const w = origin.w;
      const h = origin.h;
      return {
        x: Math.round(Math.max(0, Math.min(origin.x + dx, nw - w))),
        y: Math.round(Math.max(0, Math.min(origin.y + dy, nh - h))),
        w,
        h,
      };
    }
    let x = origin.x;
    let y = origin.y;
    let w = origin.w;
    let h = origin.h;
    const east = handle.includes("e");
    const west = handle.includes("w");
    const north = handle.includes("n");
    const south = handle.includes("s");
    if (east) w = origin.w + dx;
    if (west) {
      x = origin.x + dx;
      w = origin.w - dx;
    }
    if (south) h = origin.h + dy;
    if (north) {
      y = origin.y + dy;
      h = origin.h - dy;
    }
    if (w < 1) {
      x = east ? origin.x + origin.w - 1 : origin.x;
      w = 1;
    }
    if (h < 1) {
      y = south ? origin.y + origin.h - 1 : origin.y;
      h = 1;
    }
    if (square) {
      const side = Math.max(1, Math.round(Math.max(Math.abs(w), Math.abs(h))));
      if (west) x = origin.x + origin.w - side;
      else if (!east) x = origin.x + (origin.w - side) / 2;
      if (north) y = origin.y + origin.h - side;
      else if (!south) y = origin.y + (origin.h - side) / 2;
      w = side;
      h = side;
    }
    return clampCropBox({ x, y, w, h }, nw, nh);
  }

  function paintCropReadout(tab) {
    const readout = editorPane && editorPane.querySelector("[data-crop-readout]");
    if (!readout || !tab || !tab.cropBox) return;
    const natural = tab.cropNatural;
    const box = tab.cropBox;
    readout.textContent = natural
      ? `${box.w} × ${box.h} of ${natural.w} × ${natural.h}`
      : `${box.w} × ${box.h}`;
  }

  function paintCropOverlay(tab) {
    const body = editorPane && editorPane.querySelector(".chat-editor-body.is-crop");
    if (!body || !tab || !tab.cropBox) return;
    const img = body.querySelector("img");
    const boxEl = body.querySelector("[data-crop-box]");
    if (!img || !boxEl || !img.naturalWidth) return;
    const sx = img.clientWidth / img.naturalWidth;
    const sy = img.clientHeight / img.naturalHeight;
    const { x, y, w, h } = tab.cropBox;
    boxEl.style.left = `${x * sx}px`;
    boxEl.style.top = `${y * sy}px`;
    boxEl.style.width = `${Math.max(1, w * sx)}px`;
    boxEl.style.height = `${Math.max(1, h * sy)}px`;
    const n = body.querySelector('[data-crop-shade="n"]');
    const s = body.querySelector('[data-crop-shade="s"]');
    const e = body.querySelector('[data-crop-shade="e"]');
    const west = body.querySelector('[data-crop-shade="w"]');
    if (n) {
      n.style.left = "0";
      n.style.top = "0";
      n.style.right = "0";
      n.style.height = `${Math.max(0, y * sy)}px`;
    }
    if (s) {
      s.style.left = "0";
      s.style.top = `${(y + h) * sy}px`;
      s.style.right = "0";
      s.style.bottom = "0";
    }
    if (west) {
      west.style.left = "0";
      west.style.top = `${y * sy}px`;
      west.style.width = `${Math.max(0, x * sx)}px`;
      west.style.height = `${Math.max(0, h * sy)}px`;
    }
    if (e) {
      e.style.left = `${(x + w) * sx}px`;
      e.style.top = `${y * sy}px`;
      e.style.right = "0";
      e.style.height = `${Math.max(0, h * sy)}px`;
    }
    paintCropReadout(tab);
    const apply = editorPane.querySelector("[data-edit='crop-apply']");
    if (apply) {
      apply.disabled = tab.busy || w < 1 || h < 1;
      apply.textContent = tab.busy ? "Cropping" : "Apply";
    }
  }

  function defaultCropBox(nw, nh) {
    const insetX = Math.max(1, Math.round(nw * 0.08));
    const insetY = Math.max(1, Math.round(nh * 0.08));
    return clampCropBox(
      { x: insetX, y: insetY, w: nw - insetX * 2, h: nh - insetY * 2 },
      nw,
      nh
    );
  }

  function mountCropOverlay(tab) {
    if (cropResize) {
      cropResize.disconnect();
      cropResize = null;
    }
    const body = editorPane && editorPane.querySelector(".chat-editor-body.is-crop");
    if (!body || !tab) return;
    const stage = body.querySelector(".chat-crop-stage");
    const img = body.querySelector("img");
    if (!stage || !img) return;

    const ready = () => {
      const nw = img.naturalWidth;
      const nh = img.naturalHeight;
      if (!nw || !nh) return;
      tab.cropNatural = { w: nw, h: nh };
      if (!tab.cropBox) tab.cropBox = defaultCropBox(nw, nh);
      paintCropOverlay(tab);
    };
    if (img.complete && img.naturalWidth) ready();
    else img.addEventListener("load", ready, { once: true });

    if (typeof ResizeObserver === "function") {
      cropResize = new ResizeObserver(() => paintCropOverlay(tab));
      cropResize.observe(img);
    }

    const naturalFromClient = (clientX, clientY) => {
      const rect = img.getBoundingClientRect();
      const width = rect.width || 1;
      const height = rect.height || 1;
      return {
        x: ((clientX - rect.left) / width) * (img.naturalWidth || 1),
        y: ((clientY - rect.top) / height) * (img.naturalHeight || 1),
      };
    };

    stage.addEventListener("pointerdown", (event) => {
      if (event.button !== 0 || tab.busy) return;
      const handleEl = event.target.closest("[data-crop-handle]");
      const onBox = event.target.closest("[data-crop-box]");
      const natural = tab.cropNatural;
      if (!natural) return;
      event.preventDefault();
      stage.setPointerCapture(event.pointerId);
      const at = naturalFromClient(event.clientX, event.clientY);
      if (!handleEl && !onBox) {
        const x = Math.round(Math.max(0, Math.min(at.x, natural.w - 1)));
        const y = Math.round(Math.max(0, Math.min(at.y, natural.h - 1)));
        tab.cropBox = { x, y, w: 1, h: 1 };
        cropDrag = {
          tab,
          handle: "se",
          start: { x, y },
          origin: { ...tab.cropBox },
        };
        paintCropOverlay(tab);
        return;
      }
      cropDrag = {
        tab,
        handle: handleEl ? handleEl.dataset.cropHandle : "move",
        start: at,
        origin: { ...tab.cropBox },
      };
    });
    stage.addEventListener("pointermove", (event) => {
      if (!cropDrag || cropDrag.tab !== tab || !tab.cropNatural) return;
      const at = naturalFromClient(event.clientX, event.clientY);
      tab.cropBox = resizeCropBox(
        cropDrag.origin,
        cropDrag.handle,
        at.x - cropDrag.start.x,
        at.y - cropDrag.start.y,
        tab.cropNatural,
        event.shiftKey
      );
      paintCropOverlay(tab);
    });
    const endDrag = (event) => {
      if (!cropDrag || cropDrag.tab !== tab) return;
      cropDrag = null;
      try {
        stage.releasePointerCapture(event.pointerId);
      } catch {
        /* already released */
      }
    };
    stage.addEventListener("pointerup", endDrag);
    stage.addEventListener("pointercancel", endDrag);
  }

  function beginCrop(tab) {
    if (!tab || !isImageTab(tab) || isHistoryTab(tab)) return;
    clearPunchState(tab);
    clearResizeState(tab);
    dropSizeDrag();
    if (punchResize) {
      punchResize.disconnect();
      punchResize = null;
    }
    tab.cropping = true;
    tab.cropBox = null;
    tab.cropNatural = null;
    tab.note = "";
    if (editorPane) editorPane.dataset.key = "";
    renderEditorPane();
  }

  function beginCropPath(path) {
    openFileTab(path);
    const tab = findTab(path);
    if (tab) beginCrop(tab);
  }

  function cancelCrop(tab) {
    if (!tab || !tab.cropping) return;
    tab.cropping = false;
    tab.cropBox = null;
    tab.cropNatural = null;
    tab.note = "";
    cropDrag = null;
    if (editorPane) editorPane.dataset.key = "";
    renderEditorPane();
  }

  async function applyCrop(tab) {
    if (!tab || !tab.cropping || tab.busy || !tab.cropBox) return;
    const { x, y, w, h } = tab.cropBox;
    if (w < 1 || h < 1) return;
    const chatId = activeWorkspaceId();
    const path = tab.path;
    tab.busy = true;
    tab.note = "";
    paintEditorHead();
    try {
      const data = await TabbyUI.api(`workspace/${encodeURIComponent(chatId)}/crop`, {
        method: "POST",
        body: { path, x, y, width: w, height: h },
      });
      if (chatId !== activeWorkspaceId()) return;
      tab.busy = false;
      tab.cropping = false;
      tab.cropBox = null;
      tab.cropNatural = null;
      cropDrag = null;
      applyListing(data);
      const live = findTab(path) || tab;
      const saved = filesListing.find((item) => item.path === path);
      live.size = saved ? Number(saved.size) || Number(data.bytes) || live.size : Number(data.bytes) || live.size;
      live.state = "image";
      live.rev += 1;
      live.note = "Cropped.";
      reloadPreviewIfNeeded();
      if (editorPane) editorPane.dataset.key = "";
      paintTabsAndFiles();
    } catch (err) {
      tab.busy = false;
      tab.note = err.message;
      paintEditorHead();
    }
  }

  const RESIZE_MAX = 8192;
  let sizeDrag = null;
  let sizeObs = null;

  function dropSizeDrag() {
    sizeDrag = null;
    if (sizeObs) {
      sizeObs.disconnect();
      sizeObs = null;
    }
  }

  function clearResizeState(tab) {
    if (!tab) return;
    tab.resizing = false;
    tab.resizeW = null;
    tab.resizeH = null;
    tab.resizeNatural = null;
    sizeDrag = null;
  }

  function resizeDim(value) {
    const n = Math.round(Number(value));
    if (!Number.isFinite(n)) return 0;
    return Math.max(1, Math.min(RESIZE_MAX, n));
  }

  function applyResizeHandle(origin, handle, dx, dy, lock, natural) {
    const east = handle.includes("e");
    const west = handle.includes("w");
    const north = handle.includes("n");
    const south = handle.includes("s");
    let w = origin.w;
    let h = origin.h;
    if (lock && natural && natural.w && natural.h) {
      if (east || west) {
        w = resizeDim(east ? origin.w + dx : origin.w - dx);
        h = resizeDim((w * natural.h) / natural.w);
      } else {
        h = resizeDim(south ? origin.h + dy : origin.h - dy);
        w = resizeDim((h * natural.w) / natural.h);
      }
    } else {
      if (east) w = resizeDim(origin.w + dx);
      if (west) w = resizeDim(origin.w - dx);
      if (south) h = resizeDim(origin.h + dy);
      if (north) h = resizeDim(origin.h - dy);
    }
    return { w, h };
  }

  function resizeChanged(tab) {
    const natural = tab && tab.resizeNatural;
    const w = Number(tab && tab.resizeW);
    const h = Number(tab && tab.resizeH);
    if (!natural || w < 1 || h < 1) return false;
    return w !== natural.w || h !== natural.h;
  }

  function paintResizePreview(tab) {
    const stage = editorPane && editorPane.querySelector(".chat-resize-stage");
    if (!stage || !tab || !tab.resizeW || !tab.resizeH) return;
    stage.style.setProperty("--resize-w", `${tab.resizeW}px`);
    stage.style.setProperty("--resize-h", `${tab.resizeH}px`);
  }

  function paintResizeHead(tab) {
    if (!tab || !tab.resizing) return;
    const readout = editorPane && editorPane.querySelector("[data-resize-readout]");
    const natural = tab.resizeNatural;
    const w = tab.resizeW;
    const h = tab.resizeH;
    if (readout) {
      readout.textContent = natural && w && h
        ? `${w} × ${h} of ${natural.w} × ${natural.h}`
        : w && h ? `${w} × ${h}` : "";
    }
    const apply = editorPane && editorPane.querySelector("[data-edit='resize-apply']");
    if (apply) {
      apply.disabled = tab.busy || !resizeChanged(tab);
      apply.textContent = tab.busy ? "Resizing" : "Apply";
    }
    const lock = editorPane && editorPane.querySelector("[data-edit='resize-lock']");
    if (lock) {
      const on = tab.resizeLock !== false;
      lock.classList.toggle("is-on", on);
      lock.setAttribute("aria-pressed", on ? "true" : "false");
      lock.textContent = on ? "Lock" : "Free";
    }
    const wIn = editorPane && editorPane.querySelector("[data-resize-w]");
    const hIn = editorPane && editorPane.querySelector("[data-resize-h]");
    if (wIn && document.activeElement !== wIn && w) wIn.value = String(w);
    if (hIn && document.activeElement !== hIn && h) hIn.value = String(h);
    paintResizePreview(tab);
  }

  function setResizeNatural(tab, nw, nh) {
    if (!tab || !nw || !nh) return;
    tab.resizeNatural = { w: nw, h: nh };
    if (!tab.resizeW || !tab.resizeH) {
      tab.resizeW = nw;
      tab.resizeH = nh;
    }
    paintResizeHead(tab);
  }

  function setResizeWidth(tab, value) {
    if (!tab || !tab.resizing) return;
    const w = resizeDim(value);
    tab.resizeW = w;
    if (tab.resizeLock !== false && tab.resizeNatural) {
      tab.resizeH = resizeDim((w * tab.resizeNatural.h) / tab.resizeNatural.w);
    }
    paintResizeHead(tab);
  }

  function setResizeHeight(tab, value) {
    if (!tab || !tab.resizing) return;
    const h = resizeDim(value);
    tab.resizeH = h;
    if (tab.resizeLock !== false && tab.resizeNatural) {
      tab.resizeW = resizeDim((h * tab.resizeNatural.w) / tab.resizeNatural.h);
    }
    paintResizeHead(tab);
  }

  function toggleResizeLock(tab) {
    if (!tab || !tab.resizing) return;
    tab.resizeLock = tab.resizeLock === false;
    if (tab.resizeLock !== false && tab.resizeNatural && tab.resizeW) {
      tab.resizeH = resizeDim((tab.resizeW * tab.resizeNatural.h) / tab.resizeNatural.w);
    }
    paintResizeHead(tab);
  }

  function mountResizePreview(tab) {
    dropSizeDrag();
    const body = editorPane && editorPane.querySelector(".chat-editor-body.is-resize");
    if (!body || !tab) return;
    const stage = body.querySelector(".chat-resize-stage");
    const img = body.querySelector("img");
    if (!stage || !img) return;
    const ready = () => setResizeNatural(tab, img.naturalWidth, img.naturalHeight);
    if (img.complete && img.naturalWidth) ready();
    else img.addEventListener("load", ready, { once: true });
    paintResizePreview(tab);
    if (typeof ResizeObserver === "function") {
      sizeObs = new ResizeObserver(() => paintResizePreview(tab));
      sizeObs.observe(stage);
    }
    stage.addEventListener("pointerdown", (event) => {
      if (event.button !== 0 || tab.busy) return;
      const handleEl = event.target.closest("[data-resize-handle]");
      if (!handleEl || !tab.resizeW || !tab.resizeH) return;
      event.preventDefault();
      stage.setPointerCapture(event.pointerId);
      const rect = stage.getBoundingClientRect();
      sizeDrag = {
        tab,
        handle: handleEl.dataset.resizeHandle,
        start: { x: event.clientX, y: event.clientY },
        origin: { w: tab.resizeW, h: tab.resizeH },
        scaleX: (rect.width || 1) / tab.resizeW,
        scaleY: (rect.height || 1) / tab.resizeH,
      };
    });
    stage.addEventListener("pointermove", (event) => {
      if (!sizeDrag || sizeDrag.tab !== tab) return;
      const handle = sizeDrag.handle || "";
      const corner =
        (handle.includes("n") || handle.includes("s")) &&
        (handle.includes("e") || handle.includes("w"));
      const lock = event.shiftKey ? !corner : corner;
      const next = applyResizeHandle(
        sizeDrag.origin,
        sizeDrag.handle,
        (event.clientX - sizeDrag.start.x) / sizeDrag.scaleX,
        (event.clientY - sizeDrag.start.y) / sizeDrag.scaleY,
        lock,
        tab.resizeNatural
      );
      tab.resizeW = next.w;
      tab.resizeH = next.h;
      paintResizeHead(tab);
    });
    const endDrag = (event) => {
      if (!sizeDrag || sizeDrag.tab !== tab) return;
      sizeDrag = null;
      try {
        stage.releasePointerCapture(event.pointerId);
      } catch {
        /* already released */
      }
    };
    stage.addEventListener("pointerup", endDrag);
    stage.addEventListener("pointercancel", endDrag);
  }

  function beginResize(tab) {
    if (!tab || !isImageTab(tab) || isHistoryTab(tab)) return;
    clearPunchState(tab);
    if (punchResize) {
      punchResize.disconnect();
      punchResize = null;
    }
    tab.cropping = false;
    tab.cropBox = null;
    tab.cropNatural = null;
    cropDrag = null;
    if (cropResize) {
      cropResize.disconnect();
      cropResize = null;
    }
    tab.resizing = true;
    tab.resizeW = null;
    tab.resizeH = null;
    tab.resizeNatural = null;
    if (tab.resizeLock == null) tab.resizeLock = true;
    tab.note = "";
    if (editorPane) editorPane.dataset.key = "";
    renderEditorPane();
  }

  function beginResizePath(path) {
    openFileTab(path);
    const tab = findTab(path);
    if (tab) beginResize(tab);
  }

  function cancelResize(tab) {
    if (!tab || !tab.resizing) return;
    clearResizeState(tab);
    dropSizeDrag();
    tab.note = "";
    if (editorPane) editorPane.dataset.key = "";
    renderEditorPane();
  }

  async function applyResize(tab) {
    if (!tab || !tab.resizing || tab.busy || !resizeChanged(tab)) return;
    const w = resizeDim(tab.resizeW);
    const h = resizeDim(tab.resizeH);
    const chatId = activeWorkspaceId();
    const path = tab.path;
    tab.busy = true;
    tab.note = "";
    paintEditorHead();
    try {
      const data = await TabbyUI.api(`workspace/${encodeURIComponent(chatId)}/resize`, {
        method: "POST",
        body: { path, width: w, height: h },
      });
      if (chatId !== activeWorkspaceId()) return;
      tab.busy = false;
      clearResizeState(tab);
      dropSizeDrag();
      applyListing(data);
      const live = findTab(path) || tab;
      const saved = filesListing.find((item) => item.path === path);
      live.size = saved ? Number(saved.size) || Number(data.bytes) || live.size : Number(data.bytes) || live.size;
      live.state = "image";
      live.rev += 1;
      live.note = data.dimensions ? `Resized to ${data.dimensions.replace("x", " × ")}.` : "Resized.";
      reloadPreviewIfNeeded();
      if (editorPane) editorPane.dataset.key = "";
      paintTabsAndFiles();
    } catch (err) {
      tab.busy = false;
      tab.note = err.message;
      paintEditorHead();
    }
  }

  const PUNCH_TOLERANCE_DEFAULT = 28;
  let punchDrag = null;
  let punchResize = null;

  function punchSelectionCount(tab) {
    return (tab && tab.punchCount) || 0;
  }

  function clearPunchState(tab) {
    if (!tab) return;
    tab.punching = false;
    tab.punchSeeds = [];
    tab.punchBoxes = [];
    tab.punchNatural = null;
    tab.punchSource = null;
    tab.punchMask = null;
    tab.punchCount = 0;
    punchDrag = null;
  }

  function paintPunchHead(tab) {
    if (!tab || !tab.punching) return;
    const readout = editorPane && editorPane.querySelector("[data-punch-readout]");
    if (readout) {
      const n = punchSelectionCount(tab);
      readout.textContent = n ? `${n.toLocaleString()} px selected` : "No selection";
    }
    const apply = editorPane && editorPane.querySelector("[data-edit='punch-apply']");
    if (apply) {
      apply.disabled = tab.busy || punchSelectionCount(tab) < 1;
      apply.textContent = tab.busy ? "Saving" : "Make transparent";
    }
    const slider = editorPane && editorPane.querySelector("[data-punch-tolerance]");
    if (slider && Number(slider.value) !== Number(tab.punchTolerance)) {
      slider.value = String(tab.punchTolerance ?? PUNCH_TOLERANCE_DEFAULT);
    }
    const toggle = editorPane && editorPane.querySelector("[data-edit='punch-contiguous']");
    if (toggle) {
      const on = tab.punchContiguous !== false;
      toggle.classList.toggle("is-on", on);
      toggle.setAttribute("aria-pressed", on ? "true" : "false");
      toggle.textContent = on ? "Connected" : "All matching";
    }
  }

  function colorDist2(data, index, r, g, b) {
    const dr = data[index] - r;
    const dg = data[index + 1] - g;
    const db = data[index + 2] - b;
    return dr * dr + dg * dg + db * db;
  }

  function dilatePunchMask(mask, width, height) {
    const out = new Uint8Array(mask);
    for (let y = 0; y < height; y += 1) {
      const row = y * width;
      for (let x = 0; x < width; x += 1) {
        if (!mask[row + x]) continue;
        if (x) out[row + x - 1] = 1;
        if (x + 1 < width) out[row + x + 1] = 1;
        if (y) out[row - width + x] = 1;
        if (y + 1 < height) out[row + width + x] = 1;
      }
    }
    return out;
  }

  function rebuildPunchMask(tab) {
    const source = tab && tab.punchSource;
    if (!source) {
      if (tab) tab.punchCount = 0;
      return;
    }
    const { width, height, data } = source;
    const mask = new Uint8Array(width * height);
    const tol = Number(tab.punchTolerance);
    const tol2 = (Number.isFinite(tol) ? tol : PUNCH_TOLERANCE_DEFAULT) ** 2;
    const contiguous = tab.punchContiguous !== false;
    const seeds = Array.isArray(tab.punchSeeds) ? tab.punchSeeds : [];
    const boxes = Array.isArray(tab.punchBoxes) ? tab.punchBoxes : [];

    const matches = (x, y, r, g, b) => {
      const i = (y * width + x) * 4;
      if (data[i + 3] < 8) return false;
      return colorDist2(data, i, r, g, b) <= tol2;
    };

    const flood = (sx, sy) => {
      if (sx < 0 || sy < 0 || sx >= width || sy >= height) return;
      const start = (sy * width + sx) * 4;
      if (data[start + 3] < 8) return;
      const r = data[start];
      const g = data[start + 1];
      const b = data[start + 2];
      if (contiguous) {
        const queue = [[sx, sy]];
        for (let q = 0; q < queue.length; q += 1) {
          const x = queue[q][0];
          const y = queue[q][1];
          const index = y * width + x;
          if (mask[index] || !matches(x, y, r, g, b)) continue;
          mask[index] = 1;
          if (x) queue.push([x - 1, y]);
          if (x + 1 < width) queue.push([x + 1, y]);
          if (y) queue.push([x, y - 1]);
          if (y + 1 < height) queue.push([x, y + 1]);
        }
        return;
      }
      for (let y = 0; y < height; y += 1) {
        const row = y * width;
        for (let x = 0; x < width; x += 1) {
          if (matches(x, y, r, g, b)) mask[row + x] = 1;
        }
      }
    };

    seeds.forEach((seed) => flood(Math.round(seed.x), Math.round(seed.y)));
    boxes.forEach((box) => {
      const x0 = Math.max(0, Math.round(box.x));
      const y0 = Math.max(0, Math.round(box.y));
      const x1 = Math.min(width, Math.round(box.x + box.w));
      const y1 = Math.min(height, Math.round(box.y + box.h));
      if (x1 <= x0 || y1 <= y0) return;
      for (let y = y0; y < y1; y += 1) {
        const row = y * width;
        for (let x = x0; x < x1; x += 1) {
          if (data[(row + x) * 4 + 3] >= 8) mask[row + x] = 1;
        }
      }
    });

    let punched = 0;
    for (let i = 0; i < mask.length; i += 1) if (mask[i]) punched += 1;
    const grown = punched ? dilatePunchMask(mask, width, height) : mask;
    if (grown !== mask) {
      punched = 0;
      for (let i = 0; i < grown.length; i += 1) if (grown[i]) punched += 1;
    }
    tab.punchMask = grown;
    tab.punchCount = punched;
  }

  function paintPunchOverlay(tab) {
    const body = editorPane && editorPane.querySelector(".chat-editor-body.is-punch");
    if (!body || !tab) return;
    const img = body.querySelector("img");
    const canvas = body.querySelector("[data-punch-canvas]");
    if (!img || !canvas || !img.clientWidth || !tab.punchSource) return;
    const { width, height, data } = tab.punchSource;
    const mask = tab.punchMask;
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    const preview = ctx.createImageData(width, height);
    preview.data.set(data);
    if (mask) {
      const out = preview.data;
      for (let i = 0, p = 0; i < mask.length; i += 1, p += 4) {
        if (mask[i]) out[p + 3] = 0;
      }
    }
    ctx.putImageData(preview, 0, 0);
    canvas.style.width = `${img.clientWidth}px`;
    canvas.style.height = `${img.clientHeight}px`;
    paintPunchHead(tab);
  }

  async function imageDataFromUrl(url) {
    const res = await fetch(url, { credentials: "same-origin" });
    if (!res.ok) throw new Error("Could not read that image.");
    const blob = await res.blob();
    const canvas = document.createElement("canvas");
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    if (typeof createImageBitmap === "function") {
      const bitmap = await createImageBitmap(blob);
      canvas.width = bitmap.width;
      canvas.height = bitmap.height;
      ctx.drawImage(bitmap, 0, 0);
      if (bitmap.close) bitmap.close();
    } else {
      const href = URL.createObjectURL(blob);
      try {
        const image = await new Promise((resolve, reject) => {
          const node = new Image();
          node.onload = () => resolve(node);
          node.onerror = () => reject(new Error("Could not read that image."));
          node.src = href;
        });
        canvas.width = image.naturalWidth;
        canvas.height = image.naturalHeight;
        ctx.drawImage(image, 0, 0);
      } finally {
        URL.revokeObjectURL(href);
      }
    }
    return ctx.getImageData(0, 0, canvas.width, canvas.height);
  }

  function mountPunchOverlay(tab) {
    if (punchResize) {
      punchResize.disconnect();
      punchResize = null;
    }
    const body = editorPane && editorPane.querySelector(".chat-editor-body.is-punch");
    if (!body || !tab) return;
    const stage = body.querySelector(".chat-punch-stage");
    const img = body.querySelector("img");
    const marquee = body.querySelector("[data-punch-marquee]");
    if (!stage || !img) return;

    const chatId = activeWorkspaceId();
    const path = tab.path;
    const src = fileUrl(chatId, path);
    imageDataFromUrl(`${src}${src.includes("?") ? "&" : "?"}v=${tab.size || 0}`)
      .then((pixels) => {
        if (activeWorkspaceId() !== chatId || !tab.punching || tab.path !== path) return;
        tab.punchSource = pixels;
        tab.punchNatural = { w: pixels.width, h: pixels.height };
        rebuildPunchMask(tab);
        paintPunchOverlay(tab);
      })
      .catch((err) => {
        if (activeWorkspaceId() !== chatId || tab.path !== path) return;
        tab.note = err.message || "Could not read that image.";
        paintEditorHead();
      });

    if (img.complete && img.naturalWidth) paintPunchOverlay(tab);
    else img.addEventListener("load", () => paintPunchOverlay(tab), { once: true });
    if (typeof ResizeObserver === "function") {
      punchResize = new ResizeObserver(() => paintPunchOverlay(tab));
      punchResize.observe(img);
    }

    const naturalFromClient = (clientX, clientY) => {
      const rect = img.getBoundingClientRect();
      const width = rect.width || 1;
      const height = rect.height || 1;
      const nw = (tab.punchNatural && tab.punchNatural.w) || img.naturalWidth || 1;
      const nh = (tab.punchNatural && tab.punchNatural.h) || img.naturalHeight || 1;
      return {
        x: ((clientX - rect.left) / width) * nw,
        y: ((clientY - rect.top) / height) * nh,
        rect,
        nw,
        nh,
      };
    };

    const paintMarquee = (a, b, natural) => {
      if (!marquee || !natural) return;
      const sx = (img.clientWidth || 1) / natural.nw;
      const sy = (img.clientHeight || 1) / natural.nh;
      const x = Math.min(a.x, b.x);
      const y = Math.min(a.y, b.y);
      const w = Math.abs(b.x - a.x);
      const h = Math.abs(b.y - a.y);
      marquee.hidden = w < 1 && h < 1;
      marquee.style.left = `${x * sx}px`;
      marquee.style.top = `${y * sy}px`;
      marquee.style.width = `${Math.max(1, w * sx)}px`;
      marquee.style.height = `${Math.max(1, h * sy)}px`;
    };

    stage.addEventListener("pointerdown", (event) => {
      if (event.button !== 0 || tab.busy || !tab.punchSource) return;
      event.preventDefault();
      stage.setPointerCapture(event.pointerId);
      const at = naturalFromClient(event.clientX, event.clientY);
      punchDrag = { tab, start: at, last: at };
      paintMarquee(at, at, at);
    });
    stage.addEventListener("pointermove", (event) => {
      if (!punchDrag || punchDrag.tab !== tab) return;
      const at = naturalFromClient(event.clientX, event.clientY);
      punchDrag.last = at;
      paintMarquee(punchDrag.start, at, at);
    });
    const endDrag = (event) => {
      if (!punchDrag || punchDrag.tab !== tab) return;
      const start = punchDrag.start;
      const last = punchDrag.last || start;
      punchDrag = null;
      if (marquee) marquee.hidden = true;
      try {
        stage.releasePointerCapture(event.pointerId);
      } catch {
        /* already released */
      }
      const nw = start.nw;
      const nh = start.nh;
      const x0 = Math.round(Math.max(0, Math.min(start.x, last.x, nw - 1)));
      const y0 = Math.round(Math.max(0, Math.min(start.y, last.y, nh - 1)));
      const x1 = Math.round(Math.min(nw, Math.max(start.x, last.x) + 1));
      const y1 = Math.round(Math.min(nh, Math.max(start.y, last.y) + 1));
      const w = Math.max(1, x1 - x0);
      const h = Math.max(1, y1 - y0);
      const dx = (last.x - start.x) * ((img.clientWidth || 1) / nw);
      const dy = (last.y - start.y) * ((img.clientHeight || 1) / nh);
      if (Math.hypot(dx, dy) < 6) {
        tab.punchSeeds = (tab.punchSeeds || []).concat({ x: x0, y: y0 });
      } else {
        tab.punchBoxes = (tab.punchBoxes || []).concat({ x: x0, y: y0, w, h });
      }
      tab.note = "";
      rebuildPunchMask(tab);
      paintPunchOverlay(tab);
    };
    stage.addEventListener("pointerup", endDrag);
    stage.addEventListener("pointercancel", endDrag);
  }

  function beginPunch(tab) {
    if (!tab || !isImageTab(tab) || isHistoryTab(tab)) return;
    tab.cropping = false;
    tab.cropBox = null;
    tab.cropNatural = null;
    cropDrag = null;
    if (cropResize) {
      cropResize.disconnect();
      cropResize = null;
    }
    clearResizeState(tab);
    dropSizeDrag();
    tab.punching = true;
    tab.punchSeeds = [];
    tab.punchBoxes = [];
    tab.punchNatural = null;
    tab.punchSource = null;
    tab.punchMask = null;
    tab.punchCount = 0;
    if (tab.punchTolerance == null) tab.punchTolerance = PUNCH_TOLERANCE_DEFAULT;
    if (tab.punchContiguous == null) tab.punchContiguous = true;
    tab.note = "";
    if (editorPane) editorPane.dataset.key = "";
    renderEditorPane();
  }

  function beginPunchPath(path) {
    openFileTab(path);
    const tab = findTab(path);
    if (tab) beginPunch(tab);
  }

  function cancelPunch(tab) {
    if (!tab || !tab.punching) return;
    clearPunchState(tab);
    tab.note = "";
    if (punchResize) {
      punchResize.disconnect();
      punchResize = null;
    }
    if (editorPane) editorPane.dataset.key = "";
    renderEditorPane();
  }

  function setPunchTolerance(tab, value) {
    if (!tab || !tab.punching) return;
    const next = Math.max(0, Math.min(80, Number(value)));
    if (!Number.isFinite(next) || next === tab.punchTolerance) return;
    tab.punchTolerance = next;
    rebuildPunchMask(tab);
    paintPunchOverlay(tab);
  }

  function togglePunchContiguous(tab) {
    if (!tab || !tab.punching) return;
    tab.punchContiguous = tab.punchContiguous === false;
    rebuildPunchMask(tab);
    paintPunchOverlay(tab);
  }

  async function applyPunch(tab) {
    if (!tab || !tab.punching || tab.busy || punchSelectionCount(tab) < 1) return;
    const chatId = activeWorkspaceId();
    const path = tab.path;
    tab.busy = true;
    tab.note = "";
    paintEditorHead();
    try {
      const data = await TabbyUI.api(`workspace/${encodeURIComponent(chatId)}/punch`, {
        method: "POST",
        body: {
          path,
          seeds: tab.punchSeeds || [],
          boxes: (tab.punchBoxes || []).map((box) => ({
            x: box.x,
            y: box.y,
            width: box.w,
            height: box.h,
          })),
          tolerance: tab.punchTolerance ?? PUNCH_TOLERANCE_DEFAULT,
          contiguous: tab.punchContiguous !== false,
        },
      });
      if (chatId !== activeWorkspaceId()) return;
      const written = data.path || path;
      tab.busy = false;
      clearPunchState(tab);
      if (punchResize) {
        punchResize.disconnect();
        punchResize = null;
      }
      if (written !== path) retargetPath(path, written);
      applyListing(data);
      const live = findTab(written) || tab;
      const saved = filesListing.find((item) => item.path === written);
      live.size = saved ? Number(saved.size) || Number(data.bytes) || live.size : Number(data.bytes) || live.size;
      live.state = "image";
      live.kind = "image";
      live.rev += 1;
      const n = Number(data.punched) || 0;
      live.note = n ? `Made ${n.toLocaleString()} pixels transparent.` : "Made transparent.";
      (data.rewritten || []).forEach((rel) => {
        const other = findTab(rel);
        if (!other || other.dirty) return;
        other.state = "loading";
        other.loading = false;
        other.rev += 1;
        ensureTabLoaded(other);
      });
      reloadPreviewIfNeeded();
      if (editorPane) editorPane.dataset.key = "";
      paintTabsAndFiles();
    } catch (err) {
      tab.busy = false;
      tab.note = err.message;
      paintEditorHead();
    }
  }

  async function saveTab() {
    const tab = activeTabRow();
    stashEditor();
    if (!tab || !tab.dirty || tab.busy) return;
    const path = isHistoryTab(tab) ? tab.filePath : tab.path;
    if (!path) return;
    const contents = tab.text;
    const chatId = activeWorkspaceId();
    tab.busy = true;
    tab.note = "";
    paintEditorHead();
    try {
      const data = await TabbyUI.api(
        `workspace/${encodeURIComponent(chatId)}/file?path=${encodeURIComponent(path)}`,
        { method: "PUT", body: { contents } }
      );
      tab.busy = false;
      if (chatId !== activeWorkspaceId()) return;
      filesListing = Array.isArray(data.files) ? data.files : filesListing;
      filesEntry = typeof data.entry === "string" ? data.entry : filesEntry;
      const live = findTab(path) || tab;
      live.original = contents;
      live.text = contents;
      live.dirty = false;
      live.gone = false;
      live.note = "Saved.";
      tab.original = contents;
      tab.text = contents;
      tab.dirty = false;
      tab.note = "Saved.";
      const saved = filesListing.find((item) => item.path === path);
      live.size = saved ? Number(saved.size) || 0 : live.size;
      noteChange(path, true);
      queueDrafts();
      reloadPreviewIfNeeded(path);
      if (window.TabbyLsp) window.TabbyLsp.didSave(path, contents);
      paintFilesHead();
      paintFilesTree();
      paintTabs();
      paintEditorHead();
      paintFilesChanges();
      refreshHistory();
    } catch (err) {
      tab.busy = false;
      tab.note = err.message;
      paintEditorHead();
    }
  }

  function revertTabAt(path) {
    const tab = findTab(path);
    if (!tab || isHistoryTab(tab) || !tab.dirty) return;
    tab.dirty = false;
    tab.note = "";
    tab.caret = null;
    tab.text = tab.original || "";
    queueDrafts();
    if (window.TabbyLsp) window.TabbyLsp.didChange(tab.path, tab.text);
    if (activeTab === tab.path && window.TabbyMonaco && window.TabbyMonaco.getEditor()) {
      window.TabbyMonaco.setValue(tab.text);
      paintEditorHead();
      paintTabs();
      paintFilesChanges();
      return;
    }
    if (activeTab === tab.path) {
      tab.state = "loading";
      paintTabs();
      paintView();
      return;
    }
    paintTabs();
    paintFilesChanges();
  }

  function revertTab() {
    const tab = activeTabRow();
    if (!tab || isHistoryTab(tab)) return;
    revertTabAt(tab.path);
  }

  async function openSite() {
    const row = selectedRow();
    const wanted = row && row.page ? row.path : "";
    if (!filesEntry && !wanted) return;
    const chatId = activeWorkspaceId();
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

  function collectDrafts(chatId) {
    stashEditor();
    const saved = chatId && tabsByChat[chatId];
    const list = saved ? saved.openTabs : openTabs;
    const tabs = [];
    const seen = new Set();
    (list || []).forEach((tab) => {
      if (!tab) return;
      const path = isHistoryTab(tab) ? tab.filePath || tab.path : tab.path;
      if (!tab.dirty || !TEXT_SUFFIXES.has(fileSuffix(path))) return;
      if (seen.has(path)) return;
      seen.add(path);
      tabs.push({
        path,
        text: String(tab.text || ""),
        caret: Array.isArray(tab.caret) ? tab.caret : undefined,
      });
    });
    return tabs;
  }

  function queueDrafts() {
    if (draftsTimer) clearTimeout(draftsTimer);
    draftsTimer = setTimeout(() => {
      draftsTimer = 0;
      flushDrafts();
    }, 800);
  }

  function flushDrafts(keepalive) {
    const chatId = tabsChat || activeWorkspaceId();
    if (!chatId) return;
    stashCurrentTabs();
    const drafts = collectDrafts(chatId);
    const body = JSON.stringify({ drafts });
    const url = TabbyUI.path(`workspace/${encodeURIComponent(chatId)}/drafts`);
    if (keepalive) {
      fetch(url, {
        method: "PUT",
        body,
        credentials: "same-origin",
        keepalive: true,
        headers: { "Content-Type": "application/json", Accept: "application/json" },
      }).catch(() => {});
      return;
    }
    TabbyUI.api(`workspace/${encodeURIComponent(chatId)}/drafts`, {
      method: "PUT",
      body: { drafts },
    }).catch(() => {});
  }

  async function loadDrafts(chatId) {
    if (!chatId || activeMode() !== "code") return;
    try {
      const data = await TabbyUI.api(`workspace/${encodeURIComponent(chatId)}/drafts`);
      const drafts = Array.isArray(data.drafts) ? data.drafts : [];
      drafts.forEach((draft) => {
        if (!draft || !draft.path || typeof draft.text !== "string") return;
        if (!TEXT_SUFFIXES.has(fileSuffix(draft.path))) return;
        let tab = findTab(draft.path);
        if (!tab) {
          const row = filesListing.find((item) => item.path === draft.path);
          openTabs.push({
            path: draft.path,
            text: draft.text,
            original: "",
            dirty: true,
            // rev > 0 keeps the draft on screen while the disk copy loads.
            state: "loading",
            rev: 1,
            size: row ? Number(row.size) || 0 : 0,
            kind: (row && row.kind) || "text",
            editable: true,
            busy: false,
            note: "",
            gone: !row,
            caret: Array.isArray(draft.caret) ? draft.caret : null,
            scrollTop: 0,
            scrollLeft: 0,
          });
          tab = findTab(draft.path);
        } else if (!tab.dirty) {
          tab.text = draft.text;
          tab.dirty = tab.text !== tab.original;
          if (Array.isArray(draft.caret)) tab.caret = draft.caret;
        }
      });
      draftsChat = chatId;
      if (drafts.length) {
        syncTabs();
        paintTabsAndFiles();
      }
    } catch {
      /* drafts are optional */
    }
  }

  function previewSuffix(path) {
    return [".html", ".htm", ".css", ".js", ".mjs"].includes(fileSuffix(path));
  }

  function nextBrowserTabId() {
    browserTabSeq += 1;
    return `bt${browserTabSeq}`;
  }

  function activeBrowserTabRow() {
    return browserTabs.find((tab) => tab.id === activeBrowserTab) || null;
  }

  function setPreviewRootFromHref(href) {
    try {
      const url = new URL(href, window.location.href);
      const match = url.pathname.match(/^(.*\/code\/[^/]+\/[^/]+\/[^/]+\/)/);
      if (!match) return "";
      previewRoot = `${url.origin}${match[1]}`;
      return previewRoot;
    } catch {
      return "";
    }
  }

  function pathFromPreviewHref(href) {
    if (!href || href === "about:blank") return "";
    try {
      const url = new URL(href, window.location.href);
      if (!previewRoot) setPreviewRootFromHref(href);
      if (!previewRoot) return "";
      const root = new URL(previewRoot, window.location.href);
      if (url.origin !== root.origin || !url.pathname.startsWith(root.pathname)) return "";
      return decodeURIComponent(url.pathname.slice(root.pathname.length)).replace(/^\//, "");
    } catch {
      return "";
    }
  }

  function hrefFromPreviewPath(path) {
    if (!previewRoot) return "";
    return new URL(String(path || "").replace(/^\//, ""), previewRoot).href;
  }

  function browserTabLabel(tab) {
    if (!tab) return "New tab";
    if (tab.title && tab.title !== "New tab") return tab.title;
    if (tab.path) return fileBase(tab.path);
    if (tab.url && tab.url !== "about:blank") {
      try {
        return new URL(tab.url, window.location.href).hostname || tab.url;
      } catch {
        return tab.url;
      }
    }
    return "New tab";
  }

  function browserAddressValue(tab) {
    if (!tab) return "";
    if (tab.path) return tab.path;
    if (tab.url && tab.url !== "about:blank") return tab.url;
    return "";
  }

  function restoreBrowserTabList(rows, activeId) {
    blankPreviewFrame();
    browserTabs = [];
    activeBrowserTab = "";
    (rows || []).forEach((row) => {
      if (!row) return;
      const id = row.id || nextBrowserTabId();
      const num = Number(String(id).replace(/^bt/, ""));
      if (Number.isFinite(num) && num >= browserTabSeq) browserTabSeq = num;
      browserTabs.push({
        id,
        path: row.path || "",
        title: row.title || "",
        url: row.url || "",
        frame: null,
      });
    });
    activeBrowserTab = activeId && browserTabs.some((tab) => tab.id === activeId)
      ? activeId
      : (browserTabs[0] ? browserTabs[0].id : "");
  }

  function paintBrowserChrome() {
    if (previewTabsEl) {
      const ids = browserTabs.map((tab) => tab.id).join("\0");
      const rebuilt = previewTabsEl.dataset.ids !== ids || previewTabsEl.dataset.active !== activeBrowserTab;
      if (rebuilt) {
        const frag = document.createDocumentFragment();
        browserTabs.forEach((tab) => {
          const item = document.createElement("div");
          const name = browserTabLabel(tab);
          item.className = "chat-preview-tab" + (tab.id === activeBrowserTab ? " is-active" : "");
          item.dataset.btab = tab.id;
          item.setAttribute("role", "tab");
          item.setAttribute("aria-selected", tab.id === activeBrowserTab ? "true" : "false");
          item.innerHTML =
            `<button type="button" class="chat-preview-tab-open" title="${TabbyUI.escapeHtml(tab.path || tab.url || name)}">${TabbyUI.escapeHtml(name)}</button>` +
            `<button type="button" class="chat-preview-tab-close" data-btab-close aria-label="Close ${TabbyUI.escapeHtml(name)}">×</button>`;
          frag.appendChild(item);
        });
        previewTabsEl.replaceChildren(frag);
        previewTabsEl.dataset.ids = ids;
        previewTabsEl.dataset.active = activeBrowserTab;
        const current = previewTabsEl.querySelector(".chat-preview-tab.is-active");
        if (current) current.scrollIntoView({ inline: "nearest", block: "nearest" });
      } else {
        browserTabs.forEach((tab) => {
          const item = previewTabsEl.querySelector(`[data-btab="${tab.id}"]`);
          if (!item) return;
          const name = browserTabLabel(tab);
          const btn = item.querySelector(".chat-preview-tab-open");
          if (btn && btn.textContent !== name) {
            btn.textContent = name;
            btn.title = tab.path || tab.url || name;
          }
        });
      }
    }
    if (previewUrlInput && document.activeElement !== previewUrlInput) {
      previewUrlInput.value = browserAddressValue(activeBrowserTabRow());
    }
    browserTabs.forEach((tab) => {
      if (tab.frame) tab.frame.classList.toggle("is-idle", tab.id !== activeBrowserTab);
    });
  }

  function ensureBrowserFrame(tab) {
    if (!tab) return null;
    if (tab.frame && tab.frame.isConnected) return tab.frame;
    const frame = document.createElement("iframe");
    frame.title = "Site preview";
    frame.sandbox = PREVIEW_SANDBOX;
    frame.dataset.btab = tab.id;
    frame.classList.toggle("is-idle", tab.id !== activeBrowserTab);
    if (previewFrames) previewFrames.appendChild(frame);
    tab.frame = frame;
    return frame;
  }

  function loadBrowserTab(tab, spec) {
    if (!tab) return;
    spec = spec || {};
    tab.url = spec.url || "";
    if (spec.path != null) tab.path = spec.path;
    if (spec.title) tab.title = spec.title;
    else if (tab.path) tab.title = fileBase(tab.path);
    const frame = ensureBrowserFrame(tab);
    frame.src = tab.url || "about:blank";
    if (tab.id === activeBrowserTab) previewUrl = tab.url;
    paintBrowserChrome();
  }

  function activateBrowserTab(id) {
    const tab = browserTabs.find((item) => item.id === id);
    if (!tab) return;
    activeBrowserTab = tab.id;
    previewUrl = tab.url || "";
    paintBrowserChrome();
  }

  function addBrowserTab(spec) {
    spec = spec || {};
    const tab = {
      id: nextBrowserTabId(),
      path: spec.path || "",
      title: spec.title || (spec.path ? fileBase(spec.path) : "New tab"),
      url: spec.url || "",
      frame: null,
    };
    const at = browserTabs.findIndex((item) => item.id === activeBrowserTab);
    browserTabs.splice(at >= 0 ? at + 1 : browserTabs.length, 0, tab);
    activeBrowserTab = tab.id;
    if (tab.url) loadBrowserTab(tab, spec);
    else {
      ensureBrowserFrame(tab);
      previewUrl = "";
      paintBrowserChrome();
      if (previewUrlInput) {
        previewUrlInput.value = "";
        previewUrlInput.focus();
        previewUrlInput.select();
      }
    }
    return tab;
  }

  function closeBrowserTab(id) {
    const at = browserTabs.findIndex((tab) => tab.id === id);
    if (at < 0) return;
    const tab = browserTabs[at];
    if (tab.frame) tab.frame.remove();
    browserTabs.splice(at, 1);
    if (!browserTabs.length) {
      hidePreview();
      return;
    }
    if (activeBrowserTab === id) {
      const next = browserTabs[at] || browserTabs[at - 1];
      activeBrowserTab = next.id;
      previewUrl = next.url || "";
    }
    paintBrowserChrome();
  }

  function newBlankBrowserTab() {
    if (!previewOpen) return;
    addBrowserTab({});
  }

  function postToActivePreview(kind) {
    const tab = activeBrowserTabRow();
    if (!tab || !tab.frame || !tab.frame.contentWindow) return;
    tab.frame.contentWindow.postMessage({ source: "tabby-preview-host", kind }, "*");
  }

  function safePreviewHref(href) {
    const text = String(href || "").trim();
    if (!text) return "";
    const lower = text.toLowerCase();
    if (lower.startsWith("javascript:") || lower.startsWith("vbscript:")) return "";
    return text;
  }

  function looksLikeUrl(text) {
    return /^(https?:|about:|data:|blob:)/i.test(text);
  }

  async function mintPreview(wanted) {
    const chatId = activeWorkspaceId();
    if (!chatId) return { href: "", path: "" };
    const data = await TabbyUI.api(`workspace/${encodeURIComponent(chatId)}/preview`, {
      method: "POST",
      body: { path: wanted || "" },
    });
    const href = new URL(TabbyUI.path(data.url), window.location.href).href;
    setPreviewRootFromHref(href);
    return { href, path: data.path || wanted || "" };
  }

  async function mintPreviewUrl(wanted) {
    const minted = await mintPreview(wanted);
    return minted.href;
  }

  async function openPreviewHref(href, opts) {
    opts = opts || {};
    const raw = safePreviewHref(href);
    if (!raw) {
      if (opts.newTab) addBrowserTab({});
      return;
    }
    let url = raw;
    try {
      url = new URL(raw, previewRoot || window.location.href).href;
    } catch {
      url = raw;
    }
    const path = pathFromPreviewHref(url);
    const spec = {
      url,
      path,
      title: path ? fileBase(path) : browserTabLabel({ url, path, title: "" }),
    };
    if (opts.newTab || !activeBrowserTabRow()) addBrowserTab(spec);
    else loadBrowserTab(activeBrowserTabRow(), spec);
  }

  async function goPreviewAddress(raw) {
    const text = String(raw || "").trim();
    let tab = activeBrowserTabRow();
    if (!tab) tab = addBrowserTab({});
    if (!text) {
      loadBrowserTab(tab, { url: "about:blank", path: "", title: "New tab" });
      return;
    }
    if (looksLikeUrl(text)) {
      await openPreviewHref(text);
      return;
    }
    try {
      if (!previewRoot) await mintPreview(text);
      const path = text.replace(/^\//, "");
      const href = hrefFromPreviewPath(path) || (await mintPreview(path)).href;
      loadBrowserTab(tab, { url: href, path, title: fileBase(path) });
    } catch (err) {
      addBubble("assistant", `Error: ${err.message}`);
    }
  }

  function previewPagePath(explicit) {
    if (explicit) return explicit;
    const row = selectedRow();
    if (row && row.page) return row.path;
    return filesEntry || "";
  }

  function ensurePreviewTab() {
    if (findTab(PREVIEW_TAB)) return;
    openTabs.push({
      path: PREVIEW_TAB,
      kind: "preview",
      state: "ready",
      rev: 0,
      original: "",
      text: "",
      dirty: false,
      busy: false,
      note: "",
      gone: false,
    });
  }

  function blankPreviewFrame() {
    previewUrl = "";
    browserTabs.forEach((tab) => {
      if (tab.frame) {
        tab.frame.src = "about:blank";
        tab.frame.remove();
        tab.frame = null;
      }
    });
    if (previewFrames) previewFrames.replaceChildren();
  }

  function clearBrowserTabs() {
    blankPreviewFrame();
    browserTabs = [];
    activeBrowserTab = "";
    previewRoot = "";
    if (previewTabsEl) {
      previewTabsEl.replaceChildren();
      previewTabsEl.dataset.ids = "";
      previewTabsEl.dataset.active = "";
    }
    if (previewUrlInput) previewUrlInput.value = "";
  }

  function dockPreview() {
    if (!previewOpen) return;
    const other = [...openTabs].reverse().find((item) => !isPreviewTab(item));
    activateTab(other ? other.path : "");
  }

  function browserTabNeedsLoad(tab) {
    if (!tab || !tab.path && !tab.url) return false;
    if (!tab.frame) return true;
    const src = tab.frame.getAttribute("src") || "";
    return !src || src === "about:blank";
  }

  async function ensurePreviewLoaded() {
    if (!previewOpen || !findTab(PREVIEW_TAB)) return;
    const pending = browserTabs.filter((tab) => browserTabNeedsLoad(tab));
    if (!pending.length && browserTabs.length) return;
    try {
      if (!browserTabs.length) {
        const wanted = previewPagePath();
        if (!filesEntry && !wanted) return;
        const minted = await mintPreview(wanted);
        if (!previewOpen) return;
        addBrowserTab({ path: minted.path, url: minted.href, title: fileBase(minted.path) });
        return;
      }
      const seed = pending.find((tab) => tab.path) || pending[0];
      if (!previewRoot) await mintPreview(seed.path || "");
      if (!previewOpen) return;
      pending.forEach((tab) => {
        const href = tab.path ? hrefFromPreviewPath(tab.path) : tab.url;
        if (!href) return;
        loadBrowserTab(tab, {
          url: href,
          path: tab.path || pathFromPreviewHref(href),
          title: tab.title || (tab.path ? fileBase(tab.path) : ""),
        });
      });
    } catch (err) {
      addBubble("assistant", `Error: ${err.message}`);
    }
  }

  async function showPreview(opts) {
    opts = opts || {};
    const wanted = previewPagePath(opts.path);
    if (!filesEntry && !wanted) {
      addBubble("assistant", "Error: No page to open yet. Ask for an HTML file first.");
      return;
    }
    const chatId = activeWorkspaceId();
    try {
      const minted = await mintPreview(wanted);
      if (chatId !== activeWorkspaceId()) return;
      const spec = { path: minted.path, url: minted.href, title: fileBase(minted.path) };
      previewOpen = true;
      ensurePreviewTab();
      if (previewPane) previewPane.hidden = false;
      if (opts.newTab && browserTabs.length) addBrowserTab(spec);
      else if (!browserTabs.length) addBrowserTab(spec);
      else loadBrowserTab(activeBrowserTabRow(), spec);
      if (filesPreviewBtn) filesPreviewBtn.classList.add("is-on");
      paintTabsAndFiles();
    } catch (err) {
      addBubble("assistant", `Error: ${err.message}`);
    }
  }

  function hidePreview() {
    const at = openTabs.findIndex((tab) => isPreviewTab(tab));
    if (at >= 0) {
      if (activeTab === PREVIEW_TAB) {
        const next = openTabs[at + 1] || openTabs[at - 1] || null;
        activeTab = next ? next.path : "";
        if (editorPane) editorPane.dataset.key = "";
      }
      openTabs.splice(at, 1);
    }
    previewOpen = false;
    clearBrowserTabs();
    if (previewPane) {
      previewPane.hidden = true;
      previewPane.classList.remove("is-tab");
    }
    if (filesPreviewBtn) filesPreviewBtn.classList.remove("is-on");
    paintTabsAndFiles();
  }

  function reloadBrowserTab(tab) {
    if (!tab || !tab.frame) return;
    const url = tab.url || tab.frame.getAttribute("src") || "";
    if (!url || url === "about:blank") return;
    tab.frame.src = "about:blank";
    setTimeout(() => {
      if (previewOpen && tab.frame) tab.frame.src = url;
    }, 30);
  }

  function reloadPreviewIfNeeded(path) {
    if (!previewOpen || !browserTabs.length) return;
    if (path && !previewSuffix(path)) return;
    const suffix = path ? fileSuffix(path) : "";
    const all = !path || suffix === ".css" || suffix === ".js" || suffix === ".mjs";
    browserTabs.forEach((tab) => {
      if (all || !tab.path || tab.path === path) reloadBrowserTab(tab);
    });
  }

  function onPreviewMessage(event) {
    const data = event.data;
    if (!data || data.source !== "tabby-preview") return;
    const tab = browserTabs.find((item) => item.frame && item.frame.contentWindow === event.source);
    if (!tab) return;
    if (data.kind === "open") {
      openPreviewHref(data.href, { newTab: true });
      return;
    }
    if (data.href) {
      tab.url = data.href;
      tab.path = pathFromPreviewHref(data.href);
    }
    if (data.title) tab.title = data.title;
    else if (tab.path) tab.title = fileBase(tab.path);
    if (tab.id === activeBrowserTab) previewUrl = tab.url || "";
    paintBrowserChrome();
  }

  function previewHasFocus(target) {
    if (!previewOpen || !previewPane) return false;
    if (target && previewPane.contains(target)) return true;
    return isPreviewTab(activeTabRow()) && !(target && target.closest(".chat-compose, #chat-editor, textarea, input"));
  }

  function wsUrl(suffix) {
    const href = new URL(TabbyUI.path(suffix), window.location.href);
    href.protocol = href.protocol === "https:" ? "wss:" : "ws:";
    return href.href;
  }

  function fitTerm() {
    if (termFit && termTerm) {
      try {
        termFit.fit();
      } catch {
        /* ignore */
      }
    }
    if (termSocket && termSocket.readyState === 1 && termTerm) {
      termSocket.send(JSON.stringify({ type: "resize", cols: termTerm.cols, rows: termTerm.rows }));
    }
  }

  function waitSocketClosed(socket) {
    if (!socket || socket.readyState === 3) return Promise.resolve();
    return new Promise((resolve) => {
      let settled = false;
      const done = () => {
        if (settled) return;
        settled = true;
        resolve();
      };
      socket.addEventListener("close", done);
      socket.addEventListener("error", done);
      try {
        if (socket.readyState < 2) socket.close();
      } catch {
        done();
        return;
      }
      window.setTimeout(done, 2000);
    });
  }

  function disposeTermClient() {
    const socket = termSocket;
    termSocket = null;
    if (socket) {
      socket.onopen = null;
      socket.onmessage = null;
      socket.onclose = null;
      socket.onerror = null;
    }
    const wait = waitSocketClosed(socket);
    if (termTerm) {
      try {
        termTerm.dispose();
      } catch {
        /* ignore */
      }
      termTerm = null;
      termFit = null;
    }
    if (termHost) termHost.replaceChildren();
    return wait;
  }

  function closeTerm() {
    termWanted = false;
    termGen += 1;
    termOpen = false;
    if (termPane) termPane.hidden = true;
    if (filesTermBtn) filesTermBtn.classList.remove("is-on");
    disposeTermClient();
    if (termNote) termNote.textContent = "";
  }

  function termTheme() {
    const css = window.TabbyUI && TabbyUI.cssVar ? TabbyUI.cssVar.bind(TabbyUI) : (name) =>
      getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return {
      background: css("--bg") || "#0b0d12",
      foreground: css("--text") || "#e8ecf4",
      cursor: css("--accent") || "#7aa2ff",
    };
  }

  document.addEventListener("tabby-theme-change", () => {
    if (termTerm) termTerm.options.theme = termTheme();
  });

  function termFontSize() {
    const z = window.TabbyUI && TabbyUI.getZoom ? TabbyUI.getZoom() / 100 : 1;
    return Math.max(8, Math.round(12 * z));
  }

  function connectTerm(chatId, gen, retries) {
    if (termGen !== gen || !termWanted || !chatId) return;
    if (typeof window.Terminal !== "function") {
      if (termNote) termNote.textContent = "xterm.js is missing.";
      return;
    }
    if (termNote) termNote.textContent = retries ? "Reconnecting…" : "";
    termTerm = new window.Terminal({
      cursorBlink: true,
      fontSize: termFontSize(),
      fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
      theme: termTheme(),
    });
    if (window.FitAddon && window.FitAddon.FitAddon) {
      termFit = new window.FitAddon.FitAddon();
      termTerm.loadAddon(termFit);
    }
    termTerm.open(termHost);
    termTerm.onData((data) => {
      if (termSocket && termSocket.readyState === 1) termSocket.send(new TextEncoder().encode(data));
    });
    const socket = new WebSocket(wsUrl(`workspace/${encodeURIComponent(chatId)}/shell`));
    termSocket = socket;
    let fatal = false;
    socket.binaryType = "arraybuffer";
    socket.onopen = () => {
      if (termGen !== gen || termSocket !== socket) return;
      if (termNote && termNote.textContent === "Reconnecting…") termNote.textContent = "";
      fitTerm();
      if (termTerm) termTerm.focus();
    };
    socket.onmessage = (event) => {
      if (termGen !== gen || termSocket !== socket || !termTerm) return;
      if (typeof event.data === "string") {
        try {
          const payload = JSON.parse(event.data);
          if (payload && payload.type === "error") {
            fatal = true;
            if (termNote) termNote.textContent = payload.message || "install docker";
            termTerm.write(`\r\n${payload.message || "install docker"}\r\n`);
          }
        } catch {
          termTerm.write(event.data);
        }
        return;
      }
      if (termNote && termNote.textContent === "Reconnecting…") termNote.textContent = "";
      termTerm.write(new Uint8Array(event.data));
    };
    socket.onclose = () => {
      if (termGen !== gen || termSocket !== socket) return;
      termSocket = null;
      if (!termWanted || fatal) {
        if (termWanted && termNote && !termNote.textContent) termNote.textContent = "Disconnected.";
        return;
      }
      const next = (retries || 0) + 1;
      if (next > 8) {
        if (termNote) termNote.textContent = "Disconnected.";
        return;
      }
      if (termNote) termNote.textContent = "Reconnecting…";
      window.setTimeout(() => {
        if (termGen !== gen || !termWanted) return;
        disposeTermClient().then(() => connectTerm(activeWorkspaceId(), gen, next));
      }, Math.min(120 * next, 800));
    };
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        if (termGen !== gen || termSocket !== socket) return;
        fitTerm();
        if (termTerm) termTerm.focus();
      });
    });
  }

  function openTerm() {
    const chatId = activeWorkspaceId();
    if (!chatId) return;
    const gen = ++termGen;
    termWanted = true;
    termOpen = true;
    if (termPane) termPane.hidden = false;
    setTermH(termH, false);
    if (filesTermBtn) filesTermBtn.classList.add("is-on");
    if (typeof window.Terminal !== "function") {
      if (termNote) termNote.textContent = "xterm.js is missing.";
      return;
    }
    disposeTermClient().then(() => {
      if (termGen !== gen || !termWanted) return;
      connectTerm(chatId, gen, 0);
    });
  }

  function toggleTerm() {
    if (termOpen) closeTerm();
    else openTerm();
  }

  function collectEditorFindHits(query) {
    const tab = activeTabRow();
    const box = editorBox();
    const text = box ? box.value : tab && tab.text;
    const needle = String(query || "").toLowerCase();
    if (!needle || text == null) return [];
    const hay = String(text).toLowerCase();
    const hits = [];
    let from = 0;
    while (from <= hay.length) {
      const at = hay.indexOf(needle, from);
      if (at < 0) break;
      hits.push([at, at + needle.length]);
      from = at + Math.max(1, needle.length);
      if (hits.length > 400) break;
    }
    return hits;
  }

  function paintEditorFindBar() {
    if (!editorFindCountEl) return;
    if (!editorFindQuery) {
      editorFindCountEl.textContent = "";
      return;
    }
    editorFindCountEl.textContent = editorFindHits.length
      ? `${editorFindIndex + 1} / ${editorFindHits.length}`
      : "0 / 0";
  }

  function revealEditorFindHit(index) {
    const box = editorBox();
    if (!box || !editorFindHits.length) {
      paintEditorFindBar();
      return;
    }
    editorFindIndex = ((index % editorFindHits.length) + editorFindHits.length) % editorFindHits.length;
    const [start, end] = editorFindHits[editorFindIndex];
    box.focus();
    box.setSelectionRange(start, end);
    const line = box.value.slice(0, start).split("\n").length;
    const lineH = parseFloat(getComputedStyle(box).lineHeight) || 18;
    box.scrollTop = Math.max(0, (line - 3) * lineH);
    paintEditorFindBar();
    queueHighlight();
  }

  function runEditorFind(query, jump) {
    editorFindQuery = String(query || "");
    editorFindHits = collectEditorFindHits(editorFindQuery);
    editorFindIndex = 0;
    paintEditorFindBar();
    if (jump !== false && editorFindHits.length) revealEditorFindHit(0);
    else queueHighlight();
  }

  function openEditorFind() {
    if (window.TabbyMonaco && window.TabbyMonaco.getEditor()) {
      window.TabbyMonaco.find();
      return;
    }
    if (editorFindBar) editorFindBar.hidden = false;
    if (editorFindInput) {
      editorFindInput.focus();
      editorFindInput.select();
      runEditorFind(editorFindInput.value);
    }
  }

  function closeEditorFind() {
    editorFindQuery = "";
    editorFindHits = [];
    editorFindIndex = 0;
    if (editorFindBar) editorFindBar.hidden = true;
    if (editorFindInput) editorFindInput.value = "";
    paintEditorFindBar();
    queueHighlight();
  }

  let filesRefreshTimer = 0;

  function noteNewListingFiles(prev, next) {
    if (!inFlight || !chatsShareWorkspace(flightChatId)) return;
    const before = new Set(
      (prev || [])
        .filter((row) => row && row.kind !== "dir")
        .map((row) => String(row.path || "").replace(/^\/+/, ""))
        .filter(Boolean)
    );
    (next || []).forEach((row) => {
      if (!row || row.kind === "dir") return;
      const path = String(row.path || "").replace(/^\/+/, "");
      if (!path || before.has(path)) return;
      noteChange(path, true);
    });
  }

  async function refreshFiles() {
    const chatId = activeWorkspaceId();
    if (tabsChat !== chatId) {
      switchWorkspaceTabs(chatId);
    }
    if (activeMode() !== "code" || !chatId) {
      filesListing = [];
      filesSelected = "";
      filesEntry = "";
      paintFiles();
      return;
    }
    try {
      const data = await TabbyUI.api(`workspace/${encodeURIComponent(chatId)}`);
      if (chatId !== activeWorkspaceId()) return;
      const prev = filesListing;
      filesListing = Array.isArray(data.files) ? data.files : [];
      filesEntry = typeof data.entry === "string" ? data.entry : "";
      noteNewListingFiles(prev, filesListing);
      if (filesSelected && !filesListing.some((row) => row.path === filesSelected)) {
        filesSelected = "";
      }
      rememberCurrentListing(chatId);
    } catch {
      if (chatId !== activeWorkspaceId()) return;
      // A 502 during GPU switch used to wipe a good listing. Keep it.
    }
    paintFiles();
    if (chatId && draftsChat !== chatId) loadDrafts(chatId);
    if (window.TabbyLsp && chatId) window.TabbyLsp.setChat(chatId);
    if (previewOpen) ensurePreviewLoaded();
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
  let pinningLog = false;
  let pinLogRaf = 0;

  function nearBottom() {
    return log.scrollHeight - log.scrollTop - log.clientHeight < 96;
  }

  function paintJump() {
    if (!jumpBtn) return;
    const overflow = log.scrollHeight > log.clientHeight + 8;
    jumpBtn.hidden = !overflow || followLog || nearBottom();
  }

  function pinLogNow() {
    pinningLog = true;
    log.scrollTop = log.scrollHeight;
    pinningLog = false;
  }

  function stickLog(force) {
    if (force) followLog = true;
    if (!followLog) {
      paintJump();
      return;
    }
    pinLogNow();
    if (pinLogRaf) cancelAnimationFrame(pinLogRaf);
    pinLogRaf = requestAnimationFrame(() => {
      pinLogRaf = requestAnimationFrame(() => {
        pinLogRaf = 0;
        if (followLog) pinLogNow();
        paintJump();
      });
    });
  }

  const logSizeObs = window.ResizeObserver
    ? new ResizeObserver(() => {
        if (followLog) stickLog();
        else paintJump();
      })
    : null;
  if (logSizeObs) logSizeObs.observe(log);

  function watchLogChild(node) {
    if (logSizeObs && node) logSizeObs.observe(node);
  }

  function resizeInput() {
    const maxH = composeMax();
    if (composeH > 0) {
      input.style.height = `${Math.min(composeH, maxH)}px`;
      input.style.maxHeight = `${maxH}px`;
    } else {
      input.style.maxHeight = `${maxH}px`;
      input.style.height = "auto";
      const minH = parseFloat(getComputedStyle(input).minHeight) || 0;
      input.style.height = `${Math.min(Math.max(input.scrollHeight, minH), maxH)}px`;
    }
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

  function hideFilesMoreMenu() {
    if (!filesMoreMenu || !filesMoreBtn) return;
    filesMoreMenu.hidden = true;
    filesMoreBtn.setAttribute("aria-expanded", "false");
  }

  function hideUploadMenu() {
    if (!filesUploadMenu || !filesUploadBtn) return;
    filesUploadMenu.hidden = true;
    filesUploadBtn.setAttribute("aria-expanded", "false");
  }

  function hidePopovers() {
    hideMoreMenu();
    hideFilesMoreMenu();
    hideAttachMenu();
    hideUploadMenu();
    hideAgentMenu();
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
    reclampPaneWidths();
  }

  function reclampPaneWidths() {
    if (isNarrowChat()) return;
    setPaneWidth("sidebar", sidebarW, false);
    setPaneWidth("files", filesW, false);
    setPreviewW(previewW, false);
    setTermH(termH, false);
    if (composeH > 0) setComposeH(composeH, false);
  }

  function applyPaneWidths() {
    shell.style.setProperty("--chat-sidebar-w", `${sidebarW}px`);
    shell.style.setProperty("--chat-files-w", `${filesW}px`);
    shell.style.setProperty("--chat-preview-w", `${previewW}%`);
    shell.style.setProperty("--chat-term-h", `${termH}px`);
    const sideHandle = root.querySelector("#chat-sidebar-resize");
    const filesHandle = root.querySelector("#chat-files-resize");
    const previewHandle = root.querySelector("#chat-preview-resize");
    const termHandle = root.querySelector("#chat-term-resize");
    if (sideHandle) sideHandle.setAttribute("aria-valuenow", String(sidebarW));
    if (filesHandle) filesHandle.setAttribute("aria-valuenow", String(filesW));
    if (previewHandle) previewHandle.setAttribute("aria-valuenow", String(previewW));
    if (termHandle) termHandle.setAttribute("aria-valuenow", String(termH));
    if (window.TabbyMonaco) window.TabbyMonaco.layout();
    if (termOpen) fitTerm();
  }

  function persistPaneWidth(key, value) {
    try {
      localStorage.setItem(key, String(value));
    } catch {
      /* ignore */
    }
  }

  function clampPaneWidth(which, next) {
    const shellW = shell.clientWidth || 0;
    const leftOn = !isNarrowChat() && !shell.classList.contains("is-sidebar-hidden");
    const rightOn = !isNarrowChat() && filesPane && !filesPane.hidden;
    const other = which === "sidebar"
      ? (rightOn ? filesW : 0)
      : (leftOn ? sidebarW : 0);
    const min = which === "sidebar" ? SIDEBAR_W_MIN : FILES_W_MIN;
    const max = which === "sidebar" ? SIDEBAR_W_MAX : FILES_W_MAX;
    const room = Math.max(min, shellW - other - CHAT_COL_MIN);
    return Math.round(Math.min(max, room, Math.max(min, next)));
  }

  function setPaneWidth(which, next, persist) {
    const width = clampPaneWidth(which, next);
    if (which === "sidebar") sidebarW = width;
    else filesW = width;
    applyPaneWidths();
    if (persist) persistPaneWidth(which === "sidebar" ? SIDEBAR_W_KEY : FILES_W_KEY, width);
    return width;
  }

  function stageEl() {
    return root.querySelector("#chat-stage-main") || root.querySelector("#chat-stage");
  }

  function clampPreviewPct(next) {
    const stageW = stageEl() ? stageEl().clientWidth : 0;
    const minMain = 160;
    const minPrev = 180;
    let lo = PREVIEW_W_MIN;
    let hi = PREVIEW_W_MAX;
    if (stageW >= minMain + minPrev) {
      lo = Math.max(lo, (minPrev / stageW) * 100);
      hi = Math.min(hi, ((stageW - minMain) / stageW) * 100);
    }
    return Math.round(Math.min(hi, Math.max(lo, next)));
  }

  function setPreviewW(next, persist) {
    previewW = clampPreviewPct(next);
    applyPaneWidths();
    if (persist) persistPaneWidth(PREVIEW_W_KEY, previewW);
    return previewW;
  }

  function termMax() {
    const view = root.querySelector(".chat-view");
    const h = view ? view.clientHeight : 0;
    return Math.max(TERM_H_MIN, Math.floor((h || 480) * 0.72));
  }

  function setTermH(next, persist) {
    termH = Math.round(Math.min(termMax(), Math.max(TERM_H_MIN, next)));
    applyPaneWidths();
    if (persist) persistPaneWidth(TERM_H_KEY, termH);
    return termH;
  }

  function composeMax() {
    const style = input ? getComputedStyle(input) : null;
    const line = style ? parseFloat(style.lineHeight) : NaN;
    const size = style ? parseFloat(style.fontSize) : NaN;
    const row = Number.isFinite(line) && line > 0
      ? line
      : (Number.isFinite(size) && size > 0 ? size * 1.45 : 13);
    const pad = style
      ? (parseFloat(style.paddingTop) || 0)
        + (parseFloat(style.paddingBottom) || 0)
        + (parseFloat(style.borderTopWidth) || 0)
        + (parseFloat(style.borderBottomWidth) || 0)
      : 22;
    const rows = row * COMPOSE_ROWS_MAX + pad;
    const wrap = root.querySelector(".chat-wrap");
    const h = wrap ? wrap.clientHeight : 0;
    const room = Math.max(COMPOSE_H_MIN, (h || 400) - 180);
    return Math.max(COMPOSE_H_MIN, Math.min(rows, room));
  }

  function applyComposeH() {
    const handle = root.querySelector("#chat-compose-resize");
    if (composeH > 0) {
      const cap = composeMax();
      const h = Math.min(composeH, cap);
      shell.style.setProperty("--chat-input-h", `${h}px`);
      input.style.maxHeight = `${cap}px`;
      input.style.height = `${h}px`;
    } else {
      shell.style.removeProperty("--chat-input-h");
      input.style.maxHeight = "";
      resizeInput();
    }
    if (handle) {
      handle.setAttribute(
        "aria-valuenow",
        String(composeH > 0 ? composeH : Math.round(input.getBoundingClientRect().height))
      );
    }
    if (window.TabbyMonaco) window.TabbyMonaco.layout();
  }

  function setComposeH(next, persist) {
    if (next <= 0) composeH = 0;
    else composeH = Math.round(Math.min(composeMax(), Math.max(COMPOSE_H_MIN, next)));
    applyComposeH();
    if (persist) persistPaneWidth(COMPOSE_H_KEY, composeH);
    return composeH;
  }

  function applyFilesFr() {
    if (!filesPane) return;
    filesPane.style.setProperty("--chat-files-tree-fr", String(filesFr.tree));
    filesPane.style.setProperty("--chat-files-changes-fr", String(filesFr.changes));
    filesPane.style.setProperty("--chat-files-history-fr", String(filesFr.history));
    const changesHandle = root.querySelector("#chat-files-changes-resize");
    const historyHandle = root.querySelector("#chat-files-history-resize");
    if (changesHandle) changesHandle.setAttribute("aria-valuenow", String(Math.round(filesFr.changes * 100)));
    if (historyHandle) historyHandle.setAttribute("aria-valuenow", String(Math.round(filesFr.history * 100)));
  }

  function persistFilesFr() {
    persistPaneWidth(
      FILES_FR_KEY,
      `${filesFr.tree.toFixed(3)},${filesFr.changes.toFixed(3)},${filesFr.history.toFixed(3)}`
    );
  }

  function filesSplitSections() {
    return [
      { key: "tree", el: filesTree, open: true },
      { key: "changes", el: filesChangesPane, open: changesOpen },
      { key: "history", el: filesHistoryPane, open: historyOpen },
    ];
  }

  function bindDragResize(handle, opts) {
    if (!handle) return;
    const axis = opts.axis || "x";
    const invert = Boolean(opts.invert);
    const minOf = () => (typeof opts.min === "function" ? opts.min() : opts.min);
    const maxOf = () => (typeof opts.max === "function" ? opts.max() : opts.max);
    const defOf = () => (typeof opts.def === "function" ? opts.def() : opts.def);
    const scaleOf = () => (typeof opts.scale === "function" ? opts.scale() : (opts.scale || 1));
    handle.setAttribute("role", "separator");
    handle.setAttribute("aria-orientation", axis === "y" ? "horizontal" : "vertical");
    const coord = (event) => (axis === "y" ? event.clientY : event.clientX);
    const paint = () => {
      handle.setAttribute("aria-valuenow", String(Math.round(opts.get())));
      const min = minOf();
      const max = maxOf();
      if (min != null) handle.setAttribute("aria-valuemin", String(min));
      if (max != null) handle.setAttribute("aria-valuemax", String(max));
    };
    let drag = null;
    const onMove = (event) => {
      if (!drag) return;
      const delta = (coord(event) - drag.p) * drag.s;
      opts.set(drag.v + (invert ? -delta : delta), false);
      paint();
    };
    const onUp = () => {
      if (!drag) return;
      drag = null;
      handle.classList.remove("is-dragging");
      shell.classList.remove("is-resizing", "is-resizing-y");
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onUp);
      if (opts.persist) opts.persist();
      paint();
    };
    handle.addEventListener("pointerdown", (event) => {
      if (event.button !== 0 || isNarrowChat()) return;
      if (opts.enabled && !opts.enabled()) return;
      event.preventDefault();
      drag = { p: coord(event), v: opts.get(), s: scaleOf() };
      handle.classList.add("is-dragging");
      shell.classList.add("is-resizing");
      if (axis === "y") shell.classList.add("is-resizing-y");
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
      window.addEventListener("pointercancel", onUp);
    });
    handle.addEventListener("dblclick", () => {
      if (isNarrowChat()) return;
      opts.set(defOf(), true);
      paint();
    });
    handle.addEventListener("keydown", (event) => {
      if (isNarrowChat()) return;
      const step = event.shiftKey ? (opts.shiftStep || 32) : (opts.step || 16);
      let delta = 0;
      if (axis === "x") {
        if (event.key === "ArrowLeft") delta = invert ? step : -step;
        else if (event.key === "ArrowRight") delta = invert ? -step : step;
      } else if (event.key === "ArrowUp") delta = invert ? step : -step;
      else if (event.key === "ArrowDown") delta = invert ? -step : step;
      if (event.key === "Home") {
        event.preventDefault();
        opts.set(defOf(), true);
        paint();
        return;
      }
      if (!delta) return;
      event.preventDefault();
      opts.set(opts.get() + delta, true);
      paint();
    });
    paint();
  }

  function bindFilesSplit(handle, belowKey) {
    if (!handle || !filesPane) return;
    handle.setAttribute("role", "separator");
    handle.setAttribute("aria-orientation", "horizontal");
    let drag = null;
    const onMove = (event) => {
      if (!drag) return;
      const dy = event.clientY - drag.y;
      let newA = drag.aH + dy;
      let newB = drag.bH - dy;
      if (newA < drag.aMin) {
        newB -= drag.aMin - newA;
        newA = drag.aMin;
      }
      if (newB < drag.bMin) {
        newA -= drag.bMin - newB;
        newB = drag.bMin;
      }
      if (newA < drag.aMin || newB < drag.bMin) return;
      const sumH = newA + newB;
      if (sumH <= 0) return;
      filesFr[drag.aKey] = drag.sumFr * (newA / sumH);
      filesFr[drag.bKey] = drag.sumFr * (newB / sumH);
      applyFilesFr();
    };
    const onUp = () => {
      if (!drag) return;
      drag = null;
      handle.classList.remove("is-dragging");
      shell.classList.remove("is-resizing", "is-resizing-y");
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onUp);
      persistFilesFr();
    };
    handle.addEventListener("pointerdown", (event) => {
      if (event.button !== 0 || isNarrowChat()) return;
      const visible = filesSplitSections().filter((row) => row.open && row.el);
      const below = visible.findIndex((row) => row.key === belowKey);
      if (below <= 0) return;
      const above = visible[below - 1];
      const under = visible[below];
      event.preventDefault();
      drag = {
        y: event.clientY,
        aH: above.el.getBoundingClientRect().height,
        bH: under.el.getBoundingClientRect().height,
        aMin: FILES_SPLIT_MIN,
        bMin: FILES_SPLIT_MIN,
        aKey: above.key,
        bKey: under.key,
        sumFr: filesFr[above.key] + filesFr[under.key],
      };
      handle.classList.add("is-dragging");
      shell.classList.add("is-resizing", "is-resizing-y");
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
      window.addEventListener("pointercancel", onUp);
    });
    handle.addEventListener("dblclick", () => {
      if (isNarrowChat()) return;
      filesFr = { tree: 2, changes: 1, history: 1 };
      applyFilesFr();
      persistFilesFr();
    });
    handle.addEventListener("keydown", (event) => {
      if (isNarrowChat()) return;
      if (event.key === "Home") {
        event.preventDefault();
        filesFr = { tree: 2, changes: 1, history: 1 };
        applyFilesFr();
        persistFilesFr();
        return;
      }
      const step = event.shiftKey ? 0.25 : 0.12;
      let delta = 0;
      if (event.key === "ArrowUp") delta = -step;
      else if (event.key === "ArrowDown") delta = step;
      else return;
      event.preventDefault();
      const visible = filesSplitSections().filter((row) => row.open && row.el);
      const below = visible.findIndex((row) => row.key === belowKey);
      if (below <= 0) return;
      const above = visible[below - 1];
      const under = visible[below];
      const sumFr = filesFr[above.key] + filesFr[under.key];
      const nextA = Math.min(sumFr - 0.15, Math.max(0.15, filesFr[above.key] + delta));
      filesFr[above.key] = nextA;
      filesFr[under.key] = sumFr - nextA;
      applyFilesFr();
      persistFilesFr();
    });
  }

  applyPaneWidths();
  applyFilesFr();
  if (composeH > 0) setComposeH(composeH, false);
  else applyComposeH();
  bindDragResize(root.querySelector("#chat-sidebar-resize"), {
    axis: "x",
    min: SIDEBAR_W_MIN,
    max: SIDEBAR_W_MAX,
    def: SIDEBAR_W_DEFAULT,
    get: () => sidebarW,
    set: (next, persist) => setPaneWidth("sidebar", next, persist),
    persist: () => persistPaneWidth(SIDEBAR_W_KEY, sidebarW),
  });
  bindDragResize(root.querySelector("#chat-files-resize"), {
    axis: "x",
    invert: true,
    min: FILES_W_MIN,
    max: FILES_W_MAX,
    def: FILES_W_DEFAULT,
    get: () => filesW,
    set: (next, persist) => setPaneWidth("files", next, persist),
    persist: () => persistPaneWidth(FILES_W_KEY, filesW),
  });
  bindDragResize(root.querySelector("#chat-preview-resize"), {
    axis: "x",
    invert: true,
    min: PREVIEW_W_MIN,
    max: PREVIEW_W_MAX,
    def: PREVIEW_W_DEFAULT,
    scale: () => {
      const w = stageEl() ? stageEl().clientWidth : 0;
      return w > 0 ? 100 / w : 1;
    },
    step: 2,
    shiftStep: 8,
    get: () => previewW,
    set: (next, persist) => setPreviewW(next, persist),
    persist: () => persistPaneWidth(PREVIEW_W_KEY, previewW),
  });
  bindDragResize(root.querySelector("#chat-term-resize"), {
    axis: "y",
    invert: true,
    min: TERM_H_MIN,
    max: termMax,
    def: TERM_H_DEFAULT,
    get: () => termH,
    set: (next, persist) => setTermH(next, persist),
    persist: () => persistPaneWidth(TERM_H_KEY, termH),
  });
  bindDragResize(root.querySelector("#chat-compose-resize"), {
    axis: "y",
    invert: true,
    min: COMPOSE_H_MIN,
    max: composeMax,
    def: 0,
    get: () => (composeH > 0 ? composeH : Math.round(input.getBoundingClientRect().height)),
    set: (next, persist) => setComposeH(next, persist),
    persist: () => persistPaneWidth(COMPOSE_H_KEY, composeH),
  });
  bindFilesSplit(root.querySelector("#chat-files-changes-resize"), "changes");
  bindFilesSplit(root.querySelector("#chat-files-history-resize"), "history");
  window.addEventListener("tabby-zoom-change", () => {
    if (termTerm) {
      termTerm.options.fontSize = termFontSize();
      fitTerm();
    }
    resizeInput();
  });
  window.addEventListener("resize", () => {
    if (isNarrowChat()) return;
    reclampPaneWidths();
  });
  if (editorCol && window.ResizeObserver) {
    new ResizeObserver(() => {
      if (window.TabbyMonaco) window.TabbyMonaco.layout();
    }).observe(editorCol);
  }
  if (termHost && window.ResizeObserver) {
    new ResizeObserver(() => {
      if (termOpen) fitTerm();
    }).observe(termHost);
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
    const item = messages[idx];
    let stamp = null;
    if (item && item.createdAt) {
      stamp = document.createElement("span");
      stamp.className = "chat-stamp";
      stamp.textContent = stampLabel(item.createdAt);
    }
    if (role === "user") {
      meta.appendChild(actions);
      if (stamp) meta.appendChild(stamp);
    } else {
      if (stamp) meta.appendChild(stamp);
      meta.appendChild(actions);
    }
    host.appendChild(meta);
    attachPlanBuild(host, idx);
  }

  function lastUnbuiltPlanIndex() {
    let latest = -1;
    for (let i = 0; i < messages.length; i += 1) {
      const item = messages[i];
      if (!item) continue;
      if (item.role === "assistant" && normalizeAgent(item.agent) === "plan") {
        latest = i;
      }
      if (item.role === "user" && isBuildPromptText(item.content)) latest = -1;
    }
    return latest;
  }

  function canBuildPlan(idx) {
    if (activeMode() !== "code") return false;
    if (modelLoading || inFlight) return false;
    return idx === lastUnbuiltPlanIndex();
  }

  function attachPlanBuild(host, idx) {
    if (!host) return;
    host.querySelectorAll(".chat-plan-build").forEach((node) => node.remove());
    if (!canBuildPlan(idx)) return;
    const bar = document.createElement("div");
    bar.className = "chat-plan-build";
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn primary";
    btn.dataset.act = "build";
    btn.dataset.idx = String(idx);
    btn.textContent = "Build";
    btn.title = "Implement this plan";
    btn.setAttribute("aria-label", "Implement this plan");
    bar.appendChild(btn);
    host.appendChild(bar);
  }

  function buildApprovedPlan(idx) {
    if (inFlight || modelLoading) return;
    const planIdx = Number.isInteger(idx) && idx >= 0 ? idx : lastUnbuiltPlanIndex();
    const plan = planIdx >= 0 ? messages[planIdx] : null;
    if (!plan || plan.role !== "assistant" || normalizeAgent(plan.agent) !== "plan") return;
    const body = String(plan.content || "").trim();
    const prompt = body
      ? `${BUILD_PROMPT}\n\n<approved_plan>\n${body}\n</approved_plan>`
      : BUILD_PROMPT;
    setCodeAgent("agent");
    hidePopovers();
    runLoop(prompt, { hidden: true }).catch((err) => {
      addBubble("assistant", `Error: ${err.message}`);
      persist();
    });
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
    const current = activeChat();
    const chat = emptyChat(mode, mode === "code" ? workspaceId(current) : "");
    chat.messages = [{ ...SYSTEM }, ...tail];
    chat.title = titleFromMessages(chat.messages, chat);
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
    let replayAgent = "";
    if (messages.length && messages[messages.length - 1].role === "assistant") {
      const popped = messages.pop();
      if (activeMode() === "code") replayAgent = normalizeAgent(popped && popped.agent);
    }
    const lastUser = [...messages].reverse().find((item) => item.role === "user");
    if (!lastUser) return;
    persist();
    renderLog();
    const opts = { replay: true };
    if (replayAgent) opts.agent = replayAgent;
    runLoop(lastUser.content, opts).catch((err) => {
      addBubble("assistant", `Error: ${err.message}`);
      persist();
    });
  }

  function conversationMarkdown(id) {
    return chatMessages(id)
      .filter((item) => {
        if (item.role === "assistant") return true;
        return item.role === "user" && !isHiddenUserTurn(item);
      })
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
    field.value = chat.title || defaultChatTitle(chat);
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

  function pinTarget(id) {
    const chat = store.chats.find((item) => item.id === (id || store.activeId));
    if (!chat) return null;
    if (chatMode(chat) === "chat") return chat;
    if (isWorkspaceRoot(chat)) return chat;
    const root = store.chats.find((item) => item.id === workspaceId(chat));
    return root && isWorkspaceRoot(root) ? root : null;
  }

  function togglePin(id) {
    const chat = pinTarget(id);
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
    add("gallery", "From gallery");
    if (activeMode() !== "code") {
      add("context", "Attach files");
      attachMenu.replaceChildren(frag);
      return;
    }
    add("upload", "Upload files to project");
    add("upload-folder", "Upload folder to project");
    add("upload-gallery", "Upload from gallery");
    const fileRows = filesListing.filter((row) => row.kind !== "dir");
    if (fileRows.length) {
      const mark = document.createElement("div");
      mark.className = "chat-attach-label";
      mark.textContent = "Project files";
      frag.appendChild(mark);
      fileRows.forEach((row) => {
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
    const open = Boolean(attachMenu && attachMenu.hidden);
    hideMoreMenu();
    hideFilesMoreMenu();
    hideUploadMenu();
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
    if (contextInput) contextInput.value = "";
    if (uploadInput) uploadInput.value = "";
    if (uploadDirInput) uploadDirInput.value = "";
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

  function uniqueProjectPath(rel) {
    const path = String(rel || "").replace(/^\/+/, "");
    const names = new Set(filesListing.map((row) => row.path));
    if (!names.has(path)) return path;
    const suffix = fileSuffix(path);
    const stem = suffix && path.endsWith(suffix) ? path.slice(0, -suffix.length) : path;
    for (let i = 2; i < 100; i += 1) {
      const next = `${stem}-${i}${suffix}`;
      if (!names.has(next)) return next;
    }
    return `${stem}-${Date.now()}${suffix}`;
  }

  async function attachGalleryItems(items) {
    if (modelLoading) return;
    const list = Array.isArray(items) ? items : [];
    let overflow = false;
    for (const item of list) {
      if (pendingFiles.length >= MAX_ATTACH) {
        overflow = true;
        break;
      }
      const name = String((item && item.name) || "image.png");
      const url = TabbyUI.resolveUiUrl((item && item.url) || "");
      if (!url) continue;
      const path = uniqueAttachPath(name);
      if (isPendingFile(path)) continue;
      const res = await fetch(url, { credentials: "same-origin" });
      if (!res.ok) throw new Error("Could not read that image.");
      const dataUrl = await blobToDataUrl(await res.blob());
      const preview = await resizeDataUrl(dataUrl, 320, 0.72);
      const compact = await resizeDataUrl(dataUrl, 1280, 0.82);
      pendingFiles.push({ path, kind: "image", dataUrl: compact, preview });
    }
    paintAttach();
    if (overflow) addBubble("assistant", "Error: Too many attached files.");
    if (input) input.focus();
  }

  async function uploadGalleryItems(items, { attach = false, open = false } = {}) {
    if (activeMode() !== "code") {
      await attachGalleryItems(items);
      return;
    }
    const chatId = activeWorkspaceId();
    const prefix = filesFocusDir ? `${String(filesFocusDir).replace(/\/+$/, "")}/` : "images/";
    const list = Array.isArray(items) ? items : [];
    let lastPath = "";
    let written = 0;
    for (const item of list) {
      const name = String((item && item.name) || "image.png");
      const url = TabbyUI.resolveUiUrl((item && item.url) || "");
      if (!url) continue;
      const res = await fetch(url, { credentials: "same-origin" });
      if (!res.ok) throw new Error("Could not read that image.");
      const blob = await res.blob();
      if (blob.size > 8 * 1024 * 1024) {
        addBubble("assistant", `Error: ${name} must be under 8 MB.`);
        continue;
      }
      const path = uniqueProjectPath(prefix + name);
      const data = await TabbyUI.api(
        `workspace/${encodeURIComponent(chatId)}/file`,
        { method: "POST", body: { path, bytes_b64: await blobToBase64(blob) } }
      );
      applyListing(data);
      const writtenPath = data.path || path;
      written += 1;
      lastPath = writtenPath;
      if (attach) await attachProjectFile(writtenPath, { toggle: false });
    }
    if (open && lastPath && written === 1) openFileTab(lastPath);
  }

  async function pickAndAttachGallery() {
    if (!TabbyUI.pickGallery) return;
    const items = await TabbyUI.pickGallery({ title: "Attach from gallery", confirm: "Attach" });
    if (!items || !items.length) return;
    await attachGalleryItems(items);
  }

  async function pickAndUploadGallery({ attach = false } = {}) {
    if (!TabbyUI.pickGallery) return;
    const items = await TabbyUI.pickGallery({
      title: attach ? "Add from gallery" : "Upload from gallery",
      confirm: "Add to project",
    });
    if (!items || !items.length) return;
    await uploadGalleryItems(items, { attach, open: !attach && items.length === 1 });
  }

  async function consumeGalleryUse() {
    const job = TabbyUI.takeGalleryUse && TabbyUI.takeGalleryUse();
    if (!job || !Array.isArray(job.items) || !job.items.length) return;
    try {
      if (job.action === "upload") await uploadGalleryItems(job.items, { attach: false, open: job.items.length === 1 });
      else await attachGalleryItems(job.items);
    } catch (err) {
      addBubble("assistant", `Error: ${err.message}`);
    }
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
      const res = await fetch(fileUrl(activeWorkspaceId(), path), { credentials: "same-origin" });
      if (!res.ok) throw new Error("Could not read that file.");
      const dataUrl = await blobToDataUrl(await res.blob());
      const preview = await resizeDataUrl(dataUrl, 320, 0.72);
      pendingFiles.push({ path, kind: "image", dataUrl, preview });
    } else if (row.editable) {
      const tab = findTab(path);
      let text = tab && tab.state === "ready" ? String(tab.text || "") : "";
      if (!(tab && tab.state === "ready")) {
        const res = await fetch(fileUrl(activeWorkspaceId(), path), { credentials: "same-origin" });
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

  function defaultNewPath(dir) {
    const prefix = dir ? `${String(dir).replace(/\/+$/, "")}/` : "";
    const names = new Set(filesListing.map((row) => row.path));
    if (!names.has(`${prefix}untitled.txt`)) return `${prefix}untitled.txt`;
    for (let i = 2; i < 100; i += 1) {
      const name = `${prefix}untitled-${i}.txt`;
      if (!names.has(name)) return name;
    }
    return `${prefix}untitled-${Date.now()}.txt`;
  }

  async function createUserFile(dir) {
    const folder = dir != null && dir !== ""
      ? String(dir).replace(/\/+$/, "")
      : filesFocusDir;
    const raw = await TabbyUI.promptModal({
      title: "New file",
      text: "Relative path in this chat's project.",
      label: "Path",
      yes: "Create",
      value: defaultNewPath(folder),
      placeholder: folder ? `${folder}/index.html` : "index.html",
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
        `workspace/${encodeURIComponent(activeWorkspaceId())}/file?path=${encodeURIComponent(path)}`,
        { method: "PUT", body: { contents: "" } }
      );
      applyListing(data);
      const written = data.path || path;
      filesFocusDir = fileDir(written);
      openFileTab(written);
    } catch (err) {
      addBubble("assistant", `Error: ${err.message}`);
    }
  }

  async function createUserFolder(dir) {
    const folder = dir != null && dir !== ""
      ? String(dir).replace(/\/+$/, "")
      : filesFocusDir;
    const raw = await TabbyUI.promptModal({
      title: "New folder",
      text: "Folder name in this chat's project.",
      label: "Folder",
      yes: "Create",
      value: folder ? `${folder}/` : "",
      placeholder: folder ? `${folder}/css` : "css",
    });
    if (raw == null) return;
    const path = String(raw).trim().replace(/\\/g, "/").replace(/^\/+|\/+$/g, "");
    if (!path || path.includes("..") || path.startsWith("~")) {
      addBubble("assistant", "Error: Enter a relative folder such as css.");
      return;
    }
    filesOpenFolders.add(path);
    try {
      const data = await TabbyUI.api(
        `workspace/${encodeURIComponent(activeWorkspaceId())}/folder?path=${encodeURIComponent(path)}`,
        { method: "PUT" }
      );
      applyListing(data);
      const written = data.path || path;
      filesFocusDir = written;
      filesOpenFolders.add(written);
      folderAncestors(written).forEach((dir) => filesOpenFolders.add(dir));
      paintAttach();
      paintFiles();
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
    openTabs.forEach((item) => {
      if (!isHistoryTab(item) || item.filePath !== from) return;
      const next = historyTabKey(to, item.revId);
      if (activeTab === item.path) activeTab = next;
      item.filePath = to;
      item.path = next;
    });
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
        `workspace/${encodeURIComponent(activeWorkspaceId())}/rename`,
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
      const response = await fetch(fileUrl(activeWorkspaceId(), path), { credentials: "same-origin" });
      if (!response.ok) throw new Error("Could not read that file.");
      const bytesB64 = await blobToBase64(await response.blob());
      const data = await TabbyUI.api(
        `workspace/${encodeURIComponent(activeWorkspaceId())}/file`,
        { method: "POST", body: { path: dest, bytes_b64: bytesB64 } }
      );
      applyListing(data);
      const written = data.path || dest;
      if (TEXT_SUFFIXES.has(fileSuffix(written))) openFileTab(written);
    } catch (err) {
      addBubble("assistant", `Error: ${err.message}`);
    }
  }

  async function deleteProjectFile(path, options) {
    const skipConfirm = Boolean(options && options.skipConfirm);
    if (!skipConfirm) {
      const yes = await TabbyUI.confirmModal({
        title: "Delete file",
        text: `Delete “${path}”? The last version stays in History.`,
        yes: "Delete",
        no: "Cancel",
      });
      if (!yes) return;
    }
    try {
      const data = await TabbyUI.api(
        `workspace/${encodeURIComponent(activeWorkspaceId())}/file?path=${encodeURIComponent(path)}`,
        { method: "DELETE" }
      );
      filesListing = Array.isArray(data.files) ? data.files : [];
      filesEntry = typeof data.entry === "string" ? data.entry : "";
      const open = findTab(path);
      if (open) open.dirty = false;
      filesSelected = path;
      pendingFiles = pendingFiles.filter((file) => file.path !== path);
      dropChange(path);
      queueDrafts();
      paintAttach();
      paintFiles();
    } catch (err) {
      if (skipConfirm) throw err;
      addBubble("assistant", `Error: ${err.message}`);
    }
  }

  async function deleteProjectFolder(dir) {
    const prefix = String(dir || "").replace(/\/+$/, "");
    if (!prefix) return;
    const paths = filesListing
      .filter((row) => row.path === prefix || row.path.startsWith(`${prefix}/`))
      .map((row) => row.path);
    if (!paths.length) return;
    const yes = await TabbyUI.confirmModal({
      title: "Delete folder",
      text: `Delete “${prefix}” and ${paths.length} file${paths.length === 1 ? "" : "s"}?`,
      yes: "Delete",
      no: "Cancel",
    });
    if (!yes) return;
    try {
      const data = await TabbyUI.api(
        `workspace/${encodeURIComponent(activeWorkspaceId())}/folder?path=${encodeURIComponent(prefix)}`,
        { method: "DELETE" }
      );
      applyListing(data);
      paths.forEach((path) => {
        const open = findTab(path);
        if (open) open.dirty = false;
        pendingFiles = pendingFiles.filter((file) => file.path !== path);
      });
      if (filesSelected === prefix || filesSelected.startsWith(`${prefix}/`)) filesSelected = "";
      paintAttach();
      paintFiles();
    } catch (err) {
      addBubble("assistant", `Error: ${err.message}`);
    }
  }

  async function renameProjectFolder(dir) {
    const prefix = String(dir || "").replace(/\/+$/, "");
    if (!prefix) return;
    const raw = await TabbyUI.promptModal({
      title: "Rename folder",
      text: "New folder path in this chat's project.",
      label: "Folder",
      yes: "Rename",
      value: prefix,
    });
    if (raw == null) return;
    const dest = String(raw).trim().replace(/\\/g, "/").replace(/^\/+|\/+$/g, "");
    if (!dest || dest === prefix) return;
    if (dest.includes("..") || dest.startsWith("~")) {
      addBubble("assistant", "Error: Enter a relative folder such as css.");
      return;
    }
    try {
      const data = await TabbyUI.api(
        `workspace/${encodeURIComponent(activeWorkspaceId())}/folder`,
        { method: "POST", body: { path: prefix, to: dest } }
      );
      (Array.isArray(data.moved) ? data.moved : []).forEach((row) => {
        if (row && row.from && row.to) retargetPath(row.from, row.to);
      });
      applyListing(data);
      filesFocusDir = dest;
      filesOpenFolders.add(dest);
      paintAttach();
    } catch (err) {
      addBubble("assistant", `Error: ${err.message}`);
    }
  }

  function treeDragPayload(event) {
    const transfer = event.dataTransfer;
    if (!transfer) return null;
    const path = transfer.getData(TREE_DRAG) || transfer.getData("text/plain");
    const kind = transfer.getData("application/x-tabby-kind") || "file";
    if (!path) return null;
    return { path, kind };
  }

  function treeHasDrag(event) {
    return Array.from((event.dataTransfer && event.dataTransfer.types) || []).includes(TREE_DRAG);
  }

  function dropDirFor(event) {
    const row = event.target.closest && event.target.closest(".chat-file");
    if (!row || !filesTree.contains(row)) return "";
    if (row.dataset.kind === "dir") return row.dataset.path || "";
    return fileDir(row.dataset.path || "");
  }

  function moveDest(src, kind, dir) {
    const name = fileBase(src);
    if (!name) return "";
    return dir ? `${dir}/${name}` : name;
  }

  function invalidTreeMove(src, kind, dest) {
    if (!src || !dest || src === dest) return true;
    if (kind === "dir" && (dest === src || dest.startsWith(`${src}/`))) return true;
    return false;
  }

  function markTreeDrop(event) {
    if (filesTree) {
      filesTree.querySelectorAll(".chat-file.is-drop-target").forEach((node) => {
        node.classList.remove("is-drop-target");
      });
    }
    const row = event.target.closest && event.target.closest(".chat-file");
    if (row && filesTree && filesTree.contains(row)) row.classList.add("is-drop-target");
  }

  async function moveProjectItem(src, kind, dir) {
    const dest = moveDest(src, kind, dir);
    if (invalidTreeMove(src, kind, dest)) return;
    const exists = kind === "dir"
      ? filesListing.some((row) => row.path === dest || row.path.startsWith(`${dest}/`))
      : filesListing.some((row) => row.path === dest);
    if (exists) {
      const yes = await TabbyUI.confirmModal({
        title: kind === "dir" ? "Replace folder?" : "Replace file?",
        text: `${dest} already exists. Replace it?`,
        yes: "Replace",
        no: "Cancel",
      });
      if (!yes) return;
      try {
        if (kind === "dir") {
          await TabbyUI.api(
            `workspace/${encodeURIComponent(activeWorkspaceId())}/folder?path=${encodeURIComponent(dest)}`,
            { method: "DELETE" }
          );
        } else {
          await TabbyUI.api(
            `workspace/${encodeURIComponent(activeWorkspaceId())}/file?path=${encodeURIComponent(dest)}`,
            { method: "DELETE" }
          );
        }
      } catch (err) {
        addBubble("assistant", `Error: ${err.message}`);
        return;
      }
    }
    try {
      if (kind === "dir") {
        const data = await TabbyUI.api(
          `workspace/${encodeURIComponent(activeWorkspaceId())}/folder`,
          { method: "POST", body: { path: src, to: dest } }
        );
        (Array.isArray(data.moved) ? data.moved : []).forEach((row) => {
          if (row && row.from && row.to) retargetPath(row.from, row.to);
        });
        applyListing(data);
        filesFocusDir = dest;
        filesOpenFolders.add(dest);
      } else {
        const data = await TabbyUI.api(
          `workspace/${encodeURIComponent(activeWorkspaceId())}/rename`,
          { method: "POST", body: { path: src, to: dest } }
        );
        retargetPath(src, data.path || dest);
        applyListing(data);
      }
      paintAttach();
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
        `workspace/${encodeURIComponent(activeWorkspaceId())}/file?path=${encodeURIComponent(path)}`,
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
    fetch(TabbyUI.path(`workspace/${encodeURIComponent(activeWorkspaceId())}/zip`), {
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
      text: "Delete every file in this workspace?",
      yes: "Clear",
      no: "Cancel",
    });
    if (!yes) return;
    try {
      await TabbyUI.api(`workspace/${encodeURIComponent(activeWorkspaceId())}`, { method: "DELETE" });
      filesListing = [];
      filesSelected = "";
      filesEntry = "";
      pendingFiles = [];
      resetTabs();
      if (tabsChat) tabsByChat[tabsChat] = { openTabs, activeTab };
      resetFilesTreeState();
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

  function cleanUploadRel(rel) {
    return String(rel || "")
      .replace(/\\/g, "/")
      .replace(/^\/+/, "")
      .split("/")
      .filter((part) => part && part !== "." && part !== "..");
  }

  function skipUploadParts(parts) {
    if (!parts.length) return true;
    if (parts.some((part) => SKIP_UPLOAD_DIRS.has(part))) return true;
    return SKIP_UPLOAD_FILES.has(String(parts[parts.length - 1] || "").toLowerCase());
  }

  function normalizeUploadItems(fileList) {
    return Array.from(fileList || []).filter(Boolean).map((item) => {
      if (item && item.file) {
        return { file: item.file, rel: String(item.rel || item.file.name || "file") };
      }
      const file = item;
      return { file, rel: String(file.webkitRelativePath || file.name || "file") };
    });
  }

  function readDirEntries(reader) {
    return new Promise((resolve, reject) => reader.readEntries(resolve, reject));
  }

  function readEntryFile(entry) {
    return new Promise((resolve, reject) => entry.file(resolve, reject));
  }

  async function collectEntry(entry, prefix, out) {
    if (!entry) return;
    if (entry.isFile) {
      if (SKIP_UPLOAD_FILES.has(String(entry.name || "").toLowerCase())) return;
      const file = await readEntryFile(entry);
      out.push({ file, rel: `${prefix}${entry.name}` });
      return;
    }
    if (!entry.isDirectory || SKIP_UPLOAD_DIRS.has(entry.name)) return;
    const next = `${prefix}${entry.name}/`;
    const reader = entry.createReader();
    let batch = await readDirEntries(reader);
    while (batch.length) {
      for (const child of batch) await collectEntry(child, next, out);
      batch = await readDirEntries(reader);
    }
  }

  async function readDirHandle(dirHandle, prefix, out) {
    if (!dirHandle || SKIP_UPLOAD_DIRS.has(dirHandle.name)) return out;
    for await (const [name, handle] of dirHandle.entries()) {
      if (handle.kind === "directory") {
        if (SKIP_UPLOAD_DIRS.has(name)) continue;
        await readDirHandle(handle, `${prefix}/${name}`, out);
      } else if (handle.kind === "file") {
        if (SKIP_UPLOAD_FILES.has(String(name || "").toLowerCase())) continue;
        const file = await handle.getFile();
        out.push({ file, rel: `${prefix}/${name}` });
      }
    }
    return out;
  }

  async function itemsFromDataTransfer(dt) {
    const items = dt && dt.items;
    if (items && items.length) {
      const entries = [];
      for (let i = 0; i < items.length; i += 1) {
        const item = items[i];
        if (item.kind !== "file") continue;
        const entry = item.webkitGetAsEntry && item.webkitGetAsEntry();
        if (entry) entries.push(entry);
      }
      if (entries.length) {
        const out = [];
        for (const entry of entries) await collectEntry(entry, "", out);
        return out;
      }
    }
    return Array.from((dt && dt.files) || []);
  }

  function uniqueAttachPath(rel) {
    const path = cleanUploadRel(rel).join("/") || "file";
    if (!isPendingFile(path)) return path;
    const suffix = fileSuffix(path);
    const stem = suffix && path.endsWith(suffix) ? path.slice(0, -suffix.length) : path;
    for (let i = 2; i < 100; i += 1) {
      const next = `${stem}-${i}${suffix}`;
      if (!isPendingFile(next)) return next;
    }
    return `${stem}-${Date.now()}${suffix}`;
  }

  function looksLikeImageFile(file, path) {
    if (IMAGE_SUFFIXES.has(fileSuffix(path))) return true;
    return /^image\/(png|jpe?g|webp|gif)\b/.test(String(file && file.type || "").toLowerCase());
  }

  async function attachLocalContextFile(file, rel) {
    if (!file || modelLoading) return false;
    const parts = cleanUploadRel(rel || file.name || "file");
    if (skipUploadParts(parts)) return false;
    const path = uniqueAttachPath(parts.join("/") || file.name || "file");
    if (pendingFiles.length >= MAX_ATTACH) {
      addBubble("assistant", "Error: Too many attached files.");
      return false;
    }
    if (looksLikeImageFile(file, path)) {
      if (file.size > 8 * 1024 * 1024) {
        addBubble("assistant", `Error: ${path} must be under 8 MB.`);
        return false;
      }
      const dataUrl = await blobToDataUrl(file);
      const preview = await resizeDataUrl(dataUrl, 320, 0.72);
      const compact = await resizeDataUrl(dataUrl, 1280, 0.82);
      pendingFiles.push({ path, kind: "image", dataUrl: compact, preview });
      paintAttach();
      return true;
    }
    if (BINARY_SUFFIXES.has(fileSuffix(path))) {
      addBubble("assistant", `Error: ${path} is not a text or image file.`);
      return false;
    }
    if (file.size > 1 * 1024 * 1024) {
      addBubble("assistant", `Error: ${path} is larger than 1 MB.`);
      return false;
    }
    let text = await file.text();
    if (text.includes("\0")) {
      addBubble("assistant", `Error: ${path} is not a text file.`);
      return false;
    }
    if (text.length > ATTACH_TEXT_LIMIT) text = `${text.slice(0, ATTACH_TEXT_LIMIT)}\n…(truncated)`;
    pendingFiles.push({ path, kind: "text", text });
    paintAttach();
    return true;
  }

  async function attachLocalContextFiles(fileList) {
    const items = normalizeUploadItems(fileList);
    let overflow = false;
    for (const item of items) {
      if (pendingFiles.length >= MAX_ATTACH) {
        overflow = true;
        break;
      }
      await attachLocalContextFile(item.file, item.rel);
    }
    if (overflow) addBubble("assistant", "Error: Too many attached files.");
  }

  async function pickLocalFiles({ attach = false, dir = "", folder = false, context = false } = {}) {
    uploadWantsAttach = attach;
    uploadWantsContext = context;
    uploadTargetDir = dir || "";
    if (context) {
      if (contextInput) contextInput.click();
      return;
    }
    if (folder && typeof window.showDirectoryPicker === "function") {
      try {
        const handle = await window.showDirectoryPicker({ mode: "read" });
        const items = [];
        await readDirHandle(handle, handle.name || "folder", items);
        await uploadLocalFiles(items, {
          attach,
          open: !attach && items.length === 1,
          dir: uploadTargetDir,
        });
        return;
      } catch (err) {
        if (err && err.name === "AbortError") return;
      }
    }
    const input = folder ? uploadDirInput : uploadInput;
    if (input) input.click();
  }

  async function uploadLocalFiles(fileList, { attach = false, open = false, dir = "" } = {}) {
    const chatId = activeWorkspaceId();
    let items = normalizeUploadItems(fileList);
    const prefix = dir ? `${String(dir).replace(/\/+$/, "")}/` : "";
    if (items.length > 200) {
      addBubble("assistant", "Error: Too many files (max 200).");
      items = items.slice(0, 200);
    }
    let lastText = "";
    const errors = [];
    let skipped = 0;
    let written = 0;
    for (const item of items) {
      const parts = cleanUploadRel(item.rel);
      if (skipUploadParts(parts)) {
        skipped += 1;
        continue;
      }
      const name = prefix + parts.join("/");
      const file = item.file;
      const suffix = fileSuffix(name);
      if (!TEXT_SUFFIXES.has(suffix) && !IMAGE_SUFFIXES.has(suffix)) {
        errors.push(`${name} is not a text or image file.`);
        continue;
      }
      if (TEXT_SUFFIXES.has(suffix) && file.size > 1 * 1024 * 1024) {
        errors.push(`${name} is larger than 1 MB.`);
        continue;
      }
      if (IMAGE_SUFFIXES.has(suffix) && file.size > 8 * 1024 * 1024) {
        errors.push(`${name} must be under 8 MB.`);
        continue;
      }
      const bytesB64 = await blobToBase64(file);
      const data = await TabbyUI.api(
        `workspace/${encodeURIComponent(chatId)}/file`,
        { method: "POST", body: { path: name, bytes_b64: bytesB64 } }
      );
      applyListing(data);
      const path = data.path || name;
      written += 1;
      if (attach) await attachProjectFile(path, { toggle: false });
      if (TEXT_SUFFIXES.has(fileSuffix(path))) lastText = path;
    }
    if (errors.length) {
      const extra = errors.length > 3 ? ` (+${errors.length - 3} more)` : "";
      addBubble("assistant", `Error: ${errors.slice(0, 3).join(" ")}${extra}`);
    } else if (!written && skipped) {
      addBubble("assistant", "Error: Nothing in that folder could be added.");
    }
    if (open && lastText && items.length === 1) openFileTab(lastText);
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
    const textBlocks = files
      .filter((file) => file.kind !== "image" && file.path && typeof file.text === "string")
      .map((file) => `Attached file \`${file.path}\`:\n\`\`\`\n${file.text}\n\`\`\``);
    const imageBlocks = files
      .filter((file) => file.kind === "image" && file.path)
      .map((file) => `Attached project image: \`${file.path}\``);
    const blocks = [...imageBlocks, ...textBlocks];
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

  function showShortcuts() {
    return TabbyUI.showShortcuts();
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
      attachPlanBuild(turn.node, idx);
      watchLogChild(turn.node);
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
    watchLogChild(row);
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
    if (isBuildPromptText(raw) || looksLikeCodeProjectPrompt(raw)) {
      return { label: "Building", kind: "chat", processing: true };
    }
    if (
      /qwen-image:/i.test(raw) ||
      /^(generate an image)/i.test(raw) ||
      /^\/image\b/i.test(raw) ||
      /\b(generate|draw|paint|render|create|make|replace)\b[\s\S]{0,80}\b(image|picture|logo|poster|icon|svg)\b/i.test(lower) ||
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

    if (!live || store.activeId === flightChatId) {
      log.appendChild(turn);
      watchLogChild(turn);
    }

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

  function messageFindText(item) {
    return [item && item.content, item && item.reasoning].filter(Boolean).join("\n");
  }

  function collectFindHits(q) {
    const needle = String(q || "").trim().toLowerCase();
    if (!needle) return [];
    const hits = [];
    messages.forEach((item, idx) => {
      if (!item || item.role === "system") return;
      if (messageFindText(item).toLowerCase().includes(needle)) hits.push(idx);
    });
    return hits;
  }

  function paintFindBar() {
    if (!findCountEl) return;
    if (!findQuery.trim()) {
      findCountEl.textContent = "";
      return;
    }
    findCountEl.textContent = findHits.length
      ? `${findIndex + 1}/${findHits.length}`
      : "0/0";
  }

  function paintFindHits() {
    if (!log) return;
    log.querySelectorAll("[data-msg-idx]").forEach((node) => {
      const idx = Number(node.dataset.msgIdx);
      node.classList.toggle("is-find-hit", findHits.includes(idx));
      node.classList.toggle("is-find-current", findHits.length > 0 && findHits[findIndex] === idx);
    });
    paintFindBar();
  }

  function revealFindHit(index) {
    if (!findHits.length) {
      paintFindHits();
      return;
    }
    findIndex = ((index % findHits.length) + findHits.length) % findHits.length;
    paintFindHits();
    const node = log.querySelector(`[data-msg-idx="${findHits[findIndex]}"]`);
    if (node) node.scrollIntoView({ block: "center" });
  }

  function runFind(query, { jump = true } = {}) {
    findQuery = String(query || "");
    findHits = collectFindHits(findQuery);
    findIndex = 0;
    paintFindHits();
    if (jump && findHits.length) revealFindHit(0);
  }

  function openFind(seed) {
    if (findBar) findBar.hidden = false;
    if (findInput) {
      if (seed != null) findInput.value = seed;
      findInput.focus();
      findInput.select();
      runFind(findInput.value);
    } else {
      runFind(seed || findQuery);
    }
  }

  function closeFind() {
    findQuery = "";
    findHits = [];
    findIndex = 0;
    if (findBar) findBar.hidden = true;
    if (findInput) findInput.value = "";
    paintFindHits();
  }

  function jumpSidebarSearch() {
    const q = String((searchEl && searchEl.value) || "").trim();
    if (!q) return;
    openFind(q);
  }

  function renderLog(stickToEnd) {
    if (logSizeObs) {
      logSizeObs.disconnect();
      logSizeObs.observe(log);
    }
    log.replaceChildren();
    messages.forEach((item, idx) => {
      if (item.role === "user") {
        if (isHiddenUserTurn(item)) return;
        addBubble("user", item.content, false, null, idx, item);
      } else if (item.role === "assistant") addBubble("assistant", item.content, false, item.reasoning, idx, item);
    });
    if (inFlight && store.activeId === flightChatId && flightWorking && flightWorking.isLive()) {
      log.appendChild(flightWorking.node);
      watchLogChild(flightWorking.node);
    }
    paintEmpty();
    paintFindHits();
    if (stickToEnd !== false) stickLog(true);
    else paintJump();
  }

  function loadChat(id, stickToEnd) {
    const target = store.chats.find((item) => item.id === id);
    if (target && isWorkspaceRoot(target)) {
      openWorkspaceNav(target.id);
      return;
    }
    if (id === store.activeId) {
      if (stickToEnd !== false) stickLog(true);
      jumpSidebarSearch();
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
    const parent = chatParentId(chat);
    if (parent) expandWorkspace(parent);
    cancelEdit();
    clearPendingImage();
    persist();
    resetRecall();
    renderLog(stickToEnd !== false);
    switchWorkspaceTabs(activeWorkspaceId());
    refreshFiles();
    jumpSidebarSearch();
    paintCompose();
    input.focus();
    setSidebarOpen(false);
  }

  async function deleteChat(id) {
    const chat = store.chats.find((item) => item.id === id);
    if (!chat) return;
    const root = isWorkspaceRoot(chat);
    const children = root ? store.chats.filter((item) => chatParentId(item) === id) : [];
    const doomed = [chat, ...children];
    const hasContent = doomed.some((item) => (
      hasUserTurn(item) || (item.id === store.activeId && hasUserTurn({ messages }))
    ));
    if (hasContent) {
      const named = String(chat.title || "").replace(/\s+/g, " ").trim()
        || (root ? "this workspace" : "this chat");
      const extra = children.length
        ? ` and ${children.length} nested chat${children.length === 1 ? "" : "s"}`
        : "";
      const yes = await TabbyUI.confirmModal({
        title: root ? "Delete workspace" : "Delete chat",
        text: root
          ? `Delete workspace “${named}”${extra}? This cannot be undone.`
          : `Delete “${named}”? This cannot be undone.`,
        yes: "Delete",
        no: "Cancel",
      });
      if (!yes) return;
    }
    const ids = new Set(doomed.map((item) => item.id));
    if (ids.has(store.activeId) || ids.has(flightChatId)) abortSession("stop");
    if (ids.has(store.activeId)) cancelEdit();
    persist();
    const mode = chatMode(chat);
    store.chats = store.chats.filter((item) => !ids.has(item.id));
    if (root) dropWorkspace(id);
    if (ids.has(store.activeId)) {
      const parentId = chatParentId(chat);
      const next = mode === "code"
        ? fallbackCodeChat(parentId)
        : store.chats
          .filter((item) => chatMode(item) === mode && (hasUserTurn(item) || item.pinned))
          .sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0))[0]
          || emptyChat(mode);
      if (mode !== "code" && !store.chats.some((item) => item.id === next.id)) {
        store.chats.unshift(next);
      }
      store.activeId = next.id;
      messages = cloneMessages(next.messages);
      if (!messages.some((item) => item.role === "system")) messages.unshift({ ...SYSTEM });
    }
    persist();
    resetRecall();
    renderLog();
    hideHistoryMenu();
    hideMoreMenu();
    refreshFiles();
    paintCompose();
    input.focus();
  }

  function startNestedChat(parentId) {
    const parent = store.chats.find((item) => item.id === parentId) || activeChat();
    const rootId = parent ? workspaceId(parent) : "";
    const root = store.chats.find((item) => item.id === rootId);
    if (!root || !isWorkspaceRoot(root)) return;
    if (flightIsHere()) abortSession("stop");
    persist();
    cancelEdit();
    clearPendingImage();
    const chat = emptyChat("code", rootId);
    store.chats.unshift(chat);
    store.activeId = chat.id;
    messages = cloneMessages(chat.messages);
    expandWorkspace(rootId);
    persist();
    resetRecall();
    renderLog();
    refreshFiles();
    hideHistoryMenu();
    hideMoreMenu();
    input.focus();
  }

  function startNewChat() {
    if (flightIsHere()) abortSession("stop");
    persist();
    cancelEdit();
    clearPendingImage();
    if (activeMode() === "code") {
      const chat = addCodeWorkspace();
      store.activeId = chat.id;
      messages = cloneMessages(chat.messages);
      persist();
      resetRecall();
      renderLog();
      filesSelected = "";
      switchWorkspaceTabs(activeWorkspaceId());
      refreshFiles();
      hideHistoryMenu();
      input.focus();
      return;
    }
    if (!hasUserTurn({ messages })) {
      resetRecall();
      renderLog();
      input.focus();
      return;
    }
    const chat = emptyChat("chat");
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
          ? "Delete all saved Code workspaces for this account?"
          : "Delete all saved Chat conversations for this account?",
        yes: "Delete all",
        no: "Cancel",
      });
      if (!yes) return;
    }
    if (inFlight && doomed.some((item) => item.id === flightChatId)) {
      abortSession("stop");
    }
    cancelEdit();
    clearPendingImage();
    doomed.forEach((item) => {
      if (isWorkspaceRoot(item)) dropWorkspace(item.id);
    });
    store.chats = store.chats.filter((item) => chatMode(item) !== mode);
    const chat = mode === "code" ? addCodeWorkspace() : emptyChat(mode);
    if (mode !== "code") store.chats.unshift(chat);
    store = {
      version: 1,
      activeId: chat.id,
      chats: store.chats,
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
    historyItems = listedChats().filter((item) => !isWorkspaceRoot(item));
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
      const label = isWorkspaceRoot(item)
        ? workspaceDisplayTitle(item)
        : (item.title || "New chat");
      main.innerHTML = `<span class="history-title">${TabbyUI.escapeHtml(label)}</span><span class="slash-hint">${TabbyUI.escapeHtml(when)}</span>`;
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
      filesMoreMenu &&
      filesMoreBtn &&
      !filesMoreMenu.hidden &&
      !filesMoreMenu.contains(target) &&
      !filesMoreBtn.contains(target)
    ) {
      hideFilesMoreMenu();
    }
    if (
      filesUploadMenu &&
      filesUploadBtn &&
      !filesUploadMenu.hidden &&
      !filesUploadMenu.contains(target) &&
      !filesUploadBtn.contains(target)
    ) {
      hideUploadMenu();
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
    if (
      agentMenu &&
      agentBtn &&
      !agentMenu.hidden &&
      !agentMenu.contains(target) &&
      !agentBtn.contains(target)
    ) {
      hideAgentMenu();
    }
  }

  function editorHasFocus() {
    const el = document.activeElement;
    return Boolean(
      el &&
        editorCol &&
        !editorCol.hidden &&
        (editorCol.contains(el) || (editorPane && editorPane.contains(el)))
    );
  }

  function codeViewActive() {
    return !root.hidden && activeMode() === "code";
  }

  function shouldSkipAgentCycle(event) {
    if (!menu.hidden && menuItems.length) return true;
    const el = event.target;
    if (!el || el === input) return false;
    if (agentWrap && agentWrap.contains(el)) return false;
    if (el.isContentEditable) return true;
    const tag = String(el.tagName || "").toLowerCase();
    if (tag === "textarea" || tag === "select") return true;
    if (tag === "input") {
      const type = String(el.type || "text").toLowerCase();
      return type !== "button" && type !== "checkbox" && type !== "radio"
        && type !== "file" && type !== "submit" && type !== "reset"
        && type !== "hidden" && type !== "range";
    }
    if (termPane && !termPane.hidden && termPane.contains(el)) return true;
    return false;
  }

  function onCodeShortcut(event) {
    if (event.repeat || event.isComposing || !codeViewActive()) return;
    if (document.querySelector(".dialog-modal")) return;
    const backquote = event.code === "Backquote" || event.key === "`" || event.key === "~";
    if ((event.ctrlKey || event.metaKey) && !event.altKey && backquote) {
      event.preventDefault();
      event.stopPropagation();
      toggleTerm();
      return;
    }
    if (
      event.key === "Tab" &&
      event.shiftKey &&
      !event.ctrlKey &&
      !event.metaKey &&
      !event.altKey
    ) {
      if (shouldSkipAgentCycle(event)) return;
      event.preventDefault();
      event.stopPropagation();
      cycleCodeAgent();
    }
  }

  function onGlobalKey(event) {
    if (event.key === "Escape") {
      const cropTab = activeTabRow();
      if (cropTab && cropTab.cropping) {
        cancelCrop(cropTab);
        event.preventDefault();
        return;
      }
      if (cropTab && cropTab.punching) {
        cancelPunch(cropTab);
        event.preventDefault();
        return;
      }
      if (cropTab && cropTab.resizing) {
        cancelResize(cropTab);
        event.preventDefault();
        return;
      }
      if (editorFindBar && !editorFindBar.hidden) {
        closeEditorFind();
        event.preventDefault();
        return;
      }
      if (findBar && !findBar.hidden) {
        closeFind();
        event.preventDefault();
        return;
      }
      if (stopMic()) {
        event.preventDefault();
        return;
      }
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
      if (inFlight && flightIsHere() && !input.value.trim()) {
        abortSession("stop");
        event.preventDefault();
      }
      return;
    }
    if (event.key === "Enter" && !event.shiftKey && !event.ctrlKey && !event.metaKey && !event.altKey) {
      const cropTab = activeTabRow();
      if (cropTab && (cropTab.cropping || cropTab.punching || cropTab.resizing)) {
        const tag = String((event.target && event.target.tagName) || "").toLowerCase();
        const resizeField = event.target.closest("[data-resize-w],[data-resize-h]");
        if (
          resizeField ||
          (tag !== "textarea" && tag !== "input" && tag !== "select" && !(event.target && event.target.isContentEditable))
        ) {
          event.preventDefault();
          if (cropTab.cropping) applyCrop(cropTab);
          else if (cropTab.punching) applyPunch(cropTab);
          else applyResize(cropTab);
          return;
        }
      }
    }
    if (previewHasFocus(event.target) && (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "t") {
      event.preventDefault();
      newBlankBrowserTab();
      return;
    }
    if (previewHasFocus(event.target) && (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "w") {
      event.preventDefault();
      closeBrowserTab(activeBrowserTab);
      return;
    }
    if (previewHasFocus(event.target) && (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "l") {
      event.preventDefault();
      if (previewUrlInput) {
        previewUrlInput.focus();
        previewUrlInput.select();
      }
      return;
    }
    if (previewHasFocus(event.target) && event.altKey && event.key === "ArrowLeft") {
      event.preventDefault();
      postToActivePreview("back");
      return;
    }
    if (previewHasFocus(event.target) && event.altKey && event.key === "ArrowRight") {
      event.preventDefault();
      postToActivePreview("forward");
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
    if ((event.ctrlKey || event.metaKey) && !event.shiftKey && event.key.toLowerCase() === "f") {
      event.preventDefault();
      if (editorHasFocus()) openEditorFind();
      else openFind();
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
    const list = listedChats().filter((item) => !isWorkspaceRoot(item));
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
    return messages
      .filter((item) => item.role === "user" && !isHiddenUserTurn(item))
      .map((item) => item.content);
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
        comment.includes("tabby-stack-queue:") ||
        comment.includes("tabby-context-usage:")
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
      if (json.usage) onEvent({ usage: json.usage });
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
        applyStackOccupancy(data, working, kind);
        const queue = data && data.stack_queue;
        if (queue && queue.queued && (!queue.mine || stackWaiting)) {
          return;
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
  const queuedByChat = Object.create(null);
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
    if (waitingMark) waitingMark.textContent = "Queued";
    startStackWaitClock();
    paintStackWaitElapsed();
    if (waitingBar) waitingBar.hidden = false;
    if (working) {
      working.setActivity("Queued", { processing: true, note: stackWaitHint });
    }
    paintCompose();
  }

  function applyStackOccupancy(data, working, kind) {
    const queue = data && data.stack_queue;
    const queued = Boolean(queue && queue.queued);
    const mine = Boolean(queue && queue.mine);
    const here = flightIsHere();
    const live = working || (here ? flightWorking : null);
    if (queued && !(mine && here && !stackWaiting)) {
      showStackQueue((queue && queue.hint) || "", live);
      return;
    }
    if (!stackWaiting) {
      if (waitingBar) waitingBar.hidden = true;
      return;
    }
    hideStackQueue(live, {
      label: kind === "image" ? "Starting the picture" : "Thinking",
      processing: kind === "image",
    });
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
    let idleFails = 0;
    while (kind === "restart" || Date.now() < deadline) {
      try {
        const data = await TabbyUI.api("status");
        rememberGpu(data);
        const name = (data && data.switch_target) || target;
        const nextKind = data && data.restarting ? "restart" : kind;
        if (statusIsBusy(data)) {
          sawBusy = true;
          idleFails = 0;
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
        } else if (sawBusy && kind !== "restart") {
          // Reload finished but no model came up (VRAM fail after Comfy).
          // Do not keep the composer locked until the 4-minute deadline.
          idleFails += 1;
          if (idleFails >= 2) {
            if (working) {
              working.setActivity("Load failed", {
                processing: false,
                note: "The model did not come back. Try switch to qwen, or restart.",
              });
            }
            return false;
          }
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

  function onGpuStatus(event) {
    const data = event && event.detail;
    rememberGpu(data);
    paintActiveContext();
    applyStackOccupancy(data);
    if (modelWait || !statusIsBusy(data) || (data && data.down)) return;
    const target = data.switch_target || (comfyIsStarting(data) ? "comfy" : "");
    const kind = data.restarting ? "restart" : "switch";
    ensureModelWait(null, { kind, target });
  }

  function stopGatePoll() {
    if (!gateTicker) return;
    clearInterval(gateTicker);
    gateTicker = null;
  }

  function abortSession(kind) {
    stopKind = kind || "stop";
    TabbyUI.api("chat", { method: "POST", body: { cancel: true } }).catch(() => {});
    if (abortController) abortController.abort();
  }

  function flightIsHere() {
    return Boolean(inFlight && flightChatId && store.activeId === flightChatId);
  }

  function flightChatTitle() {
    const chat = store.chats.find((item) => item.id === flightChatId);
    const title = String((chat && chat.title) || "").replace(/\s+/g, " ").trim();
    return title || "another chat";
  }

  function queuedTextFor(chatId) {
    return String(queuedByChat[chatId] || "").trim();
  }

  function takeQueue(chatId) {
    const id = chatId || flightChatId || store.activeId;
    const text = queuedTextFor(id);
    delete queuedByChat[id];
    return text;
  }

  function queueFollowup(text, chatId) {
    const id = chatId || store.activeId;
    if (!id) return;
    queuedByChat[id] = String(text || "").trim();
    paintCompose();
  }

  function clearQueue(chatId) {
    const id = chatId || store.activeId;
    if (id) delete queuedByChat[id];
  }

  function paintCompose() {
    if (form) form.classList.toggle("is-loading", modelLoading);
    if (waitingBar) waitingBar.hidden = modelLoading || !stackWaiting;
    const here = flightIsHere();
    const away = Boolean(inFlight && !here);
    if (flightAwayBar) {
      flightAwayBar.hidden = modelLoading || !away;
      if (away && flightAwayText) {
        flightAwayText.textContent = `A reply is still running in “${flightChatTitle()}”. Switch back to see progress.`;
      }
    }
    if (modelLoading) {
      const queuedText = queuedTextFor(store.activeId);
      if (queueBar) queueBar.hidden = !queuedText;
      if (queueTextEl) queueTextEl.textContent = queuedText;
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
      if (agentBtn) agentBtn.disabled = true;
      paintCodeAgent();
      if (editBar) editBar.hidden = pendingEditIndex < 0;
      return;
    }
    input.disabled = false;
    if (loadingBar) loadingBar.hidden = true;
    const queuedText = queuedTextFor(store.activeId);
    const action = tabbyChatComposeAction(here, input.value, queuedText);
    const hasQueue = Boolean(queuedText);
    if (queueBar) queueBar.hidden = !hasQueue || away;
    if (queueTextEl) queueTextEl.textContent = queuedText;
    if (steerBtn) {
      steerBtn.hidden = !action.showSteer;
      steerBtn.disabled = !(here && hasQueue);
    }
    if (!sendBtn) return;
    sendBtn.disabled = away;
    sendBtn.classList.toggle("primary", action.mode !== "stop");
    sendBtn.classList.toggle("danger", action.mode === "stop");
    sendBtn.classList.toggle("is-stop", action.mode === "stop");
    sendBtn.setAttribute("aria-label", away ? "Busy" : action.label);
    if (action.mode === "stop") {
      sendBtn.innerHTML = `<span class="chat-stop-icon" aria-hidden="true"></span>${action.label}`;
    } else {
      sendBtn.textContent = action.label;
    }
    input.placeholder = away
      ? `A reply is still running in “${flightChatTitle()}”. Switch back to see progress.`
      : here
        ? hasQueue
          ? "Session running. Steer the queued message or type a replacement."
          : "Session running. Type a follow-up to queue it."
        : comfyOwnsGpu()
          ? "Describe a picture, or type a question to switch back to the LLM."
          : activeMode() === "code"
            ? codePlaceholder()
            : DEFAULT_PLACEHOLDER;
    if (agentBtn) agentBtn.disabled = Boolean(modelLoading || away);
    paintCodeAgent();
    if (editBar) editBar.hidden = pendingEditIndex < 0;
    if (sessionRestoring) sendBtn.disabled = true;
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
    chat.title = titleFromMessages(chat.messages, chat);
    chat.updatedAt = Date.now();
    persist();
  }

  async function refreshChatFromServer(chatId) {
    try {
      const incoming = await TabbyUI.api("chats");
      store = normalizeStore(incoming);
      const chat = store.chats.find((item) => item.id === chatId) || activeChat();
      if (chat && !isWorkspaceRoot(chat)) {
        store.activeId = chat.id;
        messages = cloneMessages(chat.messages);
      }
      renderLog();
      paintToolbar();
      renderSidebar();
    } catch {
      /* ignore */
    }
  }

  function liveMessages(chatId) {
    if (!chatId || chatId === store.activeId) return messages;
    const chat = store.chats.find((item) => item.id === chatId);
    if (!chat) return messages;
    if (!Array.isArray(chat.messages)) chat.messages = [];
    return chat.messages;
  }

  function outboundMessagesFor(chatId) {
    return liveMessages(chatId)
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

  function touchChat(chatId) {
    const chat = store.chats.find((item) => item.id === chatId);
    if (!chat || isWorkspaceRoot(chat)) return;
    chat.updatedAt = Date.now();
  }

  async function send(text, opts) {
    const replay = Boolean(opts && opts.replay);
    const resume = Boolean(opts && opts.resume);
    const chatId = (opts && opts.chatId) || flightChatId || store.activeId;
    flightChatId = chatId;
    const targetChat = store.chats.find((item) => item.id === chatId);
    const sendAgent = chatMode(targetChat) === "code"
      ? normalizeAgent((opts && opts.agent) || codeAgent)
      : "";
    const viewing = store.activeId === chatId;
    abortController = new AbortController();
    const outboundText = expandSlash(text);
    const list = liveMessages(chatId);
    if (resume) {
      const prompt = String((opts && opts.prompt) || "").trim();
      if (prompt && !hasUserTurn({ messages: list })) {
        list.push({ role: "user", content: prompt, createdAt: Date.now() });
        touchChat(chatId);
        persist();
      }
      if (viewing) renderLog();
    } else if (!replay) {
      if (pendingEditIndex >= 0 && viewing) {
        const idx = pendingEditIndex;
        pendingEditIndex = -1;
        if (editBar) editBar.hidden = true;
        messages = messages.slice(0, idx);
        if (!messages.some((item) => item.role === "system")) messages.unshift({ ...SYSTEM });
      }
      const userItem = { role: "user", content: outboundText, createdAt: Date.now() };
      if ((opts && opts.hidden) || isBuildPromptText(outboundText)) userItem.hidden = true;
      if (viewing && pendingImage) {
        userItem.imageData = pendingImage.dataUrl;
        userItem.imagePreview = pendingImage.preview || pendingImage.dataUrl;
        userItem.imageName = pendingImage.name;
      }
      if (viewing && pendingFiles.length) {
        userItem.attachedFiles = pendingFiles.map((file) => ({ ...file }));
      }
      list.push(userItem);
      if (viewing) {
        clearPendingImage();
        touchActive();
        persist();
        renderLog();
      } else {
        if (targetChat && !targetChat.titleLocked) {
          targetChat.title = titleFromMessages(list, targetChat);
        }
        touchChat(chatId);
        persist();
      }
    } else if (viewing) {
      persist();
      renderLog();
    } else {
      persist();
    }
    const activity = resume
      ? {
        label: "Thinking",
        kind: (opts && opts.kind) || "chat",
        processing: (opts && opts.kind) === "image",
      }
      : activityFromPrompt(outboundText);
    const working = addWorkingReply(activity);
    flightWorking = working;
    const poll = startStatusPoll(working, activity.kind);
    let assembled = "";
    let reasoning = "";
    let elapsedSec = null;
    let statusLabel = "";
    const body = resume
      ? { resume: true, conversation_id: chatId, stream: true }
      : { messages: outboundMessagesFor(chatId), stream: true, conversation_id: chatId };
    if (!resume && settings.temperature != null) body.temperature = settings.temperature;
    if (!resume && sendAgent) {
      body.mode = "code";
      body.chat_id = workspaceId(targetChat) || activeWorkspaceId();
      body.agent = sendAgent;
    }
    await persist();
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
      const unavailable = response.status === 502 || response.status === 503 || response.status === 504;
      if (!response.ok) {
        let data = "";
        if (type.includes("application/json")) {
          data = await response.json().catch(() => ({}));
        } else {
          data = await response.text().catch(() => "");
        }
        const msg = TabbyUI.httpErrorMessage
          ? TabbyUI.httpErrorMessage(response, data)
          : (unavailable ? `API unavailable (${response.status})` : "Chat failed");
        if (unavailable) {
          activity.kind = "restart";
        } else {
          throw new Error(msg);
        }
      } else if (type.includes("text/html")) {
        activity.kind = "restart";
      } else if (type.includes("application/json")) {
        const data = await response.json();
        assembled = data.choices?.[0]?.message?.content || data.message || JSON.stringify(data);
        reasoning = data.choices?.[0]?.message?.reasoning_content || "";
        if (reasoning) working.setReasoning(reasoning);
        if (assembled) working.setAnswer(assembled);
        if (data.usage) applyUsage(data.usage, chatId);
      } else {
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buf = "";
        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          buf += decoder.decode(value, { stream: true });
          if (TabbyUI.looksLikeHtml && TabbyUI.looksLikeHtml(buf) && !assembled) {
            activity.kind = "restart";
            break;
          }
          buf = consumeSseBuffer(buf, (event) => {
            if (event.usage) applyUsage(event.usage, chatId);
            if (event.comment && event.comment.includes("tabby-context-usage:")) {
              const raw = String(event.comment)
                .split(/\r?\n/)
                .map((line) => line.trim())
                .filter((line) => /tabby-context-usage:/i.test(line))
                .pop() || "";
              const json = raw.replace(/^[\s\S]*tabby-context-usage:\s*/i, "");
              try {
                applyUsage(JSON.parse(json), chatId);
              } catch {
                /* ignore */
              }
            }
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
              if (chatsShareWorkspace(chatId)) refreshFilesSoon();
              if (/^(?:Writing|Editing|Deleting|Optimizing|Renaming) \S/.test(label) && chatsShareWorkspace(chatId)) {
                const written = label.replace(/^(?:Writing|Editing|Deleting|Optimizing|Renaming)\s+/, "").split(/\s/)[0];
                if (isChangePath(written)) {
                  reloadPreviewIfNeeded(written);
                  if (!/^Deleting\b/.test(label)) noteAgentWrite(written);
                }
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
      } else if (TabbyUI.looksLikeHtml && TabbyUI.looksLikeHtml(err && err.message)) {
        activity.kind = "restart";
      } else {
        assembled = assembled || `Error: ${err.message}`;
      }
    }
    if (TabbyUI.looksLikeHtml && TabbyUI.looksLikeHtml(assembled)) {
      assembled = "";
      activity.kind = "restart";
    }
    let stoppedEmpty = false;
    poll.stop();
    hideStackQueue();
    const waitingOnModel = activity.kind === "switch" || activity.kind === "restart";
    if (waitingOnModel) {
      await ensureModelWait(working, activity);
    }
    stoppedEmpty = Boolean(stopKind) && !waitingOnModel && !String(assembled || "").trim() && !reasoning;
    if (resume && !stopKind && !String(assembled || "").trim() && !reasoning) {
      working.discard();
      await refreshChatFromServer(chatId);
    } else if (stoppedEmpty) {
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
      if (sendAgent === "ask" || sendAgent === "plan") item.agent = sendAgent;
      const last = messages.length ? messages[messages.length - 1] : null;
      const already = Boolean(
        last && last.role === "assistant" && String(last.content || "") === assembled
      );
      if (!already) appendAssistantToChat(chatId, item);
      if (store.activeId === chatId && !stoppedEmpty && working.node && working.node.isConnected) {
        attachMsgActions(working.node, "assistant", messages.length - 1, assembled);
        attachPlanBuild(working.node, messages.length - 1);
        stickLog();
      }
    } else if (store.activeId === chatId) {
      persist();
    }
    if (flightWorking === working) flightWorking = null;
    if (chatMode(store.chats.find((item) => item.id === chatId)) === "code") {
      if (chatsShareWorkspace(chatId)) refreshFiles();
    }
  }

  async function runLoop(firstText, opts) {
    if (modelLoading && !loopBusy) return;
    if (loopBusy) {
      if (modelLoading) return;
      if (firstText && !(opts && opts.replay) && flightIsHere()) queueFollowup(firstText);
      return;
    }
    loopBusy = true;
    flightChatId = store.activeId;
    inFlight = true;
    paintCompose();
    renderSidebar();
    let filesTicker = 0;
    if (activeMode() === "code") {
      refreshFilesSoon();
      filesTicker = setInterval(() => {
        if (chatsShareWorkspace(flightChatId)) refreshFilesSoon();
      }, 2500);
    }
    try {
      let next = firstText;
      let sendOpts = opts;
      if (opts && opts.resume) {
        await send("", Object.assign({}, opts, { chatId: flightChatId }));
        sendOpts = undefined;
        next = takeQueue(flightChatId);
      }
      while (next) {
        stopKind = "";
        await send(next, Object.assign({}, sendOpts || {}, { chatId: flightChatId }));
        sendOpts = undefined;
        if (stopKind === "steer") {
          next = takeQueue(flightChatId);
          continue;
        }
        if (stopKind === "stop") {
          if (queuedTextFor(flightChatId) && store.activeId === flightChatId && !input.value.trim()) {
            input.value = takeQueue(flightChatId);
          } else if (store.activeId === flightChatId) {
            clearQueue(flightChatId);
          }
          break;
        }
        await syncModelGate();
        if (chatMode(store.chats.find((item) => item.id === flightChatId)) === "code") {
          try {
            const data = await TabbyUI.api("status");
            if (!data || data.down || !data.tabby_model) {
              await ensureModelWait(null, {
                kind: "switch",
                target: (data && data.switch_target) || "llm",
              });
            }
          } catch {
            await ensureModelWait(null, { kind: "restart", target: "restart" });
          }
        }
        next = takeQueue(flightChatId);
      }
    } finally {
      if (filesTicker) clearInterval(filesTicker);
      inFlight = false;
      loopBusy = false;
      abortController = null;
      flightChatId = "";
      paintCompose();
      renderSidebar();
      input.focus();
    }
  }

  root.querySelector("#chat-new").addEventListener("click", startNewChat);
  root.querySelector("#chat-clear").addEventListener("click", clearHistory);

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    stopMic();
    if (modelLoading) return;
    if (sessionRestoring) return;
    if (!menu.hidden && menuItems[menuIndex]) {
      if (!applyCommand(menuItems[menuIndex])) return;
    }
    hideHistoryMenu();
    const text = input.value.trim();
    if (inFlight) {
      if (!flightIsHere()) return;
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
    if (!flightIsHere()) return;
    if (input.value.trim()) return;
    event.preventDefault();
    abortSession("stop");
  });
  steerBtn.addEventListener("click", () => {
    if (!flightIsHere() || !queuedTextFor(flightChatId)) return;
    abortSession("steer");
  });
  queueClearBtn.addEventListener("click", () => {
    clearQueue(store.activeId);
    paintCompose();
    input.focus();
  });
  if (flightBackBtn) {
    flightBackBtn.addEventListener("click", () => {
      if (!flightChatId) return;
      loadChat(flightChatId);
    });
  }
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
      if (
        activeMode() === "code" &&
        event.shiftKey &&
        !event.ctrlKey &&
        !event.metaKey &&
        !event.altKey
      ) {
        event.preventDefault();
        cycleCodeAgent();
        return;
      }
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
      hideAgentMenu();
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
    const root = isWorkspaceRoot(chat);
    const kidCount = root ? listedWorkspaceKids(id, listedChats()).length : 0;
    const expanded = root && workspaceExpanded(id);
    const items = [
      { label: "Open", run: () => (root ? openWorkspaceNav(id) : loadChat(id)) },
      root ? { label: "Expand", disabled: kidCount === 0 || expanded, run: () => setWorkspaceOpen(id, true) } : null,
      root ? { label: "Collapse", disabled: kidCount === 0 || !expanded, run: () => setWorkspaceOpen(id, false) } : null,
      root ? { label: "New chat in this workspace", run: () => startNestedChat(id) } : null,
      { label: "Rename", run: () => {
        if (!root) loadChat(id);
        beginRename(id);
      } },
      root
        ? { label: chat.pinned ? "Unpin workspace" : "Pin workspace", run: () => togglePin(id) }
        : (chatMode(chat) === "chat"
          ? { label: chat.pinned ? "Unpin" : "Pin", run: () => togglePin(id) }
          : null),
    ];
    if (!root) {
      items.push(
        { sep: true },
        { label: "Copy conversation", run: () => copyText(conversationMarkdown(id)) },
        { label: "Export markdown", run: () => exportChat(id) }
      );
    }
    items.push(
      { sep: true },
      { label: root ? "Delete workspace" : "Delete chat", danger: true, run: () => deleteChat(id) }
    );
    return items;
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
      row && row.kind === "image" ? { label: "Crop", run: () => beginCropPath(path) } : null,
      row && row.kind === "image" ? { label: "Resize", run: () => beginResizePath(path) } : null,
      row && row.kind === "image" ? { label: "Make transparent", run: () => beginPunchPath(path) } : null,
      { label: attached ? "Remove from chat" : "Add to chat", run: () => {
        attachProjectFile(path).catch((err) => addBubble("assistant", `Error: ${err.message}`));
      } },
      { sep: true },
      { label: "Copy path", run: () => copyText(path) },
      { label: "Insert path", run: () => insertCompose(path) },
      { label: "Download", run: () => saveUrl(fileUrl(activeWorkspaceId(), path), path.split("/").pop() || "file") },
      { sep: true },
      { label: "Rename", run: () => renameProjectFile(path) },
      { label: "Duplicate", run: () => duplicateProjectFile(path) },
      { label: "Delete", danger: true, run: () => deleteProjectFile(path) },
      row && row.page ? { sep: true } : null,
      row && row.page ? { label: "Open in preview", run: () => showPreview({ path }) } : null,
      row && row.page ? { label: "Open in new preview tab", run: () => showPreview({ path, newTab: true }) } : null,
      row && row.page ? { label: "Open in site", run: () => openSite() } : null,
    ];
  }

  function folderMenuItems(path) {
    const open = filesOpenFolders.has(path);
    return [
      { label: "New file", run: () => {
        filesFocusDir = path;
        createUserFile(path).catch((err) => addBubble("assistant", `Error: ${err.message}`));
      } },
      { label: "New folder", run: () => {
        createUserFolder(path).catch((err) => addBubble("assistant", `Error: ${err.message}`));
      } },
      { label: "Upload files", run: () => {
        pickLocalFiles({ dir: path }).catch((err) => addBubble("assistant", `Error: ${err.message}`));
      } },
      { label: "Upload folder", run: () => {
        pickLocalFiles({ dir: path, folder: true }).catch((err) => addBubble("assistant", `Error: ${err.message}`));
      } },
      { label: "From gallery", run: () => {
        filesFocusDir = path;
        pickAndUploadGallery().catch((err) => addBubble("assistant", `Error: ${err.message}`));
      } },
      { sep: true },
      { label: open ? "Collapse" : "Expand", run: () => toggleFolder(path) },
      { label: "Expand all", run: () => expandAllFolders() },
      { label: "Collapse all", run: () => collapseAllFolders() },
      { sep: true },
      { label: "Copy path", run: () => copyText(path) },
      { label: "Rename folder", run: () => renameProjectFolder(path) },
      { label: "Delete folder", danger: true, run: () => deleteProjectFolder(path) },
    ];
  }

  function filesPaneMenuItems() {
    return [
      { label: "New file", run: () => {
        createUserFile().catch((err) => addBubble("assistant", `Error: ${err.message}`));
      } },
      { label: "New folder", run: () => {
        createUserFolder().catch((err) => addBubble("assistant", `Error: ${err.message}`));
      } },
      { label: "Upload files", run: () => {
        pickLocalFiles({}).catch((err) => addBubble("assistant", `Error: ${err.message}`));
      } },
      { label: "Upload folder", run: () => {
        pickLocalFiles({ folder: true }).catch((err) => addBubble("assistant", `Error: ${err.message}`));
      } },
      { label: "From gallery", run: () => {
        pickAndUploadGallery().catch((err) => addBubble("assistant", `Error: ${err.message}`));
      } },
      { label: "Refresh", run: () => refreshFiles() },
      { sep: true },
      { label: "Expand all", disabled: !filesListing.length, run: () => expandAllFolders() },
      { label: "Collapse all", disabled: !filesListing.length, run: () => collapseAllFolders() },
      { sep: true },
      { label: "Download zip", disabled: !filesListing.length, run: () => downloadZip() },
      { label: "Clear files", danger: true, disabled: !filesListing.length, run: () => clearProjectFiles() },
    ];
  }

  function historyMenuItems(path, version) {
    return [
      { label: "Compare to latest", run: () => openHistoryTab(path, version) },
      { label: "Restore this version", run: () => restoreHistory(path, version.id) },
    ];
  }

  function changeMenuItems(path) {
    const tab = findTab(path);
    const busy = Boolean(tab && tab.busy);
    return [
      { label: "Open Changes", run: () => openChange(path) },
      { label: "Open File", run: () => openFileTab(path) },
      { label: "Copy path", run: () => copyText(path) },
      { sep: true },
      { label: "Discard Changes", danger: true, disabled: busy, run: () => discardChange(path) },
      { label: "Discard All Changes", danger: true, disabled: !changeRows().length, run: () => discardAllChanges() },
    ];
  }

  function changesPaneMenuItems() {
    return [
      { label: changesOpen ? "Collapse" : "Expand", run: () => setChangesOpen(!changesOpen) },
      { sep: true },
      { label: "Discard All Changes", danger: true, disabled: !changeRows().length, run: () => discardAllChanges() },
    ];
  }

  function historyPaneMenuItems() {
    return [
      { label: historyOpen ? "Collapse" : "Expand", run: () => setHistoryOpen(!historyOpen) },
    ];
  }

  function tabMenuItems(path) {
    if (!path) {
      return [
        { label: "Show chat", run: () => activateTab("") },
        openTabs.length ? { label: "Close all files", run: () => closeAllTabs() } : null,
      ];
    }
    if (isPreviewPath(path)) {
      return [
        { label: "Open", run: () => activateTab(path) },
        { label: "Show beside editor", run: () => dockPreview() },
        { label: "New tab", run: () => newBlankBrowserTab() },
        { label: "Reload", run: () => reloadPreviewIfNeeded() },
        { label: "Close", run: () => hidePreview() },
        { label: "Close others", disabled: openTabs.length < 2, run: () => closeOtherTabs(path) },
        { label: "Close all", run: () => closeAllTabs() },
      ];
    }
    const tab = findTab(path);
    if (isHistoryTab(tab)) {
      return [
        { label: "Open", run: () => activateTab(path) },
        { label: "Close", run: () => closeTab(path) },
        { label: "Close others", disabled: openTabs.length < 2, run: () => closeOtherTabs(path) },
        { label: "Close all", run: () => closeAllTabs() },
        { sep: true },
        { label: "Restore this version", run: () => restoreHistory(tab.filePath, tab.revId) },
      ];
    }
    return [
      { label: "Open", run: () => activateTab(path) },
      { label: "Close", run: () => closeTab(path) },
      { label: "Close others", disabled: openTabs.length < 2, run: () => closeOtherTabs(path) },
      { label: "Close all", run: () => closeAllTabs() },
      { sep: true },
      { label: "Copy path", run: () => copyText(path) },
      { label: "Download", run: () => saveUrl(fileUrl(activeWorkspaceId(), path), path.split("/").pop() || "file") },
      tab && tab.dirty ? { label: "Revert", run: () => { activateTab(path); revertTab(); } } : null,
    ];
  }

  function composeExtras() {
    return [
      { label: "Clear", disabled: !input.value, run: () => { setCompose(""); input.focus(); } },
      { label: "Attach image", run: () => { if (fileInput) fileInput.click(); } },
      { label: "From gallery", run: () => {
        pickAndAttachGallery().catch((err) => {
          addBubble("assistant", `Error: ${err.message}`);
        });
      } },
      activeMode() === "code"
        ? { label: "Attach project file", run: () => toggleAttachMenu() }
        : { label: "Attach files", run: () => {
          pickLocalFiles({ context: true }).catch((err) => {
            addBubble("assistant", `Error: ${err.message}`);
          });
        } },
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
    if (event.target.closest(".chat-editor-body.is-diff, .code-diff")) {
      const tab = activeTabRow();
      if (isHistoryTab(tab)) {
        openCtx(event, [
          { label: "Restore this version", run: () => restoreHistory(tab.filePath, tab.revId) },
          { label: "Close", run: () => closeTab(tab.path) },
        ]);
        return;
      }
    }
    if (field && field.classList.contains("chat-files-edit")) {
      const tab = activeTabRow();
      openCtx(event, TabbyUI.inputMenuItems(field, [
        { label: "Save", disabled: !tab || !tab.dirty || tab.busy, kbd: "Ctrl+S", run: () => saveTab() },
        { label: "Revert", disabled: !tab || !tab.dirty, run: () => revertTab() },
        tab ? { label: "Copy path", run: () => copyText(tab.path) } : null,
        tab ? { label: "Download", run: () => saveUrl(fileUrl(activeWorkspaceId(), tab.path), tab.path.split("/").pop() || "file") } : null,
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
    const group = event.target.closest(".chat-nav-group");
    if (group && navList.contains(group) && group.dataset.id) {
      openCtx(event, navMenuItems(group.dataset.id));
      return;
    }
    if (event.target.closest("#chat-nav-list, #chat-sidebar")) {
      openCtx(event, [
        { label: activeMode() === "code" ? "New workspace" : "New chat", run: () => startNewChat() },
        activeMode() === "code" ? { label: "New chat in this workspace", run: () => startNestedChat(activeWorkspaceId()) } : null,
        { label: activeMode() === "code" ? "Search workspaces" : "Search chats", kbd: "Ctrl+K", run: () => { if (searchEl) { searchEl.focus(); searchEl.select(); } } },
        { label: "Clear history", danger: true, run: () => clearHistory() },
      ]);
      return;
    }

    const fileRow = event.target.closest(".chat-file");
    if (fileRow && filesTree && filesTree.contains(fileRow) && fileRow.dataset.path) {
      if (fileRow.dataset.kind === "dir") {
        filesFocusDir = fileRow.dataset.path;
        openCtx(event, folderMenuItems(fileRow.dataset.path));
        return;
      }
      filesSelected = fileRow.dataset.path;
      filesFocusDir = fileDir(fileRow.dataset.path);
      paintFilesTree();
      refreshHistory();
      openCtx(event, fileMenuItems(fileRow.dataset.path));
      return;
    }
    const changeRow = event.target.closest(".chat-history");
    if (changeRow && filesChangesList && filesChangesList.contains(changeRow) && changeRow.dataset.path) {
      openCtx(event, changeMenuItems(changeRow.dataset.path));
      return;
    }
    if (event.target.closest("#chat-files-changes")) {
      openCtx(event, changesPaneMenuItems());
      return;
    }
    const historyRow = event.target.closest(".chat-history");
    if (historyRow && filesHistoryList && filesHistoryList.contains(historyRow) && filesSelected) {
      const version = filesHistory.find((row) => row.id === historyRow.dataset.id);
      if (version) {
        openCtx(event, historyMenuItems(filesSelected, version));
        return;
      }
    }
    if (event.target.closest("#chat-files-history")) {
      openCtx(event, historyPaneMenuItems());
      return;
    }
    if (historyRow && filesHistoryList && filesHistoryList.contains(historyRow) && filesSelected) {
      const version = filesHistory.find((row) => row.id === historyRow.dataset.id);
      if (version) {
        openCtx(event, historyMenuItems(filesSelected, version));
        return;
      }
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
      const pinned = pinTarget(store.activeId);
      openCtx(event, [
        { label: "Rename", run: () => beginRename() },
        pinned
          ? {
            label: isWorkspaceRoot(pinned)
              ? (pinned.pinned ? "Unpin workspace" : "Pin workspace")
              : (pinned.pinned ? "Unpin" : "Pin"),
            run: () => togglePin(pinned.id),
          }
          : null,
        activeMode() === "code" ? { label: "New chat in this workspace", run: () => startNestedChat(workspaceId(chat)) } : null,
        { label: "Copy conversation", run: () => copyText(conversationMarkdown()) },
        { label: "Export markdown", run: () => exportChat() },
        { sep: true },
        { label: isWorkspaceRoot(chat) ? "Delete this workspace" : "Delete this chat", danger: true, run: () => deleteChat(store.activeId) },
      ]);
      return;
    }

    if (event.target.closest("#chat-queue")) {
      openCtx(event, [
        { label: "Steer now", disabled: !(inFlight && queuedTextFor(flightChatId || store.activeId)), run: () => {
          if (steerBtn) steerBtn.click();
        } },
        { label: "Clear queue", run: () => {
          clearQueue(store.activeId);
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
        tab ? { label: "Download", run: () => saveUrl(fileUrl(activeWorkspaceId(), tab.path), tab.path.split("/").pop() || "file") } : null,
        { sep: true },
        { label: "Close file", disabled: !tab, run: () => closeTab(activeTab) },
      ]);
      return;
    }

    if (event.target.closest("#chat-preview")) {
      const strip = event.target.closest("[data-btab]");
      const tabId = strip && strip.dataset.btab;
      openCtx(event, [
        { label: "New tab", run: () => newBlankBrowserTab() },
        { label: "Close tab", run: () => closeBrowserTab(tabId || activeBrowserTab) },
        { sep: true },
        isPreviewTab(activeTabRow())
          ? { label: "Show beside editor", run: () => dockPreview() }
          : { label: "Open as tab", run: () => activateTab(PREVIEW_TAB) },
        { label: "Reload", run: () => reloadPreviewIfNeeded() },
        { label: "Close preview", run: () => hidePreview() },
      ]);
      return;
    }

    if (event.target.closest("#chat-log-wrap, #chat-empty")) {
      const picked = TabbyUI.selectedText();
      openCtx(event, [
        picked ? { label: "Copy selection", run: () => copyText(picked) } : null,
        { label: "Paste into compose", run: () => pasteCompose() },
        { label: activeMode() === "code" ? "New workspace" : "New chat", kbd: "Ctrl+Shift+O", run: () => startNewChat() },
        { label: "Keyboard shortcuts", run: () => showShortcuts() },
      ]);
    }
  }

  shell.addEventListener("contextmenu", onChatContextMenu);

  log.addEventListener("click", (event) => {
    const dlBtn = event.target.closest(".md-image-dl");
    if (dlBtn && log.contains(dlBtn)) {
      event.preventDefault();
      const href = dlBtn.getAttribute("data-href") || "";
      const name = dlBtn.getAttribute("data-name") || "image.png";
      if (href) saveUrl(href, name);
      return;
    }
    const imageLink = event.target.closest(".md-image-link");
    if (imageLink && log.contains(imageLink)) {
      event.preventDefault();
      openImageFromLink(imageLink);
      return;
    }
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
      if (act === "build") buildApprovedPlan(idx);
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
    if (pinningLog) return;
    followLog = nearBottom();
    paintJump();
  }, { passive: true });
  log.addEventListener("load", (event) => {
    if (event.target && event.target.tagName === "IMG" && followLog) stickLog();
  }, true);
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
    const group = event.target.closest(".chat-nav-group");
    if (tool) {
      const host = row || group;
      if (!host) return;
      const id = host.dataset.id;
      event.preventDefault();
      event.stopPropagation();
      if (tool.dataset.nav === "twist") {
        setWorkspaceOpen(id, !workspaceExpanded(id));
        return;
      }
      if (tool.dataset.nav === "thread") {
        startNestedChat(id);
        return;
      }
      if (tool.dataset.nav === "pin") togglePin(id);
      if (tool.dataset.nav === "rename") {
        const item = store.chats.find((chat) => chat.id === id);
        if (!isWorkspaceRoot(item)) loadChat(id);
        beginRename(id);
      }
      if (tool.dataset.nav === "delete") deleteChat(id);
      return;
    }
    if (row) {
      if (row.classList.contains("is-workspace")) {
        openWorkspaceNav(row.dataset.id);
        return;
      }
      loadChat(row.dataset.id);
      return;
    }
    if (group && group.dataset.id) openWorkspaceNav(group.dataset.id);
  });
  navList.addEventListener("keydown", (event) => {
    const row = event.target.closest(".chat-nav");
    if (!row || event.target.closest("[data-nav]")) return;
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      if (row.classList.contains("is-workspace")) {
        openWorkspaceNav(row.dataset.id);
        return;
      }
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
    if (act === "thread") startNestedChat(activeWorkspaceId());
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
  if (agentBtn && agentMenu) {
    agentBtn.addEventListener("click", () => {
      if (modelLoading || agentBtn.disabled) return;
      const open = agentMenu.hidden;
      hidePopovers();
      agentMenu.hidden = !open;
      agentBtn.setAttribute("aria-expanded", open ? "true" : "false");
    });
    agentMenu.addEventListener("click", (event) => {
      const btn = event.target.closest("[data-agent]");
      if (!btn) return;
      setCodeAgent(btn.dataset.agent);
    });
  }
  if (filesTree) {
    filesTree.addEventListener("dragstart", (event) => {
      const row = event.target.closest(".chat-file");
      if (!row || !row.dataset.path) return;
      event.dataTransfer.setData(TREE_DRAG, row.dataset.path);
      event.dataTransfer.setData("application/x-tabby-kind", row.dataset.kind || "file");
      event.dataTransfer.setData("text/plain", row.dataset.path);
      event.dataTransfer.effectAllowed = "move";
      row.classList.add("is-dragging");
    });
    filesTree.addEventListener("dragend", () => {
      filesTree.querySelectorAll(".is-dragging, .is-drop-target").forEach((node) => {
        node.classList.remove("is-dragging", "is-drop-target");
      });
      if (filesPane) filesPane.classList.remove("is-drop");
    });
    filesTree.addEventListener("click", async (event) => {
      const btn = event.target.closest("[data-file]");
      if (!btn) return;
      const row = btn.closest(".chat-file");
      const path = row && row.dataset.path;
      if (!path) return;
      if (btn.dataset.file === "toggle") {
        filesFocusDir = path;
        toggleFolder(path);
        return;
      }
      if (btn.dataset.file === "open") {
        filesFocusDir = fileDir(path);
        const fileRow = filesListing.find((item) => item.path === path);
        if (fileRow && fileRow.page && (event.ctrlKey || event.metaKey)) {
          showPreview({ path, newTab: previewOpen });
          return;
        }
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
        saveUrl(fileUrl(activeWorkspaceId(), path), path.split("/").pop() || "file");
        return;
      }
      if (btn.dataset.file === "delete") {
        deleteProjectFile(path);
      }
    });
    filesTree.addEventListener("keydown", (event) => {
      const row = event.target.closest(".chat-file");
      if (!row || !filesTree.contains(row) || row.dataset.kind !== "dir") return;
      const path = row.dataset.path;
      if (!path) return;
      if (event.key === "ArrowRight" && !filesOpenFolders.has(path)) {
        event.preventDefault();
        filesFocusDir = path;
        toggleFolder(path);
      } else if (event.key === "ArrowLeft" && filesOpenFolders.has(path)) {
        event.preventDefault();
        filesFocusDir = path;
        toggleFolder(path);
      }
    });
  }
  if (filesHistoryList) {
    filesHistoryList.addEventListener("click", (event) => {
      const btn = event.target.closest("[data-history]");
      if (!btn || !filesSelected) return;
      const row = btn.closest(".chat-history");
      const version = filesHistory.find((item) => item.id === (row && row.dataset.id));
      if (!version) return;
      if (btn.dataset.history === "open") {
        openHistoryTab(filesSelected, version);
        return;
      }
      if (btn.dataset.history === "restore") {
        restoreHistory(filesSelected, version.id);
      }
    });
  }
  if (filesChangesList) {
    filesChangesList.addEventListener("click", (event) => {
      const btn = event.target.closest("[data-change]");
      if (!btn) return;
      const row = btn.closest(".chat-history");
      const path = row && row.dataset.path;
      if (btn.dataset.change === "open" && path) openChange(path);
      if (btn.dataset.change === "discard" && path) discardChange(path);
    });
  }
  if (filesChangesToggle) {
    filesChangesToggle.addEventListener("click", () => setChangesOpen(!changesOpen));
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
      queueDrafts();
      if (window.TabbyLsp) window.TabbyLsp.didChange(tab.path, tab.text);
      if (editorFindBar && !editorFindBar.hidden) runEditorFind(editorFindQuery, false);
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
      if ((event.ctrlKey || event.metaKey) && event.code === "Space") {
        event.preventDefault();
        if (window.TabbyLsp) window.TabbyLsp.complete();
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
      if (btn.dataset.edit === "compare" && tab) {
        openChange(isHistoryTab(tab) ? tab.filePath : tab.path);
        return;
      }
      if (btn.dataset.edit === "restore" && isHistoryTab(tab)) {
        restoreHistory(tab.filePath, tab.revId);
        return;
      }
      if (btn.dataset.edit === "download" && tab) {
        saveUrl(fileUrl(activeWorkspaceId(), tab.path), tab.path.split("/").pop() || "file");
      }
      if (btn.dataset.edit === "retry-editor") remountEditor();
      if (btn.dataset.edit === "crop" && tab) beginCrop(tab);
      if (btn.dataset.edit === "crop-cancel" && tab) cancelCrop(tab);
      if (btn.dataset.edit === "crop-apply" && tab) applyCrop(tab);
      if (btn.dataset.edit === "punch" && tab) beginPunch(tab);
      if (btn.dataset.edit === "punch-cancel" && tab) cancelPunch(tab);
      if (btn.dataset.edit === "punch-apply" && tab) applyPunch(tab);
      if (btn.dataset.edit === "punch-contiguous" && tab) togglePunchContiguous(tab);
      if (btn.dataset.edit === "resize" && tab) beginResize(tab);
      if (btn.dataset.edit === "resize-cancel" && tab) cancelResize(tab);
      if (btn.dataset.edit === "resize-apply" && tab) applyResize(tab);
      if (btn.dataset.edit === "resize-lock" && tab) toggleResizeLock(tab);
    });
    editorPane.addEventListener("input", (event) => {
      const tab = activeTabRow();
      if (!tab) return;
      const slider = event.target.closest("[data-punch-tolerance]");
      if (slider) {
        setPunchTolerance(tab, slider.value);
        return;
      }
      if (event.target.closest("[data-resize-w]")) setResizeWidth(tab, event.target.value);
      if (event.target.closest("[data-resize-h]")) setResizeHeight(tab, event.target.value);
    });
  }
  if (filesSiteBtn) {
    filesSiteBtn.addEventListener("click", () => openSite());
  }
  if (filesPreviewBtn) {
    filesPreviewBtn.addEventListener("click", () => {
      if (previewOpen) hidePreview();
      else showPreview();
    });
  }
  if (previewTabBtn) {
    previewTabBtn.addEventListener("click", () => {
      if (isPreviewTab(activeTabRow())) dockPreview();
      else activateTab(PREVIEW_TAB);
    });
  }
  if (previewNewBtn) previewNewBtn.addEventListener("click", () => newBlankBrowserTab());
  if (previewBackBtn) previewBackBtn.addEventListener("click", () => postToActivePreview("back"));
  if (previewForwardBtn) previewForwardBtn.addEventListener("click", () => postToActivePreview("forward"));
  if (previewReloadBtn) previewReloadBtn.addEventListener("click", () => reloadPreviewIfNeeded());
  if (previewCloseBtn) previewCloseBtn.addEventListener("click", () => hidePreview());
  if (previewTabsEl) {
    previewTabsEl.addEventListener("click", (event) => {
      const item = event.target.closest("[data-btab]");
      if (!item) return;
      if (event.target.closest("[data-btab-close]")) {
        closeBrowserTab(item.dataset.btab);
        return;
      }
      activateBrowserTab(item.dataset.btab);
    });
    previewTabsEl.addEventListener("auxclick", (event) => {
      if (event.button !== 1) return;
      const item = event.target.closest("[data-btab]");
      if (!item) return;
      event.preventDefault();
      closeBrowserTab(item.dataset.btab);
    });
  }
  if (previewUrlInput) {
    previewUrlInput.addEventListener("keydown", (event) => {
      if (event.key !== "Enter") return;
      event.preventDefault();
      goPreviewAddress(previewUrlInput.value);
    });
  }
  if (filesTermBtn) {
    filesTermBtn.addEventListener("click", () => toggleTerm());
  }
  if (termCloseBtn) termCloseBtn.addEventListener("click", () => closeTerm());
  if (editorFindInput) {
    editorFindInput.addEventListener("input", () => runEditorFind(editorFindInput.value));
    editorFindInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        if (event.shiftKey) revealEditorFindHit(editorFindIndex - 1);
        else revealEditorFindHit(editorFindIndex + 1);
      }
    });
  }
  if (editorFindPrevBtn) editorFindPrevBtn.addEventListener("click", () => revealEditorFindHit(editorFindIndex - 1));
  if (editorFindNextBtn) editorFindNextBtn.addEventListener("click", () => revealEditorFindHit(editorFindIndex + 1));
  if (editorFindCloseBtn) editorFindCloseBtn.addEventListener("click", () => closeEditorFind());
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
      const open = Boolean(filesUploadMenu && filesUploadMenu.hidden);
      hideMoreMenu();
      hideFilesMoreMenu();
      hideAttachMenu();
      if (!filesUploadMenu) {
        pickLocalFiles({}).catch((err) => addBubble("assistant", `Error: ${err.message}`));
        return;
      }
      filesUploadMenu.hidden = !open;
      filesUploadBtn.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }
  if (filesUploadMenu) {
    filesUploadMenu.addEventListener("click", (event) => {
      const btn = event.target.closest("[data-upload]");
      if (!btn) return;
      hideUploadMenu();
      if (btn.dataset.upload === "gallery") {
        pickAndUploadGallery().catch((err) => {
          addBubble("assistant", `Error: ${err.message}`);
        });
        return;
      }
      pickLocalFiles({ folder: btn.dataset.upload === "folder" }).catch((err) => {
        addBubble("assistant", `Error: ${err.message}`);
      });
    });
  }
  if (filesMoreBtn && filesMoreMenu) {
    filesMoreBtn.addEventListener("click", () => {
      const open = filesMoreMenu.hidden;
      hideMoreMenu();
      hideAttachMenu();
      hideUploadMenu();
      filesMoreMenu.hidden = !open;
      filesMoreBtn.setAttribute("aria-expanded", open ? "true" : "false");
    });
    filesMoreMenu.addEventListener("click", (event) => {
      const btn = event.target.closest("[data-files-more]");
      if (!btn) return;
      hideFilesMoreMenu();
      const act = btn.dataset.filesMore;
      if (act === "refresh") refreshFiles();
      if (act === "zip") downloadZip();
      if (act === "clear") clearProjectFiles();
    });
  }
  if (filesHistoryToggle) {
    filesHistoryToggle.addEventListener("click", () => setHistoryOpen(!historyOpen));
  }
  if (filesPane) {
    filesPane.addEventListener("dragover", (event) => {
      if (treeHasDrag(event)) {
        event.preventDefault();
        event.dataTransfer.dropEffect = "move";
        filesPane.classList.add("is-drop");
        markTreeDrop(event);
        return;
      }
      if (Array.from(event.dataTransfer.types || []).includes("Files")) {
        event.preventDefault();
        filesPane.classList.add("is-drop");
      }
    });
    filesPane.addEventListener("dragleave", (event) => {
      if (event.relatedTarget && filesPane.contains(event.relatedTarget)) return;
      filesPane.classList.remove("is-drop");
      if (filesTree) filesTree.querySelectorAll(".chat-file.is-drop-target").forEach((node) => {
        node.classList.remove("is-drop-target");
      });
    });
    filesPane.addEventListener("drop", (event) => {
      event.preventDefault();
      filesPane.classList.remove("is-drop");
      if (filesTree) filesTree.querySelectorAll(".chat-file.is-drop-target").forEach((node) => {
        node.classList.remove("is-drop-target");
      });
      const dragged = treeDragPayload(event);
      if (dragged) {
        moveProjectItem(dragged.path, dragged.kind, dropDirFor(event)).catch((err) => {
          addBubble("assistant", `Error: ${err.message}`);
        });
        return;
      }
      const files = event.dataTransfer && event.dataTransfer.files;
      if ((!event.dataTransfer || !event.dataTransfer.items || !event.dataTransfer.items.length) && (!files || !files.length)) return;
      const row = event.target.closest(".chat-file");
      const dir = row && row.dataset.kind === "dir" ? row.dataset.path : "";
      itemsFromDataTransfer(event.dataTransfer).then((picked) => {
        if (!picked.length) return;
        return uploadLocalFiles(picked, { attach: false, open: picked.length === 1, dir });
      }).catch((err) => {
        addBubble("assistant", `Error: ${err.message}`);
      });
    });
  }
  if (findInput) {
    findInput.addEventListener("input", () => runFind(findInput.value));
    findInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        if (event.shiftKey) revealFindHit(findIndex - 1);
        else revealFindHit(findIndex + 1);
      }
    });
  }
  if (findPrevBtn) findPrevBtn.addEventListener("click", () => revealFindHit(findIndex - 1));
  if (findNextBtn) findNextBtn.addEventListener("click", () => revealFindHit(findIndex + 1));
  if (findCloseBtn) findCloseBtn.addEventListener("click", () => closeFind());
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
      if (btn.dataset.attach === "gallery") {
        pickAndAttachGallery().catch((err) => {
          addBubble("assistant", `Error: ${err.message}`);
        });
        return;
      }
      if (btn.dataset.attach === "context") {
        pickLocalFiles({ context: true }).catch((err) => {
          addBubble("assistant", `Error: ${err.message}`);
        });
        return;
      }
      if (btn.dataset.attach === "upload") {
        pickLocalFiles({ attach: true }).catch((err) => {
          addBubble("assistant", `Error: ${err.message}`);
        });
        return;
      }
      if (btn.dataset.attach === "upload-folder") {
        pickLocalFiles({ attach: true, folder: true }).catch((err) => {
          addBubble("assistant", `Error: ${err.message}`);
        });
        return;
      }
      if (btn.dataset.attach === "upload-gallery") {
        pickAndUploadGallery({ attach: true }).catch((err) => {
          addBubble("assistant", `Error: ${err.message}`);
        });
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
  function bindUploadInput(input) {
    if (!input) return;
    input.addEventListener("change", () => {
      const files = input.files;
      const attach = uploadWantsAttach;
      const context = uploadWantsContext;
      const dir = uploadTargetDir;
      uploadWantsAttach = false;
      uploadWantsContext = false;
      uploadTargetDir = "";
      const work = context
        ? attachLocalContextFiles(files)
        : uploadLocalFiles(files, { attach, open: !attach && files && files.length === 1, dir });
      work
        .catch((err) => {
          addBubble("assistant", `Error: ${err.message}`);
        })
        .finally(() => {
          input.value = "";
        });
    });
  }
  bindUploadInput(uploadInput);
  bindUploadInput(uploadDirInput);
  if (contextInput) {
    contextInput.addEventListener("change", () => {
      const files = contextInput.files;
      attachLocalContextFiles(files)
        .catch((err) => {
          addBubble("assistant", `Error: ${err.message}`);
        })
        .finally(() => {
          contextInput.value = "";
        });
    });
  }
  input.addEventListener("paste", (event) => {
    const items = event.clipboardData && event.clipboardData.items;
    if (!items) return;
    const files = [];
    for (const item of items) {
      if (item.kind !== "file") continue;
      const file = item.getAsFile();
      if (file) files.push(file);
    }
    if (!files.length) return;
    if (files.length === 1 && /^image\//.test(files[0].type || "")) {
      event.preventDefault();
      setPendingImageFromFile(files[0]).catch((err) => {
        addBubble("assistant", `Error: ${err.message}`);
      });
      return;
    }
    event.preventDefault();
    attachLocalContextFiles(files).catch((err) => {
      addBubble("assistant", `Error: ${err.message}`);
    });
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
    if ((!event.dataTransfer || !event.dataTransfer.items || !event.dataTransfer.items.length) && (!files || !files.length)) return;
    if (activeMode() === "code") {
      itemsFromDataTransfer(event.dataTransfer).then((picked) => {
        if (!picked.length) return;
        return uploadLocalFiles(picked, { attach: true, open: picked.length === 1 });
      }).catch((err) => {
        addBubble("assistant", `Error: ${err.message}`);
      });
      return;
    }
    itemsFromDataTransfer(event.dataTransfer).then((picked) => {
      if (!picked.length) return;
      const first = picked[0].file ? picked[0] : { file: picked[0], rel: picked[0].name };
      if (picked.length === 1 && looksLikeImageFile(first.file, first.rel || first.file.name)) {
        return setPendingImageFromFile(first.file);
      }
      return attachLocalContextFiles(picked);
    }).catch((err) => {
      addBubble("assistant", `Error: ${err.message}`);
    });
  });
  const Speech = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (micBtn && Speech) {
    micBtn.hidden = false;
    let rec = null;
    let live = false;
    let recGen = 0;
    function paintMic() {
      micBtn.classList.toggle("is-live", live);
      micBtn.setAttribute("aria-pressed", live ? "true" : "false");
      micBtn.setAttribute("aria-label", live ? "Stop recording" : "Voice input");
      micBtn.title = live ? "Listening — click to stop" : "Voice input";
      if (micStatus) micStatus.hidden = !live;
    }
    function voiceErrorText(code, fallback) {
      if (code === "not-allowed" || code === "NotAllowedError" || code === "PermissionDeniedError") {
        return "Microphone permission was denied. Allow the mic for this site, then try again.";
      }
      if (code === "audio-capture" || code === "NotFoundError" || code === "NotReadableError") {
        return "No microphone is available.";
      }
      if (code === "network" || code === "service-not-allowed") {
        return "This browser could not reach a speech service. Google Chrome on HTTPS or localhost usually works.";
      }
      if (code === "language-not-supported") return "Voice input does not support this language.";
      if (fallback) return fallback;
      return `Voice input failed (${code || "unknown"}).`;
    }
    function haltRec() {
      if (!rec) return;
      const active = rec;
      rec = null;
      active.onresult = null;
      active.onerror = null;
      active.onend = null;
      try {
        active.abort();
      } catch {
        try {
          active.stop();
        } catch {
          /* ignore */
        }
      }
    }
    stopMic = () => {
      if (!live && !rec) return false;
      live = false;
      recGen = 0;
      haltRec();
      paintMic();
      return true;
    };
    function armRec() {
      const session = new Speech();
      const gen = recGen;
      const startedAt = Date.now();
      rec = session;
      recGen += 1;
      session.continuous = true;
      session.interimResults = true;
      session.lang = navigator.language || "en-US";
      const prefix = input.value.replace(/\s+$/, "");
      session.onresult = (ev) => {
        if (rec !== session) return;
        let spoken = "";
        for (let i = 0; i < ev.results.length; i += 1) {
          spoken += ev.results[i][0].transcript;
        }
        if (!spoken) return;
        input.value = prefix ? `${prefix} ${spoken}` : spoken;
        resizeInput();
        paintCompose();
      };
      session.onerror = (ev) => {
        if (rec !== session) return;
        const code = ev && ev.error;
        if (code === "no-speech" || code === "aborted") return;
        live = false;
        recGen = 0;
        haltRec();
        paintMic();
        addBubble("assistant", `Error: ${voiceErrorText(code)}`);
      };
      session.onend = () => {
        if (rec === session) rec = null;
        if (!live) {
          paintMic();
          return;
        }
        if (gen === 0 && Date.now() - startedAt < 400) {
          live = false;
          recGen = 0;
          paintMic();
          addBubble("assistant", "Error: Voice input stopped immediately. Check the microphone, or try Google Chrome on HTTPS or localhost.");
          return;
        }
        try {
          armRec();
        } catch (err) {
          live = false;
          recGen = 0;
          paintMic();
          addBubble("assistant", `Error: ${voiceErrorText(err && err.name, err && err.message)}`);
        }
      };
      session.start();
    }
    micBtn.addEventListener("click", () => {
      if (live || rec) {
        stopMic();
        return;
      }
      if (input.disabled) return;
      if (!window.isSecureContext) {
        addBubble("assistant", "Error: Voice input needs HTTPS or localhost.");
        return;
      }
      live = true;
      paintMic();
      try {
        armRec();
      } catch (err) {
        live = false;
        haltRec();
        paintMic();
        addBubble("assistant", `Error: ${voiceErrorText(err && err.name, err && err.message)}`);
      }
    });
  }

  async function resumeLiveFlight() {
    let data;
    try {
      data = await TabbyUI.api("status");
    } catch {
      return;
    }
    rememberGpu(data);
    applyStackOccupancy(data);
    const queue = (data && data.stack_queue) || {};
    if (!queue.live) return;
    const chatId = String(queue.chat_id || "").trim();
    if (chatId) {
      const exists = store.chats.some((item) => item.id === chatId);
      if (exists) {
        if (store.activeId !== chatId) loadChat(chatId, true);
      } else {
        const mode = queue.kind === "code" ? "code" : "chat";
        const parent = mode === "code" ? activeWorkspaceId() : "";
        const chat = emptyChat(mode, parent);
        chat.id = chatId;
        store.chats.unshift(chat);
        store.activeId = chatId;
        messages = cloneMessages(chat.messages);
      }
    }
    runLoop("", {
      replay: true,
      resume: true,
      prompt: queue.prompt || "",
      kind: queue.kind || "chat",
    }).catch((err) => {
      addBubble("assistant", `Error: ${err.message}`);
      persist();
    });
  }

  window.addEventListener("beforeunload", warnDirtyUnload);
  window.addEventListener("message", onPreviewMessage);
  document.addEventListener("pointerdown", onPointerDownAway);
  document.addEventListener("keydown", onGlobalKey);
  document.addEventListener("keydown", onCodeShortcut, true);
  async function loadStore() {
    let incoming = null;
    let fetched = false;
    try {
      incoming = await TabbyUI.api("chats");
      fetched = true;
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
    restorePersistedListings();
    messages = cloneMessages(store.chats.find((chat) => chat.id === store.activeId).messages);
    persistReady = true;
    if (fetched || (incoming && Array.isArray(incoming.chats) && incoming.chats.some(hasUserTurn))) {
      persist();
    }
    renderLog();
    paintToolbar();
    renderSidebar();
    paintActiveContext();
    paintCompose();
    resizeInput();
    refreshFiles();
    startGatePoll();
    await resumeLiveFlight();
    sessionRestoring = false;
    paintCompose();
  }
  window.addEventListener("tabby-gpu-status", onGpuStatus);
  window.addEventListener("tabby-gallery-use", consumeGalleryUse);
  loadStore();
  consumeGalleryUse();
  return {
    pause() {
      stopMic();
      stopGatePoll();
      hideHistoryMenu();
      hideMoreMenu();
      setSidebarOpen(false);
    },
    resume() {
      startGatePoll();
      refreshFiles();
      consumeGalleryUse();
    },
    destroy() {
      stopMic();
      abortSession("stop");
      stopGatePoll();
      stopLoadingClock();
      hideStackQueue();
      if (filesRefreshTimer) clearTimeout(filesRefreshTimer);
      if (highlightFrame) cancelAnimationFrame(highlightFrame);
      if (pinLogRaf) cancelAnimationFrame(pinLogRaf);
      if (logSizeObs) logSizeObs.disconnect();
      persist();
      hideHistoryMenu();
      hideMoreMenu();
      document.removeEventListener("pointerdown", onPointerDownAway);
      document.removeEventListener("keydown", onGlobalKey);
      document.removeEventListener("keydown", onCodeShortcut, true);
      window.removeEventListener("tabby-gpu-status", onGpuStatus);
      window.removeEventListener("tabby-gallery-use", consumeGalleryUse);
      window.removeEventListener("beforeunload", warnDirtyUnload);
    },
  };
}

window.mountChat = mountChat;
window.tabbyChatComposeAction = tabbyChatComposeAction;
window.tabbyLooksLikeChatNotImage = tabbyLooksLikeChatNotImage;
