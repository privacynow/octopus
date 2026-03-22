from __future__ import annotations

import stat
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


def test_octopus_main_routes_zero_bots_to_first_flow(tmp_path: Path) -> None:
    script = f"""
set -euo pipefail
cd "{REPO}"
export OCTOPUS_SOURCE_ONLY=1
source "{REPO}/octopus"
count_bots() {{ echo 0; }}
first_bot_flow() {{ printf 'FLOW:%s\\n' "$1"; }}
main
"""
    result = _run_bash(script, cwd=tmp_path)
    assert result.stdout.strip() == "FLOW:quick"


def test_first_bot_flow_writes_identity_driven_env_without_naming_prompt(tmp_path: Path) -> None:
    script = f"""
set -euo pipefail
cd "{tmp_path}"
export OCTOPUS_SOURCE_ONLY=1
source "{REPO}/octopus"
cd "{tmp_path}"
print_channel_setup_help() {{ :; }}
validate_telegram_token() {{ printf '123456789\\nexample_bot\\nExample Bot\\n'; }}
prompt_with_default() {{ printf 'claude\\n'; }}
ensure_provider_image_ready() {{ :; }}
ensure_provider_auth_ready() {{ :; }}
ensure_network() {{ :; }}
run_bot_doctor_until_ready() {{ return 0; }}
start_bot_until_running() {{ return 0; }}
printf '123456:real-token\\n\\n' | first_bot_flow quick
"""
    result = _run_bash(script, cwd=tmp_path)

    env_file = tmp_path / ".deploy" / "bots" / "example-bot" / ".env"
    assert env_file.exists()
    env_text = env_file.read_text()
    assert "BOT_INSTANCE=example-bot" in env_text
    assert "BOT_SLUG=example-bot" in env_text
    assert "BOT_AGENT_SLUG=example-bot" in env_text
    assert "BOT_TELEGRAM_ID=123456789" in env_text
    assert "BOT_TELEGRAM_USERNAME=example_bot" in env_text
    assert 'BOT_DISPLAY_NAME="Example Bot"' in env_text
    assert 'BOT_AGENT_DISPLAY_NAME="Example Bot"' in env_text
    assert "TELEGRAM_BOT_TOKEN=123456:real-token" in env_text
    assert "BOT_CREDENTIAL_KEY=" in env_text
    assert "BOT_CREDENTIAL_KEY=123456:real-token" not in env_text
    assert "BOT_PROVIDER=claude" in env_text

    mode = stat.S_IMODE(env_file.stat().st_mode)
    assert mode == 0o600
    assert "This token belongs to Example Bot (@example_bot)." in result.stdout
    assert "Bot is running!" in result.stdout
    assert "Bot name" not in result.stdout + result.stderr


def test_prepare_new_bot_setup_quick_can_switch_to_full_mode(tmp_path: Path) -> None:
    script = f"""
set -euo pipefail
cd "{tmp_path}"
export OCTOPUS_SOURCE_ONLY=1
source "{REPO}/octopus"
cd "{tmp_path}"
prompt_first_bot_identity() {{
  FIRST_BOT_TELEGRAM_ID=123456789
  FIRST_BOT_TELEGRAM_USERNAME=example_bot
  FIRST_BOT_DISPLAY_NAME='Example Bot'
  FIRST_BOT_TOKEN='123456:real-token'
}}
prompt_provider_choice() {{ printf 'claude\\n'; }}
prompt_full_bot_setup_options() {{
  BOT_SETUP_ROLE='Advanced Bot'
  REGISTRY_TARGET_KIND='standalone'
}}
prepare_new_bot_setup quick <<< $'full\\n'
printf 'mode=%s\\nrole=%s\\n' "$NEW_BOT_SETUP_MODE" "$BOT_SETUP_ROLE"
"""
    result = _run_bash(script, cwd=tmp_path)
    assert "mode=full" in result.stdout
    assert "role=Advanced Bot" in result.stdout


def test_first_bot_flow_rejects_duplicate_telegram_identity(tmp_path: Path) -> None:
    env_dir = tmp_path / ".deploy" / "bots" / "existing-bot"
    env_dir.mkdir(parents=True, exist_ok=True)
    (env_dir / ".env").write_text(
        "BOT_SLUG=existing-bot\n"
        "BOT_TELEGRAM_ID=123456789\n"
        "BOT_TELEGRAM_USERNAME=example_bot\n"
        'BOT_DISPLAY_NAME="Existing Bot"\n'
    )

    script = f"""
set -euo pipefail
cd "{tmp_path}"
export OCTOPUS_SOURCE_ONLY=1
source "{REPO}/octopus"
cd "{tmp_path}"
print_channel_setup_help() {{ :; }}
validate_telegram_token() {{ printf '123456789\\nexample_bot\\nExample Bot\\n'; }}
if printf '123456:real-token\\n' | first_bot_flow quick; then
  exit 1
fi
    """
    result = _run_bash(script, cwd=tmp_path, check=False)
    assert result.returncode == 0
    assert "already configured as 'existing-bot'" in result.stderr
