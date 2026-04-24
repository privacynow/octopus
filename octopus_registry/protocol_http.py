"""Protocol HTTP routes for the registry control plane."""

from __future__ import annotations

import mimetypes
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from pydantic import ValidationError

from octopus_sdk.protocols import (
    ProtocolAccessContextRecord,
    ProtocolArtifactRecord,
    ProtocolDraftCreateRecord,
    ProtocolRunCreateRecord,
)
from octopus_sdk.registry.models import RegistryJsonRecord

from .artifact_paths import artifact_download_name, resolve_protocol_artifact_path, resolve_protocol_artifact_rehearsal_text
from .auth import AuthContext
from .http_support import json_payload as _json_payload, paginated_response as _paginated_response
from .rehearsal import RehearsalSessionManager
from .store_base import AbstractRegistryStore

_InvalidationBroadcaster = Callable[..., Awaitable[None]]
_TopicEventBroadcaster = Callable[..., Awaitable[None]]


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

    @router.get("/v1/protocol-templates/{slug}")
    def resource_get_protocol_template(
        slug: str,
        auth: AuthContext = Depends(require_authenticated),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> dict[str, Any]:
        try:
            document = store.get_protocol_template(slug, access=protocol_access(auth))
        except PermissionError as exc:
            raise _protocol_http_error(403, error_code="PROTOCOL_NOT_VISIBLE", message="Protocol is not visible to this actor.") from exc
        except KeyError as exc:
            raise _protocol_http_error(404, error_code="PROTOCOL_NOT_FOUND", message="Protocol template not found.") from exc
        return _json_payload(document)

    @router.get("/v1/protocol-templates")
    def resource_list_protocol_templates(
        auth: AuthContext = Depends(require_authenticated),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> list[dict[str, Any]]:
        try:
            return _json_payload(store.list_protocol_templates(access=protocol_access(auth)))
        except PermissionError as exc:
            raise _protocol_http_error(403, error_code="PROTOCOL_FORBIDDEN", message=str(exc)) from exc

    @router.get("/v1/protocol-authoring/manifest")
    def resource_get_protocol_authoring_manifest(
        auth: AuthContext = Depends(require_operator_session),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> dict[str, Any]:
        try:
            manifest = store.get_protocol_authoring_manifest(access=protocol_access(auth))
        except PermissionError as exc:
            raise _protocol_http_error(403, error_code="PROTOCOL_FORBIDDEN", message=str(exc)) from exc
        return _json_payload(manifest)

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

    @router.get("/v1/protocol-runs")
    def resource_list_protocol_runs(
        cursor: int = Query(default=0, ge=0),
        limit: int = Query(default=25, ge=1, le=100),
        status: str = Query(default=""),
        protocol_id: str = Query(default=""),
        entry_agent_id: str = Query(default=""),
        root_conversation_id: str = Query(default=""),
        origin_channel: str = Query(default=""),
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
    def resource_get_protocol_run_artifact_content(
        run_id: str,
        artifact_key: str,
        download: bool = Query(default=False),
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
            content_text = resolve_protocol_artifact_rehearsal_text(detail, artifact)
            if content_text:
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
        return FileResponse(
            path=resolved_path,
            media_type=media_type,
            filename=preferred_name or resolved_path.name,
            content_disposition_type="attachment" if download else "inline",
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
        auth: AuthContext = Depends(require_operator_session),
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
