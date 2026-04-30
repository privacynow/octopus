from __future__ import annotations

from octopus_sdk.registry.models import TaskRecord

from octopus_registry.store_base import decode_json_field
from octopus_registry.store_dialect import StoreDialect
from octopus_registry.store_shared.common import record, records


def _task_context(request):
    context = request.get("context", {})
    return context if isinstance(context, dict) else {}


def _task_internal_context(request):
    internal_context = request.get("internal_context", {})
    return internal_context if isinstance(internal_context, dict) else {}


def _task_protocol_contract(request):
    contract = _task_internal_context(request).get("protocol_stage_contract", {})
    return contract if isinstance(contract, dict) else {}


def _task_base_payload(row, request, result):
    context = _task_context(request)
    return {
        "routed_task_id": row["routed_task_id"],
        "delivery_id": row.get("delivery_id", ""),
        "source_kind": row.get("source_kind", "delegation") or "delegation",
        "hidden_from_default_views": bool(row.get("hidden_from_default_views", False)),
        "parent_conversation_id": row["parent_conversation_id"],
        "parent_conversation_title": row.get("parent_conversation_title", "") or "",
        "recipient_conversation_id": row.get("recipient_conversation_id", "") or "",
        "origin_transport_ref": request.get("origin_transport_ref", ""),
        "origin_agent_id": row["origin_agent_id"],
        "origin_display_name": row["origin_name"] or "",
        "target_agent_id": row["target_agent_id"],
        "target_display_name": row["target_name"] or "",
        "title": row["title"],
        "status": row["status"],
        "summary": row["summary"],
        "instructions": request.get("instructions", ""),
        "result_summary": result.get("summary", ""),
        "result_text": result.get("full_text", ""),
        "protocol_run_id": str(context.get("protocol_run_id", "") or ""),
        "protocol_stage_execution_id": str(context.get("protocol_stage_execution_id", "") or ""),
        "protocol_definition_version_id": str(context.get("protocol_definition_version_id", "") or ""),
        "participant_key": str(context.get("participant_key", "") or ""),
        "stage_key": str(context.get("stage_key", "") or ""),
        "project_id_override": str(request.get("project_id_override", "") or ""),
        "file_policy_override": str(request.get("file_policy_override", "") or ""),
        "working_dir": str(result.get("working_dir", "") or ""),
        "artifact_count": len(result.get("artifacts", ()) or ()),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _task_list_payload(row):
    request = decode_json_field(row["request_json"], {})
    result = decode_json_field(row["result_json"], {})
    payload = _task_base_payload(row, request, result)
    contract = _task_protocol_contract(request)
    if contract:
        payload["artifact_count"] = max(
            int(payload.get("artifact_count", 0) or 0),
            len(contract.get("output_artifacts", ()) or ()),
        )
    if payload.get("protocol_run_id") or payload.get("artifact_count"):
        payload["request"] = request
        payload["result"] = result
    return payload


def _task_detail_payload(row):
    request = decode_json_field(row["request_json"], {})
    result = decode_json_field(row["result_json"], {})
    payload = _task_base_payload(row, request, result)
    payload.update({
        "request": request,
        "result": result,
    })
    contract = _task_protocol_contract(request)
    if contract:
        payload["artifact_count"] = max(
            int(payload.get("artifact_count", 0) or 0),
            len(contract.get("output_artifacts", ()) or ()),
        )
    return payload


def _task_select_sql(dialect: StoreDialect) -> str:
    return f"""
        SELECT
            t.*,
            origin.display_name AS origin_name,
            target.display_name AS target_name,
            parent.title AS parent_conversation_title
        FROM {dialect.qualify('routed_tasks')} t
        LEFT JOIN {dialect.qualify('agents')} origin ON origin.agent_id = t.origin_agent_id
        LEFT JOIN {dialect.qualify('agents')} target ON target.agent_id = t.target_agent_id
        LEFT JOIN {dialect.qualify('conversations')} parent ON parent.conversation_id = t.parent_conversation_id
    """


def tasks_for_routed_ids(
    conn,
    *,
    dialect: StoreDialect,
    routed_task_ids: list[str],
) -> list[TaskRecord]:
    ordered_ids = [str(item or "").strip() for item in routed_task_ids if str(item or "").strip()]
    if not ordered_ids:
        return []
    placeholders = ", ".join(dialect.placeholder(index + 1) for index in range(len(ordered_ids)))
    rows = dialect.fetchall(
        conn,
        _task_select_sql(dialect)
        + f" WHERE t.routed_task_id IN ({placeholders})",
        ordered_ids,
    )
    payload_by_id = {
        str(row["routed_task_id"] or ""): _task_detail_payload(row)
        for row in rows
    }
    return records(TaskRecord, [payload_by_id[item] for item in ordered_ids if item in payload_by_id])


def list_tasks(
    conn,
    *,
    dialect: StoreDialect,
    for_agent_id: str | None = None,
    parent_conversation_id: str = "",
    protocol_run_id: str = "",
    cursor: int = 0,
    limit: int = 25,
    status: str = "",
    completed_since_iso: str = "",
    include_generated: bool = True,
) -> list[TaskRecord]:
    fetch_limit = limit + 1
    sql = _task_select_sql(dialect)
    params: list[object] = []
    where_clauses: list[str] = []
    if for_agent_id is not None:
        p1 = dialect.placeholder(len(params) + 1)
        p2 = dialect.placeholder(len(params) + 2)
        where_clauses.append(f"(t.origin_agent_id = {p1} OR t.target_agent_id = {p2})")
        params.extend([for_agent_id, for_agent_id])
    if parent_conversation_id:
        params.append(parent_conversation_id)
        where_clauses.append(f"t.parent_conversation_id = {dialect.placeholder(len(params))}")
    if protocol_run_id:
        params.append(protocol_run_id)
        where_clauses.append(
            f"{dialect.json_path_text('t.request_json', 'context', 'protocol_run_id')} = {dialect.placeholder(len(params))}"
        )
    if status:
        params.append(status)
        where_clauses.append(f"t.status = {dialect.placeholder(len(params))}")
    if completed_since_iso:
        params.append(completed_since_iso)
        completed_expr = dialect.json_text("t.result_json", "completed_at")
        where_clauses.append(
            f"COALESCE({completed_expr}, t.updated_at) >= {dialect.placeholder(len(params))}"
        )
    if not include_generated:
        where_clauses.append("t.hidden_from_default_views = FALSE")
    if where_clauses:
        sql += " WHERE " + " AND ".join(where_clauses)
    params.extend([fetch_limit, cursor])
    sql += (
        f" ORDER BY t.updated_at DESC LIMIT {dialect.placeholder(len(params) - 1)} "
        f"OFFSET {dialect.placeholder(len(params))}"
    )
    rows = dialect.fetchall(conn, sql, params)
    return records(TaskRecord, [_task_list_payload(row) for row in rows])


def get_task(
    conn,
    *,
    dialect: StoreDialect,
    routed_task_id: str,
) -> TaskRecord:
    row = dialect.fetchone(
        conn,
        _task_select_sql(dialect) + f" WHERE t.routed_task_id = {dialect.placeholder(1)}",
        (routed_task_id,),
    )
    if row is None:
        raise KeyError(routed_task_id)
    return record(TaskRecord, _task_detail_payload(row))
