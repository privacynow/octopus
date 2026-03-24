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


def _write_registry_bot_env(tmp_path: Path, slug: str, display_name: str) -> None:
    env_dir = tmp_path / ".deploy" / "bots" / slug
    env_dir.mkdir(parents=True, exist_ok=True)
    (env_dir / ".env").write_text(
        "\n".join(
            [
                f"BOT_DISPLAY_NAME={display_name}",
                f"BOT_TELEGRAM_USERNAME={slug}",
                "BOT_PROVIDER=codex",
                "BOT_AGENT_MODE=registry",
                "BOT_AGENT_REGISTRY_1_ID=local",
                "BOT_AGENT_REGISTRY_1_URL=http://registry:8787",
                "BOT_AGENT_REGISTRY_1_ENROLL_TOKEN=test-token",
                "BOT_AGENT_REGISTRY_1_SCOPE=full",
                "",
            ]
        )
    )


def test_connect_menu_all_eligible_survives_bot_compose_stdin_reads(tmp_path: Path) -> None:
    _write_registry_bot_env(tmp_path, "m1", "M1")
    _write_registry_bot_env(tmp_path, "m2", "M2")
    script = f"""
set -euo pipefail
cd "{tmp_path}"
export OCTOPUS_SOURCE_ONLY=1
source "{REPO}/octopus"
cd "{tmp_path}"
bot_compose() {{ cat >/dev/null; return 1; }}
selected_bots_need_local_scope() {{ return 1; }}
connect_bots_to_local_registry_batch() {{ printf 'BATCH:%s\\n' "$*"; }}
printf 'a\\n' | connect_bot_to_local_registry_menu
"""
    result = _run_bash(script, cwd=tmp_path)
    assert "BATCH:full m1 m2" in result.stdout


def test_registry_connect_all_survives_bot_compose_stdin_reads(tmp_path: Path) -> None:
    _write_registry_bot_env(tmp_path, "m1", "M1")
    _write_registry_bot_env(tmp_path, "m2", "M2")
    script = f"""
set -euo pipefail
cd "{tmp_path}"
export OCTOPUS_SOURCE_ONLY=1
source "{REPO}/octopus"
cd "{tmp_path}"
bot_compose() {{ cat >/dev/null; return 1; }}
connect_bots_to_local_registry_batch() {{ printf 'BATCH:%s\\n' "$*"; }}
registry_connect_cmd --all
"""
    result = _run_bash(script, cwd=tmp_path)
    assert "BATCH:full m1 m2" in result.stdout
