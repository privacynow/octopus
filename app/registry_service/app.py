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
        --bg: #f7f3ea;
        --fg: #1f1b16;
        --card: #fffaf1;
        --accent: #0f766e;
        --muted: #756c5f;
        --border: #d7c9b2;
      }}
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        font-family: "IBM Plex Sans", "Avenir Next", sans-serif;
        color: var(--fg);
        background:
          radial-gradient(circle at top right, rgba(15,118,110,0.14), transparent 30%),
          linear-gradient(180deg, #faf7f0 0%, var(--bg) 100%);
      }}
      header {{
        padding: 24px 32px;
        border-bottom: 1px solid var(--border);
        background: rgba(255,250,241,0.85);
        backdrop-filter: blur(10px);
      }}
      h1 {{ margin: 0 0 6px; font-size: 28px; }}
      p {{ margin: 0; color: var(--muted); }}
      main {{
        display: grid;
        grid-template-columns: 320px 1fr 1fr;
        gap: 16px;
        padding: 24px 32px 32px;
      }}
      section {{
        min-height: 260px;
        background: var(--card);
        border: 1px solid var(--border);
        border-radius: 20px;
        padding: 20px;
        box-shadow: 0 10px 24px rgba(40, 24, 8, 0.06);
      }}
      h2 {{
        margin-top: 0;
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
        border: 1px solid var(--border);
        border-radius: 14px;
        background: rgba(255,255,255,0.65);
      }}
      .meta {{
        margin-top: 6px;
        font-size: 12px;
        color: var(--muted);
      }}
      .badge {{
        display: inline-block;
        margin-right: 6px;
        padding: 2px 8px;
        border-radius: 999px;
        background: rgba(15,118,110,0.12);
        color: var(--accent);
        font-size: 12px;
      }}
      pre {{
        overflow: auto;
        white-space: pre-wrap;
        font-family: "IBM Plex Mono", monospace;
        font-size: 12px;
      }}
      @media (max-width: 980px) {{
        main {{
          grid-template-columns: 1fr;
        }}
      }}
    </style>
  </head>
  <body>
    <header>
      <h1>Agent Registry</h1>
      <p>Live directory, routed work board, and shared conversation view for private bots.</p>
    </header>
    <main>
      <section>
        <h2>Bots</h2>
        <div id="bots" class="list"></div>
      </section>
      <section>
        <h2>Conversations</h2>
        <div id="conversations" class="list"></div>
      </section>
      <section>
        <h2>Routed Tasks</h2>
        <div id="tasks" class="list"></div>
      </section>
    </main>
    <script>
      const token = {token!r};
      async function loadBootstrap() {{
        const response = await fetch('/v1/ui/bootstrap', {{
          headers: {{ Authorization: `Bearer ${{token}}` }},
        }});
        if (!response.ok) {{
          document.body.innerHTML = `<main><section><h2>Registry unavailable</h2><pre>${{await response.text()}}</pre></section></main>`;
          return;
        }}
        const data = await response.json();
        renderList('bots', data.bots, item => `
          <div class="item">
            <strong>${{item.display_name}}</strong>
            <div class="meta"><span class="badge">${{item.connectivity_state}}</span>${{item.role || 'unassigned role'}}</div>
            <div class="meta">${{(item.skills || []).join(', ') || 'no skills declared'}}</div>
          </div>
        `);
        renderList('conversations', data.conversations, item => `
          <div class="item">
            <strong>${{item.title || item.conversation_id}}</strong>
            <div class="meta">${{item.target_display_name || item.target_agent_id}}</div>
            <div class="meta"><span class="badge">${{item.status}}</span></div>
          </div>
        `);
        renderList('tasks', data.tasks, item => `
          <div class="item">
            <strong>${{item.title}}</strong>
            <div class="meta">${{item.origin_display_name || item.origin_agent_id}} -> ${{item.target_display_name || item.target_agent_id}}</div>
            <div class="meta"><span class="badge">${{item.status}}</span>${{item.summary || ''}}</div>
          </div>
        `);
      }}
      function renderList(id, items, template) {{
        document.getElementById(id).innerHTML = items.length
          ? items.map(template).join('')
          : '<div class="item"><div class="meta">Nothing yet.</div></div>';
      }}
      loadBootstrap();
      setInterval(loadBootstrap, 5000);
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
