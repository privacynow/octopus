from __future__ import annotations

from pathlib import Path

from app.octopus_cli.core import OctopusManager, PromptIO
from app.octopus_cli.models import Action


class _ComposeDockerRunner:
    def __init__(self) -> None:
        self.commands: list[tuple[str, ...]] = []

    def ensure_network(self) -> None:
        return None

    def docker_status_for_slug(self, slug: str) -> str:
        del slug
        return "Up 1 second"

    def bot_compose(self, slug, *args, **kwargs):  # noqa: ANN001
        del kwargs
        self.commands.append((slug, *args))
        from subprocess import CompletedProcess

        return CompletedProcess(["docker"], 0, "", "")

    def image_labels(self, image: str) -> dict[str, str]:
        del image
        return {}

    def image_exists(self, image: str) -> bool:
        del image
        return True


class _CleanupDockerRunner:
    def __init__(self) -> None:
        self.commands: list[tuple[str, ...]] = []

    def run(self, args, **kwargs):  # noqa: ANN001
        del kwargs
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
        del kwargs
        self.commands.append(("bot_compose", slug, *args))
        from subprocess import CompletedProcess

        return CompletedProcess(["docker"], 0, "", "")

    def registry_compose(self, *args, **kwargs):  # noqa: ANN001
        del kwargs
        self.commands.append(("registry_compose", *args))
        from subprocess import CompletedProcess

        return CompletedProcess(["docker"], 0, "", "")


class _FakeInput:
    def __init__(self, lines: list[str]) -> None:
        self._lines = list(lines)

    def readline(self) -> str:
        if not self._lines:
            return ""
        return self._lines.pop(0)

    def isatty(self) -> bool:
        return False


class _FakeOutput:
    def __init__(self) -> None:
        self.parts: list[str] = []

    def write(self, value: str) -> None:
        self.parts.append(value)

    def flush(self) -> None:
        return None

    def isatty(self) -> bool:
        return False


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
        ),
        encoding="utf-8",
    )


def test_connect_targets_default_to_all_eligible_registry_bots(tmp_path: Path) -> None:
    _write_registry_bot_env(tmp_path, "m1", "M1")
    _write_registry_bot_env(tmp_path, "m2", "M2")
    manager = OctopusManager(tmp_path, docker=_ComposeDockerRunner())
    state = manager.inspect_state()

    targets = manager.resolve_targets([], Action.CONNECT, state)

    assert [target.identifier for target in targets] == ["m1", "m2"]


def test_resolve_bot_accepts_unique_display_name_alias(tmp_path: Path) -> None:
    _write_registry_bot_env(tmp_path, "lift-and-shift-m1-bot", "M1")
    _write_registry_bot_env(tmp_path, "lift-and-shift-m2-bot", "M2")
    manager = OctopusManager(tmp_path, docker=_ComposeDockerRunner())
    state = manager.inspect_state()

    bot = manager.resolve_bot("m1", state)

    assert bot.slug == "lift-and-shift-m1-bot"


def test_start_bot_rebuilds_provider_image_before_start(tmp_path: Path) -> None:
    env_dir = tmp_path / ".deploy" / "bots" / "example-bot"
    env_dir.mkdir(parents=True, exist_ok=True)
    (env_dir / ".env").write_text("BOT_PROVIDER=codex\n", encoding="utf-8")

    docker = _ComposeDockerRunner()
    manager = OctopusManager(tmp_path, docker=docker)
    calls: list[str] = []
    manager.ensure_provider_image_ready = lambda provider, force=False: calls.append(f"image:{provider}")  # type: ignore[method-assign]

    manager.start_bot("example-bot")

    assert calls == ["image:codex"]
    assert docker.commands == [("example-bot", "up", "-d", "bot")]


def test_run_bot_doctor_rebuilds_provider_image_before_doctor(tmp_path: Path) -> None:
    env_dir = tmp_path / ".deploy" / "bots" / "example-bot"
    env_dir.mkdir(parents=True, exist_ok=True)
    (env_dir / ".env").write_text("BOT_PROVIDER=codex\n", encoding="utf-8")

    docker = _ComposeDockerRunner()
    manager = OctopusManager(tmp_path, docker=docker)
    calls: list[str] = []
    manager.ensure_provider_image_ready = lambda provider, force=False: calls.append(f"image:{provider}")  # type: ignore[method-assign]

    manager.run_bot_doctor("example-bot")

    assert calls == ["image:codex"]
    assert docker.commands == [
        ("example-bot", "run", "--rm", "bot", "python", "-m", "app.main", "--doctor"),
    ]


def test_clean_all_removes_registry_image_and_prunes_storage(tmp_path: Path) -> None:
    deploy = tmp_path / ".deploy" / "bots" / "example-bot"
    deploy.mkdir(parents=True, exist_ok=True)
    (deploy / ".env").write_text("BOT_PROVIDER=codex\n", encoding="utf-8")
    (tmp_path / ".deploy" / "registry").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".deploy" / "registry" / ".env").write_text("REGISTRY_PORT=8787\n", encoding="utf-8")

    stdout = _FakeOutput()
    io = PromptIO(stdin=_FakeInput(["yes\n"]), stdout=stdout, stderr=stdout)
    docker = _CleanupDockerRunner()
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
