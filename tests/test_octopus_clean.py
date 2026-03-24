from __future__ import annotations

from pathlib import Path

from app.octopus_cli.core import OctopusManager, PromptIO


class FakeDockerRunner:
    def __init__(self) -> None:
        self.commands: list[tuple[str, ...]] = []

    def run(self, args, **kwargs):  # noqa: ANN001
        self.commands.append(tuple(args))
        from subprocess import CompletedProcess

        joined = " ".join(args)
        if "docker ps -a" in joined:
            return CompletedProcess(args, 0, "octopus-registry-service-1\ntelegram_bot_test_pg_master\n", "")
        if "docker volume ls" in joined:
            return CompletedProcess(args, 0, "octopus-registry_data\n", "")
        if "docker network ls" in joined:
            return CompletedProcess(args, 0, "octopus-net\n", "")
        if "docker image ls --filter reference=octopus-agent:*" in joined:
            return CompletedProcess(args, 0, "octopus-agent:codex\n", "")
        if "docker image ls --filter reference=octopus-registry-service*" in joined:
            return CompletedProcess(args, 0, "octopus-registry-service:latest\n", "")
        return CompletedProcess(args, 0, "", "")

    def bot_compose(self, slug, *args, **kwargs):  # noqa: ANN001
        self.commands.append(("bot_compose", slug, *args))
        from subprocess import CompletedProcess

        return CompletedProcess(["docker"], 0, "", "")

    def registry_compose(self, *args, **kwargs):  # noqa: ANN001
        self.commands.append(("registry_compose", *args))
        from subprocess import CompletedProcess

        return CompletedProcess(["docker"], 0, "", "")


class FakeInput:
    def __init__(self, lines: list[str]) -> None:
        self._lines = list(lines)

    def readline(self) -> str:
        if not self._lines:
            return ""
        return self._lines.pop(0)

    def isatty(self) -> bool:
        return False


class FakeOutput:
    def __init__(self) -> None:
        self.parts: list[str] = []

    def write(self, value: str) -> None:
        self.parts.append(value)

    def flush(self) -> None:
        return None

    def isatty(self) -> bool:
        return False

    def text(self) -> str:
        return "".join(self.parts)


def test_cmd_clean_removes_registry_image_and_prunes_storage(tmp_path: Path) -> None:
    deploy = tmp_path / ".deploy" / "bots" / "example-bot"
    deploy.mkdir(parents=True, exist_ok=True)
    (deploy / ".env").write_text("BOT_PROVIDER=codex\n", encoding="utf-8")
    (tmp_path / ".deploy" / "registry").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".deploy" / "registry" / ".env").write_text("REGISTRY_PORT=8787\n", encoding="utf-8")

    stdout = FakeOutput()
    io = PromptIO(stdin=FakeInput(["yes\n"]), stdout=stdout, stderr=stdout)
    docker = FakeDockerRunner()
    manager = OctopusManager(tmp_path, io=io, docker=docker)

    manager.clean_all()

    logged = "\n".join(" ".join(item) for item in docker.commands)
    assert "registry_compose down --remove-orphans" in logged
    assert "docker rm -v octopus-registry-service-1" in logged
    assert "docker rm -v telegram_bot_test_pg_master" in logged
    assert "docker image rm octopus-agent:codex" in logged
    assert "docker image rm octopus-registry-service:latest" in logged
    assert "docker volume prune -f" in logged
    assert "docker builder prune -af" in logged
