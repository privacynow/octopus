"""Protocol HTTP routes for the registry control plane."""

from __future__ import annotations

import mimetypes
import copy
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import ValidationError

from octopus_sdk.protocols import (
    ProtocolAccessContextRecord,
    ProtocolArtifactRecord,
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
    protocol_definition_content_hash,
    protocol_package_document,
    protocol_package_from_text,
    protocol_package_hash,
    protocol_package_required_skill_names,
    protocol_package_to_text,
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
from .auth import AuthContext
from .http_support import json_payload as _json_payload, paginated_response as _paginated_response
from .ingress import (
    RegistryIngressError,
    export_catalog_skill_package,
    import_catalog_skill_package,
)
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
        }

    def _connected_agents(store: AbstractRegistryStore) -> list[dict[str, Any]]:
        return [
            _agent_json(agent)
            for agent in store.list_agents(cursor=0, limit=200, connectivity_state="connected")
        ]

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
    def resource_get_protocol_run_artifact_content(
        request: Request,
        run_id: str,
        artifact_key: str,
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
            member_path=member_path,
            request=request,
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
