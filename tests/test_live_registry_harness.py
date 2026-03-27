from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from tests.e2e.live_registry_harness import FreshStack


def _make_deploy_tree(tmp_path: Path) -> tuple[Path, Path]:
    deploy_dir = tmp_path / ".deploy"
    (deploy_dir / "registry").mkdir(parents=True)
    (deploy_dir / "bots" / "bot-a").mkdir(parents=True)
    (deploy_dir / "provider-auth" / "codex").mkdir(parents=True)
    (deploy_dir / "registry" / ".env").write_text(
        "REGISTRY_PORT=8787\nREGISTRY_UI_TOKEN=ui-token\nREGISTRY_ENROLL_TOKEN=enroll-token\n",
        encoding="utf-8",
    )
    (deploy_dir / "bots" / "bot-a" / ".env").write_text(
        "BOT_PROVIDER=codex\nBOT_DISPLAY_NAME=Bot A\n",
        encoding="utf-8",
    )
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    return deploy_dir, artifacts_dir


def test_read_bot_registry_state_exec_script_imports_path_correctly(tmp_path: Path) -> None:
    deploy_dir, artifacts_dir = _make_deploy_tree(tmp_path)
    stack = FreshStack(tmp_path, deploy_dir, artifacts_dir, "test")
    captured: dict[str, object] = {}

    def _bot_compose(slug: str, *args: str, **kwargs):
        captured["slug"] = slug
        captured["args"] = args
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=0, stdout='{"connectivity_state":"connected"}', stderr="")

    stack.bot_compose = _bot_compose  # type: ignore[method-assign]

    state = stack.read_bot_registry_state("bot-a", "local")

    assert state == {"connectivity_state": "connected"}
    script = captured["args"][-1]
    assert isinstance(script, str)
    assert "from pathlib import Path" in script


def test_write_bot_file_exec_script_imports_path_correctly(tmp_path: Path) -> None:
    deploy_dir, artifacts_dir = _make_deploy_tree(tmp_path)
    stack = FreshStack(tmp_path, deploy_dir, artifacts_dir, "test")
    captured: dict[str, object] = {}

    def _bot_compose(slug: str, *args: str, **kwargs):
        captured["slug"] = slug
        captured["args"] = args
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    stack.bot_compose = _bot_compose  # type: ignore[method-assign]

    stack.write_bot_file("bot-a", "/tmp/example.txt", "secret")

    script = captured["args"][-1]
    assert isinstance(script, str)
    assert "from pathlib import Path" in script
