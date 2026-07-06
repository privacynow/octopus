"""Postgres connectivity and current-schema validation."""

from __future__ import annotations

from typing import Any

_REQUIRED_TABLES: dict[str, tuple[str, ...]] = {
    "bot_runtime": (
        "sessions",
        "updates",
        "work_items",
        "worker_heartbeats",
        "user_access",
        "usage_log",
        "control_plane_commands",
        "deferred_notifications",
    ),
    "agent_registry": (
        "meta",
        "agents",
        "agent_runtime_workers",
        "deliveries",
        "management_requests",
        "conversations",
        "routed_tasks",
        "events",
        "protocol_definitions",
        "protocol_definition_versions",
        "protocol_runs",
        "protocol_run_participants",
        "protocol_stage_executions",
        "protocol_artifacts",
        "protocol_transitions",
        "protocol_runtime_capability_tokens",
        "protocol_idempotency",
        "protocol_compliance_events",
        "skills_override",
        "runtime_skills",
        "skill_revisions",
        "skill_approvals",
        "provider_guidance",
        "guidance_revisions",
        "guidance_approvals",
    ),
    "bot_content": (
        "skill_namespaces",
        "skill_tracks",
        "skill_revisions",
        "skill_files",
        "provider_guidance_tracks",
        "provider_guidance_revisions",
        "skill_approval_records",
        "provider_guidance_approval_records",
    ),
    "bot_credentials": ("credentials",),
}
_REQUIRED_COLUMNS: dict[tuple[str, str], tuple[str, ...]] = {
    ("bot_runtime", "sessions"): ("conversation_key",),
    ("bot_runtime", "updates"): ("event_id", "conversation_key", "actor_key"),
    ("bot_runtime", "work_items"): (
        "event_id",
        "conversation_key",
        "dispatch_mode",
        "cancel_requested_by",
        "cancel_request_event_id",
    ),
    ("bot_runtime", "user_access"): ("actor_key", "granted_by"),
    ("bot_runtime", "usage_log"): ("conversation_key",),
    ("agent_registry", "agents"): (
        "bot_key",
        "registry_scope",
        "transport_implementations",
        "supported_admin_operations",
        "runtime_health_json",
    ),
    ("agent_registry", "conversations"): ("conversation_type",),
    ("agent_registry", "protocol_definitions"): (
        "owner_org_id",
        "visibility",
        "created_by",
        "updated_by",
        "draft_definition_json",
        "draft_content_hash",
    ),
    ("agent_registry", "protocol_definition_versions"): ("published_by",),
    ("agent_registry", "protocol_runs"): (
        "blocked_code",
        "blocked_detail",
        "run_org_id",
        "started_by",
        "version",
        "retention_until",
        "last_transition_at",
    ),
    ("agent_registry", "protocol_run_participants"): (
        "resolution_outcome",
        "resolution_reason",
        "selector_snapshot_json",
    ),
    ("agent_registry", "protocol_stage_executions"): ("timeout_at", "lease_owner", "lease_expires_at"),
    ("agent_registry", "protocol_artifacts"): (
        "size_bytes",
        "exists",
        "modified_at",
        "observed_at",
        "verification_state",
    ),
    ("agent_registry", "protocol_transitions"): ("error_code", "metadata_json"),
    ("agent_registry", "protocol_runtime_capability_tokens"): (
        "capability_ref_hash",
        "bearer_token_hash",
        "protocol_run_id",
        "protocol_stage_execution_id",
        "allowed_actions_json",
        "expires_at",
        "revoked_at",
    ),
    ("bot_content", "skill_revisions"): ("skill_kind",),
}
_REQUIRED_INDEX = "idx_one_claimed_per_conv"


def run_doctor(conn: Any) -> list[str]:
    """Validate connectivity, current tables/columns, and required indexes."""
    errors: list[str] = []
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_schema = ANY(%s)
            """,
            (list(_REQUIRED_TABLES),),
        )
        by_schema: dict[str, set[str]] = {}
        for schema_name, table_name in cur.fetchall():
            by_schema.setdefault(str(schema_name), set()).add(str(table_name))
    for schema_name, required_tables in _REQUIRED_TABLES.items():
        existing_tables = by_schema.get(schema_name)
        if not existing_tables:
            errors.append(f"Schema '{schema_name}' does not exist. Run DB init.")
            continue
        for table in required_tables:
            if table not in existing_tables:
                errors.append(f"Table {schema_name}.{table} missing. Run DB init.")

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_schema, table_name, column_name
            FROM information_schema.columns
            WHERE table_schema = ANY(%s)
            """,
            (list(_REQUIRED_TABLES),),
        )
        columns: dict[tuple[str, str], set[str]] = {}
        for schema_name, table_name, column_name in cur.fetchall():
            columns.setdefault((str(schema_name), str(table_name)), set()).add(str(column_name))
    for key, required_columns in _REQUIRED_COLUMNS.items():
        existing_columns = columns.get(key, set())
        for column in required_columns:
            if column not in existing_columns:
                errors.append(f"Column {key[0]}.{key[1]}.{column} missing. Run DB init.")

    # Required partial unique index: exactly UNIQUE ON (conversation_key) WHERE (state = 'claimed')
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.oid,
                   i.indisunique,
                   pg_get_expr(i.indpred, i.indrelid) AS pred
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = 'bot_runtime'
            JOIN pg_index i ON i.indexrelid = c.oid
            JOIN pg_class t ON t.oid = i.indrelid AND t.relname = 'work_items'
            WHERE c.relkind = 'i' AND c.relname = %s
            """,
            (_REQUIRED_INDEX,),
        )
        row = cur.fetchone()
    if row is None:
        errors.append(f"Index bot_runtime.work_items.{_REQUIRED_INDEX} missing. Run DB init.")
        return errors
    index_oid, is_unique, pred = row[0], row[1], (row[2] or "")
    if not is_unique:
        errors.append(f"Index bot_runtime.work_items.{_REQUIRED_INDEX} must be UNIQUE. Run DB init.")
    # Exact column list: must be exactly (conversation_key), no extra columns
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT array_agg(a.attname) AS cols
            FROM pg_index i, pg_attribute a
            WHERE i.indexrelid = %s AND a.attrelid = i.indrelid
              AND a.attnum = ANY(i.indkey) AND a.attnum > 0 AND NOT a.attisdropped
            """,
            (index_oid,),
        )
        col_row = cur.fetchone()
    cols = sorted(col_row[0]) if col_row and col_row[0] else []
    if cols != ["conversation_key"]:
        errors.append(
            f"Index bot_runtime.work_items.{_REQUIRED_INDEX} must be on (conversation_key) only, got {cols}. Run DB init."
        )
    # Exact predicate: WHERE (state = 'claimed') only (Postgres may show (state = 'claimed'::text))
    pred_normalized = " ".join((pred or "").split()).strip()
    pred_canonical = pred_normalized.replace("::text", "").replace("::character varying", "")
    if pred_canonical != "(state = 'claimed')":
        errors.append(
            f"Index bot_runtime.work_items.{_REQUIRED_INDEX} must be partial WHERE (state = 'claimed') only, got {pred!r}. Run DB init."
        )

    return errors
