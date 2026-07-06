from __future__ import annotations

import io
from pathlib import Path

from app.octopus_cli.admin_service import OctopusAdminService
from app.octopus_cli.cli import OctopusCLI
from app.octopus_cli.core import PromptIO
from app.octopus_cli.models import (
    Action,
    BotState,
    ExecutionPlan,
    ImageFreshness,
    ProviderAuthState,
    RegistryConnectionStatus,
    RegistryState,
    ResolvedTarget,
    SystemState,
    TargetKind,
)


def _bot(
    slug: str,
    *,
    registry_connection_statuses: list[RegistryConnectionStatus] | None = None,
    execution_state: str = "healthy",
    execution_fault_detail: str = "",
) -> BotState:
    return BotState(
        slug=slug,
        display_name=slug.upper(),
        telegram_username=slug,
        telegram_id="1",
        provider="codex",
        mode="registry",
        env_file=Path("/tmp") / slug / ".env",
        running=True,
        registry_connection_statuses=registry_connection_statuses or [],
        execution_state=execution_state,
        execution_fault_detail=execution_fault_detail,
    )


def _state(*bots: BotState) -> SystemState:
    return SystemState(
        repo_dir=Path("/tmp/repo"),
        bots=list(bots),
        registry=RegistryState(configured=True, running=True, env_file=Path("/tmp/repo/.deploy/registry/.env")),
        workspaces=[],
        provider_auth=[],
        freshness={"registry": ImageFreshness(image="octopus-registry-service:latest", fingerprint="a", image_exists=True, image_fingerprint="a")},
    )


def test_cli_start_registry_passes_deploy_options(tmp_path: Path) -> None:
    cli = OctopusCLI(tmp_path)
    cli.manager.inspect_state = lambda: _state()  # type: ignore[method-assign]
    cli.manager.resolve_targets = lambda selectors, action, state: [ResolvedTarget(TargetKind.REGISTRY, "registry", "registry")]  # type: ignore[method-assign]
    cli.manager.plan_action = lambda action, targets, state: ExecutionPlan(action=action, targets=targets)  # type: ignore[method-assign]
    cli.manager.confirm_plan = lambda plan, yes: None  # type: ignore[method-assign]
    seen: dict[str, object] = {}

    def _start_registry(*, force_rebuild=False, force_recreate=False, deploy=None):  # noqa: ANN001
        seen["force_rebuild"] = force_rebuild
        seen["force_recreate"] = force_recreate
        seen["deploy"] = deploy

    cli.manager.start_registry = _start_registry  # type: ignore[method-assign]

    result = cli.run(
        [
            "start",
            "registry",
            "--registry-bind-host",
            "0.0.0.0",
            "--registry-public-url",
            "http://mybox.local:8787",
            "--yes",
        ]
    )

    assert result == 0
    deploy = seen["deploy"]
    assert deploy.bind_host == "0.0.0.0"
    assert deploy.public_url == "http://mybox.local:8787"
    assert deploy.port is None


def test_cli_mutating_commands_delegate_to_admin_service(tmp_path: Path) -> None:
    cli = OctopusCLI(tmp_path)
    calls: list[tuple[Action, list[str], bool]] = []

    def _run_mutating(action, selectors, *, yes, deploy=None, connect=None, disconnect_registry_id=""):  # noqa: ANN001
        del deploy, connect, disconnect_registry_id
        calls.append((action, selectors, yes))
        return 0

    cli.admin.run_mutating = _run_mutating  # type: ignore[method-assign]

    result = cli.run(["restart", "m1", "--yes"])

    assert result == 0
    assert calls == [(Action.RESTART, ["m1"], True)]


def test_admin_service_redeploy_uses_existing_manager_operations(tmp_path: Path) -> None:
    cli = OctopusCLI(tmp_path)
    service = OctopusAdminService(cli.manager, io=cli.io)
    calls: list[tuple[str, str, bool]] = []

    cli.manager.has_local_registry = lambda: True  # type: ignore[method-assign]
    cli.manager.stop_registry = lambda: calls.append(("registry", "stop", False))  # type: ignore[method-assign]
    cli.manager.start_registry = (  # type: ignore[method-assign]
        lambda *, force_rebuild=False, force_recreate=False, deploy=None:
        calls.append(("registry", "start", bool(force_rebuild and force_recreate)))
    )
    cli.manager.restart_bot = lambda slug, *, force_rebuild=False: calls.append((slug, "restart", force_rebuild))  # type: ignore[method-assign]

    result = service.redeploy([
        ResolvedTarget(TargetKind.REGISTRY, "registry", "registry"),
        ResolvedTarget(TargetKind.BOT, "m1", "M1"),
    ])

    assert result == 0
    assert calls == [
        ("registry", "stop", False),
        ("registry", "start", True),
        ("m1", "restart", True),
    ]


def test_cli_connect_remote_without_targets_uses_all_bots(tmp_path: Path) -> None:
    cli = OctopusCLI(tmp_path)
    cli.manager.inspect_state = lambda: _state(_bot("m1"), _bot("m2"))  # type: ignore[method-assign]
    cli.manager.plan_action = lambda action, targets, state: ExecutionPlan(action=action, targets=targets)  # type: ignore[method-assign]
    cli.manager.confirm_plan = lambda plan, yes: None  # type: ignore[method-assign]
    calls: list[tuple[str, str, str, str, str]] = []

    def _connect_bot_to_registry(slug: str, *, registry_url: str, enrollment_token: str, desired_scope: str, registry_id: str):  # noqa: ANN001
        calls.append((slug, registry_url, enrollment_token, desired_scope, registry_id))
        return type("Conn", (), {"registry_id": registry_id, "url": registry_url})()

    cli.manager.connect_bot_to_registry = _connect_bot_to_registry  # type: ignore[method-assign]

    result = cli.run(
        [
            "connect",
            "--registry-url",
            "http://remote.example.internal:8787",
            "--registry-enroll-token",
            "secret",
            "--registry-id",
            "qa",
            "--registry-scope",
            "observe",
            "--yes",
        ]
    )

    assert result == 0
    assert calls == [
        ("m1", "http://remote.example.internal:8787", "secret", "observe", "qa"),
        ("m2", "http://remote.example.internal:8787", "secret", "observe", "qa"),
    ]


def test_cli_disconnect_registry_id_without_targets_uses_matching_bots(tmp_path: Path) -> None:
    cli = OctopusCLI(tmp_path)
    cli.manager.inspect_state = lambda: _state(  # type: ignore[method-assign]
        _bot("m1", registry_connection_statuses=[RegistryConnectionStatus(registry_id="qa", url="http://qa.example", scope="full")]),
        _bot("m2", registry_connection_statuses=[RegistryConnectionStatus(registry_id="local", url="http://registry:8787", scope="full", local=True)]),
    )
    cli.manager.plan_action = lambda action, targets, state: ExecutionPlan(action=action, targets=targets)  # type: ignore[method-assign]
    cli.manager.confirm_plan = lambda plan, yes: None  # type: ignore[method-assign]
    disconnected: list[tuple[str, str]] = []

    def _disconnect(slug: str, *, registry_id: str = ""):  # noqa: ANN001
        disconnected.append((slug, registry_id))
        return type("Conn", (), {"url": "http://qa.example", "registry_id": registry_id})()

    cli.manager.disconnect_bot_registry = _disconnect  # type: ignore[method-assign]

    result = cli.run(["disconnect", "--registry-id", "qa", "--yes"])

    assert result == 0
    assert disconnected == [("m1", "qa")]


def test_interactive_diagnose_logs_passes_follow_flag(tmp_path: Path) -> None:
    cli = OctopusCLI(tmp_path, io=PromptIO(stdin=io.StringIO("1\n1\n"), stdout=io.StringIO()))
    cli.manager.inspect_state = lambda: _state(_bot("m1"))  # type: ignore[method-assign]
    calls: list[tuple[list[str], bool]] = []

    def _logs(targets: list[str], *, follow: bool) -> int:
        calls.append((targets, follow))
        return 0

    cli.cmd_logs = _logs  # type: ignore[method-assign]

    result = cli.menu_diagnose()

    assert result == 0
    assert calls == [(["registry"], True)]


def test_render_provider_auth_status_shows_live_failure_detail(tmp_path: Path) -> None:
    class _Output:
        def __init__(self) -> None:
            self.parts: list[str] = []

        def write(self, value: str) -> None:
            self.parts.append(value)

        def flush(self) -> None:
            return None

        def isatty(self) -> bool:
            return False

    output = _Output()
    cli = OctopusCLI(tmp_path, io=PromptIO(stdout=output))
    state = _state()
    state.provider_auth = [
        ProviderAuthState(
            provider="claude",
            configured=True,
            live_checked=True,
            healthy=False,
            detail="Claude auth probe failed (rc=1): Not logged in · Please run /login",
        )
    ]

    cli.render_provider_auth_status(state)

    assert output.parts == [
        "Provider auth:\n",
        "  claude     configured, unable to authenticate\n",
        "      detail: Claude auth probe failed (rc=1): Not logged in · Please run /login\n",
    ]


def test_status_is_static_by_default(tmp_path: Path) -> None:
    cli = OctopusCLI(tmp_path)
    state = _state(_bot("m1"))
    state.provider_auth = [ProviderAuthState(provider="claude", configured=True)]
    cli.manager.inspect_state = lambda: state  # type: ignore[method-assign]
    called: list[tuple[tuple[str, ...], bool]] = []

    def _provider_auth_states(providers, *, live=False):  # noqa: ANN001
        called.append((tuple(providers), live))
        return state.provider_auth

    cli.manager.provider_auth_states = _provider_auth_states  # type: ignore[method-assign]

    result = cli.run(["status"])

    assert result == 0
    assert called == []


def test_status_live_provider_opt_in(tmp_path: Path) -> None:
    cli = OctopusCLI(tmp_path)
    state = _state(_bot("m1"))
    state.provider_auth = [ProviderAuthState(provider="claude", configured=True)]
    cli.manager.inspect_state = lambda: state  # type: ignore[method-assign]
    called: list[tuple[tuple[str, ...], bool]] = []

    def _provider_auth_states(providers, *, live=False):  # noqa: ANN001
        called.append((tuple(providers), live))
        return [
            ProviderAuthState(
                provider="claude",
                configured=True,
                live_checked=True,
                healthy=False,
                detail="Not logged in",
            )
        ]

    cli.manager.provider_auth_states = _provider_auth_states  # type: ignore[method-assign]

    result = cli.run(["status", "--live-provider"])

    assert result == 0
    assert called == [(("claude",), True)]


def test_render_registry_status_surfaces_execution_faults_without_hiding_transport_connected(tmp_path: Path) -> None:
    class _Output:
        def __init__(self) -> None:
            self.parts: list[str] = []

        def write(self, value: str) -> None:
            self.parts.append(value)

        def flush(self) -> None:
            return None

        def isatty(self) -> bool:
            return False

    output = _Output()
    cli = OctopusCLI(tmp_path, io=PromptIO(stdout=output))
    state = _state(
        _bot(
            "m1",
            registry_connection_statuses=[
                RegistryConnectionStatus(
                    registry_id="local",
                    url="http://registry:8787",
                    scope="full",
                    connection_state="enrolled",
                    live_state="connected",
                    local=True,
                )
            ],
            execution_state="faulted",
            execution_fault_detail="Not logged in · Please run /login",
        )
    )

    cli.render_registry_status(state)

    rendered = "".join(output.parts)
    assert "Connected bots:" in rendered
    assert "state: connected" in rendered
    assert "execution: faulted" in rendered
    assert "Execution faults:" in rendered
    assert "Not logged in · Please run /login" in rendered


def test_recommended_actions_include_authenticate_for_invalid_live_auth(tmp_path: Path) -> None:
    cli = OctopusCLI(tmp_path)
    state = _state(_bot("m1"))
    state.provider_auth = [
        ProviderAuthState(provider="claude", configured=True, live_checked=True, healthy=False, detail="not logged in")
    ]

    actions = cli.recommended_actions(state)

    assert [label for label, _ in actions] == ["Authenticate claude"]
