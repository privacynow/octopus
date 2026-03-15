"""Contract tests: README operator health model (Phase 14).

Asserts README presents the three health surfaces clearly and keeps
Local Runtime (SQLite) as default, Postgres optional.
Pins valid Compose command ordering (--env-file before run).
"""

from pathlib import Path

# Canonical Compose ordering: --env-file must come before run (Phase 14 follow-up).
_VALID_FULL_APP_DOCTOR = "docker compose --profile bot --env-file .env.bot run --rm bot python -m app.main --doctor"
_INVALID_ORDERING = "run --rm --env-file .env.bot"


def test_readme_full_app_doctor_command_valid_ordering():
    """README must document full app health command with valid Compose ordering."""
    repo = Path(__file__).resolve().parent.parent
    readme = repo / "README.md"
    text = readme.read_text()
    assert _INVALID_ORDERING not in text, (
        "README must not use invalid 'run --rm --env-file .env.bot' ordering"
    )
    assert _VALID_FULL_APP_DOCTOR in text, (
        "README must contain the canonical full app doctor command with --env-file before run"
    )


def test_readme_distinguishes_three_health_surfaces():
    """README must distinguish provider-only, Postgres/schema-only, and full app health."""
    repo = Path(__file__).resolve().parent.parent
    readme = repo / "README.md"
    text = readme.read_text()
    # Provider only
    assert "provider" in text.lower() and ("runtime only" in text or "auth and runtime" in text), (
        "README must describe provider-only health surface"
    )
    # Postgres/schema
    assert "db-doctor" in text or "db_doctor" in text or "Postgres" in text and "schema" in text, (
        "README must describe Postgres/schema-only health (db-doctor)"
    )
    # Full app health (and valid command shape is asserted in test_readme_full_app_doctor_command_valid_ordering)
    assert "app.main --doctor" in text or "full app health" in text, (
        "README must describe full app health (python -m app.main --doctor or /doctor)"
    )


def test_readme_sqlite_local_runtime_default():
    """README must state SQLite Local Runtime is the default."""
    repo = Path(__file__).resolve().parent.parent
    readme = repo / "README.md"
    text = readme.read_text()
    assert "SQLite" in text and ("default" in text.lower() or "Local Runtime" in text), (
        "README must say SQLite / Local Runtime is the default"
    )


def test_readme_no_postgres_only_regression():
    """README must not imply Postgres is required (no Postgres-only wording)."""
    repo = Path(__file__).resolve().parent.parent
    readme = repo / "README.md"
    text = readme.read_text()
    # Should mention optional Postgres or both paths, not only Postgres
    assert "optional" in text.lower() or "no DB" in text or "Local Runtime" in text, (
        "README must not regress into Postgres-only; optional or Local Runtime must appear"
    )
