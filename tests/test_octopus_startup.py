from __future__ import annotations

from pathlib import Path

from app.octopus_cli.core import OctopusManager


class FakeDockerRunner:
    def __init__(self) -> None:
        self.commands: list[tuple[str, ...]] = []

    def ensure_network(self) -> None:
        return None

    def bot_compose(self, slug, *args, **kwargs):  # noqa: ANN001
        self.commands.append((slug, *args))
        from subprocess import CompletedProcess

        return CompletedProcess(["docker"], 0, "", "")

    def docker_status_for_slug(self, slug: str) -> str:
        del slug
        return "Up 1 second"

    def image_labels(self, image: str) -> dict[str, str]:
        del image
        return {}

    def image_exists(self, image: str) -> bool:
        del image
        return True


def test_start_bot_until_running_rebuilds_provider_image_before_start(tmp_path: Path) -> None:
    env_dir = tmp_path / ".deploy" / "bots" / "example-bot"
    env_dir.mkdir(parents=True, exist_ok=True)
    (env_dir / ".env").write_text("BOT_PROVIDER=codex\n", encoding="utf-8")

    docker = FakeDockerRunner()
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

    docker = FakeDockerRunner()
    manager = OctopusManager(tmp_path, docker=docker)
    calls: list[str] = []
    manager.ensure_provider_image_ready = lambda provider, force=False: calls.append(f"image:{provider}")  # type: ignore[method-assign]

    manager.run_bot_doctor("example-bot")

    assert calls == ["image:codex"]
    assert docker.commands == [
        ("example-bot", "run", "--rm", "bot", "python", "-m", "app.main", "--doctor"),
    ]
