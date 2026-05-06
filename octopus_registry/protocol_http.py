"""Protocol HTTP routes for the registry control plane."""

from __future__ import annotations

import mimetypes
import base64
import copy
import json
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from urllib.parse import quote
import uuid

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import ValidationError

from octopus_sdk.protocols import (
    ProtocolAccessContextRecord,
    ProtocolArtifactRecord,
    ProtocolArtifactRuntimeEventRecord,
    ProtocolArtifactRuntimeInstanceRecord,
    ProtocolArtifactRuntimeManifestRecord,
    ProtocolAutoDesignModelRequestRecord,
    ProtocolAutoDesignRequestRecord,
    ProtocolAutoDesignSessionRecord,
    ProtocolDraftCreateRecord,
    ProtocolPackageImportApplyResultRecord,
    ProtocolPackageImportPlanRecord,
    ProtocolPackageIssueRecord,
    ProtocolPackageProtocolPlanRecord,
    ProtocolPackageSkillPlanRecord,
    ProtocolPackageStageMappingPlanRecord,
    ProtocolRunCreateRecord,
    ProtocolTemplateCreateRecord,
    TargetSelector,
    canonical_protocol_document,
    protocol_run_create_from_auto_session,
    revise_auto_protocol_session,
    protocol_definition_content_hash,
    protocol_package_document,
    protocol_package_from_text,
    protocol_package_hash,
    protocol_package_required_skill_names,
    protocol_package_to_text,
)
from octopus_sdk.registry.management import (
    ArtifactRuntimeFetchRequest,
    ArtifactRuntimeFetchResult,
    ArtifactRuntimeHealthRequest,
    ArtifactRuntimeHealthResult,
    ArtifactRuntimeLogsRequest,
    ArtifactRuntimeLogsResult,
    DesignAutoProtocolRequest,
    DesignAutoProtocolResult,
    StartArtifactRuntimeRequest,
    StartArtifactRuntimeResult,
    StopArtifactRuntimeRequest,
    StopArtifactRuntimeResult,
    WorkspaceCleanupPlanRecord,
    WorkspaceCleanupRequest,
    WorkspaceCleanupResult,
    WorkspaceUsageRequest,
    WorkspaceUsageResult,
)
from octopus_sdk.registry.models import RegistryJsonRecord
from octopus_sdk.skill_packages import (
    skill_document_from_text,
    skill_document_to_text,
    skill_package_from_document,
    skill_package_hash,
)

from .artifact_paths import (
    artifact_download_name,
    resolve_protocol_artifact_path,
    resolve_protocol_artifact_rehearsal_text,
)
from .artifact_responses import workspace_artifact_content_response
from .artifact_responses import rendered_artifact_text_preview_response
from .artifact_snapshots import artifact_snapshot_storage_path, create_artifact_snapshot
from .auth import AuthContext
from .config import load_registry_config
from .http_support import json_payload as _json_payload, paginated_response as _paginated_response
from .management_client import ManagementClientError, RegistryManagementClient
from .ingress import (
    RegistryIngressError,
    export_catalog_skill_package,
    import_catalog_skill_package,
)
from .rehearsal import RehearsalSessionManager
from .store_base import AbstractRegistryStore

_InvalidationBroadcaster = Callable[..., Awaitable[None]]
_TopicEventBroadcaster = Callable[..., Awaitable[None]]


def _runtime_http_path(value: str, default: str = "/") -> str:
    text = str(value or default).strip() or default
    if not text.startswith("/"):
        text = f"/{text}"
    return text


def _runtime_proxy_base(run_id: str, artifact_key: str, area: str) -> str:
    safe_run = quote(str(run_id), safe="")
    safe_artifact = quote(str(artifact_key), safe="")
    return f"/runtime/protocol-runs/{safe_run}/artifacts/{safe_artifact}/{area.strip('/')}"


def _runtime_api_outbound_path(manifest: ProtocolArtifactRuntimeManifestRecord, proxy_tail: str) -> str:
    base_path = _runtime_http_path(str(manifest.api_base_path or "/api"), "/api")
    tail = str(proxy_tail or "").strip("/")
    if not tail:
        return base_path
    tail_path = _runtime_http_path(tail)
    base_prefix = base_path.rstrip("/")
    if tail_path == base_path or tail_path.startswith(f"{base_prefix}/") or tail_path.startswith(f"{base_prefix}?"):
        return tail_path
    if base_path == "/":
        return tail_path
    return f"{base_prefix}{tail_path}"


def _runtime_rewrite_browser_path(
    url: str,
    *,
    app_base: str,
    api_base: str,
    manifest: ProtocolArtifactRuntimeManifestRecord,
) -> str:
    text = str(url or "")
    if not text.startswith("/") or text.startswith("//"):
        return text
    if text.startswith(f"{app_base}/") or text == app_base or text.startswith(f"{api_base}/") or text == api_base:
        return text
    api_root = _runtime_http_path(str(manifest.api_base_path or "/api"), "/api").rstrip("/") or "/api"
    health_path = _runtime_http_path(str(manifest.health_path or "/health"), "/health").rstrip("/") or "/health"
    if text == health_path or text.startswith(f"{health_path}?") or text.startswith(f"{health_path}#"):
        suffix = text[len(health_path) :]
        return f"{app_base}{health_path}{suffix}"
    if text == api_root or text.startswith(f"{api_root}/") or text.startswith(f"{api_root}?") or text.startswith(f"{api_root}#"):
        suffix = text[len(api_root) :]
        return f"{api_base}{suffix}"
    if text == "/api" or text.startswith("/api/") or text.startswith("/api?") or text.startswith("/api#"):
        suffix = text[len("/api") :]
        return f"{api_base}{suffix}"
    return f"{app_base}{text}"


_RUNTIME_URL_ATTR_RE = re.compile(r"(?P<prefix>\b(?:src|href|action)=['\"])(?P<url>/(?!/)[^'\"]*)(?P<suffix>['\"])", re.IGNORECASE)


def _rewrite_runtime_html_content(
    content: bytes,
    *,
    content_type: str,
    run_id: str,
    artifact_key: str,
    manifest: ProtocolArtifactRuntimeManifestRecord,
) -> bytes:
    if "text/html" not in str(content_type or "").lower():
        return content
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return content
    app_base = _runtime_proxy_base(run_id, artifact_key, "app")
    api_base = _runtime_proxy_base(run_id, artifact_key, "api")

    def _replace_attr(match: re.Match[str]) -> str:
        return (
            match.group("prefix")
            + _runtime_rewrite_browser_path(match.group("url"), app_base=app_base, api_base=api_base, manifest=manifest)
            + match.group("suffix")
        )

    text = _RUNTIME_URL_ATTR_RE.sub(_replace_attr, text)
    script = f"""
<script>
(() => {{
  const appBase = {json.dumps(app_base)};
  const apiBase = {json.dumps(api_base)};
  const apiRoot = {json.dumps(_runtime_http_path(str(manifest.api_base_path or "/api"), "/api").rstrip("/") or "/api")};
  const healthPath = {json.dumps(_runtime_http_path(str(manifest.health_path or "/health"), "/health").rstrip("/") or "/health")};
  const rewrite = (value) => {{
    if (typeof value !== 'string') return value;
    if (!value.startsWith('/') || value.startsWith('//')) return value;
    if (value === appBase || value.startsWith(appBase + '/') || value === apiBase || value.startsWith(apiBase + '/')) return value;
    if (value === healthPath || value.startsWith(healthPath + '?') || value.startsWith(healthPath + '#')) return appBase + value;
    if (value === apiRoot || value.startsWith(apiRoot + '/') || value.startsWith(apiRoot + '?') || value.startsWith(apiRoot + '#')) return apiBase + value.slice(apiRoot.length);
    if (value === '/api' || value.startsWith('/api/') || value.startsWith('/api?') || value.startsWith('/api#')) return apiBase + value.slice('/api'.length);
    return appBase + value;
  }};
  window.OCTOPUS_RUNTIME = Object.freeze({{
    appBase,
    apiBase,
    healthPath: appBase + healthPath,
    rewrite
  }});
  const originalFetch = window.fetch;
  if (originalFetch) {{
    window.fetch = function(input, init) {{
      if (typeof input === 'string') {{
        input = rewrite(input);
      }} else if (input && typeof input.url === 'string') {{
        const parsed = new URL(input.url, window.location.href);
        if (parsed.origin === window.location.origin) {{
          const originalPath = parsed.pathname + parsed.search + parsed.hash;
          const nextUrl = rewrite(originalPath);
          if (nextUrl !== originalPath) input = new Request(nextUrl, input);
        }}
      }}
      return originalFetch.call(this, input, init);
    }};
  }}
  const originalOpen = window.XMLHttpRequest && window.XMLHttpRequest.prototype && window.XMLHttpRequest.prototype.open;
  if (originalOpen) {{
    window.XMLHttpRequest.prototype.open = function(method, url, ...rest) {{
      return originalOpen.call(this, method, rewrite(url), ...rest);
    }};
  }}
}})();
</script>
""".strip()
    head_match = re.search(r"<head\b[^>]*>", text, flags=re.IGNORECASE)
    if head_match:
        text = text[: head_match.end()] + script + text[head_match.end() :]
    else:
        text = script + text
    return text.encode("utf-8")


def build_protocol_router(
    *,
    get_store: Callable[[], AbstractRegistryStore],
    require_authenticated: Callable[..., AuthContext],
    require_operator_session: Callable[..., AuthContext],
    protocol_access: Callable[[AuthContext], ProtocolAccessContextRecord],
    broadcast_invalidations: _InvalidationBroadcaster,
    broadcast_topic_event: _TopicEventBroadcaster,
    get_rehearsal_manager: Callable[[], RehearsalSessionManager],
) -> APIRouter:
    router = APIRouter()

    def _protocol_http_error(
        status_code: int,
        *,
        error_code: str,
        message: str,
        details: object | None = None,
    ) -> HTTPException:
        return HTTPException(
            status_code=status_code,
            detail={
                "error_code": error_code,
                "message": message,
                "details": details,
            },
        )

    def _protocol_result_http_error(result) -> HTTPException:
        status = str(getattr(result, "status", "") or "").lower()
        message = str(getattr(result, "message", "") or "Protocol request failed.")
        if status == "conflict":
            details = {
                "protocol": _json_payload(getattr(result, "protocol", None)),
                "draft_definition_json": _json_payload(getattr(result, "draft_definition_json", None)),
                "draft_document": _json_payload(getattr(result, "draft_document", None)),
                "validation": _json_payload(getattr(result, "validation", None)),
            }
            return _protocol_http_error(409, error_code="PROTOCOL_DRAFT_CONFLICT", message=message, details=details)
        if status == "not_found":
            return _protocol_http_error(404, error_code="PROTOCOL_NOT_FOUND", message=message)
        if status == "not_visible":
            return _protocol_http_error(403, error_code="PROTOCOL_NOT_VISIBLE", message=message)
        if status == "forbidden":
            return _protocol_http_error(403, error_code="PROTOCOL_FORBIDDEN", message=message)
        if status == "idempotency_conflict":
            return _protocol_http_error(409, error_code="IDEMPOTENCY_REPLAY", message=message)
        if status == "concurrent_modification":
            return _protocol_http_error(409, error_code="CONCURRENT_MODIFICATION", message=message)
        if status == "duplicate_slug":
            return _protocol_http_error(409, error_code="PROTOCOL_DUPLICATE_SLUG", message=message)
        if status == "invalid_action":
            return _protocol_http_error(400, error_code="PROTOCOL_INVALID_ACTION", message=message)
        if status == "invalid":
            return _protocol_http_error(400, error_code="PROTOCOL_INVALID", message=message)
        return _protocol_http_error(400, error_code="PROTOCOL_REQUEST_FAILED", message=message)

    def _auto_protocol_access(auth: AuthContext) -> ProtocolAccessContextRecord:
        access = protocol_access(auth)
        roles = set(access.roles or ())
        if auth.is_agent:
            roles.update({"agent", "author", "publisher"})
        return access.model_copy(update={"roles": sorted(roles)})

    def _package_format(value: object) -> str:
        token = str(value or "").strip().lower()
        if token in {"yaml", "yml"}:
            return "yaml"
        return "json"

    def _agent_json(agent) -> dict[str, Any]:
        row = agent.model_dump(mode="json") if hasattr(agent, "model_dump") else dict(agent)
        return {
            "agent_id": str(row.get("agent_id", "") or ""),
            "slug": str(row.get("slug", "") or ""),
            "display_name": str(row.get("display_name", "") or ""),
            "provider": str(row.get("provider", "") or ""),
            "role": str(row.get("role", "") or ""),
            "routing_skills": [
                str(item or "").strip().lower()
                for item in row.get("routing_skills", []) or []
                if str(item or "").strip()
            ],
            "supported_admin_operations": [
                str(item or "").strip()
                for item in row.get("supported_admin_operations", []) or []
                if str(item or "").strip()
            ],
        }

    def _connected_agents(store: AbstractRegistryStore) -> list[dict[str, Any]]:
        return [
            _agent_json(agent)
            for agent in store.list_agents(cursor=0, limit=200, connectivity_state="connected")
        ]

    def _management_agent_id_for_operation(
        store: AbstractRegistryStore,
        *,
        requested_agent_id: str = "",
        operation: str,
    ) -> str:
        agents = _connected_agents(store)
        if requested_agent_id:
            candidate = next((item for item in agents if str(item.get("agent_id") or "") == requested_agent_id), None)
            if candidate is None:
                raise _protocol_http_error(
                    404,
                    error_code="AGENT_NOT_CONNECTED",
                    message="Requested agent is not connected.",
                )
            operations = {str(item or "").strip() for item in candidate.get("supported_admin_operations", []) or []}
            if operation not in operations:
                raise _protocol_http_error(
                    409,
                    error_code="AGENT_OPERATION_UNSUPPORTED",
                    message=f"Requested agent does not support {operation}.",
                )
            return requested_agent_id
        for agent in agents:
            operations = {str(item or "").strip() for item in agent.get("supported_admin_operations", []) or []}
            if operation in operations:
                return str(agent.get("agent_id") or "").strip()
        raise _protocol_http_error(
            409,
            error_code="AGENT_OPERATION_UNAVAILABLE",
            message=f"Connect an agent that supports {operation}.",
        )

    def _routing_skill_json(skill) -> dict[str, Any]:
        row = skill.model_dump(mode="json") if hasattr(skill, "model_dump") else dict(skill)
        return {
            "skill_name": str(row.get("skill_name", "") or row.get("name", "") or ""),
            "advertised_by_agents": [
                str(item or "").strip()
                for item in row.get("advertised_by_agents", []) or []
                if str(item or "").strip()
            ],
            "enabled": row.get("enabled"),
        }

    def _auto_protocol_request(
        payload: dict[str, Any],
        *,
        auth: AuthContext,
        access: ProtocolAccessContextRecord,
        store: AbstractRegistryStore,
        default_mode: str = "create",
    ) -> ProtocolAutoDesignRequestRecord:
        alias_fields = {"protocol_id", "source_protocol_id", "change_request", "constraints", "entry_agent_id"}
        used_aliases = sorted(field for field in alias_fields if field in payload)
        if used_aliases:
            raise _protocol_http_error(
                400,
                error_code="PROTOCOL_AUTO_INVALID_FIELD",
                message=f"Unsupported Auto Protocol field(s): {', '.join(used_aliases)}. Use canonical SDK field names.",
            )
        target_protocol_id = str(payload.get("target_protocol_id") or "").strip()
        source_document: dict[str, object] = {}
        target_version_id = ""
        target_draft_revision = 0
        if target_protocol_id:
            loaded = store.get_protocol(target_protocol_id, access=access)
            if not loaded.ok:
                raise _protocol_result_http_error(loaded)
            if loaded.protocol is not None:
                target_version_id = str(loaded.protocol.current_version_id or "")
                target_draft_revision = int(loaded.protocol.draft_revision or 0)
            source_document = loaded.draft_definition_json.as_dict()
        agents = _connected_agents(store)
        preferred_agent_id = str(payload.get("preferred_design_agent_id") or "").strip()
        if auth.is_agent and auth.agent_id and not preferred_agent_id:
            preferred_agent_id = str(auth.agent_id)
        mode = str(payload.get("mode") or default_mode or "create").strip() or "create"
        if mode not in {"create", "revise"}:
            raise _protocol_http_error(
                400,
                error_code="PROTOCOL_AUTO_INVALID_MODE",
                message="Auto Protocol mode must be create or revise.",
            )
        requirement_text = str(payload.get("requirement_text") or "")
        if not requirement_text.strip():
            raise _protocol_http_error(
                400,
                error_code="PROTOCOL_AUTO_REQUIREMENT_REQUIRED",
                message="requirement_text is required for Auto Protocol generation.",
            )
        return ProtocolAutoDesignRequestRecord.model_validate({
            "mode": mode,
            "surface": str(payload.get("surface") or ("telegram" if auth.is_agent else "registry")),
            "requirement_text": requirement_text,
            "constraints_text": str(payload.get("constraints_text") or ""),
            "target_protocol_id": target_protocol_id,
            "target_version_id": target_version_id,
            "target_draft_revision": target_draft_revision,
            "source_document": source_document,
            "available_agents": agents,
            "available_skills": [_routing_skill_json(item) for item in store.list_routing_skills()],
            "workspace_ref": str(payload.get("workspace_ref") or ""),
            "preferred_design_agent_id": preferred_agent_id,
            "actor_ref": access.actor_ref,
            "chat_ref": str(payload.get("chat_ref") or ""),
            "idempotency_key": str(payload.get("idempotency_key") or ""),
        })

    def _auto_protocol_design_agent_id(
        request_payload: ProtocolAutoDesignRequestRecord,
    ) -> str:
        preferred = str(request_payload.preferred_design_agent_id or "").strip()
        candidates = [item.as_dict() for item in request_payload.available_agents]
        if preferred:
            return preferred
        for agent in candidates:
            operations = {
                str(item or "").strip()
                for item in agent.get("supported_admin_operations", []) or []
                if str(item or "").strip()
            }
            if "design_auto_protocol" in operations:
                return str(agent.get("agent_id") or "").strip()
        return str(candidates[0].get("agent_id") or "").strip() if candidates else ""

    async def _auto_protocol_model_response(
        store: AbstractRegistryStore,
        request_payload: ProtocolAutoDesignRequestRecord,
    ):
        agent_id = _auto_protocol_design_agent_id(request_payload)
        if not agent_id:
            raise _protocol_http_error(
                409,
                error_code="PROTOCOL_AUTO_PLANNER_UNAVAILABLE",
                message="Connect a provider-capable agent before generating an Auto Protocol.",
            )
        result = await RegistryManagementClient(store).send(
            agent_id=agent_id,
            payload=DesignAutoProtocolRequest(
                request=ProtocolAutoDesignModelRequestRecord(
                    mode=request_payload.mode,
                    requirement_text=request_payload.requirement_text,
                    constraints_text=request_payload.constraints_text,
                    source_document=request_payload.source_document,
                    available_agents=request_payload.available_agents,
                    available_skills=request_payload.available_skills,
                    workspace_ref=request_payload.workspace_ref,
                    actor_ref=request_payload.actor_ref,
                    chat_ref=request_payload.chat_ref,
                ),
            ),
            timeout_seconds=90,
        )
        if not result.success or not isinstance(result.payload, DesignAutoProtocolResult):
            raise _protocol_http_error(
                502,
                error_code="PROTOCOL_AUTO_PLANNER_FAILED",
                message=result.error_detail or "Auto Protocol planner failed.",
            )
        return result.payload.response

    def _artifact_for_detail(detail, artifact_key: str) -> ProtocolArtifactRecord:
        artifact = next(
            (item for item in detail.artifacts if str(item.artifact_key or "").strip() == str(artifact_key or "").strip()),
            None,
        )
        if artifact is None:
            raise _protocol_http_error(
                404,
                error_code="PROTOCOL_ARTIFACT_NOT_FOUND",
                message="Protocol artifact not found.",
            )
        return artifact

    def _artifact_snapshot_path(snapshot) -> Path | None:
        return artifact_snapshot_storage_path(load_registry_config().artifact_store_dir, snapshot)

    def _artifact_snapshot_payload(snapshot) -> dict[str, Any]:
        return {
            "artifact_snapshot_id": snapshot.artifact_snapshot_id,
            "protocol_artifact_id": snapshot.protocol_artifact_id,
            "protocol_run_id": snapshot.protocol_run_id,
            "artifact_key": snapshot.artifact_key,
            "snapshot_kind": snapshot.snapshot_kind,
            "storage_uri": snapshot.storage_uri,
            "content_hash": snapshot.content_hash,
            "size_bytes": snapshot.size_bytes,
            "manifest_json": snapshot.manifest_json.as_dict(),
            "retention_state": snapshot.retention_state,
            "retention_until": snapshot.retention_until,
            "created_at": snapshot.created_at,
            "created_by": snapshot.created_by,
            "deleted_at": snapshot.deleted_at,
            "deleted_by": snapshot.deleted_by,
        }

    def _runtime_instance_id(run_id: str, artifact_key: str) -> str:
        return uuid.uuid5(uuid.NAMESPACE_URL, f"octopus-runtime:{run_id}:{artifact_key}").hex

    def _runtime_manifest_from_path(path: Path) -> tuple[ProtocolArtifactRuntimeManifestRecord | None, str]:
        root = path if path.is_dir() else path.parent
        manifest_path = root / "octopus-runtime.json"
        if manifest_path.is_file():
            try:
                raw = json.loads(manifest_path.read_text(encoding="utf-8"))
                return ProtocolArtifactRuntimeManifestRecord.model_validate(raw), str(manifest_path)
            except (OSError, json.JSONDecodeError, ValidationError) as exc:
                raise _protocol_http_error(
                    409,
                    error_code="PROTOCOL_ARTIFACT_RUNTIME_MANIFEST_INVALID",
                    message=f"Artifact runtime manifest is invalid: {exc}",
                ) from exc
        index_path = root / "index.html"
        if index_path.is_file():
            return ProtocolArtifactRuntimeManifestRecord(
                runtime_kind="static",
                display_name=root.name or "Artifact app",
                description="Static web artifact served from the artifact package.",
                ui_path="/",
                health_path="/",
            ), ""
        return None, ""

    def _runtime_agent_id(detail, artifact: ProtocolArtifactRecord) -> str:
        producer_id = str(artifact.produced_by_stage_execution_id or "").strip()
        participant_key = ""
        if producer_id:
            producer = next(
                (item for item in detail.stage_executions if str(item.protocol_stage_execution_id or "") == producer_id),
                None,
            )
            participant_key = str(getattr(producer, "participant_key", "") or "").strip()
        if participant_key:
            participant = next(
                (item for item in detail.participants if str(item.participant_key or "") == participant_key),
                None,
            )
            if participant is not None and str(participant.resolved_agent_id or "").strip():
                return str(participant.resolved_agent_id or "").strip()
        return str(detail.run.entry_agent_id or "").strip()

    def _runtime_event(
        *,
        runtime: ProtocolArtifactRuntimeInstanceRecord,
        event_kind: str,
        actor_ref: str,
        summary: str,
        metadata: dict[str, object] | None = None,
    ) -> ProtocolArtifactRuntimeEventRecord:
        return ProtocolArtifactRuntimeEventRecord(
            runtime_event_id=uuid.uuid4().hex,
            runtime_instance_id=runtime.runtime_instance_id,
            protocol_run_id=runtime.protocol_run_id,
            artifact_key=runtime.artifact_key,
            event_kind=event_kind,
            actor_ref=actor_ref,
            summary=summary,
            metadata_json=RegistryJsonRecord(metadata or {}),
        )

    def _runtime_public_urls(run_id: str, artifact_key: str) -> dict[str, str]:
        base = f"/runtime/protocol-runs/{run_id}/artifacts/{artifact_key}"
        return {
            "runtime_url": f"{base}/app/",
            "ui_url": f"{base}/app/",
            "api_url": f"{base}/api/",
            "health_url": f"/v1/protocol-runs/{run_id}/artifacts/{artifact_key}/runtime/health",
        }

    def _runtime_record_json(runtime: ProtocolArtifactRuntimeInstanceRecord | None) -> dict[str, object] | None:
        return _json_payload(runtime) if runtime is not None else None

    def _merge_runtime_record(
        existing: ProtocolArtifactRuntimeInstanceRecord,
        update: ProtocolArtifactRuntimeInstanceRecord,
    ) -> ProtocolArtifactRuntimeInstanceRecord:
        payload = existing.model_dump(mode="json")
        update_payload = update.model_dump(mode="json", exclude_none=True)
        for key in (
            "agent_id",
            "manifest",
            "manifest_path",
            "artifact_path",
            "runtime_url",
            "ui_url",
            "api_url",
            "health_url",
            "internal_url",
        ):
            if not update_payload.get(key):
                update_payload.pop(key, None)
        payload.update(update_payload)
        return ProtocolArtifactRuntimeInstanceRecord.model_validate(payload)

    def _metadata_from_auto_session(session: ProtocolAutoDesignSessionRecord) -> dict[str, str]:
        doc = session.draft_definition_json.as_dict()
        metadata = doc.get("metadata") if isinstance(doc.get("metadata"), dict) else {}
        return {
            "slug": str(metadata.get("slug", "") or session.plan.protocol_slug or "").strip(),
            "display_name": str(metadata.get("display_name", "") or session.plan.protocol_name or "").strip(),
            "description": str(metadata.get("description", "") or session.plan.description or "").strip(),
        }

    def _apply_auto_protocol_session(
        store: AbstractRegistryStore,
        session: ProtocolAutoDesignSessionRecord,
        *,
        access: ProtocolAccessContextRecord,
    ) -> ProtocolAutoDesignSessionRecord:
        metadata = _metadata_from_auto_session(session)
        definition_json = session.draft_definition_json
        result = store.save_protocol_draft(
            access=access,
            protocol_id=str(session.target_protocol_id or ""),
            slug=metadata["slug"],
            display_name=metadata["display_name"],
            description=metadata["description"],
            definition_json=definition_json,
            authoring_surface="standard",
            expected_revision=int(session.target_draft_revision or 0) if session.target_protocol_id else None,
        )
        if not result.ok and str(result.status or "") == "duplicate_slug" and not str(session.target_protocol_id or "").strip():
            copy_slug, copy_name = _suggest_generated_identity(store, metadata["slug"], metadata["display_name"], access)
            copied_document = session.draft_definition_json.as_dict()
            copied_metadata = dict(copied_document.get("metadata") or {})
            copied_metadata.update({"slug": copy_slug, "display_name": copy_name})
            copied_document["metadata"] = copied_metadata
            definition_json = RegistryJsonRecord.model_validate(copied_document)
            metadata = {**metadata, "slug": copy_slug, "display_name": copy_name}
            result = store.save_protocol_draft(
                access=access,
                protocol_id="",
                slug=metadata["slug"],
                display_name=metadata["display_name"],
                description=metadata["description"],
                definition_json=definition_json,
                authoring_surface="standard",
                expected_revision=None,
            )
        if not result.ok:
            raise _protocol_result_http_error(result)
        protocol_id = str(result.protocol.protocol_id if result.protocol is not None else session.target_protocol_id or "")
        updated = session.model_copy(update={
            "status": "applied",
            "target_protocol_id": protocol_id,
            "target_draft_revision": int(result.protocol.draft_revision if result.protocol is not None else session.target_draft_revision or 0),
            "draft_definition_json": definition_json,
            "applied_protocol": result,
        })
        return store.update_protocol_auto_design_session(updated, access=access, event_kind="applied")

    def _auto_protocol_session_has_applied_draft(session: ProtocolAutoDesignSessionRecord) -> bool:
        return (
            str(session.target_protocol_id or "").strip()
            and session.applied_protocol is not None
            and str(session.status or "").strip() in {"applied", "published", "running"}
        )

    def _ensure_auto_protocol_session_applied(
        store: AbstractRegistryStore,
        session: ProtocolAutoDesignSessionRecord,
        *,
        access: ProtocolAccessContextRecord,
    ) -> ProtocolAutoDesignSessionRecord:
        if _auto_protocol_session_has_applied_draft(session):
            return session
        return _apply_auto_protocol_session(store, session, access=access)

    def _ensure_auto_protocol_session_published(
        store: AbstractRegistryStore,
        session: ProtocolAutoDesignSessionRecord,
        *,
        access: ProtocolAccessContextRecord,
    ) -> ProtocolAutoDesignSessionRecord:
        session = _ensure_auto_protocol_session_applied(store, session, access=access)
        if session.applied_protocol is not None and str(session.status or "").strip() in {"published", "running"}:
            return session
        result = store.publish_protocol(session.target_protocol_id, access=access)
        if not result.ok:
            raise _protocol_result_http_error(result)
        return store.update_protocol_auto_design_session(
            session.model_copy(update={"status": "published", "applied_protocol": result}),
            access=access,
            event_kind="published",
        )

    def _ensure_auto_protocol_ready(session: ProtocolAutoDesignSessionRecord, *, action: str) -> None:
        unresolved = list(session.unresolved_decisions or [])
        validation = session.validation
        if validation.ok and not unresolved:
            return
        details = {
            "validation": _json_payload(validation),
            "unresolved_decisions": _json_payload(unresolved),
        }
        if action == "publish":
            raise _protocol_http_error(
                400,
                error_code="PROTOCOL_AUTO_PUBLISH_BLOCKED",
                message="Resolve Auto Protocol validation and assignment warnings before publishing.",
                details=details,
            )
        raise _protocol_http_error(
            400,
            error_code="PROTOCOL_AUTO_RUN_BLOCKED",
            message="Resolve Auto Protocol validation and assignment warnings before running.",
            details=details,
        )

    def _agents_for_skill(agents: list[dict[str, Any]], skill_name: str) -> list[dict[str, Any]]:
        name = str(skill_name or "").strip().lower()
        return [
            agent for agent in agents
            if name in {str(item or "").strip().lower() for item in agent.get("routing_skills", [])}
        ]

    def _agent_by_id(agents: list[dict[str, Any]], agent_id: str) -> dict[str, Any] | None:
        normalized = str(agent_id or "").strip()
        if not normalized:
            return None
        return next((agent for agent in agents if str(agent.get("agent_id", "") or "") == normalized), None)

    def _protocol_metadata(document) -> dict[str, str]:
        metadata = document.metadata.as_dict() if hasattr(document.metadata, "as_dict") else dict(document.metadata or {})
        return {
            "slug": str(metadata.get("slug", "") or "").strip(),
            "display_name": str(metadata.get("display_name", "") or "").strip(),
            "description": str(metadata.get("description", "") or "").strip(),
        }

    def _protocol_package_filename(slug: str, fmt: str) -> str:
        safe_slug = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in str(slug or "protocol").strip().lower()).strip("-") or "protocol"
        return f"{safe_slug}.octopus-protocol.{fmt}"

    def _suggest_copy_identity(store: AbstractRegistryStore, slug: str, display_name: str, access: ProtocolAccessContextRecord) -> tuple[str, str]:
        base_slug = str(slug or "imported-protocol").strip().lower() or "imported-protocol"
        base_name = str(display_name or base_slug.replace("-", " ").title()).strip()
        existing = {
            str(item.slug or "").strip().lower()
            for item in store.list_protocols(access=access, limit=500, include_drafts=True)
        }
        index = 2
        while True:
            candidate = f"{base_slug}-copy-{index}"
            if candidate not in existing:
                return candidate, f"{base_name} (Imported {index})"
            index += 1

    def _suggest_generated_identity(store: AbstractRegistryStore, slug: str, display_name: str, access: ProtocolAccessContextRecord) -> tuple[str, str]:
        base_slug = str(slug or "auto-protocol").strip().lower() or "auto-protocol"
        base_name = str(display_name or base_slug.replace("-", " ").title()).strip()
        existing = {
            str(item.slug or "").strip().lower()
            for item in store.list_protocols(access=access, limit=500, include_drafts=True)
        }
        index = 2
        while True:
            candidate = f"{base_slug}-generated-{index}"
            if candidate not in existing:
                return candidate, f"{base_name} (Generated {index})"
            index += 1

    def _stage_mapping_choices(payload: dict[str, Any]) -> dict[str, str]:
        mappings: dict[str, str] = {}
        for item in payload.get("stage_mappings") or []:
            if not isinstance(item, dict):
                continue
            stage_key = str(item.get("stage_key", "") or "").strip()
            agent_id = str(item.get("target_agent_id", "") or "").strip()
            if stage_key and agent_id:
                mappings[stage_key] = agent_id
        return mappings

    def _skill_target_choices(payload: dict[str, Any]) -> dict[str, str]:
        mappings: dict[str, str] = {}
        for item in payload.get("skill_targets") or []:
            if not isinstance(item, dict):
                continue
            skill_name = str(item.get("skill_name", item.get("name", "")) or "").strip().lower()
            agent_id = str(item.get("target_agent_id", "") or "").strip()
            if skill_name and agent_id:
                mappings[skill_name] = agent_id
        return mappings

    def _copy_protocol_document_with_mappings(package, stage_mappings: dict[str, str]) -> dict[str, Any]:
        document = copy.deepcopy(package.protocol.model_dump(mode="json"))
        stages = document.get("stages") if isinstance(document.get("stages"), list) else []
        for stage in stages:
            if not isinstance(stage, dict):
                continue
            stage_key = str(stage.get("stage_key", "") or "").strip()
            target_agent_id = stage_mappings.get(stage_key, "")
            selector = stage.get("selector")
            if not isinstance(selector, dict) or not target_agent_id:
                continue
            kind = str(selector.get("kind", "") or "").strip().lower()
            if kind == "skill":
                selector["preferred_agent_id"] = target_agent_id
            elif kind == "agent":
                selector["value"] = target_agent_id
                selector.pop("preferred_agent_id", None)
        return document

    def _expected_protocol_version(if_match: str | None) -> int | None:
        value = str(if_match or "").strip()
        if not value:
            return None
        try:
            return int(value)
        except ValueError as exc:
            raise _protocol_http_error(
                400,
                error_code="PROTOCOL_INVALID_IF_MATCH",
                message="If-Match must be an integer protocol run version.",
                details={"if_match": value},
            ) from exc

    def _expected_draft_revision(if_match: str | None) -> int | None:
        value = str(if_match or "").strip()
        if not value:
            return None
        try:
            return int(value)
        except ValueError as exc:
            raise _protocol_http_error(
                400,
                error_code="PROTOCOL_INVALID_IF_MATCH",
                message="If-Match must be an integer protocol draft revision.",
                details={"if_match": value},
            ) from exc

    @router.post("/v1/protocol-auto/sessions")
    async def resource_create_protocol_auto_session(
        payload: dict[str, Any] = Body(...),
        auth: AuthContext = Depends(require_authenticated),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise _protocol_http_error(400, error_code="PROTOCOL_AUTO_INVALID", message="Invalid Auto Protocol payload.")
        access = _auto_protocol_access(auth)
        try:
            request_payload = _auto_protocol_request(payload, auth=auth, access=access, store=store)
            model_response = await _auto_protocol_model_response(store, request_payload)
            request_payload = request_payload.model_copy(update={"model_response": model_response})
            session = store.create_protocol_auto_design_session(request_payload, access=access)
        except PermissionError as exc:
            raise _protocol_http_error(403, error_code="PROTOCOL_FORBIDDEN", message=str(exc)) from exc
        except ManagementClientError as exc:
            raise _protocol_http_error(exc.status_code, error_code=exc.error_code, message=exc.detail) from exc
        except ValidationError as exc:
            raise _protocol_http_error(400, error_code="PROTOCOL_AUTO_INVALID", message=str(exc)) from exc
        await broadcast_invalidations(topics=("protocols", f"protocol-auto-session:{session.session_id}"), reason="protocol.auto.created")
        return _json_payload(session)

    @router.get("/v1/protocol-auto/sessions/{session_id}")
    def resource_get_protocol_auto_session(
        session_id: str,
        auth: AuthContext = Depends(require_authenticated),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> dict[str, Any]:
        access = _auto_protocol_access(auth)
        try:
            session = store.get_protocol_auto_design_session(session_id, access=access)
        except PermissionError as exc:
            raise _protocol_http_error(403, error_code="PROTOCOL_FORBIDDEN", message=str(exc)) from exc
        except KeyError as exc:
            raise _protocol_http_error(404, error_code="PROTOCOL_AUTO_SESSION_NOT_FOUND", message="Auto Protocol session not found.") from exc
        return _json_payload(session)

    @router.get("/v1/protocol-auto/sessions/{session_id}/events")
    def resource_list_protocol_auto_session_events(
        session_id: str,
        auth: AuthContext = Depends(require_authenticated),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> dict[str, Any]:
        access = _auto_protocol_access(auth)
        try:
            events = store.list_protocol_auto_design_session_events(session_id, access=access)
        except PermissionError as exc:
            raise _protocol_http_error(403, error_code="PROTOCOL_FORBIDDEN", message=str(exc)) from exc
        return {"items": [item.model_dump(mode="json") for item in events]}

    @router.post("/v1/protocol-auto/sessions/{session_id}/revise")
    async def resource_revise_protocol_auto_session(
        session_id: str,
        payload: dict[str, Any] = Body(...),
        auth: AuthContext = Depends(require_authenticated),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise _protocol_http_error(400, error_code="PROTOCOL_AUTO_INVALID", message="Invalid Auto Protocol payload.")
        access = _auto_protocol_access(auth)
        try:
            existing = store.get_protocol_auto_design_session(session_id, access=access)
            request_payload = _auto_protocol_request({
                **payload,
                "mode": "revise",
                "target_protocol_id": payload.get("target_protocol_id") or existing.target_protocol_id,
                "source_document": existing.draft_definition_json.as_dict(),
            }, auth=auth, access=access, store=store, default_mode="revise")
            if not request_payload.source_document.as_dict():
                request_payload = request_payload.model_copy(update={"source_document": existing.draft_definition_json})
            model_response = await _auto_protocol_model_response(store, request_payload)
            request_payload = request_payload.model_copy(update={"model_response": model_response})
            revised = revise_auto_protocol_session(
                request_payload,
                session_id=existing.session_id,
                created_at=existing.created_at,
                updated_at=existing.updated_at,
            )
            session = store.update_protocol_auto_design_session(revised, access=access, event_kind="revised")
        except PermissionError as exc:
            raise _protocol_http_error(403, error_code="PROTOCOL_FORBIDDEN", message=str(exc)) from exc
        except ManagementClientError as exc:
            raise _protocol_http_error(exc.status_code, error_code=exc.error_code, message=exc.detail) from exc
        except KeyError as exc:
            raise _protocol_http_error(404, error_code="PROTOCOL_AUTO_SESSION_NOT_FOUND", message="Auto Protocol session not found.") from exc
        except ValidationError as exc:
            raise _protocol_http_error(400, error_code="PROTOCOL_AUTO_INVALID", message=str(exc)) from exc
        await broadcast_invalidations(topics=("protocols", f"protocol-auto-session:{session.session_id}"), reason="protocol.auto.revised")
        return _json_payload(session)

    @router.post("/v1/protocol-auto/sessions/{session_id}/apply")
    async def resource_apply_protocol_auto_session(
        session_id: str,
        auth: AuthContext = Depends(require_authenticated),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> dict[str, Any]:
        access = _auto_protocol_access(auth)
        try:
            session = store.get_protocol_auto_design_session(session_id, access=access)
            session = _apply_auto_protocol_session(store, session, access=access)
        except PermissionError as exc:
            raise _protocol_http_error(403, error_code="PROTOCOL_FORBIDDEN", message=str(exc)) from exc
        except KeyError as exc:
            raise _protocol_http_error(404, error_code="PROTOCOL_AUTO_SESSION_NOT_FOUND", message="Auto Protocol session not found.") from exc
        await broadcast_invalidations(topics=("protocols", f"protocol-auto-session:{session.session_id}"), reason="protocol.auto.applied")
        return _json_payload(session)

    @router.post("/v1/protocol-auto/sessions/{session_id}/publish")
    async def resource_publish_protocol_auto_session(
        session_id: str,
        auth: AuthContext = Depends(require_authenticated),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> dict[str, Any]:
        access = _auto_protocol_access(auth)
        try:
            session = store.get_protocol_auto_design_session(session_id, access=access)
            _ensure_auto_protocol_ready(session, action="publish")
            session = _ensure_auto_protocol_session_published(store, session, access=access)
        except PermissionError as exc:
            raise _protocol_http_error(403, error_code="PROTOCOL_FORBIDDEN", message=str(exc)) from exc
        except KeyError as exc:
            raise _protocol_http_error(404, error_code="PROTOCOL_AUTO_SESSION_NOT_FOUND", message="Auto Protocol session not found.") from exc
        await broadcast_invalidations(topics=("protocols", f"protocol-auto-session:{session.session_id}"), reason="protocol.auto.published")
        return _json_payload(session)

    @router.post("/v1/protocol-auto/sessions/{session_id}/run")
    async def resource_run_protocol_auto_session(
        session_id: str,
        payload: dict[str, Any] | None = Body(default=None),
        auth: AuthContext = Depends(require_authenticated),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> dict[str, Any]:
        payload = payload if isinstance(payload, dict) else {}
        access = _auto_protocol_access(auth)
        try:
            session = store.get_protocol_auto_design_session(session_id, access=access)
            _ensure_auto_protocol_ready(session, action="run")
            session = _ensure_auto_protocol_session_published(store, session, access=access)
            agents = _connected_agents(store)
            entry_agent_id = str(payload.get("entry_agent_id") or "").strip()
            if not entry_agent_id and auth.is_agent and auth.agent_id:
                entry_agent_id = str(auth.agent_id)
            if not entry_agent_id and agents:
                entry_agent_id = str(agents[0].get("agent_id") or "").strip()
            if not entry_agent_id:
                raise _protocol_http_error(
                    400,
                    error_code="PROTOCOL_AUTO_RUN_BLOCKED",
                    message="Choose an entry agent before running this generated protocol.",
                )
            run_payload = protocol_run_create_from_auto_session(
                session,
                protocol_id=session.target_protocol_id,
                entry_agent_id=entry_agent_id,
                root_conversation_id=str(payload.get("root_conversation_id") or ""),
                origin_channel=str(payload.get("origin_channel") or ("telegram" if auth.is_agent else "registry")),
            )
            result = store.create_protocol_run(
                run_payload,
                access=access,
                idempotency_key=str(payload.get("idempotency_key") or ""),
            )
            if not result.ok:
                raise _protocol_result_http_error(result)
            session = store.update_protocol_auto_design_session(
                session.model_copy(update={"status": "running", "run_result": result}),
                access=access,
                event_kind="run_started",
            )
        except PermissionError as exc:
            raise _protocol_http_error(403, error_code="PROTOCOL_FORBIDDEN", message=str(exc)) from exc
        except KeyError as exc:
            raise _protocol_http_error(404, error_code="PROTOCOL_AUTO_SESSION_NOT_FOUND", message="Auto Protocol session not found.") from exc
        await broadcast_invalidations(topics=("protocols", f"protocol-auto-session:{session.session_id}", "protocol-runs"), reason="protocol.auto.run_started")
        return _json_payload(session)

    @router.get("/v1/protocols")
    def resource_list_protocols(
        cursor: int = Query(default=0, ge=0),
        limit: int = Query(default=50, ge=1, le=200),
        lifecycle_state: str = Query(default=""),
        slug: str = Query(default=""),
        created_after: str = Query(default=""),
        auth: AuthContext = Depends(require_authenticated),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> list[dict[str, Any]]:
        try:
            return _json_payload(
                store.list_protocols(
                    access=protocol_access(auth),
                    cursor=cursor,
                    limit=limit,
                    lifecycle_state=lifecycle_state,
                    slug=slug,
                    created_after=created_after,
                )
            )
        except ValueError as exc:
            raise _protocol_http_error(400, error_code="PROTOCOL_INVALID_FILTER", message=str(exc)) from exc

    @router.get("/v1/protocol-authoring/options")
    def resource_get_protocol_authoring_options(
        auth: AuthContext = Depends(require_operator_session),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> dict[str, Any]:
        try:
            options = store.get_protocol_authoring_options(access=protocol_access(auth))
        except PermissionError as exc:
            raise _protocol_http_error(403, error_code="PROTOCOL_FORBIDDEN", message=str(exc)) from exc
        return _json_payload(options)

    @router.get("/v1/protocol-templates")
    def resource_list_protocol_templates(
        auth: AuthContext = Depends(require_operator_session),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> Any:
        return _json_payload(store.list_protocol_templates(access=protocol_access(auth)))

    @router.get("/v1/protocol-templates/{slug}")
    def resource_get_protocol_template(
        slug: str,
        auth: AuthContext = Depends(require_operator_session),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> dict[str, Any]:
        try:
            template = store.get_protocol_template(slug, access=protocol_access(auth))
        except PermissionError as exc:
            raise _protocol_http_error(403, error_code="PROTOCOL_NOT_VISIBLE", message="Protocol template is not visible to this actor.") from exc
        except KeyError as exc:
            raise _protocol_http_error(404, error_code="PROTOCOL_TEMPLATE_NOT_FOUND", message="Protocol template not found.") from exc
        return _json_payload(template)

    @router.post("/v1/protocol-templates")
    async def resource_create_protocol_template(
        payload: dict[str, Any] = Body(...),
        auth: AuthContext = Depends(require_operator_session),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise _protocol_http_error(400, error_code="PROTOCOL_INVALID", message="Invalid protocol template payload.")
        try:
            create_payload = ProtocolTemplateCreateRecord.model_validate(payload)
        except (ValidationError, ValueError) as exc:
            raise _protocol_http_error(400, error_code="PROTOCOL_INVALID", message=str(exc)) from exc
        result = store.publish_protocol_template(
            create_payload.source_protocol_id,
            access=protocol_access(auth),
            slug=create_payload.slug,
            display_name=create_payload.display_name,
            description=create_payload.description,
        )
        if not result.ok:
            raise _protocol_result_http_error(result)
        await broadcast_invalidations(topics=("protocols",), reason="protocol.template.published")
        return _json_payload(result)

    @router.get("/v1/protocols/{protocol_id}")
    def resource_get_protocol(
        protocol_id: str,
        auth: AuthContext = Depends(require_authenticated),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> dict[str, Any]:
        result = store.get_protocol(protocol_id, access=protocol_access(auth))
        if not result.ok:
            raise _protocol_result_http_error(result)
        return _json_payload(result)

    @router.get("/v1/protocols/{protocol_id}/versions/{version_id}")
    def resource_get_protocol_version(
        protocol_id: str,
        version_id: str,
        auth: AuthContext = Depends(require_authenticated),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> dict[str, Any]:
        try:
            version = store.get_protocol_version(protocol_id, version_id, access=protocol_access(auth))
        except PermissionError as exc:
            raise _protocol_http_error(403, error_code="PROTOCOL_NOT_VISIBLE", message="Protocol is not visible to this actor.") from exc
        except KeyError as exc:
            raise _protocol_http_error(404, error_code="PROTOCOL_VERSION_NOT_FOUND", message="Protocol version not found.") from exc
        return _json_payload(version)

    @router.post("/v1/protocols/parse")
    async def resource_parse_protocol_document(
        request: Request,
        auth: AuthContext = Depends(require_operator_session),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> dict[str, Any]:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise _protocol_http_error(400, error_code="PROTOCOL_INVALID", message="Invalid protocol payload.")
        try:
            parsed = store.parse_protocol_document_text(
                access=protocol_access(auth),
                definition_text=str(payload.get("definition_text", "") or ""),
                format=str(payload.get("format", "") or "json"),
                validation_mode=str(payload.get("validation_mode", "") or "strict"),
            )
        except PermissionError as exc:
            raise _protocol_http_error(403, error_code="PROTOCOL_FORBIDDEN", message=str(exc)) from exc
        except ValidationError as exc:
            raise _protocol_http_error(400, error_code="PROTOCOL_INVALID", message=str(exc)) from exc
        return _json_payload(parsed)

    @router.get("/v1/protocols/{protocol_id}/package/export")
    async def resource_export_protocol_package(
        protocol_id: str,
        format: str = Query(default="json"),
        revision: str = Query(default=""),
        auth: AuthContext = Depends(require_operator_session),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> dict[str, Any]:
        access = protocol_access(auth)
        normalized_format = _package_format(format)
        detail = store.get_protocol(protocol_id, access=access)
        if not detail.ok or detail.protocol is None:
            raise _protocol_result_http_error(detail)

        requested_revision = str(revision or "").strip().lower()
        version = detail.version
        use_published = requested_revision == "published" or (not requested_revision and version is not None)
        if use_published:
            if version is None:
                raise _protocol_http_error(
                    409,
                    error_code="PROTOCOL_PACKAGE_NO_PUBLISHED_VERSION",
                    message="This protocol has no published version to export.",
                )
            protocol_document = version.definition_json.as_dict()
            revision_scope = "published"
        else:
            protocol_document = detail.draft_definition_json.as_dict()
            revision_scope = "draft"

        required_skills = protocol_package_required_skill_names(protocol_document)
        agents = _connected_agents(store)
        source_agents_by_id: dict[str, dict[str, Any]] = {}
        skill_documents: list[dict[str, object]] = []
        skill_agent_id: dict[str, str] = {}
        warnings: list[dict[str, Any]] = []

        protocol_record = detail.protocol
        export_protocol_document = canonical_protocol_document(protocol_document)
        for skill_name in required_skills:
            preferred_ids = []
            for stage in export_protocol_document.stages:
                selector = stage.selector
                if (
                    selector is not None
                    and str(selector.kind or "").strip().lower() == "skill"
                    and str(selector.value or "").strip().lower() == skill_name
                    and str(selector.preferred_agent_id or "").strip()
                ):
                    preferred_ids.append(str(selector.preferred_agent_id or "").strip())
            candidates = []
            for preferred_id in preferred_ids:
                agent = _agent_by_id(agents, preferred_id)
                if agent is not None:
                    candidates.append(agent)
            if not candidates:
                candidates = _agents_for_skill(agents, skill_name)
            exported: list[tuple[dict[str, Any], dict[str, object], str]] = []
            for agent in candidates:
                try:
                    artifact = await export_catalog_skill_package(
                        store,
                        str(agent.get("agent_id", "") or ""),
                        skill_name,
                        revision_scope=revision_scope,
                        format="json",
                    )
                    document = skill_document_from_text(
                        str(artifact.get("document_text", "") or ""),
                        format=str(artifact.get("format", "") or "json"),
                    )
                    package_hash = skill_package_hash(skill_package_from_document(document))
                    exported.append((agent, document, package_hash))
                except Exception as exc:
                    warnings.append({
                        "code": "skill_export_failed",
                        "message": f"Could not export skill '{skill_name}' from {agent.get('display_name') or agent.get('slug') or agent.get('agent_id')}: {exc}",
                        "severity": "warning",
                        "blocking": False,
                    })
            if not exported:
                raise _protocol_http_error(
                    409,
                    error_code="PROTOCOL_PACKAGE_SKILL_MISSING",
                    message=f"Required skill '{skill_name}' could not be exported from any connected bot.",
                    details={"skill_name": skill_name, "candidates": candidates},
                )
            hashes = {item[2] for item in exported}
            if len(hashes) > 1:
                raise _protocol_http_error(
                    409,
                    error_code="PROTOCOL_PACKAGE_SKILL_AMBIGUOUS",
                    message=f"Required skill '{skill_name}' exists on multiple bots with different content. Choose a source bot before exporting.",
                    details={
                        "skill_name": skill_name,
                        "candidates": [
                            {**agent, "package_hash": package_hash}
                            for agent, _, package_hash in exported
                        ],
                    },
                )
            chosen_agent, chosen_document, _ = exported[0]
            skill_documents.append(chosen_document)
            skill_agent_id[skill_name] = str(chosen_agent.get("agent_id", "") or "")
            source_agents_by_id[str(chosen_agent.get("agent_id", "") or "")] = chosen_agent

        source_agent_keys = {
            agent_id: f"source-agent-{index + 1}"
            for index, agent_id in enumerate(sorted(source_agents_by_id))
        }
        source_agents = [
            {
                "source_agent_key": source_agent_keys[agent_id],
                "source_agent_id": agent_id,
                "slug": source_agents_by_id[agent_id].get("slug", ""),
                "display_name": source_agents_by_id[agent_id].get("display_name", ""),
                "provider": source_agents_by_id[agent_id].get("provider", ""),
                "role": source_agents_by_id[agent_id].get("role", ""),
                "advertised_skills": source_agents_by_id[agent_id].get("routing_skills", []),
            }
            for agent_id in sorted(source_agents_by_id)
        ]
        package_protocol = protocol_package_document(protocol=protocol_document, skills=skill_documents).protocol
        stage_bindings = []
        for stage in package_protocol.stages:
            selector = stage.selector
            required = []
            source_key = ""
            if selector is not None and str(selector.kind or "").strip().lower() == "skill":
                skill_name = str(selector.value or "").strip().lower()
                required = [skill_name] if skill_name else []
                agent_id = str(selector.preferred_agent_id or "").strip() or skill_agent_id.get(skill_name, "")
                source_key = source_agent_keys.get(agent_id, "")
            stage_bindings.append({
                "stage_key": stage.stage_key,
                "selector": selector.model_dump(mode="json") if selector is not None else None,
                "source_agent_key": source_key,
                "required_skills": required,
            })

        package = protocol_package_document(
            protocol=protocol_document,
            skills=skill_documents,
            bindings={
                "source_agents": source_agents,
                "stage_bindings": stage_bindings,
            },
            metadata={
                "source": "registry",
                "revision_scope": revision_scope,
                "protocol_id": protocol_record.protocol_id,
                "protocol_slug": protocol_record.slug,
            },
        )
        text = protocol_package_to_text(package, format=normalized_format)
        return _json_payload({
            "format": normalized_format,
            "file_name": _protocol_package_filename(protocol_record.slug, normalized_format),
            "content_type": "application/x-yaml" if normalized_format == "yaml" else "application/json",
            "text": text,
            "package": package,
            "package_hash": protocol_package_hash(package),
            "warnings": warnings,
        })

    async def _protocol_package_import_plan(
        *,
        store: AbstractRegistryStore,
        access: ProtocolAccessContextRecord,
        payload: dict[str, Any],
    ) -> ProtocolPackageImportPlanRecord:
        normalized_format = _package_format(payload.get("format", "json"))
        issues: list[ProtocolPackageIssueRecord] = []
        warnings: list[ProtocolPackageIssueRecord] = []
        try:
            package = protocol_package_from_text(str(payload.get("text", "") or ""), format=normalized_format)
        except Exception as exc:
            issue = ProtocolPackageIssueRecord(
                code="package.invalid",
                message=str(exc),
                severity="error",
                blocking=True,
            )
            return ProtocolPackageImportPlanRecord(
                ok=False,
                format=normalized_format,
                blocking_issues=[issue],
            )

        metadata = _protocol_metadata(package.protocol)
        slug = metadata["slug"]
        display_name = metadata["display_name"]
        existing_protocols = [
            item for item in store.list_protocols(access=access, limit=500, include_drafts=True)
            if str(item.slug or "").strip().lower() == slug.lower()
        ]
        existing = existing_protocols[0] if existing_protocols else None
        imported_hash = "sha256:" + protocol_definition_content_hash(package.protocol)
        identical = False
        if existing is not None:
            detail = store.get_protocol(existing.protocol_id, access=access)
            existing_hash = str(detail.validation.content_hash if detail.validation is not None else "" or "")
            identical = existing_hash in {imported_hash, imported_hash.replace("sha256:", "")}
        copy_slug, copy_name = _suggest_copy_identity(store, slug, display_name, access)
        protocol_plan = ProtocolPackageProtocolPlanRecord(
            slug=slug,
            display_name=display_name,
            exists=existing is not None,
            existing_protocol_id=str(existing.protocol_id if existing is not None else ""),
            identical_to_existing=identical,
            available_policies=["overwrite_existing", "import_copy", "fail_if_exists"] if existing is not None else ["create_new", "fail_if_exists"],
            suggested_copy_slug=copy_slug,
            suggested_copy_display_name=copy_name,
        )

        agents = _connected_agents(store)
        stage_choices = _stage_mapping_choices(payload)
        skill_choices = _skill_target_choices(payload)
        skill_plans: list[ProtocolPackageSkillPlanRecord] = []
        skill_docs_by_name: dict[str, dict[str, object]] = {}
        for item in package.skills:
            document = item.as_dict() if hasattr(item, "as_dict") else dict(item)
            skill_package = skill_package_from_document(document)
            skill_name = skill_package.skill_name
            skill_docs_by_name[skill_name] = document
            package_hash = skill_package_hash(skill_package)
            candidates = _agents_for_skill(agents, skill_name)
            target_agent_id = skill_choices.get(skill_name, "")
            candidate_rows: list[dict[str, Any]] = []
            matching_hash = False
            different_hash = False
            compare_agents = [_agent_by_id(agents, target_agent_id)] if target_agent_id else candidates
            for agent in [item for item in compare_agents if item is not None]:
                existing_hash = ""
                try:
                    artifact = await export_catalog_skill_package(
                        store,
                        str(agent.get("agent_id", "") or ""),
                        skill_name,
                        revision_scope="draft",
                        format="json",
                    )
                    existing_document = skill_document_from_text(
                        str(artifact.get("document_text", "") or ""),
                        format=str(artifact.get("format", "") or "json"),
                    )
                    existing_hash = skill_package_hash(skill_package_from_document(existing_document))
                    if existing_hash == package_hash:
                        matching_hash = True
                    else:
                        different_hash = True
                except Exception:
                    existing_hash = ""
                candidate_rows.append({**agent, "package_hash": existing_hash})
            if target_agent_id:
                status = "identical" if matching_hash else ("different_content" if different_hash else "missing")
            elif matching_hash:
                status = "identical"
                target_agent_id = str(candidate_rows[0].get("agent_id", "") or "") if len(candidate_rows) == 1 else ""
            elif candidates:
                status = "different_content" if different_hash else "available"
            else:
                status = "missing"
            skill_plans.append(
                ProtocolPackageSkillPlanRecord(
                    name=skill_name,
                    package_hash=package_hash,
                    status=status,
                    target_agent_id=target_agent_id,
                    candidates=[RegistryJsonRecord.model_validate(row) for row in candidate_rows or candidates],
                    message=(
                        "Skill content matches the selected bot."
                        if status == "identical"
                        else "Skill will be imported to the selected bot."
                    ),
                )
            )

        stage_plans: list[ProtocolPackageStageMappingPlanRecord] = []
        for stage in package.protocol.stages:
            selector = stage.selector
            if selector is None:
                continue
            kind = str(selector.kind or "").strip().lower()
            value = str(selector.value or "").strip()
            candidates: list[dict[str, Any]] = []
            target_agent_id = stage_choices.get(stage.stage_key, "")
            status = "unmapped"
            message = ""
            if kind == "skill":
                candidates = _agents_for_skill(agents, value)
                if target_agent_id:
                    status = "mapped"
                elif str(selector.preferred_agent_id or "").strip() and _agent_by_id(agents, selector.preferred_agent_id):
                    target_agent_id = str(selector.preferred_agent_id or "").strip()
                    status = "auto_resolved"
                elif len(candidates) == 1:
                    target_agent_id = str(candidates[0].get("agent_id", "") or "")
                    status = "auto_resolved"
                elif len(candidates) > 1:
                    status = "requires_mapping"
                    message = "Choose which bot should run this skill stage."
                else:
                    status = "requires_mapping"
                    message = "Choose a bot to receive the required skill."
            elif kind == "agent":
                lowered = value.lower()
                candidates = [
                    agent for agent in agents
                    if lowered in {
                        str(agent.get("agent_id", "") or "").lower(),
                        str(agent.get("slug", "") or "").lower(),
                        str(agent.get("display_name", "") or "").lower(),
                    }
                ]
                if target_agent_id:
                    status = "mapped"
                elif len(candidates) == 1:
                    target_agent_id = str(candidates[0].get("agent_id", "") or "")
                    status = "auto_resolved"
                else:
                    status = "requires_mapping"
                    message = "Choose the local bot for this agent assignment."
            elif kind == "role":
                lowered = value.lower()
                candidates = [
                    agent for agent in agents
                    if lowered and lowered in str(agent.get("role", "") or "").lower()
                ]
                if target_agent_id:
                    status = "mapped"
                elif len(candidates) == 1:
                    target_agent_id = str(candidates[0].get("agent_id", "") or "")
                    status = "auto_resolved"
                elif len(candidates) > 1:
                    status = "requires_mapping"
                    message = "Choose one bot so this role assignment is deterministic."
                else:
                    status = "requires_mapping"
                    message = "Choose the local bot for this role assignment."
            if status == "requires_mapping":
                issues.append(
                    ProtocolPackageIssueRecord(
                        code="stage.mapping_required",
                        message=f"Stage '{stage.display_name or stage.stage_key}' needs a target bot mapping.",
                        severity="error",
                        field_path=f"stages.{stage.stage_key}.selector",
                        blocking=True,
                    )
                )
            stage_plans.append(
                ProtocolPackageStageMappingPlanRecord(
                    stage_key=stage.stage_key,
                    selector=selector,
                    status=status,
                    target_agent_id=target_agent_id,
                    candidates=[RegistryJsonRecord.model_validate(row) for row in candidates],
                    message=message,
                )
            )

        if existing is not None:
            warnings.append(
                ProtocolPackageIssueRecord(
                    code="protocol.exists",
                    message=f"Protocol slug '{slug}' already exists. Choose overwrite draft or import as copy.",
                    severity="warning",
                    blocking=False,
                )
            )
        return ProtocolPackageImportPlanRecord(
            ok=not issues,
            format=normalized_format,
            package_hash=protocol_package_hash(package),
            protocol=protocol_plan,
            skills=skill_plans,
            stage_mappings=stage_plans,
            blocking_issues=issues,
            warnings=warnings,
        )

    @router.post("/v1/protocols/package/import/plan")
    async def resource_protocol_package_import_plan(
        request: Request,
        auth: AuthContext = Depends(require_operator_session),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> dict[str, Any]:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise _protocol_http_error(400, error_code="PROTOCOL_PACKAGE_INVALID", message="Invalid protocol package payload.")
        plan = await _protocol_package_import_plan(store=store, access=protocol_access(auth), payload=payload)
        return _json_payload(plan)

    @router.post("/v1/protocols/package/import/apply")
    async def resource_protocol_package_import_apply(
        request: Request,
        auth: AuthContext = Depends(require_operator_session),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> dict[str, Any]:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise _protocol_http_error(400, error_code="PROTOCOL_PACKAGE_INVALID", message="Invalid protocol package payload.")
        access = protocol_access(auth)
        plan = await _protocol_package_import_plan(store=store, access=access, payload=payload)
        if plan.blocking_issues:
            raise _protocol_http_error(
                409,
                error_code="PROTOCOL_PACKAGE_MAPPING_REQUIRED",
                message=plan.blocking_issues[0].message,
                details=plan.model_dump(mode="json"),
            )
        normalized_format = _package_format(payload.get("format", "json"))
        package = protocol_package_from_text(str(payload.get("text", "") or ""), format=normalized_format)
        stage_choices = {
            item.stage_key: item.target_agent_id
            for item in plan.stage_mappings
            if item.target_agent_id
        }
        stage_choices.update(_stage_mapping_choices(payload))
        skill_targets = _skill_target_choices(payload)
        skill_results: list[RegistryJsonRecord] = []
        for item in package.skills:
            document = item.as_dict() if hasattr(item, "as_dict") else dict(item)
            skill_package = skill_package_from_document(document)
            skill_name = skill_package.skill_name
            target_ids = {
                target
                for stage in package.protocol.stages
                if stage.selector is not None
                and str(stage.selector.kind or "").strip().lower() == "skill"
                and str(stage.selector.value or "").strip().lower() == skill_name
                for target in [stage_choices.get(stage.stage_key, "")]
                if target
            }
            explicit_target = skill_targets.get(skill_name, "")
            if explicit_target:
                target_ids.add(explicit_target)
            if not target_ids:
                raise _protocol_http_error(
                    409,
                    error_code="PROTOCOL_PACKAGE_SKILL_TARGET_REQUIRED",
                    message=f"Skill '{skill_name}' needs a target bot before import.",
                )
            document_text = skill_document_to_text(document, format="json")
            for agent_id in sorted(target_ids):
                try:
                    result = await import_catalog_skill_package(
                        store,
                        agent_id,
                        actor_key=getattr(auth, "actor_key", "") or getattr(auth, "subject", "") or "reg:registry-ui",
                        document_text=document_text,
                        format="json",
                        file_name=f"{skill_name}.skill.json",
                        target_skill_name=skill_name,
                    )
                    skill_results.append(RegistryJsonRecord.model_validate({"agent_id": agent_id, "skill_name": skill_name, "result": result}))
                except RegistryIngressError as exc:
                    raise _protocol_http_error(exc.status_code, error_code="PROTOCOL_PACKAGE_SKILL_IMPORT_FAILED", message=exc.detail) from exc

        rewritten_document = _copy_protocol_document_with_mappings(package, stage_choices)
        metadata = _protocol_metadata(package.protocol)
        policy = str(payload.get("protocol_policy", "") or "").strip().lower()
        if not policy:
            policy = "import_copy" if plan.protocol.exists else "create_new"
        protocol_id = ""
        slug = metadata["slug"]
        display_name = metadata["display_name"]
        if policy == "overwrite_existing":
            if not plan.protocol.existing_protocol_id:
                raise _protocol_http_error(409, error_code="PROTOCOL_PACKAGE_NO_EXISTING_PROTOCOL", message="No existing protocol was found to overwrite.")
            protocol_id = plan.protocol.existing_protocol_id
        elif policy == "import_copy":
            slug = str(payload.get("copy_slug", "") or plan.protocol.suggested_copy_slug).strip()
            display_name = str(payload.get("copy_display_name", "") or plan.protocol.suggested_copy_display_name).strip()
        elif policy in {"create_new", "fail_if_exists"}:
            if plan.protocol.exists:
                raise _protocol_http_error(409, error_code="PROTOCOL_PACKAGE_PROTOCOL_EXISTS", message="Protocol already exists.")
        else:
            raise _protocol_http_error(400, error_code="PROTOCOL_PACKAGE_POLICY_INVALID", message="Unsupported protocol import policy.")

        mutation = store.save_protocol_draft(
            access=access,
            protocol_id=protocol_id,
            slug=slug,
            display_name=display_name,
            description=metadata["description"],
            definition_json=RegistryJsonRecord.model_validate(rewritten_document),
            authoring_surface="operator",
        )
        if not mutation.ok:
            raise _protocol_result_http_error(mutation)
        if bool(payload.get("publish", False)):
            mutation = store.publish_protocol(mutation.protocol.protocol_id if mutation.protocol is not None else protocol_id, access=access)
            if not mutation.ok:
                raise _protocol_result_http_error(mutation)
        await broadcast_invalidations(topics=("protocols",), reason="protocol.package.imported")
        return _json_payload(
            ProtocolPackageImportApplyResultRecord(
                ok=True,
                status="applied",
                message="Protocol package imported.",
                protocol=mutation.protocol,
                mutation=mutation,
                plan=plan,
                skill_results=skill_results,
                mapping_results=[
                    RegistryJsonRecord.model_validate({"stage_key": key, "target_agent_id": value})
                    for key, value in sorted(stage_choices.items())
                ],
            )
        )

    @router.get("/v1/protocols/{protocol_id}/draft/export")
    def resource_export_protocol_draft(
        protocol_id: str,
        format: str = Query(default="json"),
        auth: AuthContext = Depends(require_operator_session),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> dict[str, Any]:
        try:
            exported = store.export_protocol_draft(protocol_id, access=protocol_access(auth), format=format)
        except PermissionError as exc:
            raise _protocol_http_error(403, error_code="PROTOCOL_NOT_VISIBLE", message=str(exc)) from exc
        except KeyError as exc:
            raise _protocol_http_error(404, error_code="PROTOCOL_NOT_FOUND", message="Protocol not found.") from exc
        except ValueError as exc:
            raise _protocol_http_error(400, error_code="PROTOCOL_INVALID_FORMAT", message=str(exc)) from exc
        return _json_payload(exported)

    @router.get("/v1/protocols/{protocol_id}/diff")
    def resource_diff_protocol_draft(
        protocol_id: str,
        format: str = Query(default="json"),
        auth: AuthContext = Depends(require_operator_session),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> dict[str, Any]:
        try:
            diff = store.diff_protocol_draft(protocol_id, access=protocol_access(auth), format=format)
        except PermissionError as exc:
            raise _protocol_http_error(403, error_code="PROTOCOL_NOT_VISIBLE", message=str(exc)) from exc
        except KeyError as exc:
            raise _protocol_http_error(404, error_code="PROTOCOL_VERSION_NOT_FOUND", message="Published protocol version not found.") from exc
        except ValueError as exc:
            raise _protocol_http_error(400, error_code="PROTOCOL_INVALID_FORMAT", message=str(exc)) from exc
        return _json_payload(diff)

    @router.post("/v1/protocols")
    async def resource_create_protocol(
        request: Request,
        authoring_surface: str | None = Header(default=None, alias="X-Protocol-Authoring-Surface"),
        auth: AuthContext = Depends(require_operator_session),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> dict[str, Any]:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise _protocol_http_error(400, error_code="PROTOCOL_INVALID", message="Invalid protocol payload.")
        result = store.save_protocol_draft(
            access=protocol_access(auth),
            protocol_id=str(payload.get("protocol_id", "") or ""),
            slug=str(payload.get("slug", "") or ""),
            display_name=str(payload.get("display_name", "") or ""),
            description=str(payload.get("description", "") or ""),
            definition_json=RegistryJsonRecord.model_validate(payload.get("definition_json", {})),
            authoring_surface=str(authoring_surface or ""),
        )
        if not result.ok:
            raise _protocol_result_http_error(result)
        await broadcast_invalidations(topics=("protocols",), reason="protocol.saved")
        return _json_payload(result)

    @router.post("/v1/protocol-drafts")
    async def resource_create_protocol_draft(
        payload: dict[str, Any] = Body(...),
        auth: AuthContext = Depends(require_operator_session),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise _protocol_http_error(400, error_code="PROTOCOL_INVALID", message="Invalid protocol payload.")
        try:
            create_payload = ProtocolDraftCreateRecord.model_validate(payload)
        except (ValidationError, ValueError) as exc:
            raise _protocol_http_error(400, error_code="PROTOCOL_INVALID", message=str(exc)) from exc
        result = store.create_protocol_draft(create_payload, access=protocol_access(auth))
        if not result.ok:
            raise _protocol_result_http_error(result)
        await broadcast_invalidations(topics=("protocols",), reason="protocol.saved")
        return _json_payload(result)

    @router.delete("/v1/protocols/{protocol_id}")
    async def resource_delete_protocol(
        protocol_id: str,
        auth: AuthContext = Depends(require_operator_session),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> dict[str, Any]:
        result = store.delete_protocol(protocol_id, access=protocol_access(auth))
        if not result.ok:
            raise _protocol_result_http_error(result)
        await broadcast_invalidations(topics=("protocols",), reason="protocol.deleted")
        return _json_payload(result)

    @router.put("/v1/protocols/{protocol_id}/draft")
    async def resource_save_protocol_draft(
        protocol_id: str,
        request: Request,
        if_match: str | None = Header(default=None, alias="If-Match"),
        authoring_surface: str | None = Header(default=None, alias="X-Protocol-Authoring-Surface"),
        auth: AuthContext = Depends(require_operator_session),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> dict[str, Any]:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise _protocol_http_error(400, error_code="PROTOCOL_INVALID", message="Invalid protocol payload.")
        expected_revision = _expected_draft_revision(if_match)
        result = store.save_protocol_draft(
            access=protocol_access(auth),
            protocol_id=protocol_id,
            slug=str(payload.get("slug", "") or ""),
            display_name=str(payload.get("display_name", "") or ""),
            description=str(payload.get("description", "") or ""),
            definition_json=RegistryJsonRecord.model_validate(payload.get("definition_json", {})),
            authoring_surface=str(authoring_surface or ""),
            expected_revision=expected_revision,
        )
        if not result.ok:
            raise _protocol_result_http_error(result)
        await broadcast_invalidations(topics=("protocols",), reason="protocol.saved")
        return _json_payload(result)

    @router.post("/v1/protocols/{protocol_id}/validate")
    async def resource_validate_protocol(
        protocol_id: str,
        auth: AuthContext = Depends(require_operator_session),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> dict[str, Any]:
        result = store.validate_protocol(protocol_id, access=protocol_access(auth))
        if not result.ok:
            raise _protocol_result_http_error(result)
        await broadcast_invalidations(topics=("protocols",), reason="protocol.validated")
        return _json_payload(result)

    @router.post("/v1/protocols/{protocol_id}/publish")
    async def resource_publish_protocol(
        protocol_id: str,
        auth: AuthContext = Depends(require_operator_session),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> dict[str, Any]:
        result = store.publish_protocol(protocol_id, access=protocol_access(auth))
        if not result.ok:
            raise _protocol_result_http_error(result)
        await broadcast_invalidations(topics=("protocols",), reason="protocol.published")
        return _json_payload(result)

    @router.post("/v1/protocols/{protocol_id}/archive")
    async def resource_archive_protocol(
        protocol_id: str,
        auth: AuthContext = Depends(require_operator_session),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> dict[str, Any]:
        result = store.archive_protocol(protocol_id, access=protocol_access(auth))
        if not result.ok:
            raise _protocol_result_http_error(result)
        await broadcast_invalidations(topics=("protocols",), reason="protocol.archived")
        return _json_payload(result)

    def _workspace_inventory_payload(row: dict[str, object] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        summary = row.get("summary_json") or {}
        return {
            "inventory_id": str(row.get("inventory_id") or ""),
            "agent_id": str(row.get("agent_id") or ""),
            "workspace_ref": str(row.get("workspace_ref") or ""),
            "protocol_run_id": str(row.get("protocol_run_id") or ""),
            "scan_status": str(row.get("scan_status") or ""),
            "file_count": int(row.get("file_count") or 0),
            "total_bytes": int(row.get("total_bytes") or 0),
            "retained_bytes": int(row.get("retained_bytes") or 0),
            "transient_bytes": int(row.get("transient_bytes") or 0),
            "unknown_bytes": int(row.get("unknown_bytes") or 0),
            "summary_json": summary,
            "created_at": str(row.get("created_at") or ""),
        }

    def _save_workspace_inventory(
        store: AbstractRegistryStore,
        *,
        access: ProtocolAccessContextRecord,
        agent_id: str,
        plan: WorkspaceCleanupPlanRecord,
        scan_status: str,
        inventory_id: str = "",
        result_payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        row_id = str(inventory_id or plan.inventory_id or uuid.uuid4().hex)
        summary = {
            "plan": plan.model_copy(update={"inventory_id": row_id, "agent_id": agent_id}).model_dump(mode="json"),
            "result": result_payload or {},
        }
        return store.save_workspace_cleanup_inventory(
            inventory_id=row_id,
            agent_id=agent_id,
            workspace_ref=plan.workspace_ref,
            protocol_run_id=plan.protocol_run_id,
            scan_status=scan_status,
            file_count=plan.file_count,
            total_bytes=plan.total_bytes,
            retained_bytes=plan.retained_bytes,
            transient_bytes=plan.transient_bytes,
            unknown_bytes=plan.unknown_bytes,
            summary=summary,
            access=access,
        )

    async def _workspace_usage_from_agent(
        *,
        store: AbstractRegistryStore,
        access: ProtocolAccessContextRecord,
        payload: dict[str, Any],
    ) -> tuple[str, WorkspaceUsageResult]:
        agent_id = _management_agent_id_for_operation(
            store,
            requested_agent_id=str(payload.get("agent_id") or ""),
            operation="workspace_usage",
        )
        result = await RegistryManagementClient(store).send(
            agent_id=agent_id,
            payload=WorkspaceUsageRequest(
                workspace_ref=str(payload.get("workspace_ref") or ""),
                protocol_run_id=str(payload.get("protocol_run_id") or ""),
                categories=[
                    str(item or "").strip()
                    for item in payload.get("categories", []) or []
                    if str(item or "").strip()
                ],
                older_than=str(payload.get("older_than") or ""),
                include_archived=bool(payload.get("include_archived") or False),
                include_failed=bool(payload.get("include_failed", True)),
                max_entries=int(payload.get("max_entries") or 250),
            ),
            timeout_seconds=45,
        )
        if not result.success or not isinstance(result.payload, WorkspaceUsageResult):
            raise _protocol_http_error(
                502,
                error_code="WORKSPACE_USAGE_FAILED",
                message=result.error_detail or "Workspace usage scan failed.",
            )
        plan = result.payload.plan.model_copy(update={"agent_id": agent_id})
        return agent_id, WorkspaceUsageResult(plan=plan)

    @router.get("/v1/admin/workspaces/usage")
    async def resource_get_workspace_usage(
        agent_id: str = Query(default=""),
        workspace_ref: str = Query(default=""),
        protocol_run_id: str = Query(default=""),
        category: list[str] = Query(default_factory=list),
        auth: AuthContext = Depends(require_operator_session),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> dict[str, Any]:
        access = protocol_access(auth)
        selected_agent_id, result = await _workspace_usage_from_agent(
            store=store,
            access=access,
            payload={
                "agent_id": agent_id,
                "workspace_ref": workspace_ref,
                "protocol_run_id": protocol_run_id,
                "categories": category,
            },
        )
        row = _save_workspace_inventory(
            store,
            access=access,
            agent_id=selected_agent_id,
            plan=result.plan,
            scan_status="completed",
        )
        return _json_payload({
            "plan": result.plan.model_copy(update={"inventory_id": row["inventory_id"], "agent_id": selected_agent_id}).model_dump(mode="json"),
            "inventory": _workspace_inventory_payload(row),
        })

    @router.post("/v1/admin/workspaces/cleanup/dry-run")
    async def resource_dry_run_workspace_cleanup(
        payload: dict[str, Any] | None = Body(default=None),
        auth: AuthContext = Depends(require_operator_session),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> dict[str, Any]:
        access = protocol_access(auth)
        selected_agent_id, result = await _workspace_usage_from_agent(
            store=store,
            access=access,
            payload=payload or {},
        )
        row = _save_workspace_inventory(
            store,
            access=access,
            agent_id=selected_agent_id,
            plan=result.plan,
            scan_status="dry_run",
        )
        plan = result.plan.model_copy(update={"inventory_id": row["inventory_id"], "agent_id": selected_agent_id})
        return _json_payload({"plan": plan.model_dump(mode="json"), "inventory": _workspace_inventory_payload(row)})

    @router.get("/v1/admin/workspaces/cleanup/jobs/{job_id}")
    def resource_get_workspace_cleanup_job(
        job_id: str,
        auth: AuthContext = Depends(require_operator_session),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> dict[str, Any]:
        try:
            row = store.get_workspace_cleanup_inventory(job_id, access=protocol_access(auth))
        except PermissionError as exc:
            raise _protocol_http_error(403, error_code="WORKSPACE_CLEANUP_FORBIDDEN", message=str(exc)) from exc
        if row is None:
            raise _protocol_http_error(404, error_code="WORKSPACE_CLEANUP_JOB_NOT_FOUND", message="Workspace cleanup job not found.")
        return _json_payload({"inventory": _workspace_inventory_payload(row)})

    @router.post("/v1/admin/workspaces/cleanup")
    async def resource_execute_workspace_cleanup(
        payload: dict[str, Any] | None = Body(default=None),
        auth: AuthContext = Depends(require_operator_session),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> dict[str, Any]:
        access = protocol_access(auth)
        body = payload or {}
        confirm = str(body.get("confirm") or "").strip().upper()
        if confirm != "CLEAN":
            raise _protocol_http_error(400, error_code="WORKSPACE_CLEANUP_CONFIRMATION_REQUIRED", message="Type CLEAN to confirm workspace cleanup.")
        plan_payload = body.get("plan") or {}
        if not plan_payload and str(body.get("job_id") or "").strip():
            row = store.get_workspace_cleanup_inventory(str(body.get("job_id") or "").strip(), access=access)
            summary = row.get("summary_json", {}) if row is not None else {}
            if isinstance(summary, dict):
                plan_payload = summary.get("plan") or {}
        plan = WorkspaceCleanupPlanRecord.model_validate(plan_payload)
        agent_id = _management_agent_id_for_operation(
            store,
            requested_agent_id=str(body.get("agent_id") or plan.agent_id or ""),
            operation="workspace_cleanup",
        )
        plan = plan.model_copy(update={"agent_id": agent_id})
        result = await RegistryManagementClient(store).send(
            agent_id=agent_id,
            payload=WorkspaceCleanupRequest(plan=plan, confirm=confirm),
            timeout_seconds=90,
        )
        if not result.success or not isinstance(result.payload, WorkspaceCleanupResult):
            raise _protocol_http_error(
                502,
                error_code="WORKSPACE_CLEANUP_FAILED",
                message=result.error_detail or "Workspace cleanup failed.",
            )
        row = _save_workspace_inventory(
            store,
            access=access,
            agent_id=agent_id,
            plan=result.payload.plan,
            scan_status="executed",
            inventory_id=plan.inventory_id,
            result_payload={
                "removed_paths": result.payload.removed_paths,
                "removed_bytes": result.payload.removed_bytes,
                "failures": result.payload.failures,
            },
        )
        await broadcast_invalidations(topics=("summary", "protocols"), reason="admin.workspace_cleanup.executed")
        return _json_payload({
            "plan": result.payload.plan.model_copy(update={"inventory_id": row["inventory_id"], "agent_id": agent_id}).model_dump(mode="json"),
            "removed_paths": result.payload.removed_paths,
            "removed_bytes": result.payload.removed_bytes,
            "failures": result.payload.failures,
            "inventory": _workspace_inventory_payload(row),
        })

    @router.get("/v1/protocol-runs")
    def resource_list_protocol_runs(
        cursor: int = Query(default=0, ge=0),
        limit: int = Query(default=25, ge=1, le=100),
        status: str = Query(default=""),
        protocol_id: str = Query(default=""),
        entry_agent_id: str = Query(default=""),
        root_conversation_id: str = Query(default=""),
        origin_channel: str = Query(default=""),
        include_generated: bool = Query(default=True),
        auth: AuthContext = Depends(require_authenticated),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> dict[str, Any]:
        runs = store.list_protocol_runs(
            access=protocol_access(auth),
            limit=limit,
            cursor=cursor,
            status=status,
            protocol_id=protocol_id,
            entry_agent_id=entry_agent_id,
            root_conversation_id=root_conversation_id,
            origin_channel=origin_channel,
            include_generated=include_generated,
        )
        return _json_payload(_paginated_response("runs", runs, cursor, limit))

    @router.get("/v1/protocol-runs/issues")
    def resource_list_protocol_issues(
        cursor: int = Query(default=0, ge=0),
        limit: int = Query(default=25, ge=1, le=100),
        issue_kind: str = Query(default=""),
        protocol_run_id: str = Query(default=""),
        protocol_id: str = Query(default=""),
        auth: AuthContext = Depends(require_operator_session),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> dict[str, Any]:
        issues = store.list_protocol_issues(
            access=protocol_access(auth),
            limit=limit,
            cursor=cursor,
            issue_kind=issue_kind,
            protocol_run_id=protocol_run_id,
            protocol_id=protocol_id,
        )
        return _json_payload(_paginated_response("issues", issues, cursor, limit))

    @router.post("/v1/protocol-runs")
    async def resource_create_protocol_run(
        payload: ProtocolRunCreateRecord,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        auth: AuthContext = Depends(require_authenticated),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> dict[str, Any]:
        request_payload = payload
        if payload.is_rehearsal and not str(payload.entry_agent_id or "").strip():
            rehearsal_manager = get_rehearsal_manager()
            rehearsal_agent_id = str(rehearsal_manager.agent_id or "").strip()
            if not rehearsal_agent_id:
                rehearsal_agent_id, _ = rehearsal_manager.ensure_agent()
                rehearsal_agent_id = str(rehearsal_agent_id or "").strip()
            if not rehearsal_agent_id:
                raise _protocol_http_error(
                    503,
                    error_code="PROTOCOL_REHEARSAL_UNAVAILABLE",
                    message="Rehearsal participant is unavailable right now.",
                )
            request_payload = payload.model_copy(update={"entry_agent_id": rehearsal_agent_id})
        result = store.create_protocol_run(
            request_payload,
            access=protocol_access(auth),
            idempotency_key=str(idempotency_key or "").strip(),
        )
        if not result.ok:
            raise _protocol_result_http_error(result)
        topics = {"protocols", "summary"}
        if result.run is not None:
            topics.add(f"protocol-run:{result.run.protocol_run_id}")
        await broadcast_invalidations(topics=topics, reason="protocol.run.created")
        if result.run is not None:
            await broadcast_topic_event(
                run_id=result.run.protocol_run_id,
                event_kind="protocol_run.updated",
                reason="protocol.run.created",
            )
        return _json_payload(result)

    @router.get("/v1/protocol-runs/{run_id}")
    def resource_get_protocol_run(
        run_id: str,
        auth: AuthContext = Depends(require_authenticated),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> dict[str, Any]:
        try:
            detail = store.get_protocol_run(run_id, access=protocol_access(auth))
        except PermissionError as exc:
            raise _protocol_http_error(403, error_code="PROTOCOL_NOT_VISIBLE", message="Protocol run is not visible to this actor.") from exc
        except KeyError as exc:
            raise _protocol_http_error(404, error_code="PROTOCOL_RUN_NOT_FOUND", message="Protocol run not found.") from exc
        return _json_payload(detail)

    @router.get("/v1/protocol-runs/{run_id}/participants")
    def resource_get_protocol_run_participants(
        run_id: str,
        auth: AuthContext = Depends(require_authenticated),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> dict[str, Any]:
        try:
            participants = store.get_protocol_run_participants(run_id, access=protocol_access(auth))
        except PermissionError as exc:
            raise _protocol_http_error(403, error_code="PROTOCOL_NOT_VISIBLE", message="Protocol run is not visible to this actor.") from exc
        except KeyError as exc:
            raise _protocol_http_error(404, error_code="PROTOCOL_RUN_NOT_FOUND", message="Protocol run not found.") from exc
        return _json_payload({"participants": participants})

    @router.get("/v1/protocol-runs/{run_id}/artifacts")
    def resource_get_protocol_run_artifacts(
        run_id: str,
        auth: AuthContext = Depends(require_authenticated),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> dict[str, Any]:
        try:
            artifacts = store.get_protocol_run_artifacts(run_id, access=protocol_access(auth))
        except PermissionError as exc:
            raise _protocol_http_error(403, error_code="PROTOCOL_NOT_VISIBLE", message="Protocol run is not visible to this actor.") from exc
        except KeyError as exc:
            raise _protocol_http_error(404, error_code="PROTOCOL_RUN_NOT_FOUND", message="Protocol run not found.") from exc
        return _json_payload({"artifacts": artifacts})

    @router.get("/v1/protocol-runs/{run_id}/artifacts/{artifact_key}/content")
    @router.get("/v1/protocol-runs/{run_id}/artifacts/{artifact_key}/content/{member_path_tail:path}")
    def resource_get_protocol_run_artifact_content(
        request: Request,
        run_id: str,
        artifact_key: str,
        member_path_tail: str = "",
        download: bool = Query(default=False),
        browse: bool = Query(default=False),
        preview: bool = Query(default=False),
        member_path: str = Query(default="", alias="path"),
        auth: AuthContext = Depends(require_authenticated),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> Response:
        try:
            detail = store.get_protocol_run(run_id, access=protocol_access(auth))
        except PermissionError as exc:
            raise _protocol_http_error(403, error_code="PROTOCOL_NOT_VISIBLE", message="Protocol run is not visible to this actor.") from exc
        except KeyError as exc:
            raise _protocol_http_error(404, error_code="PROTOCOL_RUN_NOT_FOUND", message="Protocol run not found.") from exc
        artifact = next(
            (item for item in detail.artifacts if str(item.artifact_key or "").strip() == str(artifact_key or "").strip()),
            None,
        )
        if artifact is None:
            raise _protocol_http_error(404, error_code="PROTOCOL_ARTIFACT_NOT_FOUND", message="Protocol artifact not found.")
        resolved_path = resolve_protocol_artifact_path(detail, artifact)
        preferred_name = artifact_download_name(
            artifact_key=str(artifact.artifact_key or ""),
            preferred_path=str(artifact.workspace_path or artifact.location or ""),
        )
        media_type = mimetypes.guess_type(preferred_name)[0] or "application/octet-stream"
        if resolved_path is None:
            snapshot = store.get_protocol_artifact_snapshot(run_id, artifact.artifact_key, access=protocol_access(auth))
            snapshot_path = _artifact_snapshot_path(snapshot) if snapshot is not None else None
            if snapshot_path is not None and snapshot_path.exists():
                return workspace_artifact_content_response(
                    resolved_path=snapshot_path,
                    artifact_key=str(artifact.artifact_key or artifact_key or ""),
                    preferred_path=str(artifact.workspace_path or artifact.location or ""),
                    preferred_name=preferred_name,
                    download=download,
                    browse=browse,
                    preview=preview,
                    member_path=member_path or member_path_tail,
                    request=request,
                )
            content_text = resolve_protocol_artifact_rehearsal_text(detail, artifact)
            if content_text:
                if preview and not download:
                    return rendered_artifact_text_preview_response(
                        content_text,
                        artifact_key=str(artifact.artifact_key or artifact_key or ""),
                        preferred_name=preferred_name,
                    )
                disposition = "attachment" if download else "inline"
                return Response(
                    content=content_text.encode("utf-8"),
                    media_type=media_type,
                    headers={"Content-Disposition": f'{disposition}; filename="{preferred_name}"'},
                )
            raise _protocol_http_error(
                409,
                error_code="PROTOCOL_ARTIFACT_PATH_UNAVAILABLE",
                message="Artifact path is not available on this host.",
                details={
                    "artifact_key": artifact.artifact_key,
                    "workspace_path": artifact.workspace_path,
                    "location": artifact.location,
                },
            )
        return workspace_artifact_content_response(
            resolved_path=resolved_path,
            artifact_key=str(artifact.artifact_key or artifact_key or ""),
            preferred_path=str(artifact.workspace_path or artifact.location or ""),
            preferred_name=preferred_name,
            download=download,
            browse=browse,
            preview=preview,
            member_path=member_path or member_path_tail,
            request=request,
        )

    @router.get("/v1/protocol-runs/{run_id}/artifacts/{artifact_key}/snapshot")
    def resource_get_protocol_run_artifact_snapshot(
        run_id: str,
        artifact_key: str,
        auth: AuthContext = Depends(require_authenticated),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> dict[str, Any]:
        access = protocol_access(auth)
        try:
            detail = store.get_protocol_run(run_id, access=access)
            artifact = _artifact_for_detail(detail, artifact_key)
        except PermissionError as exc:
            raise _protocol_http_error(403, error_code="PROTOCOL_NOT_VISIBLE", message="Protocol run is not visible to this actor.") from exc
        except KeyError as exc:
            raise _protocol_http_error(404, error_code="PROTOCOL_RUN_NOT_FOUND", message="Protocol run not found.") from exc
        snapshot = store.get_protocol_artifact_snapshot(run_id, artifact.artifact_key, access=access)
        snapshot_path = _artifact_snapshot_path(snapshot) if snapshot is not None else None
        return _json_payload({
            "snapshot": _artifact_snapshot_payload(snapshot) if snapshot is not None else None,
            "available": bool(snapshot_path is not None and snapshot_path.exists()),
            "content_url": f"/v1/protocol-runs/{run_id}/artifacts/{artifact.artifact_key}/snapshot/content" if snapshot is not None else "",
        })

    @router.post("/v1/protocol-runs/{run_id}/artifacts/{artifact_key}/snapshot")
    def resource_create_protocol_run_artifact_snapshot(
        run_id: str,
        artifact_key: str,
        auth: AuthContext = Depends(require_authenticated),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> dict[str, Any]:
        access = protocol_access(auth)
        try:
            detail = store.get_protocol_run(run_id, access=access)
            artifact = _artifact_for_detail(detail, artifact_key)
        except PermissionError as exc:
            raise _protocol_http_error(403, error_code="PROTOCOL_NOT_VISIBLE", message="Protocol run is not visible to this actor.") from exc
        except KeyError as exc:
            raise _protocol_http_error(404, error_code="PROTOCOL_RUN_NOT_FOUND", message="Protocol run not found.") from exc
        resolved_path = resolve_protocol_artifact_path(detail, artifact)
        if resolved_path is None or not resolved_path.exists():
            raise _protocol_http_error(
                409,
                error_code="PROTOCOL_ARTIFACT_PATH_UNAVAILABLE",
                message="Artifact path is not available on this host, so it cannot be snapshotted.",
                details={"artifact_key": artifact.artifact_key, "workspace_path": artifact.workspace_path, "location": artifact.location},
            )
        snapshot = create_artifact_snapshot(
            artifact_store_dir=load_registry_config().artifact_store_dir,
            source_path=resolved_path,
            protocol_artifact_id=artifact.protocol_artifact_id,
            protocol_run_id=run_id,
            artifact_key=artifact.artifact_key,
            created_by=access.actor_ref,
            retention_until=detail.run.retention_until,
        )
        saved = store.save_protocol_artifact_snapshot(snapshot, access=access)
        return _json_payload({"snapshot": _artifact_snapshot_payload(saved)})

    @router.get("/v1/protocol-runs/{run_id}/artifacts/{artifact_key}/snapshot/content")
    @router.get("/v1/protocol-runs/{run_id}/artifacts/{artifact_key}/snapshot/content/{member_path_tail:path}")
    def resource_get_protocol_run_artifact_snapshot_content(
        request: Request,
        run_id: str,
        artifact_key: str,
        member_path_tail: str = "",
        download: bool = Query(default=False),
        browse: bool = Query(default=False),
        preview: bool = Query(default=False),
        member_path: str = Query(default="", alias="path"),
        auth: AuthContext = Depends(require_authenticated),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> Response:
        access = protocol_access(auth)
        try:
            detail = store.get_protocol_run(run_id, access=access)
            artifact = _artifact_for_detail(detail, artifact_key)
        except PermissionError as exc:
            raise _protocol_http_error(403, error_code="PROTOCOL_NOT_VISIBLE", message="Protocol run is not visible to this actor.") from exc
        except KeyError as exc:
            raise _protocol_http_error(404, error_code="PROTOCOL_RUN_NOT_FOUND", message="Protocol run not found.") from exc
        snapshot = store.get_protocol_artifact_snapshot(run_id, artifact.artifact_key, access=access)
        snapshot_path = _artifact_snapshot_path(snapshot) if snapshot is not None else None
        if snapshot is None or snapshot_path is None or not snapshot_path.exists():
            raise _protocol_http_error(404, error_code="PROTOCOL_ARTIFACT_SNAPSHOT_NOT_FOUND", message="Artifact snapshot not found.")
        return workspace_artifact_content_response(
            resolved_path=snapshot_path,
            artifact_key=str(artifact.artifact_key or artifact_key or ""),
            preferred_path=str(artifact.workspace_path or artifact.location or ""),
            preferred_name=artifact_download_name(
                artifact_key=str(artifact.artifact_key or ""),
                preferred_path=str(artifact.workspace_path or artifact.location or ""),
            ),
            download=download,
            browse=browse,
            preview=preview,
            member_path=member_path or member_path_tail,
            request=request,
        )

    @router.delete("/v1/protocol-runs/{run_id}/artifacts/{artifact_key}/snapshot")
    def resource_delete_protocol_run_artifact_snapshot(
        run_id: str,
        artifact_key: str,
        auth: AuthContext = Depends(require_operator_session),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> dict[str, Any]:
        try:
            deleted = store.delete_protocol_artifact_snapshot(
                run_id,
                artifact_key,
                access=protocol_access(auth),
            )
        except PermissionError as exc:
            raise _protocol_http_error(403, error_code="PROTOCOL_SNAPSHOT_FORBIDDEN", message=str(exc)) from exc
        except KeyError as exc:
            raise _protocol_http_error(404, error_code="PROTOCOL_ARTIFACT_SNAPSHOT_NOT_FOUND", message="Artifact snapshot not found.") from exc
        return _json_payload({"snapshot": _artifact_snapshot_payload(deleted)})

    @router.get("/v1/protocol-runs/{run_id}/artifacts/{artifact_key}/runtime")
    def resource_get_protocol_artifact_runtime(
        run_id: str,
        artifact_key: str,
        auth: AuthContext = Depends(require_authenticated),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> dict[str, Any]:
        access = protocol_access(auth)
        try:
            detail = store.get_protocol_run(run_id, access=access)
            artifact = _artifact_for_detail(detail, artifact_key)
        except PermissionError as exc:
            raise _protocol_http_error(403, error_code="PROTOCOL_NOT_VISIBLE", message="Protocol run is not visible to this actor.") from exc
        except KeyError as exc:
            raise _protocol_http_error(404, error_code="PROTOCOL_RUN_NOT_FOUND", message="Protocol run not found.") from exc
        resolved_path = resolve_protocol_artifact_path(detail, artifact)
        if resolved_path is None:
            snapshot = store.get_protocol_artifact_snapshot(run_id, artifact.artifact_key, access=access)
            snapshot_path = _artifact_snapshot_path(snapshot) if snapshot is not None else None
            if snapshot_path is not None and snapshot_path.exists():
                resolved_path = snapshot_path
        manifest, manifest_path = (None, "")
        if resolved_path is not None:
            manifest, manifest_path = _runtime_manifest_from_path(resolved_path)
        runtime = store.get_protocol_artifact_runtime(run_id, artifact.artifact_key, access=access)
        if runtime is None:
            urls = _runtime_public_urls(run_id, artifact.artifact_key)
            runtime = ProtocolArtifactRuntimeInstanceRecord(
                runtime_instance_id=_runtime_instance_id(run_id, artifact.artifact_key),
                protocol_run_id=run_id,
                artifact_key=artifact.artifact_key,
                agent_id=_runtime_agent_id(detail, artifact),
                status="stopped" if manifest is not None else "not_configured",
                manifest=manifest,
                manifest_path=manifest_path,
                artifact_path=str(resolved_path or ""),
                **urls,
            )
        return {
            "runtime": _runtime_record_json(runtime),
            "manifest_available": manifest is not None or runtime.manifest is not None,
            "package_url": f"/v1/protocol-runs/{run_id}/artifacts/{artifact.artifact_key}/content?download=1",
            "browse_url": f"/v1/protocol-runs/{run_id}/artifacts/{artifact.artifact_key}/content?browse=1",
        }

    @router.post("/v1/protocol-runs/{run_id}/artifacts/{artifact_key}/runtime/start")
    async def resource_start_protocol_artifact_runtime(
        run_id: str,
        artifact_key: str,
        auth: AuthContext = Depends(require_authenticated),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> dict[str, Any]:
        access = protocol_access(auth)
        try:
            detail = store.get_protocol_run(run_id, access=access)
            artifact = _artifact_for_detail(detail, artifact_key)
        except PermissionError as exc:
            raise _protocol_http_error(403, error_code="PROTOCOL_NOT_VISIBLE", message="Protocol run is not visible to this actor.") from exc
        except KeyError as exc:
            raise _protocol_http_error(404, error_code="PROTOCOL_RUN_NOT_FOUND", message="Protocol run not found.") from exc
        resolved_path = resolve_protocol_artifact_path(detail, artifact)
        if resolved_path is None:
            snapshot = store.get_protocol_artifact_snapshot(run_id, artifact.artifact_key, access=access)
            snapshot_path = _artifact_snapshot_path(snapshot) if snapshot is not None else None
            if snapshot_path is not None and snapshot_path.exists():
                resolved_path = snapshot_path
        if resolved_path is None:
            raise _protocol_http_error(
                409,
                error_code="PROTOCOL_ARTIFACT_PATH_UNAVAILABLE",
                message="Artifact path is not available on this host.",
                details={"artifact_key": artifact.artifact_key},
            )
        manifest, manifest_path = _runtime_manifest_from_path(resolved_path)
        if manifest is None:
            raise _protocol_http_error(
                409,
                error_code="PROTOCOL_ARTIFACT_RUNTIME_MANIFEST_MISSING",
                message="This artifact does not declare a runnable app or API. You can still browse or download the package.",
            )
        agent_id = _runtime_agent_id(detail, artifact)
        if not agent_id:
            raise _protocol_http_error(
                409,
                error_code="PROTOCOL_ARTIFACT_RUNTIME_AGENT_UNAVAILABLE",
                message="No connected agent is available to run this artifact.",
            )
        runtime_id = _runtime_instance_id(run_id, artifact.artifact_key)
        urls = _runtime_public_urls(run_id, artifact.artifact_key)
        starting = ProtocolArtifactRuntimeInstanceRecord(
            runtime_instance_id=runtime_id,
            protocol_run_id=run_id,
            artifact_key=artifact.artifact_key,
            agent_id=agent_id,
            status="starting",
            manifest=manifest,
            manifest_path=manifest_path,
            artifact_path=str(resolved_path),
            started_by=access.actor_ref,
            **urls,
        )
        store.save_protocol_artifact_runtime(starting, access=access)
        store.append_protocol_artifact_runtime_event(
            _runtime_event(
                runtime=starting,
                event_kind="start_requested",
                actor_ref=access.actor_ref,
                summary="Runtime start requested.",
                metadata={"agent_id": agent_id},
            ),
            access=access,
        )
        try:
            result = await RegistryManagementClient(store).send(
                agent_id=agent_id,
                payload=StartArtifactRuntimeRequest(
                    runtime_instance_id=runtime_id,
                    protocol_run_id=run_id,
                    artifact_key=artifact.artifact_key,
                    artifact_path=str(resolved_path),
                    manifest_path=manifest_path,
                    manifest=manifest,
                    actor_ref=access.actor_ref,
                ),
                timeout_seconds=int(manifest.startup_timeout_seconds or 30) + 20,
            )
        except ManagementClientError as exc:
            failed = starting.model_copy(
                update={
                    "status": "failed",
                    "failure_code": exc.error_code,
                    "failure_detail": exc.detail,
                }
            )
            store.save_protocol_artifact_runtime(failed, access=access)
            store.append_protocol_artifact_runtime_event(
                _runtime_event(
                    runtime=failed,
                    event_kind="failed",
                    actor_ref=access.actor_ref,
                    summary=exc.detail,
                    metadata={"error_code": exc.error_code},
                ),
                access=access,
            )
            raise _protocol_http_error(exc.status_code, error_code=exc.error_code, message=exc.detail) from exc
        if not result.success or not isinstance(result.payload, StartArtifactRuntimeResult):
            detail_text = result.error_detail or "Bot failed to start artifact runtime."
            failed = starting.model_copy(update={"status": "failed", "failure_code": result.error_code, "failure_detail": detail_text})
            store.save_protocol_artifact_runtime(failed, access=access)
            store.append_protocol_artifact_runtime_event(
                _runtime_event(
                    runtime=failed,
                    event_kind="failed",
                    actor_ref=access.actor_ref,
                    summary=detail_text,
                    metadata={"error_code": result.error_code},
                ),
                access=access,
            )
            raise _protocol_http_error(502, error_code="PROTOCOL_ARTIFACT_RUNTIME_START_FAILED", message=detail_text)
        runtime = result.payload.result.runtime or starting
        runtime = runtime.model_copy(
            update={
                "agent_id": agent_id,
                "manifest": manifest,
                "manifest_path": manifest_path,
                "artifact_path": str(resolved_path),
                **urls,
            }
        )
        saved = store.save_protocol_artifact_runtime(runtime, access=access)
        store.append_protocol_artifact_runtime_event(
            _runtime_event(
                runtime=saved,
                event_kind="started" if result.payload.result.ok else "failed",
                actor_ref=access.actor_ref,
                summary=result.payload.result.message,
                metadata={"status": result.payload.result.status},
            ),
            access=access,
        )
        return _json_payload(result.payload.result.model_copy(update={"runtime": saved}))

    @router.post("/v1/protocol-runs/{run_id}/artifacts/{artifact_key}/runtime/stop")
    async def resource_stop_protocol_artifact_runtime(
        run_id: str,
        artifact_key: str,
        auth: AuthContext = Depends(require_authenticated),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> dict[str, Any]:
        access = protocol_access(auth)
        runtime = store.get_protocol_artifact_runtime(run_id, artifact_key, access=access)
        if runtime is None:
            raise _protocol_http_error(404, error_code="PROTOCOL_ARTIFACT_RUNTIME_NOT_FOUND", message="Artifact runtime not found.")
        store.append_protocol_artifact_runtime_event(
            _runtime_event(
                runtime=runtime,
                event_kind="stop_requested",
                actor_ref=access.actor_ref,
                summary="Runtime stop requested.",
            ),
            access=access,
        )
        result = await RegistryManagementClient(store).send(
            agent_id=runtime.agent_id,
            payload=StopArtifactRuntimeRequest(
                runtime_instance_id=runtime.runtime_instance_id,
                protocol_run_id=run_id,
                artifact_key=artifact_key,
                actor_ref=access.actor_ref,
            ),
            timeout_seconds=30,
        )
        if not result.success or not isinstance(result.payload, StopArtifactRuntimeResult):
            raise _protocol_http_error(502, error_code="PROTOCOL_ARTIFACT_RUNTIME_STOP_FAILED", message=result.error_detail or "Bot failed to stop artifact runtime.")
        stopped = result.payload.result.runtime or runtime
        saved = store.save_protocol_artifact_runtime(_merge_runtime_record(runtime, stopped), access=access)
        store.append_protocol_artifact_runtime_event(
            _runtime_event(
                runtime=saved,
                event_kind="stopped",
                actor_ref=access.actor_ref,
                summary=result.payload.result.message,
            ),
            access=access,
        )
        return _json_payload(result.payload.result.model_copy(update={"runtime": saved}))

    @router.post("/v1/protocol-runs/{run_id}/artifacts/{artifact_key}/runtime/archive")
    def resource_archive_protocol_artifact_runtime(
        run_id: str,
        artifact_key: str,
        auth: AuthContext = Depends(require_authenticated),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> dict[str, Any]:
        access = protocol_access(auth)
        runtime = store.get_protocol_artifact_runtime(run_id, artifact_key, access=access)
        if runtime is None:
            raise _protocol_http_error(404, error_code="PROTOCOL_ARTIFACT_RUNTIME_NOT_FOUND", message="Artifact runtime not found.")
        if str(runtime.status or "").lower() == "running":
            raise _protocol_http_error(
                409,
                error_code="PROTOCOL_ARTIFACT_RUNTIME_STILL_RUNNING",
                message="Stop the artifact runtime before archiving it.",
            )
        archived = runtime.model_copy(update={"status": "archived", "updated_at": ""})
        saved = store.save_protocol_artifact_runtime(archived, access=access)
        event = store.append_protocol_artifact_runtime_event(
            _runtime_event(runtime=saved, event_kind="archived", actor_ref=access.actor_ref, summary="Runtime archived."),
            access=access,
        )
        return _json_payload({"runtime": saved, "event": event})

    @router.delete("/v1/protocol-runs/{run_id}/artifacts/{artifact_key}/runtime")
    def resource_delete_protocol_artifact_runtime(
        run_id: str,
        artifact_key: str,
        auth: AuthContext = Depends(require_authenticated),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> dict[str, Any]:
        access = protocol_access(auth)
        runtime = store.get_protocol_artifact_runtime(run_id, artifact_key, access=access)
        if runtime is None:
            raise _protocol_http_error(404, error_code="PROTOCOL_ARTIFACT_RUNTIME_NOT_FOUND", message="Artifact runtime not found.")
        if str(runtime.status or "").lower() == "running":
            raise _protocol_http_error(
                409,
                error_code="PROTOCOL_ARTIFACT_RUNTIME_STILL_RUNNING",
                message="Stop the artifact runtime before deleting it.",
            )
        deleted = runtime.model_copy(update={"status": "deleted", "updated_at": ""})
        saved = store.save_protocol_artifact_runtime(deleted, access=access)
        event = store.append_protocol_artifact_runtime_event(
            _runtime_event(runtime=saved, event_kind="deleted", actor_ref=access.actor_ref, summary="Runtime deleted."),
            access=access,
        )
        return _json_payload({"runtime": saved, "event": event})

    @router.get("/v1/protocol-runs/{run_id}/artifacts/{artifact_key}/runtime/events")
    def resource_list_protocol_artifact_runtime_events(
        run_id: str,
        artifact_key: str,
        limit: int = Query(default=50, ge=1, le=200),
        auth: AuthContext = Depends(require_authenticated),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> dict[str, Any]:
        events = store.list_protocol_artifact_runtime_events(
            run_id,
            artifact_key,
            access=protocol_access(auth),
            limit=limit,
        )
        return _json_payload({"items": events})

    @router.get("/v1/protocol-runs/{run_id}/artifacts/{artifact_key}/runtime/logs")
    async def resource_get_protocol_artifact_runtime_logs(
        run_id: str,
        artifact_key: str,
        auth: AuthContext = Depends(require_authenticated),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> dict[str, Any]:
        access = protocol_access(auth)
        runtime = store.get_protocol_artifact_runtime(run_id, artifact_key, access=access)
        if runtime is None:
            raise _protocol_http_error(404, error_code="PROTOCOL_ARTIFACT_RUNTIME_NOT_FOUND", message="Artifact runtime not found.")
        result = await RegistryManagementClient(store).send(
            agent_id=runtime.agent_id,
            payload=ArtifactRuntimeLogsRequest(
                runtime_instance_id=runtime.runtime_instance_id,
                protocol_run_id=run_id,
                artifact_key=artifact_key,
            ),
            timeout_seconds=15,
        )
        if not result.success or not isinstance(result.payload, ArtifactRuntimeLogsResult):
            raise _protocol_http_error(502, error_code="PROTOCOL_ARTIFACT_RUNTIME_LOGS_FAILED", message=result.error_detail or "Bot failed to read artifact runtime logs.")
        saved = store.save_protocol_artifact_runtime(
            runtime.model_copy(update={"log_tail": result.payload.log_tail}),
            access=access,
        )
        return _json_payload({"runtime": saved, "log_tail": result.payload.log_tail})

    @router.get("/v1/protocol-runs/{run_id}/artifacts/{artifact_key}/runtime/health")
    async def resource_get_protocol_artifact_runtime_health(
        run_id: str,
        artifact_key: str,
        auth: AuthContext = Depends(require_authenticated),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> dict[str, Any]:
        access = protocol_access(auth)
        runtime = store.get_protocol_artifact_runtime(run_id, artifact_key, access=access)
        if runtime is None:
            raise _protocol_http_error(404, error_code="PROTOCOL_ARTIFACT_RUNTIME_NOT_FOUND", message="Artifact runtime not found.")
        result = await RegistryManagementClient(store).send(
            agent_id=runtime.agent_id,
            payload=ArtifactRuntimeHealthRequest(
                runtime_instance_id=runtime.runtime_instance_id,
                protocol_run_id=run_id,
                artifact_key=artifact_key,
            ),
            timeout_seconds=15,
        )
        if not result.success or not isinstance(result.payload, ArtifactRuntimeHealthResult):
            raise _protocol_http_error(502, error_code="PROTOCOL_ARTIFACT_RUNTIME_HEALTH_FAILED", message=result.error_detail or "Bot failed to check artifact runtime health.")
        if result.payload.health.runtime is not None:
            runtime = store.save_protocol_artifact_runtime(
                _merge_runtime_record(runtime, result.payload.health.runtime),
                access=access,
            )
        store.append_protocol_artifact_runtime_event(
            _runtime_event(
                runtime=runtime,
                event_kind="health_checked",
                actor_ref=access.actor_ref,
                summary=result.payload.health.message,
                metadata={"ok": result.payload.health.ok, "status_code": result.payload.health.status_code},
            ),
            access=access,
        )
        return _json_payload(result.payload.health)

    @router.api_route(
        "/runtime/protocol-runs/{run_id}/artifacts/{artifact_key}/app",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        include_in_schema=False,
    )
    @router.api_route(
        "/runtime/protocol-runs/{run_id}/artifacts/{artifact_key}/app/{proxy_path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        include_in_schema=False,
    )
    @router.api_route(
        "/runtime/protocol-runs/{run_id}/artifacts/{artifact_key}/api",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        include_in_schema=False,
    )
    @router.api_route(
        "/runtime/protocol-runs/{run_id}/artifacts/{artifact_key}/api/{proxy_path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        include_in_schema=False,
    )
    async def resource_proxy_protocol_artifact_runtime(
        request: Request,
        run_id: str,
        artifact_key: str,
        proxy_path: str = "",
        auth: AuthContext = Depends(require_authenticated),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> Response:
        access = protocol_access(auth)
        runtime = store.get_protocol_artifact_runtime(run_id, artifact_key, access=access)
        if runtime is None:
            raise _protocol_http_error(404, error_code="PROTOCOL_ARTIFACT_RUNTIME_NOT_FOUND", message="Artifact runtime not found.")
        if str(runtime.status or "").lower() != "running":
            raise _protocol_http_error(
                409,
                error_code="PROTOCOL_ARTIFACT_RUNTIME_NOT_RUNNING",
                message="Start the artifact runtime before opening this app or API.",
                details={"status": runtime.status},
            )
        manifest = runtime.manifest or ProtocolArtifactRuntimeManifestRecord()
        route_path = str(request.url.path)
        is_api = f"/artifacts/{artifact_key}/api" in route_path
        tail = str(proxy_path or "").strip("/")
        if is_api:
            outbound_path = _runtime_api_outbound_path(manifest, tail)
        else:
            outbound_path = f"/{tail}" if tail else str(manifest.ui_path or "/")
        body = await request.body()
        headers = {
            key: value
            for key, value in request.headers.items()
            if key.lower() not in {"host", "connection", "content-length", "cookie", "authorization"}
        }
        result = await RegistryManagementClient(store).send(
            agent_id=runtime.agent_id,
            payload=ArtifactRuntimeFetchRequest(
                runtime_instance_id=runtime.runtime_instance_id,
                protocol_run_id=run_id,
                artifact_key=artifact_key,
                method=request.method,
                path=outbound_path,
                query_string=request.url.query,
                headers=RegistryJsonRecord(headers),
                body_base64=base64.b64encode(body).decode("ascii") if body else "",
            ),
            timeout_seconds=45,
        )
        if not result.success or not isinstance(result.payload, ArtifactRuntimeFetchResult):
            raise _protocol_http_error(502, error_code="PROTOCOL_ARTIFACT_RUNTIME_PROXY_FAILED", message=result.error_detail or "Artifact runtime proxy failed.")
        store.append_protocol_artifact_runtime_event(
            _runtime_event(
                runtime=runtime,
                event_kind="fetch",
                actor_ref=access.actor_ref,
                summary=f"{request.method} {outbound_path} -> {result.payload.status_code}",
                metadata={"status_code": result.payload.status_code},
            ),
            access=access,
        )
        response_headers = {
            key: str(value)
            for key, value in result.payload.headers.as_dict().items()
            if str(key).lower() in {"content-type", "cache-control", "etag", "last-modified", "location"}
        }
        content = base64.b64decode(str(result.payload.body_base64 or "").encode("ascii"))
        media_type = response_headers.pop("content-type", None)
        if request.method.upper() == "GET":
            content = _rewrite_runtime_html_content(
                content,
                content_type=str(media_type or ""),
                run_id=run_id,
                artifact_key=artifact_key,
                manifest=manifest,
            )
        return Response(
            content=content,
            status_code=int(result.payload.status_code or 200),
            media_type=media_type,
            headers=response_headers,
        )

    @router.get("/v1/protocol-runs/{run_id}/timeline")
    def resource_get_protocol_run_timeline(
        run_id: str,
        auth: AuthContext = Depends(require_authenticated),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> dict[str, Any]:
        try:
            transitions = store.get_protocol_run_timeline(run_id, access=protocol_access(auth))
        except PermissionError as exc:
            raise _protocol_http_error(403, error_code="PROTOCOL_NOT_VISIBLE", message="Protocol run is not visible to this actor.") from exc
        except KeyError as exc:
            raise _protocol_http_error(404, error_code="PROTOCOL_RUN_NOT_FOUND", message="Protocol run not found.") from exc
        return _json_payload({"transitions": transitions})

    @router.get("/v1/protocol-runs/{run_id}/export")
    def resource_export_protocol_run(
        run_id: str,
        auth: AuthContext = Depends(require_authenticated),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> dict[str, Any]:
        try:
            exported = store.export_protocol_run(run_id, access=protocol_access(auth))
        except PermissionError as exc:
            error_code = "PROTOCOL_NOT_VISIBLE" if "not visible" in str(exc).lower() else "PROTOCOL_EXPORT_FORBIDDEN"
            raise _protocol_http_error(403, error_code=error_code, message=str(exc)) from exc
        except KeyError as exc:
            raise _protocol_http_error(404, error_code="PROTOCOL_RUN_NOT_FOUND", message="Protocol run not found.") from exc
        return _json_payload(exported)

    @router.post("/v1/protocol-runs/{run_id}/actions/{action}")
    async def resource_act_on_protocol_run(
        run_id: str,
        action: str,
        payload: dict[str, Any],
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        if_match: str | None = Header(default=None, alias="If-Match"),
        auth: AuthContext = Depends(require_operator_session),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> dict[str, Any]:
        result = store.act_on_protocol_run(
            run_id,
            access=protocol_access(auth),
            action=action,
            reason=str(payload.get("reason", "") or ""),
            idempotency_key=str(idempotency_key or "").strip(),
            expected_version=_expected_protocol_version(if_match),
        )
        if not result.ok:
            raise _protocol_result_http_error(result)
        await broadcast_invalidations(
            topics=("protocols", "summary", f"protocol-run:{run_id}"),
            reason=f"protocol.run.{action}",
        )
        await broadcast_topic_event(
            run_id=run_id,
            event_kind="protocol_run.terminal" if str(result.run.status if result.run is not None else "") in {"completed", "failed", "cancelled"} else "protocol_run.updated",
            reason=f"protocol.run.{action}",
        )
        return _json_payload(result)

    @router.post("/v1/protocol-runs/{run_id}/archive")
    async def resource_archive_protocol_run(
        run_id: str,
        payload: dict[str, Any] | None = Body(default=None),
        auth: AuthContext = Depends(require_operator_session),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> dict[str, Any]:
        result = store.archive_protocol_run(
            run_id,
            access=protocol_access(auth),
            reason=str((payload or {}).get("reason", "") or ""),
        )
        if not result.ok:
            raise _protocol_result_http_error(result)
        await broadcast_invalidations(topics=("protocols", "summary", f"protocol-run:{run_id}"), reason="protocol.run.archived")
        await broadcast_topic_event(run_id=run_id, event_kind="protocol_run.updated", reason="protocol.run.archived")
        return _json_payload(result)

    @router.post("/v1/protocol-runs/{run_id}/restore")
    async def resource_restore_protocol_run(
        run_id: str,
        payload: dict[str, Any] | None = Body(default=None),
        auth: AuthContext = Depends(require_operator_session),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> dict[str, Any]:
        result = store.restore_protocol_run(
            run_id,
            access=protocol_access(auth),
            reason=str((payload or {}).get("reason", "") or ""),
        )
        if not result.ok:
            raise _protocol_result_http_error(result)
        await broadcast_invalidations(topics=("protocols", "summary", f"protocol-run:{run_id}"), reason="protocol.run.restored")
        await broadcast_topic_event(run_id=run_id, event_kind="protocol_run.updated", reason="protocol.run.restored")
        return _json_payload(result)

    @router.delete("/v1/protocol-runs/{run_id}")
    async def resource_delete_protocol_run(
        run_id: str,
        payload: dict[str, Any] | None = Body(default=None),
        auth: AuthContext = Depends(require_operator_session),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> dict[str, Any]:
        confirm = str((payload or {}).get("confirm", "") or "").strip().upper()
        if confirm != "DELETE":
            raise _protocol_http_error(400, error_code="PROTOCOL_RUN_DELETE_CONFIRMATION_REQUIRED", message="Type DELETE to confirm run deletion.")
        result = store.delete_protocol_run(
            run_id,
            access=protocol_access(auth),
            reason=str((payload or {}).get("reason", "") or ""),
        )
        if not result.ok:
            raise _protocol_result_http_error(result)
        await broadcast_invalidations(topics=("protocols", "summary", f"protocol-run:{run_id}"), reason="protocol.run.deleted")
        await broadcast_topic_event(run_id=run_id, event_kind="protocol_run.updated", reason="protocol.run.deleted")
        return _json_payload(result)

    @router.get("/v1/protocol-runs/{run_id}/rehearsal/sessions")
    async def resource_list_rehearsal_sessions(
        run_id: str,
        auth: AuthContext = Depends(require_authenticated),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> dict[str, Any]:
        try:
            detail = store.get_protocol_run(run_id, access=protocol_access(auth))
        except KeyError as exc:
            raise _protocol_http_error(404, error_code="PROTOCOL_RUN_NOT_FOUND", message="Protocol run not found.") from exc
        if not detail.run.is_rehearsal:
            raise _protocol_http_error(
                400,
                error_code="PROTOCOL_RUN_NOT_REHEARSAL",
                message="Rehearsal sessions are only available for rehearsal runs.",
            )
        manager = get_rehearsal_manager()
        sessions = [session.as_dict() for session in manager.list_pending(protocol_run_id=run_id)]
        return {"sessions": sessions, "rehearsal_agent_id": manager.agent_id}

    @router.post("/v1/protocol-runs/{run_id}/rehearsal/respond")
    async def resource_submit_rehearsal_response(
        run_id: str,
        payload: dict[str, Any],
        auth: AuthContext = Depends(require_operator_session),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> dict[str, Any]:
        try:
            detail = store.get_protocol_run(run_id, access=protocol_access(auth))
        except KeyError as exc:
            raise _protocol_http_error(404, error_code="PROTOCOL_RUN_NOT_FOUND", message="Protocol run not found.") from exc
        if not detail.run.is_rehearsal:
            raise _protocol_http_error(
                400,
                error_code="PROTOCOL_RUN_NOT_REHEARSAL",
                message="Rehearsal responses are only valid on rehearsal runs.",
            )
        routed_task_id = str(payload.get("routed_task_id", "") or "").strip()
        if not routed_task_id:
            raise _protocol_http_error(
                400,
                error_code="PROTOCOL_INVALID",
                message="routed_task_id is required.",
            )
        response_text = str(payload.get("response_text", "") or "")
        decision = str(payload.get("decision", "") or "done")
        decision_summary = str(payload.get("decision_summary", "") or "")
        raw_artifact_contents = payload.get("artifact_contents", ())
        artifact_contents = raw_artifact_contents if isinstance(raw_artifact_contents, list) else []
        manager = get_rehearsal_manager()
        accepted = manager.respond(
            routed_task_id=routed_task_id,
            response_text=response_text,
            decision=decision,
            decision_summary=decision_summary,
            artifact_contents=artifact_contents,
            expected_protocol_run_id=run_id,
        )
        if not accepted:
            raise _protocol_http_error(
                404,
                error_code="PROTOCOL_REHEARSAL_SESSION_NOT_FOUND",
                message="No pending rehearsal session for that routed task.",
            )
        await broadcast_invalidations(
            topics=("protocols", "summary", f"protocol-run:{run_id}"),
            reason="protocol.run.rehearsal_response",
        )
        await broadcast_topic_event(
            run_id=run_id,
            event_kind="protocol_run.updated",
            reason="protocol.run.rehearsal_response",
        )
        return {"ok": True, "routed_task_id": routed_task_id}

    @router.get("/v1/protocol-scenarios")
    def resource_list_protocol_scenarios(
        protocol_id: str = Query(default=""),
        auth: AuthContext = Depends(require_authenticated),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> dict[str, Any]:
        scenarios = store.list_protocol_scenarios(
            protocol_id=str(protocol_id or "").strip(),
            access=protocol_access(auth),
        )
        return {"scenarios": [s.model_dump(mode="json") for s in scenarios]}

    @router.post("/v1/protocol-scenarios")
    def resource_create_protocol_scenario(
        payload: dict[str, Any],
        auth: AuthContext = Depends(require_operator_session),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> dict[str, Any]:
        scenario = store.create_protocol_scenario(
            payload=payload,
            access=protocol_access(auth),
        )
        return scenario.model_dump(mode="json")

    @router.delete("/v1/protocol-scenarios/{scenario_id}")
    def resource_delete_protocol_scenario(
        scenario_id: str,
        auth: AuthContext = Depends(require_operator_session),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> dict[str, Any]:
        ok = store.delete_protocol_scenario(
            scenario_id=scenario_id,
            access=protocol_access(auth),
        )
        if not ok:
            raise _protocol_http_error(
                404,
                error_code="PROTOCOL_SCENARIO_NOT_FOUND",
                message="Scenario not found.",
            )
        return {"ok": True, "scenario_id": scenario_id}

    return router
