"""Contract tests for operator scripts (Milestone E Bucket A).

Assert script content and output contracts so operator-path changes
don't remove or weaken provider vs full-doctor distinction.
"""

from pathlib import Path
import subprocess


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


def test_provider_status_uses_valid_compose_ordering():
    """provider_status.sh should use the shared provider wrapper instead of inline compose."""
    repo = Path(__file__).resolve().parent.parent
    script = repo / "scripts" / "provider" / "provider_status.sh"
    text = script.read_text()
    assert "provider_compose" in text, (
        "provider_status.sh must use the shared provider compose wrapper after the auth-volume split"
    )
    assert "run --rm bot-provider" in text


def test_provider_status_invokes_bot_provider():
    """provider_status.sh must invoke bot-provider through the provider wrapper."""
    repo = Path(__file__).resolve().parent.parent
    script = repo / "scripts" / "provider" / "provider_status.sh"
    text = script.read_text()
    assert "bot-provider" in text, "provider_status.sh must run bot-provider service"
    assert 'provider_compose "$provider" run --rm bot-provider' in text, (
        "provider_status.sh must invoke bot-provider through provider_compose"
    )


def test_provider_status_full_doctor_command_shape():
    """provider_status.sh full app health command must use valid ordering and bot service."""
    repo = Path(__file__).resolve().parent.parent
    script = repo / "scripts" / "provider" / "provider_status.sh"
    text = script.read_text()
    assert "bot python -m app.main --doctor" in text
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
    assert "codex login --device-auth" in text
    assert "device code" in text
    assert "removed flag:  codex --login" in text
    assert "/login" in text, "Claude banner should tell the user to run /login"
    assert "press Ctrl-C" in text or "Ctrl-C" in text, (
        "Codex banner should tell the user how to recover if the login command does not exit cleanly"
    )


def test_registry_start_prints_enrollment_token():
    """registry/start.sh should keep generated secrets in .env.registry, not stdout."""
    repo = Path(__file__).resolve().parent.parent
    script = repo / "scripts" / "registry" / "start.sh"
    text = script.read_text()
    assert "Enrollment token:" not in text
    assert "Registry UI password:" not in text
    assert "Registry secrets are stored in $ENV_FILE" in text
    assert "keep this file private" in text


def test_registry_start_bootstraps_local_http_acknowledgement():
    repo = Path(__file__).resolve().parent.parent
    script = repo / "scripts" / "registry" / "start.sh"
    text = script.read_text()
    assert "REGISTRY_ALLOW_HTTP=1" in text
    assert "REGISTRY_BIND_HOST=127.0.0.1" in text


def test_guided_start_offers_quick_setup_and_local_registry_token_reuse():
    """guided_start.sh should expose quick setup and auto-reuse local registry tokens."""
    repo = Path(__file__).resolve().parent.parent
    script = repo / "scripts" / "app" / "guided_start.sh"
    text = script.read_text()
    assert "Setup mode (quick/full)" in text
    assert "_LOCAL_REGISTRY_ENROLL_TOKEN" in text
    assert "Using local registry enrollment token" in text
    assert "Remote registry URLs should use https://" in text


def test_lib_env_exposes_channel_setup_help_for_telegram():
    repo = Path(__file__).resolve().parent.parent
    script = repo / "scripts" / "lib_env.sh"
    text = script.read_text()
    assert "print_channel_setup_help" in text
    assert "prompt_channel_token_with_help" in text
    assert "upsert_env_file_value" in text
    assert "format_doctor_output_for_operator" in text
    assert "https://t.me/BotFather" in text
    assert "/newbot" in text
    assert "restrict_secret_file_permissions" in text


def test_secret_writing_scripts_harden_file_permissions():
    repo = Path(__file__).resolve().parent.parent
    guided = (repo / "scripts" / "app" / "guided_start.sh").read_text()
    shared = (repo / "scripts" / "app" / "shared_start.sh").read_text()
    registry = (repo / "scripts" / "registry" / "start.sh").read_text()

    assert "umask 077" in guided
    assert 'restrict_secret_file_permissions "$BOT_ENV_FILE"' in guided
    assert "umask 077" in shared
    assert 'restrict_secret_file_permissions "$BOT_ENV_FILE"' in shared
    assert "umask 077" in registry
    assert 'chmod 600 "$ENV_FILE"' in registry


def test_guided_start_uses_channel_token_helper():
    repo = Path(__file__).resolve().parent.parent
    script = repo / "scripts" / "app" / "guided_start.sh"
    text = script.read_text()
    assert "prompt_channel_token_with_help telegram" in text
    assert "ensure_guided_telegram_token" in text
    assert "prompt_rejected_telegram_token_repair" in text


def test_shared_start_can_bootstrap_env_with_channel_help():
    repo = Path(__file__).resolve().parent.parent
    script = repo / "scripts" / "app" / "shared_start.sh"
    text = script.read_text()
    assert "create_env_file_if_missing" in text
    assert "prompt_channel_token_with_help telegram" in text
    assert "ensure_shared_telegram_token" in text
    assert "prompt_rejected_shared_telegram_token_repair" in text
    assert "Public webhook URL (must end in /webhook)" in text
    assert "Remote registry URLs should use https://" in text


def test_registry_compose_requires_enroll_token_and_binds_localhost():
    repo = Path(__file__).resolve().parent.parent
    compose = repo / "infra" / "compose" / "docker-compose.yml"
    text = compose.read_text()
    assert "REGISTRY_ENROLL_TOKEN: ${REGISTRY_ENROLL_TOKEN:?Set REGISTRY_ENROLL_TOKEN in .env.registry}" in text
    assert "REGISTRY_UI_TOKEN: ${REGISTRY_UI_TOKEN:?Set REGISTRY_UI_TOKEN in .env.registry}" in text
    assert 'REGISTRY_BIND_HOST:-127.0.0.1' in text


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


def test_guided_start_runs_full_health_check_before_background_start():
    """guided_start.sh should run full doctor before it claims the bot is starting."""
    repo = Path(__file__).resolve().parent.parent
    script = repo / "scripts" / "app" / "guided_start.sh"
    text = script.read_text()
    assert "Step 3/4: Full app health check" in text
    assert "Step 4/4: Starting bot (background service)" in text
    assert "run --rm bot python -m app.main --doctor" in text
    assert text.index("run --rm bot python -m app.main --doctor") < text.index("./scripts/app/start_instance.sh")


def test_guided_start_no_longer_depends_on_repo_version_file():
    """guided_start.sh should not try to read a missing VERSION file for the success summary."""
    repo = Path(__file__).resolve().parent.parent
    script = repo / "scripts" / "app" / "guided_start.sh"
    text = script.read_text()
    assert "VERSION" not in text


def test_guided_start_runs_doctor_on_post_start_failure():
    """guided_start.sh should rerun full doctor, not dump raw logs, when the bot exits immediately."""
    repo = Path(__file__).resolve().parent.parent
    script = repo / "scripts" / "app" / "guided_start.sh"
    text = script.read_text()
    assert "run --rm bot python -m app.main --doctor" in text
    assert "logs_instance.sh" in text
    assert "Last logs:" not in text
    assert "Fresh diagnosis:" in text
    assert "print_doctor_output_for_operator" in text


def test_shared_start_runs_doctor_on_post_start_failure():
    """shared_start.sh should rerun full doctor if webhook/worker services exit after startup."""
    repo = Path(__file__).resolve().parent.parent
    script = repo / "scripts" / "app" / "shared_start.sh"
    text = script.read_text()
    assert "run --rm bot-webhook python -m app.main --doctor" in text
    assert "logs -f bot-webhook bot-worker" in text
    assert "Fresh diagnosis:" in text
    assert "print_doctor_output_for_operator" in text


def test_shared_start_runs_health_check_before_webhook_registration():
    """shared_start.sh should verify full app health before webhook registration and service startup."""
    repo = Path(__file__).resolve().parent.parent
    script = repo / "scripts" / "app" / "shared_start.sh"
    text = script.read_text()
    assert "Running full app health check before Shared Runtime startup" in text
    assert text.index("run --rm bot-webhook python -m app.main --doctor") < text.index('telegram_set_webhook "$telegram_token"')


def test_repo_does_not_ship_env_bot():
    """The repo must not ship a live .env.bot with placeholder secrets."""
    repo = Path(__file__).resolve().parent.parent
    tracked = subprocess.run(
        ["git", "ls-files", ".env.bot"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    if not tracked:
        return
    status = subprocess.run(
        ["git", "status", "--short", "--", ".env.bot"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert status.startswith("D"), "Do not commit .env.bot; ship only .env.example"


def test_start_scripts_require_real_telegram_token():
    """Startup paths must reject placeholder Telegram tokens before Docker/provider work."""
    repo = Path(__file__).resolve().parent.parent
    guided_start = (repo / "scripts" / "app" / "guided_start.sh").read_text()
    start_instance = (repo / "scripts" / "app" / "start_instance.sh").read_text()
    shared_start = (repo / "scripts" / "app" / "shared_start.sh").read_text()
    lib_env = (repo / "scripts" / "lib_env.sh").read_text()

    assert "require_real_telegram_token" in lib_env
    assert "require_real_telegram_token" in guided_start
    assert "require_real_telegram_token" in start_instance
    assert "require_real_telegram_token" in shared_start
