"""Registry-channel UI rendering helpers."""

from __future__ import annotations

import html


def render_login_html(heading: str, *, error: str = "") -> str:
    error_html = (
        f'<div class="error">{html.escape(error)}</div>'
        if error else
        ""
    )
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{html.escape(heading)} — Login</title>
    <style>
      :root {{
        color-scheme: dark;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
                     "Helvetica Neue", Arial, sans-serif;
      }}
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        min-height: 100vh;
        display: grid;
        place-items: center;
        background:
          radial-gradient(circle at top right, rgba(15, 118, 110, 0.22), transparent 30%),
          linear-gradient(180deg, #0f172a 0%, #111827 100%);
        color: #e5e7eb;
      }}
      .card {{
        width: min(320px, calc(100vw - 2rem));
        padding: 1.5rem;
        border-radius: 1rem;
        background: #1e293b;
        border: 1px solid rgba(148, 163, 184, 0.18);
        box-shadow: 0 18px 48px rgba(0, 0, 0, 0.32);
      }}
      h1 {{
        margin: 0 0 0.4rem;
        font-size: 1.2rem;
      }}
      p {{
        margin: 0 0 1rem;
        color: #cbd5e1;
        font-size: 0.92rem;
      }}
      label {{
        display: block;
        margin-bottom: 0.45rem;
        color: #cbd5e1;
        font-size: 0.92rem;
      }}
      input {{
        width: 100%;
        padding: 0.8rem 0.9rem;
        border-radius: 0.8rem;
        border: 1px solid rgba(148, 163, 184, 0.25);
        background: #0f172a;
        color: #f8fafc;
        margin-bottom: 0.9rem;
      }}
      button {{
        width: 100%;
        border: 0;
        border-radius: 0.8rem;
        padding: 0.85rem 1rem;
        background: #0f766e;
        color: #f8fafc;
        font: inherit;
        cursor: pointer;
      }}
      .error {{
        margin-bottom: 0.9rem;
        color: #fca5a5;
        font-size: 0.9rem;
      }}
    </style>
  </head>
  <body>
    <form class="card" method="post" action="/ui/login">
      <h1>{html.escape(heading)}</h1>
      <p>Enter the Registry UI password to continue.</p>
      {error_html}
      <label for="password">Password</label>
      <input id="password" name="password" type="password" autocomplete="current-password" required />
      <button type="submit">Log in</button>
    </form>
  </body>
</html>"""


def render_shell_html(*, title_text: str, heading_text: str, logout_link: str, csrf_token: str) -> str:
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <meta name="registry-csrf-token" content="{html.escape(csrf_token)}" />
    <link rel="icon" type="image/svg+xml" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><rect width='32' height='32' rx='6' fill='%230f766e'/><text x='16' y='22' font-size='18' font-family='sans-serif' fill='white' text-anchor='middle'>A</text></svg>">
    <title>{html.escape(title_text)}</title>
    <style>
      :root {{
        color-scheme: dark;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
                     "Helvetica Neue", Arial, sans-serif;
        background: #0d1321;
        color: #f5f3ee;
        --panel: rgba(12, 18, 33, 0.92);
        --panel-border: rgba(230, 194, 41, 0.24);
        --muted: rgba(245, 243, 238, 0.72);
        --accent: #e6c229;
        --green: #5ec57e;
        --amber: #f2b24f;
        --red: #ef7366;
        --muted-state: #7f8ba8;
      }}
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        padding: 2rem;
        background:
          radial-gradient(circle at top right, rgba(230, 194, 41, 0.16), transparent 28%),
          linear-gradient(180deg, #101820 0%, #0b1220 100%);
      }}
      header {{
        display: flex;
        flex-wrap: wrap;
        align-items: end;
        justify-content: space-between;
        gap: 1rem;
        margin-bottom: 1.5rem;
      }}
      h1, h2, h3 {{
        margin: 0;
      }}
      .subtle {{
        color: var(--muted);
        font-size: 0.95rem;
      }}
      .status-line {{
        min-height: 1.2rem;
        color: var(--muted);
        font-size: 0.9rem;
      }}
      .header-meta {{
        display: flex;
        flex-wrap: wrap;
        gap: 0.75rem;
        align-items: center;
        justify-content: flex-end;
      }}
      .nav-link {{
        color: var(--muted);
        text-decoration: none;
        font-size: 0.95rem;
      }}
      .nav-link:hover {{
        color: #f5f3ee;
      }}
      main {{
        display: grid;
        grid-template-columns: minmax(280px, 0.95fr) minmax(320px, 1fr) minmax(360px, 1.15fr) minmax(280px, 0.95fr);
        gap: 1rem;
      }}
      section {{
        min-height: 260px;
        background: var(--panel);
        border: 1px solid var(--panel-border);
        border-radius: 20px;
        padding: 20px;
        box-shadow: 0 16px 40px rgba(0, 0, 0, 0.28);
      }}
      .panel-header {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 0.75rem;
        margin-bottom: 0.9rem;
      }}
      .panel-header h2 {{
        font-size: 14px;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: var(--muted);
      }}
      .skills-panel {{
        grid-column: 1 / -1;
      }}
      .list {{
        display: grid;
        gap: 10px;
      }}
      .item {{
        padding: 12px 14px;
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 14px;
        background: rgba(255,255,255,0.03);
        cursor: pointer;
        transition: background 0.15s;
      }}
      .item:hover {{
        background: rgba(255, 255, 255, 0.08);
      }}
      .item-button {{
        width: 100%;
        text-align: left;
        color: inherit;
        padding: 12px 14px;
        border-color: rgba(255,255,255,0.08);
        background: rgba(255,255,255,0.03);
      }}
      .meta {{
        margin-top: 6px;
        font-size: 12px;
        color: var(--muted);
      }}
      .meta-row {{
        display: flex;
        flex-wrap: wrap;
        gap: 0.45rem;
        align-items: center;
      }}
      .badge {{
        display: inline-flex;
        align-items: center;
        gap: 0.28rem;
        padding: 2px 8px;
        border-radius: 999px;
        background: rgba(255,255,255,0.12);
        border: 1px solid rgba(255,255,255,0.16);
        font-size: 12px;
        color: #f5f3ee;
      }}
      .badge-connected  {{ background: #22c55e; color: #fff; border-color: transparent; }}
      .badge-degraded   {{ background: #f59e0b; color: #fff; border-color: transparent; }}
      .badge-standalone {{ background: #6b7280; color: #fff; border-color: transparent; }}
      .badge-offline    {{ background: #ef4444; color: #fff; border-color: transparent; }}
      .badge-pending    {{ background: #3b82f6; color: #fff; border-color: transparent; }}
      .badge-failed     {{ background: #ef4444; color: #fff; border-color: transparent; }}
      .badge-running    {{ background: #3b82f6; color: #fff; border-color: transparent; }}
      .badge-open       {{ background: #22c55e; color: #fff; border-color: transparent; }}
      .badge-cancelling {{ background: #f59e0b; color: #fff; border-color: transparent; }}
      .badge-completed  {{ background: #6b7280; color: #fff; border-color: transparent; }}
      .diag-info {{
        color: var(--muted);
      }}
      .diag-warning {{
        color: var(--amber);
      }}
      .diag-error {{
        color: var(--red);
      }}
      .toolbar {{
        display: flex;
        flex-wrap: wrap;
        gap: 0.6rem;
        align-items: center;
      }}
      button, select, textarea, input {{
        font: inherit;
      }}
      button {{
        cursor: pointer;
        border-radius: 0.75rem;
        border: 1px solid rgba(230, 194, 41, 0.35);
        background: rgba(230, 194, 41, 0.12);
        color: #f5f3ee;
        padding: 0.55rem 0.9rem;
      }}
      button.secondary {{
        border-color: rgba(255,255,255,0.18);
        background: rgba(255,255,255,0.06);
      }}
      button.danger {{
        border-color: rgba(239, 115, 102, 0.35);
        background: rgba(239, 115, 102, 0.12);
      }}
      button:disabled {{
        opacity: 0.45;
        cursor: not-allowed;
      }}
      .hidden {{
        display: none !important;
      }}
      .form {{
        display: grid;
        gap: 0.65rem;
        margin-bottom: 0.9rem;
        padding: 0.8rem;
        border-radius: 0.9rem;
        background: rgba(255,255,255,0.03);
        border: 1px solid rgba(255,255,255,0.08);
      }}
      .form label {{
        display: grid;
        gap: 0.35rem;
        font-size: 0.92rem;
        color: var(--muted);
      }}
      select, textarea, input {{
        width: 100%;
        border-radius: 0.75rem;
        border: 1px solid rgba(255,255,255,0.12);
        background: rgba(8, 12, 22, 0.9);
        color: #f5f3ee;
        padding: 0.7rem 0.8rem;
      }}
      textarea {{
        min-height: 7.5rem;
        resize: vertical;
      }}
      .editor-shell {{
        display: grid;
        gap: 0.75rem;
        margin-top: 0.9rem;
      }}
      .editor-actions {{
        display: flex;
        flex-wrap: wrap;
        gap: 0.6rem;
      }}
      .code-editor {{
        border: 1px solid rgba(255,255,255,0.12);
        border-radius: 0.85rem;
        overflow: hidden;
        background: rgba(8, 12, 22, 0.9);
      }}
      .code-editor .cm-editor {{
        min-height: 18rem;
      }}
      .code-editor .cm-scroller {{
        font-family: "SFMono-Regular", "JetBrains Mono", Consolas, monospace;
      }}
      .timeline {{
        display: flex;
        flex-direction: column;
        gap: 0.75rem;
        max-height: 32rem;
        overflow: auto;
        padding-right: 0.2rem;
      }}
      .timeline-item {{
        border-left: 3px solid rgba(230, 194, 41, 0.32);
        padding: 0.2rem 0 0.2rem 0.8rem;
      }}
      .timeline-item strong {{
        display: block;
        margin-top: 0.25rem;
      }}
      .timeline-body {{
        color: #dde4f0;
        font-size: 0.94rem;
        white-space: pre-wrap;
        margin-top: 0.25rem;
      }}
      .timeline-controls {{
        display: flex;
        flex-wrap: wrap;
        gap: 0.6rem;
        margin-top: 0.65rem;
      }}
      .inline-error {{
        color: var(--red);
        font-size: 0.88rem;
        margin-top: 0.35rem;
      }}
      .detail-actions {{
        display: grid;
        gap: 0.75rem;
        margin-top: 1rem;
      }}
      .detail-body {{
        display: grid;
        gap: 0.8rem;
      }}
      .detail-card {{
        padding: 0.9rem 1rem;
        border-radius: 0.9rem;
        border: 1px solid rgba(255,255,255,0.08);
        background: rgba(255,255,255,0.03);
      }}
      .empty {{
        color: var(--muted);
        padding: 1.2rem 0.2rem;
      }}
      .empty-state {{
        padding: 1.5rem;
        text-align: center;
        color: #888;
        font-size: 0.9rem;
        line-height: 1.6;
      }}
      .loading-state {{
        text-align: center;
        padding: 2rem;
        color: #888;
      }}
      .error-banner {{
        background: #fef2f2;
        border-left: 4px solid #ef4444;
        color: #991b1b;
        padding: 0.75rem 1rem;
        margin-bottom: 1rem;
        display: none;
      }}
      .skills-table {{
        width: 100%;
        border-collapse: collapse;
        font-size: 0.9rem;
      }}
      .skills-table th,
      .skills-table td {{
        padding: 0.65rem 0.5rem;
        border-bottom: 1px solid rgba(255,255,255,0.08);
        text-align: left;
        vertical-align: top;
      }}
      .skills-table th {{
        color: var(--muted);
        font-size: 12px;
        letter-spacing: 0.08em;
        text-transform: uppercase;
      }}
      .skill-row-disabled {{
        opacity: 0.68;
      }}
      .skill-status-disabled {{
        color: var(--red);
      }}
      .skill-status-overridden {{
        color: var(--amber);
      }}
      .skill-empty {{
        color: var(--muted);
        font-style: italic;
      }}
      @media (max-width: 1200px) {{
        main {{
          grid-template-columns: 1fr;
        }}
        .skills-panel {{
          grid-column: auto;
        }}
      }}
    </style>
  </head>
  <body>
    <div id="error-banner" class="error-banner" role="alert"></div>
    <header>
      <div>
        <h1>{html.escape(heading_text)}</h1>
        <div class="subtle">Live directory, routed work board, and shared conversation visibility for private bots.</div>
      </div>
      <div class="header-meta">
        <span id="refresh-indicator" class="subtle hidden">Refreshing…</span>
        <span id="last-updated" class="subtle">Waiting for first update</span>
        <span id="daily-usage" class="subtle"></span>
        <div id="ui-status" class="status-line"></div>
        {logout_link}
      </div>
    </header>
    <main>
      <section>
        <div class="panel-header">
          <h2>Bots</h2>
          <span class="subtle">Live directory</span>
        </div>
        <div id="bots" class="list"><div class="loading-state">Loading…</div></div>
      </section>
      <section>
        <div class="panel-header">
          <h2>Conversations</h2>
          <button id="new-conversation-button" type="button">New conversation</button>
        </div>
        <div id="new-conversation-form" class="form hidden">
          <label>
            Target bot
            <select id="new-conversation-target"></select>
          </label>
          <label>
            Message
            <textarea id="new-conversation-message" placeholder="Describe the work you want the bot to do."></textarea>
          </label>
          <div class="toolbar">
            <button id="start-conversation-button" type="button">Start</button>
            <button id="cancel-new-conversation-button" class="secondary" type="button">Cancel</button>
          </div>
        </div>
        <div id="conv-filter-bar" style="display:flex;gap:6px;padding:6px 8px;border-bottom:1px solid #333;">
          <input id="conv-search" type="text" placeholder="Search…"
            style="flex:1;min-width:0;background:#1e1e1e;color:#ccc;border:1px solid #444;
                   border-radius:4px;padding:4px 8px;font-size:12px;" />
          <select id="conv-status"
            style="background:#1e1e1e;color:#ccc;border:1px solid #444;border-radius:4px;
                   padding:4px 6px;font-size:12px;">
            <option value="">All status</option>
            <option value="running">running</option>
            <option value="done">done</option>
            <option value="failed">failed</option>
          </select>
          <select id="conv-date"
            style="background:#1e1e1e;color:#ccc;border:1px solid #444;border-radius:4px;
                   padding:4px 6px;font-size:12px;">
            <option value="">Any time</option>
            <option value="today">Today</option>
            <option value="7d">Last 7 days</option>
            <option value="30d">Last 30 days</option>
          </select>
        </div>
        <div id="conv-filter-count" style="font-size:11px;color:#888;padding:2px 8px;display:none;"></div>
        <div id="conversations" class="list"><div class="loading-state">Loading…</div></div>
      </section>
      <section>
        <div class="panel-header">
          <h2 id="detail-panel-title">Conversation Detail</h2>
          <button id="detail-back-button" class="secondary hidden" type="button">Back to list</button>
        </div>
        <div id="conversation-detail-empty" class="empty">Select a conversation to inspect its timeline and send follow-up messages.</div>
        <div id="conversation-detail" class="hidden">
          <div id="conversation-detail-header" class="list"></div>
          <div id="conversation-detail-body" class="detail-body">
            <div id="conversation-detail-timeline" class="timeline"></div>
          </div>
          <div id="conversation-detail-actions" class="detail-actions">
            <label>
              New message
              <textarea id="detail-message-text" placeholder="Add a follow-up message to this conversation."></textarea>
            </label>
            <div class="toolbar">
              <button id="detail-export-button" class="secondary" type="button">Export</button>
              <button id="detail-send-button" type="button">Send</button>
              <button id="detail-cancel-button" class="danger" type="button">Cancel conversation</button>
            </div>
          </div>
        </div>
      </section>
      <section>
        <div class="panel-header">
          <h2>Routed Tasks</h2>
          <span class="subtle">Delegated work board</span>
        </div>
        <div id="tasks" class="list"><div class="loading-state">Loading…</div></div>
      </section>
      <section class="skills-panel">
        <div class="panel-header">
          <h2>Runtime Skills</h2>
          <span class="subtle">Catalog, prompt preview, and conversation activation</span>
        </div>
        <div class="toolbar" style="margin-bottom: 0.9rem;">
          <input id="runtime-skill-create-name" type="text" placeholder="new-runtime-skill" />
          <button id="runtime-skill-create-button" type="button">Create draft</button>
          <input id="runtime-skill-search" type="text" placeholder="Search runtime skills…" />
          <button id="runtime-skill-search-button" type="button">Search</button>
          <button id="runtime-skill-reset-button" class="secondary" type="button">Reset</button>
        </div>
        <div id="runtime-skill-detail" class="detail-card hidden"></div>
        <div id="runtime-skills"><div class="loading-state">Loading…</div></div>
      </section>
      <section class="skills-panel">
        <div class="panel-header">
          <h2>Provider Guidance</h2>
          <span class="subtle">Draft, review, publish, and runtime preview</span>
        </div>
        <div class="toolbar" style="margin-bottom: 0.9rem;">
          <select id="provider-guidance-select">
            <option value="claude">claude</option>
            <option value="codex">codex</option>
          </select>
          <button id="provider-guidance-load-button" type="button">Load guidance</button>
        </div>
        <div id="provider-guidance-detail" class="detail-card hidden"></div>
      </section>
      <section class="skills-panel">
        <div class="panel-header">
          <h2>Capabilities</h2>
          <span class="subtle">Global routing kill switches</span>
        </div>
        <div id="capabilities"><div class="loading-state">Loading…</div></div>
      </section>
    </main>
    <script>
      const csrfToken = document.querySelector('meta[name="registry-csrf-token"]')?.content || "";
      const EMPTY_STATES = {{
        bots: "No bots connected yet. Start a bot in registry mode and it will appear here.<br><code>./octopus</code>",
        conversations: "No conversations yet. Send a message to your bot in Telegram to start.",
        tasks: "No routed tasks yet. Delegated tasks appear here in real time.",
        runtimeSkills: "No runtime skills matched the current filter.",
        capabilities: "No capabilities declared yet. Connect bots with advertised capabilities and they will appear here.",
      }};
      const REGISTRY_UI_ACTOR_KEY = "reg:ui";
      let bootstrapData = {{ bots: [], conversations: [], tasks: [] }};
      let usageSummary = {{ daily_total: {{ prompt_tokens: 0, completion_tokens: 0, cost_usd: 0 }}, by_conversation: [] }};
      let bootstrapLoaded = false;
      let runtimeSkillsLoaded = false;
      let capabilitiesLoaded = false;
      let providerGuidanceLoaded = false;
      let lastSuccessfulLoad = 0;
      let currentDetailKind = "";
      let currentDetailId = "";
      let currentConversationId = "";
      let currentConversationDetail = null;
      let runtimeCatalog = [];
      let currentRuntimeSkillDetail = null;
      let currentRuntimeSkillPreview = null;
      let currentRuntimeSkillLifecycle = null;
      let currentProviderGuidanceDetail = null;
      let currentProviderGuidancePreview = null;
      const delegationActionState = Object.create(null);
      const delegationActionError = Object.create(null);
      const registryEditors = Object.create(null);
      var _convSearchTimer = null;

      async function uiFetch(url, options = {{}}) {{
        const method = String(options.method || "GET").toUpperCase();
        const headers = new Headers(options.headers || {{}});
        if (!["GET", "HEAD", "OPTIONS"].includes(method) && csrfToken) {{
          headers.set("X-CSRF-Token", csrfToken);
        }}
        return fetch(url, {{
          ...options,
          headers,
          credentials: "same-origin",
        }});
      }}

      function requestHeaders(extra = {{}}) {{
        return extra;
      }}

      function escapeHtml(value) {{
        return String(value ?? "")
          .replace(/&/g, "&amp;")
          .replace(/</g, "&lt;")
          .replace(/>/g, "&gt;")
          .replace(/"/g, "&quot;")
          .replace(/'/g, "&#39;");
      }}

      function formatTime(value) {{
        if (!value) return "";
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) return value;
        return date.toLocaleString();
      }}

      function formatAgeSeconds(value) {{
        if (value === null || value === undefined || value === "") return "";
        const total = Math.max(0, Number(value || 0));
        if (!Number.isFinite(total)) return "";
        if (total < 60) return `${{Math.floor(total)}}s`;
        const minutes = Math.floor(total / 60);
        const seconds = Math.floor(total % 60);
        if (minutes < 60) return `${{minutes}}m ${{seconds}}s`;
        const hours = Math.floor(minutes / 60);
        const remMinutes = minutes % 60;
        if (hours < 24) return `${{hours}}h ${{remMinutes}}m`;
        const days = Math.floor(hours / 24);
        const remHours = hours % 24;
        return `${{days}}d ${{remHours}}h`;
      }}

      function formatUsageCount(value) {{
        return Number(value || 0).toLocaleString();
      }}

      function formatUsageCost(value) {{
        return new Intl.NumberFormat(undefined, {{
          style: "currency",
          currency: "USD",
          minimumFractionDigits: 2,
          maximumFractionDigits: 4,
        }}).format(Number(value || 0));
      }}

      function getBadgeClass(status) {{
        const s = String(status || "").toLowerCase().replace(/[^a-z]/g, "");
        const map = {{
          connected: "badge-connected",
          degraded: "badge-degraded",
          standalone: "badge-standalone",
          offline: "badge-offline",
          pending: "badge-pending",
          queued: "badge-pending",
          submitted: "badge-pending",
          failed: "badge-failed",
          partialfailed: "badge-failed",
          timedout: "badge-failed",
          cancelled: "badge-failed",
          running: "badge-running",
          open: "badge-open",
          cancelling: "badge-cancelling",
          completed: "badge-completed",
          healthy: "badge-connected",
          unhealthy: "badge-failed",
        }};
        return map[s] || "";
      }}

      function statusLabel(status) {{
        if (!status) return "Open";
        const value = String(status);
        const labels = {{
          partialfailed: "Delivery failed",
          timed_out: "Timed out",
        }};
        return labels[value] || value.replace(/_/g, " ").replace(/\\b\\w/g, c => c.toUpperCase());
      }}

      function ensureEditorHost(textarea) {{
        const hostId = `${{textarea.id}}-host`;
        let host = document.getElementById(hostId);
        if (!host) {{
          host = document.createElement("div");
          host.id = hostId;
          host.className = "code-editor hidden";
          textarea.insertAdjacentElement("afterend", host);
        }}
        return host;
      }}

      function editorValue(textareaId) {{
        const record = registryEditors[textareaId];
        if (record && record.view) {{
          return record.view.state.doc.toString();
        }}
        const textarea = document.getElementById(textareaId);
        return textarea ? textarea.value : "";
      }}

      function setEditorValue(textareaId, value) {{
        const text = String(value || "");
        const textarea = document.getElementById(textareaId);
        if (textarea) {{
          textarea.value = text;
        }}
        const record = registryEditors[textareaId];
        if (record && record.view) {{
          const current = record.view.state.doc.toString();
          if (current !== text) {{
            record.view.dispatch({{
              changes: {{ from: 0, to: current.length, insert: text }},
            }});
          }}
        }}
      }}

      function mountRichEditor(textareaId) {{
        const textarea = document.getElementById(textareaId);
        if (!textarea) return;
        const host = ensureEditorHost(textarea);
        const cm = window.__REGISTRY_CODEMIRROR__;
        if (!cm) {{
          textarea.classList.remove("hidden");
          host.classList.add("hidden");
          return;
        }}
        textarea.classList.add("hidden");
        host.classList.remove("hidden");
        const currentText = textarea.value || "";
        const existing = registryEditors[textareaId];
        if (existing && existing.host === host) {{
          const existingText = existing.view.state.doc.toString();
          if (existingText !== currentText) {{
            existing.view.dispatch({{
              changes: {{ from: 0, to: existingText.length, insert: currentText }},
            }});
          }}
          return;
        }}
        if (existing && existing.view) {{
          existing.view.destroy();
        }}
        host.replaceChildren();
        const updateListener = cm.EditorView.updateListener.of(update => {{
          if (!update.docChanged) return;
          const text = update.state.doc.toString();
          textarea.value = text;
        }});
        const state = cm.EditorState.create({{
          doc: currentText,
          extensions: [
            cm.lineNumbers(),
            cm.history(),
            cm.keymap.of([...cm.defaultKeymap, ...cm.historyKeymap]),
            cm.EditorView.lineWrapping,
            updateListener,
          ],
        }});
        const view = new cm.EditorView({{
          state,
          parent: host,
        }});
        registryEditors[textareaId] = {{ view, host }};
      }}

      function renderLifecycleHistory(revisions = [], approvals = []) {{
        const revisionRows = revisions.length
          ? revisions.map(item => `
              <tr>
                <td><strong>${{escapeHtml(item.version_label || item.revision_id || "")}}</strong></td>
                <td>${{escapeHtml(item.status || "")}}</td>
                <td>${{escapeHtml(item.created_by || "")}}</td>
                <td>${{escapeHtml(formatTime(item.created_at) || "")}}</td>
              </tr>
            `).join("")
          : `<tr><td colspan="4" class="skill-empty">No revisions yet.</td></tr>`;
        const approvalRows = approvals.length
          ? approvals.map(item => `
              <tr>
                <td><strong>${{escapeHtml(item.action || "")}}</strong></td>
                <td>${{escapeHtml(item.actor || "")}}</td>
                <td>${{escapeHtml(item.note || "")}}</td>
                <td>${{escapeHtml(formatTime(item.created_at) || "")}}</td>
              </tr>
            `).join("")
          : `<tr><td colspan="4" class="skill-empty">No approvals yet.</td></tr>`;
        return `
          <div class="detail-card">
            <strong>Revision History</strong>
            <table class="skills-table" style="margin-top: 0.75rem;">
              <thead>
                <tr>
                  <th>Revision</th>
                  <th>Status</th>
                  <th>Actor</th>
                  <th>Created</th>
                </tr>
              </thead>
              <tbody>${{revisionRows}}</tbody>
            </table>
          </div>
          <div class="detail-card">
            <strong>Approval History</strong>
            <table class="skills-table" style="margin-top: 0.75rem;">
              <thead>
                <tr>
                  <th>Action</th>
                  <th>Actor</th>
                  <th>Note</th>
                  <th>Created</th>
                </tr>
              </thead>
              <tbody>${{approvalRows}}</tbody>
            </table>
          </div>
        `;
      }}

      function stateBadge(item) {{
        const state = item?.connectivity_state || item?.status || "unknown";
        return `<span class="badge ${{getBadgeClass(state)}}">${{escapeHtml(statusLabel(state))}}</span>`;
      }}

      function renderRuntimeHealthSummary(summary) {{
        if (!summary || Object.keys(summary).length === 0) return "";
        const oldestClaim = formatAgeSeconds(summary.oldest_claim_age_seconds);
        return `
          <div class="meta meta-row">
            <span class="badge ${{getBadgeClass(summary.status || "healthy")}}">${{escapeHtml(statusLabel(summary.status || "healthy"))}}</span>
            <span>${{escapeHtml(String(summary.healthy_worker_count || 0))}} healthy</span>
            <span>${{escapeHtml(String(summary.stale_worker_count || 0))}} stale</span>
            <span>${{escapeHtml(String(summary.fresh_queued_count || 0))}} queued</span>
            <span>${{escapeHtml(String(summary.claimed_count || 0))}} claimed</span>
            <span>${{escapeHtml(String(summary.warning_count || 0))}} warn</span>
            <span>${{escapeHtml(String(summary.error_count || 0))}} fail</span>
          </div>
          ${{
            oldestClaim
              ? `<div class="meta"><strong>Oldest claim:</strong> ${{escapeHtml(oldestClaim)}}</div>`
              : ""
          }}
        `;
      }}

      function renderRuntimeHealthDiagnostics(report) {{
        const diagnostics = Array.isArray(report?.diagnostics) ? report.diagnostics : [];
        if (!diagnostics.length) {{
          return '<div class="meta">No mirrored diagnostics.</div>';
        }}
        return diagnostics.map(item => `
          <div class="meta diag-${{escapeHtml(item.level || "info")}}">
            <strong>${{escapeHtml((item.level || "info").toUpperCase())}}:</strong>
            ${{escapeHtml(item.message || "")}}
          </div>
        `).join("");
      }}

      function renderRuntimeHealthWorkers(rows) {{
        if (!Array.isArray(rows) || rows.length === 0) {{
          return '<div class="meta">No mirrored worker rows.</div>';
        }}
        return `
          <table class="skills-table">
            <thead>
              <tr>
                <th>Worker</th>
                <th>Role</th>
                <th>Last Seen</th>
                <th>Current</th>
                <th>Processed</th>
              </tr>
            </thead>
            <tbody>
              ${{
                rows.map(row => `
                  <tr>
                    <td><strong>${{escapeHtml(row.worker_id || "")}}</strong></td>
                    <td>${{escapeHtml(row.process_role || "")}}</td>
                    <td>${{escapeHtml(formatTime(row.last_seen_at) || "")}}</td>
                    <td>${{escapeHtml(row.current_kind || row.current_item_id || "idle")}}</td>
                    <td>${{escapeHtml(String(row.items_processed || 0))}}</td>
                  </tr>
                `).join("")
              }}
            </tbody>
          </table>
        `;
      }}

      function usageForConversation(conversationId) {{
        return (usageSummary.by_conversation || []).find(item => item.conversation_id === conversationId) || null;
      }}

      function renderUsageHeader() {{
        const el = document.getElementById("daily-usage");
        if (!el) return;
        const total = usageSummary.daily_total || {{}};
        const tokens = Number(total.prompt_tokens || 0) + Number(total.completion_tokens || 0);
        el.textContent = tokens > 0
          ? `Reported today: ${{formatUsageCount(tokens)}} tokens`
          : "";
      }}

      function setStatus(message) {{
        document.getElementById("ui-status").textContent = message || "";
      }}

      function showErrorBanner(message) {{
        const banner = document.getElementById("error-banner");
        if (!banner) return;
        banner.textContent = `⚠ Could not refresh data. Retrying… (${{message}})`;
        banner.style.display = "block";
      }}

      function clearErrorBanner() {{
        const banner = document.getElementById("error-banner");
        if (banner) banner.style.display = "none";
      }}

      function setRefreshing(active) {{
        const indicator = document.getElementById("refresh-indicator");
        if (!indicator) return;
        indicator.classList.toggle("hidden", !active);
      }}

      function renderList(id, items, template, emptyKey) {{
        document.getElementById(id).innerHTML = items.length
          ? items.map(template).join("")
          : `<div class="empty-state">${{EMPTY_STATES[emptyKey] || "Nothing yet."}}</div>`;
      }}

      function convItemTemplate(item) {{
        return `
          <button type="button" class="item item-button" data-conversation-id="${{escapeHtml(item.conversation_id)}}">
            <strong>${{escapeHtml(item.title || item.conversation_id)}}</strong>
            <div class="meta">${{escapeHtml(item.target_display_name || item.target_agent_id)}}</div>
            <div class="meta meta-row">
              <span class="badge ${{getBadgeClass(item.status || "open")}}">${{escapeHtml(statusLabel(item.status || "open"))}}</span>
              <span>${{escapeHtml(String(item.timeline_event_count ?? 0))}} event(s)</span>
            </div>
            ${{
              item.search_snippet
                ? `<div class="meta">${{escapeHtml(item.search_snippet).replace(/&lt;b&gt;/g, "<b>").replace(/&lt;\\/b&gt;/g, "</b>")}}</div>`
                : ""
            }}
          </button>
        `;
      }}

      function _applyConvFilters(conversations) {{
        var text = (document.getElementById('conv-search') || {{value:''}}).value.trim().toLowerCase();
        var status = (document.getElementById('conv-status') || {{value:''}}).value;
        var dateRange = (document.getElementById('conv-date') || {{value:''}}).value;
        var now = Date.now();
        var cutoffs = {{ today: 86400000, '7d': 7 * 86400000, '30d': 30 * 86400000 }};
        var filtered = conversations.filter(function(c) {{
          var normalizedStatus = (c.status || "") === "completed"
            ? "done"
            : ((c.status || "") === "partialfailed" ? "failed" : (c.status || ""));
          if (status && normalizedStatus !== status) return false;
          if (dateRange && cutoffs[dateRange]) {{
            var t = new Date(c.updated_at).getTime();
            if (!Number.isNaN(t) && now - t > cutoffs[dateRange]) return false;
          }}
          if (text && text.length < 3) {{
            if (!c.title || c.title.toLowerCase().indexOf(text) === -1) return false;
          }}
          return true;
        }});
        var total = conversations.length;
        var countEl = document.getElementById('conv-filter-count');
        if (countEl) {{
          if (filtered.length < total) {{
            countEl.textContent = 'Showing ' + filtered.length + ' of ' + total;
            countEl.style.display = '';
          }} else {{
            countEl.style.display = 'none';
          }}
        }}
        return filtered;
      }}

      function _renderConvSearchResults(results) {{
        var all = bootstrapData.conversations || [];
        var idMap = {{}};
        all.forEach(function(c) {{ idMap[c.conversation_id] = c; }});
        var matched = results.map(function(r) {{
          var conversation = idMap[r.conversation_id];
          if (!conversation) return null;
          return {{ ...conversation, search_snippet: r.snippet || "" }};
        }}).filter(Boolean);
        var countEl = document.getElementById('conv-filter-count');
        if (countEl) {{
          countEl.textContent = 'Search: ' + matched.length + ' result' + (matched.length === 1 ? '' : 's');
          countEl.style.display = '';
        }}
        renderList('conversations', matched, convItemTemplate, "conversations");
        document.querySelectorAll("[data-conversation-id]").forEach(node => {{
          node.addEventListener("click", () => loadConversationDetail(node.dataset.conversationId));
        }});
      }}

      async function refreshConversationPanel() {{
        var searchEl = document.getElementById('conv-search');
        var q = searchEl ? searchEl.value.trim() : "";
        if (q.length >= 3) {{
          try {{
            const response = await uiFetch('/v1/ui/search?q=' + encodeURIComponent(q), {{
              headers: requestHeaders(),
            }});
            if (!response.ok) {{
              throw new Error("Search failed.");
            }}
            const data = await response.json();
            _renderConvSearchResults(data.results || []);
            return;
          }} catch (_error) {{
            // Keep the existing panel contents on transient search failures.
            return;
          }}
        }}
        renderConversations(bootstrapData.conversations || []);
      }}

      function connectedBots() {{
        return bootstrapData.bots.filter(item => item.connectivity_state === "connected");
      }}

      function toggleNewConversationForm(open) {{
        const form = document.getElementById("new-conversation-form");
        form.classList.toggle("hidden", !open);
        if (!open) {{
          document.getElementById("new-conversation-message").value = "";
          return;
        }}
        const bots = connectedBots();
        const select = document.getElementById("new-conversation-target");
        select.innerHTML = bots.length
          ? bots.map(item => `<option value="${{escapeHtml(item.agent_id)}}">${{escapeHtml(item.display_name)}} (${{escapeHtml(item.role || "unassigned")}})</option>`).join("")
          : '<option value="">No connected bots available</option>';
        document.getElementById("start-conversation-button").disabled = bots.length === 0;
      }}

      function showDetailPanel(title) {{
        document.getElementById("detail-panel-title").textContent = title;
        document.getElementById("conversation-detail-empty").classList.add("hidden");
        document.getElementById("conversation-detail").classList.remove("hidden");
        document.getElementById("detail-back-button").classList.remove("hidden");
      }}

      function setConversationActionsVisible(visible) {{
        document.getElementById("conversation-detail-actions").classList.toggle("hidden", !visible);
      }}

      function renderBots(items) {{
        renderList("bots", items, item => `
          <button type="button" class="item item-button" data-bot-id="${{escapeHtml(item.agent_id)}}">
            <strong>${{escapeHtml(item.display_name)}}</strong>
            <div class="meta meta-row">${{stateBadge(item)}}<span>${{escapeHtml(item.role || "unassigned role")}}</span></div>
            <div class="meta">${{escapeHtml(item.description || (item.capabilities || []).join(", ") || "no capabilities declared")}}</div>
            ${{renderRuntimeHealthSummary(item.runtime_health_summary)}}
          </button>
        `, "bots");
        document.querySelectorAll("[data-bot-id]").forEach(node => {{
          node.addEventListener("click", () => {{
            loadBotDetail(node.dataset.botId);
          }});
        }});
      }}

      function renderConversations(items) {{
        renderList("conversations", _applyConvFilters(items), convItemTemplate, "conversations");
        document.querySelectorAll("[data-conversation-id]").forEach(node => {{
          node.addEventListener("click", () => loadConversationDetail(node.dataset.conversationId));
        }});
      }}

      function renderTasks(items) {{
        renderList("tasks", items, item => `
          <button type="button" class="item item-button" data-task-id="${{escapeHtml(item.routed_task_id)}}">
            <strong>${{escapeHtml(item.title)}}</strong>
            <div class="meta">${{escapeHtml(item.origin_display_name || item.origin_agent_id)}} → ${{escapeHtml(item.target_display_name || item.target_agent_id)}}</div>
            <div class="meta meta-row"><span class="badge ${{getBadgeClass(item.status || "queued")}}">${{escapeHtml(statusLabel(item.status || "queued"))}}</span><span>${{escapeHtml(item.summary || "")}}</span></div>
          </button>
        `, "tasks");
        document.querySelectorAll("[data-task-id]").forEach(node => {{
          node.addEventListener("click", () => {{
            const task = (bootstrapData.tasks || []).find(item => item.routed_task_id === node.dataset.taskId);
            if (task) renderTaskDetail(task);
          }});
        }});
      }}

      function renderRuntimeSkillDetail(detail, preview = null, lifecycle = null) {{
        const panel = document.getElementById("runtime-skill-detail");
        if (!panel) return;
        if (!detail) {{
          panel.classList.add("hidden");
          panel.innerHTML = "";
          return;
        }}
        const requirements = (detail.requirement_keys || []).length
          ? escapeHtml(detail.requirement_keys.join(", "))
          : "None";
        const providers = (detail.providers || []).length
          ? detail.providers.map(provider => `
              <button type="button" class="secondary" data-runtime-skill-preview="${{escapeHtml(detail.name)}}" data-provider-name="${{escapeHtml(provider)}}">
                Preview ${{escapeHtml(provider)}}
              </button>
            `).join("")
          : '<span class="subtle">No provider-specific preview available.</span>';
        const lifecycleStatus = lifecycle?.lifecycle_status || detail.lifecycle_status || "";
        const actionButtons = detail.can_update || detail.can_uninstall
          ? `
              <button type="button" class="secondary" data-runtime-skill-update="${{escapeHtml(detail.name)}}">Update</button>
              <button type="button" class="danger" data-runtime-skill-uninstall="${{escapeHtml(detail.name)}}">Uninstall</button>
            `
          : "";
        const previewBlock = preview
          ? `
              <div class="detail-card" style="margin-top: 0.9rem;">
                <strong>Prompt Preview</strong>
                <div class="meta"><strong>Provider:</strong> ${{escapeHtml(preview.provider || "")}}</div>
                <div class="meta"><strong>Prompt weight:</strong> ${{escapeHtml(String(preview.prompt_weight || 0))}}</div>
                <div class="meta"><strong>Capabilities:</strong> ${{escapeHtml(String(preview.capability_summary || ""))}}</div>
                <pre class="timeline-body">${{escapeHtml(preview.system_prompt || "")}}</pre>
              </div>
            `
          : "";
        const lifecycleBlock = lifecycle
          ? `
              <div class="editor-shell">
                <div class="detail-card">
                  <div class="meta"><strong>Lifecycle:</strong> ${{escapeHtml(lifecycle.lifecycle_status || "draft")}}</div>
                  <div class="meta"><strong>Runtime available:</strong> ${{escapeHtml(lifecycle.runtime_available ? "yes" : "no")}}</div>
                  <div class="meta"><strong>Active revision:</strong> ${{escapeHtml(lifecycle.active_revision_id || "none")}}</div>
                  <div class="meta"><strong>Published revision:</strong> ${{escapeHtml(lifecycle.published_revision_id || "none")}}</div>
                </div>
                <label>
                  Description
                  <input id="runtime-skill-description" type="text" value="${{escapeHtml(detail.description || "")}}" />
                </label>
                <label>
                  Draft body
                  <textarea id="runtime-skill-editor-textarea">${{escapeHtml(lifecycle.body || detail.body || "")}}</textarea>
                </label>
                <div class="editor-actions">
                  <button type="button" data-runtime-skill-save="${{escapeHtml(detail.name)}}">Save draft</button>
                  <button type="button" class="secondary" data-runtime-skill-lifecycle-action="submit" data-runtime-skill-name="${{escapeHtml(detail.name)}}">Submit</button>
                  <button type="button" class="secondary" data-runtime-skill-lifecycle-action="approve" data-runtime-skill-name="${{escapeHtml(detail.name)}}">Approve</button>
                  <button type="button" class="secondary" data-runtime-skill-lifecycle-action="reject" data-runtime-skill-name="${{escapeHtml(detail.name)}}">Reject</button>
                  <button type="button" class="secondary" data-runtime-skill-lifecycle-action="publish" data-runtime-skill-name="${{escapeHtml(detail.name)}}">Publish</button>
                  <button type="button" class="danger" data-runtime-skill-lifecycle-action="archive" data-runtime-skill-name="${{escapeHtml(detail.name)}}">Archive</button>
                </div>
                ${{renderLifecycleHistory(lifecycle.revisions || [], lifecycle.approvals || [])}}
              </div>
            `
          : "";
        panel.classList.remove("hidden");
        panel.innerHTML = `
          <strong>${{escapeHtml(detail.display_name || detail.name)}}</strong>
          <div class="meta"><strong>Slug:</strong> ${{escapeHtml(detail.name)}}</div>
          <div class="meta"><strong>Source:</strong> ${{escapeHtml(detail.source_kind || "unknown")}}</div>
          <div class="meta"><strong>Status:</strong> ${{escapeHtml(lifecycleStatus || "runtime")}}</div>
          <div class="meta"><strong>Requirements:</strong> ${{requirements}}</div>
          <div class="meta"><strong>Description:</strong> ${{escapeHtml(detail.description || "No description provided.")}}</div>
          ${{
            lifecycle
              ? ""
              : `<pre class="timeline-body">${{escapeHtml(detail.body || "")}}</pre>`
          }}
          <div class="toolbar" style="margin-top: 0.75rem;">${{actionButtons}}${{providers}}</div>
          ${{lifecycleBlock}}
          ${{previewBlock}}
        `;
        panel.querySelectorAll("[data-runtime-skill-preview]").forEach(node => {{
          node.addEventListener("click", () => previewRuntimeSkill(node.dataset.providerName, node.dataset.runtimeSkillPreview));
        }});
        panel.querySelectorAll("[data-runtime-skill-install]").forEach(node => {{
          node.addEventListener("click", () => installRuntimeSkill(node.dataset.runtimeSkillInstall));
        }});
        panel.querySelectorAll("[data-runtime-skill-update]").forEach(node => {{
          node.addEventListener("click", () => updateRuntimeSkill(node.dataset.runtimeSkillUpdate));
        }});
        panel.querySelectorAll("[data-runtime-skill-uninstall]").forEach(node => {{
          node.addEventListener("click", () => uninstallRuntimeSkill(node.dataset.runtimeSkillUninstall));
        }});
        panel.querySelectorAll("[data-runtime-skill-save]").forEach(node => {{
          node.addEventListener("click", () => saveRuntimeSkillDraft(node.dataset.runtimeSkillSave));
        }});
        panel.querySelectorAll("[data-runtime-skill-lifecycle-action]").forEach(node => {{
          node.addEventListener("click", () => runRuntimeSkillLifecycle(node.dataset.runtimeSkillName, node.dataset.runtimeSkillLifecycleAction));
        }});
        if (lifecycle) {{
          mountRichEditor("runtime-skill-editor-textarea");
        }}
      }}

      function renderRuntimeSkills(items) {{
        const container = document.getElementById("runtime-skills");
        if (!container) return;
        if (!items.length) {{
          container.innerHTML = `<div class="empty-state">${{EMPTY_STATES.runtimeSkills}}</div>`;
          return;
        }}
        container.innerHTML = `
          <table class="skills-table">
            <thead>
              <tr>
                <th>Skill</th>
                <th>Source</th>
                <th>Providers</th>
                <th>Status</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              ${{
                items.map(item => {{
                  const providers = (item.providers || []).length
                    ? escapeHtml(item.providers.join(", "))
                    : '<span class="skill-empty">(generic)</span>';
                  const sourceKind = item.source_kind || "unknown";
                  const status = sourceKind === "imported"
                    ? "Imported"
                    : (sourceKind === "custom"
                      ? (item.lifecycle_status || "draft")
                      : "Built-in");
                  const rowAction = item.can_update || item.can_uninstall
                    ? `<button type="button" class="secondary" data-runtime-skill-update="${{escapeHtml(item.name)}}">Update</button>
                       <button type="button" class="danger" data-runtime-skill-uninstall="${{escapeHtml(item.name)}}">Uninstall</button>`
                    : "";
                  return `
                    <tr>
                      <td>
                        <strong>${{escapeHtml(item.display_name || item.name)}}</strong>
                        <div class="meta">${{escapeHtml(item.description || "")}}</div>
                      </td>
                      <td>${{escapeHtml(sourceKind)}}</td>
                      <td>${{providers}}</td>
                      <td>${{escapeHtml(status)}}</td>
                      <td>
                        <div class="toolbar">
                          <button type="button" class="secondary" data-runtime-skill-detail="${{escapeHtml(item.name)}}">Details</button>${{rowAction ? ` ${{rowAction}}` : ""}}
                        </div>
                      </td>
                    </tr>
                  `;
                }}).join("")
              }}
            </tbody>
          </table>
        `;
        container.querySelectorAll("[data-runtime-skill-detail]").forEach(node => {{
          node.addEventListener("click", () => loadRuntimeSkillDetail(node.dataset.runtimeSkillDetail));
        }});
        container.querySelectorAll("[data-runtime-skill-install]").forEach(node => {{
          node.addEventListener("click", () => installRuntimeSkill(node.dataset.runtimeSkillInstall));
        }});
        container.querySelectorAll("[data-runtime-skill-update]").forEach(node => {{
          node.addEventListener("click", () => updateRuntimeSkill(node.dataset.runtimeSkillUpdate));
        }});
        container.querySelectorAll("[data-runtime-skill-uninstall]").forEach(node => {{
          node.addEventListener("click", () => uninstallRuntimeSkill(node.dataset.runtimeSkillUninstall));
        }});
      }}

      async function loadRuntimeSkills(query = "") {{
        const suffix = query ? `?q=${{encodeURIComponent(query)}}` : "";
          const response = await uiFetch(`/v1/catalog/skills${{suffix}}`, {{
          headers: requestHeaders(),
        }});
        if (!response.ok) {{
          throw new Error(await response.text() || "Failed to load runtime skills.");
        }}
        const payload = await response.json();
        runtimeCatalog = Array.isArray(payload.skills) ? payload.skills : [];
        runtimeSkillsLoaded = true;
        renderRuntimeSkills(runtimeCatalog);
        if (currentConversationDetail && currentConversationDetail.conversation) {{
          renderConversationDetail(
            currentConversationDetail.conversation,
            currentConversationDetail.events || [],
            currentConversationDetail.skillState || null,
          );
        }}
      }}

      async function loadRuntimeSkillDetail(skillName) {{
        const [detailResponse, lifecycleResponse] = await Promise.all([
          uiFetch(`/v1/catalog/skills/${{encodeURIComponent(skillName)}}`, {{
            headers: requestHeaders(),
          }}),
          uiFetch(`/v1/catalog/skills/${{encodeURIComponent(skillName)}}/lifecycle`, {{
            headers: requestHeaders(),
          }}),
        ]);
        if (!detailResponse.ok) {{
          setStatus(await detailResponse.text() || "Failed to load runtime skill detail.");
          return;
        }}
        currentRuntimeSkillDetail = await detailResponse.json();
        currentRuntimeSkillPreview = null;
        currentRuntimeSkillLifecycle = lifecycleResponse.ok ? await lifecycleResponse.json() : null;
        renderRuntimeSkillDetail(currentRuntimeSkillDetail, null, currentRuntimeSkillLifecycle);
      }}

      async function previewRuntimeSkill(providerName, skillName) {{
        const response = await uiFetch(`/v1/provider-guidance/${{encodeURIComponent(providerName)}}/preview`, {{
          method: "POST",
          headers: requestHeaders({{ "Content-Type": "application/json" }}),
          body: JSON.stringify({{
            role: "",
            active_skills: [skillName],
            compact_mode: false,
          }}),
        }});
        if (!response.ok) {{
          setStatus(await response.text() || "Preview failed.");
          return;
        }}
        currentRuntimeSkillPreview = await response.json();
        if (currentRuntimeSkillDetail && currentRuntimeSkillDetail.name === skillName) {{
          renderRuntimeSkillDetail(currentRuntimeSkillDetail, currentRuntimeSkillPreview);
        }}
      }}

      async function installRuntimeSkill(skillName) {{
        const response = await uiFetch(`/v1/catalog/skills/${{encodeURIComponent(skillName)}}/install`, {{
          method: "POST",
          headers: requestHeaders(),
        }});
        const payload = await response.json();
        if (!response.ok) {{
          setStatus(payload.detail || payload.message || "Install failed.");
          return;
        }}
        setStatus(payload.message || `Installed ${{skillName}}.`);
        await loadRuntimeSkills(document.getElementById("runtime-skill-search")?.value.trim() || "");
        if (currentRuntimeSkillDetail && currentRuntimeSkillDetail.name === skillName) {{
          await loadRuntimeSkillDetail(skillName);
        }}
        await refreshCurrentDetail();
      }}

      async function updateRuntimeSkill(skillName) {{
        const response = await uiFetch(`/v1/catalog/skills/${{encodeURIComponent(skillName)}}/update`, {{
          method: "POST",
          headers: requestHeaders(),
        }});
        const payload = await response.json();
        if (!response.ok) {{
          setStatus(payload.detail || payload.message || "Update failed.");
          return;
        }}
        setStatus(payload.message || `Updated ${{skillName}}.`);
        await loadRuntimeSkills(document.getElementById("runtime-skill-search")?.value.trim() || "");
        if (currentRuntimeSkillDetail && currentRuntimeSkillDetail.name === skillName) {{
          await loadRuntimeSkillDetail(skillName);
        }}
        await refreshCurrentDetail();
      }}

      async function uninstallRuntimeSkill(skillName) {{
        const response = await uiFetch(`/v1/catalog/skills/${{encodeURIComponent(skillName)}}/uninstall`, {{
          method: "POST",
          headers: requestHeaders(),
        }});
        const payload = await response.json();
        if (!response.ok) {{
          setStatus(payload.detail || payload.message || "Uninstall failed.");
          return;
        }}
        setStatus(payload.message || `Uninstalled ${{skillName}}.`);
        await loadRuntimeSkills(document.getElementById("runtime-skill-search")?.value.trim() || "");
        if (currentRuntimeSkillDetail && currentRuntimeSkillDetail.name === skillName) {{
          await loadRuntimeSkillDetail(skillName);
        }}
        await refreshCurrentDetail();
      }}

      function normalizeRuntimeSkillName(value) {{
        return String(value || "")
          .trim()
          .toLowerCase()
          .replace(/[^a-z0-9._-]+/g, "-")
          .replace(/^-+|-+$/g, "");
      }}

      async function createRuntimeSkillDraft() {{
        const input = document.getElementById("runtime-skill-create-name");
        const skillName = normalizeRuntimeSkillName(input?.value || "");
        if (!skillName) {{
          setStatus("Enter a runtime skill slug first.");
          return;
        }}
        if (input) {{
          input.value = skillName;
        }}
        const response = await uiFetch(`/v1/catalog/skills/${{encodeURIComponent(skillName)}}/draft`, {{
          method: "PUT",
          headers: requestHeaders({{ "Content-Type": "application/json" }}),
          body: JSON.stringify({{
            actor_key: REGISTRY_UI_ACTOR_KEY,
            body: "Add your instructions here.",
            description: "",
            changelog: "Created in registry editor",
          }}),
        }});
        const payload = await response.json().catch(() => ({{}}));
        if (!response.ok) {{
          setStatus(payload.detail || payload.message || "Could not create draft.");
          return;
        }}
        setStatus(payload.message || `Created draft ${{skillName}}.`);
        await loadRuntimeSkills(document.getElementById("runtime-skill-search")?.value.trim() || "");
        await loadRuntimeSkillDetail(skillName);
      }}

      async function saveRuntimeSkillDraft(skillName) {{
        const body = editorValue("runtime-skill-editor-textarea").trim();
        const description = document.getElementById("runtime-skill-description")?.value.trim() || "";
        const response = await uiFetch(`/v1/catalog/skills/${{encodeURIComponent(skillName)}}/draft`, {{
          method: "PUT",
          headers: requestHeaders({{ "Content-Type": "application/json" }}),
          body: JSON.stringify({{
            actor_key: REGISTRY_UI_ACTOR_KEY,
            body,
            description,
            changelog: "Updated in registry editor",
          }}),
        }});
        const payload = await response.json().catch(() => ({{}}));
        if (!response.ok) {{
          setStatus(payload.detail || payload.message || "Could not save draft.");
          return;
        }}
        setStatus(payload.message || `Saved draft ${{skillName}}.`);
        await loadRuntimeSkills(document.getElementById("runtime-skill-search")?.value.trim() || "");
        await loadRuntimeSkillDetail(skillName);
      }}

      async function runRuntimeSkillLifecycle(skillName, action) {{
        const response = await uiFetch(`/v1/catalog/skills/${{encodeURIComponent(skillName)}}/${{action}}`, {{
          method: "POST",
          headers: requestHeaders({{ "Content-Type": "application/json" }}),
          body: JSON.stringify({{
            actor_key: REGISTRY_UI_ACTOR_KEY,
            note: `registry-ui:${{action}}`,
          }}),
        }});
        const payload = await response.json().catch(() => ({{}}));
        if (!response.ok) {{
          setStatus(payload.detail || payload.message || `Could not ${{action}} ${{skillName}}.`);
          return;
        }}
        setStatus(payload.message || `${{action}} ${{skillName}}.`);
        await loadRuntimeSkills(document.getElementById("runtime-skill-search")?.value.trim() || "");
        await loadRuntimeSkillDetail(skillName);
        await refreshCurrentDetail();
      }}

      function renderProviderGuidanceDetail(detail, preview = null) {{
        const panel = document.getElementById("provider-guidance-detail");
        if (!panel) return;
        if (!detail) {{
          panel.classList.add("hidden");
          panel.innerHTML = "";
          return;
        }}
        const previewBlock = preview
          ? `
              <div class="detail-card">
                <strong>Runtime Preview</strong>
                <div class="meta"><strong>Prompt weight:</strong> ${{escapeHtml(String(preview.prompt_weight || 0))}}</div>
                <div class="meta"><strong>Capabilities:</strong> ${{escapeHtml(String(preview.capability_summary || ""))}}</div>
                <pre class="timeline-body">${{escapeHtml(preview.effective_guidance || "")}}</pre>
              </div>
            `
          : "";
        panel.classList.remove("hidden");
        panel.innerHTML = `
          <strong>${{escapeHtml(detail.provider || "")}} guidance</strong>
          <div class="meta"><strong>Scope:</strong> ${{escapeHtml(detail.scope_kind || "system")}}${{detail.scope_key ? ` / ${{escapeHtml(detail.scope_key)}}` : ""}}</div>
          <div class="meta"><strong>Lifecycle:</strong> ${{escapeHtml(detail.lifecycle_status || "draft")}}</div>
          <div class="meta"><strong>Runtime available:</strong> ${{escapeHtml(detail.runtime_available ? "yes" : "no")}}</div>
          <div class="meta"><strong>Active revision:</strong> ${{escapeHtml(detail.active_revision_id || "none")}}</div>
          <div class="meta"><strong>Published revision:</strong> ${{escapeHtml(detail.published_revision_id || "none")}}</div>
          <div class="editor-shell">
            <label>
              Draft body
              <textarea id="provider-guidance-editor-textarea">${{escapeHtml(detail.body || "")}}</textarea>
            </label>
            <div class="editor-actions">
              <button type="button" data-provider-guidance-save="${{escapeHtml(detail.provider)}}">Save draft</button>
              <button type="button" class="secondary" data-provider-guidance-action="submit" data-provider-name="${{escapeHtml(detail.provider)}}">Submit</button>
              <button type="button" class="secondary" data-provider-guidance-action="approve" data-provider-name="${{escapeHtml(detail.provider)}}">Approve</button>
              <button type="button" class="secondary" data-provider-guidance-action="reject" data-provider-name="${{escapeHtml(detail.provider)}}">Reject</button>
              <button type="button" class="secondary" data-provider-guidance-action="publish" data-provider-name="${{escapeHtml(detail.provider)}}">Publish</button>
              <button type="button" class="danger" data-provider-guidance-action="archive" data-provider-name="${{escapeHtml(detail.provider)}}">Archive</button>
              <button type="button" class="secondary" data-provider-guidance-preview="${{escapeHtml(detail.provider)}}">Refresh preview</button>
            </div>
            ${{renderLifecycleHistory(detail.revisions || [], detail.approvals || [])}}
            ${{previewBlock}}
          </div>
        `;
        panel.querySelectorAll("[data-provider-guidance-save]").forEach(node => {{
          node.addEventListener("click", () => saveProviderGuidanceDraft(node.dataset.providerGuidanceSave));
        }});
        panel.querySelectorAll("[data-provider-guidance-action]").forEach(node => {{
          node.addEventListener("click", () => runProviderGuidanceLifecycle(node.dataset.providerName, node.dataset.providerGuidanceAction));
        }});
        panel.querySelectorAll("[data-provider-guidance-preview]").forEach(node => {{
          node.addEventListener("click", () => loadProviderGuidanceDetail(node.dataset.providerGuidancePreview));
        }});
        mountRichEditor("provider-guidance-editor-textarea");
      }}

      async function loadProviderGuidanceDetail(providerName) {{
        const [detailResponse, previewResponse] = await Promise.all([
          uiFetch(`/v1/provider-guidance/${{encodeURIComponent(providerName)}}`, {{
            headers: requestHeaders(),
          }}),
          uiFetch(`/v1/provider-guidance/${{encodeURIComponent(providerName)}}/preview`, {{
            method: "POST",
            headers: requestHeaders({{ "Content-Type": "application/json" }}),
            body: JSON.stringify({{
              role: "",
              active_skills: [],
              compact_mode: false,
            }}),
          }}),
        ]);
        if (!detailResponse.ok) {{
          setStatus(await detailResponse.text() || "Failed to load provider guidance.");
          return;
        }}
        currentProviderGuidanceDetail = await detailResponse.json();
        currentProviderGuidancePreview = previewResponse.ok ? await previewResponse.json() : null;
        providerGuidanceLoaded = true;
        renderProviderGuidanceDetail(currentProviderGuidanceDetail, currentProviderGuidancePreview);
      }}

      async function saveProviderGuidanceDraft(providerName) {{
        const body = editorValue("provider-guidance-editor-textarea").trim();
        const detail = currentProviderGuidanceDetail;
        if (!detail) {{
          setStatus("Load provider guidance first.");
          return;
        }}
        const response = await uiFetch(`/v1/provider-guidance/${{encodeURIComponent(providerName)}}/draft`, {{
          method: "PUT",
          headers: requestHeaders({{ "Content-Type": "application/json" }}),
          body: JSON.stringify({{
            actor_key: REGISTRY_UI_ACTOR_KEY,
            body,
            scope_kind: detail.scope_kind || "system",
            scope_key: detail.scope_key || "",
          }}),
        }});
        const payload = await response.json().catch(() => ({{}}));
        if (!response.ok) {{
          setStatus(payload.detail || payload.message || "Could not save provider guidance.");
          return;
        }}
        setStatus(payload.message || `Saved ${{providerName}} guidance draft.`);
        await loadProviderGuidanceDetail(providerName);
      }}

      async function runProviderGuidanceLifecycle(providerName, action) {{
        const detail = currentProviderGuidanceDetail;
        const response = await uiFetch(`/v1/provider-guidance/${{encodeURIComponent(providerName)}}/${{action}}`, {{
          method: "POST",
          headers: requestHeaders({{ "Content-Type": "application/json" }}),
          body: JSON.stringify({{
            actor_key: REGISTRY_UI_ACTOR_KEY,
            note: `registry-ui:${{action}}`,
            scope_kind: detail?.scope_kind || "system",
            scope_key: detail?.scope_key || "",
          }}),
        }});
        const payload = await response.json().catch(() => ({{}}));
        if (!response.ok) {{
          setStatus(payload.detail || payload.message || `Could not ${{action}} ${{providerName}} guidance.`);
          return;
        }}
        setStatus(payload.message || `${{action}} ${{providerName}} guidance.`);
        await loadProviderGuidanceDetail(providerName);
      }}

      function renderCapabilities(items) {{
        const container = document.getElementById("capabilities");
        if (!container) return;
        if (!items.length) {{
          container.innerHTML = `<div class="empty-state">${{EMPTY_STATES.capabilities}}</div>`;
          return;
        }}
        container.innerHTML = `
          <table class="skills-table">
            <thead>
              <tr>
                <th>Capability</th>
                <th>Declared by</th>
                <th>Status</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              ${{
                items.map(item => {{
                  const disabled = item.enabled === false;
                  const overridden = item.enabled === true;
                  const status = disabled
                    ? '<span class="skill-status-disabled">Disabled</span>'
                    : overridden
                      ? '<span class="skill-status-overridden">Enabled (overridden)</span>'
                      : 'Enabled';
                  const action = disabled ? 'enable' : 'disable';
                  const actionLabel = disabled ? 'Enable' : 'Disable';
                  const declaredBy = (item.declared_by_agents || []).length
                    ? escapeHtml(item.declared_by_agents.join(', '))
                    : '<span class="skill-empty">(none active)</span>';
                  return `
                    <tr class="${{disabled ? 'skill-row-disabled' : ''}}">
                      <td><strong>${{escapeHtml(item.capability_name)}}</strong></td>
                      <td>${{declaredBy}}</td>
                      <td>${{status}}</td>
                      <td>
                        <button
                          type="button"
                          class="${{disabled ? '' : 'secondary'}}"
                          data-capability-name="${{escapeHtml(item.capability_name)}}"
                          data-capability-action="${{action}}"
                        >${{actionLabel}}</button>
                      </td>
                    </tr>
                  `;
                }}).join("")
              }}
            </tbody>
          </table>
        `;
        document.querySelectorAll("[data-capability-action]").forEach(node => {{
          node.addEventListener("click", () => {{
            toggleCapabilityOverride(node.dataset.capabilityName, node.dataset.capabilityAction === "enable");
          }});
        }});
      }}

      async function loadBotDetail(agentId) {{
        const bot = (bootstrapData.bots || []).find(item => item.agent_id === agentId);
        if (!bot) return;
        renderBotDetail(bot);
        try {{
          const response = await uiFetch(`/v1/ui/bots/${{agentId}}/health`, {{
            headers: requestHeaders(),
          }});
          if (!response.ok) {{
            return;
          }}
          const detail = await response.json();
          renderBotDetail(bot, detail);
        }} catch (_error) {{
          // Keep the summary-only bot detail on transient failures.
        }}
      }}

      function renderBotDetail(bot, runtimeHealthDetail = null) {{
        currentDetailKind = "bot";
        currentDetailId = bot.agent_id || "";
        currentConversationId = "";
        currentConversationDetail = null;
        showDetailPanel("Bot Detail");
        setConversationActionsVisible(false);
        const healthReport = runtimeHealthDetail?.report || null;
        const healthSummary = healthReport?.summary || bot.runtime_health_summary || null;
        document.getElementById("conversation-detail-header").innerHTML = `
          <div class="detail-card">
            <strong>${{escapeHtml(bot.display_name || bot.agent_id)}}</strong>
            <div class="meta meta-row">
              ${{stateBadge(bot)}}
              <span>${{escapeHtml(bot.role || "unassigned role")}}</span>
            </div>
            ${{renderRuntimeHealthSummary(healthSummary)}}
          </div>
        `;
        document.getElementById("conversation-detail-body").innerHTML = `
          <div class="detail-card">
            <div class="meta"><strong>Description:</strong> ${{escapeHtml(bot.description || "No description provided.")}}</div>
            <div class="meta"><strong>Capabilities:</strong> ${{escapeHtml((bot.capabilities || []).join(", ") || "No capabilities declared")}}</div>
            <div class="meta"><strong>Tags:</strong> ${{escapeHtml((bot.tags || []).join(", ") || "No tags declared")}}</div>
            <div class="meta"><strong>Version:</strong> ${{escapeHtml(bot.version || "unknown")}}</div>
            <div class="meta"><strong>Last heartbeat:</strong> ${{escapeHtml(formatTime(bot.last_heartbeat_at) || "unknown")}}</div>
            <div class="meta"><strong>Mirrored runtime health:</strong> ${{escapeHtml(formatTime(bot.runtime_health_generated_at) || "not mirrored")}}</div>
          </div>
          <div class="detail-card">
            <strong>Diagnostics</strong>
            ${{healthReport ? renderRuntimeHealthDiagnostics(healthReport) : '<div class="meta">No mirrored diagnostics.</div>'}}
          </div>
          <div class="detail-card">
            <strong>Workers</strong>
            ${{renderRuntimeHealthWorkers(runtimeHealthDetail?.workers || [])}}
          </div>
        `;
      }}

      function renderTaskDetail(task) {{
        currentDetailKind = "task";
        currentDetailId = task.routed_task_id || "";
        currentConversationId = "";
        currentConversationDetail = null;
        showDetailPanel("Routed Task Detail");
        setConversationActionsVisible(false);
        document.getElementById("conversation-detail-header").innerHTML = `
          <div class="detail-card">
            <strong>${{escapeHtml(task.title || task.routed_task_id)}}</strong>
            <div class="meta meta-row">
              <span class="badge ${{getBadgeClass(task.status || "queued")}}">${{escapeHtml(statusLabel(task.status || "queued"))}}</span>
              <span>${{escapeHtml(task.origin_display_name || task.origin_agent_id)}} → ${{escapeHtml(task.target_display_name || task.target_agent_id)}}</span>
            </div>
          </div>
        `;
        document.getElementById("conversation-detail-body").innerHTML = `
          <div class="detail-card">
            <div class="meta"><strong>Summary:</strong> ${{escapeHtml(task.summary || "No summary yet.")}}</div>
            <div class="meta"><strong>Parent conversation:</strong> ${{escapeHtml(task.parent_conversation_id || "unknown")}}</div>
            <div class="meta"><strong>Updated:</strong> ${{escapeHtml(formatTime(task.updated_at) || "unknown")}}</div>
          </div>
        `;
      }}

      function clearConversationDetail() {{
        currentDetailKind = "";
        currentDetailId = "";
        currentConversationId = "";
        currentConversationDetail = null;
        document.getElementById("conversation-detail").classList.add("hidden");
        document.getElementById("conversation-detail-empty").classList.remove("hidden");
        document.getElementById("detail-back-button").classList.add("hidden");
        document.getElementById("detail-panel-title").textContent = "Conversation Detail";
        document.getElementById("conversation-detail-header").innerHTML = "";
        document.getElementById("conversation-detail-body").innerHTML = '<div id="conversation-detail-timeline" class="timeline"></div>';
        document.getElementById("detail-message-text").value = "";
        setConversationActionsVisible(false);
      }}

      function canRenderDelegationActions(conversation, event, index, events) {{
        const status = conversation?.status || "open";
        if (!["open", "running"].includes(status)) return false;
        if ((event?.kind || "") !== "delegation_proposed") return false;
        return index === events.length - 1;
      }}

      function renderDelegationControls(conversationId, eventId) {{
        const pendingAction = delegationActionState[eventId] || "";
        const error = delegationActionError[eventId] || "";
        const approveLabel = pendingAction === "approve_delegation" ? "Pending…" : "Approve";
        const cancelLabel = pendingAction === "cancel_delegation" ? "Pending…" : "Cancel";
        const disabled = pendingAction ? "disabled" : "";
        return `
          <div class="timeline-controls">
            <button type="button" data-delegation-action="approve_delegation" data-conversation-id="${{escapeHtml(conversationId)}}" data-event-id="${{escapeHtml(eventId)}}" ${{disabled}}>${{approveLabel}}</button>
            <button type="button" class="secondary" data-delegation-action="cancel_delegation" data-conversation-id="${{escapeHtml(conversationId)}}" data-event-id="${{escapeHtml(eventId)}}" ${{disabled}}>${{cancelLabel}}</button>
          </div>
          ${{error ? `<div class="inline-error">${{escapeHtml(error)}}</div>` : ""}}
        `;
      }}

      function renderConversationSkills(conversation, skillState) {{
        if (!runtimeSkillsLoaded) {{
          return '<div class="detail-card"><strong>Runtime Skills</strong><div class="meta">Loading skill catalog…</div></div>';
        }}
        const activeNames = new Set((skillState?.active_skills || []).map(String));
        const activeDetails = Array.isArray(skillState?.active_skill_details) ? skillState.active_skill_details : [];
        const activeSummary = activeDetails.length
          ? activeDetails.map(item => `<span class="badge badge-running">${{escapeHtml(item.display_name || item.name || "")}}</span>`).join(" ")
          : '<span class="skill-empty">(none active)</span>';
        const rows = runtimeCatalog.map(skill => {{
          const active = activeNames.has(skill.name);
          let actions = `<button type="button" class="secondary" data-runtime-skill-detail="${{escapeHtml(skill.name)}}">Details</button>`;
          if (active) {{
            actions += ` <button type="button" class="danger" data-conversation-skill-action="deactivate" data-conversation-id="${{escapeHtml(conversation.conversation_id)}}" data-skill-name="${{escapeHtml(skill.name)}}">Deactivate</button>`;
          }} else if (skill.can_activate) {{
            actions += ` <button type="button" data-conversation-skill-action="activate" data-conversation-id="${{escapeHtml(conversation.conversation_id)}}" data-skill-name="${{escapeHtml(skill.name)}}">Activate</button>`;
          }} else {{
            actions += ` <button type="button" data-runtime-skill-install="${{escapeHtml(skill.name)}}">Install</button>`;
          }}
          return `
            <tr>
              <td>
                <strong>${{escapeHtml(skill.display_name || skill.name)}}</strong>
                <div class="meta">${{escapeHtml(skill.description || "")}}</div>
              </td>
              <td>${{active ? '<span class="skill-status-overridden">Active</span>' : escapeHtml(skill.can_activate ? 'Available' : 'Not available')}}</td>
              <td><div class="toolbar">${{actions}}</div></td>
            </tr>
          `;
        }}).join("");
        const clearButton = activeNames.size
          ? `<button type="button" class="secondary" data-conversation-skill-action="clear" data-conversation-id="${{escapeHtml(conversation.conversation_id)}}">Clear all</button>`
          : "";
        return `
          <div class="detail-card">
            <strong>Runtime Skills</strong>
            <div class="meta"><strong>Active:</strong> ${{activeSummary}}</div>
            <div class="toolbar" style="margin-top: 0.75rem;">${{clearButton}}</div>
            <table class="skills-table" style="margin-top: 0.75rem;">
              <thead>
                <tr>
                  <th>Skill</th>
                  <th>Status</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>${{rows}}</tbody>
            </table>
          </div>
        `;
      }}

      function renderConversationDetail(conversation, events, skillState = null) {{
        currentDetailKind = "conversation";
        currentDetailId = conversation.conversation_id || "";
        currentConversationId = conversation.conversation_id || "";
        currentConversationDetail = {{ conversation, events, skillState }};
        const usage = usageForConversation(conversation.conversation_id);
        const usageTokensLine = usage && (usage.prompt_tokens > 0 || usage.completion_tokens > 0)
          ? `<div class="meta"><strong>Reported tokens:</strong> ${{formatUsageCount(usage.prompt_tokens)}} in / ${{formatUsageCount(usage.completion_tokens)}} out</div>`
          : "";
        const usageCostLine = usage && Number(usage.cost_usd || 0) > 0
          ? `<div class="meta"><strong>Reported cost:</strong> ${{escapeHtml(formatUsageCost(usage.cost_usd))}}</div>`
          : "";
        showDetailPanel("Conversation Detail");
        setConversationActionsVisible(true);
        document.getElementById("conversation-detail-header").innerHTML = `
          <div class="detail-card">
            <strong>${{escapeHtml(conversation.title || conversation.conversation_id)}}</strong>
            <div class="meta">${{escapeHtml(conversation.target_display_name || conversation.target_agent_id)}}</div>
            <div class="meta meta-row">
              <span class="badge ${{getBadgeClass(conversation.status || "open")}}">${{escapeHtml(statusLabel(conversation.status || "open"))}}</span>
              <span>${{escapeHtml(String(conversation.timeline_event_count ?? events.length))}} event(s)</span>
            </div>
            <div class="meta">Created ${{escapeHtml(formatTime(conversation.created_at))}}</div>
            ${{usageTokensLine}}
            ${{usageCostLine}}
          </div>
        `;
        const timelineHtml = events.length
          ? `<div id="conversation-detail-timeline" class="timeline">${{events.map((event, index) => `
              <div class="timeline-item">
                <div class="meta meta-row">
                  <span class="badge ${{getBadgeClass(event.kind || "timeline")}}">${{escapeHtml(event.kind || "timeline")}}</span>
                  <span>${{escapeHtml(formatTime(event.created_at))}}</span>
                </div>
                <strong>${{escapeHtml(event.title || "Update")}}</strong>
                <div class="timeline-body">${{escapeHtml(event.body || "")}}</div>
                ${{
                  canRenderDelegationActions(conversation, event, index, events)
                    ? renderDelegationControls(conversation.conversation_id, event.event_id || `${{conversation.conversation_id}}:${{index}}`)
                    : ""
                }}
              </div>
            `).join("")}}</div>`
          : '<div class="empty-state">No timeline events yet.</div>';
        document.getElementById("conversation-detail-body").innerHTML = `
          ${{renderConversationSkills(conversation, skillState)}}
          ${{timelineHtml}}
        `;
        document.querySelectorAll("[data-delegation-action]").forEach(node => {{
          node.addEventListener("click", () => submitDelegationAction(
            node.dataset.conversationId,
            node.dataset.eventId,
            node.dataset.delegationAction,
          ));
        }});
        document.querySelectorAll("[data-conversation-skill-action]").forEach(node => {{
          node.addEventListener("click", () => submitConversationSkillAction(
            node.dataset.conversationId,
            node.dataset.conversationSkillAction,
            node.dataset.skillName || "",
          ));
        }});
        document.querySelectorAll("[data-runtime-skill-detail]").forEach(node => {{
          node.addEventListener("click", () => loadRuntimeSkillDetail(node.dataset.runtimeSkillDetail));
        }});
        document.querySelectorAll("[data-runtime-skill-install]").forEach(node => {{
          node.addEventListener("click", () => installRuntimeSkill(node.dataset.runtimeSkillInstall));
        }});
      }}

      async function loadConversationDetail(conversationId) {{
        currentConversationId = conversationId;
        try {{
          const [conversationResponse, timelineResponse, skillsResponse] = await Promise.all([
            uiFetch(`/v1/ui/conversations/${{conversationId}}`),
            uiFetch(`/v1/ui/conversations/${{conversationId}}/timeline`),
            uiFetch(`/v1/conversations/${{conversationId}}/skills`),
          ]);
          if (!conversationResponse.ok || !timelineResponse.ok || !skillsResponse.ok) {{
            throw new Error("Failed to load conversation detail.");
          }}
          const conversation = await conversationResponse.json();
          const timeline = await timelineResponse.json();
          const skillState = await skillsResponse.json();
          renderConversationDetail(conversation, timeline.events || [], skillState);
        }} catch (error) {{
          setStatus(error.message || "Failed to load conversation detail.");
        }}
      }}

      async function refreshCurrentDetail() {{
        if (!currentDetailKind || !currentDetailId) return;
        if (currentDetailKind === "conversation") {{
          const exists = (bootstrapData.conversations || []).some(item => item.conversation_id === currentDetailId);
          if (!exists) {{
            clearConversationDetail();
            return;
          }}
          await loadConversationDetail(currentDetailId);
          return;
        }}
        if (currentDetailKind === "bot") {{
          const exists = (bootstrapData.bots || []).some(item => item.agent_id === currentDetailId);
          if (!exists) {{
            clearConversationDetail();
            return;
          }}
          await loadBotDetail(currentDetailId);
          return;
        }}
        if (currentDetailKind === "task") {{
          const task = (bootstrapData.tasks || []).find(item => item.routed_task_id === currentDetailId);
          if (!task) {{
            clearConversationDetail();
            return;
          }}
          renderTaskDetail(task);
        }}
      }}

      async function loadBootstrap() {{
        if (bootstrapLoaded) {{
          setRefreshing(true);
        }}
        try {{
          const response = await uiFetch('/v1/ui/bootstrap', {{
            headers: requestHeaders(),
          }});
          if (!response.ok) {{
            throw new Error(await response.text() || "Registry unavailable.");
          }}
          bootstrapData = await response.json();
          clearErrorBanner();
          setStatus("");
          lastSuccessfulLoad = Date.now();
          bootstrapLoaded = true;
          renderBots(bootstrapData.bots || []);
          var searchInput = document.getElementById('conv-search');
          if (!(searchInput && searchInput.value.trim().length >= 3)) {{
            renderConversations(bootstrapData.conversations || []);
          }}
          renderTasks(bootstrapData.tasks || []);
          if (!runtimeSkillsLoaded) {{
            await loadRuntimeSkills();
          }}
          if (!capabilitiesLoaded) {{
            await loadCapabilities();
          }}
          if (!providerGuidanceLoaded) {{
            const provider = document.getElementById("provider-guidance-select")?.value || "claude";
            await loadProviderGuidanceDetail(provider);
          }}
          await refreshCurrentDetail();
        }} catch (error) {{
          const message = error.message || "Failed to refresh registry UI.";
          showErrorBanner(message);
          setStatus(message);
        }} finally {{
          setRefreshing(false);
        }}
      }}

      async function createConversation() {{
        const targetAgentId = document.getElementById("new-conversation-target").value;
        const messageText = document.getElementById("new-conversation-message").value.trim();
        if (!targetAgentId || !messageText) {{
          setStatus("Choose a connected bot and enter a message.");
          return;
        }}
        const title = messageText.split(/\\n+/)[0].slice(0, 80) || "Registry UI conversation";
        const response = await uiFetch("/v1/ui/conversations", {{
          method: "POST",
          headers: requestHeaders({{ "Content-Type": "application/json" }}),
          body: JSON.stringify({{
            target_agent_id: targetAgentId,
            title,
            message_text: messageText,
          }}),
        }});
        if (!response.ok) {{
          setStatus(await response.text());
          return;
        }}
        const conversation = await response.json();
        toggleNewConversationForm(false);
        await loadBootstrap();
        await loadConversationDetail(conversation.conversation_id);
      }}

      async function sendDetailMessage() {{
        if (!currentConversationId) return;
        const textArea = document.getElementById("detail-message-text");
        const text = textArea.value.trim();
        if (!text) {{
          setStatus("Enter a follow-up message first.");
          return;
        }}
        const response = await uiFetch(`/v1/ui/conversations/${{currentConversationId}}/messages`, {{
          method: "POST",
          headers: requestHeaders({{ "Content-Type": "application/json" }}),
          body: JSON.stringify({{ text }}),
        }});
        if (!response.ok) {{
          setStatus(await response.text());
          return;
        }}
        textArea.value = "";
        await loadBootstrap();
      }}

      async function submitConversationSkillAction(conversationId, action, skillName = "", confirm = false) {{
        let endpoint = "";
        if (action === "activate") {{
          endpoint = `/v1/conversations/${{conversationId}}/skills/${{encodeURIComponent(skillName)}}/activate`;
        }} else if (action === "deactivate") {{
          endpoint = `/v1/conversations/${{conversationId}}/skills/${{encodeURIComponent(skillName)}}/deactivate`;
        }} else if (action === "clear") {{
          endpoint = `/v1/conversations/${{conversationId}}/skills/clear`;
        }} else {{
          setStatus("Unknown runtime skill action.");
          return;
        }}
        const response = await uiFetch(endpoint, {{
          method: "POST",
          headers: requestHeaders({{ "Content-Type": "application/json" }}),
          body: JSON.stringify({{
            actor_key: REGISTRY_UI_ACTOR_KEY,
            confirm,
          }}),
        }});
        const payload = await response.json().catch(() => ({{}}));
        if (!response.ok) {{
          setStatus(payload.detail || "Runtime skill update failed.");
          return;
        }}
        if (payload.status === "needs_confirmation" && !confirm) {{
          const accepted = window.confirm(
            `Adding ${{skillName}} will increase prompt size to ${{payload.projected_size}} characters. Continue?`
          );
          if (accepted) {{
            await submitConversationSkillAction(conversationId, action, skillName, true);
          }}
          return;
        }}
        if (payload.status === "needs_setup") {{
          const requirement = payload.first_requirement?.key || "required credentials";
          setStatus(`Skill ${{skillName}} needs setup before activation: ${{requirement}}.`);
          return;
        }}
        if (payload.status === "foreign_setup") {{
          setStatus("Another credential setup flow is already in progress for this conversation.");
          return;
        }}
        setStatus(
          action === "clear"
            ? "Conversation runtime skills cleared."
            : `Skill ${{skillName}}: ${{payload.status}}.`
        );
        await loadConversationDetail(conversationId);
      }}

      async function loadCapabilities() {{
        const response = await uiFetch('/v1/ui/capabilities', {{
          headers: requestHeaders(),
        }});
        if (!response.ok) {{
          throw new Error(await response.text() || "Failed to load capabilities.");
        }}
        const capabilities = await response.json();
        capabilitiesLoaded = true;
        renderCapabilities(Array.isArray(capabilities) ? capabilities : []);
      }}

      async function loadUsage() {{
        const response = await uiFetch('/v1/ui/usage', {{
          headers: requestHeaders(),
        }});
        if (!response.ok) {{
          throw new Error(await response.text() || "Failed to load reported usage.");
        }}
        const data = await response.json();
        usageSummary = {{
          daily_total: data.daily_total || {{ prompt_tokens: 0, completion_tokens: 0, cost_usd: 0 }},
          by_conversation: Array.isArray(data.by_conversation) ? data.by_conversation : [],
        }};
        renderUsageHeader();
        if (currentConversationDetail && currentConversationDetail.conversation) {{
          renderConversationDetail(
            currentConversationDetail.conversation,
            currentConversationDetail.events || [],
            currentConversationDetail.skillState || null,
          );
        }}
      }}

      async function toggleCapabilityOverride(capabilityName, enable) {{
        const action = enable ? "enable" : "disable";
        const response = await uiFetch(`/v1/ui/capabilities/${{encodeURIComponent(capabilityName)}}/${{action}}`, {{
          method: "POST",
          headers: requestHeaders(),
        }});
        if (!response.ok) {{
          setStatus(await response.text() || "Capability update failed.");
        }}
        await loadCapabilities();
      }}

      async function cancelConversation() {{
        if (!currentConversationId) return;
        const response = await uiFetch(`/v1/ui/conversations/${{currentConversationId}}/actions`, {{
          method: "POST",
          headers: requestHeaders({{ "Content-Type": "application/json" }}),
          body: JSON.stringify({{ action: "cancel_conversation" }}),
        }});
        if (!response.ok) {{
          setStatus(await response.text());
          return;
        }}
        await loadBootstrap();
      }}

      async function exportConversation() {{
        if (!currentConversationId) return;
        const url = '/v1/ui/conversations/' + encodeURIComponent(currentConversationId) + '/export';
        try {{
          const response = await uiFetch(url, {{
            headers: requestHeaders(),
          }});
          if (!response.ok) {{
            console.error('Export failed', response.status);
            setStatus('Export failed.');
            return;
          }}
          const blob = await response.blob();
          const link = document.createElement('a');
          const objectUrl = URL.createObjectURL(blob);
          link.href = objectUrl;
          link.download = 'conversation-' + currentConversationId + '.md';
          document.body.appendChild(link);
          link.click();
          document.body.removeChild(link);
          URL.revokeObjectURL(objectUrl);
        }} catch (error) {{
          console.error('Export error', error);
          setStatus('Export failed.');
        }}
      }}

      async function submitDelegationAction(conversationId, eventId, action) {{
        delegationActionState[eventId] = action;
        delete delegationActionError[eventId];
        if (currentConversationDetail && currentConversationDetail.conversation.conversation_id === conversationId) {{
          renderConversationDetail(
            currentConversationDetail.conversation,
            currentConversationDetail.events,
            currentConversationDetail.skillState || null,
          );
        }}
        const response = await uiFetch(`/v1/ui/conversations/${{conversationId}}/actions`, {{
          method: "POST",
          headers: requestHeaders({{ "Content-Type": "application/json" }}),
          body: JSON.stringify({{ action }}),
        }});
        if (!response.ok) {{
          delete delegationActionState[eventId];
          delegationActionError[eventId] = "Action failed — try again.";
          if (currentConversationDetail && currentConversationDetail.conversation.conversation_id === conversationId) {{
            renderConversationDetail(
              currentConversationDetail.conversation,
              currentConversationDetail.events,
              currentConversationDetail.skillState || null,
            );
          }}
          return;
        }}
        delete delegationActionState[eventId];
        delete delegationActionError[eventId];
        if (currentConversationDetail && currentConversationDetail.conversation.conversation_id === conversationId) {{
          renderConversationDetail(
            currentConversationDetail.conversation,
            currentConversationDetail.events,
            currentConversationDetail.skillState || null,
          );
        }}
        await loadBootstrap();
      }}

      document.getElementById("new-conversation-button").addEventListener("click", () => toggleNewConversationForm(true));
      document.getElementById("cancel-new-conversation-button").addEventListener("click", () => toggleNewConversationForm(false));
      document.getElementById("start-conversation-button").addEventListener("click", createConversation);
      document.getElementById("detail-export-button").addEventListener("click", exportConversation);
      document.getElementById("detail-send-button").addEventListener("click", sendDetailMessage);
      document.getElementById("detail-cancel-button").addEventListener("click", cancelConversation);
      document.getElementById("detail-back-button").addEventListener("click", clearConversationDetail);
      document.getElementById("runtime-skill-search-button").addEventListener("click", () => {{
        loadRuntimeSkills(document.getElementById("runtime-skill-search").value.trim()).catch(error => {{
          setStatus(error.message || "Failed to search runtime skills.");
        }});
      }});
      document.getElementById("runtime-skill-create-button").addEventListener("click", () => {{
        createRuntimeSkillDraft().catch(error => {{
          setStatus(error.message || "Failed to create runtime skill draft.");
        }});
      }});
      document.getElementById("runtime-skill-reset-button").addEventListener("click", () => {{
        document.getElementById("runtime-skill-search").value = "";
        loadRuntimeSkills().catch(error => {{
          setStatus(error.message || "Failed to load runtime skills.");
        }});
      }});
      document.getElementById("runtime-skill-search").addEventListener("keydown", event => {{
        if (event.key !== "Enter") return;
        event.preventDefault();
        loadRuntimeSkills(document.getElementById("runtime-skill-search").value.trim()).catch(error => {{
          setStatus(error.message || "Failed to search runtime skills.");
        }});
      }});
      document.getElementById("runtime-skill-create-name").addEventListener("keydown", event => {{
        if (event.key !== "Enter") return;
        event.preventDefault();
        createRuntimeSkillDraft().catch(error => {{
          setStatus(error.message || "Failed to create runtime skill draft.");
        }});
      }});
      document.getElementById("provider-guidance-load-button").addEventListener("click", () => {{
        const provider = document.getElementById("provider-guidance-select").value;
        loadProviderGuidanceDetail(provider).catch(error => {{
          setStatus(error.message || "Failed to load provider guidance.");
        }});
      }});
      var convSearchEl = document.getElementById('conv-search');
      if (convSearchEl) {{
        convSearchEl.addEventListener('input', function() {{
          var q = this.value.trim();
          clearTimeout(_convSearchTimer);
          if (q.length >= 3) {{
            _convSearchTimer = setTimeout(function() {{
              refreshConversationPanel().catch(function() {{}});
            }}, 300);
          }} else {{
            renderConversations(bootstrapData.conversations || []);
          }}
        }});
      }}
      ['conv-status', 'conv-date'].forEach(function(id) {{
        var el = document.getElementById(id);
        if (el) el.addEventListener('change', function() {{
          var search = document.getElementById('conv-search');
          if (search && search.value.trim().length >= 3) return;
          renderConversations(bootstrapData.conversations || []);
        }});
      }});

      setInterval(() => {{
        if (!lastSuccessfulLoad) return;
        const age = Math.floor((Date.now() - lastSuccessfulLoad) / 1000);
        const el = document.getElementById("last-updated");
        if (!el) return;
        el.textContent = age < 5 ? "Just updated" : `Updated ${{age}}s ago`;
        el.style.color = age > 60 ? "#ef4444" : age > 30 ? "#f59e0b" : "#6b7280";
      }}, 1000);

      loadBootstrap().catch(error => {{
        const message = error.message || "Failed to load registry UI.";
        showErrorBanner(message);
        setStatus(message);
      }});
      loadUsage().catch(() => {{}});
      setInterval(() => {{
        loadBootstrap().catch(error => {{
          const message = error.message || "Failed to refresh registry UI.";
          showErrorBanner(message);
          setStatus(message);
        }});
      }}, 5000);
      setInterval(() => {{
        loadUsage().catch(() => {{}});
      }}, 60000);
    </script>
  </body>
</html>"""
