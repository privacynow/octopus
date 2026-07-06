from __future__ import annotations

import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_provider_auth_scripts_export_runtime_image_for_compose_interpolation() -> None:
    for script_name in ("provider_login.sh", "provider_status.sh", "provider_logout.sh"):
        script = REPO_ROOT / "scripts" / "provider" / script_name
        text = script.read_text(encoding="utf-8")

        assert 'OCTOPUS_RUNTIME_IMAGE="octopus-agent:$provider" \\' in text
        assert text.index('OCTOPUS_RUNTIME_IMAGE="octopus-agent:$provider" \\') < text.index("docker compose")


def test_provider_status_checks_configured_bot_env_files() -> None:
    script = REPO_ROOT / "scripts" / "provider" / "provider_status.sh"
    text = script.read_text(encoding="utf-8")

    assert "for candidate in .deploy/bots/*/.env" in text
    assert 'if [ "$candidate_provider" = "$provider" ]; then' in text
    assert 'BOT_ENV_FILE="$bot_env_file" \\' in text
    assert 'BOT_ENV_FILE="/dev/null" \\' not in text


def test_container_provider_login_rejects_codex_interactive_login() -> None:
    result = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "provider" / "container_provider_login.sh")],
        capture_output=True,
        text=True,
        env={"BOT_PROVIDER": "codex"},
    )

    assert result.returncode == 2
    assert "Codex interactive login must run on the host" in result.stderr
    assert "browser callback to localhost reaches the login server" in result.stderr


def test_provider_login_runs_codex_login_on_host_with_shared_codex_home() -> None:
    script = REPO_ROOT / "scripts" / "provider" / "provider_login.sh"
    text = script.read_text(encoding="utf-8")

    assert 'if [ "$provider" = "codex" ]; then' in text
    assert 'codex_home="$REPO_DIR/$auth_dir/.codex"' in text
    assert 'CODEX_HOME="$codex_home" codex login' in text
    assert 'CODEX_HOME="$codex_home" python3 -m app.provider_auth has-runtime-artifacts codex "$HOME"' in text
    assert text.index('CODEX_HOME="$codex_home" codex login') < text.index("docker compose")
    assert "--device-auth" not in text


def test_provider_login_runs_live_health_check_after_interactive_login() -> None:
    script = REPO_ROOT / "scripts" / "provider" / "provider_login.sh"
    text = script.read_text(encoding="utf-8")

    assert 'echo "Running live provider health check..."' in text
    assert '"$REPO_DIR/scripts/provider/provider_status.sh" "$provider"' in text
