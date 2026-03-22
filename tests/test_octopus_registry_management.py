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


def test_connect_bot_to_local_registry_updates_env_and_restarts(tmp_path: Path) -> None:
    env_dir = tmp_path / ".deploy" / "bots" / "example-bot"
    env_dir.mkdir(parents=True, exist_ok=True)
    (env_dir / ".env").write_text(
        "BOT_SLUG=example-bot\n"
        "BOT_PROVIDER=claude\n"
        "BOT_AGENT_MODE=standalone\n"
    )

    script = f"""
set -euo pipefail
cd "{tmp_path}"
export OCTOPUS_SOURCE_ONLY=1
source "{REPO}/octopus"
cd "{tmp_path}"
prompt_registry_target() {{
  REGISTRY_TARGET_KIND=local
  REGISTRY_TARGET_URL=http://registry:8787
  REGISTRY_TARGET_TOKEN=local-enroll
  REGISTRY_TARGET_SCOPE=full
}}
restart_bot_after_config_change() {{ printf 'restart:%s\\n' "$1" > restart.txt; }}
verify_registry_enrollment() {{ return 0; }}
connect_bot_to_registry_flow example-bot
cat .deploy/bots/example-bot/.env
cat restart.txt
"""
    result = _run_bash(script, cwd=tmp_path)
    assert "BOT_AGENT_MODE=registry" in result.stdout
    assert "BOT_AGENT_REGISTRY_1_ID=local" in result.stdout
    assert "BOT_AGENT_REGISTRY_1_URL=http://registry:8787" in result.stdout
    assert "BOT_AGENT_REGISTRY_1_ENROLL_TOKEN=local-enroll" in result.stdout
    assert "BOT_AGENT_REGISTRY_1_SCOPE=full" in result.stdout
    assert "restart:example-bot" in result.stdout
    assert "Bot example-bot is now connected to the local registry." in result.stdout


def test_add_bot_flow_can_create_registry_bot_without_naming_prompt(tmp_path: Path) -> None:
    script = f"""
set -euo pipefail
cd "{tmp_path}"
export OCTOPUS_SOURCE_ONLY=1
source "{REPO}/octopus"
cd "{tmp_path}"
prepare_new_bot_setup() {{
  NEW_BOT_SLUG=example-bot
  NEW_BOT_TELEGRAM_ID=123456789
  NEW_BOT_TELEGRAM_USERNAME=example_bot
  NEW_BOT_DISPLAY_NAME='Example Bot'
  NEW_BOT_TOKEN='123456:real-token'
  NEW_BOT_PROVIDER=claude
}}
prompt_new_bot_registry_target() {{
  REGISTRY_TARGET_KIND=local
  REGISTRY_TARGET_URL=http://registry:8787
  REGISTRY_TARGET_TOKEN=local-enroll
  REGISTRY_TARGET_SCOPE=full
}}
ensure_provider_image_ready() {{ :; }}
ensure_provider_auth_ready() {{ :; }}
ensure_network() {{ :; }}
run_bot_doctor_until_ready() {{ printf 'doctor:%s\\n' "$1"; }}
start_bot_until_running() {{ printf 'start:%s\\n' "$1"; }}
verify_registry_enrollment() {{ return 0; }}
add_bot_flow
cat .deploy/bots/example-bot/.env
"""
    result = _run_bash(script, cwd=tmp_path)
    assert result.stdout.index("doctor:example-bot") < result.stdout.index("start:example-bot")
    assert "BOT_SLUG=example-bot" in result.stdout
    assert "BOT_TELEGRAM_ID=123456789" in result.stdout
    assert "BOT_AGENT_MODE=registry" in result.stdout
    assert "BOT_AGENT_REGISTRY_1_ID=local" in result.stdout
    assert "BOT_AGENT_REGISTRY_1_URL=http://registry:8787" in result.stdout
    assert "BOT_AGENT_REGISTRY_1_ENROLL_TOKEN=local-enroll" in result.stdout
    assert "BOT_AGENT_REGISTRY_1_SCOPE=full" in result.stdout
    assert "Bot is running!" in result.stdout
    assert "Bot example-bot is now connected to the local registry." in result.stdout
    assert "Bot name" not in result.stdout + result.stderr


def test_disconnect_bot_from_registry_removes_registry_keys(tmp_path: Path) -> None:
    env_dir = tmp_path / ".deploy" / "bots" / "example-bot"
    env_dir.mkdir(parents=True, exist_ok=True)
    (env_dir / ".env").write_text(
        "BOT_SLUG=example-bot\n"
        "BOT_PROVIDER=claude\n"
        "BOT_AGENT_MODE=registry\n"
        "BOT_AGENT_REGISTRY_1_ID=local\n"
        "BOT_AGENT_REGISTRY_1_URL=http://registry:8787\n"
        "BOT_AGENT_REGISTRY_1_ENROLL_TOKEN=local-enroll\n"
        "BOT_AGENT_REGISTRY_1_SCOPE=full\n"
    )

    script = f"""
set -euo pipefail
cd "{tmp_path}"
export OCTOPUS_SOURCE_ONLY=1
source "{REPO}/octopus"
cd "{tmp_path}"
restart_bot_after_config_change() {{ :; }}
offer_stop_unused_local_registry() {{ printf 'offer-stop\\n'; }}
printf 'y\\n' | disconnect_bot_from_registry_flow example-bot
cat .deploy/bots/example-bot/.env
"""
    result = _run_bash(script, cwd=tmp_path)
    assert "BOT_AGENT_MODE=standalone" in result.stdout
    assert "BOT_AGENT_REGISTRY_1_URL=" not in result.stdout
    assert "BOT_AGENT_REGISTRY_1_ENROLL_TOKEN=" not in result.stdout
    assert "Bot example-bot is now running standalone." in result.stdout
    assert "offer-stop" in result.stdout


def test_switch_local_bot_to_remote_registry_requires_https_and_updates_env(tmp_path: Path) -> None:
    env_dir = tmp_path / ".deploy" / "bots" / "example-bot"
    env_dir.mkdir(parents=True, exist_ok=True)
    (env_dir / ".env").write_text(
        "BOT_SLUG=example-bot\n"
        "BOT_PROVIDER=claude\n"
        "BOT_AGENT_MODE=registry\n"
        "BOT_AGENT_REGISTRY_1_ID=local\n"
        "BOT_AGENT_REGISTRY_1_URL=http://registry:8787\n"
        "BOT_AGENT_REGISTRY_1_ENROLL_TOKEN=local-enroll\n"
        "BOT_AGENT_REGISTRY_1_SCOPE=full\n"
    )

    script = f"""
set -euo pipefail
cd "{tmp_path}"
export OCTOPUS_SOURCE_ONLY=1
source "{REPO}/octopus"
cd "{tmp_path}"
restart_bot_after_config_change() {{ :; }}
verify_registry_enrollment() {{ return 0; }}
offer_stop_unused_local_registry() {{ printf 'offer-stop\\n'; }}
printf 'http://bad.example\\nhttps://remote.example.com\\nremote-enroll\\n' | switch_local_bot_to_remote_registry_flow example-bot
cat .deploy/bots/example-bot/.env
"""
    result = _run_bash(script, cwd=tmp_path)
    assert "Remote registry URLs must start with https://" in result.stderr
    assert "BOT_AGENT_REGISTRY_1_ID=remote-example-com" in result.stdout
    assert "BOT_AGENT_REGISTRY_1_URL=https://remote.example.com" in result.stdout
    assert "BOT_AGENT_REGISTRY_1_ENROLL_TOKEN=remote-enroll" in result.stdout
    assert "BOT_AGENT_REGISTRY_1_SCOPE=full" in result.stdout
    assert "Bot example-bot is now connected to the registry at https://remote.example.com." in result.stdout
    assert "offer-stop" in result.stdout


def test_add_registry_connection_flow_appends_indexed_registry_vars(tmp_path: Path) -> None:
    env_dir = tmp_path / ".deploy" / "bots" / "example-bot"
    env_dir.mkdir(parents=True, exist_ok=True)
    (env_dir / ".env").write_text(
        "BOT_SLUG=example-bot\n"
        "BOT_PROVIDER=claude\n"
        "BOT_AGENT_MODE=registry\n"
        "BOT_AGENT_REGISTRY_1_ID=local\n"
        "BOT_AGENT_REGISTRY_1_URL=http://registry:8787\n"
        "BOT_AGENT_REGISTRY_1_ENROLL_TOKEN=local-enroll\n"
        "BOT_AGENT_REGISTRY_1_SCOPE=full\n"
    )

    script = f"""
set -euo pipefail
cd "{tmp_path}"
export OCTOPUS_SOURCE_ONLY=1
source "{REPO}/octopus"
cd "{tmp_path}"
prompt_registry_target() {{
  REGISTRY_TARGET_KIND=remote
  REGISTRY_TARGET_URL=https://analytics.example.com
  REGISTRY_TARGET_TOKEN=analytics-enroll
  REGISTRY_TARGET_SCOPE=channel
}}
restart_bot_after_config_change() {{ :; }}
verify_registry_enrollment() {{ return 0; }}
add_registry_connection_flow example-bot
cat .deploy/bots/example-bot/.env
"""
    result = _run_bash(script, cwd=tmp_path)
    assert "BOT_AGENT_REGISTRY_1_ID=local" in result.stdout
    assert "BOT_AGENT_REGISTRY_1_URL=http://registry:8787" in result.stdout
    assert "BOT_AGENT_REGISTRY_2_ID=analytics-example-com" in result.stdout
    assert "BOT_AGENT_REGISTRY_2_URL=https://analytics.example.com" in result.stdout
    assert "BOT_AGENT_REGISTRY_2_ENROLL_TOKEN=analytics-enroll" in result.stdout
    assert "BOT_AGENT_REGISTRY_2_SCOPE=channel" in result.stdout


def test_cmd_registry_can_start_local_registry_from_empty_state(tmp_path: Path) -> None:
    script = f"""
set -euo pipefail
cd "{tmp_path}"
export OCTOPUS_SOURCE_ONLY=1
source "{REPO}/octopus"
cd "{tmp_path}"
ensure_local_registry() {{
  mkdir -p .deploy/registry
  cat > .deploy/registry/.env <<'EOF'
REGISTRY_PORT=9001
REGISTRY_ENROLL_TOKEN=token
REGISTRY_UI_TOKEN=ui
EOF
}}
printf '1\\n' | cmd_registry
"""
    result = _run_bash(script, cwd=tmp_path)
    assert "local      not configured" in result.stdout
    assert "Registry UI: http://localhost:9001/ui" in result.stdout
