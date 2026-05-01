"""FastAPI HTTP entrypoint for the registry channel."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import hmac
import logging
import mimetypes
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, WebSocket
from starlette.websockets import WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response

from .auth import (
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
from .artifact_paths import (
    artifact_download_name,
    resolve_protocol_artifact_path,
    resolve_task_artifact_path,
    resolve_task_artifact_rehearsal_text,
)
from .artifact_responses import rendered_artifact_text_preview_response, workspace_artifact_content_response
from .ws import WebSocketManager
from .rehearsal import RehearsalSessionManager
from .routing_skill_service import RoutingSkillService
from octopus_sdk.exact_aliases import direct_selector_aliases
from octopus_sdk.protocols import ProtocolAccessContextRecord, ProtocolRunCreateRecord
from octopus_sdk.registry.models import (
    AgentCapacityUpdate,
    AgentDiscoveryQuery,
    AgentTokenRotationResult,
    AgentTrustTierUpdate,
    ConversationCreate,
    CoordinationActionEnvelope,
    HealthSummary,
    SelectorPreviewCandidate,
    SelectorPreviewRequest,
    SelectorPreviewResult,
    TargetSelector,
    TaskRecord,
    RoutedTaskResult,
    RoutedTaskUpdate,
    format_target_selector,
    parse_target_selector,
    utcnow_iso,
)
from octopus_sdk.registry.management import ManagementResult
from octopus_sdk.events import ConversationEvent, validate_event_metadata
from octopus_sdk.realtime import ConversationProgressUpdate
from octopus_sdk.time_utils import utc_now
from .ingress import (
    approve_catalog_skill,
    approve_provider_guidance,
    archive_catalog_skill,
    archive_provider_guidance,
    RegistryIngressError,
    activate_conversation_skill,
    catalog_skill_detail,
    catalog_skill_lifecycle_detail,
    clear_conversation_skills,
    conversation_settings_state,
    conversation_skill_state,
    deactivate_conversation_skill,
    diff_catalog_skill,
    edit_catalog_skill_draft,
    export_catalog_skill_package,
    edit_provider_guidance_draft,
    import_catalog_skill_package,
    install_catalog_skill,
    list_catalog_skills,
    provider_guidance_detail,
    preview_provider_guidance,
    publish_catalog_skill,
    publish_provider_guidance,
    reject_catalog_skill,
    reject_provider_guidance,
    reset_conversation,
    reset_execution_fault,
    search_catalog_skills,
    set_conversation_setting,
    submit_conversation_skill_credential,
    submit_catalog_skill,
    submit_provider_guidance,
    uninstall_catalog_skill,
    update_catalog_skill,
)
from .authority import StoreBackedRegistryAuthority
from .backend import get_registry_authority, get_registry_store
from .protocol_http import build_protocol_router
from .protocol_runtime import broadcast_protocol_run_event, internal_protocol_access
from .store_base import (
    AbstractRegistryStore,
    RoutingSkillDisabledError,
    RegistryScopeError,
    validated_agent_card_payload,
    validated_routed_task_request,
)
from .http_support import (
    AgentExecutionResetRequest,
    ConversationResetRequest,
    ConversationSettingUpdateRequest,
    ConversationSkillCredentialRequest,
    ConversationSkillMutationRequest,
    LifecycleActionRequest,
    ProviderGuidanceDraftUpdateRequest,
    ProviderGuidancePreviewRequest,
    RuntimeSkillDraftUpdateRequest,
    RuntimeSkillPackageImportRequest,
    json_payload as _json_payload,
    operator_actor_key as _operator_actor_key,
    paginated_response as _paginated_response,
    require_own_resource as _require_own_resource,
    scoped_agent_id as _scoped_agent_id,
    secure_html_response as _secure_html_response,
)
from .store_shared.usage import aggregate_usage_rows
from .task_artifact_payloads import (
    protocol_run_id_from_task_record as _protocol_run_id_from_task_record,
    tasks_with_protocol_artifacts as _tasks_with_protocol_artifacts,
)
from .ui_http import register_ui_routes

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
from octopus_sdk.identity import normalize_conversation_id


def get_store() -> AbstractRegistryStore:
    return get_registry_store()


def get_authority() -> StoreBackedRegistryAuthority:
    return get_registry_authority()


@asynccontextmanager
async def _registry_lifespan(app: FastAPI):
    del app
    validate_settings()
    stop_event = asyncio.Event()
    global _rehearsal_manager
    _rehearsal_manager = RehearsalSessionManager(store=get_store())
    try:
        await _rehearsal_manager.start()
    except Exception:
        log.warning("Rehearsal session manager failed to start", exc_info=True)

    async def _protocol_maintenance_loop() -> None:
        while not stop_event.is_set():
            try:
                result = await asyncio.to_thread(get_store().run_protocol_maintenance)
                swept_count = int(getattr(result, "swept_count", 0) or 0)
                if swept_count:
                    topics = {"protocols", "summary"}
                    for run_id in getattr(result, "affected_run_ids", ()) or ():
                        normalized = str(run_id or "").strip()
                        if normalized:
                            topics.add(f"protocol-run:{normalized}")
                    await _broadcast_invalidations(
                        topics=topics,
                        reason="protocol.run.timeout",
                    )
                    for run_id in getattr(result, "affected_run_ids", ()) or ():
                        normalized = str(run_id or "").strip()
                        if normalized:
                            await broadcast_protocol_run_event(
                                get_store(),
                                _ws_manager,
                                run_id=normalized,
                                event_kind="protocol_run.terminal",
                                reason="protocol.run.timeout",
                            )
            except Exception:
                log.warning("Protocol maintenance sweep failed", exc_info=True)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=15.0)
            except asyncio.TimeoutError:
                continue

    maintenance_task = asyncio.create_task(_protocol_maintenance_loop(), name="registry-protocol-maintenance")
    try:
        yield
    finally:
        stop_event.set()
        maintenance_task.cancel()
        try:
            await maintenance_task
        except asyncio.CancelledError:
            pass
        try:
            await _rehearsal_manager.stop()
        except Exception:
            log.warning("Rehearsal session manager failed to stop cleanly", exc_info=True)


app = FastAPI(title="Agent Registry", version="0.1.0", lifespan=_registry_lifespan)
configure_session_middleware(app)
_ws_manager = WebSocketManager()
_rehearsal_manager: RehearsalSessionManager | None = None


def get_ws_manager() -> WebSocketManager:
    return _ws_manager


def get_rehearsal_manager() -> RehearsalSessionManager:
    if _rehearsal_manager is None:
        raise HTTPException(status_code=503, detail="Rehearsal service not initialized.")
    return _rehearsal_manager


def _protocol_access(auth: AuthContext) -> ProtocolAccessContextRecord:
    actor_ref = f"agent:{auth.agent_id}" if auth.is_agent and auth.agent_id else "operator-session"
    return ProtocolAccessContextRecord(
        actor_ref=actor_ref,
        org_id=str(auth.org_id or "local"),
        roles=list(auth.roles or ()),
    )


def _raise_ingress_http_error(exc: RegistryIngressError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


def _event_invalidation_topics(kind: str) -> tuple[str, ...]:
    topics = {"conversations", "summary"}
    if kind == "provider.response":
        topics.add("usage")
    if kind == "task.status":
        topics.add("tasks")
    if kind in {"approval.requested", "approval.decided"}:
        topics.add("approvals")
    return tuple(sorted(topics))


async def _broadcast_task_record_events(result: TaskRecord) -> None:
    agent_id = str(result.target_agent_id or result.origin_agent_id or "")
    for event in result.inserted_events or []:
        conversation_id = str(event.conversation_id or result.parent_conversation_id or "")
        if conversation_id:
            await _ws_manager.broadcast_event(conversation_id, agent_id, event.model_dump(mode="json"))
    for event in result.recipient_inserted_events or []:
        conversation_id = str(event.conversation_id or result.recipient_conversation_id or "")
        if conversation_id:
            await _ws_manager.broadcast_event(conversation_id, agent_id, event.model_dump(mode="json"))


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


app.include_router(
    build_protocol_router(
        get_store=get_store,
        require_authenticated=require_authenticated,
        require_operator_session=require_operator_session,
        protocol_access=_protocol_access,
        broadcast_invalidations=_broadcast_invalidations,
        broadcast_topic_event=lambda *, run_id, event_kind, reason: broadcast_protocol_run_event(
            get_store(),
            _ws_manager,
            run_id=run_id,
            event_kind=event_kind,
            reason=reason,
        ),
        get_rehearsal_manager=get_rehearsal_manager,
    )
)
register_ui_routes(app, security_headers=_REGISTRY_UI_SECURITY_HEADERS)


@app.websocket("/v1/ws")
async def websocket_feed(ws: WebSocket) -> None:
    """Real-time event feed. v1: operator session cookie auth only."""
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
        return HTTPException(status_code=403, detail={"error_code": "registry_scope_not_permitted", "message": str(exc)})
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
    authority: StoreBackedRegistryAuthority = Depends(get_authority),
) -> dict[str, Any]:
    settings = load_settings()
    enforce_auth_attempt_limit(request, "registry-enroll")
    enroll_tok = payload.get("enrollment_token") or ""
    if not hmac.compare_digest(enroll_tok, settings.enroll_token):
        raise HTTPException(status_code=401, detail="Invalid enrollment token")
    clear_auth_attempt_limit(request, "registry-enroll")
    try:
        result = authority.enroll_agent(
            validated_agent_card_payload(
                payload.get("agent_card"),
                require_registry_scope=True,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await _broadcast_invalidations(
        topics=("agents", "summary"),
        reason="agent.enrolled",
        agent_id=str(result.agent_id or ""),
    )
    return _json_payload(result)


@app.post("/v1/agents/register")
async def register(
    payload: dict[str, Any],
    agent_token: str = Depends(require_agent_token),
    authority: StoreBackedRegistryAuthority = Depends(get_authority),
) -> dict[str, Any]:
    try:
        result = authority.register_agent(agent_token, payload)
    except PermissionError as exc:
        raise _agent_permission_http_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    agent = result.agent
    agent_id = str(agent.agent_id or "")
    if agent_id:
        await _ws_manager.broadcast_heartbeat(agent_id, _json_payload(agent))
    await _broadcast_invalidations(
        topics=("agents", "summary"),
        reason="agent.registered",
        agent_id=agent_id,
    )
    return _json_payload(result)


@app.post("/v1/agents/heartbeat")
async def heartbeat(
    payload: dict[str, Any],
    agent_token: str = Depends(require_agent_token),
    authority: StoreBackedRegistryAuthority = Depends(get_authority),
) -> dict[str, Any]:
    try:
        result = authority.heartbeat_agent(agent_token, payload)
    except PermissionError as exc:
        raise _agent_permission_http_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    # Broadcast heartbeat status to WebSocket subscribers
    agent = result.agent
    agent_id = str(agent.agent_id or "") if agent is not None else ""
    if agent is not None and agent_id:
        await _ws_manager.broadcast_heartbeat(agent_id, _json_payload(agent))
    if result.collections_changed:
        await _broadcast_invalidations(
            topics=("agents", "summary"),
            reason="agent.heartbeat",
            agent_id=str(agent_id or ""),
        )
    return _json_payload(result)


@app.post("/v1/agents/discovery/search")
def search_agents(
    payload: dict[str, Any],
    agent_token: str = Depends(require_agent_token),
    authority: StoreBackedRegistryAuthority = Depends(get_authority),
) -> dict[str, Any]:
    try:
        agents = authority.search_agents_for_agent(agent_token, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except PermissionError as exc:
        raise _agent_permission_http_error(exc) from exc
    return {"agents": [agent.model_dump(mode="json") for agent in agents]}


@app.post("/v1/agents/routed-tasks")
async def create_routed_task(
    payload: dict[str, Any],
    agent_token: str = Depends(require_agent_token),
    authority: StoreBackedRegistryAuthority = Depends(get_authority),
) -> dict[str, Any]:
    try:
        result = authority.submit_routed_task_for_agent(agent_token, payload)
    except PermissionError as exc:
        raise _agent_permission_http_error(exc) from exc
    except RoutingSkillDisabledError as exc:
        raise HTTPException(status_code=409, detail="routing_skill_disabled") from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown conversation: {exc.args[0]}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    parent_conversation_id = str(result.parent_conversation_id or "")
    agent_id = str(result.target_agent_id or result.origin_agent_id or "")
    await _broadcast_task_record_events(result)
    await _broadcast_invalidations(
        topics=("tasks", "conversations", "summary"),
        reason="routed_task.created",
        conversation_id=parent_conversation_id,
        agent_id=agent_id,
        routed_task_id=str(result.routed_task_id or ""),
    )
    return result.model_dump(mode="json")


@app.get("/v1/agents/poll")
def poll(
    cursor: str = Query(default="0"),
    limit: int = Query(default=20, ge=1, le=100),
    wait_seconds: int = Query(default=1, ge=0, le=30),
    agent_token: str = Depends(require_agent_token),
    authority: StoreBackedRegistryAuthority = Depends(get_authority),
) -> dict[str, Any]:
    del wait_seconds
    try:
        return _json_payload(authority.poll_for_agent(agent_token, cursor=int(cursor or "0"), limit=limit))
    except PermissionError as exc:
        raise _agent_permission_http_error(exc) from exc
@app.post("/v1/agents/ack")
def ack(
    payload: dict[str, Any],
    agent_token: str = Depends(require_agent_token),
    authority: StoreBackedRegistryAuthority = Depends(get_authority),
) -> dict[str, Any]:
    try:
        return _json_payload(
            authority.ack_for_agent(
                agent_token,
                delivery_ids=payload.get("delivery_ids"),
                classification=payload.get("classification"),
            )
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
    authority: StoreBackedRegistryAuthority = Depends(get_authority),
) -> dict[str, Any]:
    try:
        result = authority.update_routed_task_for_agent(
            agent_token,
            {
                **payload,
                "routed_task_id": routed_task_id,
            }
        )
    except PermissionError as exc:
        raise _agent_permission_http_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    # Broadcast actual stored events via WebSocket (only when events were inserted)
    parent_conversation_id = result.parent_conversation_id
    agent_id = result.target_agent_id or result.origin_agent_id
    if (parent_conversation_id or result.recipient_conversation_id) and (result.inserted_events or result.recipient_inserted_events):
        await _broadcast_task_record_events(result)
    await _broadcast_invalidations(
        topics=("tasks", "conversations", "summary"),
        reason="routed_task.updated",
        conversation_id=parent_conversation_id,
        agent_id=agent_id,
        routed_task_id=routed_task_id,
    )
    return result.model_dump(mode="json")


@app.post("/v1/agents/routed-tasks/{routed_task_id}/result")
async def routed_task_result(
    routed_task_id: str,
    payload: dict[str, Any],
    agent_token: str = Depends(require_agent_token),
    authority: StoreBackedRegistryAuthority = Depends(get_authority),
    store: AbstractRegistryStore = Depends(get_store),
) -> dict[str, Any]:
    try:
        result = authority.report_routed_result_for_agent(
            agent_token,
            {
                **payload,
                "routed_task_id": routed_task_id,
            }
        )
    except PermissionError as exc:
        raise _agent_permission_http_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown routed task: {routed_task_id}") from exc
    parent_conversation_id = str(result.parent_conversation_id or "")
    agent_id = str(result.target_agent_id or result.origin_agent_id or "")
    protocol_run_id = _protocol_run_id_from_task_record(result)
    if (parent_conversation_id or result.recipient_conversation_id) and (result.inserted_events or result.recipient_inserted_events):
        await _broadcast_task_record_events(result)
    topics = {"tasks", "conversations", "summary"}
    reason = "routed_task.completed"
    if protocol_run_id:
        topics.add("protocols")
        topics.add(f"protocol-run:{protocol_run_id}")
        reason = "protocol.run.updated"
    await _broadcast_invalidations(
        topics=topics,
        reason=reason,
        conversation_id=parent_conversation_id,
        agent_id=agent_id,
        routed_task_id=routed_task_id,
    )
    if protocol_run_id:
        event_kind = "protocol_run.updated"
        try:
            detail = store.get_protocol_run(protocol_run_id, access=internal_protocol_access())
        except Exception:
            detail = None
        if detail is not None:
            if str(detail.run.status or "") in {"completed", "failed", "cancelled"}:
                event_kind = "protocol_run.terminal"
            elif str(detail.run.current_stage_key or ""):
                event_kind = "protocol_run.stage_changed"
        await broadcast_protocol_run_event(
            store,
            _ws_manager,
            run_id=protocol_run_id,
            event_kind=event_kind,
            reason=reason,
            routed_task_id=routed_task_id,
        )
    return result.model_dump(mode="json")


@app.post("/v1/agents/management-requests/{request_id}/result")
def management_request_result(
    request_id: str,
    payload: ManagementResult,
    agent_token: str = Depends(require_agent_token),
    authority: StoreBackedRegistryAuthority = Depends(get_authority),
) -> dict[str, Any]:
    try:
        result = authority.report_management_result_for_agent(agent_token, request_id, payload)
    except PermissionError as exc:
        raise _agent_permission_http_error(exc) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown management request: {request_id}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return result.model_dump(mode="json", by_alias=True)


@app.post("/v1/agents/deregister")
async def deregister(
    agent_token: str = Depends(require_agent_token),
    authority: StoreBackedRegistryAuthority = Depends(get_authority),
) -> dict[str, Any]:
    try:
        result = authority.disconnect_agent_token(agent_token)
    except PermissionError as exc:
        raise _agent_permission_http_error(exc) from exc
    agent_id = str(result.agent_id or "")
    if agent_id:
        await _ws_manager.broadcast_heartbeat(
            agent_id,
            _json_payload({"agent_id": agent_id, "connectivity_state": str(result.connectivity_state or "disconnected")}),
        )
    await _broadcast_invalidations(
        topics=("agents", "summary"),
        reason="agent.deregistered",
        agent_id=agent_id,
    )
    return _json_payload(result)


# ---------------------------------------------------------------------------
# Resource-oriented routes (Phase 3 of registry UI rebuild)
# ---------------------------------------------------------------------------


def _conversation_agent_scope(
    store: AbstractRegistryStore,
    *,
    agent_id: str,
    conversation_id: str,
) -> str:
    normalized = normalize_conversation_id(conversation_id)
    try:
        conversation = store.get_conversation(normalized)
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown conversation: {normalized}",
        ) from exc
    owner_agent_id = str(conversation.get("target_agent_id", "") or "")
    if owner_agent_id != agent_id:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Conversation {normalized} is not managed by agent {agent_id}."
            ),
        )
    return normalized


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
    agent_rows: list[dict[str, Any]] = []
    for agent in agents:
        row = agent.model_dump(mode="json") if hasattr(agent, "model_dump") else dict(agent)
        selector_aliases = direct_selector_aliases(
            slug=str(row.get("slug", "") or ""),
            display_name=str(row.get("display_name", "") or ""),
        )
        role = str(row.get("role", "") or "").strip()
        row["selector"] = selector_aliases[0] if selector_aliases else ""
        row["selector_aliases"] = list(selector_aliases)
        row["role_selector"] = format_target_selector("role", role) if role else ""
        agent_rows.append(row)
    return _json_payload(_paginated_response("agents", agent_rows, cursor, limit))


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
    return _json_payload(result)


@app.post("/v1/agents/{agent_id}/execution/reset")
async def api_agent_execution_reset(
    agent_id: str,
    payload: AgentExecutionResetRequest,
    store: AbstractRegistryStore = Depends(get_store),
    _: None = Depends(require_ui_write_access),
) -> dict[str, Any]:
    try:
        result = await reset_execution_fault(
            store,
            agent_id,
            actor_key=_operator_actor_key(payload.actor_key),
        )
        await _broadcast_invalidations(
            topics=("agents", f"agent:{agent_id}", "summary"),
            reason="agent.execution.reset",
            agent_id=agent_id,
        )
        return result
    except RegistryIngressError as exc: _raise_ingress_http_error(exc)


@app.patch("/v1/agents/{agent_id}/trust-tier")
async def api_agent_trust_tier_update(
    agent_id: str,
    payload: AgentTrustTierUpdate,
    store: AbstractRegistryStore = Depends(get_store),
    _: None = Depends(require_ui_write_access),
) -> dict[str, Any]:
    try:
        record = store.update_agent_trust_tier(agent_id, payload.trust_tier)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await _broadcast_invalidations(
        topics=("agents", f"agent:{agent_id}"),
        reason="agent.trust_tier.updated",
        agent_id=agent_id,
    )
    return _json_payload(record)


@app.patch("/v1/agents/{agent_id}/capacity")
async def api_agent_capacity_update(
    agent_id: str,
    payload: AgentCapacityUpdate,
    store: AbstractRegistryStore = Depends(get_store),
    _: None = Depends(require_ui_write_access),
) -> dict[str, Any]:
    try:
        record = store.update_agent_capacity(
            agent_id,
            current_capacity=payload.current_capacity,
            max_capacity=payload.max_capacity,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await _broadcast_invalidations(
        topics=("agents", f"agent:{agent_id}"),
        reason="agent.capacity.updated",
        agent_id=agent_id,
    )
    return _json_payload(record)


@app.post("/v1/agents/{agent_id}/rotate-token")
async def api_agent_rotate_token(
    agent_id: str,
    store: AbstractRegistryStore = Depends(get_store),
    _: None = Depends(require_ui_write_access),
) -> dict[str, Any]:
    try:
        record, plaintext_token = store.rotate_agent_token(agent_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await _broadcast_invalidations(
        topics=("agents", f"agent:{agent_id}"),
        reason="agent.token.rotated",
        agent_id=agent_id,
    )
    return _json_payload(
        AgentTokenRotationResult(
            agent_id=record.agent_id,
            agent_token=plaintext_token,
            slug=record.slug,
            registry_epoch=utcnow_iso(),
        )
    )


@app.delete("/v1/agents/{agent_id}")
async def api_agent_soft_delete(
    agent_id: str,
    store: AbstractRegistryStore = Depends(get_store),
    _: None = Depends(require_ui_write_access),
) -> dict[str, Any]:
    try:
        record = store.soft_delete_agent(agent_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await _broadcast_invalidations(
        topics=("agents", f"agent:{agent_id}", "summary"),
        reason="agent.soft_deleted",
        agent_id=agent_id,
    )
    return _json_payload(record)


@app.post("/v1/selector/preview")
def api_selector_preview(
    payload: SelectorPreviewRequest,
    store: AbstractRegistryStore = Depends(get_store),
    _: AuthContext = Depends(require_authenticated),
) -> dict[str, Any]:
    parsed = parse_target_selector(payload.selector)
    if parsed is None:
        parsed = TargetSelector(kind="agent", value=payload.selector)
    try:
        candidates = store.preview_selector_resolution(
            parsed,
            exclude_agent_ids=tuple(payload.exclude_agent_ids or ()),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    enriched: list[SelectorPreviewCandidate] = []
    for row in candidates:
        raw_skills = row.get("skills_json")
        if isinstance(raw_skills, str):
            try:
                import json as _json
                decoded_skills = _json.loads(raw_skills)
            except Exception:
                decoded_skills = []
        elif isinstance(raw_skills, list):
            decoded_skills = raw_skills
        else:
            decoded_skills = []
        enriched.append(
            SelectorPreviewCandidate(
                agent_id=str(row.get("agent_id") or ""),
                display_name=str(row.get("display_name") or ""),
                slug=str(row.get("slug") or ""),
                role=str(row.get("role") or ""),
                connectivity_state=str(row.get("effective_state") or row.get("connectivity_state") or ""),
                trust_tier=str(row.get("trust_tier") or "community"),
                current_capacity=int(row.get("current_capacity") or 0),
                max_capacity=int(row.get("max_capacity") or 1),
                routing_skills=[str(s) for s in decoded_skills if isinstance(s, str)],
                reason="",
            )
        )
    return _json_payload(
        SelectorPreviewResult(
            selector=payload.selector,
            authority_ref=payload.authority_ref,
            candidates=enriched,
            total_considered=len(enriched),
        )
    )


@app.get("/v1/agents/{agent_id}/conversations")
def resource_agent_conversations(
    agent_id: str,
    cursor: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    conversation_type: str = Query(default=""),
    include_generated: bool = Query(default=True),
    auth: AuthContext = Depends(require_authenticated),
    store: AbstractRegistryStore = Depends(get_store),
) -> dict[str, Any]:
    _require_own_resource(auth, agent_id)
    conversations = store.list_agent_conversations(
        agent_id,
        for_agent_id=_scoped_agent_id(auth),
        cursor=cursor,
        limit=limit,
        conversation_type=conversation_type,
        include_generated=include_generated,
    )
    return _json_payload(_paginated_response("conversations", conversations, cursor, limit))


# IMPORTANT: register GET /v1/conversations BEFORE /v1/conversations/{id}
@app.get("/v1/conversations")
def resource_list_conversations(
    cursor: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=100),
    q: str = Query(default=""),
    status: str = Query(default=""),
    conversation_type: str = Query(default=""),
    include_generated: bool = Query(default=True),
    auth: AuthContext = Depends(require_authenticated),
    store: AbstractRegistryStore = Depends(get_store),
) -> dict[str, Any]:
    conversations = store.list_conversations(
        for_agent_id=_scoped_agent_id(auth),
        cursor=cursor,
        limit=limit,
        q=q,
        status=status,
        conversation_type=conversation_type,
        include_generated=include_generated,
    )
    return _json_payload(_paginated_response("conversations", conversations, cursor, limit))


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
    return _json_payload(conv)


@app.post("/v1/conversations", status_code=201)
async def resource_create_conversation(
    payload: ConversationCreate,
    auth: AuthContext = Depends(require_authenticated),
    store: AbstractRegistryStore = Depends(get_store),
    authority: StoreBackedRegistryAuthority = Depends(get_authority),
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
    result = authority.create_conversation(payload)
    await _broadcast_invalidations(
        topics=("conversations", "summary"),
        reason="conversation.created",
        conversation_id=str(result.conversation_id or ""),
        agent_id=payload.target_agent_id,
    )
    return result.model_dump(mode="json")


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
    authority: StoreBackedRegistryAuthority = Depends(get_authority),
) -> dict[str, Any]:
    conversation_id = normalize_conversation_id(conversation_id)
    # Resolve agent token
    agent_row = store.resolve_agent_for_token(agent_token)
    if agent_row is None:
        raise HTTPException(status_code=401, detail="Unknown agent token")
    agent_id = agent_row["agent_id"]
    authority.remember_agent_token(str(agent_id or ""), agent_token)
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
    result = authority.publish_events(
        conversation_id,
        [ConversationEvent.model_validate(item) for item in validated],
    )
    topics: set[str] = set()
    # Broadcast actual stored event rows (with seq, matching list_events shape)
    for ev in result:
        encoded = ev.model_dump(mode="json")
        await _ws_manager.broadcast_event(conversation_id, agent_id, encoded)
        topics.update(_event_invalidation_topics(str(ev.kind or "")))
    if topics:
        await _broadcast_invalidations(
            topics=topics,
            reason="conversation.event_published",
            conversation_id=conversation_id,
            agent_id=agent_id,
        )
    return {"inserted": len(result), "skipped": max(0, len(raw_events) - len(result))}


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
    return _json_payload(
        store.list_events(
            conversation_id,
            kind=kind,
            before_seq=before_seq,
            after_seq=after_seq,
            limit=limit,
        )
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
    return _json_payload(store.list_messages(conversation_id, cursor=cursor, limit=limit))


@app.post("/v1/conversations/{conversation_id}/messages")
async def resource_add_message(
    conversation_id: str,
    payload: dict[str, Any],
    auth: AuthContext = Depends(require_operator_session),
    store: AbstractRegistryStore = Depends(get_store),
    authority: StoreBackedRegistryAuthority = Depends(get_authority),
) -> dict[str, Any]:
    conversation_id = normalize_conversation_id(conversation_id)
    text = payload.get("text", "").strip()
    try:
        result = authority.add_message(conversation_id, text, actor="operator")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Conversation not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    # Broadcast operator message via WebSocket (full stored event)
    conv = store.get_conversation(conversation_id)
    agent_id = conv.get("target_agent_id", "")
    event_data = result.event.model_dump(mode="json") if result.event is not None else None
    if event_data:
        await _ws_manager.broadcast_event(conversation_id, agent_id, event_data)
    await _broadcast_invalidations(
        topics=("conversations", "summary"),
        reason="conversation.message_added",
        conversation_id=conversation_id,
        agent_id=agent_id,
    )
    return result.model_dump(mode="json")


@app.post("/v1/conversations/{conversation_id}/actions")
async def resource_add_action(
    conversation_id: str,
    payload: CoordinationActionEnvelope,
    auth: AuthContext = Depends(require_authenticated),
    store: AbstractRegistryStore = Depends(get_store),
    authority: StoreBackedRegistryAuthority = Depends(get_authority),
) -> dict[str, Any]:
    conversation_id = normalize_conversation_id(conversation_id)
    try:
        conv = store.get_conversation(conversation_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Conversation not found") from exc
    if auth.is_agent:
        try:
            store.assert_agent_scope(str(auth.agent_token or ""), {"coordination", "full"})
        except PermissionError as exc:
            raise _agent_permission_http_error(exc) from exc
        _require_own_resource(auth, str(conv.get("target_agent_id", "") or ""))
        if auth.agent_id and auth.agent_token:
            authority.remember_agent_token(auth.agent_id, auth.agent_token)
    try:
        result = authority.submit_action(conversation_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    # Broadcast action via WebSocket (full stored event)
    agent_id = conv.get("target_agent_id", "")
    inserted_events = result.inserted_events or []
    if inserted_events:
        topics: set[str] = set()
        for event_data in inserted_events:
            typed_event = event_data.model_dump(mode="json") if hasattr(event_data, "model_dump") else event_data
            await _ws_manager.broadcast_event(conversation_id, agent_id, typed_event)
            topics.update(_event_invalidation_topics(str(typed_event.get("kind", ""))))
    else:
        event_data = result.event
        if event_data:
            typed_event = event_data.model_dump(mode="json") if hasattr(event_data, "model_dump") else event_data
            await _ws_manager.broadcast_event(conversation_id, agent_id, typed_event)
            topics = set(_event_invalidation_topics(str(typed_event.get("kind", ""))))
        else:
            topics = {"conversations", "summary"}
    await _broadcast_invalidations(
        topics=topics,
        reason="conversation.action_added",
        conversation_id=conversation_id,
        agent_id=agent_id,
    )
    return result.model_dump(mode="json")


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
    protocol_run_id: str = Query(default=""),
    completed_since_iso: str = Query(default=""),
    include_generated: bool = Query(default=True),
    auth: AuthContext = Depends(require_authenticated),
    store: AbstractRegistryStore = Depends(get_store),
) -> dict[str, Any]:
    tasks = store.list_tasks(
        for_agent_id=_scoped_agent_id(auth),
        parent_conversation_id=parent_conversation_id,
        protocol_run_id=protocol_run_id,
        cursor=cursor,
        limit=limit,
        status=status,
        completed_since_iso=completed_since_iso,
        include_generated=include_generated,
    )
    tasks = _tasks_with_protocol_artifacts(tasks, access=_protocol_access(auth), store=store)
    return _json_payload(_paginated_response("tasks", tasks, cursor, limit))


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
    task = _tasks_with_protocol_artifacts([task], access=_protocol_access(auth), store=store)[0]
    return _json_payload(task)


@app.get("/v1/tasks/{routed_task_id}/artifacts/{artifact_key}/content")
def resource_get_task_artifact_content(
    request: Request,
    routed_task_id: str,
    artifact_key: str,
    download: bool = Query(default=False),
    browse: bool = Query(default=False),
    preview: bool = Query(default=False),
    member_path: str = Query(default="", alias="path"),
    auth: AuthContext = Depends(require_authenticated),
    store: AbstractRegistryStore = Depends(get_store),
) -> Response:
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
    resolved_path = resolve_task_artifact_path(task, artifact_key)
    detail = None
    if resolved_path is None:
        protocol_run_id = _protocol_run_id_from_task_record(task)
        if protocol_run_id:
            try:
                detail = store.get_protocol_run(protocol_run_id, access=_protocol_access(auth))
            except KeyError:
                detail = None
            if detail is not None:
                resolved_path = resolve_task_artifact_path(task, artifact_key, run_detail=detail)
                if resolved_path is None:
                    stage_execution_id = str(task.protocol_stage_execution_id or "").strip()
                    for artifact in detail.artifacts or []:
                        if str(artifact.artifact_key or "").strip() != str(artifact_key or "").strip():
                            continue
                        produced_stage_id = str(artifact.produced_by_stage_execution_id or "").strip()
                        if stage_execution_id and produced_stage_id and produced_stage_id != stage_execution_id:
                            continue
                        resolved_path = resolve_protocol_artifact_path(detail, artifact)
                        if resolved_path is not None:
                            break
    preferred_path = ""
    result_payload = task.result.as_dict() if task.result is not None else {}
    artifacts = result_payload.get("artifacts", ()) if isinstance(result_payload, dict) else ()
    if isinstance(artifacts, list):
        for item in artifacts:
            if not isinstance(item, dict):
                continue
            if str(item.get("artifact_key", "") or "").strip() != str(artifact_key or "").strip():
                continue
            preferred_path = str(item.get("path", "") or "").strip()
            break
    preferred_name = artifact_download_name(
        artifact_key=str(artifact_key or ""),
        preferred_path=preferred_path,
    )
    media_type = mimetypes.guess_type(preferred_name)[0] or "application/octet-stream"
    if resolved_path is None:
        content_text = resolve_task_artifact_rehearsal_text(task, artifact_key, run_detail=detail)
        if content_text:
            if preview and not download:
                return rendered_artifact_text_preview_response(
                    content_text,
                    artifact_key=str(artifact_key or ""),
                    preferred_name=preferred_name,
                )
            disposition = "attachment" if download else "inline"
            return Response(
                content=content_text.encode("utf-8"),
                media_type=media_type,
                headers={"Content-Disposition": f'{disposition}; filename="{preferred_name}"'},
            )
        raise HTTPException(status_code=409, detail="Artifact path is not available on this host.")
    return workspace_artifact_content_response(
        resolved_path=resolved_path,
        artifact_key=str(artifact_key or ""),
        preferred_path=preferred_path or str(resolved_path.name or ""),
        preferred_name=preferred_name,
        download=download,
        browse=browse,
        preview=preview,
        member_path=member_path,
        request=request,
    )


@app.get("/v1/routing/skills")
def resource_list_routing_skills(
    auth: AuthContext = Depends(require_operator_session),
    store: AbstractRegistryStore = Depends(get_store),
) -> list[dict[str, Any]]:
    return [
        {
            "skill_name": item.skill_name,
            "selector": format_target_selector("skill", item.skill_name),
            "advertised_by_agents": list(item.advertised_by_agents),
            "enabled": item.enabled,
        }
        for item in RoutingSkillService(store).list_routing_skills()
    ]


@app.post("/v1/routing/skills/{skill_name}/enable")
def resource_enable_routing_skill(
    skill_name: str,
    auth: AuthContext = Depends(require_operator_session),
    store: AbstractRegistryStore = Depends(get_store),
) -> dict[str, Any]:
    item = RoutingSkillService(store).set_enabled(skill_name, enabled=True)
    return {"skill_name": item.skill_name, "enabled": True}


@app.post("/v1/routing/skills/{skill_name}/disable")
def resource_disable_routing_skill(
    skill_name: str,
    auth: AuthContext = Depends(require_operator_session),
    store: AbstractRegistryStore = Depends(get_store),
) -> dict[str, Any]:
    item = RoutingSkillService(store).set_enabled(skill_name, enabled=False)
    return {"skill_name": item.skill_name, "enabled": False}


@app.get("/v1/usage")
def resource_usage(
    since: str = Query(default=""),
    until: str = Query(default=""),
    auth: AuthContext = Depends(require_operator_session),
    store: AbstractRegistryStore = Depends(get_store),
) -> dict[str, Any]:
    if not since:
        since_iso = utc_now().replace(
            hour=0, minute=0, second=0, microsecond=0,
        ).isoformat()
    else:
        since_iso = since
    until_iso = until or ""
    rows = store.get_usage_summary(since_iso, until_iso=until_iso)
    return aggregate_usage_rows(rows)


@app.get("/v1/summary")
def resource_summary(
    auth: AuthContext = Depends(require_operator_session),
    store: AbstractRegistryStore = Depends(get_store),
) -> dict[str, Any]:
    now_iso = utcnow_iso()
    return _json_payload(store.get_summary(now_iso=now_iso))


@app.post("/v1/admin/workspace-data/cleanup")
async def resource_cleanup_workspace_data(
    request: Request,
    store: AbstractRegistryStore = Depends(get_store),
    _: None = Depends(require_ui_write_access),
) -> dict[str, Any]:
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    password = str((payload or {}).get("password") or "")
    confirm = str((payload or {}).get("confirm") or "").strip().upper()
    if confirm != "CLEAN":
        raise HTTPException(status_code=400, detail="Type CLEAN to confirm workspace-data cleanup.")
    if not ui_password_matches(password, settings=load_settings()):
        raise HTTPException(status_code=403, detail="Registry UI password did not match.")
    result = store.cleanup_workspace_data()
    await _broadcast_invalidations(
        topics=("summary", "conversations", "tasks", "approvals", "protocols"),
        reason="admin.workspace_data.cleanup",
    )
    return _json_payload(result)


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
    return _json_payload(_paginated_response("approvals", approvals, cursor, limit))


@app.get("/v1/agents/{agent_id}/catalog/skills")
async def api_catalog_skills(
    agent_id: str,
    q: str = "",
    store: AbstractRegistryStore = Depends(get_store),
    _: None = Depends(require_ui_token),
) -> dict[str, Any]:
    try:
        return await list_catalog_skills(store, agent_id, q)
    except RegistryIngressError as exc: _raise_ingress_http_error(exc)


@app.get("/v1/agents/{agent_id}/catalog/skills/search")
async def api_catalog_skill_search(
    agent_id: str,
    q: str = "",
    store: AbstractRegistryStore = Depends(get_store),
    _: None = Depends(require_ui_token),
) -> dict[str, Any]:
    try:
        return await search_catalog_skills(store, agent_id, q)
    except RegistryIngressError as exc: _raise_ingress_http_error(exc)


@app.get("/v1/agents/{agent_id}/catalog/skills/{skill_name}")
async def api_catalog_skill_detail(
    agent_id: str,
    skill_name: str,
    store: AbstractRegistryStore = Depends(get_store),
    _: None = Depends(require_ui_token),
) -> dict[str, Any]:
    try:
        return await catalog_skill_detail(store, agent_id, skill_name)
    except RegistryIngressError as exc: _raise_ingress_http_error(exc)


@app.get("/v1/agents/{agent_id}/catalog/skills/{skill_name}/lifecycle")
async def api_catalog_skill_lifecycle_detail(
    agent_id: str,
    skill_name: str,
    store: AbstractRegistryStore = Depends(get_store),
    _: None = Depends(require_ui_token),
) -> dict[str, Any]:
    try:
        return await catalog_skill_lifecycle_detail(store, agent_id, skill_name)
    except RegistryIngressError as exc: _raise_ingress_http_error(exc)


@app.put("/v1/agents/{agent_id}/catalog/skills/{skill_name}/draft")
async def api_catalog_skill_edit_draft(
    agent_id: str,
    skill_name: str,
    payload: RuntimeSkillDraftUpdateRequest,
    store: AbstractRegistryStore = Depends(get_store),
    _: None = Depends(require_ui_write_access),
) -> dict[str, Any]:
    try:
        return await edit_catalog_skill_draft(
            store,
            agent_id,
            skill_name,
            actor_key=_operator_actor_key(payload.actor_key),
            body=payload.body,
            display_name=payload.display_name,
            description=payload.description or None,
            skill_kind=payload.skill_kind,
            requirements=payload.requirements,
            provider_config=payload.provider_config,
            files=payload.files,
            changelog=payload.changelog,
        )
    except RegistryIngressError as exc: _raise_ingress_http_error(exc)


@app.get("/v1/agents/{agent_id}/catalog/skills/{skill_name}/export")
async def api_catalog_skill_export_package(
    agent_id: str,
    skill_name: str,
    revision: str = Query(default="draft"),
    store: AbstractRegistryStore = Depends(get_store),
    _: None = Depends(require_ui_token),
) -> dict[str, Any]:
    try:
        return await export_catalog_skill_package(
            store,
            agent_id,
            skill_name,
            revision_scope=revision,
        )
    except RegistryIngressError as exc: _raise_ingress_http_error(exc)


@app.post("/v1/agents/{agent_id}/catalog/skills/import")
async def api_catalog_skill_import_package(
    agent_id: str,
    payload: RuntimeSkillPackageImportRequest,
    store: AbstractRegistryStore = Depends(get_store),
    _: None = Depends(require_ui_write_access),
) -> dict[str, Any]:
    try:
        return await import_catalog_skill_package(
            store,
            agent_id,
            actor_key=_operator_actor_key(payload.actor_key),
            target_skill_name=payload.target_skill_name,
            file_name=payload.file_name,
            package_base64=payload.package_base64,
        )
    except RegistryIngressError as exc: _raise_ingress_http_error(exc)


@app.post("/v1/agents/{agent_id}/catalog/skills/{skill_name}/submit")
async def api_catalog_skill_submit(
    agent_id: str,
    skill_name: str,
    payload: LifecycleActionRequest,
    store: AbstractRegistryStore = Depends(get_store),
    _: None = Depends(require_ui_write_access),
) -> dict[str, Any]:
    try:
        return await submit_catalog_skill(
            store,
            agent_id,
            skill_name,
            actor_key=_operator_actor_key(payload.actor_key),
            note=payload.note,
        )
    except RegistryIngressError as exc: _raise_ingress_http_error(exc)


@app.post("/v1/agents/{agent_id}/catalog/skills/{skill_name}/approve")
async def api_catalog_skill_approve(
    agent_id: str,
    skill_name: str,
    payload: LifecycleActionRequest,
    store: AbstractRegistryStore = Depends(get_store),
    _: None = Depends(require_ui_write_access),
) -> dict[str, Any]:
    try:
        return await approve_catalog_skill(
            store,
            agent_id,
            skill_name,
            actor_key=_operator_actor_key(payload.actor_key),
            note=payload.note,
        )
    except RegistryIngressError as exc: _raise_ingress_http_error(exc)


@app.post("/v1/agents/{agent_id}/catalog/skills/{skill_name}/reject")
async def api_catalog_skill_reject(
    agent_id: str,
    skill_name: str,
    payload: LifecycleActionRequest,
    store: AbstractRegistryStore = Depends(get_store),
    _: None = Depends(require_ui_write_access),
) -> dict[str, Any]:
    try:
        return await reject_catalog_skill(
            store,
            agent_id,
            skill_name,
            actor_key=_operator_actor_key(payload.actor_key),
            note=payload.note,
        )
    except RegistryIngressError as exc: _raise_ingress_http_error(exc)


@app.post("/v1/agents/{agent_id}/catalog/skills/{skill_name}/publish")
async def api_catalog_skill_publish(
    agent_id: str,
    skill_name: str,
    payload: LifecycleActionRequest,
    store: AbstractRegistryStore = Depends(get_store),
    _: None = Depends(require_ui_write_access),
) -> dict[str, Any]:
    try:
        return await publish_catalog_skill(
            store,
            agent_id,
            skill_name,
            actor_key=_operator_actor_key(payload.actor_key),
            note=payload.note,
        )
    except RegistryIngressError as exc: _raise_ingress_http_error(exc)


@app.post("/v1/agents/{agent_id}/catalog/skills/{skill_name}/archive")
async def api_catalog_skill_archive(
    agent_id: str,
    skill_name: str,
    payload: LifecycleActionRequest,
    store: AbstractRegistryStore = Depends(get_store),
    _: None = Depends(require_ui_write_access),
) -> dict[str, Any]:
    try:
        return await archive_catalog_skill(
            store,
            agent_id,
            skill_name,
            actor_key=_operator_actor_key(payload.actor_key),
            note=payload.note,
        )
    except RegistryIngressError as exc: _raise_ingress_http_error(exc)


@app.post("/v1/agents/{agent_id}/catalog/skills/{skill_name}/install")
async def api_catalog_skill_install(
    agent_id: str,
    skill_name: str,
    store: AbstractRegistryStore = Depends(get_store),
    _: None = Depends(require_ui_write_access),
) -> dict[str, Any]:
    try:
        return await install_catalog_skill(store, agent_id, skill_name)
    except RegistryIngressError as exc: _raise_ingress_http_error(exc)


@app.post("/v1/agents/{agent_id}/catalog/skills/{skill_name}/uninstall")
async def api_catalog_skill_uninstall(
    agent_id: str,
    skill_name: str,
    store: AbstractRegistryStore = Depends(get_store),
    _: None = Depends(require_ui_write_access),
) -> dict[str, Any]:
    try:
        return await uninstall_catalog_skill(store, agent_id, skill_name)
    except RegistryIngressError as exc: _raise_ingress_http_error(exc)


@app.post("/v1/agents/{agent_id}/catalog/skills/{skill_name}/update")
async def api_catalog_skill_update(
    agent_id: str,
    skill_name: str,
    store: AbstractRegistryStore = Depends(get_store),
    _: None = Depends(require_ui_write_access),
) -> dict[str, Any]:
    try:
        return await update_catalog_skill(store, agent_id, skill_name)
    except RegistryIngressError as exc: _raise_ingress_http_error(exc)


@app.get("/v1/agents/{agent_id}/catalog/skills/{skill_name}/diff")
async def api_catalog_skill_diff(
    agent_id: str,
    skill_name: str,
    store: AbstractRegistryStore = Depends(get_store),
    _: None = Depends(require_ui_token),
) -> dict[str, Any]:
    try:
        return await diff_catalog_skill(store, agent_id, skill_name)
    except RegistryIngressError as exc: _raise_ingress_http_error(exc)


@app.get("/v1/agents/{agent_id}/conversations/{conversation_id:path}/skills")
async def api_conversation_skills(
    agent_id: str,
    conversation_id: str,
    store: AbstractRegistryStore = Depends(get_store),
    _: None = Depends(require_ui_token),
) -> dict[str, Any]:
    scoped_conversation_id = _conversation_agent_scope(
        store,
        agent_id=agent_id,
        conversation_id=conversation_id,
    )
    try:
        return await conversation_skill_state(store, agent_id, scoped_conversation_id)
    except RegistryIngressError as exc: _raise_ingress_http_error(exc)


@app.post("/v1/agents/{agent_id}/conversations/{conversation_id:path}/skills/{skill_name}/activate")
async def api_conversation_activate_skill(
    agent_id: str,
    conversation_id: str,
    skill_name: str,
    payload: ConversationSkillMutationRequest,
    store: AbstractRegistryStore = Depends(get_store),
    _: None = Depends(require_ui_write_access),
) -> dict[str, Any]:
    scoped_conversation_id = _conversation_agent_scope(
        store,
        agent_id=agent_id,
        conversation_id=conversation_id,
    )
    try:
        result = await activate_conversation_skill(
            store,
            agent_id,
            scoped_conversation_id,
            actor_key=_operator_actor_key(payload.actor_key),
            skill_name=skill_name,
            confirm=payload.confirm,
        )
        await _broadcast_invalidations(
            topics=(f"conversation:{scoped_conversation_id}", "conversations"),
            reason="conversation.skill.activated",
            conversation_id=scoped_conversation_id,
            agent_id=agent_id,
        )
        return result
    except RegistryIngressError as exc: _raise_ingress_http_error(exc)


@app.post("/v1/agents/{agent_id}/conversations/{conversation_id:path}/skills/{skill_name}/deactivate")
async def api_conversation_deactivate_skill(
    agent_id: str,
    conversation_id: str,
    skill_name: str,
    payload: ConversationSkillMutationRequest,
    store: AbstractRegistryStore = Depends(get_store),
    _: None = Depends(require_ui_write_access),
) -> dict[str, Any]:
    scoped_conversation_id = _conversation_agent_scope(
        store,
        agent_id=agent_id,
        conversation_id=conversation_id,
    )
    try:
        result = await deactivate_conversation_skill(
            store,
            agent_id,
            scoped_conversation_id,
            actor_key=_operator_actor_key(payload.actor_key),
            skill_name=skill_name,
        )
        await _broadcast_invalidations(
            topics=(f"conversation:{scoped_conversation_id}", "conversations"),
            reason="conversation.skill.deactivated",
            conversation_id=scoped_conversation_id,
            agent_id=agent_id,
        )
        return result
    except RegistryIngressError as exc: _raise_ingress_http_error(exc)


@app.post("/v1/agents/{agent_id}/conversations/{conversation_id:path}/skills/clear")
async def api_conversation_clear_skills(
    agent_id: str,
    conversation_id: str,
    payload: ConversationSkillMutationRequest,
    store: AbstractRegistryStore = Depends(get_store),
    _: None = Depends(require_ui_write_access),
) -> dict[str, Any]:
    scoped_conversation_id = _conversation_agent_scope(
        store,
        agent_id=agent_id,
        conversation_id=conversation_id,
    )
    try:
        result = await clear_conversation_skills(
            store,
            agent_id,
            scoped_conversation_id,
            actor_key=_operator_actor_key(payload.actor_key),
        )
        await _broadcast_invalidations(
            topics=(f"conversation:{scoped_conversation_id}", "conversations"),
            reason="conversation.skills.cleared",
            conversation_id=scoped_conversation_id,
            agent_id=agent_id,
        )
        return result
    except RegistryIngressError as exc: _raise_ingress_http_error(exc)


@app.post("/v1/agents/{agent_id}/conversations/{conversation_id:path}/skills/{skill_name}/credential")
async def api_conversation_submit_skill_credential(
    agent_id: str,
    conversation_id: str,
    skill_name: str,
    payload: ConversationSkillCredentialRequest,
    store: AbstractRegistryStore = Depends(get_store),
    _: None = Depends(require_ui_write_access),
) -> dict[str, Any]:
    scoped_conversation_id = _conversation_agent_scope(
        store,
        agent_id=agent_id,
        conversation_id=conversation_id,
    )
    try:
        result = await submit_conversation_skill_credential(
            store,
            agent_id,
            scoped_conversation_id,
            actor_key=_operator_actor_key(payload.actor_key),
            skill_name=skill_name,
            value=payload.value,
        )
        await _broadcast_invalidations(
            topics=(f"conversation:{scoped_conversation_id}", "conversations"),
            reason="conversation.skill.credential",
            conversation_id=scoped_conversation_id,
            agent_id=agent_id,
        )
        return result
    except RegistryIngressError as exc: _raise_ingress_http_error(exc)


@app.get("/v1/agents/{agent_id}/conversations/{conversation_id:path}/settings")
async def api_conversation_settings(
    agent_id: str,
    conversation_id: str,
    store: AbstractRegistryStore = Depends(get_store),
    _: None = Depends(require_ui_token),
) -> dict[str, Any]:
    scoped_conversation_id = _conversation_agent_scope(
        store,
        agent_id=agent_id,
        conversation_id=conversation_id,
    )
    try:
        return await conversation_settings_state(store, agent_id, scoped_conversation_id)
    except RegistryIngressError as exc: _raise_ingress_http_error(exc)


@app.post("/v1/agents/{agent_id}/conversations/{conversation_id:path}/settings")
async def api_conversation_update_settings(
    agent_id: str,
    conversation_id: str,
    payload: ConversationSettingUpdateRequest,
    store: AbstractRegistryStore = Depends(get_store),
    _: None = Depends(require_ui_write_access),
) -> dict[str, Any]:
    scoped_conversation_id = _conversation_agent_scope(
        store,
        agent_id=agent_id,
        conversation_id=conversation_id,
    )
    try:
        result = await set_conversation_setting(
            store,
            agent_id,
            scoped_conversation_id,
            actor_key=_operator_actor_key(payload.actor_key),
            setting=payload.setting,
            value=payload.value,
        )
        await _broadcast_invalidations(
            topics=(f"conversation:{scoped_conversation_id}", "conversations"),
            reason="conversation.settings.updated",
            conversation_id=scoped_conversation_id,
            agent_id=agent_id,
        )
        return result
    except RegistryIngressError as exc: _raise_ingress_http_error(exc)


@app.post("/v1/agents/{agent_id}/conversations/{conversation_id:path}/reset")
async def api_conversation_reset(
    agent_id: str,
    conversation_id: str,
    payload: ConversationResetRequest,
    store: AbstractRegistryStore = Depends(get_store),
    _: None = Depends(require_ui_write_access),
) -> dict[str, Any]:
    scoped_conversation_id = _conversation_agent_scope(
        store,
        agent_id=agent_id,
        conversation_id=conversation_id,
    )
    try:
        result = await reset_conversation(
            store,
            agent_id,
            scoped_conversation_id,
            actor_key=_operator_actor_key(payload.actor_key),
        )
        await _broadcast_invalidations(
            topics=(f"conversation:{scoped_conversation_id}", "conversations"),
            reason="conversation.reset",
            conversation_id=scoped_conversation_id,
            agent_id=agent_id,
        )
        return result
    except RegistryIngressError as exc: _raise_ingress_http_error(exc)


@app.post("/v1/agents/{agent_id}/guidance/{provider_name}/preview")
async def api_provider_guidance_preview(
    agent_id: str,
    provider_name: str,
    payload: ProviderGuidancePreviewRequest,
    store: AbstractRegistryStore = Depends(get_store),
    _: None = Depends(require_ui_write_access),
) -> dict[str, Any]:
    try:
        return await preview_provider_guidance(
            store,
            agent_id,
            provider_name,
            role=payload.role,
            active_skills=list(payload.active_skills),
            compact_mode=payload.compact_mode,
            use_draft=payload.use_draft,
            body_override=payload.body_override,
        )
    except RegistryIngressError as exc: _raise_ingress_http_error(exc)


@app.get("/v1/agents/{agent_id}/guidance/{provider_name}")
async def api_provider_guidance_detail(
    agent_id: str,
    provider_name: str,
    scope_kind: str = Query(default="system"),
    scope_key: str = Query(default=""),
    store: AbstractRegistryStore = Depends(get_store),
    _: None = Depends(require_ui_token),
) -> dict[str, Any]:
    try:
        return await provider_guidance_detail(
            store,
            agent_id,
            provider_name,
            scope_kind=scope_kind,
            scope_key=scope_key,
        )
    except RegistryIngressError as exc: _raise_ingress_http_error(exc)


@app.put("/v1/agents/{agent_id}/guidance/{provider_name}/draft")
async def api_provider_guidance_edit_draft(
    agent_id: str,
    provider_name: str,
    payload: ProviderGuidanceDraftUpdateRequest,
    store: AbstractRegistryStore = Depends(get_store),
    _: None = Depends(require_ui_write_access),
) -> dict[str, Any]:
    try:
        return await edit_provider_guidance_draft(
            store,
            agent_id,
            provider_name,
            actor_key=_operator_actor_key(payload.actor_key),
            body=payload.body,
            scope_kind=payload.scope_kind,
            scope_key=payload.scope_key,
        )
    except RegistryIngressError as exc: _raise_ingress_http_error(exc)


@app.post("/v1/agents/{agent_id}/guidance/{provider_name}/submit")
async def api_provider_guidance_submit(
    agent_id: str,
    provider_name: str,
    payload: LifecycleActionRequest,
    store: AbstractRegistryStore = Depends(get_store),
    _: None = Depends(require_ui_write_access),
) -> dict[str, Any]:
    try:
        return await submit_provider_guidance(
            store,
            agent_id,
            provider_name,
            actor_key=_operator_actor_key(payload.actor_key),
            note=payload.note,
        )
    except RegistryIngressError as exc: _raise_ingress_http_error(exc)


@app.post("/v1/agents/{agent_id}/guidance/{provider_name}/approve")
async def api_provider_guidance_approve(
    agent_id: str,
    provider_name: str,
    payload: LifecycleActionRequest,
    store: AbstractRegistryStore = Depends(get_store),
    _: None = Depends(require_ui_write_access),
) -> dict[str, Any]:
    try:
        return await approve_provider_guidance(
            store,
            agent_id,
            provider_name,
            actor_key=_operator_actor_key(payload.actor_key),
            note=payload.note,
        )
    except RegistryIngressError as exc: _raise_ingress_http_error(exc)


@app.post("/v1/agents/{agent_id}/guidance/{provider_name}/reject")
async def api_provider_guidance_reject(
    agent_id: str,
    provider_name: str,
    payload: LifecycleActionRequest,
    store: AbstractRegistryStore = Depends(get_store),
    _: None = Depends(require_ui_write_access),
) -> dict[str, Any]:
    try:
        return await reject_provider_guidance(
            store,
            agent_id,
            provider_name,
            actor_key=_operator_actor_key(payload.actor_key),
            note=payload.note,
        )
    except RegistryIngressError as exc: _raise_ingress_http_error(exc)


@app.post("/v1/agents/{agent_id}/guidance/{provider_name}/publish")
async def api_provider_guidance_publish(
    agent_id: str,
    provider_name: str,
    payload: LifecycleActionRequest,
    store: AbstractRegistryStore = Depends(get_store),
    _: None = Depends(require_ui_write_access),
) -> dict[str, Any]:
    try:
        return await publish_provider_guidance(
            store,
            agent_id,
            provider_name,
            actor_key=_operator_actor_key(payload.actor_key),
            note=payload.note,
        )
    except RegistryIngressError as exc: _raise_ingress_http_error(exc)


@app.post("/v1/agents/{agent_id}/guidance/{provider_name}/archive")
async def api_provider_guidance_archive(
    agent_id: str,
    provider_name: str,
    payload: LifecycleActionRequest,
    store: AbstractRegistryStore = Depends(get_store),
    _: None = Depends(require_ui_write_access),
) -> dict[str, Any]:
    try:
        return await archive_provider_guidance(
            store,
            agent_id,
            provider_name,
            actor_key=_operator_actor_key(payload.actor_key),
            note=payload.note,
        )
    except RegistryIngressError as exc: _raise_ingress_http_error(exc)
