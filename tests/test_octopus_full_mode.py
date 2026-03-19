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


def test_main_full_routes_zero_bots_to_full_flow(tmp_path: Path) -> None:
    script = f"""
set -euo pipefail
cd "{REPO}"
export OCTOPUS_SOURCE_ONLY=1
source "{REPO}/octopus"
count_bots() {{ echo 0; }}
first_bot_flow() {{ printf 'FLOW:%s\\n' "$1"; }}
main --full
"""
    result = _run_bash(script, cwd=tmp_path)
    assert result.stdout.strip() == "FLOW:full"


def test_first_bot_flow_full_writes_extended_env_and_registry_fields(tmp_path: Path) -> None:
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
  BOT_SETUP_ROLE='Product Bot'
  BOT_SETUP_TAGS='prod,helpdesk'
  BOT_SETUP_DESCRIPTION='Registry-enabled support bot'
  BOT_SETUP_SKILLS='triage,search'
  BOT_SETUP_ALLOWED_USERS='@alice,42'
  BOT_SETUP_TIMEOUT_SECONDS='900'
  BOT_SETUP_WORKING_DIR='/srv/bot'
  BOT_SETUP_COMPLETION_WEBHOOK_URL='https://hooks.example.com/done'
  REGISTRY_TARGET_KIND=remote
  REGISTRY_TARGET_URL='https://registry.example.com'
  REGISTRY_TARGET_TOKEN='remote-enroll'
}}
ensure_provider_image_ready() {{ :; }}
ensure_provider_auth_ready() {{ :; }}
ensure_network() {{ :; }}
run_bot_doctor_until_ready() {{ return 0; }}
start_bot_until_running() {{ return 0; }}
verify_registry_enrollment() {{ return 0; }}
first_bot_flow full
cat .deploy/bots/example-bot/.env
"""
    result = _run_bash(script, cwd=tmp_path)
    assert "BOT_ROLE=\"Product Bot\"" in result.stdout
    assert "BOT_AGENT_ROLE=\"Product Bot\"" in result.stdout
    assert "BOT_AGENT_TAGS=prod,helpdesk" in result.stdout
    assert "BOT_AGENT_DESCRIPTION=\"Registry-enabled support bot\"" in result.stdout
    assert "BOT_SKILLS=triage,search" in result.stdout
    assert "BOT_AGENT_CAPABILITIES=triage,search" in result.stdout
    assert "BOT_ALLOWED_USERS=@alice,42" in result.stdout
    assert "BOT_ALLOW_OPEN=0" in result.stdout
    assert "BOT_TIMEOUT_SECONDS=900" in result.stdout
    assert "BOT_WORKING_DIR=/srv/bot" in result.stdout
    assert "BOT_COMPLETION_WEBHOOK_URL=https://hooks.example.com/done" in result.stdout
    assert "BOT_AGENT_MODE=registry" in result.stdout
    assert "BOT_AGENT_REGISTRY_URL=https://registry.example.com" in result.stdout
    assert "BOT_AGENT_REGISTRY_ENROLL_TOKEN=remote-enroll" in result.stdout


def test_edit_bot_settings_updates_display_name(tmp_path: Path) -> None:
    bot_dir = tmp_path / ".deploy" / "bots" / "example-bot"
    bot_dir.mkdir(parents=True, exist_ok=True)
    (bot_dir / ".env").write_text(
        "BOT_SLUG=example-bot\n"
        'BOT_DISPLAY_NAME="Example Bot"\n'
        'BOT_AGENT_DISPLAY_NAME="Example Bot"\n'
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
bot_is_running() {{ return 1; }}
printf '1\\nRenamed Bot\\n7\\n' | edit_bot_settings_menu example-bot
cat .deploy/bots/example-bot/.env
"""
    result = _run_bash(script, cwd=tmp_path)
    assert 'BOT_DISPLAY_NAME="Renamed Bot"' in result.stdout
    assert 'BOT_AGENT_DISPLAY_NAME="Renamed Bot"' in result.stdout


def test_edit_bot_settings_can_clear_allowed_users_back_to_open(tmp_path: Path) -> None:
    bot_dir = tmp_path / ".deploy" / "bots" / "example-bot"
    bot_dir.mkdir(parents=True, exist_ok=True)
    (bot_dir / ".env").write_text(
        "BOT_SLUG=example-bot\n"
        "BOT_TELEGRAM_USERNAME=example_bot\n"
        "BOT_PROVIDER=claude\n"
        "BOT_AGENT_MODE=standalone\n"
        "BOT_ALLOWED_USERS=@alice\n"
        "BOT_ALLOW_OPEN=0\n"
    )

    script = f"""
set -euo pipefail
cd "{tmp_path}"
export OCTOPUS_SOURCE_ONLY=1
source "{REPO}/octopus"
cd "{tmp_path}"
bot_is_running() {{ return 1; }}
printf '4\\n\\n7\\n' | edit_bot_settings_menu example-bot
cat .deploy/bots/example-bot/.env
"""
    result = _run_bash(script, cwd=tmp_path)
    assert "BOT_ALLOWED_USERS=" not in result.stdout
    assert "BOT_ALLOW_OPEN=1" in result.stdout


def test_configure_webhook_mode_flow_updates_env(tmp_path: Path) -> None:
    bot_dir = tmp_path / ".deploy" / "bots" / "example-bot"
    bot_dir.mkdir(parents=True, exist_ok=True)
    (bot_dir / ".env").write_text(
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
bot_is_running() {{ return 1; }}
printf 'https://bot.example.com/webhook\\n8444\\n' | configure_webhook_mode_flow example-bot
cat .deploy/bots/example-bot/.env
"""
    result = _run_bash(script, cwd=tmp_path)
    assert "BOT_MODE=webhook" in result.stdout
    assert "BOT_RUNTIME_MODE=shared" in result.stdout
    assert "BOT_PROCESS_ROLE=all" in result.stdout
    assert "BOT_WEBHOOK_URL=https://bot.example.com/webhook" in result.stdout
    assert "BOT_WEBHOOK_LISTEN=0.0.0.0" in result.stdout
    assert "BOT_WEBHOOK_PORT=8444" in result.stdout
