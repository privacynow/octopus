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


def test_cmd_clean_removes_registry_image_and_prunes_storage(tmp_path: Path) -> None:
    script = f"""
set -euo pipefail
cd "{tmp_path}"
export OCTOPUS_SOURCE_ONLY=1
source "{REPO}/octopus"
cd "{tmp_path}"
mkdir -p .deploy

list_bot_slugs() {{ printf 'example-bot\\n'; }}
bot_compose() {{ printf 'bot_compose:%s\\n' "$*" >> clean.log; }}
has_local_registry() {{ return 0; }}
registry_compose() {{ printf 'registry_compose:%s\\n' "$*" >> clean.log; }}

docker() {{
  case "$*" in
    'ps -a --filter name=octopus- --filter name=telegram_bot_test_pg --format {{{{.Names}}}}')
      printf 'octopus-registry-service-1\\ntelegram_bot_test_pg_master\\n'
      ;;
    'volume ls --filter name=octopus --format {{{{.Name}}}}')
      printf 'octopus-registry_data\\n'
      ;;
    'network ls --filter name=octopus --format {{{{.Name}}}}')
      printf 'octopus-net\\n'
      ;;
    'image ls --filter reference=octopus-agent:* --format {{{{.Repository}}}}:{{{{.Tag}}}}')
      printf 'octopus-agent:codex\\n'
      ;;
    'image ls --filter reference=octopus-registry-service --format {{{{.Repository}}}}:{{{{.Tag}}}}')
      printf 'octopus-registry-service:latest\\n'
      ;;
    *)
      printf '%s\\n' "$*" >> clean.log
      ;;
  esac
}}

printf 'yes\\n' | cmd_clean
cat clean.log
"""
    result = _run_bash(script, cwd=tmp_path)
    assert "registry_compose:down --remove-orphans" in result.stdout
    assert "rm -v octopus-registry-service-1" in result.stdout
    assert "rm -v telegram_bot_test_pg_master" in result.stdout
    assert "image rm octopus-agent:codex" in result.stdout
    assert "image rm octopus-registry-service:latest" in result.stdout
    assert "volume prune -f" in result.stdout
    assert "builder prune -af" in result.stdout
