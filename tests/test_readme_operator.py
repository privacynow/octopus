"""Contract tests: README first-time-user setup model.

The README should stay focused on the guided Docker path for a non-technical
first-time user. It may still include the canonical full-health command, but
it should not make readers understand alternate backend or operator-only flows
before they can get started.
"""

from pathlib import Path

# Canonical Compose ordering: --env-file must come before run (Phase 14 follow-up).
_VALID_FULL_APP_DOCTOR = (
    "docker compose --project-directory . -f infra/compose/docker-compose.yml "
    "--profile bot --env-file .env.bot run --rm bot python -m app.main --doctor"
)
_INVALID_ORDERING = "run --rm --env-file .env.bot"


def test_readme_full_app_doctor_command_valid_ordering():
    """If README shows the full app health command, it must use valid Compose ordering."""
    repo = Path(__file__).resolve().parent.parent
    readme = repo / "README.md"
    text = readme.read_text()
    assert _INVALID_ORDERING not in text, (
        "README must not use invalid 'run --rm --env-file .env.bot' ordering"
    )
    assert _VALID_FULL_APP_DOCTOR in text, (
        "README must contain the canonical full app doctor command with --env-file before run"
    )


def test_readme_guided_start_is_the_primary_setup_path():
    """README should center the guided start flow."""
    repo = Path(__file__).resolve().parent.parent
    readme = repo / "README.md"
    text = readme.read_text()
    assert "./scripts/app/guided_start.sh" in text, (
        "README must tell first-time users to use guided_start.sh"
    )
    assert "First-Time Setup" in text
    assert "Message the bot in Telegram" in text


def test_readme_explains_provider_login_and_doctor_in_plain_language():
    """README should give plain-language recovery steps for auth and health."""
    repo = Path(__file__).resolve().parent.parent
    readme = repo / "README.md"
    text = readme.read_text()
    assert "./scripts/provider/provider_login.sh" in text, (
        "README must explain how to recover from missing provider auth"
    )
    assert "/doctor" in text, "README should point users to /doctor"
    assert "app.main --doctor" in text, (
        "README should keep the canonical full app health command for operators"
    )


def test_readme_avoids_operator_only_setup_clutter():
    """README should not require first-time users to understand alternate backend paths."""
    repo = Path(__file__).resolve().parent.parent
    readme = repo / "README.md"
    text = readme.read_text()
    assert "BOT_DATABASE_URL" not in text, "README should not require backend configuration for the primary path"
    assert "dev_up_postgres.sh" not in text, "README should not lead with alternate Postgres bootstrap flow"
    assert "db-bootstrap" not in text and "db-update" not in text and "db-doctor" not in text, (
        "README should not send first-time users through Postgres-specific tooling"
    )
