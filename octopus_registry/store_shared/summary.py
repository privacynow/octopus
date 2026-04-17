from __future__ import annotations

from datetime import datetime, timedelta

from octopus_sdk.registry.models import (
    ApprovalRecord,
    RegistrySummaryRecord,
    UsageSummaryRecord,
)

from octopus_registry.store_base import decode_json_field, effective_connectivity_state, runtime_health_summary
from octopus_registry.store_dialect import StoreDialect
from octopus_registry.store_shared.common import records
from octopus_registry.store_shared.usage import aggregate_usage_totals


def _stringify_timestamp(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


def get_usage_summary(
    conn,
    *,
    dialect: StoreDialect,
    since_iso: str,
    until_iso: str = "",
) -> list[UsageSummaryRecord]:
    params: list[object] = [since_iso]
    usage_predicate = dialect.usage_token_predicate("e.metadata_json")
    sql = f"""
        SELECT e.conversation_id, e.metadata_json, e.created_at, c.title
        FROM {dialect.qualify("events")} e
        LEFT JOIN {dialect.qualify("conversations")} c ON c.conversation_id = e.conversation_id
        WHERE (
            e.kind = 'provider.response'
            OR (e.kind = 'task.status' AND {usage_predicate})
        ) AND e.created_at >= {dialect.placeholder(1)}
    """
    if until_iso:
        params.append(until_iso)
        sql += f" AND e.created_at <= {dialect.placeholder(2)}"
    sql += " ORDER BY e.created_at"
    rows = dialect.fetchall(conn, sql, params)
    return records(UsageSummaryRecord, [
        {
            "conversation_id": row["conversation_id"],
            "title": row["title"] or "",
            "metadata": decode_json_field(row["metadata_json"], {}),
            "created_at": _stringify_timestamp(row["created_at"]),
        }
        for row in rows
    ])


def get_summary(
    conn,
    *,
    dialect: StoreDialect,
    now_iso: str,
) -> RegistrySummaryRecord:
    window_start = (
        datetime.fromisoformat(now_iso) - timedelta(hours=24)
    ).isoformat()
    agent_rows = dialect.fetchall(
        conn,
        f"SELECT connectivity_state, last_heartbeat_at, runtime_health_json FROM {dialect.qualify('agents')}",
    )
    conversation_totals = dialect.fetchone(
        conn,
        f"""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN status IN ('open', 'running', 'cancelling') THEN 1 ELSE 0 END) AS active
        FROM {dialect.qualify('conversations')}
        """,
    ) or {}
    pending_approvals_row = dialect.fetchone(
        conn,
        f"""
        SELECT COUNT(*) AS cnt
        FROM {dialect.qualify('conversations')} c
        WHERE EXISTS (
            SELECT 1
            FROM {dialect.qualify('events')} e
            WHERE e.conversation_id = c.conversation_id
              AND e.kind = 'approval.requested'
              AND e.seq = (
                  SELECT MAX(e2.seq)
                  FROM {dialect.qualify('events')} e2
                  WHERE e2.conversation_id = c.conversation_id
                    AND e2.kind IN ('approval.requested', 'approval.decided')
              )
        )
        """,
    ) or {}
    task_totals = dialect.fetchone(
        conn,
        f"""
        SELECT
            SUM(CASE WHEN status = 'running' THEN 1 ELSE 0 END) AS running,
            SUM(CASE WHEN status IN ('queued', 'leased', 'submitted') THEN 1 ELSE 0 END) AS pending,
            SUM(CASE WHEN status = 'failed' AND updated_at >= {dialect.placeholder(1)} THEN 1 ELSE 0 END) AS failed_24h
        FROM {dialect.qualify('routed_tasks')}
        """,
        (window_start,),
    ) or {}
    protocol_totals = dialect.fetchone(
        conn,
        f"""
        SELECT
            (SELECT COUNT(*) FROM {dialect.qualify('protocol_definitions')}) AS definitions_total,
            (SELECT COUNT(*) FROM {dialect.qualify('protocol_definitions')} WHERE lifecycle_state = 'published') AS definitions_published,
            (SELECT COUNT(*) FROM {dialect.qualify('protocol_runs')}) AS runs_total,
            (SELECT COUNT(*) FROM {dialect.qualify('protocol_runs')} WHERE status IN ('queued', 'running', 'blocked')) AS runs_active,
            (SELECT COUNT(*) FROM {dialect.qualify('protocol_runs')} WHERE status = 'blocked') AS runs_blocked,
            (SELECT COUNT(*) FROM {dialect.qualify('protocol_runs')} WHERE status = 'failed' AND updated_at >= {dialect.placeholder(1)}) AS runs_failed_24h,
            (SELECT COUNT(*) FROM {dialect.qualify('protocol_runs')} WHERE blocked_code = 'protocol_contract_invalid') AS runs_contract_invalid,
            (
                SELECT COUNT(*)
                FROM {dialect.qualify('protocol_stage_executions')} pse
                JOIN {dialect.qualify('protocol_runs')} pr
                  ON pr.protocol_run_id = pse.protocol_run_id
                WHERE pse.status = 'running'
                  AND COALESCE(pse.lease_expires_at, '') <> ''
                  AND pse.lease_expires_at <= {dialect.placeholder(2)}
                  AND pr.status = 'running'
            ) AS stuck_leases,
            (
                SELECT COUNT(*)
                FROM {dialect.qualify('protocol_stage_executions')} pse
                JOIN {dialect.qualify('protocol_runs')} pr
                  ON pr.protocol_run_id = pse.protocol_run_id
                WHERE pse.status = 'running'
                  AND COALESCE(pse.timeout_at, '') <> ''
                  AND pse.timeout_at <= {dialect.placeholder(2)}
                  AND pr.status = 'running'
            ) AS overdue_timeouts
        """,
        (window_start, now_iso, now_iso),
    ) or {}

    connected = 0
    degraded = 0
    disconnected = 0
    execution_faulted = 0
    for row in agent_rows:
        state = effective_connectivity_state(row["connectivity_state"], row["last_heartbeat_at"])
        health = runtime_health_summary(row.get("runtime_health_json"))
        if state == "connected":
            connected += 1
        elif state == "degraded":
            degraded += 1
        else:
            disconnected += 1
        if str(health.execution_state or "healthy") == "faulted":
            execution_faulted += 1

    usage_rows = get_usage_summary(conn, dialect=dialect, since_iso=window_start, until_iso=now_iso)
    usage_total = aggregate_usage_totals(usage_rows)

    return RegistrySummaryRecord.model_validate({
        "generated_at": now_iso,
        "agents": {
            "total": len(agent_rows),
            "connected": connected,
            "degraded": degraded,
            "disconnected": disconnected,
            "execution_faulted": execution_faulted,
        },
        "conversations": {
            "total": int(conversation_totals.get("total") or 0),
            "active": int(conversation_totals.get("active") or 0),
            "pending_approvals": int(pending_approvals_row.get("cnt") or 0),
        },
        "tasks": {
            "running": int(task_totals.get("running") or 0),
            "pending": int(task_totals.get("pending") or 0),
            "failed_24h": int(task_totals.get("failed_24h") or 0),
        },
        "protocols": {
            "definitions_total": int(protocol_totals.get("definitions_total") or 0),
            "definitions_published": int(protocol_totals.get("definitions_published") or 0),
            "runs_total": int(protocol_totals.get("runs_total") or 0),
            "runs_active": int(protocol_totals.get("runs_active") or 0),
            "runs_blocked": int(protocol_totals.get("runs_blocked") or 0),
            "runs_failed_24h": int(protocol_totals.get("runs_failed_24h") or 0),
            "runs_contract_invalid": int(protocol_totals.get("runs_contract_invalid") or 0),
            "stuck_leases": int(protocol_totals.get("stuck_leases") or 0),
            "overdue_timeouts": int(protocol_totals.get("overdue_timeouts") or 0),
        },
        "usage_24h": usage_total,
    })


def list_approvals(
    conn,
    *,
    dialect: StoreDialect,
    for_agent_id: str | None = None,
    cursor: int = 0,
    limit: int = 25,
) -> list[ApprovalRecord]:
    fetch_limit = limit + 1
    params: list[object] = []
    sql = f"""
        SELECT
            e.event_id,
            e.conversation_id,
            e.actor,
            e.content,
            e.metadata_json,
            e.created_at,
            c.title,
            c.status AS conversation_status,
            c.updated_at AS conversation_updated_at,
            c.target_agent_id,
            a.display_name AS target_name
        FROM {dialect.qualify('events')} e
        JOIN {dialect.qualify('conversations')} c ON c.conversation_id = e.conversation_id
        LEFT JOIN {dialect.qualify('agents')} a ON a.agent_id = c.target_agent_id
        WHERE e.kind = 'approval.requested'
          AND e.seq = (
              SELECT MAX(e2.seq)
              FROM {dialect.qualify('events')} e2
              WHERE e2.conversation_id = e.conversation_id
                AND e2.kind IN ('approval.requested', 'approval.decided')
          )
    """
    if for_agent_id is not None:
        params.append(for_agent_id)
        sql += f" AND c.target_agent_id = {dialect.placeholder(len(params))}"
    params.extend([fetch_limit, cursor])
    sql += (
        f" ORDER BY e.created_at DESC LIMIT {dialect.placeholder(len(params) - 1)} "
        f"OFFSET {dialect.placeholder(len(params))}"
    )
    rows = dialect.fetchall(conn, sql, params)
    return records(ApprovalRecord, [
        {
            "request_id": row["event_id"],
            "conversation_id": row["conversation_id"],
            "conversation_title": row["title"],
            "conversation_status": row["conversation_status"],
            "conversation_updated_at": _stringify_timestamp(row["conversation_updated_at"]),
            "target_agent_id": row["target_agent_id"],
            "target_display_name": row["target_name"] or "",
            "actor": row["actor"],
            "content": row["content"],
            "created_at": _stringify_timestamp(row["created_at"]),
            **(
                lambda metadata: (
                    {
                        **{key: value for key, value in metadata.items() if key != "update_id"},
                        "recovery_id": metadata.get("recovery_id") or str(metadata.get("update_id") or ""),
                    }
                    if metadata.get("request_kind") == "recovery"
                    else metadata
                )
            )(decode_json_field(row["metadata_json"], {})),
        }
        for row in rows
    ])


def get_usage(
    conn,
    *,
    dialect: StoreDialect,
    agent_id: str = "",
    conversation_id: str = "",
    since: str = "",
    until: str = "",
) -> list[UsageSummaryRecord]:
    usage_predicate = dialect.usage_token_predicate("e.metadata_json")
    sql = (
        f"SELECT e.*, c.title AS conversation_title "
        f"FROM {dialect.qualify('events')} e "
        f"LEFT JOIN {dialect.qualify('conversations')} c ON c.conversation_id = e.conversation_id "
        f"WHERE (e.kind = 'provider.response' OR (e.kind = 'task.status' AND {usage_predicate}))"
    )
    params: list[object] = []
    if agent_id:
        params.append(agent_id)
        sql += f" AND e.agent_id = {dialect.placeholder(len(params))}"
    if conversation_id:
        params.append(conversation_id)
        sql += f" AND e.conversation_id = {dialect.placeholder(len(params))}"
    if since:
        params.append(since)
        sql += f" AND e.created_at >= {dialect.placeholder(len(params))}"
    if until:
        params.append(until)
        sql += f" AND e.created_at <= {dialect.placeholder(len(params))}"
    sql += " ORDER BY e.created_at"
    rows = dialect.fetchall(conn, sql, params)
    return records(UsageSummaryRecord, [
        {
            "event_id": row["event_id"],
            "conversation_id": row["conversation_id"],
            "title": row["conversation_title"] or "",
            "agent_id": row["agent_id"],
            "metadata": decode_json_field(row["metadata_json"], {}),
            "created_at": _stringify_timestamp(row["created_at"]),
        }
        for row in rows
    ])
