"""Tests for Postgres DB init, doctor, and CLI."""

from io import StringIO

import pytest

from app.db.postgres_doctor import run_doctor
from app.db.postgres_init import run_init


def test_run_init_applies_current_schema(postgres_base_url, request):
    """DB init applies the full current schema to an empty database."""
    from app.db.postgres import get_connection
    from tests.support.postgres_support import _replace_db_in_url, create_test_database, get_worker_id

    worker_id = get_worker_id(request.config)
    db_name = f"test_bot_registry_init_{worker_id}".replace("-", "_")
    db_url = _replace_db_in_url(postgres_base_url, db_name)
    create_test_database(postgres_base_url, db_name)

    with get_connection(db_url) as conn:
        errors = run_init(conn)
        assert errors == []

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'agent_registry'
                  AND table_name = 'agents'
                ORDER BY ordinal_position
                """
            )
            agent_columns = {row[0] for row in cur.fetchall()}

    assert "channel_capabilities_json" in agent_columns
    assert "registry_scope" in agent_columns
    assert "runtime_health_json" in agent_columns
    assert "bot_key" in agent_columns


def test_doctor_passes_after_init(postgres_truncated):
    """With Postgres harness: current-schema init then doctor returns no errors."""
    from app.db.postgres import get_connection

    with get_connection(postgres_truncated) as conn:
        errors = run_doctor(conn)
    assert errors == []


def test_run_init_is_noop_on_current_db(postgres_truncated):
    """run_init() on an already-current DB should be a no-op."""
    from app.db.postgres import get_connection

    with get_connection(postgres_truncated) as conn:
        errors = run_init(conn)
    assert errors == []


def test_run_init_does_not_seed_builtin_protocols_into_authored_definitions(postgres_base_url, request):
    """DB init leaves builtin protocol examples out of authored protocol rows."""
    from app.db.postgres import get_connection
    from tests.support.postgres_support import _replace_db_in_url, create_test_database, get_worker_id

    worker_id = get_worker_id(request.config)
    db_name = f"test_bot_registry_builtin_seed_{worker_id}".replace("-", "_")
    db_url = _replace_db_in_url(postgres_base_url, db_name)
    create_test_database(postgres_base_url, db_name)

    with get_connection(db_url) as conn:
        errors = run_init(conn)
        assert errors == []

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT slug, lifecycle_state
                FROM agent_registry.protocol_definitions
                WHERE slug = 'software-engineering'
                """
            )
            row = cur.fetchone()

    assert row is None


def test_run_init_restores_missing_additive_schema_objects(postgres_truncated):
    """run_init() recreates missing additive objects from the canonical init.sql."""
    from app.db.postgres import get_connection

    with get_connection(postgres_truncated) as conn:
        with conn.cursor() as cur:
            cur.execute("DROP TABLE agent_registry.protocol_transitions CASCADE")
            cur.execute("DROP TABLE agent_registry.protocol_artifacts CASCADE")
            cur.execute("DROP TABLE agent_registry.protocol_stage_executions CASCADE")
            cur.execute("DROP TABLE agent_registry.protocol_run_participants CASCADE")
            cur.execute("DROP TABLE agent_registry.protocol_runs CASCADE")
            cur.execute("DROP TABLE agent_registry.protocol_definition_versions CASCADE")
            cur.execute("DROP TABLE agent_registry.protocol_definitions CASCADE")
        conn.commit()

        errors = run_init(conn)
        assert errors == []
        assert run_doctor(conn) == []

        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('agent_registry.protocol_definitions')")
            assert cur.fetchone()[0] == "agent_registry.protocol_definitions"


def test_run_init_restores_missing_additive_protocol_columns(postgres_truncated):
    """run_init() adds newly introduced protocol columns onto existing tables."""
    from app.db.postgres import get_connection

    with get_connection(postgres_truncated) as conn:
        with conn.cursor() as cur:
            cur.execute("ALTER TABLE agent_registry.protocol_definitions DROP COLUMN owner_org_id")
            cur.execute("ALTER TABLE agent_registry.protocol_definition_versions DROP COLUMN published_by")
            cur.execute("ALTER TABLE agent_registry.protocol_runs DROP COLUMN blocked_code")
            cur.execute("ALTER TABLE agent_registry.protocol_run_participants DROP COLUMN resolution_outcome")
            cur.execute("ALTER TABLE agent_registry.protocol_stage_executions DROP COLUMN timeout_at")
            cur.execute("ALTER TABLE agent_registry.protocol_artifacts DROP COLUMN verification_state")
            cur.execute("ALTER TABLE agent_registry.protocol_transitions DROP COLUMN error_code")
        conn.commit()

        errors = run_init(conn)
        assert errors == []
        assert run_doctor(conn) == []


def test_registry_init_schema_matches_current_store_contract(postgres_truncated):
    """Fresh Postgres init exposes the current registry tables/columns/defaults."""
    from app.db.postgres import get_connection

    expected_columns = {
        "agents": {
            "agent_id",
            "agent_token",
            "bot_key",
            "display_name",
            "slug",
            "role",
            "registry_scope",
            "skills_json",
            "tags_json",
            "description",
            "provider",
            "mode",
            "connectivity_state",
            "current_capacity",
            "max_capacity",
            "channel_capabilities_json",
            "management_capabilities_json",
            "version",
            "runtime_health_json",
            "trust_tier",
            "soft_deleted_at",
            "created_at",
            "updated_at",
            "last_heartbeat_at",
        },
        "agent_runtime_workers": {
            "agent_id",
            "worker_id",
            "process_role",
            "started_at",
            "last_seen_at",
            "current_item_id",
            "current_conversation_key",
            "current_kind",
            "items_processed",
            "stale_recoveries_seen",
            "last_error",
            "mirrored_at",
        },
        "deliveries": {
            "seq",
            "delivery_id",
            "target_agent_id",
            "kind",
            "payload_json",
            "state",
            "created_at",
            "updated_at",
            "leased_at",
            "acked_at",
        },
        "management_requests": {
            "request_id",
            "target_agent_id",
            "operation",
            "capability",
            "payload_json",
            "status",
            "delivery_id",
            "result_json",
            "error_code",
            "error_detail",
            "created_at",
            "completed_at",
        },
        "conversations": {
            "conversation_id",
            "target_agent_id",
            "title",
            "conversation_type",
            "origin_channel",
            "external_conversation_ref",
            "status",
            "created_at",
            "updated_at",
        },
        "events": {
            "seq",
            "event_id",
            "conversation_id",
            "agent_id",
            "kind",
            "actor",
            "content",
            "metadata_json",
            "created_at",
        },
        "guidance_approvals": {
            "record_id",
            "provider",
            "scope_kind",
            "scope_key",
            "revision_id",
            "action",
            "actor",
            "note",
            "created_at",
        },
        "guidance_revisions": {
            "revision_id",
            "provider",
            "scope_kind",
            "scope_key",
            "content",
            "format",
            "status",
            "created_by",
            "created_at",
        },
        "provider_guidance": {
            "provider",
            "scope_kind",
            "scope_key",
            "content",
            "format",
            "is_mutable",
            "active_revision_id",
            "published_revision_id",
            "created_at",
            "updated_at",
        },
        "runtime_skills": {
            "slug",
            "display_name",
            "description",
            "source_kind",
            "source_uri",
            "owner_actor",
            "visibility",
            "is_mutable",
            "archived",
            "instruction_body",
            "requirements_json",
            "provider_config_json",
            "files_json",
            "active_revision_id",
            "published_revision_id",
            "created_at",
            "updated_at",
        },
        "skill_approvals": {
            "record_id",
            "slug",
            "revision_id",
            "action",
            "actor",
            "note",
            "created_at",
        },
        "skill_revisions": {
            "revision_id",
            "slug",
            "instruction_body",
            "requirements_json",
            "provider_config_json",
            "files_json",
            "version_label",
            "changelog",
            "status",
            "created_by",
            "created_at",
        },
        "routed_tasks": {
            "routed_task_id",
            "parent_conversation_id",
            "origin_agent_id",
            "target_agent_id",
            "title",
            "request_json",
            "status",
            "summary",
            "result_json",
            "created_at",
            "updated_at",
        },
        "protocol_definitions": {
            "protocol_id",
            "slug",
            "display_name",
            "description",
            "lifecycle_state",
            "current_version_id",
            "owner_org_id",
            "visibility",
            "created_by",
            "updated_by",
            "draft_definition_json",
            "draft_content_hash",
            "draft_revision",
            "created_at",
            "updated_at",
        },
        "protocol_definition_versions": {
            "protocol_definition_version_id",
            "protocol_id",
            "version",
            "definition_json",
            "content_hash",
            "validation_status",
            "published_at",
            "published_by",
            "created_at",
        },
        "protocol_runs": {
            "protocol_run_id",
            "protocol_id",
            "protocol_definition_version_id",
            "entry_agent_id",
            "entry_authority_ref",
            "is_rehearsal",
            "root_conversation_id",
            "origin_channel",
            "workspace_ref",
            "repo_ref",
            "branch_ref",
            "problem_statement",
            "constraints_json",
            "status",
            "current_stage_execution_id",
            "current_stage_key",
            "termination_summary",
            "blocked_code",
            "blocked_detail",
            "run_org_id",
            "started_by",
            "version",
            "retention_until",
            "last_transition_at",
            "created_at",
            "updated_at",
            "completed_at",
        },
        "protocol_scenarios": {
            "protocol_scenario_id",
            "protocol_id",
            "stage_key",
            "participant_key",
            "display_name",
            "decision",
            "decision_summary",
            "response_text",
            "run_org_id",
            "created_by",
            "created_at",
            "updated_at",
        },
        "protocol_run_participants": {
            "protocol_run_participant_id",
            "protocol_run_id",
            "participant_key",
            "display_name",
            "required_skills_json",
            "target_selector_json",
            "resolved_agent_id",
            "resolved_authority_ref",
            "session_key",
            "state",
            "resolution_outcome",
            "resolution_reason",
            "selector_snapshot_json",
            "created_at",
            "updated_at",
        },
        "protocol_stage_executions": {
            "protocol_stage_execution_id",
            "protocol_run_id",
            "stage_key",
            "participant_key",
            "attempt",
            "loop_iteration",
            "status",
            "decision",
            "decision_summary",
            "input_snapshot_json",
            "routed_task_id",
            "failure_code",
            "failure_detail",
            "timeout_at",
            "lease_owner",
            "lease_expires_at",
            "started_at",
            "completed_at",
        },
        "protocol_artifacts": {
            "protocol_artifact_id",
            "protocol_run_id",
            "artifact_key",
            "artifact_kind",
            "location",
            "workspace_path",
            "content_hash",
            "size_bytes",
            "exists",
            "modified_at",
            "observed_at",
            "verification_state",
            "produced_by_stage_execution_id",
            "state",
            "supersedes_protocol_artifact_id",
            "created_at",
        },
        "protocol_transitions": {
            "protocol_transition_id",
            "protocol_run_id",
            "from_stage_execution_id",
            "to_stage_execution_id",
            "transition_kind",
            "decision",
            "reason",
            "error_code",
            "metadata_json",
            "actor_type",
            "actor_ref",
            "created_at",
        },
        "protocol_idempotency": {
            "protocol_idempotency_id",
            "scope_kind",
            "scope_ref",
            "action_name",
            "idempotency_key",
            "request_hash",
            "response_json",
            "created_at",
        },
        "protocol_compliance_events": {
            "protocol_compliance_event_id",
            "protocol_run_id",
            "protocol_definition_version_id",
            "event_kind",
            "actor_ref",
            "actor_role",
            "summary",
            "metadata_json",
            "created_at",
        },
        "skills_override": {"skill_name", "enabled", "set_by", "set_at"},
        "meta": {"key", "value"},
    }

    with get_connection(postgres_truncated) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name, column_name, column_default
                FROM information_schema.columns
                WHERE table_schema = 'agent_registry'
                ORDER BY table_name, ordinal_position
                """
            )
            rows = cur.fetchall()

    by_table: dict[str, set[str]] = {}
    defaults: dict[tuple[str, str], str] = {}
    for table_name, column_name, column_default in rows:
        by_table.setdefault(table_name, set()).add(column_name)
        defaults[(table_name, column_name)] = column_default or ""

    assert by_table == expected_columns
    assert defaults[("agents", "registry_scope")].startswith("'full'")
    assert "jsonb" in defaults[("agents", "channel_capabilities_json")]
    assert "jsonb" in defaults[("agents", "runtime_health_json")]
    assert defaults[("conversations", "conversation_type")].startswith("'conversation'")
    assert defaults[("conversations", "origin_channel")].startswith("'registry'")
    assert "jsonb" in defaults[("events", "metadata_json")]
    assert defaults[("protocol_definitions", "visibility")].startswith("'org_private'")
    assert defaults[("protocol_runs", "status")].startswith("'queued'")
    assert "jsonb" in defaults[("protocol_transitions", "metadata_json")]


def test_run_init_rejects_non_current_existing_schema(postgres_base_url, request):
    """Init refuses older or partial schema states instead of migrating them."""
    from app.db.postgres import get_connection
    from tests.support.postgres_support import _replace_db_in_url, create_test_database, get_worker_id

    worker_id = get_worker_id(request.config)
    db_name = f"test_bot_legacy_{worker_id}".replace("-", "_")
    db_url = _replace_db_in_url(postgres_base_url, db_name)
    create_test_database(postgres_base_url, db_name)

    with get_connection(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE SCHEMA bot_runtime")
            cur.execute("CREATE TABLE bot_runtime.sessions (chat_id BIGINT PRIMARY KEY)")
        conn.commit()
        errors = run_init(conn)

    assert errors
    assert "do not match the current build" in errors[0]


def test_cli_doctor_exits_when_no_database_url(monkeypatch):
    """db doctor must exit with error when OCTOPUS_DATABASE_URL is not set."""
    monkeypatch.delenv("OCTOPUS_DATABASE_URL", raising=False)
    import sys

    old_argv = sys.argv
    try:
        sys.argv = ["app.db.cli", "doctor"]
        with pytest.raises(SystemExit) as exc_info:
            from app.db.cli import main

            main()
        assert exc_info.value.code == 1
    finally:
        sys.argv = old_argv


def test_cli_doctor_requires_url(monkeypatch):
    """Running doctor without OCTOPUS_DATABASE_URL prints error and exits 1."""
    monkeypatch.delenv("OCTOPUS_DATABASE_URL", raising=False)
    import sys

    old_argv = sys.argv
    old_stderr = sys.stderr
    try:
        sys.argv = ["app.db.cli", "doctor"]
        sys.stderr = StringIO()
        from app.db.cli import _cmd_doctor

        with pytest.raises(SystemExit) as exc_info:
            _cmd_doctor()
        assert exc_info.value.code == 1
        assert "OCTOPUS_DATABASE_URL" in sys.stderr.getvalue()
    finally:
        sys.argv = old_argv
        sys.stderr = old_stderr


def test_db_cli_sanitizes_connection_errors(monkeypatch):
    monkeypatch.setenv("OCTOPUS_DATABASE_URL", "postgresql://localhost:5432/bot")

    class OperationalError(RuntimeError):
        pass

    def fake_get_connection(url):
        del url
        raise OperationalError("postgresql://bot:secret@example.com/bot refused connection")

    monkeypatch.setattr("app.db.cli.get_connection", fake_get_connection)

    import sys

    old_stderr = sys.stderr
    try:
        sys.stderr = StringIO()
        with pytest.raises(SystemExit) as exc_info:
            from app.db.cli import _cmd_doctor

            _cmd_doctor()
        assert exc_info.value.code == 1
        output = sys.stderr.getvalue()
        assert "could not connect to the configured database" in output
        assert "secret@example.com" not in output
    finally:
        sys.stderr = old_stderr
