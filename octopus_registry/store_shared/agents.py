from __future__ import annotations

from datetime import datetime, timedelta, timezone

from octopus_sdk.registry.models import AgentRecord, AgentStatusRecord

from octopus_registry.store_base import runtime_health_detail
from octopus_registry.store_dialect import StoreDialect
from octopus_registry.store_shared.common import record


def list_agents(
    conn,
    *,
    dialect: StoreDialect,
    row_to_agent,
    for_agent_id: str | None = None,
    cursor: int = 0,
    limit: int = 25,
    q: str = "",
    connectivity_state: str = "",
) -> list[AgentRecord]:
    fetch_limit = limit + 1
    if q or connectivity_state:
        rows = dialect.fetchall(
            conn,
            f"SELECT * FROM {dialect.qualify('agents')} ORDER BY lower(display_name)",
        )
        agents = [row_to_agent(row) for row in rows]
        if for_agent_id is not None:
            agents = [agent for agent in agents if agent["agent_id"] == for_agent_id]
        q_lower = q.strip().lower()
        if q_lower:
            agents = [
                agent for agent in agents
                if q_lower in (agent["display_name"] or "").lower()
                or q_lower in (agent["slug"] or "").lower()
                or q_lower in (agent["role"] or "").lower()
                or q_lower in (agent["provider"] or "").lower()
            ]
        if connectivity_state:
            agents = [
                agent for agent in agents
                if (agent["connectivity_state"] or "") == connectivity_state
            ]
        return agents[cursor: cursor + fetch_limit]
    if for_agent_id is not None:
        rows = dialect.fetchall(
            conn,
            (
                f"SELECT * FROM {dialect.qualify('agents')} "
                f"WHERE agent_id = {dialect.placeholder(1)} "
                f"ORDER BY lower(display_name) "
                f"LIMIT {dialect.placeholder(2)} OFFSET {dialect.placeholder(3)}"
            ),
            (for_agent_id, fetch_limit, cursor),
        )
    else:
        rows = dialect.fetchall(
            conn,
            (
                f"SELECT * FROM {dialect.qualify('agents')} "
                f"ORDER BY lower(display_name) "
                f"LIMIT {dialect.placeholder(1)} OFFSET {dialect.placeholder(2)}"
            ),
            (fetch_limit, cursor),
        )
    return [row_to_agent(row) for row in rows]


def get_agent_runtime_health(
    conn,
    *,
    dialect: StoreDialect,
    agent_id: str,
    runtime_worker_rows,
):
    row = dialect.fetchone(
        conn,
        f"SELECT * FROM {dialect.qualify('agents')} WHERE agent_id = {dialect.placeholder(1)}",
        (agent_id,),
    )
    if row is None:
        return None
    return runtime_health_detail(
        row.get("runtime_health_json"),
        runtime_worker_rows(conn, agent_id),
    )


def get_agent_status(
    conn,
    *,
    dialect: StoreDialect,
    agent_id: str,
    row_to_agent,
    runtime_worker_rows,
):
    row = dialect.fetchone(
        conn,
        f"SELECT * FROM {dialect.qualify('agents')} WHERE agent_id = {dialect.placeholder(1)}",
        (agent_id,),
    )
    if row is None:
        return None
    agent = row_to_agent(row)
    workers = runtime_worker_rows(conn, agent_id)
    active_count_row = dialect.fetchone(
        conn,
        f"""
        SELECT COUNT(*) AS cnt FROM {dialect.qualify('conversations')}
        WHERE target_agent_id = {dialect.placeholder(1)} AND status IN ('open', 'running')
        """,
        (agent_id,),
    ) or {}
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    error_count_row = dialect.fetchone(
        conn,
        f"""
        SELECT COUNT(*) AS cnt FROM {dialect.qualify('events')}
        WHERE agent_id = {dialect.placeholder(1)} AND kind = 'error'
          AND created_at >= {dialect.placeholder(2)}
        """,
        (agent_id, cutoff),
    ) or {}
    return record(
        AgentStatusRecord,
        {
            **agent.model_dump(mode="json"),
            "workers": workers,
            "active_conversations": int(active_count_row.get("cnt") or 0),
            "recent_errors": int(error_count_row.get("cnt") or 0),
        },
    )
