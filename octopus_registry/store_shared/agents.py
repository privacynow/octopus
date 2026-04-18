from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from octopus_sdk.exact_aliases import matches_exact_alias
from octopus_sdk.registry.models import AgentRecord, AgentStatusRecord
from octopus_sdk.registry.models import (
    AgentCard,
    AgentDiscoveryQuery,
    AgentHeartbeatRequest,
    AgentRegisterRequest,
    EnrollmentResult,
    HealthSummary,
    RuntimeWorkerRecord,
)
from psycopg.types.json import Jsonb

from octopus_registry.routing_skill_service import query_routing_skills
from octopus_registry.store_base import (
    canonical_registry_connectivity_state,
    decode_json_field,
    effective_connectivity_state,
    hash_agent_token,
    offline_before_iso,
    runtime_health_detail,
    runtime_health_execution_fields,
    runtime_health_generated_at,
    runtime_health_summary,
    validated_agent_card_payload,
    validated_heartbeat_payload,
    validated_register_payload,
    validated_registry_scope,
    validated_search_query,
)
from octopus_registry.store_dialect import StoreDialect
from octopus_registry.store_shared.common import record
from octopus_sdk.time_utils import utc_now_iso as utcnow_iso


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
    include_soft_deleted: bool = False,
) -> list[AgentRecord]:
    fetch_limit = limit + 1
    soft_delete_filter = "" if include_soft_deleted else " WHERE soft_deleted_at = ''"
    if q or connectivity_state:
        rows = dialect.fetchall(
            conn,
            f"SELECT * FROM {dialect.qualify('agents')}{soft_delete_filter} ORDER BY lower(display_name)",
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
        id_filter_clause = "WHERE agent_id = " + dialect.placeholder(1)
        if not include_soft_deleted:
            id_filter_clause += " AND soft_deleted_at = ''"
        rows = dialect.fetchall(
            conn,
            (
                f"SELECT * FROM {dialect.qualify('agents')} "
                f"{id_filter_clause} "
                f"ORDER BY lower(display_name) "
                f"LIMIT {dialect.placeholder(2)} OFFSET {dialect.placeholder(3)}"
            ),
            (for_agent_id, fetch_limit, cursor),
        )
    else:
        rows = dialect.fetchall(
            conn,
            (
                f"SELECT * FROM {dialect.qualify('agents')}{soft_delete_filter} "
                f"ORDER BY lower(display_name) "
                f"LIMIT {dialect.placeholder(1)} OFFSET {dialect.placeholder(2)}"
            ),
            (fetch_limit, cursor),
    )
    return [row_to_agent(row) for row in rows]


def agent_exists(
    conn,
    *,
    dialect: StoreDialect,
    agent_id: str,
) -> bool:
    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_agent_id:
        return False
    row = dialect.fetchone(
        conn,
        f"SELECT 1 AS ok FROM {dialect.qualify('agents')} WHERE agent_id = {dialect.placeholder(1)}",
        (normalized_agent_id,),
    )
    return row is not None


def row_to_agent(row) -> AgentRecord:
    effective_state = row.get("effective_state") or effective_connectivity_state(
        row["connectivity_state"], row["last_heartbeat_at"]
    )
    return record(AgentRecord, {
        **runtime_health_execution_fields(row.get("runtime_health_json")),
        "agent_id": row["agent_id"],
        "display_name": row["display_name"],
        "slug": row["slug"],
        "role": row["role"],
        "registry_scope": row.get("registry_scope", "full"),
        "routing_skills": decode_json_field(row["skills_json"], []),
        "tags": decode_json_field(row["tags_json"], []),
        "description": row["description"],
        "provider": row["provider"],
        "mode": row["mode"],
        "connectivity_state": effective_state,
        "current_capacity": row["current_capacity"],
        "max_capacity": row["max_capacity"],
        "channel_capabilities": decode_json_field(row.get("channel_capabilities_json"), []),
        "management_capabilities": decode_json_field(row.get("management_capabilities_json"), []),
        "version": row["version"],
        "trust_tier": str(row.get("trust_tier", "community") or "community"),
        "soft_deleted_at": str(row.get("soft_deleted_at", "") or ""),
        "last_heartbeat_at": row["last_heartbeat_at"],
        "updated_at": row["updated_at"],
        "runtime_health_summary": runtime_health_summary(row.get("runtime_health_json")),
        "runtime_health_generated_at": runtime_health_generated_at(row.get("runtime_health_json")),
    })


def replace_runtime_health_workers(
    conn,
    *,
    dialect: StoreDialect,
    agent_id: str,
    runtime_health_payload,
    mirrored_at: str,
) -> None:
    workers: list[RuntimeWorkerRecord] = []
    snapshot = getattr(runtime_health_payload, "snapshot", None)
    if snapshot is not None:
        raw_workers = snapshot.get("workers") or []
        if isinstance(raw_workers, list):
            for worker in raw_workers:
                try:
                    workers.append(RuntimeWorkerRecord.model_validate(worker))
                except Exception:
                    continue
    dialect.execute(
        conn,
        f"DELETE FROM {dialect.qualify('agent_runtime_workers')} WHERE agent_id = {dialect.placeholder(1)}",
        (agent_id,),
    )
    for worker in workers:
        dialect.execute(
            conn,
            f"""
            INSERT INTO {dialect.qualify('agent_runtime_workers')} (
                agent_id, worker_id, process_role, started_at, last_seen_at,
                current_item_id, current_conversation_key, current_kind,
                items_processed, stale_recoveries_seen, last_error, mirrored_at
            ) VALUES (
                {dialect.placeholder(1)},
                {dialect.placeholder(2)},
                {dialect.placeholder(3)},
                {dialect.placeholder(4)},
                {dialect.placeholder(5)},
                {dialect.placeholder(6)},
                {dialect.placeholder(7)},
                {dialect.placeholder(8)},
                {dialect.placeholder(9)},
                {dialect.placeholder(10)},
                {dialect.placeholder(11)},
                {dialect.placeholder(12)}
            )
            """,
            (
                agent_id,
                worker.worker_id,
                worker.process_role,
                worker.started_at,
                worker.last_seen_at,
                worker.current_item_id,
                worker.current_conversation_key,
                worker.current_kind,
                worker.items_processed,
                worker.stale_recoveries_seen,
                worker.last_error,
                mirrored_at,
            ),
        )


def runtime_worker_rows(
    conn,
    *,
    dialect: StoreDialect,
    agent_id: str,
) -> list[dict[str, object]]:
    rows = dialect.fetchall(
        conn,
        f"""
        SELECT *
        FROM {dialect.qualify('agent_runtime_workers')}
        WHERE agent_id = {dialect.placeholder(1)}
        ORDER BY worker_id ASC
        """,
        (agent_id,),
    )
    return [
        {
            "worker_id": row["worker_id"],
            "process_role": row["process_role"],
            "started_at": row["started_at"],
            "last_seen_at": row["last_seen_at"],
            "current_item_id": row["current_item_id"],
            "current_conversation_key": row["current_conversation_key"],
            "current_kind": row["current_kind"],
            "items_processed": row["items_processed"],
            "stale_recoveries_seen": row["stale_recoveries_seen"],
            "last_error": row["last_error"],
            "mirrored_at": row["mirrored_at"],
        }
        for row in rows
    ]


def resolve_agent_for_token(
    conn,
    *,
    token_row,
    agent_token: str,
) -> AgentRecord | None:
    row = token_row(conn, agent_token)
    return row_to_agent(row) if row else None


def enroll(
    conn,
    *,
    dialect: StoreDialect,
    ensure_unique_slug,
    registry_epoch,
    requested_card: AgentCard,
    now: str,
) -> EnrollmentResult:
    requested_payload = (
        requested_card.model_dump(mode="json")
        if hasattr(requested_card, "model_dump")
        else requested_card
    )
    card = validated_agent_card_payload(requested_payload, require_registry_scope=True)
    bot_key = str(card.get("bot_key", "") or "").strip()
    if not bot_key:
        raise ValueError("bot_key requires non-empty text")
    existing = dialect.fetchone(
        conn,
        f"SELECT agent_id, slug FROM {dialect.qualify('agents')} WHERE bot_key = {dialect.placeholder(1)}",
        (bot_key,),
    )
    if existing:
        agent_token = secrets.token_urlsafe(32)
        dialect.execute(
            conn,
            (
                f"UPDATE {dialect.qualify('agents')} "
                f"SET agent_token = {dialect.placeholder(1)}, updated_at = {dialect.placeholder(2)} "
                f"WHERE bot_key = {dialect.placeholder(3)}"
            ),
            (hash_agent_token(agent_token), now, bot_key),
        )
        return record(EnrollmentResult, {
            "agent_id": existing["agent_id"],
            "slug": existing["slug"],
            "agent_token": agent_token,
            "poll_cursor": "0",
            "registry_epoch": registry_epoch(conn),
        })
    agent_id = secrets.token_hex(16)
    agent_token = secrets.token_urlsafe(32)
    slug = ensure_unique_slug(conn, card.get("slug") or "agent")
    dialect.execute(
        conn,
        f"""
        INSERT INTO {dialect.qualify('agents')} (
            agent_id, agent_token, display_name, slug, role, registry_scope,
            skills_json, tags_json, description, provider, mode,
            connectivity_state, current_capacity, max_capacity,
            channel_capabilities_json, management_capabilities_json, version, bot_key,
            created_at, updated_at, last_heartbeat_at
        ) VALUES (
            {dialect.placeholder(1)},
            {dialect.placeholder(2)},
            {dialect.placeholder(3)},
            {dialect.placeholder(4)},
            {dialect.placeholder(5)},
            {dialect.placeholder(6)},
            {dialect.placeholder(7)},
            {dialect.placeholder(8)},
            {dialect.placeholder(9)},
            {dialect.placeholder(10)},
            {dialect.placeholder(11)},
            {dialect.placeholder(12)},
            {dialect.placeholder(13)},
            {dialect.placeholder(14)},
            {dialect.placeholder(15)},
            {dialect.placeholder(16)},
            {dialect.placeholder(17)},
            {dialect.placeholder(18)},
            {dialect.placeholder(19)},
            {dialect.placeholder(20)},
            {dialect.placeholder(21)}
        )
        """,
        (
            agent_id,
            hash_agent_token(agent_token),
            card.get("display_name") or slug,
            slug,
            card.get("role", ""),
            validated_registry_scope(card.get("registry_scope")),
            Jsonb(card.get("routing_skills", [])),
            Jsonb(card.get("tags", [])),
            card.get("description", ""),
            card.get("provider", ""),
            card.get("mode", "registry"),
            canonical_registry_connectivity_state(card.get("connectivity_state", "degraded")),
            card.get("current_capacity", 0),
            card.get("max_capacity", 1),
            Jsonb(card.get("channel_capabilities", [])),
            Jsonb(card.get("management_capabilities", [])),
            card.get("version", ""),
            bot_key,
            now,
            now,
            now,
        ),
    )
    return record(EnrollmentResult, {
        "agent_id": agent_id,
        "slug": slug,
        "agent_token": agent_token,
        "poll_cursor": "0",
        "registry_epoch": registry_epoch(conn),
    })


def register(
    conn,
    *,
    dialect: StoreDialect,
    token_row,
    agent_token: str,
    payload: AgentRegisterRequest,
) -> AgentRecord:
    row = token_row(conn, agent_token)
    if row is None:
        raise PermissionError("Unknown agent token")
    now = utcnow_iso()
    register_payload = validated_register_payload(
        payload.model_dump(mode="json", exclude_none=True, exclude_defaults=True)
        if hasattr(payload, "model_dump")
        else payload
    )
    card = register_payload.agent_card
    requested_bot_key = str(card.bot_key or "").strip()
    current_bot_key = str(row["bot_key"] or "").strip()
    if requested_bot_key and requested_bot_key != current_bot_key:
        raise ValueError("bot_key must match the enrolled agent identity")
    current_skills = decode_json_field(row.get("skills_json"), [])
    current_tags = decode_json_field(row.get("tags_json"), [])
    current_channel_capabilities = decode_json_field(row.get("channel_capabilities_json"), [])
    current_management_capabilities = decode_json_field(row.get("management_capabilities_json"), [])
    dialect.execute(
        conn,
        f"""
        UPDATE {dialect.qualify('agents')}
        SET display_name = {dialect.placeholder(1)},
            role = {dialect.placeholder(2)},
            registry_scope = {dialect.placeholder(3)},
            skills_json = {dialect.placeholder(4)},
            tags_json = {dialect.placeholder(5)},
            description = {dialect.placeholder(6)},
            provider = {dialect.placeholder(7)},
            mode = {dialect.placeholder(8)},
            connectivity_state = {dialect.placeholder(9)},
            current_capacity = {dialect.placeholder(10)},
            max_capacity = {dialect.placeholder(11)},
            channel_capabilities_json = {dialect.placeholder(12)},
            management_capabilities_json = {dialect.placeholder(13)},
            version = {dialect.placeholder(14)},
            updated_at = {dialect.placeholder(15)},
            last_heartbeat_at = {dialect.placeholder(16)}
        WHERE agent_token = {dialect.placeholder(17)}
        """,
        (
            card.display_name or row["display_name"],
            card.role or row["role"],
            card.registry_scope or row["registry_scope"],
            Jsonb(card.routing_skills or current_skills),
            Jsonb(card.tags or current_tags),
            card.description or row["description"],
            card.provider or row["provider"],
            card.mode or row["mode"],
            canonical_registry_connectivity_state(register_payload.connectivity_state or row["connectivity_state"]),
            row["current_capacity"] if register_payload.current_capacity is None else register_payload.current_capacity,
            row["max_capacity"] if register_payload.max_capacity is None else register_payload.max_capacity,
            Jsonb(card.channel_capabilities or current_channel_capabilities),
            Jsonb(card.management_capabilities or current_management_capabilities),
            card.version or row["version"],
            now,
            now,
            hash_agent_token(agent_token),
        ),
    )
    updated = token_row(conn, agent_token)
    assert updated is not None
    return row_to_agent(updated)


def heartbeat(
    conn,
    *,
    dialect: StoreDialect,
    token_row,
    replace_runtime_health_workers,
    agent_token: str,
    payload: AgentHeartbeatRequest,
) -> HealthSummary:
    row = token_row(conn, agent_token)
    if row is None:
        raise PermissionError("Unknown agent token")
    now = utcnow_iso()
    heartbeat_payload = validated_heartbeat_payload(
        payload.model_dump(mode="json", exclude_none=True) if hasattr(payload, "model_dump") else payload
    )
    previous_effective_state = effective_connectivity_state(
        row["connectivity_state"],
        row["last_heartbeat_at"],
    )
    runtime_health_payload = heartbeat_payload.runtime_health
    runtime_health_json = (
        runtime_health_payload.model_dump(mode="json")
        if hasattr(runtime_health_payload, "model_dump")
        else runtime_health_payload
    )
    dialect.execute(
        conn,
        f"""
        UPDATE {dialect.qualify('agents')}
        SET connectivity_state = {dialect.placeholder(1)},
            current_capacity = {dialect.placeholder(2)},
            max_capacity = {dialect.placeholder(3)},
            updated_at = {dialect.placeholder(4)},
            last_heartbeat_at = {dialect.placeholder(5)},
            runtime_health_json = {dialect.placeholder(6)}
        WHERE agent_token = {dialect.placeholder(7)}
        """,
        (
            canonical_registry_connectivity_state(heartbeat_payload.connectivity_state or row["connectivity_state"]),
            row["current_capacity"] if heartbeat_payload.current_capacity is None else heartbeat_payload.current_capacity,
            row["max_capacity"] if heartbeat_payload.max_capacity is None else heartbeat_payload.max_capacity,
            now,
            now,
            Jsonb(runtime_health_json if runtime_health_payload is not None else decode_json_field(row.get("runtime_health_json"), {})),
            hash_agent_token(agent_token),
        ),
    )
    if runtime_health_payload is not None:
        replace_runtime_health_workers(
            conn,
            agent_id=row["agent_id"],
            runtime_health_payload=runtime_health_payload,
            mirrored_at=now,
        )
    current_agent = row_to_agent(token_row(conn, agent_token))
    return record(HealthSummary, {
        "agent": current_agent,
        "collections_changed": previous_effective_state != current_agent["connectivity_state"],
        "server_time": now,
    })


def search_agents(
    conn,
    *,
    dialect: StoreDialect,
    disabled_skill_names: set[str],
    query: AgentDiscoveryQuery,
) -> list[AgentRecord]:
    validated_query = validated_search_query(
        query.model_dump(mode="json") if hasattr(query, "model_dump") else query
    )
    role = validated_query.get("role", "").strip().lower()
    required_state = validated_query.get("required_state", "connected")
    skills = query_routing_skills(validated_query) - disabled_skill_names
    tags = {t.lower() for t in validated_query.get("tags", []) if t}
    free_text = validated_query.get("free_text", "").strip()
    exclude = sorted(set(validated_query.get("exclude_agent_ids", [])))
    if validated_query.get("skills") and not skills:
        return []
    sql = [
        f"""
        WITH agent_rows AS (
            SELECT
                a.*,
                CASE
                    WHEN coalesce(a.last_heartbeat_at, '') != ''
                         AND a.last_heartbeat_at::timestamptz < {dialect.placeholder(1)}::timestamptz
                    THEN 'disconnected'
                    WHEN a.connectivity_state = 'offline' THEN 'disconnected'
                    ELSE a.connectivity_state
                END AS effective_state
            FROM {dialect.qualify('agents')} a
        )
        SELECT *
        FROM agent_rows
        WHERE 1 = 1
        """
    ]
    params: list[object] = [offline_before_iso()]
    if exclude:
        sql.append(f" AND agent_id != ALL({dialect.placeholder(len(params) + 1)})")
        params.append(exclude)
    if required_state:
        sql.append(f" AND effective_state = {dialect.placeholder(len(params) + 1)}")
        params.append(required_state)
    if role:
        sql.append(f" AND role ILIKE {dialect.placeholder(len(params) + 1)}")
        params.append(f"%{role}%")
    for skill_name in sorted(skills):
        sql.append(
            f"""
            AND EXISTS (
                SELECT 1
                FROM jsonb_array_elements_text(agent_rows.skills_json) AS je(value)
                WHERE lower(je.value) = {dialect.placeholder(len(params) + 1)}
            )
            """
        )
        params.append(skill_name)
    for tag in sorted(tags):
        sql.append(
            f"""
            AND EXISTS (
                SELECT 1
                FROM jsonb_array_elements_text(agent_rows.tags_json) AS je(value)
                WHERE lower(je.value) = {dialect.placeholder(len(params) + 1)}
            )
            """
        )
        params.append(tag)
    if free_text:
        like = f"%{free_text}%"
        if disabled_skill_names:
            sql.append(
                f"""
                AND (
                    display_name ILIKE {dialect.placeholder(len(params) + 1)}
                    OR role ILIKE {dialect.placeholder(len(params) + 2)}
                    OR description ILIKE {dialect.placeholder(len(params) + 3)}
                    OR EXISTS (
                        SELECT 1
                        FROM jsonb_array_elements_text(agent_rows.skills_json) AS je(value)
                        WHERE je.value ILIKE {dialect.placeholder(len(params) + 4)}
                          AND lower(je.value) != ALL({dialect.placeholder(len(params) + 5)})
                    )
                    OR EXISTS (
                        SELECT 1
                        FROM jsonb_array_elements_text(agent_rows.tags_json) AS je(value)
                        WHERE je.value ILIKE {dialect.placeholder(len(params) + 6)}
                    )
                )
                """
            )
            params.extend([like, like, like, like, sorted(disabled_skill_names), like])
        else:
            sql.append(
                f"""
                AND (
                    display_name ILIKE {dialect.placeholder(len(params) + 1)}
                    OR role ILIKE {dialect.placeholder(len(params) + 2)}
                    OR description ILIKE {dialect.placeholder(len(params) + 3)}
                    OR EXISTS (
                        SELECT 1
                        FROM jsonb_array_elements_text(agent_rows.skills_json) AS je(value)
                        WHERE je.value ILIKE {dialect.placeholder(len(params) + 4)}
                    )
                    OR EXISTS (
                        SELECT 1
                        FROM jsonb_array_elements_text(agent_rows.tags_json) AS je(value)
                        WHERE je.value ILIKE {dialect.placeholder(len(params) + 5)}
                    )
                )
                """
            )
            params.extend([like, like, like, like, like])
    sql.append(" ORDER BY lower(display_name)")
    rows = dialect.fetchall(conn, "".join(sql), params)
    agents = [row_to_agent(row) for row in rows]
    return [agent for agent in agents if str(agent.execution_state or "healthy") != "faulted"]


def selector_candidates(
    conn,
    *,
    dialect: StoreDialect,
    selector,
) -> list[dict[str, object]]:
    rows = dialect.fetchall(
        conn,
        f"""
        WITH agent_rows AS (
            SELECT
                a.*,
                CASE
                    WHEN a.last_heartbeat_at != '' AND a.last_heartbeat_at < {dialect.placeholder(1)} THEN 'disconnected'
                    WHEN a.connectivity_state = 'offline' THEN 'disconnected'
                    ELSE a.connectivity_state
                END AS effective_state
            FROM {dialect.qualify('agents')} a
        )
        SELECT *
        FROM agent_rows
        WHERE effective_state = 'connected'
        ORDER BY lower(display_name), agent_id
        """,
        (offline_before_iso(),),
    )
    value = selector.value.strip().lower()
    matches: list[dict[str, object]] = []
    for row in rows:
        if selector.kind == "agent":
            if matches_exact_alias(
                value,
                identifier=str(row["agent_id"] or "").strip().lower(),
                slug=str(row["slug"] or "").strip().lower(),
                display_name=str(row["display_name"] or ""),
            ):
                matches.append(row)
        elif selector.kind == "skill":
            caps = {str(item).strip().lower() for item in decode_json_field(row["skills_json"], []) if item}
            if value in caps:
                matches.append(row)
        elif selector.kind == "role":
            role_value = str(row["role"] or "").strip().lower()
            if role_value == value or value in role_value:
                matches.append(row)
    return matches


def resolve_selector(
    conn,
    *,
    dialect: StoreDialect,
    selector,
) -> dict[str, object]:
    matches = selector_candidates(conn, dialect=dialect, selector=selector)
    preferred = selector.preferred_agent_id.strip()
    if preferred:
        preferred_matches = [row for row in matches if str(row["agent_id"] or "").strip() == preferred]
        if not preferred_matches:
            raise ValueError(
                f"Selector {selector.kind}:{selector.value} does not resolve to preferred agent {preferred}"
            )
        return preferred_matches[0]
    if not matches:
        raise ValueError(f"No connected agent matches {selector.kind}:{selector.value}")
    if len(matches) > 1:
        labels = ", ".join(str(row["slug"] or row["agent_id"] or "").strip() for row in matches[:5])
        raise ValueError(
            f"Selector {selector.kind}:{selector.value} is ambiguous across {len(matches)} agents: {labels}"
        )
    return matches[0]


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
            "runtime_health_detail": runtime_health_detail(
                row.get("runtime_health_json"),
                workers,
            ),
        },
    )
