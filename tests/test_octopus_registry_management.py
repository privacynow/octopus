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
registry_is_running() {{ return 1; }}
ensure_local_registry() {{
  mkdir -p .deploy/registry
  cat > .deploy/registry/.env <<'EOF'
REGISTRY_PORT=9001
REGISTRY_ENROLL_TOKEN=token
REGISTRY_UI_TOKEN=ui
EOF
  REGISTRY_WAS_CREATED=1
}}
cmd_registry start
"""
    result = _run_bash(script, cwd=tmp_path)
    assert "Registry started: http://localhost:9001/ui" in result.stdout
    assert "UI password: see .deploy/registry/.env (REGISTRY_UI_TOKEN)" in result.stdout
    assert "shown once" not in result.stdout


def test_registry_start_prints_token_once_when_created_in_tty(tmp_path: Path) -> None:
    script = f"""
set -euo pipefail
cd "{tmp_path}"
export OCTOPUS_SOURCE_ONLY=1
source "{REPO}/octopus"
cd "{tmp_path}"
stdin_is_tty() {{ return 0; }}
count_bots() {{ echo 0; }}
ensure_local_registry() {{
  mkdir -p .deploy/registry
  cat > .deploy/registry/.env <<'EOF'
REGISTRY_PORT=9002
REGISTRY_ENROLL_TOKEN=token
REGISTRY_UI_TOKEN=ui-secret
EOF
  REGISTRY_WAS_CREATED=1
}}
registry_is_running() {{ return 1; }}
registry_start_cmd
"""
    result = _run_bash(script, cwd=tmp_path)
    assert "Registry started: http://localhost:9002/ui" in result.stdout
    assert "UI password (shown once): ui-secret" in result.stdout
    assert "Stored in: .deploy/registry/.env (REGISTRY_UI_TOKEN)" in result.stdout


def test_registry_start_is_noop_when_registry_is_running(tmp_path: Path) -> None:
    script = f"""
set -euo pipefail
cd "{tmp_path}"
export OCTOPUS_SOURCE_ONLY=1
source "{REPO}/octopus"
cd "{tmp_path}"
registry_is_running() {{ return 0; }}
registry_start_cmd
"""
    result = _run_bash(script, cwd=tmp_path)
    assert result.stdout == ""


def test_registry_start_offers_to_connect_existing_bot_after_first_create(tmp_path: Path) -> None:
    env_dir = tmp_path / ".deploy" / "bots" / "example-bot"
    env_dir.mkdir(parents=True, exist_ok=True)
    (env_dir / ".env").write_text(
        "BOT_SLUG=example-bot\n"
        "BOT_DISPLAY_NAME=Example Bot\n"
        "BOT_PROVIDER=claude\n"
        "BOT_AGENT_MODE=standalone\n"
    )

    script = f"""
set -euo pipefail
cd "{tmp_path}"
export OCTOPUS_SOURCE_ONLY=1
source "{REPO}/octopus"
cd "{tmp_path}"
stdin_is_tty() {{ return 0; }}
ensure_local_registry() {{
  mkdir -p .deploy/registry
  cat > .deploy/registry/.env <<'EOF'
REGISTRY_PORT=9003
REGISTRY_ENROLL_TOKEN=token
REGISTRY_UI_TOKEN=ui-secret
EOF
  REGISTRY_WAS_CREATED=1
}}
registry_is_running() {{ return 1; }}
prompt_registry_scope() {{ printf 'coordination\\n'; }}
connect_bot_to_local_registry_once() {{ printf 'connect:%s:%s\\n' "$1" "$2"; }}
printf '\\n' | registry_start_cmd
"""
    result = _run_bash(script, cwd=tmp_path)
    assert "UI password (shown once): ui-secret" in result.stdout
    assert "connect:example-bot:coordination" in result.stdout


def test_registry_connect_cmd_retries_existing_unenrolled_local_connection_without_rewriting_env(tmp_path: Path) -> None:
    env_dir = tmp_path / ".deploy" / "bots" / "example-bot"
    env_dir.mkdir(parents=True, exist_ok=True)
    env_file = env_dir / ".env"
    env_file.write_text(
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
ensure_local_registry() {{ REGISTRY_WAS_CREATED=0; }}
read_local_registry_enroll_token() {{ printf 'fresh-token\\n'; }}
bot_registry_has_identity() {{ return 1; }}
restart_bot_after_config_change() {{ printf 'restart:%s:%s\\n' "$1" "$2" > restart.txt; }}
verify_registry_enrollment() {{ printf 'verify:%s:%s\\n' "$1" "$2" > verify.txt; }}
registry_connect_cmd example-bot
cat .deploy/bots/example-bot/.env
cat restart.txt
cat verify.txt
"""
    result = _run_bash(script, cwd=tmp_path)
    assert "BOT_AGENT_REGISTRY_1_ENROLL_TOKEN=local-enroll" in result.stdout
    assert "restart:example-bot:local" in result.stdout
    assert "verify:example-bot:local" in result.stdout
    assert "Bot example-bot is now connected to the local registry." in result.stdout


def test_registry_connect_cmd_noops_for_already_enrolled_local_connection(tmp_path: Path) -> None:
    env_dir = tmp_path / ".deploy" / "bots" / "example-bot"
    env_dir.mkdir(parents=True, exist_ok=True)
    (env_dir / ".env").write_text(
        "BOT_SLUG=example-bot\n"
        "BOT_DISPLAY_NAME=Example Bot\n"
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
ensure_local_registry() {{ REGISTRY_WAS_CREATED=0; }}
read_local_registry_enroll_token() {{ printf 'local-enroll\\n'; }}
bot_registry_has_identity() {{ return 0; }}
restart_bot_after_config_change() {{ printf 'should-not-restart\\n'; }}
registry_connect_cmd example-bot
"""
    result = _run_bash(script, cwd=tmp_path)
    assert "Example Bot is already enrolled on the local registry." in result.stdout
    assert "should-not-restart" not in result.stdout


def test_registry_connect_cmd_all_connects_only_eligible_bots(tmp_path: Path) -> None:
    alpha_dir = tmp_path / ".deploy" / "bots" / "alpha"
    bravo_dir = tmp_path / ".deploy" / "bots" / "bravo"
    charlie_dir = tmp_path / ".deploy" / "bots" / "charlie"
    alpha_dir.mkdir(parents=True, exist_ok=True)
    bravo_dir.mkdir(parents=True, exist_ok=True)
    charlie_dir.mkdir(parents=True, exist_ok=True)
    (alpha_dir / ".env").write_text(
        "BOT_SLUG=alpha\n"
        "BOT_DISPLAY_NAME=Alpha\n"
        "BOT_PROVIDER=claude\n"
        "BOT_AGENT_MODE=standalone\n"
    )
    (bravo_dir / ".env").write_text(
        "BOT_SLUG=bravo\n"
        "BOT_DISPLAY_NAME=Bravo\n"
        "BOT_PROVIDER=claude\n"
        "BOT_AGENT_MODE=registry\n"
        "BOT_AGENT_REGISTRY_1_ID=local\n"
        "BOT_AGENT_REGISTRY_1_URL=http://registry:8787\n"
        "BOT_AGENT_REGISTRY_1_ENROLL_TOKEN=local-enroll\n"
        "BOT_AGENT_REGISTRY_1_SCOPE=full\n"
    )
    (charlie_dir / ".env").write_text(
        "BOT_SLUG=charlie\n"
        "BOT_DISPLAY_NAME=Charlie\n"
        "BOT_PROVIDER=claude\n"
        "BOT_AGENT_MODE=registry\n"
        "BOT_AGENT_REGISTRY_1_ID=local\n"
        "BOT_AGENT_REGISTRY_1_URL=http://registry:8787\n"
        "BOT_AGENT_REGISTRY_1_ENROLL_TOKEN=old-enroll\n"
        "BOT_AGENT_REGISTRY_1_SCOPE=full\n"
        "BOT_AGENT_REGISTRY_2_ID=remote-example\n"
        "BOT_AGENT_REGISTRY_2_URL=https://remote.example.com\n"
        "BOT_AGENT_REGISTRY_2_ENROLL_TOKEN=remote-enroll\n"
        "BOT_AGENT_REGISTRY_2_SCOPE=channel\n"
    )

    script = f"""
set -euo pipefail
cd "{tmp_path}"
export OCTOPUS_SOURCE_ONLY=1
source "{REPO}/octopus"
cd "{tmp_path}"
ensure_local_registry() {{ REGISTRY_WAS_CREATED=0; }}
read_local_registry_enroll_token() {{ printf 'fresh-token\\n'; }}
bot_registry_has_identity() {{
  local slug="$1" registry_id="$2"
  if [ "$slug" = "bravo" ] && [ "$registry_id" = "local" ]; then
    return 0
  fi
  return 1
}}
restart_bot_after_config_change() {{ printf '%s:%s\\n' "$1" "$2" >> restart.txt; }}
verify_registry_enrollment() {{ return 0; }}
registry_connect_cmd --all --scope coordination
cat restart.txt
printf '%s\\n' '---alpha---'
cat .deploy/bots/alpha/.env
printf '%s\\n' '---charlie---'
cat .deploy/bots/charlie/.env
"""
    result = _run_bash(script, cwd=tmp_path)
    assert "Connecting Alpha... done" in result.stdout
    assert "Connecting Charlie... done" in result.stdout
    assert "2 connected." in result.stdout
    assert "alpha:local" in result.stdout
    assert "charlie:local" in result.stdout
    assert "BOT_AGENT_REGISTRY_1_SCOPE=coordination" in result.stdout
    assert "BOT_AGENT_REGISTRY_1_SCOPE=full" in result.stdout
    assert "BOT_AGENT_REGISTRY_2_URL=https://remote.example.com" in result.stdout


def test_connect_bot_to_local_registry_menu_marks_local_enrollment_and_noops_selected_bot(tmp_path: Path) -> None:
    alpha_dir = tmp_path / ".deploy" / "bots" / "alpha"
    bravo_dir = tmp_path / ".deploy" / "bots" / "bravo"
    alpha_dir.mkdir(parents=True, exist_ok=True)
    bravo_dir.mkdir(parents=True, exist_ok=True)
    (alpha_dir / ".env").write_text(
        "BOT_SLUG=alpha\n"
        "BOT_DISPLAY_NAME=Alpha\n"
        "BOT_PROVIDER=claude\n"
        "BOT_AGENT_MODE=standalone\n"
    )
    (bravo_dir / ".env").write_text(
        "BOT_SLUG=bravo\n"
        "BOT_DISPLAY_NAME=Bravo\n"
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
bot_registry_has_identity() {{
  [ "$1" = "bravo" ] && [ "$2" = "local" ]
}}
printf '2\\n' | connect_bot_to_local_registry_menu
"""
    result = _run_bash(script, cwd=tmp_path)
    assert "Bravo — enrolled on local registry" in result.stdout
    assert "Bravo is already enrolled on the local registry." in result.stdout


def test_registry_status_cmd_groups_local_connection_states(tmp_path: Path) -> None:
    alpha_dir = tmp_path / ".deploy" / "bots" / "alpha"
    bravo_dir = tmp_path / ".deploy" / "bots" / "bravo"
    charlie_dir = tmp_path / ".deploy" / "bots" / "charlie"
    alpha_dir.mkdir(parents=True, exist_ok=True)
    bravo_dir.mkdir(parents=True, exist_ok=True)
    charlie_dir.mkdir(parents=True, exist_ok=True)
    for slug, name in (("alpha", "Alpha"), ("bravo", "Bravo"), ("charlie", "Charlie")):
        (tmp_path / ".deploy" / "bots" / slug / ".env").write_text(
            f"BOT_SLUG={slug}\nBOT_DISPLAY_NAME={name}\nBOT_PROVIDER=claude\n"
        )
    registry_dir = tmp_path / ".deploy" / "registry"
    registry_dir.mkdir(parents=True, exist_ok=True)
    (registry_dir / ".env").write_text("REGISTRY_PORT=9010\n")

    script = f"""
set -euo pipefail
cd "{tmp_path}"
export OCTOPUS_SOURCE_ONLY=1
source "{REPO}/octopus"
cd "{tmp_path}"
registry_is_running() {{ return 0; }}
bot_local_registry_connection_state() {{
  case "$1" in
    alpha) printf 'enrolled\\n' ;;
    bravo) printf 'configured\\n' ;;
    *) printf 'none\\n' ;;
  esac
}}
bot_local_registry_scope() {{
  case "$1" in
    alpha) printf 'full\\n' ;;
    bravo) printf 'coordination\\n' ;;
  esac
}}
bot_local_registry_runtime_state() {{ printf 'degraded\\n'; }}
registry_status_cmd
"""
    result = _run_bash(script, cwd=tmp_path)
    assert "local      running    http://localhost:9010/ui" in result.stdout
    assert "Alpha    scope: full    state: degraded" in result.stdout
    assert "Bravo    scope: coordination    state: enrollment failed" in result.stdout
    assert "retry: ./octopus registry connect bravo" in result.stdout
    assert "Charlie" in result.stdout
