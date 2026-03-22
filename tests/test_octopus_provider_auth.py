from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent


def _run_bash(script: str, *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-lc", script],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=True,
    )


def test_ensure_provider_auth_dir_creates_claude_layout(tmp_path: Path) -> None:
    script = f"""
set -euo pipefail
source "{REPO}/scripts/lib/provider.sh"
cd "{tmp_path}"
ensure_provider_auth_dir claude
test -d .deploy/provider-auth/claude/.claude
test -f .deploy/provider-auth/claude/.claude.json
"""
    _run_bash(script, cwd=tmp_path)

    auth_dir = tmp_path / ".deploy" / "provider-auth" / "claude"
    mode = stat.S_IMODE(auth_dir.stat().st_mode)
    assert mode == 0o700


def test_ensure_provider_auth_dir_creates_codex_layout(tmp_path: Path) -> None:
    script = f"""
set -euo pipefail
source "{REPO}/scripts/lib/provider.sh"
cd "{tmp_path}"
ensure_provider_auth_dir codex
test -d .deploy/provider-auth/codex/.codex
"""
    _run_bash(script, cwd=tmp_path)

    auth_dir = tmp_path / ".deploy" / "provider-auth" / "codex"
    mode = stat.S_IMODE(auth_dir.stat().st_mode)
    assert mode == 0o700


def test_provider_auth_hint_marker_is_octopus_managed(tmp_path: Path) -> None:
    script = f"""
set -euo pipefail
source "{REPO}/scripts/lib/provider.sh"
cd "{tmp_path}"
ensure_provider_auth_dir claude
update_provider_auth_hint claude true
provider_auth_hint claude
update_provider_auth_hint claude false
! provider_auth_hint claude
"""
    _run_bash(script, cwd=tmp_path)
    assert not (tmp_path / ".deploy" / "provider-auth" / "claude" / ".authed").exists()


def test_provider_has_auth_files_accepts_nonempty_claude_auth_dir(tmp_path: Path) -> None:
    script = f"""
set -euo pipefail
source "{REPO}/scripts/lib/provider.sh"
cd "{tmp_path}"
ensure_provider_auth_dir claude
mkdir -p .deploy/provider-auth/claude/.claude
printf '{{"token":"secret"}}' > .deploy/provider-auth/claude/.claude/session.json
provider_has_auth_files claude
"""
    _run_bash(script, cwd=tmp_path)


def test_entrypoint_only_chowns_data_and_symlinks_live_auth_paths() -> None:
    text = (REPO / "scripts" / "docker" / "docker-entrypoint.sh").read_text()
    assert "chown -R 1000:1000 /home/bot/data" in text
    assert "chown -R 1000:1000 /home/bot 2>/dev/null || true" not in text
    assert "rm -rf /home/bot/.claude" in text
    assert "rm -f /home/bot/.claude.json" in text
    assert "/home/bot/.provider-auth/.claude" in text
    assert "/home/bot/.provider-auth/.claude.json" in text
    assert "/home/bot/.provider-auth/.codex" in text
    assert ".config/Claude" not in text
    assert ".config/openai" not in text


def test_compose_mounts_provider_auth_and_bot_data_only() -> None:
    main = (REPO / "infra" / "compose" / "docker-compose.yml").read_text()
    shared = (REPO / "infra" / "compose" / "docker-compose.shared.yml").read_text()

    assert "/home/bot/.provider-auth:rw" in main
    assert "/home/bot/data" in main
    assert "- bot-home:/home/bot\n" not in main
    assert "BOT_PROVIDER: ${BOT_PROVIDER:-claude}" in main

    assert "/home/bot/.provider-auth:rw" in shared
    assert "/home/bot/data" in shared
    assert "- bot-home:/home/bot\n" not in shared
    assert "BOT_PROVIDER: ${BOT_PROVIDER:-claude}" in shared


def test_provider_probe_comment_records_live_paths() -> None:
    text = (REPO / "scripts" / "lib" / "provider.sh").read_text()
    assert ".claude" in text
    assert ".claude.json" in text
    assert ".codex" in text
    assert "integration probe" in text.lower()


def test_container_provider_login_requires_claude_auth_artifacts(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log_path = tmp_path / "claude.log"
    (fake_bin / "claude").write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"printf 'claude:%s\\n' \"$*\" >> {str(log_path)!r}\n"
        "exit 0\n",
        encoding="utf-8",
    )
    os.chmod(fake_bin / "claude", 0o755)

    result = subprocess.run(
        ["bash", str(REPO / "scripts" / "provider" / "container_provider_login.sh")],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "BOT_PROVIDER": "claude",
            "HOME": str(tmp_path / "home"),
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
        },
    )

    assert result.returncode == 1
    assert "Claude authentication is still incomplete." in result.stderr
    assert "✓ Claude authentication complete." not in result.stdout


def test_container_provider_login_accepts_claude_auth_file(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    auth_file = home_dir / ".claude.json"
    (fake_bin / "claude").write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"printf '{{\"token\":\"secret\"}}' > {str(auth_file)!r}\n"
        "exit 0\n",
        encoding="utf-8",
    )
    os.chmod(fake_bin / "claude", 0o755)

    result = subprocess.run(
        ["bash", str(REPO / "scripts" / "provider" / "container_provider_login.sh")],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "BOT_PROVIDER": "claude",
            "HOME": str(home_dir),
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
        },
    )

    assert result.returncode == 0
    assert "✓ Claude authentication complete. Returning to setup..." in result.stdout


def test_ensure_provider_auth_ready_reports_persistence_failure(tmp_path: Path) -> None:
    script = f"""
set -euo pipefail
cd "{tmp_path}"
export OCTOPUS_SOURCE_ONLY=1
source "{REPO}/octopus"
cd "{tmp_path}"
provider_has_auth_files() {{
  if [ "${{PROVIDER_AUTH_CHECKS:-0}}" -eq 0 ]; then
    PROVIDER_AUTH_CHECKS=1
    export PROVIDER_AUTH_CHECKS
    return 1
  fi
  return 1
}}
provider_compose() {{ return 0; }}
if ensure_provider_auth_ready claude; then
  exit 1
fi
"""
    result = subprocess.run(
        ["bash", "-lc", script],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=True,
    )

    assert "Provider authentication is required. Starting the login flow now." in result.stderr
    assert "did not persist to .deploy/provider-auth/claude" in result.stderr
