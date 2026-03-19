"""Security tests for subprocess environment isolation."""

from __future__ import annotations

from pathlib import Path

from app.providers.codex import CodexProvider
from app.subprocess_env import build_subprocess_env
from app.summarize import _summary_env
from tests.support.config_support import make_config
from tests.support.handler_support import FakeProgress


class _AsyncReader:
    def __init__(self, chunks: list[bytes] | None = None) -> None:
        self._chunks = list(chunks or [b""])

    async def readline(self) -> bytes:
        if self._chunks:
            return self._chunks.pop(0)
        return b""

    async def read(self) -> bytes:
        return b""


class _FakeProc:
    def __init__(self) -> None:
        self.stdout = _AsyncReader([b""])
        self.stderr = _AsyncReader()
        self.returncode = 0

    async def wait(self) -> int:
        return 0

    def kill(self) -> None:
        self.returncode = -9


def test_build_subprocess_env_filters_ambient_secrets_and_keeps_explicit_env(monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("HOME", "/tmp/home")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-secret")
    monkeypatch.setenv("BOT_TELEGRAM_TOKEN", "telegram-secret")
    monkeypatch.setenv("CODEX_HOME", "/tmp/codex-home")
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("SSH_AUTH_SOCK", "/tmp/agent.sock")
    monkeypatch.setenv("GIT_ASKPASS", "/tmp/askpass.sh")
    monkeypatch.setenv("HTTPS_PROXY", "https://proxy.internal")

    env = build_subprocess_env(
        allowed_keys=("OPENAI_API_KEY",),
        extra_env={"SKILL_TOKEN": "credential-secret"},
        blocked_keys=("CLAUDECODE",),
    )

    assert env["PATH"] == "/usr/bin"
    assert env["HOME"] == "/tmp/home"
    assert env["OPENAI_API_KEY"] == "openai-secret"
    assert env["SKILL_TOKEN"] == "credential-secret"
    assert "BOT_TELEGRAM_TOKEN" not in env
    assert "CODEX_HOME" not in env
    assert "CLAUDECODE" not in env
    assert "SSH_AUTH_SOCK" not in env
    assert "GIT_ASKPASS" not in env
    assert "HTTPS_PROXY" not in env


def test_summary_env_filters_runtime_secrets(monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("HOME", "/tmp/home")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-secret")
    monkeypatch.setenv("BOT_DATABASE_URL", "postgresql://user:pass@db/service")
    monkeypatch.setenv("CLAUDECODE", "1")

    env = _summary_env()

    assert env["PATH"] == "/usr/bin"
    assert env["HOME"] == "/tmp/home"
    assert env["ANTHROPIC_API_KEY"] == "anthropic-secret"
    assert "BOT_DATABASE_URL" not in env
    assert "CLAUDECODE" not in env


async def test_codex_run_cmd_uses_allowlisted_builder_env(monkeypatch, tmp_path: Path):
    captured: dict[str, object] = {}

    def fake_build_subprocess_env(*, allowed_keys=(), extra_env=None, blocked_keys=()):
        captured["allowed_keys"] = tuple(allowed_keys)
        captured["extra_env"] = dict(extra_env or {})
        captured["blocked_keys"] = tuple(blocked_keys)
        return {
            "PATH": "/usr/bin",
            "HOME": str(tmp_path),
            "OPENAI_API_KEY": "openai-secret",
            "SKILL_TOKEN": "credential-secret",
        }

    async def fake_exec(*cmd, **kwargs):
        captured["env"] = dict(kwargs["env"])
        return _FakeProc()

    monkeypatch.setattr("app.providers.codex.build_subprocess_env", fake_build_subprocess_env)
    monkeypatch.setattr("app.providers.codex.asyncio.create_subprocess_exec", fake_exec)

    provider = CodexProvider(make_config(working_dir=tmp_path))
    result = await provider._run_cmd(
        ["codex", "exec", "--json", "-C", str(tmp_path), "reply with ok"],
        FakeProgress(),
        extra_env={"SKILL_TOKEN": "credential-secret"},
        working_dir=str(tmp_path),
    )

    assert captured["allowed_keys"] == ("OPENAI_API_KEY", "CODEX_HOME")
    assert captured["extra_env"] == {"SKILL_TOKEN": "credential-secret"}
    assert captured["env"] == {
        "PATH": "/usr/bin",
        "HOME": str(tmp_path),
        "OPENAI_API_KEY": "openai-secret",
        "SKILL_TOKEN": "credential-secret",
    }
    assert result.text == "[empty response]"


def test_app_code_does_not_copy_full_process_environment():
    app_root = Path(__file__).resolve().parents[1] / "app"
    offenders: list[str] = []
    for path in app_root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "os.environ.copy(" in text:
            offenders.append(str(path))
    assert offenders == []
