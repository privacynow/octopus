from __future__ import annotations

from pathlib import Path

from app.octopus_cli.cli import OctopusCLI
from app.octopus_cli.core import OctopusManager
from app.octopus_cli.models import Action


class FakeDockerRunner:
    def __init__(self) -> None:
        self.commands: list[tuple[str, ...]] = []

    def docker_status_for_slug(self, slug: str) -> str:
        del slug
        return ""

    def bot_compose(self, slug, *args, **kwargs):  # noqa: ANN001
        self.commands.append((slug, *args))
        from subprocess import CompletedProcess

        return CompletedProcess(["docker"], 1, "", "")

    def image_labels(self, image: str) -> dict[str, str]:
        del image
        return {}

    def image_exists(self, image: str) -> bool:
        del image
        return True


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


def test_connect_all_targets_all_eligible_bots(tmp_path: Path) -> None:
    _write_registry_bot_env(tmp_path, "m1", "M1")
    _write_registry_bot_env(tmp_path, "m2", "M2")
    manager = OctopusManager(tmp_path, docker=FakeDockerRunner())
    state = manager.inspect_state()

    targets = manager.resolve_targets([], Action.CONNECT, state)

    assert [target.identifier for target in targets] == ["m1", "m2"]


def test_short_alias_resolution_uses_display_name_when_unique(tmp_path: Path) -> None:
    _write_registry_bot_env(tmp_path, "lift-and-shift-m1-bot", "M1")
    _write_registry_bot_env(tmp_path, "lift-and-shift-m2-bot", "M2")
    manager = OctopusManager(tmp_path, docker=FakeDockerRunner())
    state = manager.inspect_state()

    bot = manager.resolve_bot("m1", state)

    assert bot.slug == "lift-and-shift-m1-bot"
