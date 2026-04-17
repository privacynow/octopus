"""Protocol HTTP routes for the registry control plane."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request

from octopus_sdk.protocols import ProtocolAccessContextRecord, ProtocolRunCreateRecord
from octopus_sdk.registry.models import RegistryJsonRecord

from .auth import AuthContext
from .http_support import json_payload as _json_payload, paginated_response as _paginated_response
from .store_base import AbstractRegistryStore

_InvalidationBroadcaster = Callable[..., Awaitable[None]]


def build_protocol_router(
    *,
    get_store: Callable[[], AbstractRegistryStore],
    require_authenticated: Callable[..., AuthContext],
    require_operator_session: Callable[..., AuthContext],
    protocol_access: Callable[[AuthContext], ProtocolAccessContextRecord],
    broadcast_invalidations: _InvalidationBroadcaster,
) -> APIRouter:
    router = APIRouter()

    def _protocol_http_error(
        status_code: int,
        *,
        error_code: str,
        message: str,
    ) -> HTTPException:
        return HTTPException(
            status_code=status_code,
            detail={
                "error_code": error_code,
                "message": message,
            },
        )

    def _protocol_result_http_error(result) -> HTTPException:
        status = str(getattr(result, "status", "") or "").lower()
        message = str(getattr(result, "message", "") or "Protocol request failed.")
        if status == "not_found":
            return _protocol_http_error(404, error_code="PROTOCOL_NOT_FOUND", message=message)
        if status == "not_visible":
            return _protocol_http_error(403, error_code="PROTOCOL_NOT_VISIBLE", message=message)
        if status == "forbidden":
            return _protocol_http_error(403, error_code="PROTOCOL_FORBIDDEN", message=message)
        if status in {"idempotency_conflict", "concurrent_modification"}:
            return _protocol_http_error(409, error_code=status.upper(), message=message)
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
            raise HTTPException(status_code=404, detail="Protocol template not found") from exc
        return _json_payload(document)

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

    @router.post("/v1/protocols")
    async def resource_create_protocol(
        request: Request,
        auth: AuthContext = Depends(require_operator_session),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> dict[str, Any]:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Invalid protocol payload")
        result = store.save_protocol_draft(
            access=protocol_access(auth),
            protocol_id=str(payload.get("protocol_id", "") or ""),
            slug=str(payload.get("slug", "") or ""),
            display_name=str(payload.get("display_name", "") or ""),
            description=str(payload.get("description", "") or ""),
            definition_json=RegistryJsonRecord.model_validate(payload.get("definition_json", {})),
        )
        if not result.ok:
            raise _protocol_result_http_error(result)
        await broadcast_invalidations(topics=("protocols",), reason="protocol.saved")
        return _json_payload(result)

    @router.put("/v1/protocols/{protocol_id}/draft")
    async def resource_save_protocol_draft(
        protocol_id: str,
        request: Request,
        auth: AuthContext = Depends(require_operator_session),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> dict[str, Any]:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Invalid protocol payload")
        result = store.save_protocol_draft(
            access=protocol_access(auth),
            protocol_id=protocol_id,
            slug=str(payload.get("slug", "") or ""),
            display_name=str(payload.get("display_name", "") or ""),
            description=str(payload.get("description", "") or ""),
            definition_json=RegistryJsonRecord.model_validate(payload.get("definition_json", {})),
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
        auth: AuthContext = Depends(require_authenticated),
        store: AbstractRegistryStore = Depends(get_store),
    ) -> dict[str, Any]:
        runs = store.list_protocol_runs(
            access=protocol_access(auth),
            limit=limit,
            cursor=cursor,
            status=status,
            protocol_id=protocol_id,
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
        result = store.create_protocol_run(
            payload,
            access=protocol_access(auth),
            idempotency_key=str(idempotency_key or "").strip(),
        )
        if not result.ok:
            raise _protocol_result_http_error(result)
        topics = {"protocols", "summary"}
        if result.run is not None:
            topics.add(f"protocol-run:{result.run.protocol_run_id}")
        await broadcast_invalidations(topics=topics, reason="protocol.run.created")
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
        return _json_payload(result)

    return router
