from __future__ import annotations

from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path

from octopus_sdk.protocols import ProtocolArtifactRecord, ProtocolRunDetailRecord
from octopus_sdk.registry.models import TaskRecord


def _resolve_artifact_file_path(
    *,
    candidate_paths: Iterable[str],
    candidate_roots: Iterable[str],
) -> Path | None:
    normalized_paths = [str(item or "").strip() for item in candidate_paths if str(item or "").strip()]
    normalized_roots = [str(item or "").strip() for item in candidate_roots if str(item or "").strip()]

    for candidate in normalized_paths:
        path = Path(candidate)
        if path.is_absolute() and path.is_file():
            return path

    relative_path = next((item for item in normalized_paths if not Path(item).is_absolute()), "")
    if not relative_path:
        return None

    relative_candidate = Path(relative_path)
    for root in normalized_roots:
        root_path = Path(root)
        if not root_path.is_absolute():
            continue
        try:
            resolved = (root_path / relative_candidate).resolve()
            resolved.relative_to(root_path.resolve())
        except Exception:
            continue
        if resolved.is_file():
            return resolved
    return None


def _resolve_artifact_target_path(
    *,
    candidate_path: str,
    candidate_roots: Iterable[str],
) -> Path | None:
    normalized_path = str(candidate_path or "").strip()
    if not normalized_path:
        return None
    direct = Path(normalized_path)
    if direct.is_absolute():
        parent = direct.parent
        return direct if parent.is_dir() else None
    relative_candidate = Path(normalized_path)
    for root in candidate_roots:
        root_path = Path(str(root or "").strip())
        if not root_path.is_absolute():
            continue
        try:
            resolved = (root_path / relative_candidate).resolve()
            resolved.relative_to(root_path.resolve())
        except Exception:
            continue
        return resolved
    return None


@lru_cache(maxsize=1)
def _mounted_workspace_roots() -> tuple[str, ...]:
    workspace_parent = Path("/workspace")
    if not workspace_parent.is_dir():
        return ()
    return tuple(
        str(child)
        for child in sorted(workspace_parent.iterdir())
        if child.is_dir()
    )


def _artifact_body_from_full_text(full_text: str) -> str:
    body_lines: list[str] = []
    for line in str(full_text or "").splitlines():
        marker = line.strip().upper()
        if marker.startswith("PROTOCOL_DECISION:") or marker.startswith("PROTOCOL_SUMMARY:"):
            continue
        body_lines.append(line.rstrip())
    return "\n".join(body_lines).strip()


def _result_payload_artifact_content(result_payload: object, artifact_key: str) -> str:
    if not isinstance(result_payload, dict):
        return ""
    target_key = str(artifact_key or "").strip()
    if not target_key:
        return ""
    artifact_contents = result_payload.get("artifact_contents", ())
    if not isinstance(artifact_contents, list):
        return ""
    for item in artifact_contents:
        if not isinstance(item, dict):
            continue
        if str(item.get("artifact_key", "") or "").strip() != target_key:
            continue
        content = str(item.get("content", "") or "")
        if content:
            return content
    return ""


def artifact_download_name(*, artifact_key: str, preferred_path: str = "") -> str:
    candidate = str(preferred_path or "").strip()
    if candidate:
        name = Path(candidate).name.strip()
        if name:
            return name
    return str(artifact_key or "").strip() or "artifact"


def resolve_workspace_artifact_target(*, workspace_ref: str = "", artifact_path: str = "") -> Path | None:
    return _resolve_artifact_target_path(
        candidate_path=artifact_path,
        candidate_roots=[
            str(workspace_ref or "").strip(),
            *_mounted_workspace_roots(),
        ],
    )


def resolve_protocol_artifact_path(detail: ProtocolRunDetailRecord, artifact: ProtocolArtifactRecord) -> Path | None:
    produced_stage_id = str(artifact.produced_by_stage_execution_id or "").strip()
    candidate_roots: list[str] = []
    if produced_stage_id:
        for task in detail.tasks or []:
            if str(task.protocol_stage_execution_id or "").strip() != produced_stage_id:
                continue
            candidate_roots.extend([
                str(task.working_dir or "").strip(),
                str(task.project_id_override or "").strip(),
            ])
            break
    candidate_roots.extend([
        str(detail.run.workspace_ref or "").strip(),
        str(detail.run.repo_ref or "").strip(),
    ])
    candidate_roots.extend(_mounted_workspace_roots())
    return _resolve_artifact_file_path(
        candidate_paths=[
            str(artifact.location or "").strip(),
            str(artifact.workspace_path or "").strip(),
        ],
        candidate_roots=candidate_roots,
    )


def resolve_protocol_artifact_rehearsal_text(
    detail: ProtocolRunDetailRecord,
    artifact: ProtocolArtifactRecord,
) -> str:
    if not bool(getattr(detail.run, "is_rehearsal", False)):
        return ""
    produced_stage_id = str(artifact.produced_by_stage_execution_id or "").strip()
    for task in detail.tasks or ():
        if produced_stage_id and str(task.protocol_stage_execution_id or "").strip() != produced_stage_id:
            continue
        if task.result is None:
            continue
        result_payload = task.result.as_dict()
        if not isinstance(result_payload, dict):
            continue
        content = _result_payload_artifact_content(result_payload, str(artifact.artifact_key or ""))
        if content:
            return content
        body = _artifact_body_from_full_text(str(result_payload.get("full_text", "") or ""))
        if body:
            return body
    return ""


def resolve_task_artifact_path(
    task: TaskRecord,
    artifact_key: str,
    *,
    run_detail: ProtocolRunDetailRecord | None = None,
) -> Path | None:
    result_payload = task.result.as_dict() if task.result is not None else {}
    artifacts = result_payload.get("artifacts", ()) if isinstance(result_payload, dict) else ()
    if not isinstance(artifacts, list):
        return None
    artifact = next(
        (
            item for item in artifacts
            if isinstance(item, dict) and str(item.get("artifact_key", "") or "").strip() == str(artifact_key or "").strip()
        ),
        None,
    )
    if artifact is None:
        return None
    candidate_roots = [
        str(task.working_dir or result_payload.get("working_dir", "") or "").strip(),
        str(task.project_id_override or "").strip(),
    ]
    if run_detail is not None:
        candidate_roots.extend([
            str(run_detail.run.workspace_ref or "").strip(),
            str(run_detail.run.repo_ref or "").strip(),
        ])
    candidate_roots.extend(_mounted_workspace_roots())
    return _resolve_artifact_file_path(
        candidate_paths=[str(artifact.get("path", "") or "").strip()],
        candidate_roots=candidate_roots,
    )


def resolve_task_artifact_rehearsal_text(
    task: TaskRecord,
    artifact_key: str,
    *,
    run_detail: ProtocolRunDetailRecord | None = None,
) -> str:
    if run_detail is None or not bool(getattr(run_detail.run, "is_rehearsal", False)):
        return ""
    result_payload = task.result.as_dict() if task.result is not None else {}
    artifacts = result_payload.get("artifacts", ()) if isinstance(result_payload, dict) else ()
    if not isinstance(artifacts, list):
        return ""
    matched = any(
        isinstance(item, dict) and str(item.get("artifact_key", "") or "").strip() == str(artifact_key or "").strip()
        for item in artifacts
    )
    if not matched:
        return ""
    content = _result_payload_artifact_content(result_payload, artifact_key)
    if content:
        return content
    return _artifact_body_from_full_text(str(result_payload.get("full_text", "") or ""))
