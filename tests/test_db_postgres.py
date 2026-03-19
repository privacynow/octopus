"""Tests for Phase 12 Postgres DB tooling: migrate, doctor, CLI."""

import os
from pathlib import Path

import pytest

from app.db.postgres_migrate import current_schema_version, run_bootstrap, run_update
from app.db.postgres_doctor import run_doctor


def test_current_schema_version():
    """Repo has at least 0001_runtime.sql so current version >= 1."""
    assert current_schema_version() >= 1


def test_run_update_renames_legacy_registry_delivery_kinds(postgres_base_url, request):
    """Postgres update applies 0009 and rewrites legacy delivery kinds in-place."""
    from app.db.postgres import get_connection
    from tests.support.postgres_support import _replace_db_in_url, create_test_database, get_worker_id

    worker_id = get_worker_id(request.config)
    db_name = f"test_bot_registry_v8_{worker_id}".replace("-", "_")
    db_url = _replace_db_in_url(postgres_base_url, db_name)
    create_test_database(postgres_base_url, db_name)
    sql_dir = Path(__file__).resolve().parents[1] / "app" / "db" / "migrations" / "postgres"

    with get_connection(db_url) as conn:
        for version in range(1, 9):
            matching = sorted(sql_dir.glob(f"{version:04d}_*.sql"))
            assert matching, f"missing migration file for version {version}"
            sql = matching[0].read_text()
            with conn.cursor() as cur:
                cur.execute(sql)
                cur.execute(
                    """
                    INSERT INTO bot_runtime.schema_migrations (version, applied_at)
                    VALUES (%s, (NOW() AT TIME ZONE 'utc'))
                    ON CONFLICT (version) DO NOTHING
                    """,
                    (version,),
                )
            conn.commit()

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO agent_registry.deliveries (
                    delivery_id, target_agent_id, kind, payload_json, state, created_at, updated_at
                ) VALUES
                    ('legacy-input', 'agent-1', 'surface_input', '{}'::jsonb, 'queued', '2026-03-18T00:00:00+00:00', '2026-03-18T00:00:00+00:00'),
                    ('legacy-action', 'agent-1', 'surface_action', '{}'::jsonb, 'queued', '2026-03-18T00:00:00+00:00', '2026-03-18T00:00:00+00:00')
                """
            )
        conn.commit()

        errors = run_update(conn)
        assert errors == []

        with conn.cursor() as cur:
            cur.execute(
                "SELECT delivery_id, kind FROM agent_registry.deliveries ORDER BY delivery_id"
            )
            rows = cur.fetchall()

    assert rows == [
        ("legacy-action", "channel_action"),
        ("legacy-input", "channel_input"),
    ]


def test_doctor_passes_after_bootstrap(postgres_truncated):
    """With Postgres harness: bootstrap then doctor returns no errors."""
    from app.db.postgres import get_connection
    with get_connection(postgres_truncated) as conn:
        errors = run_doctor(conn)
    assert errors == []


def test_run_bootstrap_is_idempotent_on_bootstrapped_db(postgres_truncated):
    """run_bootstrap() on an already bootstrapped DB should be a no-op, not replay old SQL."""
    from app.db.postgres import get_connection

    with get_connection(postgres_truncated) as conn:
        errors = run_bootstrap(conn)
    assert errors == []


def test_cli_doctor_exits_when_no_database_url(monkeypatch):
    """db doctor must exit with error when BOT_DATABASE_URL is not set."""
    monkeypatch.delenv("BOT_DATABASE_URL", raising=False)
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


def test_run_update_fails_with_bootstrap_first_message_on_empty_db(postgres_base_url, request):
    """run_update() on empty/missing schema returns 'run DB bootstrap first' instead of bootstrapping.

    Pins the bootstrap/update split: update must not silently bootstrap a fresh DB.
    """
    from app.db.postgres import get_connection
    from tests.support.postgres_support import (
        _replace_db_in_url,
        create_test_database,
        get_worker_id,
    )

    worker_id = get_worker_id(request.config)
    db_name = f"test_bot_empty_{worker_id}".replace("-", "_")
    empty_url = _replace_db_in_url(postgres_base_url, db_name)
    create_test_database(postgres_base_url, db_name)
    with get_connection(empty_url) as conn:
        errors = run_update(conn)
    assert len(errors) >= 1
    assert any("Run DB bootstrap first" in e or "run DB bootstrap first" in e for e in errors)


def test_cli_doctor_requires_url(monkeypatch):
    """Running doctor without BOT_DATABASE_URL prints error and exits 1."""
    monkeypatch.delenv("BOT_DATABASE_URL", raising=False)
    import sys
    from io import StringIO
    old_argv = sys.argv
    old_stderr = sys.stderr
    try:
        sys.argv = ["app.db.cli", "doctor"]
        sys.stderr = StringIO()
        from app.db.cli import _cmd_doctor
        with pytest.raises(SystemExit) as exc_info:
            _cmd_doctor()
        assert exc_info.value.code == 1
        assert "BOT_DATABASE_URL" in sys.stderr.getvalue()
    finally:
        sys.argv = old_argv
        sys.stderr = old_stderr
