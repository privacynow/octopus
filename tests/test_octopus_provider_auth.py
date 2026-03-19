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


def test_entrypoint_only_chowns_data_and_symlinks_live_auth_paths() -> None:
    text = (REPO / "scripts" / "docker" / "docker-entrypoint.sh").read_text()
    assert "chown -R 1000:1000 /home/bot/data" in text
    assert "chown -R 1000:1000 /home/bot 2>/dev/null || true" not in text
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
