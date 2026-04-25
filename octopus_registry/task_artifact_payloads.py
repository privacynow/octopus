from __future__ import annotations

from typing import Any

from octopus_sdk.registry.models import RegistryJsonRecord, TaskRecord


def protocol_run_id_from_task_record(task: TaskRecord) -> str:
    direct_run_id = str(task.protocol_run_id or "").strip()
    if direct_run_id:
        return direct_run_id
    routed_task_id = str(task.routed_task_id or "").strip()
    if not routed_task_id.startswith("protocol-stage:"):
        return ""
    return str(_task_request_context(task).get("protocol_run_id", "") or "").strip()


def _task_request_context(task: TaskRecord) -> dict[str, Any]:
    request_payload = task.request.as_dict() if task.request is not None else {}
    context = request_payload.get("context", {}) if isinstance(request_payload, dict) else {}
    return context if isinstance(context, dict) else {}


def _protocol_stage_execution_id_from_task_record(task: TaskRecord) -> str:
    direct_stage_id = str(task.protocol_stage_execution_id or "").strip()
    if direct_stage_id:
        return direct_stage_id
    return str(_task_request_context(task).get("protocol_stage_execution_id", "") or "").strip()


def _task_expected_output_keys(task: TaskRecord) -> set[str]:
    request_payload = task.request.as_dict() if task.request is not None else {}
    internal_context = request_payload.get("internal_context", {})
    if not isinstance(internal_context, dict):
        return set()
    contract = internal_context.get("protocol_stage_contract", {})
    if not isinstance(contract, dict):
        return set()
    outputs = contract.get("output_artifacts", ())
    if not isinstance(outputs, list):
        return set()
    return {
        str(item.get("artifact_key", "") or "").strip()
        for item in outputs
        if isinstance(item, dict) and str(item.get("artifact_key", "") or "").strip()
    }


def _protocol_artifact_payloads_for_task(task: TaskRecord, detail: Any) -> list[dict[str, Any]]:
    stage_execution_id = _protocol_stage_execution_id_from_task_record(task)
    if not stage_execution_id or detail is None:
        return []
    expected_keys = _task_expected_output_keys(task)
    payloads: list[dict[str, Any]] = []
    for artifact in detail.artifacts or []:
        artifact_key = str(artifact.artifact_key or "").strip()
        if not artifact_key:
            continue
        produced_stage_id = str(artifact.produced_by_stage_execution_id or "").strip()
        if produced_stage_id:
            if produced_stage_id != stage_execution_id:
                continue
        elif artifact_key not in expected_keys:
            continue
        payloads.append(
            {
                "artifact_key": artifact_key,
                "artifact_kind": str(artifact.artifact_kind or "").strip(),
                "path": str(artifact.location or artifact.workspace_path or "").strip(),
                "workspace_path": str(artifact.workspace_path or "").strip(),
                "location": str(artifact.location or "").strip(),
                "exists": bool(artifact.exists),
                "size_bytes": int(artifact.size_bytes or 0),
                "content_hash": str(artifact.content_hash or "").strip(),
                "modified_at": str(artifact.modified_at or "").strip(),
                "observed_at": str(artifact.observed_at or "").strip(),
                "verification_state": str(artifact.verification_state or "").strip(),
                "state": str(artifact.state or "").strip(),
                "produced_by_stage_execution_id": produced_stage_id,
            }
        )
    return payloads


def _merge_task_artifact_payloads(task: TaskRecord, extra_artifacts: list[dict[str, Any]]) -> TaskRecord:
    if not extra_artifacts:
        return task
    result_payload = task.result.as_dict() if task.result is not None else {}
    if not isinstance(result_payload, dict):
        result_payload = {}
    existing = result_payload.get("artifacts", [])
    if not isinstance(existing, list):
        existing = []
    seen_keys = {
        str(item.get("artifact_key", "") or "").strip()
        for item in existing
        if isinstance(item, dict) and str(item.get("artifact_key", "") or "").strip()
    }
    merged = list(existing)
    for artifact in extra_artifacts:
        artifact_key = str(artifact.get("artifact_key", "") or "").strip()
        if not artifact_key or artifact_key in seen_keys:
            continue
        merged.append(artifact)
        seen_keys.add(artifact_key)
    if len(merged) == len(existing):
        return task
    result_payload["artifacts"] = merged
    return task.model_copy(update={
        "result": RegistryJsonRecord.model_validate(result_payload),
        "artifact_count": max(int(task.artifact_count or 0), len(merged)),
    })


def tasks_with_protocol_artifacts(
    tasks: list[TaskRecord],
    *,
    access: Any,
    store: Any,
) -> list[TaskRecord]:
    if not tasks:
        return tasks
    run_cache: dict[str, Any | None] = {}
    enriched: list[TaskRecord] = []
    for task in tasks:
        run_id = protocol_run_id_from_task_record(task)
        if not run_id:
            enriched.append(task)
            continue
        if run_id not in run_cache:
            try:
                run_cache[run_id] = store.get_protocol_run(run_id, access=access)
            except (AttributeError, KeyError, PermissionError):
                run_cache[run_id] = None
        enriched.append(_merge_task_artifact_payloads(
            task,
            _protocol_artifact_payloads_for_task(task, run_cache.get(run_id)),
        ))
    return enriched
