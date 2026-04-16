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
