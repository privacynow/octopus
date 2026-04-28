from __future__ import annotations

from app.octopus_cli.core import LOCAL_REGISTRY_INTERNAL_URL, OctopusError, OctopusManager, PromptIO
from app.octopus_cli.models import (
    Action,
    RegistryConnectOptions,
    RegistryDeployOptions,
    ResolvedTarget,
    SystemState,
    TargetKind,
)


class OctopusAdminService:
    """Shared admin service used by CLI surfaces over the Octopus manager implementation."""

    def __init__(self, manager: OctopusManager, *, io: PromptIO | None = None) -> None:
        self.manager = manager
        self.io = io or manager.io

    def state(self, *, live_provider_auth: bool = False) -> SystemState:
        state = self.manager.inspect_state()
        if live_provider_auth:
            providers = [provider.provider for provider in state.provider_auth]
            state.provider_auth = self.manager.provider_auth_states(providers, live=True)
        return state

    def run_mutating(
        self,
        action: Action,
        selectors: list[str],
        *,
        yes: bool,
        deploy: RegistryDeployOptions | None = None,
        connect: RegistryConnectOptions | None = None,
        disconnect_registry_id: str = "",
    ) -> int:
        deploy = deploy or RegistryDeployOptions()
        connect = connect or RegistryConnectOptions()
        self._validate_options(action, deploy=deploy, connect=connect, disconnect_registry_id=disconnect_registry_id)
        state = self.manager.inspect_state()
        targets = self._resolve_mutation_targets(
            action,
            selectors,
            state,
            connect=connect,
            disconnect_registry_id=disconnect_registry_id,
        )
        if action in {Action.CONNECT, Action.DISCONNECT} and any(target.kind == TargetKind.REGISTRY for target in targets):
            raise OctopusError(f"{action.value.title()} only applies to bots.")
        if not targets:
            self.io.print("Nothing to do.")
            return 0
        plan = self.manager.plan_action(action, targets, state)
        if action == Action.CONNECT:
            if connect.is_remote:
                plan.notes = [f"Bots will be connected to remote registry {connect.registry_url}."]
            else:
                plan.notes = ["Bots will be connected to the local registry."]
        elif action == Action.DISCONNECT:
            if disconnect_registry_id:
                plan.notes = [
                    f"Only registry connection '{disconnect_registry_id}' will be removed; bot data will be preserved."
                ]
            else:
                plan.notes = ["Only the local registry connection will be removed; bot data will be preserved."]
        self.manager.confirm_plan(plan, yes=yes)
        return self.execute(action, targets, deploy=deploy, connect=connect, disconnect_registry_id=disconnect_registry_id)

    def execute(
        self,
        action: Action,
        targets: list[ResolvedTarget],
        *,
        deploy: RegistryDeployOptions | None = None,
        connect: RegistryConnectOptions | None = None,
        disconnect_registry_id: str = "",
    ) -> int:
        if action == Action.START:
            return self.start(targets, deploy=deploy)
        if action == Action.STOP:
            return self.stop(targets)
        if action == Action.RESTART:
            return self.restart(targets, deploy=deploy)
        if action == Action.REDEPLOY:
            return self.redeploy(targets, deploy=deploy)
        if action == Action.CONNECT:
            return self.connect(targets, connect=connect)
        if action == Action.DISCONNECT:
            return self.disconnect(targets, registry_id=disconnect_registry_id)
        raise OctopusError(f"Unsupported action: {action.value}")

    def start(self, targets: list[ResolvedTarget], *, deploy: RegistryDeployOptions | None = None) -> int:
        for target in targets:
            if target.kind == TargetKind.REGISTRY:
                self.manager.start_registry(deploy=deploy)
            else:
                self.manager.start_bot(target.identifier)
        return 0

    def stop(self, targets: list[ResolvedTarget]) -> int:
        for target in targets:
            if target.kind == TargetKind.REGISTRY:
                self.manager.stop_registry()
            else:
                self.manager.stop_bot(target.identifier)
        return 0

    def restart(self, targets: list[ResolvedTarget], *, deploy: RegistryDeployOptions | None = None) -> int:
        for target in targets:
            if target.kind == TargetKind.REGISTRY:
                if self.manager.has_local_registry():
                    self.manager.stop_registry()
                self.manager.start_registry(deploy=deploy)
            else:
                self.manager.restart_bot(target.identifier)
        return 0

    def redeploy(self, targets: list[ResolvedTarget], *, deploy: RegistryDeployOptions | None = None) -> int:
        for target in targets:
            if target.kind == TargetKind.REGISTRY:
                if self.manager.has_local_registry():
                    self.manager.stop_registry()
                self.manager.start_registry(force_rebuild=True, force_recreate=True, deploy=deploy)
            else:
                self.manager.restart_bot(target.identifier, force_rebuild=True)
        return 0

    def connect(self, targets: list[ResolvedTarget], *, connect: RegistryConnectOptions | None = None) -> int:
        connect = connect or RegistryConnectOptions()
        for target in targets:
            if connect.is_remote:
                connection = self.manager.connect_bot_to_registry(
                    target.identifier,
                    registry_url=connect.registry_url,
                    enrollment_token=connect.enrollment_token,
                    desired_scope=connect.scope or "full",
                    registry_id=connect.registry_id,
                )
                self.io.print(f"Connected {target.label} to remote registry {connection.registry_id} ({connection.url}).")
            else:
                self.manager.connect_bot_to_local_registry(target.identifier, desired_scope=connect.scope or "full")
                self.io.print(f"Connected {target.label} to the local registry.")
        return 0

    def disconnect(self, targets: list[ResolvedTarget], *, registry_id: str = "") -> int:
        for target in targets:
            connection = self.manager.disconnect_bot_registry(target.identifier, registry_id=registry_id)
            label = "local registry" if connection.url == LOCAL_REGISTRY_INTERNAL_URL else f"registry {connection.registry_id}"
            self.io.print(f"Disconnected {target.label} from {label}.")
        return 0

    def logs(self, targets: list[str], *, follow: bool) -> int:
        state = self.manager.inspect_state()
        resolved = self.manager.resolve_targets(targets, Action.LOGS, state)
        if len(resolved) != 1:
            raise OctopusError("logs requires exactly one target.")
        return self.manager.follow_logs(resolved[0], follow=follow)

    def shell(self, targets: list[str]) -> int:
        state = self.manager.inspect_state()
        resolved = self.manager.resolve_targets(targets, Action.SHELL, state)
        if len(resolved) != 1:
            raise OctopusError("shell requires exactly one target.")
        return self.manager.open_shell(resolved[0])

    def doctor(self, targets: list[str], *, live_provider: bool) -> int:
        state = self.manager.inspect_state()
        resolved = self.manager.resolve_targets(targets, Action.DOCTOR, state)
        if len(resolved) != 1 or resolved[0].kind != TargetKind.BOT:
            raise OctopusError("doctor requires exactly one bot target.")
        output = self.manager.run_bot_doctor(resolved[0].identifier, live_provider=live_provider)
        self.io.print(output.rstrip())
        return 0

    def _validate_options(
        self,
        action: Action,
        *,
        deploy: RegistryDeployOptions,
        connect: RegistryConnectOptions,
        disconnect_registry_id: str,
    ) -> None:
        if action not in {Action.START, Action.RESTART, Action.REDEPLOY} and not deploy.is_empty:
            raise OctopusError("Registry bind/public URL options are only valid with start, restart, or redeploy.")
        if action not in {Action.CONNECT, Action.DISCONNECT}:
            if connect.is_remote or disconnect_registry_id:
                raise OctopusError("Registry connection options are only valid with connect or disconnect.")
        if action != Action.CONNECT and connect.is_remote:
            raise OctopusError("--registry-url and --registry-enroll-token are only valid with connect.")

    def _resolve_mutation_targets(
        self,
        action: Action,
        selectors: list[str],
        state: SystemState,
        *,
        connect: RegistryConnectOptions,
        disconnect_registry_id: str,
    ) -> list[ResolvedTarget]:
        if action == Action.CONNECT and connect.is_remote and not selectors:
            return [ResolvedTarget(TargetKind.BOT, bot.slug, bot.label) for bot in state.bots]
        if action == Action.DISCONNECT and disconnect_registry_id and not selectors:
            return [
                ResolvedTarget(TargetKind.BOT, bot.slug, bot.label)
                for bot in state.bots
                if any(connection.registry_id == disconnect_registry_id for connection in bot.registry_connection_statuses)
            ]
        return self.manager.resolve_targets(selectors, action, state)
