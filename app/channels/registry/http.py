"""FastAPI HTTP entrypoint for the registry channel."""

from __future__ import annotations

from contextlib import asynccontextmanager
import html
import hmac
from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel, Field

from app.channels.registry.auth import (
    clear_ui_session,
    configure_session_middleware,
    current_ui_csrf_token,
    load_settings,
    mark_ui_session_authenticated,
    require_agent_token,
    require_ui_session,
    require_ui_token,
    require_ui_write_access,
    ui_password_matches,
    ui_session_is_valid,
    validate_settings,
)
from app.capability_service import CapabilityService
from app.channels.registry import ui
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
from app.session_state import session_to_dict

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


class CreateConversationRequest(BaseModel):
    target_agent_id: str = Field(..., min_length=1, description="Agent ID to target")
    title: str = Field(default="", description="Conversation title")
    message_text: str = Field(..., min_length=1, description="Initial message text")


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
def healthz(store: AbstractRegistryStore = Depends(get_store)) -> dict[str, Any]:
    return {"ok": True, "bots": len(store.list_agents())}


@app.post("/v1/agents/enroll")
def enroll(payload: dict[str, Any], store: AbstractRegistryStore = Depends(get_store)) -> dict[str, Any]:
    settings = load_settings()
    enroll_tok = payload.get("enrollment_token") or ""
    if not hmac.compare_digest(enroll_tok, settings.enroll_token):
        raise HTTPException(status_code=401, detail="Invalid enrollment token")
    try:
        return store.enroll(payload.get("agent_card"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/agents/register")
def register(
    payload: dict[str, Any],
    agent_token: str = Depends(require_agent_token),
    store: AbstractRegistryStore = Depends(get_store),
) -> dict[str, Any]:
    try:
        return store.register(agent_token, payload)
    except PermissionError as exc:
        raise _agent_permission_http_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/agents/heartbeat")
def heartbeat(
    payload: dict[str, Any],
    agent_token: str = Depends(require_agent_token),
    store: AbstractRegistryStore = Depends(get_store),
) -> dict[str, Any]:
    try:
        return store.heartbeat(agent_token, payload)
    except PermissionError as exc:
        raise _agent_permission_http_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/agents/timeline")
def publish_timeline(
    payload: dict[str, Any],
    agent_token: str = Depends(require_agent_token),
    store: AbstractRegistryStore = Depends(get_store),
) -> dict[str, Any]:
    try:
        return store.publish_timeline(agent_token, payload.get("events"))
    except PermissionError as exc:
        raise _agent_permission_http_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/agents/conversations/bind")
def bind_conversation(
    payload: dict[str, Any],
    agent_token: str = Depends(require_agent_token),
    store: AbstractRegistryStore = Depends(get_store),
) -> dict[str, Any]:
    try:
        return store.bind_conversation(agent_token, payload)
    except PermissionError as exc:
        raise _agent_permission_http_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


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
def create_routed_task(
    payload: dict[str, Any],
    agent_token: str = Depends(require_agent_token),
    store: AbstractRegistryStore = Depends(get_store),
) -> dict[str, Any]:
    try:
        store.assert_agent_scope(agent_token, {"coordination", "full"})
        validated_request = validated_routed_task_request(payload)
        store.heartbeat(agent_token, {"connectivity_state": "connected"})
        return store.create_routed_task(validated_request)
    except PermissionError as exc:
        raise _agent_permission_http_error(exc) from exc
    except CapabilityDisabledError as exc:
        raise HTTPException(status_code=409, detail="capability_disabled") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


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
def routed_task_status(
    routed_task_id: str,
    payload: dict[str, Any],
    agent_token: str = Depends(require_agent_token),
    store: AbstractRegistryStore = Depends(get_store),
) -> dict[str, Any]:
    try:
        return store.update_routed_task_status(agent_token, routed_task_id, payload)
    except PermissionError as exc:
        raise _agent_permission_http_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/agents/routed-tasks/{routed_task_id}/result")
def routed_task_result(
    routed_task_id: str,
    payload: dict[str, Any],
    agent_token: str = Depends(require_agent_token),
    store: AbstractRegistryStore = Depends(get_store),
) -> dict[str, Any]:
    try:
        return store.update_routed_task_result(agent_token, routed_task_id, payload)
    except PermissionError as exc:
        raise _agent_permission_http_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown routed task: {routed_task_id}") from exc


@app.post("/v1/agents/deregister")
def deregister(
    agent_token: str = Depends(require_agent_token),
    store: AbstractRegistryStore = Depends(get_store),
) -> dict[str, Any]:
    try:
        return store.deregister(agent_token)
    except PermissionError as exc:
        raise _agent_permission_http_error(exc) from exc


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


@app.get("/ui/login", response_class=HTMLResponse)
def ui_login_page(request: Request):
    settings = load_settings()
    if ui_session_is_valid(request):
        return RedirectResponse("/ui", status_code=303)
    return _secure_html_response(ui.render_login_html(settings.display_name or "Agent Registry"))


@app.post("/ui/login")
async def ui_login(request: Request, password: str = Form(default="")):
    settings = load_settings()
    if ui_session_is_valid(request):
        return RedirectResponse("/ui", status_code=303)
    if not ui_password_matches(password, settings=settings):
        return _secure_html_response(
            ui.render_login_html(settings.display_name or "Agent Registry", error="Incorrect password.")
        )
    mark_ui_session_authenticated(request)
    return RedirectResponse("/ui", status_code=303)


@app.get("/ui/logout")
def ui_logout(request: Request):
    clear_ui_session(request)
    return RedirectResponse("/ui/login", status_code=303)


@app.get("/ui", response_class=HTMLResponse)
def ui_shell(request: Request) -> str:
    require_ui_session(request)
    settings = load_settings()
    title_text = f"{settings.display_name} — Agent Registry" if settings.display_name else "Agent Registry"
    heading_text = settings.display_name or "Agent Registry"
    logout_link = '<a href="/ui/logout" class="nav-link">Logout</a>'
    # TODO M11: add a read-only access panel once the registry has a bot-to-registry
    # sync protocol for user_access overrides; the registry service cannot read
    # the bot-local transport.db directly.
    return _secure_html_response(
        ui.render_shell_html(
            title_text=title_text,
            heading_text=heading_text,
            logout_link=logout_link,
            csrf_token=current_ui_csrf_token(request),
        )
    )

@app.get("/v1/ui/bootstrap")
def ui_bootstrap(_: None = Depends(require_ui_token), store: AbstractRegistryStore = Depends(get_store)) -> dict[str, Any]:
    return store.ui_bootstrap()


@app.get("/v1/ui/bots")
def ui_bots(_: None = Depends(require_ui_token), store: AbstractRegistryStore = Depends(get_store)) -> dict[str, Any]:
    return {"bots": store.list_agents()}


@app.get("/v1/ui/bots/{agent_id}/health")
def ui_bot_health(
    agent_id: str,
    _: None = Depends(require_ui_token),
    store: AbstractRegistryStore = Depends(get_store),
) -> dict[str, Any]:
    detail = store.get_agent_runtime_health(agent_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Unknown bot or no mirrored runtime health")
    return detail


@app.get("/v1/ui/conversations")
def ui_conversations(_: None = Depends(require_ui_token), store: AbstractRegistryStore = Depends(get_store)) -> dict[str, Any]:
    return {"conversations": store.list_conversations()}


@app.get("/v1/ui/search")
def ui_search(
    q: str = "",
    limit: int = 20,
    _: None = Depends(require_ui_token),
    store: AbstractRegistryStore = Depends(get_store),
) -> dict[str, Any]:
    q = q.strip()
    if len(q) < 3:
        return {"results": []}
    return {"results": store.search_conversations(q, min(limit, 100))}


@app.get("/v1/ui/capabilities")
def ui_capabilities(_: None = Depends(require_ui_token), store: AbstractRegistryStore = Depends(get_store)) -> list[dict[str, Any]]:
    return [
        {
            "capability_name": item.capability_name,
            "declared_by_agents": list(item.declared_by_agents),
            "enabled": item.enabled,
        }
        for item in CapabilityService(store).list_capabilities()
    ]


@app.get("/v1/ui/usage")
def ui_usage(
    _: None = Depends(require_ui_token),
    store: AbstractRegistryStore = Depends(get_store),
) -> dict[str, Any]:
    since_iso = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0,
    ).isoformat()
    rows = store.get_usage_summary(since_iso)
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


@app.post("/v1/ui/capabilities/{capability_name}/enable")
def ui_enable_capability(
    capability_name: str,
    _: None = Depends(require_ui_write_access),
    store: AbstractRegistryStore = Depends(get_store),
) -> dict[str, Any]:
    item = CapabilityService(store).set_enabled(capability_name, enabled=True)
    return {"capability_name": item.capability_name, "enabled": True}


@app.post("/v1/ui/capabilities/{capability_name}/disable")
def ui_disable_capability(
    capability_name: str,
    _: None = Depends(require_ui_write_access),
    store: AbstractRegistryStore = Depends(get_store),
) -> dict[str, Any]:
    item = CapabilityService(store).set_enabled(capability_name, enabled=False)
    return {"capability_name": item.capability_name, "enabled": False}


@app.post("/v1/ui/conversations", status_code=201)
def ui_create_conversation(
    payload: CreateConversationRequest,
    _: None = Depends(require_ui_write_access),
    store: AbstractRegistryStore = Depends(get_store),
) -> dict[str, Any]:
    if not any(agent["agent_id"] == payload.target_agent_id for agent in store.list_agents()):
        raise HTTPException(status_code=404, detail=f"Unknown agent: {payload.target_agent_id}")
    return store.create_conversation(
        target_agent_id=payload.target_agent_id,
        title=payload.title,
        message_text=payload.message_text,
    )


@app.get("/v1/ui/conversations/{conversation_id}")
def ui_get_conversation(
    conversation_id: str,
    _: None = Depends(require_ui_token),
    store: AbstractRegistryStore = Depends(get_store),
) -> dict[str, Any]:
    try:
        return store.get_conversation(conversation_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown conversation: {conversation_id}") from exc


@app.get("/v1/ui/conversations/{conversation_id}/timeline")
def ui_get_conversation_timeline(
    conversation_id: str,
    _: None = Depends(require_ui_token),
    store: AbstractRegistryStore = Depends(get_store),
) -> dict[str, Any]:
    return {"events": store.get_conversation_timeline(conversation_id)}


@app.get("/v1/ui/conversations/{conversation_id}/export")
def ui_export_conversation(
    conversation_id: str,
    _: None = Depends(require_ui_token),
    store: AbstractRegistryStore = Depends(get_store),
) -> Response:
    try:
        conv = store.get_conversation(conversation_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Conversation not found") from exc
    events = store.get_conversation_timeline(conversation_id)

    lines = [
        f"# Conversation: {conv['title'] or conversation_id}",
        f"Exported: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
        f"Status: {conv['status']}",
        f"Bot: {conv.get('target_display_name') or conv.get('target_agent_id', '')}",
        f"Created: {conv['created_at']}",
        "",
    ]
    for event in events:
        lines.append(f"## [{event['created_at']}] {event['kind']}")
        body = (event.get("body") or "").strip()
        if body:
            lines.append(body)
        lines.append("")

    content = "\n".join(lines)
    filename = f'conversation-{conversation_id}.md'
    return Response(
        content=content,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/v1/ui/conversations/{conversation_id}/messages")
def ui_add_conversation_message(
    conversation_id: str,
    payload: dict[str, Any],
    _: None = Depends(require_ui_write_access),
    store: AbstractRegistryStore = Depends(get_store),
) -> dict[str, Any]:
    try:
        return store.add_conversation_message(conversation_id, payload.get("text", ""))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Conversation not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/ui/conversations/{conversation_id}/actions")
def ui_add_conversation_action(
    conversation_id: str,
    payload: dict[str, Any],
    _: None = Depends(require_ui_write_access),
    store: AbstractRegistryStore = Depends(get_store),
) -> dict[str, Any]:
    try:
        return store.add_conversation_action(
            conversation_id,
            payload.get("action", ""),
            payload.get("payload", {}),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Conversation not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/v1/ui/tasks")
def ui_tasks(_: None = Depends(require_ui_token), store: AbstractRegistryStore = Depends(get_store)) -> dict[str, Any]:
    return {"tasks": store.list_tasks()}
