from __future__ import annotations

import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_provider_auth_scripts_export_runtime_image_for_compose_interpolation() -> None:
    for script_name in ("provider_login.sh", "provider_status.sh", "provider_logout.sh"):
        script = REPO_ROOT / "scripts" / "provider" / script_name
        text = script.read_text(encoding="utf-8")

        assert 'OCTOPUS_RUNTIME_IMAGE="octopus-agent:$provider" \\' in text
        assert text.index('OCTOPUS_RUNTIME_IMAGE="octopus-agent:$provider" \\') < text.index("docker compose")


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _provider_login_env(tmp_path: Path, *, help_text: str, login_exit: int, artifact_exit: int) -> tuple[dict[str, str], Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    command_log = tmp_path / "commands.log"
    _write_executable(
        bin_dir / "codex",
        f"""#!/usr/bin/env bash
set -euo pipefail
printf 'codex:%s\\n' "$*" >> "$TEST_COMMAND_LOG"
if [ "$*" = "login --help" ]; then
  cat <<'EOF'
{help_text}
EOF
  exit 0
fi
if [ "$*" = "login" ] || [ "$*" = "login --device-auth" ]; then
  exit {login_exit}
fi
exit 64
""",
    )
    _write_executable(
        bin_dir / "python",
        f"""#!/usr/bin/env bash
set -euo pipefail
printf 'python:%s\\n' "$*" >> "$TEST_COMMAND_LOG"
if [ "$*" = "-m app.provider_auth has-runtime-artifacts codex $HOME" ]; then
  exit {artifact_exit}
fi
exit 64
""",
    )
    env = os.environ.copy()
    env.update(
        {
            "BOT_PROVIDER": "codex",
            "HOME": str(tmp_path / "home"),
            "PATH": f"{bin_dir}:{env['PATH']}",
            "TEST_COMMAND_LOG": str(command_log),
        }
    )
    return env, command_log


def test_container_provider_login_uses_plain_codex_login_when_device_auth_is_absent(tmp_path: Path) -> None:
    env, command_log = _provider_login_env(
        tmp_path,
        help_text="Usage: codex login [OPTIONS] [COMMAND]",
        login_exit=0,
        artifact_exit=0,
    )

    result = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "provider" / "container_provider_login.sh")],
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    logged = command_log.read_text(encoding="utf-8")
    assert "codex:login --help" in logged
    assert "codex:login\n" in logged
    assert "codex:login --device-auth" not in logged


def test_container_provider_login_uses_device_auth_when_supported(tmp_path: Path) -> None:
    env, command_log = _provider_login_env(
        tmp_path,
        help_text="Usage: codex login --device-auth",
        login_exit=0,
        artifact_exit=0,
    )

    result = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "provider" / "container_provider_login.sh")],
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    logged = command_log.read_text(encoding="utf-8")
    assert "codex:login --device-auth" in logged


def test_container_provider_login_fails_when_codex_login_fails_even_with_auth_artifacts(tmp_path: Path) -> None:
    env, command_log = _provider_login_env(
        tmp_path,
        help_text="Usage: codex login [OPTIONS] [COMMAND]",
        login_exit=2,
        artifact_exit=0,
    )

    result = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "provider" / "container_provider_login.sh")],
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 2
    assert "Codex login command failed" in result.stderr
    logged = command_log.read_text(encoding="utf-8")
    assert "codex:login\n" in logged
    assert "python:-m app.provider_auth has-runtime-artifacts" not in logged


def test_provider_login_runs_live_health_check_after_interactive_login() -> None:
    script = REPO_ROOT / "scripts" / "provider" / "provider_login.sh"
    text = script.read_text(encoding="utf-8")

    assert 'echo "Running live provider health check..."' in text
    assert '"$REPO_DIR/scripts/provider/provider_status.sh" "$provider"' in text
