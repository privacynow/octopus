from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import shutil
import socket
import subprocess
import sys
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from app.octopus_cli.core import OctopusManager
from app.octopus_cli.envfiles import parse_env_file, write_env_file
from app.subprocess_env import build_subprocess_env
from octopus_sdk.registry.client import RegistryClient
from octopus_sdk.registry.models import RoutedTaskRequest


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE_REPO = Path("/Users/tinker/octopus")
DEFAULT_TEMP_ROOT = REPO_ROOT / ".tmp" / "e2e-live-smoke"
PLAYWRIGHT_DIR = REPO_ROOT / "docs" / "registry-ui-screenshots"
PLAYWRIGHT_SPEC = PLAYWRIGHT_DIR / "live_registry_smoke.spec.js"
PLAYWRIGHT_CONFIG = PLAYWRIGHT_DIR / "live_registry_playwright.config.cjs"


class HarnessError(RuntimeError):
    pass


@dataclass(frozen=True)
class StackState:
    registry_running: bool
    running_bots: list[str]


@dataclass(frozen=True)
class BotRuntimeState:
    slug: str
    display_name: str
    registry_id: str
    agent_id: str
    agent_token: str


def _print(message: str = "") -> None:
    sys.stdout.write(f"{message}\n")
    sys.stdout.flush()


def _free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _ensure_removed(path: Path) -> None:
    if not path.exists() and not path.is_symlink():
        return
    if path.is_symlink() or path.is_file():
        path.unlink()
        return
    shutil.rmtree(path)


def _snapshot_ignore(path: str, names: list[str]) -> set[str]:
    current = Path(path)
    ignored: set[str] = set()
    if "provider-auth" in current.parts:
        for name in names:
            if name in {"tmp", ".tmp"}:
                ignored.add(name)
    return ignored


def _poll(
    description: str,
    func,
    *,
    timeout_seconds: float,
    interval_seconds: float = 2.0,
) -> Any:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            result = func()
            if result:
                return result
        except Exception as exc:  # pragma: no cover - exercised live
            last_error = exc
        time.sleep(interval_seconds)
    if last_error is not None:
        raise HarnessError(f"{description} timed out: {last_error}") from last_error
    raise HarnessError(f"{description} timed out")


class FreshStack:
    def __init__(self, repo_dir: Path, deploy_dir: Path, artifacts_dir: Path, run_id: str) -> None:
        self.repo_dir = repo_dir
        self.deploy_dir = deploy_dir
        self.artifacts_dir = artifacts_dir
        self.run_id = run_id
        self.network_name = f"octopus-e2e-net-{run_id}"
        self.registry_project = f"octopus-e2e-registry-{run_id}"
        self.registry_env_file = self.deploy_dir / "registry" / ".env"
        self.registry_values = parse_env_file(self.registry_env_file)
        self.registry_port = int(self.registry_values["REGISTRY_PORT"])
        self.base_url = f"http://127.0.0.1:{self.registry_port}"
        self.ui_url = f"{self.base_url}/ui"
        self.ui_token = self.registry_values["REGISTRY_UI_TOKEN"]
        self.enroll_token = self.registry_values["REGISTRY_ENROLL_TOKEN"]
        self.bot_slugs = sorted(
            path.name for path in (self.deploy_dir / "bots").iterdir() if (path / ".env").exists()
        )

    def _run(
        self,
        args: list[str],
        *,
        env: dict[str, str] | None = None,
        timeout: int = 120,
        capture_output: bool = True,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            args,
            cwd=self.repo_dir,
            env=build_subprocess_env(extra_env=env),
            text=True,
            capture_output=capture_output,
            check=check,
            timeout=timeout,
        )

    def ensure_network(self) -> None:
        inspect = self._run(["docker", "network", "inspect", self.network_name], check=False)
        if inspect.returncode == 0:
            return
        self._run(["docker", "network", "create", self.network_name], capture_output=False)

    def bot_env_file(self, slug: str) -> Path:
        return self.deploy_dir / "bots" / slug / ".env"

    def bot_values(self, slug: str) -> dict[str, str]:
        return parse_env_file(self.bot_env_file(slug))

    def bot_display_name(self, slug: str) -> str:
        return self.bot_values(slug).get("BOT_DISPLAY_NAME", slug)

    def bot_project(self, slug: str) -> str:
        return f"octopus-e2e-{self.run_id}-{slug}"

    def bot_provider_auth_dir(self, slug: str) -> Path:
        provider = self.bot_values(slug).get("BOT_PROVIDER", "claude")
        return self.deploy_dir / "provider-auth" / provider

    def bot_workspace_compose(self, slug: str) -> Path | None:
        path = self.deploy_dir / "bots" / slug / "docker-compose.workspace.yml"
        return path if path.exists() else None

    def registry_compose(
        self,
        *args: str,
        capture_output: bool = True,
        check: bool = True,
        timeout: int = 120,
    ) -> subprocess.CompletedProcess[str]:
        command = [
            "docker",
            "compose",
            "--project-directory",
            str(self.repo_dir),
            "-p",
            self.registry_project,
            "-f",
            str(self.repo_dir / "infra" / "compose" / "docker-compose.yml"),
            "--profile",
            "registry",
            "--env-file",
            str(self.registry_env_file),
            *args,
        ]
        return self._run(
            command,
            env={"OCTOPUS_NETWORK": self.network_name},
            capture_output=capture_output,
            check=check,
            timeout=timeout,
        )

    def bot_compose(
        self,
        slug: str,
        *args: str,
        capture_output: bool = True,
        check: bool = True,
        timeout: int = 120,
    ) -> subprocess.CompletedProcess[str]:
        env_file = self.bot_env_file(slug)
        command = [
            "docker",
            "compose",
            "--project-directory",
            str(self.repo_dir),
            "-p",
            self.bot_project(slug),
            "-f",
            str(self.repo_dir / "infra" / "compose" / "docker-compose.yml"),
        ]
        workspace_compose = self.bot_workspace_compose(slug)
        if workspace_compose is not None:
            command += ["-f", str(workspace_compose)]
        command += [
            "--profile",
            "bot",
            "--env-file",
            str(env_file),
            *args,
        ]
        env = {
            "OCTOPUS_NETWORK": self.network_name,
            "PROVIDER_AUTH_DIR": str(self.bot_provider_auth_dir(slug)),
            "BOT_ENV_FILE": str(env_file),
            "REGISTRY_ENROLL_TOKEN": self.enroll_token,
            "REGISTRY_UI_TOKEN": self.ui_token,
        }
        return self._run(command, env=env, capture_output=capture_output, check=check, timeout=timeout)

    def build_images(self) -> None:
        manager = OctopusManager(self.repo_dir)
        manager.build_registry_image()
        providers = {self.bot_values(slug).get("BOT_PROVIDER", "claude") for slug in self.bot_slugs}
        for provider in sorted(providers):
            auth_dir = self.deploy_dir / "provider-auth" / provider
            if not auth_dir.exists():
                raise HarnessError(f"Missing provider auth directory for {provider}: {auth_dir}")
            manager.build_provider_image(provider)

    def start(self) -> None:
        self.ensure_network()
        self.down()
        self.registry_compose("up", "-d", "--remove-orphans", "service", capture_output=False)
        _poll(
            "registry health",
            lambda: httpx.get(f"{self.base_url}/healthz", timeout=5.0).status_code == 200,
            timeout_seconds=30,
        )
        for slug in self.bot_slugs:
            self.bot_compose(slug, "up", "-d", "--force-recreate", "bot", capture_output=False)
            _poll(
                f"{slug} container running",
                lambda slug=slug: self.bot_compose(
                    slug,
                    "ps",
                    "--status",
                    "running",
                    "bot",
                    capture_output=True,
                    check=False,
                ).returncode == 0,
                timeout_seconds=30,
            )

    def wait_for_connected_bot(self, slug: str) -> BotRuntimeState:
        values = self.bot_values(slug)
        registry_id = "local"
        display_name = values.get("BOT_DISPLAY_NAME", slug)

        def _read() -> BotRuntimeState | None:
            state = self.read_bot_registry_state(slug, registry_id)
            if not state:
                return None
            if state.get("connectivity_state") != "connected":
                return None
            agent_id = state.get("agent_id", "")
            agent_token = state.get("agent_token", "")
            if not agent_id or not agent_token:
                return None
            return BotRuntimeState(
                slug=slug,
                display_name=display_name,
                registry_id=registry_id,
                agent_id=agent_id,
                agent_token=agent_token,
            )

        return _poll(f"{slug} registry connection", _read, timeout_seconds=90)

    def read_bot_registry_state(self, slug: str, registry_id: str) -> dict[str, str]:
        script = (
            "from pathlib import Path\n"
            "import json, os\n"
            "path = Path('/home/bot/data/agent/registries') / f\"{os.environ['OCTOPUS_REGISTRY_ID']}.json\"\n"
            "if not path.exists():\n"
            "    raise SystemExit(2)\n"
            "print(path.read_text())\n"
        )
        result = self.bot_compose(
            slug,
            "exec",
            "-T",
            "-e",
            f"OCTOPUS_REGISTRY_ID={registry_id}",
            "bot",
            "python",
            "-c",
            script,
            capture_output=True,
            check=False,
            timeout=30,
        )
        if result.returncode != 0 or not (result.stdout or "").strip():
            return {}
        try:
            data = json.loads(result.stdout.strip())
        except json.JSONDecodeError:
            return {}
        return {str(key): str(value) for key, value in data.items()}

    def write_bot_file(self, slug: str, path: str, content: str) -> None:
        script = (
            "from pathlib import Path\n"
            "import os\n"
            "path = Path(os.environ['OCTOPUS_WRITE_PATH'])\n"
            "path.parent.mkdir(parents=True, exist_ok=True)\n"
            "path.write_text(os.environ['OCTOPUS_WRITE_CONTENT'], encoding='utf-8')\n"
        )
        result = self.bot_compose(
            slug,
            "exec",
            "-T",
            "-e",
            f"OCTOPUS_WRITE_PATH={path}",
            "-e",
            f"OCTOPUS_WRITE_CONTENT={content}",
            "bot",
            "python",
            "-c",
            script,
            capture_output=True,
            check=False,
            timeout=30,
        )
        if result.returncode != 0:
            raise HarnessError(
                f"failed to write {path} in bot {slug}: {(result.stderr or result.stdout or '').strip()}"
            )

    def down(self) -> None:
        for slug in self.bot_slugs:
            self.bot_compose(
                slug,
                "down",
                "-v",
                "--remove-orphans",
                "-t",
                "2",
                capture_output=False,
                check=False,
                timeout=120,
            )
        self.registry_compose(
            "down",
            "-v",
            "--remove-orphans",
            "-t",
            "2",
            capture_output=False,
            check=False,
            timeout=120,
        )

    def collect_logs(self) -> None:
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        registry_logs = self.registry_compose("logs", "--no-color", "service", capture_output=True, check=False)
        (self.artifacts_dir / "registry.compose.log").write_text(
            (registry_logs.stdout or "") + (registry_logs.stderr or ""),
            encoding="utf-8",
        )
        for slug in self.bot_slugs:
            result = self.bot_compose(slug, "logs", "--no-color", "bot", capture_output=True, check=False)
            (self.artifacts_dir / f"{slug}.compose.log").write_text(
                (result.stdout or "") + (result.stderr or ""),
                encoding="utf-8",
            )


class LiveRegistryHarness:
    def __init__(
        self,
        *,
        repo_dir: Path,
        source_repo: Path | None,
        snapshot_deploy: Path | None,
        temp_root: Path,
        keep_fresh_stack: bool,
        leave_source_stopped: bool,
        skip_playwright: bool,
    ) -> None:
        self.repo_dir = repo_dir
        self.source_repo = source_repo
        self.snapshot_source = snapshot_deploy
        self.temp_root = temp_root
        self.keep_fresh_stack = keep_fresh_stack
        self.leave_source_stopped = leave_source_stopped
        self.skip_playwright = skip_playwright
        self.snapshot_deploy = self.temp_root / "snapshot" / ".deploy"
        self.artifacts_dir = self.temp_root / "artifacts"
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.fresh_stack: FreshStack | None = None

    def rewrite_snapshot_workspace_overrides(self) -> None:
        deploy_prefix = f"{self.snapshot_deploy.as_posix()}/"
        for compose_file in self.snapshot_deploy.glob("bots/*/docker-compose.workspace*.yml"):
            raw = compose_file.read_text(encoding="utf-8")
            updated = raw.replace(".deploy/", deploy_prefix)
            if updated != raw:
                compose_file.write_text(updated, encoding="utf-8")

    def capture_stack_state(self, repo_dir: Path) -> StackState:
        manager = OctopusManager(repo_dir)
        state = manager.inspect_state()
        return StackState(
            registry_running=state.registry.running,
            running_bots=[bot.slug for bot in state.bots if bot.running],
        )

    def stop_stack(self, repo_dir: Path, snapshot: StackState) -> None:
        manager = OctopusManager(repo_dir)
        for slug in snapshot.running_bots:
            _print(f"Stopping {repo_dir} bot {slug}")
            manager.stop_bot(slug)
        if snapshot.registry_running:
            _print(f"Stopping {repo_dir} registry")
            manager.stop_registry()

    def restore_stack(self, repo_dir: Path, snapshot: StackState) -> None:
        manager = OctopusManager(repo_dir)
        if snapshot.registry_running:
            _print(f"Restoring {repo_dir} registry")
            manager.start_registry()
        for slug in snapshot.running_bots:
            _print(f"Restoring {repo_dir} bot {slug}")
            manager.start_bot(slug)

    def snapshot_source_deploy(self) -> None:
        source_deploy = self.snapshot_source
        if source_deploy is None:
            if self.source_repo is None:
                raise HarnessError("source repo or snapshot deploy path is required")
            source_deploy = self.source_repo / ".deploy"
        if not source_deploy.exists():
            raise HarnessError(f"Missing source deploy directory: {source_deploy}")
        _ensure_removed(self.snapshot_deploy.parent)
        shutil.copytree(source_deploy, self.snapshot_deploy, dirs_exist_ok=True, ignore=_snapshot_ignore)
        self.rewrite_snapshot_workspace_overrides()
        registry_env = OrderedDict(parse_env_file(self.snapshot_deploy / "registry" / ".env"))
        registry_env["REGISTRY_BIND_HOST"] = "127.0.0.1"
        registry_env["REGISTRY_PORT"] = str(_free_local_port())
        write_env_file(self.snapshot_deploy / "registry" / ".env", registry_env)
        for bot_env_path in sorted((self.snapshot_deploy / "bots").glob("*/.env")):
            bot_env = OrderedDict(parse_env_file(bot_env_path))
            # The isolated smoke exercises registry-origin flows only. Blank the
            # Telegram token so the disposable bots run registry-only and do not
            # collide with any other long-poll consumer for the saved Telegram bot.
            bot_env["TELEGRAM_BOT_TOKEN"] = ""
            write_env_file(bot_env_path, bot_env)

    def run_operator_smoke(self) -> dict[str, str]:
        assert self.fresh_stack is not None
        stack = self.fresh_stack
        base_url = stack.base_url
        with httpx.Client(base_url=base_url, timeout=5.0, follow_redirects=False) as client:
            login = client.post(
                "/ui/login",
                data={"password": stack.ui_token},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if login.status_code not in {200, 302, 303}:
                raise HarnessError(f"Operator login failed: HTTP {login.status_code} {login.text}")
            csrf_resp = client.get("/v1/auth/csrf")
            csrf_resp.raise_for_status()
            csrf_payload = csrf_resp.json()
            csrf_token = str(csrf_payload.get("token") or csrf_payload.get("csrf_token") or "")
            if not csrf_token:
                raise HarnessError("CSRF token fetch returned no token")

            primary_state = stack.wait_for_connected_bot(stack.bot_slugs[0])
            if len(stack.bot_slugs) < 2:
                raise HarnessError("Live registry smoke requires at least two bots in the source deployment snapshot")
            secondary_state = stack.wait_for_connected_bot(stack.bot_slugs[1])
            delegation_secret = f"delegated-live-token-{secrets.token_hex(8)}"
            delegation_secret_path = "/home/bot/e2e/delegation-token.txt"
            stack.write_bot_file(
                secondary_state.slug,
                delegation_secret_path,
                delegation_secret,
            )

            for path in ("/v1/summary", "/v1/agents", "/v1/conversations", "/v1/tasks"):
                response = client.get(path, params={"limit": 10})
                response.raise_for_status()

            agents_resp = client.get("/v1/agents", params={"limit": 10})
            agents_resp.raise_for_status()
            agents_payload = agents_resp.json()
            if len(agents_payload.get("agents", [])) < 2:
                raise HarnessError("Registry did not report both bots as connected")

            basic_title = f"E2E basic conversation {int(time.time())}"
            basic_prompt = "Reply with the exact text registry smoke ok."
            basic_create = client.post(
                "/v1/conversations",
                headers={
                    "Content-Type": "application/json",
                    "X-CSRF-Token": csrf_token,
                },
                json={
                    "target_agent_id": primary_state.agent_id,
                    "origin_channel": "registry",
                    "external_conversation_ref": f"e2e-basic-{int(time.time())}",
                    "title": basic_title,
                },
            )
            basic_create.raise_for_status()
            basic_conversation_id = basic_create.json()["conversation_id"]
            basic_message = client.post(
                f"/v1/conversations/{basic_conversation_id}/messages",
                headers={
                    "Content-Type": "application/json",
                    "X-CSRF-Token": csrf_token,
                },
                json={"text": basic_prompt},
            )
            basic_message.raise_for_status()

            def _basic_reply() -> bool:
                events = client.get(
                    f"/v1/conversations/{basic_conversation_id}/events",
                    params={"limit": 40},
                )
                events.raise_for_status()
                payload = events.json()
                return any(
                    event.get("kind") == "message.bot"
                    and str(event.get("content", "")).strip().lower().rstrip(".!") == "registry smoke ok"
                    for event in payload.get("events", [])
                )

            _poll("basic conversation reply", _basic_reply, timeout_seconds=120)

            delegation_title = f"E2E natural delegation {int(time.time())}"
            delegation_prompt = (
                "The exact token needed to answer this request exists only on the other bot.\n"
                "You cannot read it in this bot.\n"
                "Your only valid first reply is exactly the delegation block below and nothing else.\n"
                "Do not explain. Do not summarize. Do not guess the token.\n\n"
                "Reply with exactly this delegation block and nothing else:\n"
                f'<delegation>{{"tasks":[{{"target":"{secondary_state.slug}","title":"Read delegated token","instructions":"Read the exact contents of {delegation_secret_path} and reply with only that content."}}]}}</delegation>\n\n'
                "When the delegated result returns, answer the user with that exact token only."
            )
            delegation_create = client.post(
                "/v1/conversations",
                headers={
                    "Content-Type": "application/json",
                    "X-CSRF-Token": csrf_token,
                },
                json={
                    "target_agent_id": primary_state.agent_id,
                    "origin_channel": "registry",
                    "external_conversation_ref": f"e2e-delegation-{int(time.time())}",
                    "title": delegation_title,
                },
            )
            delegation_create.raise_for_status()
            delegation_conversation_id = delegation_create.json()["conversation_id"]
            delegation_message = client.post(
                f"/v1/conversations/{delegation_conversation_id}/messages",
                headers={
                    "Content-Type": "application/json",
                    "X-CSRF-Token": csrf_token,
                },
                json={"text": delegation_prompt},
            )
            delegation_message.raise_for_status()

            primary_bot_values = stack.bot_values(stack.bot_slugs[0])
            delegation_autonomous = (
                primary_bot_values.get("BOT_AUTONOMOUS", "").strip() == "1"
                and primary_bot_values.get("BOT_APPROVAL_MODE", "").strip().lower() != "on"
            )

            def _delegation_events() -> list[dict[str, Any]]:
                response = client.get(
                    f"/v1/conversations/{delegation_conversation_id}/events",
                    params={"limit": 100},
                )
                response.raise_for_status()
                return response.json().get("events", [])

            def _delegation_state() -> dict[str, Any] | None:
                events = _delegation_events()
                proposed_event: dict[str, Any] | None = None
                for event in events:
                    content = str(event.get("content", "")).strip()
                    metadata = event.get("metadata", {}) or {}
                    if event.get("kind") == "error":
                        return {
                            "status": "failed",
                            "detail": str(metadata.get("message", "") or content or "error"),
                            "event": event,
                        }
                    if "Delegation submission failed" in content:
                        return {"status": "failed", "detail": content, "event": event}
                    if event.get("kind") == "delegation.submitted":
                        return {"status": "submitted", "event": event}
                    if event.get("kind") == "delegation.proposed":
                        proposed_event = event
                if proposed_event is not None:
                    return {"status": "proposed", "event": proposed_event}
                return None

            if delegation_autonomous:
                delegation_state = _poll(
                    "delegation submission",
                    _delegation_state,
                    timeout_seconds=180,
                )
                if delegation_state.get("status") == "failed":
                    raise HarnessError(
                        "autonomous delegation failed: "
                        f"{delegation_state.get('detail', 'unknown error')}"
                    )
            else:
                delegation_state = _poll(
                    "delegation proposal",
                    _delegation_state,
                    timeout_seconds=180,
                )
                if delegation_state.get("status") != "proposed":
                    raise HarnessError(
                        "delegation did not reach proposal state: "
                        f"{delegation_state.get('detail', delegation_state.get('status', 'unknown'))}"
                    )
                proposed_tasks = delegation_state.get("event", {}).get("metadata", {}).get("tasks", [])
                if not proposed_tasks:
                    raise HarnessError("delegation proposal did not include tasks metadata")

                approve_delegation = client.post(
                    f"/v1/conversations/{delegation_conversation_id}/actions",
                    headers={
                        "Content-Type": "application/json",
                        "X-CSRF-Token": csrf_token,
                    },
                    json={"action": "approve_delegation", "payload": {}},
                )
                approve_delegation.raise_for_status()

            def _delegated_task_created() -> dict[str, Any] | None:
                response = client.get("/v1/tasks", params={"limit": 50})
                response.raise_for_status()
                payload = response.json()
                for task in payload.get("tasks", []):
                    if str(task.get("parent_conversation_id", "")) == delegation_conversation_id:
                        return task
                return None

            delegated_task = _poll(
                "delegated task creation",
                _delegated_task_created,
                timeout_seconds=120,
            )
            delegated_task_id = str(delegated_task.get("routed_task_id", ""))
            if not delegated_task_id:
                raise HarnessError("delegated task creation returned no routed_task_id")

            def _delegated_task_completed() -> dict[str, Any] | None:
                task = _delegated_task_created()
                if task and str(task.get("status", "")) == "completed":
                    return task
                return None

            delegated_task = _poll(
                "delegated task completion",
                _delegated_task_completed,
                timeout_seconds=180,
            )

            def _delegation_submitted() -> bool:
                return any(event.get("kind") == "delegation.submitted" for event in _delegation_events())

            _poll("delegation submitted event", _delegation_submitted, timeout_seconds=60)

            def _delegation_completed() -> bool:
                return any(event.get("kind") == "delegation.completed" for event in _delegation_events())

            _poll("delegation completed event", _delegation_completed, timeout_seconds=120)

            def _delegation_final_reply() -> bool:
                return any(
                    event.get("kind") == "message.bot"
                    and delegation_secret == str(event.get("content", "")).strip()
                    for event in _delegation_events()
                )

            _poll("delegation final reply", _delegation_final_reply, timeout_seconds=180)

            parent_title = f"E2E routed task parent {int(time.time())}"
            parent_prompt = "Track this delegated task in the registry timeline."
            parent_create = client.post(
                "/v1/conversations",
                headers={
                    "Content-Type": "application/json",
                    "X-CSRF-Token": csrf_token,
                },
                json={
                    "target_agent_id": primary_state.agent_id,
                    "origin_channel": "registry",
                    "external_conversation_ref": f"e2e-parent-{int(time.time())}",
                    "title": parent_title,
                },
            )
            parent_create.raise_for_status()
            parent_conversation_id = parent_create.json()["conversation_id"]
            parent_message = client.post(
                f"/v1/conversations/{parent_conversation_id}/messages",
                headers={
                    "Content-Type": "application/json",
                    "X-CSRF-Token": csrf_token,
                },
                json={"text": parent_prompt},
            )
            parent_message.raise_for_status()

            routed_task_title = f"E2E routed task {int(time.time())}"
            routed_task_id = f"e2e-routed-{int(time.time())}"
            origin_client = RegistryClient(base_url, agent_token=primary_state.agent_token)
            asyncio.run(
                origin_client.submit_routed_task(
                    RoutedTaskRequest(
                        routed_task_id=routed_task_id,
                        parent_conversation_id=parent_conversation_id,
                        origin_agent_id=primary_state.agent_id,
                        target_agent_id=secondary_state.agent_id,
                        title=routed_task_title,
                        instructions="Return only the number 4.",
                    )
                )
            )

            def _task_completed() -> bool:
                response = client.get("/v1/tasks", params={"limit": 20})
                response.raise_for_status()
                payload = response.json()
                for task in payload.get("tasks", []):
                    if task.get("routed_task_id") == routed_task_id:
                        return task.get("status") == "completed" and str(task.get("summary", "")).strip() == "4"
                return False

            _poll("routed task completion", _task_completed, timeout_seconds=120)

            def _mirrored_events() -> bool:
                response = client.get(
                    f"/v1/conversations/{parent_conversation_id}/events",
                    params={"limit": 100},
                )
                response.raise_for_status()
                events = response.json().get("events", [])
                statuses = [
                    str(event.get("metadata", {}).get("status", ""))
                    for event in events
                    if event.get("kind") == "task.status"
                ]
                return "queued" in statuses and "completed" in statuses

            _poll("mirrored routed task events", _mirrored_events, timeout_seconds=30)

            context = {
                "base_url": base_url,
                "ui_url": stack.ui_url,
                "ui_token": stack.ui_token,
                "primary_label": primary_state.display_name,
                "secondary_label": secondary_state.display_name,
                "primary_agent_id": primary_state.agent_id,
                "secondary_agent_id": secondary_state.agent_id,
                "primary_agent_token": primary_state.agent_token,
                "secondary_agent_token": secondary_state.agent_token,
                "basic_conversation_title": basic_title,
                "delegation_conversation_id": delegation_conversation_id,
                "delegated_task_id": delegated_task_id,
                "parent_conversation_id": parent_conversation_id,
                "parent_prompt": parent_prompt,
                "existing_task_title": routed_task_title,
                "routed_task_id": routed_task_id,
            }
            (self.artifacts_dir / "smoke-context.json").write_text(json.dumps(context, indent=2), encoding="utf-8")
            return context

    def run_playwright(self, context: dict[str, str]) -> None:
        env = {
            "E2E_BASE_URL": context["base_url"],
            "E2E_UI_TOKEN": context["ui_token"],
            "E2E_PRIMARY_LABEL": context["primary_label"],
            "E2E_SECONDARY_LABEL": context["secondary_label"],
            "E2E_PARENT_CONVERSATION_ID": context["parent_conversation_id"],
            "E2E_PARENT_PROMPT": context["parent_prompt"],
            "E2E_EXISTING_TASK_TITLE": context["existing_task_title"],
            "E2E_BASIC_CONVERSATION_TITLE": context["basic_conversation_title"],
            "E2E_ORIGIN_TOKEN": context["primary_agent_token"],
            "E2E_TARGET_TOKEN": context["secondary_agent_token"],
            "E2E_ORIGIN_AGENT_ID": context["primary_agent_id"],
            "E2E_TARGET_AGENT_ID": context["secondary_agent_id"],
            "E2E_PLAYWRIGHT_OUTPUT_DIR": str(self.artifacts_dir / "playwright-output"),
        }
        result = subprocess.run(
            [
                "npx",
                "playwright",
                "test",
                PLAYWRIGHT_SPEC.name,
                "--config",
                PLAYWRIGHT_CONFIG.name,
                "--browser",
                "chromium",
            ],
            cwd=PLAYWRIGHT_DIR,
            env=build_subprocess_env(extra_env=env),
            text=True,
            capture_output=True,
            check=False,
            timeout=120,
        )
        (self.artifacts_dir / "playwright.stdout.log").write_text(result.stdout or "", encoding="utf-8")
        (self.artifacts_dir / "playwright.stderr.log").write_text(result.stderr or "", encoding="utf-8")
        if result.returncode != 0:
            raise HarnessError(
                "Playwright smoke failed. "
                f"See {(self.artifacts_dir / 'playwright.stdout.log')} and {(self.artifacts_dir / 'playwright.stderr.log')}"
            )

    def run(self) -> int:
        self.temp_root.mkdir(parents=True, exist_ok=True)
        source_snapshot = (
            self.capture_stack_state(self.source_repo)
            if self.source_repo is not None
            else StackState(registry_running=False, running_bots=[])
        )
        self.snapshot_source_deploy()
        fresh_run_id = str(int(time.time()))
        self.fresh_stack = FreshStack(
            self.repo_dir,
            self.snapshot_deploy,
            self.artifacts_dir,
            fresh_run_id,
        )
        _print(f"Snapshot copied to {self.snapshot_deploy}")
        _print(f"Artifacts will be written to {self.artifacts_dir}")
        try:
            if self.source_repo is not None:
                self.stop_stack(self.source_repo, source_snapshot)
            self.fresh_stack.build_images()
            self.fresh_stack.start()
            context = self.run_operator_smoke()
            if not self.skip_playwright:
                self.run_playwright(context)
            _print("Live registry smoke passed.")
            return 0
        except Exception as exc:
            if self.fresh_stack is not None:
                self.fresh_stack.collect_logs()
            raise HarnessError(str(exc)) from exc
        finally:
            if self.fresh_stack is not None and not self.keep_fresh_stack:
                try:
                    self.fresh_stack.down()
                except Exception:  # pragma: no cover - best-effort cleanup
                    pass
            if self.source_repo is not None and not self.leave_source_stopped:
                try:
                    self.restore_stack(self.source_repo, source_snapshot)
                except Exception as exc:  # pragma: no cover - best-effort restore with clear stderr
                    _print(f"WARNING: failed to restore source stack: {exc}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a fresh live registry smoke against a copied octopus deployment")
    parser.add_argument("--source-repo", type=Path, default=DEFAULT_SOURCE_REPO)
    parser.add_argument("--snapshot-deploy", type=Path, default=None)
    parser.add_argument("--temp-root", type=Path, default=DEFAULT_TEMP_ROOT)
    parser.add_argument("--keep-fresh-stack", action="store_true")
    parser.add_argument("--leave-source-stopped", action="store_true")
    parser.add_argument("--skip-playwright", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_repo = args.source_repo.resolve() if args.snapshot_deploy is None else None
    snapshot_deploy = args.snapshot_deploy.resolve() if args.snapshot_deploy is not None else None
    harness = LiveRegistryHarness(
        repo_dir=REPO_ROOT,
        source_repo=source_repo,
        snapshot_deploy=snapshot_deploy,
        temp_root=args.temp_root.resolve(),
        keep_fresh_stack=args.keep_fresh_stack,
        leave_source_stopped=args.leave_source_stopped,
        skip_playwright=args.skip_playwright,
    )
    try:
        return harness.run()
    except HarnessError as exc:
        _print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
