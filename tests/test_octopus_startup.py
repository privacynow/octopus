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


def test_start_bot_until_running_rebuilds_provider_image_before_start(tmp_path: Path) -> None:
    script = f"""
set -euo pipefail
cd "{tmp_path}"
export OCTOPUS_SOURCE_ONLY=1
source "{REPO}/octopus"
cd "{tmp_path}"
mkdir -p .deploy/bots/example-bot
cat > .deploy/bots/example-bot/.env <<'EOF'
BOT_PROVIDER=codex
EOF

ensure_provider_image_ready() {{ printf 'image:%s\\n' "$1" >> calls.log; }}
bot_compose() {{ printf 'compose:%s\\n' "$*" >> calls.log; }}
bot_is_running() {{ return 0; }}
sleep() {{ :; }}

start_bot_until_running example-bot
cat calls.log
"""
    result = _run_bash(script, cwd=tmp_path)
    assert result.stdout.splitlines() == [
        "image:codex",
        "compose:example-bot up -d bot",
    ]


def test_run_bot_doctor_rebuilds_provider_image_before_doctor(tmp_path: Path) -> None:
    script = f"""
set -euo pipefail
cd "{tmp_path}"
export OCTOPUS_SOURCE_ONLY=1
source "{REPO}/octopus"
cd "{tmp_path}"
mkdir -p .deploy/bots/example-bot
cat > .deploy/bots/example-bot/.env <<'EOF'
BOT_PROVIDER=codex
EOF

ensure_provider_image_ready() {{ printf 'image:%s\\n' "$1" >> calls.log; }}
bot_compose() {{ printf 'compose:%s\\n' "$*" >> calls.log; }}

run_bot_doctor example-bot >/dev/null
cat calls.log
"""
    result = _run_bash(script, cwd=tmp_path)
    assert result.stdout.splitlines() == [
        "image:codex",
        "compose:example-bot run --rm bot python -m app.main --doctor",
    ]
