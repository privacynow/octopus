from __future__ import annotations

from pathlib import Path

from app.provider_auth import (
    auth_artifact_errors,
    cleanup_runtime_auth,
    ensure_auth_layout,
    has_auth_artifacts,
    runtime_auth_root,
    shared_auth_root,
    sync_runtime_to_shared,
)


def test_shared_auth_root_is_provider_specific(tmp_path: Path) -> None:
    base = tmp_path / "provider-auth"
    assert shared_auth_root("claude", base) == base
    assert shared_auth_root("codex", base) == base / ".codex"


def test_has_auth_artifacts_detects_claude_file_and_codex_json(tmp_path: Path) -> None:
    claude_root = tmp_path / "claude"
    ensure_auth_layout("claude", claude_root)
    assert has_auth_artifacts("claude", claude_root) is False
    (claude_root / ".claude.json").write_text('{"token":"secret"}', encoding="utf-8")
    assert has_auth_artifacts("claude", claude_root) is True

    codex_root = tmp_path / "codex" / ".codex"
    ensure_auth_layout("codex", codex_root)
    assert has_auth_artifacts("codex", codex_root) is False
    (codex_root / "auth.json").write_text("{}", encoding="utf-8")
    assert has_auth_artifacts("codex", codex_root) is True


def test_auth_artifact_errors_report_invalid_json(tmp_path: Path) -> None:
    claude_root = tmp_path / "claude"
    ensure_auth_layout("claude", claude_root)
    (claude_root / ".claude.json").write_text("{", encoding="utf-8")

    codex_root = tmp_path / "codex" / ".codex"
    ensure_auth_layout("codex", codex_root)
    (codex_root / "auth.json").write_text("{", encoding="utf-8")

    assert "invalid JSON" in auth_artifact_errors("claude", claude_root)[0]
    assert "invalid JSON" in auth_artifact_errors("codex", codex_root)[0]


def test_sync_and_cleanup_runtime_auth_for_claude(tmp_path: Path) -> None:
    runtime_home = tmp_path / "runtime-home"
    runtime_home.mkdir()
    (runtime_home / ".claude").mkdir()
    (runtime_home / ".claude.json").write_text('{"token":"secret"}', encoding="utf-8")
    (runtime_home / ".claude" / "session.json").write_text('{"ok":true}', encoding="utf-8")

    shared_base = tmp_path / "shared"
    sync_runtime_to_shared("claude", home_dir=runtime_home, shared_base_dir=shared_base)

    assert (shared_base / ".claude.json").read_text(encoding="utf-8") == '{"token":"secret"}'
    assert (shared_base / ".claude" / "session.json").read_text(encoding="utf-8") == '{"ok":true}'

    removed = cleanup_runtime_auth("claude", home_dir=runtime_home)
    assert set(removed) == {runtime_home / ".claude", runtime_home / ".claude.json"}
    assert not (runtime_home / ".claude").exists()
    assert not (runtime_home / ".claude.json").exists()


def test_runtime_auth_root_uses_codex_home_env(monkeypatch, tmp_path: Path) -> None:
    codex_home = tmp_path / ".codex-custom"
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    assert runtime_auth_root("codex", home_dir=Path("/ignored")) == codex_home
