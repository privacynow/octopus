"""FastAPI HTTP entrypoint for the registry channel."""

from __future__ import annotations

from contextlib import asynccontextmanager
import hmac
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request, WebSocket
from starlette.websockets import WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel, Field

from app.channels.registry.auth import (
    AuthContext,
    clear_auth_attempt_limit,
    clear_ui_session,
    configure_session_middleware,
    current_ui_csrf_token,
    enforce_auth_attempt_limit,
    load_settings,
    mark_ui_session_authenticated,
    require_agent_token,
    require_authenticated,
    require_operator_session,
    require_ui_session,
    require_ui_token,
    require_ui_write_access,
    ui_password_matches,
    ui_session_is_valid,
    validate_settings,
)
from app.channels.registry.ws import WebSocketManager
from app.capability_service import CapabilityService
from octopus_sdk.registry.models import ConversationCreate, CoordinationActionEnvelope
from octopus_sdk.events import ConversationEvent, validate_event_metadata
from octopus_sdk.realtime import ConversationProgressUpdate
from app.channels.registry.ingress import (
    approve_catalog_skill,
    approve_provider_guidance,
    archive_catalog_skill,
    archive_provider_guidance,
    RegistryIngressError,
    activate_conversation_skill,
    catalog_skill_detail,
    catalog_skill_lifecycle_detail,
    clear_conversation_skills,
    conversation_skill_state,
    deactivate_conversation_skill,
    diff_catalog_skill,
    edit_catalog_skill_draft,
    edit_provider_guidance_draft,
    install_catalog_skill,
    list_catalog_skills,
    provider_guidance_detail,
    preview_provider_guidance,
    publish_catalog_skill,
    publish_provider_guidance,
    reject_catalog_skill,
    reject_provider_guidance,
    search_catalog_skills,
    submit_catalog_skill,
    submit_provider_guidance,
    uninstall_catalog_skill,
    update_catalog_skill,
)
from app.registry_service.backend import get_registry_store
from app.registry_service.store_base import (
    AbstractRegistryStore,
    CapabilityDisabledError,
    RegistryScopeError,
    validated_routed_task_request,
)

_REGISTRY_UI_SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "font-src 'self' data:; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "frame-ancestors 'none'"
    ),
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}

log = logging.getLogger(__name__)


class ConversationSkillMutationRequest(BaseModel):
    actor_key: str = Field(..., min_length=1, description="Actor performing the skill mutation")
    confirm: bool = Field(default=False, description="Confirm activation when the prompt budget warning has already been acknowledged")


class ProviderGuidancePreviewRequest(BaseModel):
    role: str = Field(default="", description="Role/persona text to include")
    active_skills: list[str] = Field(default_factory=list, description="Active runtime skill slugs")
    compact_mode: bool = Field(default=False, description="Whether compact-mode instructions should be appended")


class LifecycleActionRequest(BaseModel):
    actor_key: str = Field(..., min_length=1, description="Actor performing the lifecycle action")
    note: str = Field(default="", description="Optional lifecycle note")


class RuntimeSkillDraftUpdateRequest(LifecycleActionRequest):
    body: str = Field(..., min_length=1, description="Draft instruction body")
    description: str = Field(default="", description="Optional skill description override")
    changelog: str = Field(default="", description="Optional changelog entry")


class ProviderGuidanceDraftUpdateRequest(LifecycleActionRequest):
    body: str = Field(..., min_length=1, description="Draft provider-guidance body")
    scope_kind: str = Field(default="system", description="Guidance scope kind")
    scope_key: str = Field(default="", description="Guidance scope key")


from octopus_sdk.identity import normalize_conversation_id


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _float_value(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def get_store() -> AbstractRegistryStore:
    return get_registry_store()


def _secure_html_response(content: str, *, status_code: int = 200) -> HTMLResponse:
    return HTMLResponse(
        content,
        status_code=status_code,
        headers=dict(_REGISTRY_UI_SECURITY_HEADERS),
    )


@asynccontextmanager
async def _registry_lifespan(app: FastAPI):
    del app
    validate_settings()
    yield


app = FastAPI(title="Agent Registry", version="0.1.0", lifespan=_registry_lifespan)
configure_session_middleware(app)



# In-process WebSocket pub/sub manager (single-process only)
_ws_manager = WebSocketManager()


def get_ws_manager() -> WebSocketManager:
    return _ws_manager


def _event_invalidation_topics(kind: str) -> tuple[str, ...]:
    topics = {"conversations", "summary"}
    if kind == "provider.response":
        topics.add("usage")
    if kind == "task.status":
        topics.add("tasks")
    if kind in {"approval.requested", "approval.decided"}:
        topics.add("approvals")
    return tuple(sorted(topics))


async def _broadcast_invalidations(
    *,
    topics: tuple[str, ...] | list[str] | set[str],
    reason: str,
    conversation_id: str = "",
    agent_id: str = "",
    routed_task_id: str = "",
) -> None:
    for topic in sorted(set(topics)):
        await _ws_manager.broadcast_invalidation(
            topic,
            reason=reason,
            conversation_id=conversation_id,
            agent_id=agent_id,
            routed_task_id=routed_task_id,
        )


@app.websocket("/v1/ws")
async def websocket_feed(ws: WebSocket) -> None:
    """Real-time event feed. v1: operator session cookie auth only."""
    # Authenticate via session cookie — WebSocket connections carry cookies
    # but cannot send custom headers, so we check the session cookie only.
    session = ws.session if hasattr(ws, "session") else {}
    if not session.get("ui_authenticated"):
        await ws.close(code=4001, reason="Authentication required")
        return

    client = await _ws_manager.connect(ws)
    try:
        while True:
            data = await ws.receive_json()
            await _ws_manager.handle_subscription(client, data)
    except WebSocketDisconnect:
        pass  # Normal client disconnect
    except Exception:
        log.warning("WebSocket error for client", exc_info=True)
    finally:
        _ws_manager.disconnect(client)


def _agent_permission_http_error(exc: PermissionError) -> HTTPException:
    if isinstance(exc, RegistryScopeError):
        return HTTPException(
            status_code=403,
            detail={
                "error_code": "registry_scope_not_permitted",
                "message": str(exc),
            },
        )
    detail = str(exc).strip().lower()
    if detail == "unknown agent token":
        return HTTPException(status_code=401, detail="Invalid or expired agent token.")
    return HTTPException(status_code=403, detail="Not authorized for this agent resource.")


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {"ok": True}


@app.get("/v1/auth/csrf")
def get_csrf_token(request: Request) -> dict[str, Any]:
    """Return the current CSRF token for an authenticated operator session."""
    require_ui_session(request)
    return {"csrf_token": current_ui_csrf_token(request)}


@app.post("/v1/agents/enroll")
async def enroll(
    request: Request,
    payload: dict[str, Any],
    store: AbstractRegistryStore = Depends(get_store),
) -> dict[str, Any]:
    settings = load_settings()
    enforce_auth_attempt_limit(request, "registry-enroll")
    enroll_tok = payload.get("enrollment_token") or ""
    if not hmac.compare_digest(enroll_tok, settings.enroll_token):
        raise HTTPException(status_code=401, detail="Invalid enrollment token")
    clear_auth_attempt_limit(request, "registry-enroll")
    try:
        result = store.enroll(payload.get("agent_card"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await _broadcast_invalidations(
        topics=("agents", "summary"),
        reason="agent.enrolled",
        agent_id=str(result.get("agent_id", "")),
    )
    return result


@app.post("/v1/agents/register")
async def register(
    payload: dict[str, Any],
    agent_token: str = Depends(require_agent_token),
    store: AbstractRegistryStore = Depends(get_store),
) -> dict[str, Any]:
    try:
        result = store.register(agent_token, payload)
    except PermissionError as exc:
        raise _agent_permission_http_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    agent = result.get("agent", {})
    agent_id = str(agent.get("agent_id", ""))
    if agent_id:
        await _ws_manager.broadcast_heartbeat(agent_id, agent)
    await _broadcast_invalidations(
        topics=("agents", "summary"),
        reason="agent.registered",
        agent_id=agent_id,
    )
    return result


@app.post("/v1/agents/heartbeat")
async def heartbeat(
    payload: dict[str, Any],
    agent_token: str = Depends(require_agent_token),
    store: AbstractRegistryStore = Depends(get_store),
) -> dict[str, Any]:
    try:
        result = store.heartbeat(agent_token, payload)
    except PermissionError as exc:
        raise _agent_permission_http_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    # Broadcast heartbeat status to WebSocket subscribers
    agent_data = result.get("agent", {})
    agent_id = agent_data.get("agent_id", "")
    if agent_id:
        await _ws_manager.broadcast_heartbeat(agent_id, agent_data)
    if result.get("collections_changed"):
        await _broadcast_invalidations(
            topics=("agents", "summary"),
            reason="agent.heartbeat",
            agent_id=str(agent_id or ""),
        )
    return result


@app.post("/v1/agents/discovery/search")
def search_agents(
    payload: dict[str, Any],
    agent_token: str = Depends(require_agent_token),
    store: AbstractRegistryStore = Depends(get_store),
) -> dict[str, Any]:
    try:
        store.assert_agent_scope(agent_token, {"coordination", "full"})
    except PermissionError as exc:
        raise _agent_permission_http_error(exc) from exc
    try:
        agents = store.search_agents(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    store.heartbeat(agent_token, {"connectivity_state": "connected"})
    return {"agents": agents}


@app.post("/v1/agents/routed-tasks")
async def create_routed_task(
    payload: dict[str, Any],
    agent_token: str = Depends(require_agent_token),
    store: AbstractRegistryStore = Depends(get_store),
) -> dict[str, Any]:
    try:
        store.assert_agent_scope(agent_token, {"coordination", "full"})
        validated_request = validated_routed_task_request(payload)
        store.heartbeat(agent_token, {"connectivity_state": "connected"})
        result = store.create_routed_task(validated_request)
    except PermissionError as exc:
        raise _agent_permission_http_error(exc) from exc
    except CapabilityDisabledError as exc:
        raise HTTPException(status_code=409, detail="capability_disabled") from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown conversation: {exc.args[0]}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    parent_conversation_id = str(result.get("parent_conversation_id", ""))
    agent_id = str(result.get("target_agent_id", "") or result.get("origin_agent_id", ""))
    for ev in result.get("inserted_events", []):
        await _ws_manager.broadcast_event(parent_conversation_id, agent_id, ev)
    await _broadcast_invalidations(
        topics=("tasks", "conversations", "summary"),
        reason="routed_task.created",
        conversation_id=parent_conversation_id,
        agent_id=agent_id,
        routed_task_id=str(result.get("routed_task_id", "")),
    )
    return result


@app.get("/v1/agents/poll")
def poll(
    cursor: str = Query(default="0"),
    limit: int = Query(default=20, ge=1, le=100),
    wait_seconds: int = Query(default=1, ge=0, le=30),
    agent_token: str = Depends(require_agent_token),
    store: AbstractRegistryStore = Depends(get_store),
) -> dict[str, Any]:
    del wait_seconds
    try:
        return store.poll(agent_token, cursor=int(cursor or "0"), limit=limit)
    except PermissionError as exc:
        raise _agent_permission_http_error(exc) from exc


@app.post("/v1/agents/ack")
def ack(
    payload: dict[str, Any],
    agent_token: str = Depends(require_agent_token),
    store: AbstractRegistryStore = Depends(get_store),
) -> dict[str, Any]:
    try:
        return store.ack(
            agent_token,
            delivery_ids=payload.get("delivery_ids"),
            classification=payload.get("classification"),
        )
    except PermissionError as exc:
        raise _agent_permission_http_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/agents/routed-tasks/{routed_task_id}/status")
async def routed_task_status(
    routed_task_id: str,
    payload: dict[str, Any],
    agent_token: str = Depends(require_agent_token),
    store: AbstractRegistryStore = Depends(get_store),
) -> dict[str, Any]:
    try:
        result = store.update_routed_task_status(agent_token, routed_task_id, payload)
    except PermissionError as exc:
        raise _agent_permission_http_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    # Broadcast actual stored events via WebSocket (only when events were inserted)
    parent_conversation_id = result.get("parent_conversation_id", "")
    agent_id = result.get("target_agent_id", result.get("origin_agent_id", ""))
    if parent_conversation_id and result.get("events_written"):
        for ev in result.get("inserted_events", []):
            await _ws_manager.broadcast_event(parent_conversation_id, agent_id, ev)
    await _broadcast_invalidations(
        topics=("tasks", "conversations", "summary"),
        reason="routed_task.updated",
        conversation_id=parent_conversation_id,
        agent_id=agent_id,
        routed_task_id=routed_task_id,
    )
    return result


@app.post("/v1/agents/routed-tasks/{routed_task_id}/result")
async def routed_task_result(
    routed_task_id: str,
    payload: dict[str, Any],
    agent_token: str = Depends(require_agent_token),
    store: AbstractRegistryStore = Depends(get_store),
) -> dict[str, Any]:
    try:
        result = store.update_routed_task_result(agent_token, routed_task_id, payload)
    except PermissionError as exc:
        raise _agent_permission_http_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown routed task: {routed_task_id}") from exc
    parent_conversation_id = str(result.get("parent_conversation_id", ""))
    agent_id = str(result.get("target_agent_id", "") or result.get("origin_agent_id", ""))
    if parent_conversation_id and result.get("events_written"):
        for ev in result.get("inserted_events", []):
            await _ws_manager.broadcast_event(parent_conversation_id, agent_id, ev)
    await _broadcast_invalidations(
        topics=("tasks", "conversations", "summary"),
        reason="routed_task.completed",
        conversation_id=parent_conversation_id,
        agent_id=agent_id,
        routed_task_id=routed_task_id,
    )
    return result


@app.post("/v1/agents/deregister")
async def deregister(
    agent_token: str = Depends(require_agent_token),
    store: AbstractRegistryStore = Depends(get_store),
) -> dict[str, Any]:
    try:
        result = store.deregister(agent_token)
    except PermissionError as exc:
        raise _agent_permission_http_error(exc) from exc
    agent_id = str(result.get("agent_id", ""))
    if agent_id:
        await _ws_manager.broadcast_heartbeat(
            agent_id,
            {"agent_id": agent_id, "connectivity_state": result.get("connectivity_state", "offline")},
        )
    await _broadcast_invalidations(
        topics=("agents", "summary"),
        reason="agent.deregistered",
        agent_id=agent_id,
    )
    return result


# ---------------------------------------------------------------------------
# Resource-oriented routes (Phase 3 of registry UI rebuild)
# ---------------------------------------------------------------------------


def _require_own_resource(auth: AuthContext, owner_agent_id: str) -> None:
    """For agent-token callers, verify the resource belongs to them. Operators pass through."""
    if auth.is_agent and auth.agent_id != owner_agent_id:
        raise HTTPException(status_code=403, detail="Not authorized for this agent resource.")


def _scoped_agent_id(auth: AuthContext) -> str | None:
    """Return agent_id for scoping list queries, or None for operators (all data)."""
    return auth.agent_id if auth.is_agent else None


def _paginated_response(key: str, items: list[Any], cursor: int, limit: int) -> dict[str, Any]:
    """Wrap a list result with offset-based pagination metadata.

    Stores fetch ``limit + 1`` rows; the extra row signals *has_more*.
    """
    has_more = len(items) > limit
    if has_more:
        items = items[:limit]
    return {
        key: items,
        "next_cursor": cursor + limit if has_more else None,
        "has_more": has_more,
    }


@app.get("/v1/agents")
def resource_list_agents(
    cursor: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=100),
    q: str = Query(default=""),
    state: str = Query(default=""),
    auth: AuthContext = Depends(require_authenticated),
    store: AbstractRegistryStore = Depends(get_store),
) -> dict[str, Any]:
    agents = store.list_agents(
        for_agent_id=_scoped_agent_id(auth),
        cursor=cursor,
        limit=limit,
        q=q,
        connectivity_state=state,
    )
    return _paginated_response("agents", agents, cursor, limit)


@app.get("/v1/agents/{agent_id}/status")
def resource_agent_status(
    agent_id: str,
    auth: AuthContext = Depends(require_authenticated),
    store: AbstractRegistryStore = Depends(get_store),
) -> dict[str, Any]:
    _require_own_resource(auth, agent_id)
    result = store.get_agent_status(agent_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Unknown agent: {agent_id}")
    return result


@app.get("/v1/agents/{agent_id}/conversations")
def resource_agent_conversations(
    agent_id: str,
    cursor: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    auth: AuthContext = Depends(require_authenticated),
    store: AbstractRegistryStore = Depends(get_store),
) -> dict[str, Any]:
    _require_own_resource(auth, agent_id)
    conversations = store.list_agent_conversations(
        agent_id,
        for_agent_id=_scoped_agent_id(auth),
        cursor=cursor,
        limit=limit,
    )
    return _paginated_response("conversations", conversations, cursor, limit)


# IMPORTANT: register GET /v1/conversations BEFORE /v1/conversations/{id}
@app.get("/v1/conversations")
def resource_list_conversations(
    cursor: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=100),
    q: str = Query(default=""),
    status: str = Query(default=""),
    auth: AuthContext = Depends(require_authenticated),
    store: AbstractRegistryStore = Depends(get_store),
) -> dict[str, Any]:
    conversations = store.list_conversations(
        for_agent_id=_scoped_agent_id(auth),
        cursor=cursor,
        limit=limit,
        q=q,
        status=status,
    )
    return _paginated_response("conversations", conversations, cursor, limit)


@app.get("/v1/conversations/{conversation_id}")
def resource_get_conversation(
    conversation_id: str,
    auth: AuthContext = Depends(require_authenticated),
    store: AbstractRegistryStore = Depends(get_store),
) -> dict[str, Any]:
    conversation_id = normalize_conversation_id(conversation_id)
    try:
        conv = store.get_conversation(conversation_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown conversation: {conversation_id}") from exc
    _require_own_resource(auth, conv.get("target_agent_id", ""))
    return conv


@app.post("/v1/conversations", status_code=201)
async def resource_create_conversation(
    payload: ConversationCreate,
    auth: AuthContext = Depends(require_authenticated),
    store: AbstractRegistryStore = Depends(get_store),
) -> dict[str, Any]:
    # Agent tokens: enforce target_agent_id == self
    if auth.is_agent:
        if payload.target_agent_id != auth.agent_id:
            raise HTTPException(
                status_code=403,
                detail="Agent tokens can only create conversations targeting themselves.",
            )
    # Validate the agent exists
    if not store.agent_exists(payload.target_agent_id):
        raise HTTPException(status_code=404, detail=f"Unknown agent: {payload.target_agent_id}")
    result = store.create_conversation(
        target_agent_id=payload.target_agent_id,
        title=payload.title,
        origin_channel=payload.origin_channel,
        external_conversation_ref=payload.external_conversation_ref,
    )
    await _broadcast_invalidations(
        topics=("conversations", "summary"),
        reason="conversation.created",
        conversation_id=str(result.get("conversation_id", "")),
        agent_id=payload.target_agent_id,
    )
    return result


@app.post("/v1/conversations/{conversation_id}/progress")
async def resource_publish_progress(
    conversation_id: str,
    payload: ConversationProgressUpdate,
    agent_token: str = Depends(require_agent_token),
    store: AbstractRegistryStore = Depends(get_store),
) -> dict[str, Any]:
    conversation_id = normalize_conversation_id(conversation_id)
    agent_row = store.resolve_agent_for_token(agent_token)
    if agent_row is None:
        raise HTTPException(status_code=401, detail="Unknown agent token")
    agent_id = str(agent_row["agent_id"])
    try:
        conv = store.get_conversation(conversation_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown conversation: {conversation_id}") from exc
    if conv.get("target_agent_id") != agent_id:
        raise HTTPException(status_code=403, detail="Not authorized for this agent resource.")
    await _ws_manager.broadcast_progress(
        conversation_id,
        agent_id,
        {
            "conversation_id": conversation_id,
            "agent_id": agent_id,
            "content": payload.content,
            "created_at": payload.created_at,
        },
    )
    return {"ok": True}


@app.post("/v1/conversations/{conversation_id}/events")
async def resource_publish_events(
    conversation_id: str,
    payload: dict[str, Any],
    agent_token: str = Depends(require_agent_token),
    store: AbstractRegistryStore = Depends(get_store),
) -> dict[str, Any]:
    conversation_id = normalize_conversation_id(conversation_id)
    # Resolve agent from token
    agent_row = store.resolve_agent_for_token(agent_token)
    if agent_row is None:
        raise HTTPException(status_code=401, detail="Unknown agent token")
    agent_id = agent_row["agent_id"]
    # Check conversation ownership
    try:
        conv = store.get_conversation(conversation_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown conversation: {conversation_id}") from exc
    if conv.get("target_agent_id") != agent_id:
        raise HTTPException(status_code=403, detail="Not authorized for this agent resource.")
    # Validate events
    raw_events = payload.get("events")
    if not isinstance(raw_events, list) or not raw_events:
        raise HTTPException(status_code=422, detail="events must be a non-empty list")
    validated: list[dict[str, Any]] = []
    for i, raw in enumerate(raw_events):
        try:
            event = ConversationEvent.model_validate(raw)
            validated_metadata = validate_event_metadata(event)
            validated.append(
                event.model_copy(update={"metadata": validated_metadata}).model_dump()
            )
        except (ValueError, Exception) as exc:
            raise HTTPException(status_code=422, detail=f"Event {i}: {exc}") from exc
    result = store.publish_events(agent_token, conversation_id, validated)
    topics: set[str] = set()
    # Broadcast actual stored event rows (with seq, matching list_events shape)
    for ev in result.get("inserted_events", []):
        await _ws_manager.broadcast_event(conversation_id, agent_id, ev)
        topics.update(_event_invalidation_topics(str(ev.get("kind", ""))))
    if topics:
        await _broadcast_invalidations(
            topics=topics,
            reason="conversation.event_published",
            conversation_id=conversation_id,
            agent_id=agent_id,
        )
    return {"inserted": result["inserted"], "skipped": result["skipped"]}


@app.get("/v1/conversations/{conversation_id}/events")
def resource_list_events(
    conversation_id: str,
    kind: str = Query(default=""),
    before_seq: int = Query(default=0, ge=0),
    after_seq: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    auth: AuthContext = Depends(require_authenticated),
    store: AbstractRegistryStore = Depends(get_store),
) -> dict[str, Any]:
    conversation_id = normalize_conversation_id(conversation_id)
    if before_seq and after_seq:
        raise HTTPException(status_code=422, detail="before_seq and after_seq cannot both be set")
    try:
        conv = store.get_conversation(conversation_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown conversation: {conversation_id}") from exc
    _require_own_resource(auth, conv.get("target_agent_id", ""))
    return store.list_events(
        conversation_id,
        kind=kind,
        before_seq=before_seq,
        after_seq=after_seq,
        limit=limit,
    )


@app.get("/v1/conversations/{conversation_id}/messages")
def resource_list_messages(
    conversation_id: str,
    cursor: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    auth: AuthContext = Depends(require_authenticated),
    store: AbstractRegistryStore = Depends(get_store),
) -> dict[str, Any]:
    conversation_id = normalize_conversation_id(conversation_id)
    try:
        conv = store.get_conversation(conversation_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown conversation: {conversation_id}") from exc
    _require_own_resource(auth, conv.get("target_agent_id", ""))
    return store.list_messages(conversation_id, cursor=cursor, limit=limit)


@app.post("/v1/conversations/{conversation_id}/messages")
async def resource_add_message(
    conversation_id: str,
    payload: dict[str, Any],
    auth: AuthContext = Depends(require_operator_session),
    store: AbstractRegistryStore = Depends(get_store),
) -> dict[str, Any]:
    conversation_id = normalize_conversation_id(conversation_id)
    text = payload.get("text", "").strip()
    try:
        result = store.add_conversation_message(conversation_id, text)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Conversation not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    # Broadcast operator message via WebSocket (full stored event)
    conv = store.get_conversation(conversation_id)
    agent_id = conv.get("target_agent_id", "")
    event_data = result.get("event")
    if event_data:
        await _ws_manager.broadcast_event(conversation_id, agent_id, event_data)
    await _broadcast_invalidations(
        topics=("conversations", "summary"),
        reason="conversation.message_added",
        conversation_id=conversation_id,
        agent_id=agent_id,
    )
    return result


@app.post("/v1/conversations/{conversation_id}/actions")
async def resource_add_action(
    conversation_id: str,
    payload: CoordinationActionEnvelope,
    auth: AuthContext = Depends(require_operator_session),
    store: AbstractRegistryStore = Depends(get_store),
) -> dict[str, Any]:
    conversation_id = normalize_conversation_id(conversation_id)
    try:
        result = store.add_conversation_action(conversation_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Conversation not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    # Broadcast action via WebSocket (full stored event)
    conv = store.get_conversation(conversation_id)
    agent_id = conv.get("target_agent_id", "")
    event_data = result.get("event")
    if event_data:
        await _ws_manager.broadcast_event(conversation_id, agent_id, event_data)
        topics = set(_event_invalidation_topics(str(event_data.get("kind", ""))))
    else:
        topics = {"conversations", "summary"}
    await _broadcast_invalidations(
        topics=topics,
        reason="conversation.action_added",
        conversation_id=conversation_id,
        agent_id=agent_id,
    )
    return result


@app.get("/v1/conversations/{conversation_id}/export")
def resource_export_conversation(
    conversation_id: str,
    auth: AuthContext = Depends(require_authenticated),
    store: AbstractRegistryStore = Depends(get_store),
) -> Response:
    conversation_id = normalize_conversation_id(conversation_id)
    try:
        conv = store.get_conversation(conversation_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Conversation not found") from exc
    _require_own_resource(auth, conv.get("target_agent_id", ""))
    content = store.export_conversation(conversation_id)
    filename = f'conversation-{conversation_id}.md'
    return Response(
        content=content,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/v1/tasks")
def resource_list_tasks(
    cursor: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=100),
    status: str = Query(default=""),
    parent_conversation_id: str = Query(default=""),
    auth: AuthContext = Depends(require_authenticated),
    store: AbstractRegistryStore = Depends(get_store),
) -> dict[str, Any]:
    tasks = store.list_tasks(
        for_agent_id=_scoped_agent_id(auth),
        parent_conversation_id=parent_conversation_id,
        cursor=cursor,
        limit=limit,
        status=status,
    )
    return _paginated_response("tasks", tasks, cursor, limit)


@app.get("/v1/tasks/{routed_task_id}")
def resource_get_task(
    routed_task_id: str,
    auth: AuthContext = Depends(require_authenticated),
    store: AbstractRegistryStore = Depends(get_store),
) -> dict[str, Any]:
    try:
        task = store.get_task(routed_task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown routed task: {routed_task_id}") from exc
    if auth.agent_id:
        agent_id = auth.agent_id
        if agent_id not in {
            str(task.get("origin_agent_id", "")),
            str(task.get("target_agent_id", "")),
        }:
            raise HTTPException(status_code=403, detail="Not authorized for this task resource.")
    return task


@app.get("/v1/capabilities")
def resource_list_capabilities(
    auth: AuthContext = Depends(require_operator_session),
    store: AbstractRegistryStore = Depends(get_store),
) -> list[dict[str, Any]]:
    return [
        {
            "capability_name": item.capability_name,
            "declared_by_agents": list(item.declared_by_agents),
            "enabled": item.enabled,
        }
        for item in CapabilityService(store).list_capabilities()
    ]


@app.post("/v1/capabilities/{capability_name}/enable")
def resource_enable_capability(
    capability_name: str,
    auth: AuthContext = Depends(require_operator_session),
    store: AbstractRegistryStore = Depends(get_store),
) -> dict[str, Any]:
    item = CapabilityService(store).set_enabled(capability_name, enabled=True)
    return {"capability_name": item.capability_name, "enabled": True}


@app.post("/v1/capabilities/{capability_name}/disable")
def resource_disable_capability(
    capability_name: str,
    auth: AuthContext = Depends(require_operator_session),
    store: AbstractRegistryStore = Depends(get_store),
) -> dict[str, Any]:
    item = CapabilityService(store).set_enabled(capability_name, enabled=False)
    return {"capability_name": item.capability_name, "enabled": False}


@app.get("/v1/usage")
def resource_usage(
    since: str = Query(default=""),
    until: str = Query(default=""),
    auth: AuthContext = Depends(require_operator_session),
    store: AbstractRegistryStore = Depends(get_store),
) -> dict[str, Any]:
    if not since:
        since_iso = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0,
        ).isoformat()
    else:
        since_iso = since
    until_iso = until or ""
    rows = store.get_usage_summary(since_iso, until_iso=until_iso)
    daily_total = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "cost_usd": 0.0,
    }
    by_conversation: dict[str, dict[str, Any]] = {}
    for row in rows:
        metadata = row.get("metadata") or {}
        prompt_tokens = _int_value(metadata.get("prompt_tokens"))
        completion_tokens = _int_value(metadata.get("completion_tokens"))
        cost_usd = _float_value(metadata.get("cost_usd"))
        daily_total["prompt_tokens"] += prompt_tokens
        daily_total["completion_tokens"] += completion_tokens
        daily_total["cost_usd"] += cost_usd
        item = by_conversation.setdefault(
            row["conversation_id"],
            {
                "conversation_id": row["conversation_id"],
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "cost_usd": 0.0,
            },
        )
        item["prompt_tokens"] += prompt_tokens
        item["completion_tokens"] += completion_tokens
        item["cost_usd"] += cost_usd
    return {
        "daily_total": daily_total,
        "by_conversation": sorted(
            by_conversation.values(),
            key=lambda item: (
                -(item["prompt_tokens"] + item["completion_tokens"]),
                item["conversation_id"],
            ),
        ),
    }


@app.get("/v1/summary")
def resource_summary(
    auth: AuthContext = Depends(require_operator_session),
    store: AbstractRegistryStore = Depends(get_store),
) -> dict[str, Any]:
    now_iso = datetime.now(timezone.utc).isoformat()
    return store.get_summary(now_iso=now_iso)


@app.get("/v1/approvals")
def resource_list_approvals(
    cursor: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=100),
    auth: AuthContext = Depends(require_authenticated),
    store: AbstractRegistryStore = Depends(get_store),
) -> dict[str, Any]:
    approvals = store.list_approvals(
        for_agent_id=_scoped_agent_id(auth),
        cursor=cursor,
        limit=limit,
    )
    return _paginated_response("approvals", approvals, cursor, limit)


@app.get("/v1/catalog/skills")
def api_catalog_skills(
    q: str = "",
    _: None = Depends(require_ui_token),
) -> dict[str, Any]:
    return list_catalog_skills(q)


@app.get("/v1/catalog/skills/search")
def api_catalog_skill_search(
    q: str = "",
    _: None = Depends(require_ui_token),
) -> dict[str, Any]:
    return search_catalog_skills(q)


@app.get("/v1/catalog/skills/{skill_name}")
def api_catalog_skill_detail(
    skill_name: str,
    _: None = Depends(require_ui_token),
) -> dict[str, Any]:
    try:
        return catalog_skill_detail(skill_name)
    except RegistryIngressError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.get("/v1/catalog/skills/{skill_name}/lifecycle")
def api_catalog_skill_lifecycle_detail(
    skill_name: str,
    _: None = Depends(require_ui_token),
) -> dict[str, Any]:
    try:
        return catalog_skill_lifecycle_detail(skill_name)
    except RegistryIngressError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.put("/v1/catalog/skills/{skill_name}/draft")
def api_catalog_skill_edit_draft(
    skill_name: str,
    payload: RuntimeSkillDraftUpdateRequest,
    _: None = Depends(require_ui_write_access),
) -> dict[str, Any]:
    try:
        return edit_catalog_skill_draft(
            skill_name,
            actor_key=payload.actor_key,
            body=payload.body,
            description=payload.description or None,
            changelog=payload.changelog,
        )
    except RegistryIngressError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.post("/v1/catalog/skills/{skill_name}/submit")
def api_catalog_skill_submit(
    skill_name: str,
    payload: LifecycleActionRequest,
    _: None = Depends(require_ui_write_access),
) -> dict[str, Any]:
    try:
        return submit_catalog_skill(skill_name, actor_key=payload.actor_key, note=payload.note)
    except RegistryIngressError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.post("/v1/catalog/skills/{skill_name}/approve")
def api_catalog_skill_approve(
    skill_name: str,
    payload: LifecycleActionRequest,
    _: None = Depends(require_ui_write_access),
) -> dict[str, Any]:
    try:
        return approve_catalog_skill(skill_name, actor_key=payload.actor_key, note=payload.note)
    except RegistryIngressError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.post("/v1/catalog/skills/{skill_name}/reject")
def api_catalog_skill_reject(
    skill_name: str,
    payload: LifecycleActionRequest,
    _: None = Depends(require_ui_write_access),
) -> dict[str, Any]:
    try:
        return reject_catalog_skill(skill_name, actor_key=payload.actor_key, note=payload.note)
    except RegistryIngressError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.post("/v1/catalog/skills/{skill_name}/publish")
def api_catalog_skill_publish(
    skill_name: str,
    payload: LifecycleActionRequest,
    _: None = Depends(require_ui_write_access),
) -> dict[str, Any]:
    try:
        return publish_catalog_skill(skill_name, actor_key=payload.actor_key, note=payload.note)
    except RegistryIngressError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.post("/v1/catalog/skills/{skill_name}/archive")
def api_catalog_skill_archive(
    skill_name: str,
    payload: LifecycleActionRequest,
    _: None = Depends(require_ui_write_access),
) -> dict[str, Any]:
    try:
        return archive_catalog_skill(skill_name, actor_key=payload.actor_key, note=payload.note)
    except RegistryIngressError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.post("/v1/catalog/skills/{skill_name}/install")
def api_catalog_skill_install(
    skill_name: str,
    _: None = Depends(require_ui_write_access),
) -> dict[str, Any]:
    try:
        return install_catalog_skill(skill_name)
    except RegistryIngressError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.post("/v1/catalog/skills/{skill_name}/uninstall")
def api_catalog_skill_uninstall(
    skill_name: str,
    _: None = Depends(require_ui_write_access),
) -> dict[str, Any]:
    try:
        return uninstall_catalog_skill(skill_name)
    except RegistryIngressError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.post("/v1/catalog/skills/{skill_name}/update")
def api_catalog_skill_update(
    skill_name: str,
    _: None = Depends(require_ui_write_access),
) -> dict[str, Any]:
    try:
        return update_catalog_skill(skill_name)
    except RegistryIngressError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.get("/v1/catalog/skills/{skill_name}/diff")
def api_catalog_skill_diff(
    skill_name: str,
    _: None = Depends(require_ui_token),
) -> dict[str, Any]:
    try:
        return diff_catalog_skill(skill_name)
    except RegistryIngressError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.get("/v1/conversations/{conversation_id:path}/skills")
def api_conversation_skills(
    conversation_id: str,
    store: AbstractRegistryStore = Depends(get_store),
    _: None = Depends(require_ui_token),
) -> dict[str, Any]:
    conversation_id = normalize_conversation_id(conversation_id)
    try:
        return conversation_skill_state(store, conversation_id)
    except RegistryIngressError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.post("/v1/conversations/{conversation_id:path}/skills/{skill_name}/activate")
def api_conversation_activate_skill(
    conversation_id: str,
    skill_name: str,
    payload: ConversationSkillMutationRequest,
    store: AbstractRegistryStore = Depends(get_store),
    _: None = Depends(require_ui_write_access),
) -> dict[str, Any]:
    conversation_id = normalize_conversation_id(conversation_id)
    try:
        return activate_conversation_skill(
            store,
            conversation_id,
            actor_key=payload.actor_key,
            skill_name=skill_name,
            confirm=payload.confirm,
        )
    except RegistryIngressError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.post("/v1/conversations/{conversation_id:path}/skills/{skill_name}/deactivate")
def api_conversation_deactivate_skill(
    conversation_id: str,
    skill_name: str,
    payload: ConversationSkillMutationRequest,
    store: AbstractRegistryStore = Depends(get_store),
    _: None = Depends(require_ui_write_access),
) -> dict[str, Any]:
    conversation_id = normalize_conversation_id(conversation_id)
    try:
        return deactivate_conversation_skill(
            store,
            conversation_id,
            actor_key=payload.actor_key,
            skill_name=skill_name,
        )
    except RegistryIngressError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.post("/v1/conversations/{conversation_id:path}/skills/clear")
def api_conversation_clear_skills(
    conversation_id: str,
    payload: ConversationSkillMutationRequest,
    store: AbstractRegistryStore = Depends(get_store),
    _: None = Depends(require_ui_write_access),
) -> dict[str, Any]:
    conversation_id = normalize_conversation_id(conversation_id)
    try:
        return clear_conversation_skills(
            store,
            conversation_id,
            actor_key=payload.actor_key,
        )
    except RegistryIngressError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.post("/v1/provider-guidance/{provider_name}/preview")
def api_provider_guidance_preview(
    provider_name: str,
    payload: ProviderGuidancePreviewRequest,
    _: None = Depends(require_ui_write_access),
) -> dict[str, Any]:
    try:
        return preview_provider_guidance(
            provider_name,
            role=payload.role,
            active_skills=list(payload.active_skills),
            compact_mode=payload.compact_mode,
        )
    except RegistryIngressError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.get("/v1/provider-guidance/{provider_name}")
def api_provider_guidance_detail(
    provider_name: str,
    scope_kind: str = Query(default="system"),
    scope_key: str = Query(default=""),
    _: None = Depends(require_ui_token),
) -> dict[str, Any]:
    try:
        return provider_guidance_detail(
            provider_name,
            scope_kind=scope_kind,
            scope_key=scope_key,
        )
    except RegistryIngressError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.put("/v1/provider-guidance/{provider_name}/draft")
def api_provider_guidance_edit_draft(
    provider_name: str,
    payload: ProviderGuidanceDraftUpdateRequest,
    _: None = Depends(require_ui_write_access),
) -> dict[str, Any]:
    try:
        return edit_provider_guidance_draft(
            provider_name,
            actor_key=payload.actor_key,
            body=payload.body,
            scope_kind=payload.scope_kind,
            scope_key=payload.scope_key,
        )
    except RegistryIngressError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.post("/v1/provider-guidance/{provider_name}/submit")
def api_provider_guidance_submit(
    provider_name: str,
    payload: LifecycleActionRequest,
    _: None = Depends(require_ui_write_access),
) -> dict[str, Any]:
    try:
        return submit_provider_guidance(provider_name, actor_key=payload.actor_key, note=payload.note)
    except RegistryIngressError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.post("/v1/provider-guidance/{provider_name}/approve")
def api_provider_guidance_approve(
    provider_name: str,
    payload: LifecycleActionRequest,
    _: None = Depends(require_ui_write_access),
) -> dict[str, Any]:
    try:
        return approve_provider_guidance(provider_name, actor_key=payload.actor_key, note=payload.note)
    except RegistryIngressError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.post("/v1/provider-guidance/{provider_name}/reject")
def api_provider_guidance_reject(
    provider_name: str,
    payload: LifecycleActionRequest,
    _: None = Depends(require_ui_write_access),
) -> dict[str, Any]:
    try:
        return reject_provider_guidance(provider_name, actor_key=payload.actor_key, note=payload.note)
    except RegistryIngressError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.post("/v1/provider-guidance/{provider_name}/publish")
def api_provider_guidance_publish(
    provider_name: str,
    payload: LifecycleActionRequest,
    _: None = Depends(require_ui_write_access),
) -> dict[str, Any]:
    try:
        return publish_provider_guidance(provider_name, actor_key=payload.actor_key, note=payload.note)
    except RegistryIngressError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.post("/v1/provider-guidance/{provider_name}/archive")
def api_provider_guidance_archive(
    provider_name: str,
    payload: LifecycleActionRequest,
    _: None = Depends(require_ui_write_access),
) -> dict[str, Any]:
    try:
        return archive_provider_guidance(provider_name, actor_key=payload.actor_key, note=payload.note)
    except RegistryIngressError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


def _render_login_html(title: str, error: str = "") -> str:
    error_block = f'<p class="error">{error}</p>' if error else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — Login</title>
<style>
  body {{ font-family: system-ui, sans-serif; background: #f5f5f5; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; }}
  .box {{ background: #fff; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,.12); padding: 2rem; min-width: 320px; }}
  h1 {{ font-size: 1.25rem; margin: 0 0 1.5rem; }}
  label {{ display: block; margin-bottom: .4rem; font-size: .875rem; font-weight: 500; }}
  input[type=password] {{ width: 100%; box-sizing: border-box; padding: .5rem .75rem; border: 1px solid #ccc; border-radius: 4px; font-size: 1rem; margin-bottom: 1rem; }}
  button {{ width: 100%; padding: .6rem; background: #1a73e8; color: #fff; border: none; border-radius: 4px; font-size: 1rem; cursor: pointer; }}
  button:hover {{ background: #1558b0; }}
  .error {{ color: #c62828; font-size: .875rem; margin-bottom: .75rem; }}
</style>
</head>
<body>
<div class="box">
  <h1>{title}</h1>
  {error_block}
  <form method="post" action="/ui/login">
    <label for="password">Password</label>
    <input type="password" id="password" name="password" autofocus required>
    <button type="submit">Sign in</button>
  </form>
</div>
</body>
</html>"""


import os as _os
from pathlib import Path as _Path
from fastapi.staticfiles import StaticFiles as _StaticFiles

_UI_DIR = _Path(__file__).resolve().parent.parent.parent.parent / "ui"


@app.get("/ui/login", response_class=HTMLResponse)
def ui_login_page(request: Request):
    settings = load_settings()
    if ui_session_is_valid(request):
        return RedirectResponse("/ui", status_code=303)
    return _secure_html_response(_render_login_html(settings.display_name or "Agent Registry"))


@app.post("/ui/login")
async def ui_login(request: Request, password: str = Form(default="")):
    settings = load_settings()
    if ui_session_is_valid(request):
        return RedirectResponse("/ui", status_code=303)
    enforce_auth_attempt_limit(request, "registry-ui-login")
    if not ui_password_matches(password, settings=settings):
        return _secure_html_response(
            _render_login_html(settings.display_name or "Agent Registry", error="Incorrect password.")
        )
    clear_auth_attempt_limit(request, "registry-ui-login")
    mark_ui_session_authenticated(request)
    return RedirectResponse("/ui", status_code=303)


@app.get("/ui/logout")
def ui_logout(request: Request):
    clear_ui_session(request)
    return RedirectResponse("/ui/login", status_code=303)


@app.get("/ui", response_class=HTMLResponse)
def ui_shell(request: Request) -> HTMLResponse:
    require_ui_session(request)
    return HTMLResponse(
        (_UI_DIR / "index.html").read_text(),
        headers=dict(_REGISTRY_UI_SECURITY_HEADERS),
    )


# ---------------------------------------------------------------------------
# New SPA static file serving (Phase 7)
# ---------------------------------------------------------------------------

if _UI_DIR.is_dir():
    app.mount("/ui/css", _StaticFiles(directory=str(_UI_DIR / "css")), name="ui-css")
    app.mount("/ui/js", _StaticFiles(directory=str(_UI_DIR / "js")), name="ui-js")
    if (_UI_DIR / "vendor").is_dir():
        app.mount("/ui/vendor", _StaticFiles(directory=str(_UI_DIR / "vendor")), name="ui-vendor")

    @app.get("/ui/{path:path}", response_class=HTMLResponse)
    def ui_spa_subpath(request: Request, path: str) -> HTMLResponse:
        """Serve SPA index for client-side routes so /ui/conversations etc. work on refresh/bookmark."""
        if path == "login":
            raise HTTPException(status_code=404)
        require_ui_session(request)
        return HTMLResponse(
            (_UI_DIR / "index.html").read_text(),
            headers=dict(_REGISTRY_UI_SECURITY_HEADERS),
        )

    @app.get("/ui/spa/{path:path}", response_class=HTMLResponse)
    def ui_spa_catchall(request: Request, path: str = ""):
        """Legacy: Serve the SPA index.html for all /ui/spa/* routes (client-side routing)."""
        require_ui_session(request)
        return HTMLResponse(
            (_UI_DIR / "index.html").read_text(),
            headers=dict(_REGISTRY_UI_SECURITY_HEADERS),
        )
