from __future__ import annotations

import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent


def _run_bash(script: str, *, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-lc", script],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=check,
    )


def test_cmd_status_reports_no_bots(tmp_path: Path) -> None:
    script = f"""
set -euo pipefail
cd "{tmp_path}"
export OCTOPUS_SOURCE_ONLY=1
source "{REPO}/octopus"
cd "{tmp_path}"
cmd_status
"""
    result = _run_bash(script, cwd=tmp_path)
    assert result.stdout.strip() == "No bots configured. Run ./octopus to get started."


def test_resolve_bot_slug_auto_selects_single_bot(tmp_path: Path) -> None:
    env_dir = tmp_path / ".deploy" / "bots" / "solo-bot"
    env_dir.mkdir(parents=True, exist_ok=True)
    (env_dir / ".env").write_text("BOT_SLUG=solo-bot\n")

    script = f"""
set -euo pipefail
cd "{tmp_path}"
export OCTOPUS_SOURCE_ONLY=1
source "{REPO}/octopus"
cd "{tmp_path}"
resolve_bot_slug
"""
    result = _run_bash(script, cwd=tmp_path)
    assert result.stdout.strip() == "solo-bot"


def test_cmd_start_auto_selects_single_bot(tmp_path: Path) -> None:
    env_dir = tmp_path / ".deploy" / "bots" / "solo-bot"
    env_dir.mkdir(parents=True, exist_ok=True)
    (env_dir / ".env").write_text(
        "BOT_SLUG=solo-bot\n"
        "BOT_PROVIDER=claude\n"
        "TELEGRAM_BOT_TOKEN=123456:real-token\n"
    )

    script = f"""
set -euo pipefail
cd "{tmp_path}"
export OCTOPUS_SOURCE_ONLY=1
source "{REPO}/octopus"
cd "{tmp_path}"
bot_compose() {{ printf '%s\\n' "$*" > compose-call.txt; }}
cmd_start
cat compose-call.txt
"""
    result = _run_bash(script, cwd=tmp_path)
    assert result.stdout.strip() == "solo-bot up -d bot"


def test_main_menu_add_bot_routes_to_add_bot_flow(tmp_path: Path) -> None:
    script = f"""
set -euo pipefail
cd "{tmp_path}"
export OCTOPUS_SOURCE_ONLY=1
source "{REPO}/octopus"
cd "{tmp_path}"
add_bot_flow() {{ printf 'ADD\\n'; }}
printf '1\\n' | main_menu
"""
    result = _run_bash(script, cwd=tmp_path)
    assert result.stdout.strip().endswith("ADD")


def test_resolve_bot_slug_rejects_unknown_slug(tmp_path: Path) -> None:
    script = f"""
set -euo pipefail
cd "{tmp_path}"
export OCTOPUS_SOURCE_ONLY=1
source "{REPO}/octopus"
cd "{tmp_path}"
if resolve_bot_slug missing-bot; then
  exit 1
fi
"""
    result = _run_bash(script, cwd=tmp_path, check=False)
    assert result.returncode == 0
    assert "No bot named 'missing-bot' is configured." in result.stderr


def test_cmd_status_renders_bot_registry_and_provider_auth(tmp_path: Path) -> None:
    bot_dir = tmp_path / ".deploy" / "bots" / "example-bot"
    bot_dir.mkdir(parents=True, exist_ok=True)
    (bot_dir / ".env").write_text(
        "BOT_SLUG=example-bot\n"
        'BOT_DISPLAY_NAME="Example Bot"\n'
        "BOT_TELEGRAM_USERNAME=example_bot\n"
        "BOT_PROVIDER=claude\n"
        "BOT_AGENT_MODE=registry\n"
        "BOT_AGENT_REGISTRY_1_ID=local\n"
        "BOT_AGENT_REGISTRY_1_URL=http://registry:8787\n"
        "BOT_AGENT_REGISTRY_1_ENROLL_TOKEN=local-enroll\n"
        "BOT_AGENT_REGISTRY_1_SCOPE=full\n"
        "BOT_AGENT_REGISTRY_2_ID=analytics\n"
        "BOT_AGENT_REGISTRY_2_URL=https://analytics.example.com\n"
        "BOT_AGENT_REGISTRY_2_ENROLL_TOKEN=analytics-enroll\n"
        "BOT_AGENT_REGISTRY_2_SCOPE=channel\n"
    )
    registry_dir = tmp_path / ".deploy" / "registry"
    registry_dir.mkdir(parents=True, exist_ok=True)
    (registry_dir / ".env").write_text("REGISTRY_PORT=9001\n")
    auth_dir = tmp_path / ".deploy" / "provider-auth" / "claude"
    auth_dir.mkdir(parents=True, exist_ok=True)
    (auth_dir / ".authed").write_text("")

    script = f"""
set -euo pipefail
cd "{tmp_path}"
export OCTOPUS_SOURCE_ONLY=1
source "{REPO}/octopus"
cd "{tmp_path}"
bot_is_running() {{ return 0; }}
docker_status_for_slug() {{ printf 'Up 3 hours\\n'; }}
registry_is_running() {{ return 0; }}
print_bot_registry_connection_lines() {{
  printf '      local    full    connected    http://registry:8787\\n'
  printf '      analytics    channel    degraded    https://analytics.example.com\\n'
}}
cmd_status
"""
    result = _run_bash(script, cwd=tmp_path)
    assert "Example Bot (@example_bot)" in result.stdout
    assert "claude" in result.stdout
    assert "registry" in result.stdout
    assert "running" in result.stdout
    assert "local    full    connected    http://registry:8787" in result.stdout
    assert "analytics    channel    degraded    https://analytics.example.com" in result.stdout
    assert "http://localhost:9001/ui" in result.stdout
    assert "claude     authenticated" in result.stdout


def test_manage_bot_menu_shows_identity_header(tmp_path: Path) -> None:
    bot_dir = tmp_path / ".deploy" / "bots" / "example-bot"
    bot_dir.mkdir(parents=True, exist_ok=True)
    (bot_dir / ".env").write_text(
        "BOT_SLUG=example-bot\n"
        'BOT_DISPLAY_NAME="Example Bot"\n'
        "BOT_TELEGRAM_USERNAME=example_bot\n"
        "BOT_PROVIDER=claude\n"
        "BOT_AGENT_MODE=standalone\n"
    )

    script = f"""
set -euo pipefail
cd "{tmp_path}"
export OCTOPUS_SOURCE_ONLY=1
source "{REPO}/octopus"
cd "{tmp_path}"
bot_is_running() {{ return 0; }}
printf '7\\n' | manage_bot_menu
"""
    result = _run_bash(script, cwd=tmp_path)
    assert "Bot: Example Bot (@example_bot) — claude, standalone, running" in result.stdout


def test_cmd_doctor_preserves_per_connection_health_lines(tmp_path: Path) -> None:
    bot_dir = tmp_path / ".deploy" / "bots" / "example-bot"
    bot_dir.mkdir(parents=True, exist_ok=True)
    (bot_dir / ".env").write_text(
        "BOT_SLUG=example-bot\n"
        "BOT_PROVIDER=claude\n"
        "BOT_AGENT_MODE=registry\n"
    )

    script = f"""
set -euo pipefail
cd "{tmp_path}"
export OCTOPUS_SOURCE_ONLY=1
source "{REPO}/octopus"
cd "{tmp_path}"
run_bot_doctor() {{
  cat <<'EOF'
2026-03-19 10:00:00 [INFO] internal startup noise
Registries:
  prod        full           connected    http://localhost:8787/ui
  analytics   channel        degraded     https://analytics.example.com
EOF
}}
cmd_doctor example-bot 2>doctor.txt
cat doctor.txt
"""
    result = _run_bash(script, cwd=tmp_path)
    assert "Registries:" in result.stdout
    assert "prod        full           connected" in result.stdout
    assert "analytics   channel        degraded" in result.stdout
    assert "internal startup noise" not in result.stdout
