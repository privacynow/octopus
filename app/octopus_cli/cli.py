from __future__ import annotations

import argparse
import os
import sys
import webbrowser
from pathlib import Path

from app.octopus_cli.core import LOCAL_REGISTRY_INTERNAL_URL, OctopusError, OctopusManager, PromptIO
from app.octopus_cli.models import (
    Action,
    BotState,
    RegistryConnectOptions,
    RegistryDeployOptions,
    ResolvedTarget,
    SystemState,
    TargetKind,
)


class OctopusCLI:
    def __init__(self, repo_dir: Path, *, io: PromptIO | None = None) -> None:
        self.io = io or PromptIO()
        self.manager = OctopusManager(repo_dir, io=self.io)

    def _state(self, *, live_provider_auth: bool = False) -> SystemState:
        state = self.manager.inspect_state()
        if live_provider_auth:
            providers = [provider.provider for provider in state.provider_auth]
            state.provider_auth = self.manager.provider_auth_states(providers, live=True)
        return state

    def build_parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(prog="./octopus", add_help=False)
        parser.add_argument("command", nargs="?", default="")
        parser.add_argument("targets", nargs="*")
        parser.add_argument("--yes", action="store_true")
        parser.add_argument("--follow", action="store_true")
        parser.add_argument("--live-provider", action="store_true")
        parser.add_argument("--registry-bind-host")
        parser.add_argument("--registry-port", type=int)
        parser.add_argument("--registry-public-url")
        parser.add_argument("--registry-url")
        parser.add_argument("--registry-enroll-token")
        parser.add_argument("--registry-id")
        parser.add_argument("--registry-scope")
        parser.add_argument("--help", "-h", action="store_true")
        return parser

    def _registry_deploy_options(self, args: argparse.Namespace) -> RegistryDeployOptions:
        return RegistryDeployOptions(
            bind_host=args.registry_bind_host or "",
            port=args.registry_port,
            public_url=args.registry_public_url or "",
        )

    def _registry_connect_options(self, args: argparse.Namespace) -> RegistryConnectOptions:
        if args.registry_enroll_token and not args.registry_url:
            raise OctopusError("--registry-enroll-token requires --registry-url.")
        return RegistryConnectOptions(
            registry_url=args.registry_url or "",
            enrollment_token=args.registry_enroll_token or "",
            registry_id=args.registry_id or "",
            scope=args.registry_scope or "full",
        )

    def run(self, argv: list[str] | None = None) -> int:
        args = self.build_parser().parse_args(argv)
        if args.help:
            self.print_help()
            return 0
        command = (args.command or "").strip().lower()
        try:
            if not command:
                return self.interactive_menu()
            if command == "help":
                self.print_help()
                return 0
            if command == "clean":
                self.manager.clean_all()
                return 0
            if command == "status":
                return self.cmd_status(args.targets)
            if command in {"start", "stop", "restart", "redeploy", "connect", "disconnect"}:
                return self.run_mutating(
                    Action(command),
                    args.targets,
                    yes=args.yes,
                    deploy=self._registry_deploy_options(args),
                    connect=self._registry_connect_options(args),
                    disconnect_registry_id=args.registry_id or "",
                )
            if command == "logs":
                return self.cmd_logs(args.targets, follow=args.follow or True)
            if command == "shell":
                return self.cmd_shell(args.targets)
            if command == "doctor":
                return self.cmd_doctor(args.targets, live_provider=args.live_provider)
            raise OctopusError(f"Unknown command: {command}")
        except OctopusError as exc:
            self.io.error(str(exc))
            return 1

    def print_help(self) -> None:
        self.io.print("Usage: ./octopus <action> [target...] [--yes]")
        self.io.print("")
        self.io.print("Actions:")
        self.io.print("  status")
        self.io.print("  start [target...] [--yes] [--registry-bind-host HOST] [--registry-port PORT] [--registry-public-url URL]")
        self.io.print("  stop [target...] [--yes]")
        self.io.print("  restart [target...] [--yes] [--registry-bind-host HOST] [--registry-port PORT] [--registry-public-url URL]")
        self.io.print("  redeploy [target...] [--yes] [--registry-bind-host HOST] [--registry-port PORT] [--registry-public-url URL]")
        self.io.print("  connect [target...] [--yes] [--registry-url URL --registry-enroll-token TOKEN] [--registry-id ID] [--registry-scope SCOPE]")
        self.io.print("  disconnect [target...] [--yes] [--registry-id ID]")
        self.io.print("  logs <target> [--follow]")
        self.io.print("  shell <target>")
        self.io.print("  doctor <target> [--live-provider]")
        self.io.print("  clean")
        self.io.print("")
        self.io.print("Targets:")
        self.io.print("  registry")
        self.io.print("  bots")
        self.io.print("  bot slug")
        self.io.print("  short alias like m1 when unique")

    def _render_bot_lines(self, bots: list[BotState]) -> None:
        for bot in bots:
            running = "running" if bot.running else "stopped"
            detail = f"({bot.docker_status})" if bot.docker_status else ""
            self.io.print(f"  {bot.label}    {bot.provider}   {bot.mode}   {running}   {detail}".rstrip())
            for connection in bot.registry_connection_statuses:
                label = "local" if connection.local else connection.registry_id
                self.io.print(f"      {label:<8} {connection.scope:<8} {connection.live_state:<18} {connection.url}")

    def cmd_status(self, targets: list[str]) -> int:
        state = self._state(live_provider_auth=True)
        if not targets:
            self.render_system_status(state)
            return 0
        lowered = [item.lower() for item in targets]
        if lowered == ["registry"]:
            self.render_registry_status(state)
            return 0
        if lowered == ["bots"]:
            self.render_bot_status(state)
            return 0
        for target in targets:
            bot = self.manager.resolve_bot(target, state)
            self.render_single_bot_status(bot, state)
        return 0

    def render_system_status(self, state: SystemState) -> None:
        self.render_bot_status(state)
        self.io.print("")
        self.render_registry_status(state)
        self.io.print("")
        self.render_provider_auth_status(state)
        self.io.print("")
        self.render_freshness_status(state)

    def render_bot_status(self, state: SystemState) -> None:
        self.io.print("Bots:")
        if not state.bots:
            self.io.print("  (none)")
            return
        for bot in state.bots:
            running = "running" if bot.running else "stopped"
            detail = f"({bot.docker_status})" if bot.docker_status else ""
            self.io.print(f"  {bot.label}    {bot.provider}   {bot.mode}   {running}   {detail}".rstrip())
            for connection in bot.registry_connection_statuses:
                label = "local" if connection.local else connection.registry_id
                self.io.print(f"      {label:<8} {connection.scope:<8} {connection.live_state:<18} {connection.url}")

    def render_single_bot_status(self, bot: BotState, state: SystemState) -> None:
        del state
        self.io.print(f"Bot: {bot.label}")
        self.io.print(f"  Slug:      {bot.slug}")
        self.io.print(f"  Provider:  {bot.provider}")
        self.io.print(f"  Mode:      {bot.mode}")
        self.io.print(f"  State:     {'running' if bot.running else 'stopped'}")
        if bot.docker_status:
            self.io.print(f"  Docker:    {bot.docker_status}")
        self.io.print(f"  Role:      {bot.role or '(not set)'}")
        self.io.print(f"  Tags:      {bot.tags or '(not set)'}")
        if bot.registry_connection_statuses:
            self.io.print("  Registry connections:")
            for connection in bot.registry_connection_statuses:
                label = "local" if connection.local else connection.registry_id
                self.io.print(
                    f"    {label:<12} scope={connection.scope:<8} configured={connection.connection_state:<10} live={connection.live_state:<18} {connection.url}"
                )
        else:
            self.io.print("  Registry connections: none")
        if bot.workspace_memberships:
            self.io.print(f"  Workspaces: {', '.join(bot.workspace_memberships)}")

    def render_registry_status(self, state: SystemState) -> None:
        self.io.print("Registry:")
        if not state.registry.configured:
            self.io.print("  local      not configured")
            return
        status = "running" if state.registry.running else "stopped"
        self.io.print(f"  local      {status}")
        self.io.print(f"  bind:      {state.registry.bind_host}:{state.registry.port}")
        self.io.print(f"  host URL:  {state.registry.host_base_url}")
        self.io.print(f"  public:    {state.registry.public_url}")
        self.io.print(f"  ui:        {state.registry.ui_url}")
        self.io.print("")
        self.io.print("Connected bots:")
        connected = [
            (bot, connection)
            for bot in state.bots
            for connection in bot.registry_connection_statuses
            if connection.local and connection.live_state == "connected"
        ]
        if not connected:
            self.io.print("  (none)")
        else:
            for bot, connection in connected:
                self.io.print(f"  {bot.label}    scope: {connection.scope}    state: connected")
        self.io.print("")
        self.io.print("Configured but not connected:")
        configured = [
            (bot, connection)
            for bot in state.bots
            for connection in bot.registry_connection_statuses
            if connection.local and connection.connection_state != "none" and connection.live_state != "connected"
        ]
        if not configured:
            self.io.print("  (none)")
        else:
            for bot, connection in configured:
                self.io.print(f"  {bot.label}    scope: {connection.scope}    state: {connection.live_state}")

    def render_provider_auth_status(self, state: SystemState) -> None:
        self.io.print("Provider auth:")
        for provider in state.provider_auth:
            self.io.print(f"  {provider.provider:<10} {provider.status_label}")
            if provider.detail and provider.healthy is not True:
                self.io.print(f"      detail: {provider.detail}")

    def render_freshness_status(self, state: SystemState) -> None:
        self.io.print("Freshness:")
        for key, freshness in sorted(state.freshness.items()):
            status = "stale" if freshness.stale else "current"
            self.io.print(f"  {key:<12} {status}    {freshness.image}")

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
        if action not in {Action.START, Action.RESTART, Action.REDEPLOY} and not deploy.is_empty:
            raise OctopusError("Registry bind/public URL options are only valid with start, restart, or redeploy.")
        if action not in {Action.CONNECT, Action.DISCONNECT}:
            if connect.is_remote or disconnect_registry_id:
                raise OctopusError("Registry connection options are only valid with connect or disconnect.")
        if action != Action.CONNECT and connect.is_remote:
            raise OctopusError("--registry-url and --registry-enroll-token are only valid with connect.")
        state = self.manager.inspect_state()
        if action == Action.CONNECT and connect.is_remote and not selectors:
            targets = [ResolvedTarget(TargetKind.BOT, bot.slug, bot.label) for bot in state.bots]
        elif action == Action.DISCONNECT and disconnect_registry_id and not selectors:
            targets = [
                ResolvedTarget(TargetKind.BOT, bot.slug, bot.label)
                for bot in state.bots
                if any(connection.registry_id == disconnect_registry_id for connection in bot.registry_connection_statuses)
            ]
        else:
            targets = self.manager.resolve_targets(selectors, action, state)
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
        if action == Action.START:
            return self.execute_start(targets, deploy=deploy)
        if action == Action.STOP:
            return self.execute_stop(targets)
        if action == Action.RESTART:
            return self.execute_restart(targets, deploy=deploy)
        if action == Action.REDEPLOY:
            return self.execute_redeploy(targets, deploy=deploy)
        if action == Action.CONNECT:
            return self.execute_connect(targets, connect=connect)
        if action == Action.DISCONNECT:
            return self.execute_disconnect(targets, registry_id=disconnect_registry_id)
        raise OctopusError(f"Unsupported action: {action.value}")

    def execute_start(self, targets: list[ResolvedTarget], *, deploy: RegistryDeployOptions | None = None) -> int:
        for target in targets:
            if target.kind == TargetKind.REGISTRY:
                self.manager.start_registry(deploy=deploy)
            else:
                self.manager.start_bot(target.identifier)
        return 0

    def execute_stop(self, targets: list[ResolvedTarget]) -> int:
        for target in targets:
            if target.kind == TargetKind.REGISTRY:
                self.manager.stop_registry()
            else:
                self.manager.stop_bot(target.identifier)
        return 0

    def execute_restart(self, targets: list[ResolvedTarget], *, deploy: RegistryDeployOptions | None = None) -> int:
        for target in targets:
            if target.kind == TargetKind.REGISTRY:
                if self.manager.has_local_registry():
                    self.manager.stop_registry()
                self.manager.start_registry(deploy=deploy)
            else:
                self.manager.restart_bot(target.identifier)
        return 0

    def execute_redeploy(self, targets: list[ResolvedTarget], *, deploy: RegistryDeployOptions | None = None) -> int:
        for target in targets:
            if target.kind == TargetKind.REGISTRY:
                if self.manager.has_local_registry():
                    self.manager.stop_registry()
                self.manager.start_registry(force_rebuild=True, force_recreate=True, deploy=deploy)
            else:
                self.manager.restart_bot(target.identifier, force_rebuild=True)
        return 0

    def execute_connect(self, targets: list[ResolvedTarget], *, connect: RegistryConnectOptions | None = None) -> int:
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

    def execute_disconnect(self, targets: list[ResolvedTarget], *, registry_id: str = "") -> int:
        for target in targets:
            connection = self.manager.disconnect_bot_registry(target.identifier, registry_id=registry_id)
            label = "local registry" if connection.url == LOCAL_REGISTRY_INTERNAL_URL else f"registry {connection.registry_id}"
            self.io.print(f"Disconnected {target.label} from {label}.")
        return 0

    def cmd_logs(self, targets: list[str], *, follow: bool) -> int:
        state = self.manager.inspect_state()
        resolved = self.manager.resolve_targets(targets, Action.LOGS, state)
        if len(resolved) != 1:
            raise OctopusError("logs requires exactly one target.")
        return self.manager.follow_logs(resolved[0], follow=follow)

    def cmd_shell(self, targets: list[str]) -> int:
        state = self.manager.inspect_state()
        resolved = self.manager.resolve_targets(targets, Action.SHELL, state)
        if len(resolved) != 1:
            raise OctopusError("shell requires exactly one target.")
        return self.manager.open_shell(resolved[0])

    def cmd_doctor(self, targets: list[str], *, live_provider: bool) -> int:
        state = self.manager.inspect_state()
        resolved = self.manager.resolve_targets(targets, Action.DOCTOR, state)
        if len(resolved) != 1 or resolved[0].kind != TargetKind.BOT:
            raise OctopusError("doctor requires exactly one bot target.")
        output = self.manager.run_bot_doctor(resolved[0].identifier, live_provider=live_provider)
        self.io.print(output.rstrip())
        return 0

    def recommended_actions(self, state: SystemState) -> list[tuple[str, callable[[], int]]]:
        actions: list[tuple[str, callable[[], int]]] = []
        if not state.bots:
            actions.append(("Add your first bot", self.manager.add_bot_interactive))
            return actions
        stale_registry = state.freshness["registry"].stale and state.registry.configured
        if stale_registry:
            actions.append(("Redeploy stale registry", lambda: self.execute_redeploy([ResolvedTarget(TargetKind.REGISTRY, "registry", "registry")])))
        stopped_bots = [bot for bot in state.bots if not bot.running]
        if stopped_bots:
            actions.append((f"Start {len(stopped_bots)} stopped bot(s)", lambda: self.execute_start([ResolvedTarget(TargetKind.BOT, bot.slug, bot.label) for bot in stopped_bots])))
        degraded = [
            bot for bot in state.bots if bot.local_registry_connection_state != "none" and bot.local_registry_live_state != "connected"
        ]
        if degraded:
            actions.append((f"Reconnect {len(degraded)} bot(s) to registry", lambda: self.execute_connect([ResolvedTarget(TargetKind.BOT, bot.slug, bot.label) for bot in degraded])))
        missing_auth = [auth for auth in state.provider_auth if auth.needs_authentication]
        for auth in missing_auth:
            actions.append((f"Authenticate {auth.provider}", lambda provider=auth.provider: self.manager.ensure_provider_auth_ready(provider) or 0))
        return actions

    def interactive_menu(self) -> int:
        while True:
            state = self._state()
            self.io.print("What would you like to do?")
            options: list[tuple[str, callable[[], int | None]]] = []
            options.append(("Recommended Actions", self.menu_recommended))
            options.append(("Lifecycle", self.menu_lifecycle))
            options.append(("Bots", self.menu_bots))
            if state.registry.configured or state.bots:
                options.append(("Registry", self.menu_registry))
            options.append(("Workspaces", self.menu_workspaces))
            options.append(("Diagnose", self.menu_diagnose))
            options.append(("Status", self.menu_status))
            for index, (label, _) in enumerate(options, start=1):
                self.io.print(f"  {index}. {label}")
            try:
                choice = self.io.prompt("Choose an option: ").strip()
            except EOFError:
                return 0
            if not choice.isdigit():
                self.io.error("Choose one of the listed options.")
                continue
            numeric = int(choice)
            if numeric < 1 or numeric > len(options):
                self.io.error("Choose one of the listed options.")
                continue
            action = options[numeric - 1][1]
            result = action()
            if result is not None:
                return int(result)

    def choose__items(self, title: str, items: list[tuple[str, callable[[], int | None]]]) -> int | None:
        while True:
            self.io.print(title)
            for index, (label, _) in enumerate(items, start=1):
                self.io.print(f"  {index}. {label}")
            self.io.print(f"  {len(items) + 1}. Back")
            choice = self.io.prompt("Choose an option: ").strip()
            if not choice.isdigit():
                self.io.error("Choose one of the listed options.")
                continue
            numeric = int(choice)
            if numeric == len(items) + 1:
                return None
            if numeric < 1 or numeric > len(items):
                self.io.error("Choose one of the listed options.")
                continue
            return items[numeric - 1][1]()

    def menu_recommended(self) -> int | None:
        state = self._state(live_provider_auth=True)
        recommended = self.recommended_actions(state)
        if not recommended:
            self.io.print("No recommended actions right now.")
            return None
        items = [(label, lambda callback=callback: callback()) for label, callback in recommended]
        return self.choose__items("Recommended Actions", items)

    def menu_lifecycle(self) -> int | None:
        return self.choose__items(
            "Lifecycle",
            [
                ("Start", lambda: self.menu_select_action(Action.START)),
                ("Stop", lambda: self.menu_select_action(Action.STOP)),
                ("Restart", lambda: self.menu_select_action(Action.RESTART)),
                ("Redeploy", lambda: self.menu_select_action(Action.REDEPLOY)),
            ],
        )

    def target_choices_for_menu(self, state: SystemState) -> list[tuple[str, list[ResolvedTarget]]]:
        choices: list[tuple[str, list[ResolvedTarget]]] = []
        all_targets: list[ResolvedTarget] = []
        if state.registry.configured:
            all_targets.append(ResolvedTarget(TargetKind.REGISTRY, "registry", "registry"))
            choices.append(("Registry", [ResolvedTarget(TargetKind.REGISTRY, "registry", "registry")]))
        if state.bots:
            bot_targets = [ResolvedTarget(TargetKind.BOT, bot.slug, bot.label) for bot in state.bots]
            all_targets.extend(bot_targets)
            choices.append(("Bots", bot_targets))
            for bot in state.bots:
                choices.append((bot.label, [ResolvedTarget(TargetKind.BOT, bot.slug, bot.label)]))
        if all_targets:
            choices.insert(0, ("All", all_targets))
        return choices

    def menu_select_action(self, action: Action) -> int | None:
        state = self.manager.inspect_state()
        choices = self.target_choices_for_menu(state)
        return self.choose__items(
            f"{action.value.title()}",
            [(label, lambda targets=targets, act=action: self.run_mutating(act, [target.identifier for target in targets], yes=False)) for label, targets in choices],
        )

    def menu_bots(self) -> int | None:
        state = self.manager.inspect_state()
        items: list[tuple[str, callable[[], int | None]]] = [("Add bot", self.manager.add_bot_interactive)]
        if state.bots:
            items.extend(
                [
                    ("Connect", lambda: self.menu_select_action(Action.CONNECT)),
                    ("Disconnect", lambda: self.menu_select_action(Action.DISCONNECT)),
                    ("Start", lambda: self.menu_select_action(Action.START)),
                    ("Stop", lambda: self.menu_select_action(Action.STOP)),
                    ("Restart", lambda: self.menu_select_action(Action.RESTART)),
                    ("Redeploy", lambda: self.menu_select_action(Action.REDEPLOY)),
                    ("Inspect", lambda: self.cmd_status(["bots"])),
                ]
            )
        return self.choose__items("Bots", items)

    def menu_registry(self) -> int | None:
        state = self.manager.inspect_state()
        items: list[tuple[str, callable[[], int | None]]] = []
        if state.registry.running:
            items.extend(
                [
                    ("Stop registry", lambda: self.run_mutating(Action.STOP, ["registry"], yes=False)),
                    ("Restart registry", lambda: self.run_mutating(Action.RESTART, ["registry"], yes=False)),
                ]
            )
        else:
            items.append(("Start registry", lambda: self.run_mutating(Action.START, ["registry"], yes=False)))
        items.append(("Redeploy registry", lambda: self.run_mutating(Action.REDEPLOY, ["registry"], yes=False)))
        items.append(("Open registry UI", lambda: webbrowser.open(state.registry.ui_url) or 0))
        items.append(("Inspect registry", lambda: self.cmd_status(["registry"])))
        return self.choose__items("Registry", items)

    def menu_workspaces(self) -> int | None:
        items = [
            ("Create workspace", self.menu_workspace_create),
            ("Remove workspace", self.menu_workspace_remove),
            ("Attach bot", self.menu_workspace_attach),
            ("Detach bot", self.menu_workspace_detach),
            ("Inspect workspaces", self.menu_workspace_status),
        ]
        return self.choose__items("Workspaces", items)

    def menu_workspace_create(self) -> int:
        name = self.io.prompt("Workspace name: ").strip()
        path = self.io.prompt("Host path: ").strip()
        self.manager.create_workspace(name, path)
        self.io.print(f'Workspace "{name}" created.')
        return 0

    def menu_workspace_remove(self) -> int:
        state = self.manager.inspect_state()
        if not state.workspaces:
            raise OctopusError("No workspaces configured.")
        choices = [(workspace.slug, lambda slug=workspace.slug: self._workspace_remove(slug)) for workspace in state.workspaces]
        result = self.choose__items("Remove workspace", choices)
        return 0 if result is None else int(result)

    def _workspace_remove(self, slug: str) -> int:
        ws_dir = self.manager.workspace_conf_file(slug).parent
        members = self.manager.workspace_members(slug)
        if ws_dir.exists():
            for member in members:
                self.manager.remove_bot__workspace(slug, member)
            for child in sorted(ws_dir.glob("*"), reverse=True):
                if child.is_file():
                    child.unlink()
            ws_dir.rmdir()
        self.io.print(f'Workspace "{slug}" removed.')
        return 0

    def menu_workspace_attach(self) -> int:
        state = self.manager.inspect_state()
        if not state.workspaces:
            raise OctopusError("No workspaces configured.")
        if not state.bots:
            raise OctopusError("No bots configured.")
        ws_name = self.io.prompt("Workspace name: ").strip()
        bot_selector = self.io.prompt("Bot: ").strip()
        bot = self.manager.resolve_bot(bot_selector, state)
        self.manager.add_bot_to_workspace(ws_name, bot.slug)
        self.io.print(f'Added "{bot.slug}" to workspace "{ws_name}".')
        return 0

    def menu_workspace_detach(self) -> int:
        state = self.manager.inspect_state()
        if not state.workspaces:
            raise OctopusError("No workspaces configured.")
        ws_name = self.io.prompt("Workspace name: ").strip()
        bot_selector = self.io.prompt("Bot: ").strip()
        bot = self.manager.resolve_bot(bot_selector, state)
        self.manager.remove_bot__workspace(ws_name, bot.slug)
        self.io.print(f'Removed "{bot.slug}" workspace "{ws_name}".')
        return 0

    def menu_workspace_status(self) -> int:
        state = self.manager.inspect_state()
        self.io.print("Workspaces:")
        if not state.workspaces:
            self.io.print("  (none)")
            return 0
        for workspace in state.workspaces:
            self.io.print(f"  {workspace.slug:<20} {workspace.root}    {workspace.mode}")
            self.io.print("    Members:")
            if not workspace.members:
                self.io.print("      (none)")
            else:
                for member in workspace.members:
                    running = "running" if self.manager.bot_is_running(member) else "stopped"
                    self.io.print(f"      {member:<20} {running}")
        return 0

    def menu_diagnose(self) -> int | None:
        items = [
            ("Logs", lambda: self._diagnose_choose_target(self.cmd_logs)),
            ("Shell", lambda: self._diagnose_choose_target(self.cmd_shell)),
            ("Doctor", lambda: self._diagnose_choose_target(self.cmd_doctor, bot_only=True)),
            ("Provider auth", self.menu_provider_auth),
        ]
        return self.choose__items("Diagnose", items)

    def _diagnose_choose_target(self, callback, *, bot_only: bool = False):
        state = self.manager.inspect_state()
        items: list[tuple[str, callable[[], int | None]]] = []
        if not bot_only and state.registry.configured:
            items.append(("registry", lambda: callback(["registry"])))
        for bot in state.bots:
            items.append((bot.label, lambda slug=bot.slug: callback([slug])))
        return self.choose__items("Choose a target", items)

    def menu_provider_auth(self) -> int:
        state = self._state(live_provider_auth=True)
        items = [
            (
                f"{provider.provider} ({provider.status_label})",
                lambda provider_name=provider.provider: self._provider_auth(provider_name),
            )
            for provider in state.provider_auth
        ]
        result = self.choose__items("Provider auth", items)
        return 0 if result is None else int(result)

    def _provider_auth(self, provider: str) -> int:
        self.manager.ensure_provider_auth_ready(provider)
        self.io.print(f"{provider} authentication complete.")
        return 0

    def menu_status(self) -> int | None:
        return self.choose__items(
            "Status",
            [
                ("System summary", lambda: self.cmd_status([])),
                ("Bots", lambda: self.cmd_status(["bots"])),
                ("Registry", lambda: self.cmd_status(["registry"])),
                ("Workspaces", self.menu_workspace_status),
                ("Freshness", lambda: self._status_freshness()),
            ],
        )

    def _status_freshness(self) -> int:
        self.render_freshness_status(self.manager.inspect_state())
        return 0


def main(argv: list[str] | None = None) -> int:
    repo_dir = Path(__file__).resolve().parents[2]
    cli = OctopusCLI(repo_dir)
    return cli.run(argv)
