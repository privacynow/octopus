from __future__ import annotations

from collections.abc import Iterable
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
    return _resolve_artifact_file_path(
        candidate_paths=[
            str(artifact.location or "").strip(),
            str(artifact.workspace_path or "").strip(),
        ],
        candidate_roots=candidate_roots,
    )


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
    return _resolve_artifact_file_path(
        candidate_paths=[str(artifact.get("path", "") or "").strip()],
        candidate_roots=candidate_roots,
    )
