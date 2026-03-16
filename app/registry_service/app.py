"""FastAPI registry control-plane application."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import HTMLResponse

from app.registry_service.store import RegistryStore


@dataclass(frozen=True)
class RegistrySettings:
    db_path: Path
    enroll_token: str
    ui_token: str


def load_settings() -> RegistrySettings:
    db_path = Path(os.environ.get("REGISTRY_DB_PATH", "/tmp/telegram-agent-registry/registry.sqlite3"))
    enroll_token = os.environ.get("REGISTRY_ENROLL_TOKEN", "dev-enroll-token")
    ui_token = os.environ.get("REGISTRY_UI_TOKEN", "dev-ui-token")
    return RegistrySettings(db_path=db_path, enroll_token=enroll_token, ui_token=ui_token)


def get_store() -> RegistryStore:
    return RegistryStore(load_settings().db_path)


def require_agent_token(
    authorization: str | None = Header(default=None),
    store: RegistryStore = Depends(get_store),
) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    return authorization.removeprefix("Bearer ").strip()


def require_ui_token(
    authorization: str | None = Header(default=None),
) -> None:
    settings = load_settings()
    token = ""
    if authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ").strip()
    if token != settings.ui_token:
        raise HTTPException(status_code=401, detail="Invalid UI token")


app = FastAPI(title="Telegram Agent Registry", version="0.1.0")


@app.get("/healthz")
def healthz(store: RegistryStore = Depends(get_store)) -> dict[str, Any]:
    return {"ok": True, "bots": len(store.list_agents())}


@app.post("/v1/agents/enroll")
def enroll(payload: dict[str, Any], store: RegistryStore = Depends(get_store)) -> dict[str, Any]:
    settings = load_settings()
    if payload.get("enrollment_token") != settings.enroll_token:
        raise HTTPException(status_code=401, detail="Invalid enrollment token")
    agent_card = payload.get("agent_card") or {}
    return store.enroll(agent_card)


@app.post("/v1/agents/register")
def register(
    payload: dict[str, Any],
    agent_token: str = Depends(require_agent_token),
    store: RegistryStore = Depends(get_store),
) -> dict[str, Any]:
    try:
        return store.register(agent_token, payload)
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@app.post("/v1/agents/heartbeat")
def heartbeat(
    payload: dict[str, Any],
    agent_token: str = Depends(require_agent_token),
    store: RegistryStore = Depends(get_store),
) -> dict[str, Any]:
    try:
        return store.heartbeat(agent_token, payload)
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@app.post("/v1/agents/timeline")
def publish_timeline(
    payload: dict[str, Any],
    agent_token: str = Depends(require_agent_token),
    store: RegistryStore = Depends(get_store),
) -> dict[str, Any]:
    try:
        return store.publish_timeline(agent_token, payload.get("events", []))
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@app.post("/v1/agents/conversations/bind")
def bind_conversation(
    payload: dict[str, Any],
    agent_token: str = Depends(require_agent_token),
    store: RegistryStore = Depends(get_store),
) -> dict[str, Any]:
    try:
        return store.bind_conversation(agent_token, payload)
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@app.post("/v1/agents/discovery/search")
def search_agents(
    payload: dict[str, Any],
    agent_token: str = Depends(require_agent_token),
    store: RegistryStore = Depends(get_store),
) -> dict[str, Any]:
    try:
        # Auth check only; search itself does not need the token contents.
        store.heartbeat(agent_token, {"connectivity_state": "connected"})
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return {"agents": store.search_agents(payload)}


@app.post("/v1/agents/routed-tasks")
def create_routed_task(
    payload: dict[str, Any],
    agent_token: str = Depends(require_agent_token),
    store: RegistryStore = Depends(get_store),
) -> dict[str, Any]:
    try:
        store.heartbeat(agent_token, {"connectivity_state": "connected"})
        return store.create_routed_task(payload)
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@app.get("/v1/agents/poll")
def poll(
    cursor: str = Query(default="0"),
    limit: int = Query(default=20, ge=1, le=100),
    wait_seconds: int = Query(default=1, ge=0, le=30),
    agent_token: str = Depends(require_agent_token),
    store: RegistryStore = Depends(get_store),
) -> dict[str, Any]:
    del wait_seconds
    try:
        return store.poll(agent_token, cursor=int(cursor or "0"), limit=limit)
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@app.post("/v1/agents/ack")
def ack(
    payload: dict[str, Any],
    agent_token: str = Depends(require_agent_token),
    store: RegistryStore = Depends(get_store),
) -> dict[str, Any]:
    try:
        return store.ack(
            agent_token,
            delivery_ids=list(payload.get("delivery_ids", [])),
            classification=payload.get("classification", "accepted"),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@app.post("/v1/agents/routed-tasks/{routed_task_id}/status")
def routed_task_status(
    routed_task_id: str,
    payload: dict[str, Any],
    agent_token: str = Depends(require_agent_token),
    store: RegistryStore = Depends(get_store),
) -> dict[str, Any]:
    try:
        return store.update_routed_task_status(agent_token, routed_task_id, payload)
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@app.post("/v1/agents/routed-tasks/{routed_task_id}/result")
def routed_task_result(
    routed_task_id: str,
    payload: dict[str, Any],
    agent_token: str = Depends(require_agent_token),
    store: RegistryStore = Depends(get_store),
) -> dict[str, Any]:
    try:
        return store.update_routed_task_result(agent_token, routed_task_id, payload)
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown routed task: {routed_task_id}") from exc


@app.post("/v1/agents/deregister")
def deregister(
    agent_token: str = Depends(require_agent_token),
    store: RegistryStore = Depends(get_store),
) -> dict[str, Any]:
    try:
        return store.deregister(agent_token)
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@app.get("/ui", response_class=HTMLResponse)
def ui_shell(token: str = Query(default="")) -> str:
    if token != load_settings().ui_token:
        raise HTTPException(status_code=401, detail="Invalid UI token")
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Agent Registry</title>
    <style>
      :root {{
        color-scheme: dark;
        font-family: "IBM Plex Sans", "Avenir Next", sans-serif;
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
      .list {{
        display: grid;
        gap: 10px;
      }}
      .item {{
        padding: 12px 14px;
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 14px;
        background: rgba(255,255,255,0.03);
      }}
      .item.clickable {{
        cursor: pointer;
        transition: transform 120ms ease, border-color 120ms ease, background 120ms ease;
      }}
      .item.clickable:hover {{
        transform: translateY(-1px);
        border-color: rgba(230, 194, 41, 0.42);
        background: rgba(255,255,255,0.05);
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
        background: rgba(230, 194, 41, 0.18);
        border: 1px solid rgba(230, 194, 41, 0.35);
        font-size: 12px;
        color: #f5f3ee;
      }}
      .state-badge::before {{
        content: "";
        width: 0.5rem;
        height: 0.5rem;
        border-radius: 999px;
        background: currentColor;
      }}
      .state-connected {{
        color: var(--green);
        border-color: rgba(94, 197, 126, 0.35);
        background: rgba(94, 197, 126, 0.14);
      }}
      .state-degraded {{
        color: var(--amber);
        border-color: rgba(242, 178, 79, 0.35);
        background: rgba(242, 178, 79, 0.14);
      }}
      .state-standalone {{
        color: var(--muted-state);
        border-color: rgba(127, 139, 168, 0.3);
        background: rgba(127, 139, 168, 0.12);
      }}
      .state-offline {{
        color: var(--red);
        border-color: rgba(239, 115, 102, 0.35);
        background: rgba(239, 115, 102, 0.14);
      }}
      .toolbar {{
        display: flex;
        flex-wrap: wrap;
        gap: 0.6rem;
        align-items: center;
      }}
      button, select, textarea {{
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
      select, textarea {{
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
      .empty {{
        color: var(--muted);
        padding: 1.2rem 0.2rem;
      }}
      @media (max-width: 1200px) {{
        main {{
          grid-template-columns: 1fr;
        }}
      }}
    </style>
  </head>
  <body>
    <header>
      <div>
        <h1>Agent Registry</h1>
        <div class="subtle">Live directory, routed work board, and shared conversation visibility for private bots.</div>
      </div>
      <div id="ui-status" class="status-line"></div>
    </header>
    <main>
      <section>
        <div class="panel-header">
          <h2>Bots</h2>
          <span class="subtle">Live directory</span>
        </div>
        <div id="bots" class="list"></div>
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
        <div id="conversations" class="list"></div>
      </section>
      <section>
        <div class="panel-header">
          <h2>Conversation Detail</h2>
          <button id="detail-back-button" class="secondary hidden" type="button">Back to list</button>
        </div>
        <div id="conversation-detail-empty" class="empty">Select a conversation to inspect its timeline and send follow-up messages.</div>
        <div id="conversation-detail" class="hidden">
          <div id="conversation-detail-header" class="list"></div>
          <div id="conversation-detail-timeline" class="timeline"></div>
          <div class="detail-actions">
            <label>
              New message
              <textarea id="detail-message-text" placeholder="Add a follow-up message to this conversation."></textarea>
            </label>
            <div class="toolbar">
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
        <div id="tasks" class="list"></div>
      </section>
    </main>
    <script>
      const token = {token!r};
      let bootstrapData = {{ bots: [], conversations: [], tasks: [] }};
      let currentConversationId = "";
      let currentConversationDetail = null;
      const delegationActionState = Object.create(null);
      const delegationActionError = Object.create(null);

      function authHeaders(extra = {{}}) {{
        return {{ Authorization: `Bearer ${{token}}`, ...extra }};
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

      function stateBadge(item) {{
        const state = item?.connectivity_state || item?.status || "unknown";
        const klass = ["connected", "degraded", "standalone", "offline"].includes(state)
          ? `state-${{state}}`
          : "state-standalone";
        return `<span class="badge state-badge ${{klass}}">${{escapeHtml(state)}}</span>`;
      }}

      function setStatus(message) {{
        document.getElementById("ui-status").textContent = message || "";
      }}

      function renderList(id, items, template) {{
        document.getElementById(id).innerHTML = items.length
          ? items.map(template).join("")
          : '<div class="item"><div class="meta">Nothing yet.</div></div>';
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

      function renderBots(items) {{
        renderList("bots", items, item => `
          <div class="item">
            <strong>${{escapeHtml(item.display_name)}}</strong>
            <div class="meta meta-row">${{stateBadge(item)}}<span>${{escapeHtml(item.role || "unassigned role")}}</span></div>
            <div class="meta">${{escapeHtml((item.skills || []).join(", ") || "no skills declared")}}</div>
          </div>
        `);
      }}

      function renderConversations(items) {{
        renderList("conversations", items, item => `
          <div class="item clickable" data-conversation-id="${{escapeHtml(item.conversation_id)}}">
            <strong>${{escapeHtml(item.title || item.conversation_id)}}</strong>
            <div class="meta">${{escapeHtml(item.target_display_name || item.target_agent_id)}}</div>
            <div class="meta meta-row">
              <span class="badge">${{escapeHtml(item.status || "open")}}</span>
              <span>${{escapeHtml(String(item.timeline_event_count ?? 0))}} event(s)</span>
            </div>
          </div>
        `);
        document.querySelectorAll("[data-conversation-id]").forEach(node => {{
          node.addEventListener("click", () => loadConversationDetail(node.dataset.conversationId));
        }});
      }}

      function renderTasks(items) {{
        renderList("tasks", items, item => `
          <div class="item">
            <strong>${{escapeHtml(item.title)}}</strong>
            <div class="meta">${{escapeHtml(item.origin_display_name || item.origin_agent_id)}} → ${{escapeHtml(item.target_display_name || item.target_agent_id)}}</div>
            <div class="meta meta-row"><span class="badge">${{escapeHtml(item.status || "queued")}}</span><span>${{escapeHtml(item.summary || "")}}</span></div>
          </div>
        `);
      }}

      function clearConversationDetail() {{
        currentConversationId = "";
        currentConversationDetail = null;
        document.getElementById("conversation-detail").classList.add("hidden");
        document.getElementById("conversation-detail-empty").classList.remove("hidden");
        document.getElementById("detail-back-button").classList.add("hidden");
        document.getElementById("conversation-detail-header").innerHTML = "";
        document.getElementById("conversation-detail-timeline").innerHTML = "";
        document.getElementById("detail-message-text").value = "";
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

      function renderConversationDetail(conversation, events) {{
        currentConversationDetail = {{ conversation, events }};
        document.getElementById("conversation-detail-empty").classList.add("hidden");
        document.getElementById("conversation-detail").classList.remove("hidden");
        document.getElementById("detail-back-button").classList.remove("hidden");
        document.getElementById("conversation-detail-header").innerHTML = `
          <div class="item">
            <strong>${{escapeHtml(conversation.title || conversation.conversation_id)}}</strong>
            <div class="meta">${{escapeHtml(conversation.target_display_name || conversation.target_agent_id)}}</div>
            <div class="meta meta-row">
              <span class="badge">${{escapeHtml(conversation.status || "open")}}</span>
              <span>${{escapeHtml(String(conversation.timeline_event_count ?? events.length))}} event(s)</span>
            </div>
            <div class="meta">Created ${{escapeHtml(formatTime(conversation.created_at))}}</div>
          </div>
        `;
        document.getElementById("conversation-detail-timeline").innerHTML = events.length
          ? events.map((event, index) => `
              <div class="timeline-item">
                <div class="meta meta-row">
                  <span class="badge">${{escapeHtml(event.kind || "timeline")}}</span>
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
            `).join("")
          : '<div class="empty">No timeline events yet.</div>';
        document.querySelectorAll("[data-delegation-action]").forEach(node => {{
          node.addEventListener("click", () => submitDelegationAction(
            node.dataset.conversationId,
            node.dataset.eventId,
            node.dataset.delegationAction,
          ));
        }});
      }}

      async function loadConversationDetail(conversationId) {{
        currentConversationId = conversationId;
        try {{
          const [conversationResponse, timelineResponse] = await Promise.all([
            fetch(`/v1/ui/conversations/${{conversationId}}`, {{ headers: authHeaders() }}),
            fetch(`/v1/ui/conversations/${{conversationId}}/timeline`, {{ headers: authHeaders() }}),
          ]);
          if (!conversationResponse.ok || !timelineResponse.ok) {{
            throw new Error("Failed to load conversation detail.");
          }}
          const conversation = await conversationResponse.json();
          const timeline = await timelineResponse.json();
          renderConversationDetail(conversation, timeline.events || []);
        }} catch (error) {{
          setStatus(error.message || "Failed to load conversation detail.");
        }}
      }}

      async function loadBootstrap() {{
        const response = await fetch('/v1/ui/bootstrap', {{
          headers: authHeaders(),
        }});
        if (!response.ok) {{
          document.body.innerHTML = `<main><section><h2>Registry unavailable</h2><pre>${{await response.text()}}</pre></section></main>`;
          return;
        }}
        bootstrapData = await response.json();
        renderBots(bootstrapData.bots || []);
        renderConversations(bootstrapData.conversations || []);
        renderTasks(bootstrapData.tasks || []);
        if (currentConversationId) {{
          const exists = (bootstrapData.conversations || []).some(item => item.conversation_id === currentConversationId);
          if (exists) {{
            await loadConversationDetail(currentConversationId);
          }} else {{
            clearConversationDetail();
          }}
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
        const response = await fetch("/v1/ui/conversations", {{
          method: "POST",
          headers: authHeaders({{ "Content-Type": "application/json" }}),
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
        const response = await fetch(`/v1/ui/conversations/${{currentConversationId}}/messages`, {{
          method: "POST",
          headers: authHeaders({{ "Content-Type": "application/json" }}),
          body: JSON.stringify({{ text }}),
        }});
        if (!response.ok) {{
          setStatus(await response.text());
          return;
        }}
        textArea.value = "";
        await loadBootstrap();
      }}

      async function cancelConversation() {{
        if (!currentConversationId) return;
        const response = await fetch(`/v1/ui/conversations/${{currentConversationId}}/cancel`, {{
          method: "POST",
          headers: authHeaders({{ "Content-Type": "application/json" }}),
        }});
        if (!response.ok) {{
          setStatus(await response.text());
          return;
        }}
        await loadBootstrap();
      }}

      async function submitDelegationAction(conversationId, eventId, action) {{
        delegationActionState[eventId] = action;
        delete delegationActionError[eventId];
        if (currentConversationDetail && currentConversationDetail.conversation.conversation_id === conversationId) {{
          renderConversationDetail(currentConversationDetail.conversation, currentConversationDetail.events);
        }}
        const response = await fetch(`/v1/ui/conversations/${{conversationId}}/actions`, {{
          method: "POST",
          headers: authHeaders({{ "Content-Type": "application/json" }}),
          body: JSON.stringify({{ action }}),
        }});
        if (!response.ok) {{
          delete delegationActionState[eventId];
          delegationActionError[eventId] = "Action failed — try again.";
          if (currentConversationDetail && currentConversationDetail.conversation.conversation_id === conversationId) {{
            renderConversationDetail(currentConversationDetail.conversation, currentConversationDetail.events);
          }}
          return;
        }}
        delete delegationActionState[eventId];
        delete delegationActionError[eventId];
        await loadBootstrap();
      }}

      document.getElementById("new-conversation-button").addEventListener("click", () => toggleNewConversationForm(true));
      document.getElementById("cancel-new-conversation-button").addEventListener("click", () => toggleNewConversationForm(false));
      document.getElementById("start-conversation-button").addEventListener("click", createConversation);
      document.getElementById("detail-send-button").addEventListener("click", sendDetailMessage);
      document.getElementById("detail-cancel-button").addEventListener("click", cancelConversation);
      document.getElementById("detail-back-button").addEventListener("click", clearConversationDetail);

      loadBootstrap().catch(error => setStatus(error.message || "Failed to load registry UI."));
      setInterval(() => {{
        loadBootstrap().catch(error => setStatus(error.message || "Failed to refresh registry UI."));
      }}, 5000);
    </script>
  </body>
</html>"""


@app.get("/v1/ui/bootstrap")
def ui_bootstrap(_: None = Depends(require_ui_token), store: RegistryStore = Depends(get_store)) -> dict[str, Any]:
    return store.ui_bootstrap()


@app.get("/v1/ui/bots")
def ui_bots(_: None = Depends(require_ui_token), store: RegistryStore = Depends(get_store)) -> dict[str, Any]:
    return {"bots": store.list_agents()}


@app.get("/v1/ui/conversations")
def ui_conversations(_: None = Depends(require_ui_token), store: RegistryStore = Depends(get_store)) -> dict[str, Any]:
    return {"conversations": store.list_conversations()}


@app.post("/v1/ui/conversations")
def ui_create_conversation(
    payload: dict[str, Any],
    _: None = Depends(require_ui_token),
    store: RegistryStore = Depends(get_store),
) -> dict[str, Any]:
    return store.create_conversation(
        target_agent_id=payload["target_agent_id"],
        title=payload.get("title", ""),
        message_text=payload.get("message_text", ""),
    )


@app.get("/v1/ui/conversations/{conversation_id}")
def ui_get_conversation(
    conversation_id: str,
    _: None = Depends(require_ui_token),
    store: RegistryStore = Depends(get_store),
) -> dict[str, Any]:
    try:
        return store.get_conversation(conversation_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown conversation: {conversation_id}") from exc


@app.get("/v1/ui/conversations/{conversation_id}/timeline")
def ui_get_conversation_timeline(
    conversation_id: str,
    _: None = Depends(require_ui_token),
    store: RegistryStore = Depends(get_store),
) -> dict[str, Any]:
    return {"events": store.get_conversation_timeline(conversation_id)}


@app.post("/v1/ui/conversations/{conversation_id}/messages")
def ui_add_conversation_message(
    conversation_id: str,
    payload: dict[str, Any],
    _: None = Depends(require_ui_token),
    store: RegistryStore = Depends(get_store),
) -> dict[str, Any]:
    return store.add_conversation_message(conversation_id, payload.get("text", ""))


@app.post("/v1/ui/conversations/{conversation_id}/actions")
def ui_add_conversation_action(
    conversation_id: str,
    payload: dict[str, Any],
    _: None = Depends(require_ui_token),
    store: RegistryStore = Depends(get_store),
) -> dict[str, Any]:
    return store.add_conversation_action(
        conversation_id,
        payload.get("action", ""),
        payload.get("payload", {}),
    )


@app.post("/v1/ui/conversations/{conversation_id}/cancel")
def ui_cancel_conversation(
    conversation_id: str,
    _: None = Depends(require_ui_token),
    store: RegistryStore = Depends(get_store),
) -> dict[str, Any]:
    return store.cancel_conversation(conversation_id)


@app.get("/v1/ui/tasks")
def ui_tasks(_: None = Depends(require_ui_token), store: RegistryStore = Depends(get_store)) -> dict[str, Any]:
    return {"tasks": store.list_tasks()}
