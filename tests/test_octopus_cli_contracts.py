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


def test_normalize_slug_lowercases_and_truncates(tmp_path: Path) -> None:
    script = f"""
set -euo pipefail
source "{REPO}/scripts/lib/bot.sh"
printf '%s\\n' "$(normalize_slug 'My_Support Bot!!! With Extra Characters 1234567890')"
"""
    result = _run_bash(script, cwd=tmp_path)
    assert result.stdout.strip() == "my-support-bot-with-extra-charac"


def test_state_queries_handle_zero_and_many_bots(tmp_path: Path) -> None:
    script = f"""
set -euo pipefail
source "{REPO}/scripts/lib/state.sh"
source "{REPO}/scripts/lib/bot.sh"
cd "{tmp_path}"
ensure_deploy_dirs
test "$(count_bots)" = "0"
mkdir -p .deploy/bots/alpha .deploy/bots/bravo .deploy/bots/charlie
printf 'BOT_AGENT_MODE=standalone\\n' > .deploy/bots/alpha/.env
printf 'BOT_AGENT_MODE=registry\\nBOT_AGENT_REGISTRY_1_ID=local\\nBOT_AGENT_REGISTRY_1_URL=http://registry:8787\\nBOT_AGENT_REGISTRY_1_SCOPE=full\\nBOT_AGENT_REGISTRY_2_ID=analytics\\nBOT_AGENT_REGISTRY_2_URL=https://analytics.example.com\\nBOT_AGENT_REGISTRY_2_SCOPE=channel\\n' > .deploy/bots/bravo/.env
printf 'BOT_AGENT_MODE=registry\\nBOT_AGENT_REGISTRY_1_ID=remote-example-com\\nBOT_AGENT_REGISTRY_1_URL=https://remote.example.com\\nBOT_AGENT_REGISTRY_1_SCOPE=coordination\\n' > .deploy/bots/charlie/.env
test "$(count_bots)" = "3"
bot_is_standalone alpha
bot_is_registry bravo
bot_uses_local_reg bravo
bot_uses_remote_reg charlie
test "$(bot_registry_connection_count bravo)" = "2"
test "$(bot_registry_scope charlie)" = "coordination"
printf '%s\\n' "$(list_bot_slugs | tr '\n' ' ')"
"""
    result = _run_bash(script, cwd=tmp_path)
    listed = result.stdout.strip().split()
    assert sorted(listed) == ["alpha", "bravo", "charlie"]


def test_main_routes_nonzero_bots_to_menu(tmp_path: Path) -> None:
    script = f"""
set -euo pipefail
cd "{tmp_path}"
export OCTOPUS_SOURCE_ONLY=1
source "{REPO}/octopus"
count_bots() {{ echo 2; }}
main_menu() {{ printf 'MENU\\n'; }}
main
"""
    result = _run_bash(script, cwd=tmp_path)
    assert result.stdout.strip() == "MENU"


def test_resolve_bot_slug_prompts_when_multiple_bots_exist(tmp_path: Path) -> None:
    for slug in ("alpha", "bravo"):
        env_dir = tmp_path / ".deploy" / "bots" / slug
        env_dir.mkdir(parents=True, exist_ok=True)
        (env_dir / ".env").write_text(f"BOT_SLUG={slug}\n")

    script = f"""
set -euo pipefail
cd "{tmp_path}"
export OCTOPUS_SOURCE_ONLY=1
source "{REPO}/octopus"
cd "{tmp_path}"
printf '2\\n' | resolve_bot_slug
    """
    result = _run_bash(script, cwd=tmp_path)
    assert result.stdout.splitlines()[-1] == "bravo"


def test_cmd_help_lists_registry_subcommands(tmp_path: Path) -> None:
    script = f"""
set -euo pipefail
cd "{tmp_path}"
export OCTOPUS_SOURCE_ONLY=1
source "{REPO}/octopus"
cmd_help
"""
    result = _run_bash(script, cwd=tmp_path)
    assert "registry start" in result.stdout
    assert "registry connect [slug|--all]" in result.stdout
    assert "REGISTRY_UI_TOKEN" in result.stdout


def test_bot_compose_uses_slug_project_env_and_network(tmp_path: Path) -> None:
    env_dir = tmp_path / ".deploy" / "bots" / "sample-bot"
    env_dir.mkdir(parents=True, exist_ok=True)
    (env_dir / ".env").write_text("BOT_PROVIDER=codex\n")

    fake_docker = tmp_path / "docker"
    fake_docker.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$*\" > docker-args.txt\n"
    )
    fake_docker.chmod(0o755)

    script = f"""
set -euo pipefail
export PATH="{tmp_path}:$PATH"
source "{REPO}/scripts/lib/bot.sh"
source "{REPO}/scripts/lib/docker.sh"
cd "{tmp_path}"
ensure_network() {{ :; }}
bot_compose sample-bot up -d bot
cat docker-args.txt
"""
    result = _run_bash(script, cwd=tmp_path)
    args = result.stdout.strip()
    assert "-p octopus-sample-bot" in args
    assert "--env-file .deploy/bots/sample-bot/.env" in args
    assert "--profile bot --env-file .deploy/bots/sample-bot/.env up -d bot" in args


def test_registry_compose_uses_octopus_registry_project(tmp_path: Path) -> None:
    registry_dir = tmp_path / ".deploy" / "registry"
    registry_dir.mkdir(parents=True, exist_ok=True)
    (registry_dir / ".env").write_text("REGISTRY_PORT=8787\n")

    fake_docker = tmp_path / "docker"
    fake_docker.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$*\" > docker-args.txt\n"
    )
    fake_docker.chmod(0o755)

    script = f"""
set -euo pipefail
export PATH="{tmp_path}:$PATH"
source "{REPO}/scripts/lib/docker.sh"
cd "{tmp_path}"
ensure_network() {{ :; }}
registry_compose ps
cat docker-args.txt
"""
    result = _run_bash(script, cwd=tmp_path)
    args = result.stdout.strip()
    assert "-p octopus-registry" in args
    assert "--env-file .deploy/registry/.env" in args
    assert "--profile registry --env-file .deploy/registry/.env ps" in args


def test_provider_is_authed_updates_hint_from_authoritative_check(tmp_path: Path) -> None:
    script = f"""
set -euo pipefail
source "{REPO}/scripts/lib/provider.sh"
cd "{tmp_path}"
check_provider_image() {{ :; }}
provider_compose() {{ return 0; }}
provider_is_authed claude
provider_auth_hint claude
provider_compose() {{ return 1; }}
! provider_is_authed claude
! provider_auth_hint claude
"""
    _run_bash(script, cwd=tmp_path)


def test_write_registry_connection_records_rewrites_indexed_env(tmp_path: Path) -> None:
    env_file = tmp_path / ".deploy" / "bots" / "example-bot" / ".env"
    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_text(
        "BOT_AGENT_MODE=registry\n"
        "BOT_AGENT_REGISTRY_URL=http://legacy.example.com\n"
        "BOT_AGENT_REGISTRY_ENROLL_TOKEN=legacy-token\n"
    )

    script = f"""
set -euo pipefail
source "{REPO}/scripts/lib/bot.sh"
cd "{tmp_path}"
write_registry_connection_records ".deploy/bots/example-bot/.env" \
  "local|http://registry:8787|local-enroll|full" \
  "analytics|https://analytics.example.com|analytics-enroll|channel"
cat .deploy/bots/example-bot/.env
"""
    result = _run_bash(script, cwd=tmp_path)
    assert "BOT_AGENT_REGISTRY_URL=" not in result.stdout
    assert "BOT_AGENT_REGISTRY_ENROLL_TOKEN=" not in result.stdout
    assert "BOT_AGENT_REGISTRY_1_ID=local" in result.stdout
    assert "BOT_AGENT_REGISTRY_1_URL=http://registry:8787" in result.stdout
    assert "BOT_AGENT_REGISTRY_2_ID=analytics" in result.stdout
    assert "BOT_AGENT_REGISTRY_2_SCOPE=channel" in result.stdout


def test_print_bot_registry_connection_lines_formats_scope_and_connectivity(tmp_path: Path) -> None:
    bot_dir = tmp_path / ".deploy" / "bots" / "example-bot"
    bot_dir.mkdir(parents=True, exist_ok=True)
    (bot_dir / ".env").write_text(
        "BOT_AGENT_MODE=registry\n"
        "BOT_AGENT_REGISTRY_1_ID=local\n"
        "BOT_AGENT_REGISTRY_1_URL=http://registry:8787\n"
        "BOT_AGENT_REGISTRY_1_SCOPE=full\n"
        "BOT_AGENT_REGISTRY_2_ID=analytics\n"
        "BOT_AGENT_REGISTRY_2_URL=https://analytics.example.com\n"
        "BOT_AGENT_REGISTRY_2_SCOPE=channel\n"
    )

    script = f"""
set -euo pipefail
cd "{tmp_path}"
export OCTOPUS_SOURCE_ONLY=1
source "{REPO}/octopus"
cd "{tmp_path}"
bot_is_running() {{ return 0; }}
bot_registry_state_rows() {{
  printf 'local|connected|\\n'
  printf 'analytics|degraded|registry_timeout\\n'
}}
print_bot_registry_connection_lines example-bot
"""
    result = _run_bash(script, cwd=tmp_path)
    assert "local    full    connected    http://registry:8787" in result.stdout
    assert "analytics    channel    degraded    https://analytics.example.com" in result.stdout


def test_bot_compose_rejects_unknown_slug(tmp_path: Path) -> None:
    script = f"""
set -euo pipefail
source "{REPO}/scripts/lib/bot.sh"
source "{REPO}/scripts/lib/docker.sh"
cd "{tmp_path}"
if bot_compose missing-bot ps >out.txt 2>err.txt; then
  exit 1
fi
grep -q "No env file for bot 'missing-bot'" err.txt
"""
    _run_bash(script, cwd=tmp_path)


def test_repo_has_no_legacy_startup_surface_references(tmp_path: Path) -> None:
    banned = [
        "guided" "_start",
        "shared" "_start",
        "lib_" "env.sh",
        ".env" ".bot",
        "host" ".docker.internal",
        "172" ".17.0.1",
    ]
    this_file = Path(__file__).resolve()
    offenders: list[tuple[Path, str]] = []
    for path in REPO.rglob("*"):
        if path == this_file or not path.is_file():
            continue
        if (
            ".git" in path.parts
            or ".venv" in path.parts
            or ".pytest_cache" in path.parts
            or "__pycache__" in path.parts
        ):
            continue
        try:
            text = path.read_text()
        except Exception:
            continue
        for marker in banned:
            if marker in text:
                offenders.append((path.relative_to(REPO), marker))
                break
    assert offenders == []
