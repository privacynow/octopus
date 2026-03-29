from __future__ import annotations

from octopus_sdk.registry.models import TaskRecord

from octopus_registry.store_base import decode_json_field
from octopus_registry.store_dialect import StoreDialect
from octopus_registry.store_shared.common import record, records


def _task_list_payload(row):
    request = decode_json_field(row["request_json"], {})
    result = decode_json_field(row["result_json"], {})
    return {
        "routed_task_id": row["routed_task_id"],
        "parent_conversation_id": row["parent_conversation_id"],
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
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _task_detail_payload(row):
    request = decode_json_field(row["request_json"], {})
    result = decode_json_field(row["result_json"], {})
    return {
        "routed_task_id": row["routed_task_id"],
        "parent_conversation_id": row["parent_conversation_id"],
        "origin_transport_ref": request.get("origin_transport_ref", ""),
        "origin_agent_id": row["origin_agent_id"],
        "origin_display_name": row["origin_name"] or "",
        "target_agent_id": row["target_agent_id"],
        "target_display_name": row["target_name"] or "",
        "title": row["title"],
        "status": row["status"],
        "summary": row["summary"],
        "request": request,
        "result": result,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_tasks(
    conn,
    *,
    dialect: StoreDialect,
    for_agent_id: str | None = None,
    parent_conversation_id: str = "",
    cursor: int = 0,
    limit: int = 25,
    status: str = "",
    completed_since_iso: str = "",
) -> list[TaskRecord]:
    fetch_limit = limit + 1
    sql = f"""
        SELECT t.*, origin.display_name AS origin_name, target.display_name AS target_name
        FROM {dialect.qualify('routed_tasks')} t
        LEFT JOIN {dialect.qualify('agents')} origin ON origin.agent_id = t.origin_agent_id
        LEFT JOIN {dialect.qualify('agents')} target ON target.agent_id = t.target_agent_id
    """
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
    if status:
        params.append(status)
        where_clauses.append(f"t.status = {dialect.placeholder(len(params))}")
    if completed_since_iso:
        params.append(completed_since_iso)
        completed_expr = dialect.json_text("t.result_json", "completed_at")
        where_clauses.append(
            f"COALESCE({completed_expr}, t.updated_at) >= {dialect.placeholder(len(params))}"
        )
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
        f"""
        SELECT t.*, origin.display_name AS origin_name, target.display_name AS target_name
        FROM {dialect.qualify('routed_tasks')} t
        LEFT JOIN {dialect.qualify('agents')} origin ON origin.agent_id = t.origin_agent_id
        LEFT JOIN {dialect.qualify('agents')} target ON target.agent_id = t.target_agent_id
        WHERE t.routed_task_id = {dialect.placeholder(1)}
        """,
        (routed_task_id,),
    )
    if row is None:
        raise KeyError(routed_task_id)
    return record(TaskRecord, _task_detail_payload(row))
