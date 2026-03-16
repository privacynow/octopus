"""Contract tests for operator scripts (Milestone E Bucket A).

Assert script content and output contracts so operator-path changes
don't remove or weaken provider vs full-doctor distinction.
"""

from pathlib import Path


def test_provider_status_reminds_full_doctor():
    """provider_status.sh must remind operator to run full app doctor on success."""
    repo = Path(__file__).resolve().parent.parent
    script = repo / "scripts" / "provider" / "provider_status.sh"
    assert script.exists()
    text = script.read_text()
    assert "full app health" in text or "app.main --doctor" in text, (
        "provider_status.sh must tell operator how to run full app health (provider-only is not full health)"
    )
    assert "no DB" in text or "no DB/Telegram" in text, (
        "provider_status.sh must state it does not check DB (and optionally Telegram)"
    )


def test_provider_status_says_provider_only():
    """provider_status.sh must state it is provider-only (Phase 14 operator clarity)."""
    repo = Path(__file__).resolve().parent.parent
    script = repo / "scripts" / "provider" / "provider_status.sh"
    text = script.read_text()
    assert "provider" in text and ("runtime only" in text or "auth and runtime" in text), (
        "provider_status.sh must say it is provider auth/runtime only"
    )


def test_provider_status_success_does_not_imply_bot_ready():
    """provider_status.sh must state success there does not prove full bot/app readiness (Phase 14)."""
    repo = Path(__file__).resolve().parent.parent
    script = repo / "scripts" / "provider" / "provider_status.sh"
    text = script.read_text()
    assert "does NOT prove" in text or "does not prove" in text, (
        "provider_status.sh must say success does not prove bot can start"
    )


def test_provider_status_points_to_full_health_command():
    """provider_status.sh must point operator to the full health command (Phase 14)."""
    repo = Path(__file__).resolve().parent.parent
    script = repo / "scripts" / "provider" / "provider_status.sh"
    text = script.read_text()
    assert "app.main --doctor" in text, (
        "provider_status.sh must point to full app health command (python -m app.main --doctor)"
    )


# Canonical Compose ordering: --env-file must come before run (Phase 14 follow-up).
_VALID_COMPOSE_RUN = (
    "docker compose --project-directory . -f infra/compose/docker-compose.yml "
    "--profile bot --env-file .env.bot run --rm"
)
_INVALID_ORDERING = "run --rm --env-file .env.bot"


def test_provider_status_uses_valid_compose_ordering():
    """provider_status.sh must use valid Compose flag order: --env-file before run."""
    repo = Path(__file__).resolve().parent.parent
    script = repo / "scripts" / "provider" / "provider_status.sh"
    text = script.read_text()
    assert _INVALID_ORDERING not in text, (
        "provider_status.sh must not use invalid 'run --rm --env-file .env.bot' ordering"
    )
    assert _VALID_COMPOSE_RUN in text, (
        "provider_status.sh must use the compose file under infra/compose with --project-directory"
    )


def test_provider_status_invokes_bot_provider():
    """provider_status.sh must invoke bot-provider service with valid ordering."""
    repo = Path(__file__).resolve().parent.parent
    script = repo / "scripts" / "provider" / "provider_status.sh"
    text = script.read_text()
    assert "bot-provider" in text, "provider_status.sh must run bot-provider service"
    assert _VALID_COMPOSE_RUN in text and "bot-provider" in text, (
        "provider_status.sh must use valid compose run and bot-provider"
    )


def test_provider_status_full_doctor_command_shape():
    """provider_status.sh full app health command must use valid ordering and bot service."""
    repo = Path(__file__).resolve().parent.parent
    script = repo / "scripts" / "provider" / "provider_status.sh"
    text = script.read_text()
    assert _INVALID_ORDERING not in text
    assert "bot python -m app.main --doctor" in text
    assert _VALID_COMPOSE_RUN in text
    assert "app.main --doctor" in text


def test_provider_status_requires_env_bot():
    """provider_status.sh (or its sourced lib) must tell operator to create .env.bot when missing."""
    repo = Path(__file__).resolve().parent.parent
    script = repo / "scripts" / "provider" / "provider_status.sh"
    lib_env = repo / "scripts" / "lib_env.sh"
    script_text = script.read_text()
    assert ".env.bot" in script_text
    # Message may live in script or in sourced lib_env.sh
    script_has_message = "Create .env.bot" in script_text or "create .env.bot" in script_text.lower()
    lib_has_message = (
        lib_env.read_text().count("Create .env.bot") >= 1 or "create .env.bot" in lib_env.read_text().lower()
    )
    assert script_has_message or lib_has_message, (
        "provider_status.sh or scripts/lib_env.sh must tell operator to create .env.bot when missing"
    )


def test_container_provider_login_banners_explain_exit_steps():
    """container_provider_login.sh should tell the operator how to return from each CLI."""
    repo = Path(__file__).resolve().parent.parent
    script = repo / "scripts" / "provider" / "container_provider_login.sh"
    text = script.read_text()
    assert "You MUST exit the CLI to return to setup." in text
    assert "/login" in text, "Claude banner should tell the user to run /login"
    assert "q  or  Ctrl-C" in text or "q or Ctrl-C" in text, (
        "Codex banner should tell the user how to return to setup"
    )


def test_registry_start_prints_enrollment_token():
    """registry/start.sh should print the generated enrollment token for local setup."""
    repo = Path(__file__).resolve().parent.parent
    script = repo / "scripts" / "registry" / "start.sh"
    text = script.read_text()
    assert "Enrollment token:" in text
    assert "Registry UI password:" in text
    assert "keep this file private" in text


def test_guided_start_offers_quick_setup_and_local_registry_token_reuse():
    """guided_start.sh should expose quick setup and auto-reuse local registry tokens."""
    repo = Path(__file__).resolve().parent.parent
    script = repo / "scripts" / "app" / "guided_start.sh"
    text = script.read_text()
    assert "Setup mode (quick/full)" in text
    assert "_LOCAL_REGISTRY_ENROLL_TOKEN" in text
    assert "Using local registry enrollment token" in text


def test_guided_start_success_summary_uses_browser_registry_ui_url():
    """guided_start.sh should reprint a browser-safe Registry UI URL in the final box."""
    repo = Path(__file__).resolve().parent.parent
    script = repo / "scripts" / "app" / "guided_start.sh"
    text = script.read_text()
    assert "build_registry_ui_display_url" in text
    assert "REGISTRY_UI_TOKEN" in text
    assert '/ui' in text
    assert "http://localhost:" in text
    assert "login password" in text
    assert "print_box_wrapped_line" in text


def test_guided_start_reads_repo_version_for_success_summary():
    """guided_start.sh should read VERSION and show it in the final startup summary."""
    repo = Path(__file__).resolve().parent.parent
    script = repo / "scripts" / "app" / "guided_start.sh"
    text = script.read_text()
    assert 'bot_version_display="$(tr -d' in text
    assert 'printf "║  • Bot version:' in text
