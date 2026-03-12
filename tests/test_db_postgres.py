"""Tests for Phase 12 Postgres DB tooling: migrate, doctor, CLI."""

import os

import pytest

from app.db.postgres_migrate import current_schema_version
from app.db.postgres_doctor import run_doctor


def test_current_schema_version():
    """Repo has at least 0001_runtime.sql so current version >= 1."""
    assert current_schema_version() >= 1


def test_doctor_passes_after_bootstrap(postgres_truncated):
    """With Postgres harness: bootstrap then doctor returns no errors."""
    from app.db.postgres import get_connection
    with get_connection(postgres_truncated) as conn:
        errors = run_doctor(conn)
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
