from __future__ import annotations

import json
from pathlib import Path

import pytest

import app.octopus_cli.core as octopus_core
from app.octopus_cli.core import DockerRunner, OctopusManager, PromptIO
from app.octopus_cli.models import Action, RegistryConnection, RegistryDeployOptions, RegistryState


def test_compose_persists_postgres_data() -> None:
    compose = Path("infra/compose/docker-compose.yml").read_text(encoding="utf-8")

    assert "  postgres:\n" in compose
    assert "      - data:/var/lib/postgresql/data\n" in compose


class _ComposeDockerRunner:
    def __init__(self) -> None:
        self.commands: list[tuple[str, ...]] = []

    def ensure_network(self) -> None:
        return None

    def docker_status_for_slug(self, slug: str) -> str:
        del slug
        return "Up 1 second"

    def run(self, args, **kwargs):  # noqa: ANN001
        del kwargs
        from subprocess import CompletedProcess

        joined = " ".join(args)
        if "compose -p octopus-registry ps" in joined:
            return CompletedProcess(args, 0, "", "")
        return CompletedProcess(args, 0, "", "")

    def registry_compose(self, *args, **kwargs):  # noqa: ANN001
        del kwargs
        self.commands.append(("registry", *args))
        from subprocess import CompletedProcess

        return CompletedProcess(["docker"], 0, "", "")

    def bot_compose(self, slug, *args, **kwargs):  # noqa: ANN001
        del kwargs
        self.commands.append((slug, *args))
        from subprocess import CompletedProcess

        return CompletedProcess(["docker"], 0, "", "")

    def provider_compose(self, provider, *args, **kwargs):  # noqa: ANN001
        del kwargs
        self.commands.append((f"provider:{provider}", *args))
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


def _write_bot_env(tmp_path: Path, slug: str, display_name: str, extra_lines: list[str] | None = None) -> None:
    env_dir = tmp_path / ".deploy" / "bots" / slug
    env_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        f"BOT_DISPLAY_NAME={display_name}",
        f"BOT_TELEGRAM_USERNAME={slug}",
        "BOT_PROVIDER=codex",
        "BOT_AGENT_MODE=standalone",
    ]
    if extra_lines:
        lines.extend(extra_lines)
    (env_dir / ".env").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_compose_runtime_services_use_stack_specific_db_host() -> None:
    compose_path = Path(__file__).resolve().parents[1] / "infra" / "compose" / "docker-compose.yml"
    compose_text = compose_path.read_text(encoding="utf-8")

    expected = (
        "OCTOPUS_DATABASE_URL: "
        "${OCTOPUS_DATABASE_URL:-postgresql://bot:bot@${OCTOPUS_DB_HOST:-postgres}:5432/bot}"
    )

    assert compose_text.count(expected) >= 4
    assert (
        "OCTOPUS_DATABASE_URL: ${OCTOPUS_DATABASE_URL:-postgresql://bot:bot@postgres:5432/bot}"
        not in compose_text
    )


def test_registry_compose_command_uses_generated_workspace_override(tmp_path: Path) -> None:
    registry_dir = tmp_path / ".deploy" / "registry"
    registry_dir.mkdir(parents=True, exist_ok=True)
    (registry_dir / ".env").write_text("REGISTRY_UI_TOKEN=test\n", encoding="utf-8")
    (registry_dir / "docker-compose.workspace.yml").write_text("services:\n  service:\n", encoding="utf-8")

    runner = DockerRunner(tmp_path)

    command, env = runner.registry_compose_command("up", "-d", "service")

    assert command == [
        "docker",
        "compose",
        "--project-directory",
        ".",
        "-p",
        "octopus-registry",
        "-f",
        "infra/compose/docker-compose.yml",
        "--profile",
        "registry",
        "--env-file",
        ".deploy/registry/.env",
        "-f",
        ".deploy/registry/docker-compose.workspace.yml",
        "up",
        "-d",
        "service",
    ]
    assert env["OCTOPUS_DB_HOST"] == "registry-postgres"


def test_start_registry_regenerates_workspace_override_from_configured_workspaces(tmp_path: Path) -> None:
    registry_dir = tmp_path / ".deploy" / "registry"
    registry_dir.mkdir(parents=True, exist_ok=True)
    (registry_dir / ".env").write_text(
        "\n".join(
            [
                "REGISTRY_ENROLL_TOKEN=test-enroll",
                "REGISTRY_UI_TOKEN=test-ui",
                "REGISTRY_ALLOW_HTTP=1",
                "",
            ]
        ),
        encoding="utf-8",
    )
    workspace_root = tmp_path / "workspace-root"
    workspace_root.mkdir()
    manager = OctopusManager(tmp_path, docker=_ComposeDockerRunner())
    manager.ensure_registry_image_ready = lambda force=False: None  # type: ignore[method-assign]
    manager.create_workspace("workspace", str(workspace_root))

    manager.start_registry()

    override = (registry_dir / "docker-compose.workspace.yml").read_text(encoding="utf-8")
    assert "services:" in override
    assert "  service:" in override
    assert f"      - {workspace_root}:/workspace/workspace:rw" in override


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
    assert docker.commands == [
        ("example-bot", "run", "--rm", "db-init"),
        ("example-bot", "up", "-d", "bot"),
    ]


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


def test_read_bot_registry_state_uses_exec_against_running_bot(tmp_path: Path) -> None:
    _write_registry_bot_env(tmp_path, "m1", "M1")
    docker = _ComposeDockerRunner()
    manager = OctopusManager(tmp_path, docker=docker)

    def _bot_compose(slug, *args, **kwargs):  # noqa: ANN001
        del kwargs
        docker.commands.append((slug, *args))
        from subprocess import CompletedProcess

        return CompletedProcess(["docker"], 0, '{"connectivity_state":"connected","agent_id":"a1","agent_token":"t1"}', "")

    docker.bot_compose = _bot_compose  # type: ignore[method-assign]

    state = manager.read_bot_registry_state("m1", "local")

    assert state == {"connectivity_state": "connected", "agent_id": "a1", "agent_token": "t1"}
    assert docker.commands == [
        (
            "m1",
            "exec",
            "-T",
            "-e",
            "OCTOPUS_REGISTRY_ID=local",
            "bot",
            "python",
            "-c",
            docker.commands[0][-1],
        )
    ]


def test_read_bot_execution_state_uses_exec_against_running_bot(tmp_path: Path) -> None:
    _write_registry_bot_env(tmp_path, "m1", "M1")
    docker = _ComposeDockerRunner()
    manager = OctopusManager(tmp_path, docker=docker)

    def _bot_compose(slug, *args, **kwargs):  # noqa: ANN001
        del kwargs
        docker.commands.append((slug, *args))
        from subprocess import CompletedProcess

        return CompletedProcess(
            ["docker"],
            0,
            json.dumps(
                {
                    "state": "faulted",
                    "provider": "claude",
                    "fault_kind": "provider_auth",
                    "fault_code": "authentication_required",
                    "detail": "Not logged in · Please run /login",
                    "faulted_at": "2026-04-01T01:02:03+00:00",
                    "resettable": True,
                    "last_returncode": 1,
                }
            ),
            "",
        )

    docker.bot_compose = _bot_compose  # type: ignore[method-assign]

    state = manager.read_bot_execution_state("m1")

    assert state["state"] == "faulted"
    assert state["provider"] == "claude"
    assert state["detail"] == "Not logged in · Please run /login"
    script = docker.commands[0][-1]
    assert "from pathlib import Path" in script
    assert "agent' / 'execution-state.json'" in script


def test_registry_deploy_defaults_public_url_for_ip_bind(tmp_path: Path) -> None:
    manager = OctopusManager(tmp_path, docker=_ComposeDockerRunner())

    values = manager._validated_registry_deploy_values(
        RegistryDeployOptions(bind_host="192.168.1.20", port=9000),
        existing=None,
        creating=True,
    )

    assert values["REGISTRY_BIND_HOST"] == "192.168.1.20"
    assert values["REGISTRY_PORT"] == "9000"
    assert values["REGISTRY_PUBLIC_URL"] == "http://192.168.1.20:9000"


def test_registry_deploy_rejects_0_0_0_0_without_public_url(tmp_path: Path) -> None:
    manager = OctopusManager(tmp_path, docker=_ComposeDockerRunner())

    with pytest.raises(octopus_core.OctopusError, match="public registry URL is required"):
        manager._validated_registry_deploy_values(
            RegistryDeployOptions(bind_host="0.0.0.0"),
            existing=None,
            creating=True,
        )


def test_registry_deploy_rejects_hostname_bind_host(tmp_path: Path) -> None:
    manager = OctopusManager(tmp_path, docker=_ComposeDockerRunner())

    with pytest.raises(octopus_core.OctopusError, match="bind host must be localhost, 0.0.0.0, or a concrete IP address"):
        manager._validated_registry_deploy_values(
            RegistryDeployOptions(bind_host="registry.example.internal"),
            existing=None,
            creating=True,
        )


def test_inspect_state_reports_registry_bind_and_public_urls(tmp_path: Path) -> None:
    registry_dir = tmp_path / ".deploy" / "registry"
    registry_dir.mkdir(parents=True, exist_ok=True)
    (registry_dir / ".env").write_text(
        "\n".join(
            [
                "REGISTRY_BIND_HOST=0.0.0.0",
                "REGISTRY_PORT=9000",
                "REGISTRY_PUBLIC_URL=http://mybox.local:9000",
                "REGISTRY_ENROLL_TOKEN=enroll",
                "REGISTRY_UI_TOKEN=ui",
                "",
            ]
        ),
        encoding="utf-8",
    )

    class _RunningRegistryDocker(_ComposeDockerRunner):
        def run(self, args, **kwargs):  # noqa: ANN001
            del kwargs
            from subprocess import CompletedProcess

            joined = " ".join(args)
            if "compose -p octopus-registry ps" in joined:
                return CompletedProcess(args, 0, "service\n", "")
            return CompletedProcess(args, 0, "", "")

    manager = OctopusManager(tmp_path, docker=_RunningRegistryDocker())

    state = manager.inspect_state().registry

    assert state.running is True
    assert state.bind_host == "0.0.0.0"
    assert state.port == 9000
    assert state.host_base_url == "http://127.0.0.1:9000"
    assert state.public_url == "http://mybox.local:9000"
    assert state.ui_url == "http://mybox.local:9000/ui"


def test_registry_identity_valid_uses_host_base_url_for_local_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    registry_dir = tmp_path / ".deploy" / "registry"
    registry_dir.mkdir(parents=True, exist_ok=True)
    (registry_dir / ".env").write_text(
        "\n".join(
            [
                "REGISTRY_BIND_HOST=0.0.0.0",
                "REGISTRY_PORT=8787",
                "REGISTRY_PUBLIC_URL=http://mybox.local:8787",
                "",
            ]
        ),
        encoding="utf-8",
    )
    manager = OctopusManager(tmp_path, docker=_ComposeDockerRunner())
    seen: dict[str, str] = {}

    class _Response:
        status = 200

        def __enter__(self):  # noqa: ANN204
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ANN001, ANN204
            del exc_type, exc, tb
            return False

        def read(self) -> bytes:
            return json.dumps({"agent_id": "agent-1"}).encode("utf-8")

    def _fake_urlopen(request, timeout=10):  # noqa: ANN001
        del timeout
        seen["url"] = request.full_url
        return _Response()

    monkeypatch.setattr(octopus_core.urllib.request, "urlopen", _fake_urlopen)

    valid = manager.registry_identity_valid(
        RegistryConnection(registry_id="local", url="http://registry:8787", enrollment_token="secret"),
        {"agent_id": "agent-1", "agent_token": "token-1"},
    )

    assert valid is True
    assert seen["url"] == "http://127.0.0.1:8787/v1/agents/agent-1/status"


def test_connect_bot_to_remote_registry_writes_registry_record(tmp_path: Path) -> None:
    _write_bot_env(tmp_path, "m1", "M1")
    manager = OctopusManager(tmp_path, docker=_ComposeDockerRunner())
    restarted: list[str] = []
    verified: list[tuple[str, str]] = []

    manager.restart_bot = lambda slug, force_rebuild=False: restarted.append(slug)  # type: ignore[method-assign]
    manager.verify_registry_enrollment = lambda slug, registry_id: verified.append((slug, registry_id))  # type: ignore[method-assign]

    connection = manager.connect_bot_to_registry(
        "m1",
        registry_url="http://registry.example.internal:9000",
        enrollment_token="remote-secret",
        desired_scope="observe",
    )

    values = manager.bot_values("m1")
    assert values["BOT_AGENT_MODE"] == "registry"
    assert values["BOT_AGENT_REGISTRY_1_URL"] == "http://registry.example.internal:9000"
    assert values["BOT_AGENT_REGISTRY_1_ENROLL_TOKEN"] == "remote-secret"
    assert values["BOT_AGENT_REGISTRY_1_SCOPE"] == "observe"
    assert "BOT_REGISTRY_PUBLIC_URL" not in values
    assert connection.registry_id == "registry-example-internal-9000"
    assert restarted == ["m1"]
    assert verified == [("m1", "registry-example-internal-9000")]


def test_prepare_bot_for_local_registry_writes_registry_record_without_restart(tmp_path: Path) -> None:
    _write_bot_env(tmp_path, "m1", "M1")
    manager = OctopusManager(tmp_path, docker=_ComposeDockerRunner())
    cleared: list[list[str] | None] = []

    manager.ensure_local_registry = lambda force_rebuild=False, deploy=None: RegistryState(  # type: ignore[method-assign]
        configured=True,
        running=True,
        env_file=tmp_path / ".deploy" / "registry" / ".env",
        enroll_token="local-secret",
        ui_token="ui-secret",
    )
    manager.read_bot_registry_state = lambda slug, registry_id: {}  # type: ignore[method-assign]
    manager.clear_bot_registry_state = lambda slug, registry_ids=None: cleared.append(registry_ids)  # type: ignore[method-assign]

    connection = manager.prepare_bot_for_local_registry("m1")

    values = manager.bot_values("m1")
    assert values["BOT_AGENT_MODE"] == "registry"
    assert values["BOT_AGENT_REGISTRY_1_ID"] == "local"
    assert values["BOT_AGENT_REGISTRY_1_URL"] == "http://registry:8787"
    assert values["BOT_AGENT_REGISTRY_1_ENROLL_TOKEN"] == "local-secret"
    assert values["BOT_AGENT_REGISTRY_1_SCOPE"] == "full"
    assert values["BOT_REGISTRY_PUBLIC_URL"] == "http://127.0.0.1:8787"
    assert connection.registry_id == "local"
    assert cleared == []


def test_add_bot_interactive_prepares_local_registry_before_start(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stdout = _FakeOutput()
    io = PromptIO(
        stdin=_FakeInput(
            [
                "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZ123456789\n",
                "\n",
                "2\n",
            ]
        ),
        stdout=stdout,
        stderr=stdout,
    )
    manager = OctopusManager(tmp_path, io=io, docker=_ComposeDockerRunner())
    started: list[str] = []
    verified: list[tuple[str, str]] = []

    monkeypatch.setattr(
        octopus_core,
        "validate_telegram_token",
        lambda token: ("123456", "example_bot", "Example Bot"),
    )
    manager.ensure_provider_image_ready = lambda provider, force=False: None  # type: ignore[method-assign]
    manager.ensure_provider_auth_ready = lambda provider: None  # type: ignore[method-assign]
    manager.ensure_local_registry = lambda force_rebuild=False, deploy=None: RegistryState(  # type: ignore[method-assign]
        configured=True,
        running=True,
        env_file=tmp_path / ".deploy" / "registry" / ".env",
        enroll_token="local-secret",
        ui_token="ui-secret",
    )
    manager.read_bot_registry_state = lambda slug, registry_id: {}  # type: ignore[method-assign]
    manager.clear_bot_registry_state = lambda slug, registry_ids=None: None  # type: ignore[method-assign]
    manager.run_bot_doctor = lambda slug, live_provider=False: "All checks passed."  # type: ignore[method-assign]
    manager.start_bot = lambda slug, force_rebuild=False, force_recreate=False: started.append(slug)  # type: ignore[method-assign]
    manager.verify_registry_enrollment = lambda slug, registry_id: verified.append((slug, registry_id))  # type: ignore[method-assign]

    manager.add_bot_interactive()

    values = manager.bot_values("example-bot")
    assert values["BOT_AGENT_MODE"] == "registry"
    assert values["BOT_AGENT_REGISTRY_1_ID"] == "local"
    assert values["BOT_AGENT_REGISTRY_1_URL"] == "http://registry:8787"
    assert values["BOT_AGENT_REGISTRY_1_ENROLL_TOKEN"] == "local-secret"
    assert values["BOT_REGISTRY_PUBLIC_URL"] == "http://127.0.0.1:8787"
    assert started == ["example-bot"]
    assert verified == [("example-bot", "local")]


def test_ensure_provider_auth_ready_uses_live_health_for_existing_auth(tmp_path: Path) -> None:
    auth_dir = tmp_path / ".deploy" / "provider-auth" / "claude"
    auth_dir.mkdir(parents=True, exist_ok=True)
    (auth_dir / ".claude.json").write_text('{"token":"secret"}', encoding="utf-8")
    manager = OctopusManager(tmp_path, docker=_ComposeDockerRunner())
    manager.ensure_provider_image_ready = lambda provider, force=False: None  # type: ignore[method-assign]
    manager.provider_live_health_output = lambda provider: (True, "ok")  # type: ignore[method-assign]

    manager.ensure_provider_auth_ready("claude")

    assert manager.docker.commands == []


def test_ensure_provider_auth_ready_retries_login_when_existing_auth_is_invalid(tmp_path: Path) -> None:
    auth_dir = tmp_path / ".deploy" / "provider-auth" / "claude"
    auth_dir.mkdir(parents=True, exist_ok=True)
    (auth_dir / ".claude.json").write_text('{"token":"secret"}', encoding="utf-8")
    docker = _ComposeDockerRunner()
    manager = OctopusManager(tmp_path, docker=docker)
    manager.ensure_provider_image_ready = lambda provider, force=False: None  # type: ignore[method-assign]
    health_results = iter([(False, "not logged in"), (True, "ok")])
    manager.provider_live_health_output = lambda provider: next(health_results)  # type: ignore[method-assign]

    manager.ensure_provider_auth_ready("claude")

    assert docker.commands == [
        (
            "provider:claude",
            "run",
            "--rm",
            "bot-provider",
            "sh",
            "/app/scripts/provider/container_provider_login.sh",
        )
    ]


def test_provider_auth_state_reports_live_failure_for_configured_auth(tmp_path: Path) -> None:
    auth_dir = tmp_path / ".deploy" / "provider-auth" / "claude"
    auth_dir.mkdir(parents=True, exist_ok=True)
    (auth_dir / ".claude.json").write_text('{"token":"secret"}', encoding="utf-8")
    manager = OctopusManager(tmp_path, docker=_ComposeDockerRunner())
    manager.provider_live_health_output = lambda provider, build_if_stale=False: (False, "Not logged in · Please run /login")  # type: ignore[method-assign]

    state = manager.provider_auth_state("claude", live=True)

    assert state.configured is True
    assert state.live_checked is True
    assert state.healthy is False
    assert state.status_label == "configured, unable to authenticate"
    assert "Not logged in" in state.detail


def test_disconnect_bot_registry_by_id_removes_only_target_record(tmp_path: Path) -> None:
    _write_bot_env(
        tmp_path,
        "m1",
        "M1",
        [
            "BOT_AGENT_MODE=registry",
            "BOT_AGENT_REGISTRY_1_ID=local",
            "BOT_AGENT_REGISTRY_1_URL=http://registry:8787",
            "BOT_AGENT_REGISTRY_1_ENROLL_TOKEN=local-token",
            "BOT_AGENT_REGISTRY_1_SCOPE=full",
            "BOT_AGENT_REGISTRY_2_ID=qa",
            "BOT_AGENT_REGISTRY_2_URL=http://qa.example.internal:8787",
            "BOT_AGENT_REGISTRY_2_ENROLL_TOKEN=qa-token",
            "BOT_AGENT_REGISTRY_2_SCOPE=observe",
        ],
    )
    manager = OctopusManager(tmp_path, docker=_ComposeDockerRunner())
    cleared: list[list[str] | None] = []
    restarted: list[str] = []

    manager.clear_bot_registry_state = lambda slug, registry_ids=None: cleared.append(registry_ids)  # type: ignore[method-assign]
    manager.restart_bot = lambda slug, force_rebuild=False: restarted.append(slug)  # type: ignore[method-assign]

    connection = manager.disconnect_bot_registry("m1", registry_id="qa")

    values = manager.bot_values("m1")
    assert connection.registry_id == "qa"
    assert values["BOT_AGENT_MODE"] == "registry"
    assert values["BOT_AGENT_REGISTRY_1_ID"] == "local"
    assert "BOT_AGENT_REGISTRY_2_ID" not in values
    assert cleared == [["qa"]]
    assert restarted == ["m1"]
