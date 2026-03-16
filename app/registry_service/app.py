"""FastAPI registry control-plane application."""

from __future__ import annotations

import hmac
import html
import logging
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Form, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

from app.registry_service.store import RegistryStore

log = logging.getLogger(__name__)
_SESSION_TTL_SECONDS = 24 * 60 * 60
_WARNED_MISSING_UI_TOKEN = False


@dataclass(frozen=True)
class RegistrySettings:
    db_path: Path
    enroll_token: str
    ui_token: str
    display_name: str


def load_settings() -> RegistrySettings:
    db_path = Path(os.environ.get("REGISTRY_DB_PATH", "/tmp/telegram-agent-registry/registry.sqlite3"))
    enroll_token = os.environ.get("REGISTRY_ENROLL_TOKEN", "dev-enroll-token")
    ui_token = os.environ.get("REGISTRY_UI_TOKEN", "").strip()
    display_name = os.environ.get("REGISTRY_DISPLAY_NAME", "").strip()
    global _WARNED_MISSING_UI_TOKEN
    if not ui_token and not _WARNED_MISSING_UI_TOKEN:
        log.warning("REGISTRY_UI_TOKEN is not set — Registry UI is running unauthenticated.")
        _WARNED_MISSING_UI_TOKEN = True
    return RegistrySettings(db_path=db_path, enroll_token=enroll_token, ui_token=ui_token, display_name=display_name)


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
    if not settings.ui_token:
        return
    token = ""
    if authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ").strip()
    if not hmac.compare_digest(token, settings.ui_token):
        raise HTTPException(status_code=401, detail="Invalid UI token")


def _session_is_valid(request: Request) -> bool:
    settings = load_settings()
    if not settings.ui_token:
        return True
    return request.session.get("ui_authenticated") is True


def _require_session(request: Request) -> None:
    if _session_is_valid(request):
        return
    raise HTTPException(status_code=302, headers={"Location": "/ui/login"})


def _login_html(settings: RegistrySettings, *, error: str = "") -> str:
    heading = settings.display_name or "Agent Registry"
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


app = FastAPI(title="Telegram Agent Registry", version="0.1.0")
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("REGISTRY_SESSION_SECRET", secrets.token_hex(32)),
    session_cookie="registry_session",
    same_site="strict",
    max_age=_SESSION_TTL_SECONDS,
)


@app.get("/healthz")
def healthz(store: RegistryStore = Depends(get_store)) -> dict[str, Any]:
    return {"ok": True, "bots": len(store.list_agents())}


@app.post("/v1/agents/enroll")
def enroll(payload: dict[str, Any], store: RegistryStore = Depends(get_store)) -> dict[str, Any]:
    settings = load_settings()
    enroll_tok = payload.get("enrollment_token") or ""
    if not hmac.compare_digest(enroll_tok, settings.enroll_token):
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


@app.get("/ui/login", response_class=HTMLResponse)
def ui_login_page(request: Request):
    settings = load_settings()
    if _session_is_valid(request):
        return RedirectResponse("/ui", status_code=303)
    if not settings.ui_token:
        return RedirectResponse("/ui", status_code=303)
    return HTMLResponse(_login_html(settings))


@app.post("/ui/login")
async def ui_login(request: Request, password: str = Form(default="")):
    settings = load_settings()
    if _session_is_valid(request):
        return RedirectResponse("/ui", status_code=303)
    if settings.ui_token and not hmac.compare_digest(password, settings.ui_token):
        return HTMLResponse(_login_html(settings, error="Incorrect password."))
    request.session["ui_authenticated"] = True
    return RedirectResponse("/ui", status_code=303)


@app.get("/ui/logout")
def ui_logout(request: Request):
    request.session.clear()
    return RedirectResponse("/ui/login", status_code=303)


@app.get("/ui", response_class=HTMLResponse)
def ui_shell(request: Request) -> str:
    _require_session(request)
    settings = load_settings()
    title_text = f"{settings.display_name} — Agent Registry" if settings.display_name else "Agent Registry"
    heading_text = settings.display_name or "Agent Registry"
    logout_link = (
        '<a href="/ui/logout" class="nav-link">Logout</a>'
        if settings.ui_token else
        ""
    )
    # TODO M11: add a read-only access panel once the registry has a bot-to-registry
    # sync protocol for user_access overrides; the registry service cannot read
    # the bot-local transport.db directly.
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
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
      @media (max-width: 1200px) {{
        main {{
          grid-template-columns: 1fr;
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
    </main>
    <script>
      const token = {settings.ui_token!r};
      const EMPTY_STATES = {{
        bots: "No bots connected yet. Start a bot in registry mode and it will appear here.<br><code>./scripts/app/guided_start.sh</code>",
        conversations: "No conversations yet. Send a message to your bot in Telegram to start.",
        tasks: "No routed tasks yet. Delegated tasks appear here in real time.",
      }};
      let bootstrapData = {{ bots: [], conversations: [], tasks: [] }};
      let bootstrapLoaded = false;
      let lastSuccessfulLoad = 0;
      let currentDetailKind = "";
      let currentDetailId = "";
      let currentConversationId = "";
      let currentConversationDetail = null;
      const delegationActionState = Object.create(null);
      const delegationActionError = Object.create(null);
      var _convSearchTimer = null;

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
          cancelled: "badge-failed",
          running: "badge-running",
          open: "badge-open",
          cancelling: "badge-cancelling",
          completed: "badge-completed",
        }};
        return map[s] || "";
      }}

      function stateBadge(item) {{
        const state = item?.connectivity_state || item?.status || "unknown";
        return `<span class="badge ${{getBadgeClass(state)}}">${{escapeHtml(state)}}</span>`;
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
              <span class="badge ${{getBadgeClass(item.status || "open")}}">${{escapeHtml(item.status || "open")}}</span>
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
          var normalizedStatus = (c.status || "") === "completed" ? "done" : (c.status || "");
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
            const response = await fetch('/v1/ui/search?q=' + encodeURIComponent(q), {{
              headers: authHeaders(),
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
            <div class="meta">${{escapeHtml(item.description || (item.skills || []).join(", ") || "no skills declared")}}</div>
          </button>
        `, "bots");
        document.querySelectorAll("[data-bot-id]").forEach(node => {{
          node.addEventListener("click", () => {{
            const bot = (bootstrapData.bots || []).find(item => item.agent_id === node.dataset.botId);
            if (bot) renderBotDetail(bot);
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
            <div class="meta meta-row"><span class="badge ${{getBadgeClass(item.status || "queued")}}">${{escapeHtml(item.status || "queued")}}</span><span>${{escapeHtml(item.summary || "")}}</span></div>
          </button>
        `, "tasks");
        document.querySelectorAll("[data-task-id]").forEach(node => {{
          node.addEventListener("click", () => {{
            const task = (bootstrapData.tasks || []).find(item => item.routed_task_id === node.dataset.taskId);
            if (task) renderTaskDetail(task);
          }});
        }});
      }}

      function renderBotDetail(bot) {{
        currentDetailKind = "bot";
        currentDetailId = bot.agent_id || "";
        currentConversationId = "";
        currentConversationDetail = null;
        showDetailPanel("Bot Detail");
        setConversationActionsVisible(false);
        document.getElementById("conversation-detail-header").innerHTML = `
          <div class="detail-card">
            <strong>${{escapeHtml(bot.display_name || bot.agent_id)}}</strong>
            <div class="meta meta-row">
              ${{stateBadge(bot)}}
              <span>${{escapeHtml(bot.role || "unassigned role")}}</span>
            </div>
          </div>
        `;
        document.getElementById("conversation-detail-body").innerHTML = `
          <div class="detail-card">
            <div class="meta"><strong>Description:</strong> ${{escapeHtml(bot.description || "No description provided.")}}</div>
            <div class="meta"><strong>Skills:</strong> ${{escapeHtml((bot.skills || []).join(", ") || "No skills declared")}}</div>
            <div class="meta"><strong>Tags:</strong> ${{escapeHtml((bot.tags || []).join(", ") || "No tags declared")}}</div>
            <div class="meta"><strong>Version:</strong> ${{escapeHtml(bot.version || "unknown")}}</div>
            <div class="meta"><strong>Last heartbeat:</strong> ${{escapeHtml(formatTime(bot.last_heartbeat_at) || "unknown")}}</div>
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
              <span class="badge ${{getBadgeClass(task.status || "queued")}}">${{escapeHtml(task.status || "queued")}}</span>
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

      function renderConversationDetail(conversation, events) {{
        currentDetailKind = "conversation";
        currentDetailId = conversation.conversation_id || "";
        currentConversationId = conversation.conversation_id || "";
        currentConversationDetail = {{ conversation, events }};
        showDetailPanel("Conversation Detail");
        setConversationActionsVisible(true);
        document.getElementById("conversation-detail-header").innerHTML = `
          <div class="detail-card">
            <strong>${{escapeHtml(conversation.title || conversation.conversation_id)}}</strong>
            <div class="meta">${{escapeHtml(conversation.target_display_name || conversation.target_agent_id)}}</div>
            <div class="meta meta-row">
              <span class="badge ${{getBadgeClass(conversation.status || "open")}}">${{escapeHtml(conversation.status || "open")}}</span>
              <span>${{escapeHtml(String(conversation.timeline_event_count ?? events.length))}} event(s)</span>
            </div>
            <div class="meta">Created ${{escapeHtml(formatTime(conversation.created_at))}}</div>
          </div>
        `;
        document.getElementById("conversation-detail-body").innerHTML = events.length
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
          const bot = (bootstrapData.bots || []).find(item => item.agent_id === currentDetailId);
          if (!bot) {{
            clearConversationDetail();
            return;
          }}
          renderBotDetail(bot);
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
          const response = await fetch('/v1/ui/bootstrap', {{
            headers: authHeaders(),
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
        if (currentConversationDetail && currentConversationDetail.conversation.conversation_id === conversationId) {{
          renderConversationDetail(currentConversationDetail.conversation, currentConversationDetail.events);
        }}
        await loadBootstrap();
      }}

      document.getElementById("new-conversation-button").addEventListener("click", () => toggleNewConversationForm(true));
      document.getElementById("cancel-new-conversation-button").addEventListener("click", () => toggleNewConversationForm(false));
      document.getElementById("start-conversation-button").addEventListener("click", createConversation);
      document.getElementById("detail-send-button").addEventListener("click", sendDetailMessage);
      document.getElementById("detail-cancel-button").addEventListener("click", cancelConversation);
      document.getElementById("detail-back-button").addEventListener("click", clearConversationDetail);
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
      setInterval(() => {{
        loadBootstrap().catch(error => {{
          const message = error.message || "Failed to refresh registry UI.";
          showErrorBanner(message);
          setStatus(message);
        }});
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


@app.get("/v1/ui/search")
def ui_search(
    q: str = "",
    limit: int = 20,
    _: None = Depends(require_ui_token),
    store: RegistryStore = Depends(get_store),
) -> dict[str, Any]:
    q = q.strip()
    if len(q) < 3:
        return {"results": []}
    return {"results": store.search_conversations(q, min(limit, 100))}


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
