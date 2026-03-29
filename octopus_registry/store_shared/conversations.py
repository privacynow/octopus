from __future__ import annotations

from octopus_sdk.registry.models import ConversationRecord, TaskRecord

from octopus_registry.store_dialect import StoreDialect
from octopus_registry.store_shared.common import record, records


def _in_placeholders(dialect: StoreDialect, *, start_index: int, count: int) -> str:
    return ",".join(dialect.placeholder(start_index + offset) for offset in range(count))


def _conversation_payload(row):
    return {
        "conversation_id": row["conversation_id"],
        "target_agent_id": row["target_agent_id"],
        "target_display_name": row["target_name"] or "",
        "target_name": row["target_name"] or "",
        "title": row["title"],
        "conversation_type": row["conversation_type"] or "conversation",
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "origin_channel": row["origin_channel"],
        "external_conversation_ref": row["external_conversation_ref"],
        "event_count": int(row["event_count"] or 0),
    }


def _linked_task_payload(row):
    return {
        "routed_task_id": row["routed_task_id"],
        "parent_conversation_id": row["parent_conversation_id"],
        "origin_agent_id": row["origin_agent_id"],
        "origin_display_name": row["origin_name"] or "",
        "target_agent_id": row["target_agent_id"],
        "target_display_name": row["target_name"] or "",
        "title": row["title"],
        "status": row["status"],
        "summary": row["summary"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_conversations(
    conn,
    *,
    dialect: StoreDialect,
    for_agent_id: str | None = None,
    cursor: int = 0,
    limit: int = 25,
    status: str = "",
    conversation_type: str = "",
    search_hit_ids: list[str] | None = None,
) -> list[ConversationRecord]:
    fetch_limit = limit + 1
    params: list[object] = []
    sql = f"""
        SELECT
            c.*,
            a.display_name AS target_name,
            COUNT(e.event_id) AS event_count
        FROM {dialect.qualify('conversations')} c
        LEFT JOIN {dialect.qualify('agents')} a ON a.agent_id = c.target_agent_id
        LEFT JOIN {dialect.qualify('events')} e ON e.conversation_id = c.conversation_id
    """
    where_clauses: list[str] = []
    if search_hit_ids is not None:
        placeholders = _in_placeholders(dialect, start_index=1, count=len(search_hit_ids))
        where_clauses.append(f"c.conversation_id IN ({placeholders})")
        params.extend(search_hit_ids)
    if for_agent_id is not None:
        params.append(for_agent_id)
        where_clauses.append(f"c.target_agent_id = {dialect.placeholder(len(params))}")
    if status:
        params.append(status)
        where_clauses.append(f"c.status = {dialect.placeholder(len(params))}")
    if conversation_type:
        params.append(conversation_type)
        where_clauses.append(f"c.conversation_type = {dialect.placeholder(len(params))}")
    if where_clauses:
        sql += " WHERE " + " AND ".join(where_clauses)
    params.extend([fetch_limit, cursor])
    sql += """
        GROUP BY
            c.conversation_id,
            c.target_agent_id,
            c.title,
            c.conversation_type,
            c.origin_channel,
            c.external_conversation_ref,
            c.status,
            c.created_at,
            c.updated_at,
            a.display_name
        ORDER BY c.updated_at DESC
    """
    sql += (
        f" LIMIT {dialect.placeholder(len(params) - 1)} "
        f"OFFSET {dialect.placeholder(len(params))}"
    )
    rows = dialect.fetchall(conn, sql, params)
    return records(ConversationRecord, [_conversation_payload(row) for row in rows])


def get_conversation(
    conn,
    *,
    dialect: StoreDialect,
    conversation_id: str,
) -> ConversationRecord:
    row = dialect.fetchone(
        conn,
        f"""
        SELECT
            c.*,
            a.display_name AS target_name,
            COUNT(e.event_id) AS event_count
        FROM {dialect.qualify('conversations')} c
        LEFT JOIN {dialect.qualify('agents')} a ON a.agent_id = c.target_agent_id
        LEFT JOIN {dialect.qualify('events')} e ON e.conversation_id = c.conversation_id
        WHERE c.conversation_id = {dialect.placeholder(1)}
        GROUP BY
            c.conversation_id,
            c.target_agent_id,
            c.title,
            c.conversation_type,
            c.origin_channel,
            c.external_conversation_ref,
            c.status,
            c.created_at,
            c.updated_at,
            a.display_name
        """,
        (conversation_id,),
    )
    if row is None:
        raise KeyError(conversation_id)
    task_rows = dialect.fetchall(
        conn,
        f"""
        SELECT t.*, origin.display_name AS origin_name, target.display_name AS target_name
        FROM {dialect.qualify('routed_tasks')} t
        LEFT JOIN {dialect.qualify('agents')} origin ON origin.agent_id = t.origin_agent_id
        LEFT JOIN {dialect.qualify('agents')} target ON target.agent_id = t.target_agent_id
        WHERE t.parent_conversation_id = {dialect.placeholder(1)}
        ORDER BY t.updated_at DESC
        """,
        (conversation_id,),
    )
    payload = _conversation_payload(row)
    payload["linked_routed_tasks"] = records(TaskRecord, [_linked_task_payload(task) for task in task_rows])
    return record(ConversationRecord, payload)


def list_agent_conversations(
    conn,
    *,
    dialect: StoreDialect,
    agent_id: str,
    for_agent_id: str | None = None,
    cursor: int = 0,
    limit: int = 50,
    conversation_type: str = "",
) -> list[ConversationRecord]:
    fetch_limit = limit + 1
    effective_agent_id = for_agent_id if for_agent_id is not None else agent_id
    params: list[object] = [effective_agent_id]
    sql = f"""
        SELECT c.*, a.display_name AS target_name
        FROM {dialect.qualify('conversations')} c
        LEFT JOIN {dialect.qualify('agents')} a ON a.agent_id = c.target_agent_id
        WHERE c.target_agent_id = {dialect.placeholder(1)}
    """
    if conversation_type:
        params.append(conversation_type)
        sql += f" AND c.conversation_type = {dialect.placeholder(len(params))}"
    params.extend([fetch_limit, cursor])
    sql += """
        ORDER BY c.updated_at DESC
    """
    sql += (
        f" LIMIT {dialect.placeholder(len(params) - 1)} "
        f"OFFSET {dialect.placeholder(len(params))}"
    )
    rows = dialect.fetchall(conn, sql, params)
    return records(ConversationRecord, [
        {
            "conversation_id": row["conversation_id"],
            "target_agent_id": row["target_agent_id"],
            "target_display_name": row["target_name"] or "",
            "target_name": row["target_name"] or "",
            "title": row["title"],
            "conversation_type": row["conversation_type"] or "conversation",
            "origin_channel": row["origin_channel"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ])
