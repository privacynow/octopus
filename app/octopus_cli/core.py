from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import OrderedDict, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.exact_aliases import collect_exact_aliases, matches_exact_alias
from app.provider_auth import ensure_auth_layout, has_auth_artifacts, shared_auth_root
from app.provider_health import health_detail
from app.octopus_cli.envfiles import (
    list_registry_connection_records,
    parse_env_file,
    upsert_env_value,
    write_env_file,
    write_registry_connection_records,
)
from app.octopus_cli.models import (
    Action,
    BotState,
    ExecutionPlan,
    ImageFreshness,
    ProviderAuthState,
    RegistryConnection,
    RegistryConnectionStatus,
    RegistryDeployOptions,
    RegistryState,
    ResolvedTarget,
    SystemState,
    TargetKind,
    Workspace,
)
from app.subprocess_env import build_subprocess_env


LOCAL_REGISTRY_INTERNAL_URL = "http://registry:8787"
DEFAULT_REGISTRY_PORT = 8787
MANAGED_IMAGE_KIND_LABEL = "org.octopus.image-kind"
MANAGED_IMAGE_FINGERPRINT_LABEL = "org.octopus.source-fingerprint"
MANAGED_IMAGE_PROVIDER_LABEL = "org.octopus.provider"


class OctopusError(RuntimeError):
    """User-facing operator error."""


@dataclass(slots=True)
class PromptIO:
    stdin: Any = sys.stdin
    stdout: Any = sys.stdout
    stderr: Any = sys.stderr

    def print(self, message: str = "") -> None:
        self.stdout.write(f"{message}\n")
        self.stdout.flush()

    def error(self, message: str = "") -> None:
        self.stderr.write(f"{message}\n")
        self.stderr.flush()

    def prompt(self, message: str) -> str:
        self.stdout.write(message)
        self.stdout.flush()
        value = self.stdin.readline()
        if value == "":
            raise EOFError()
        return value.rstrip("\n")

    @property
    def interactive(self) -> bool:
        try:
            return self.stdin.isatty() and self.stdout.isatty()
        except Exception:
            return False


def normalize_slug(value: str, *, fallback: str = "") -> str:
    normalized = re.sub(r"-{2,}", "-", re.sub(r"[^a-z0-9]+", "-", value.lower())).strip("-")[:32]
    if normalized:
        return normalized
    return fallback[:32]


def telegram_token_format_valid(value: str) -> bool:
    return bool(re.match(r"^[0-9]+:[A-Za-z0-9_-]+$", value or ""))


def telegram_token_is_placeholder(value: str) -> bool:
    normalized = (value or "").strip().lower()
    return normalized in {
        "",
        "123:fake",
        "fake",
        "fake-token",
        "changeme",
        "replace-me",
        "your-bot-token",
        "your-telegram-bot-token",
        "<telegram-bot-token>",
        "<botfather-token>",
    }


def validate_telegram_token(token: str) -> tuple[str, str, str]:
    url = f"https://api.telegram.org/bot{token}/getMe"
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read())
    except urllib.error.URLError as exc:
        raise OctopusError("Token was rejected by Telegram. Check with @BotFather that the token is correct.") from exc
    if not payload.get("ok"):
        raise OctopusError("Token was rejected by Telegram. Check with @BotFather that the token is correct.")
    result = payload["result"]
    telegram_id = str(result.get("id", "")).strip()
    username = str(result.get("username", "")).strip()
    display_name = str(result.get("first_name", "")).strip() or username
    if not telegram_id or not username:
        raise OctopusError("Telegram returned incomplete bot identity. Try again.")
    return telegram_id, username, display_name


def provider_auth_base_dir(repo_dir: Path, provider: str) -> Path:
    return repo_dir / ".deploy" / "provider-auth" / provider


def provider_has_auth_files(repo_dir: Path, provider: str) -> bool:
    return has_auth_artifacts(
        provider,
        shared_auth_root(provider, provider_auth_base_dir(repo_dir, provider)),
    )


def ensure_provider_auth_dir(repo_dir: Path, provider: str) -> Path:
    auth_dir = provider_auth_base_dir(repo_dir, provider)
    auth_dir.mkdir(parents=True, exist_ok=True)
    auth_dir.chmod(0o700)
    ensure_auth_layout(provider, shared_auth_root(provider, auth_dir))
    return auth_dir


def prompt_with_default(io: PromptIO, label: str, default: str = "") -> str:
    if default:
        response = io.prompt(f"{label} [{default}]: ")
        return response or default
    return io.prompt(f"{label}: ")


def pick_available_port(start: int = DEFAULT_REGISTRY_PORT) -> int:
    return pick_available_port_for_host("127.0.0.1", start=start)


def pick_available_port_for_host(host: str, start: int = DEFAULT_REGISTRY_PORT) -> int:
    port = start
    while True:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, port))
            except OSError:
                port += 1
                continue
        return port


def _is_loopback_host(host: str) -> bool:
    return host.strip().lower() in {"127.0.0.1", "localhost", "::1"}


def _normalize_bind_host(host: str) -> str:
    value = (host or "").strip()
    if not value:
        return "127.0.0.1"
    if value.lower() == "localhost":
        return "127.0.0.1"
    if value == "0.0.0.0":
        return value
    try:
        ipaddress.ip_address(value)
    except ValueError as exc:
        raise OctopusError("Registry bind host must be localhost, 0.0.0.0, or a concrete IP address.") from exc
    return value


def _parse_registry_url(raw: str) -> tuple[str, str]:
    parsed = urlparse((raw or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise OctopusError("Registry URL must be a valid http:// or https:// URL.")
    host = (parsed.hostname or "").strip()
    if not host:
        raise OctopusError("Registry URL must include a host.")
    if host == "0.0.0.0":
        raise OctopusError("0.0.0.0 is a listen address, not a usable registry URL.")
    return parsed.geturl().rstrip("/"), host


class DockerRunner:
    def __init__(self, repo_dir: Path) -> None:
        self.repo_dir = repo_dir

    def run(
        self,
        args: list[str],
        *,
        env: dict[str, str] | None = None,
        capture_output: bool = True,
        check: bool = True,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            args,
            cwd=self.repo_dir,
            env=build_subprocess_env(extra_env=env),
            text=True,
            input=input_text,
            capture_output=capture_output,
            check=check,
        )

    def ensure_network(self) -> None:
        inspect = self.run(["docker", "network", "inspect", "octopus-net"], check=False)
        if inspect.returncode == 0:
            return
        stderr = (inspect.stderr or "").lower()
        if "permission denied" in stderr or "cannot connect" in stderr:
            return
        self.run(["docker", "network", "create", "octopus-net"], capture_output=False)

    def docker_status_for_slug(self, slug: str) -> str:
        result = self.run(
            [
                "docker",
                "ps",
                "-a",
                "--filter",
                f"label=com.docker.compose.project=octopus-{slug}",
                "--filter",
                "label=com.docker.compose.service=bot",
                "--format",
                "{{.Status}}",
            ],
            check=False,
        )
        return result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""

    def image_exists(self, image: str) -> bool:
        result = self.run(["docker", "image", "inspect", image], check=False)
        return result.returncode == 0

    def image_labels(self, image: str) -> dict[str, str]:
        result = self.run(
            ["docker", "image", "inspect", image, "--format", "{{json .Config.Labels}}"],
            check=False,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return {}
        try:
            raw = json.loads(result.stdout.strip())
        except json.JSONDecodeError:
            return {}
        if isinstance(raw, dict):
            return {str(key): str(value) for key, value in raw.items()}
        return {}

    def ensure_provider_auth_dir(self, provider: str) -> Path:
        return ensure_provider_auth_dir(self.repo_dir, provider)

    def bot_compose_command(self, slug: str, *args: str, shared: bool = False) -> tuple[list[str], dict[str, str]]:
        env_file = self.repo_dir / ".deploy" / "bots" / slug / ".env"
        values = parse_env_file(env_file)
        provider = values.get("BOT_PROVIDER", "claude")
        provider_auth_dir = str(self.ensure_provider_auth_dir(provider))
        command = [
            "docker",
            "compose",
            "--project-directory",
            ".",
            "-p",
            f"octopus-{slug}",
            "-f",
            "infra/compose/docker-compose.yml",
        ]
        if shared:
            command += ["-f", "infra/compose/docker-compose.shared.yml"]
            workspace_compose = self.repo_dir / ".deploy" / "bots" / slug / "docker-compose.workspace-shared.yml"
        else:
            workspace_compose = self.repo_dir / ".deploy" / "bots" / slug / "docker-compose.workspace.yml"
        if workspace_compose.exists():
            command += ["-f", str(workspace_compose.relative_to(self.repo_dir))]
        if not shared:
            command += ["--profile", "bot"]
        command += ["--env-file", str(env_file.relative_to(self.repo_dir)), *args]
        env = {
            "OCTOPUS_NETWORK": "octopus-net",
            "PROVIDER_AUTH_DIR": provider_auth_dir,
            "BOT_ENV_FILE": str(env_file.relative_to(self.repo_dir)),
            "REGISTRY_ENROLL_TOKEN": os.environ.get("REGISTRY_ENROLL_TOKEN", "placeholder-registry-enroll"),
            "REGISTRY_UI_TOKEN": os.environ.get("REGISTRY_UI_TOKEN", "placeholder-registry-ui"),
        }
        return command, env

    def provider_compose_command(self, provider: str, *args: str) -> tuple[list[str], dict[str, str]]:
        auth_dir = str(self.ensure_provider_auth_dir(provider))
        command = [
            "docker",
            "compose",
            "--project-directory",
            ".",
            "-p",
            f"octopus-auth-{provider}",
            "-f",
            "infra/compose/docker-compose.yml",
            "--profile",
            "bot",
            *args,
        ]
        env = {
            "OCTOPUS_NETWORK": "octopus-net",
            "BOT_PROVIDER": provider,
            "PROVIDER_AUTH_DIR": auth_dir,
            "BOT_ENV_FILE": "/dev/null",
            "REGISTRY_ENROLL_TOKEN": os.environ.get("REGISTRY_ENROLL_TOKEN", "placeholder-registry-enroll"),
            "REGISTRY_UI_TOKEN": os.environ.get("REGISTRY_UI_TOKEN", "placeholder-registry-ui"),
        }
        return command, env

    def registry_compose_command(self, *args: str) -> tuple[list[str], dict[str, str]]:
        command = [
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
            *args,
        ]
        env = {"OCTOPUS_NETWORK": "octopus-net"}
        return command, env

    def bot_compose(self, slug: str, *args: str, capture_output: bool = True, check: bool = True) -> subprocess.CompletedProcess[str]:
        self.ensure_network()
        command, env = self.bot_compose_command(slug, *args)
        return self.run(command, env=env, capture_output=capture_output, check=check)

    def provider_compose(self, provider: str, *args: str, capture_output: bool = True, check: bool = True) -> subprocess.CompletedProcess[str]:
        self.ensure_network()
        command, env = self.provider_compose_command(provider, *args)
        return self.run(command, env=env, capture_output=capture_output, check=check)

    def registry_compose(self, *args: str, capture_output: bool = True, check: bool = True) -> subprocess.CompletedProcess[str]:
        self.ensure_network()
        command, env = self.registry_compose_command(*args)
        return self.run(command, env=env, capture_output=capture_output, check=check)


class OctopusManager:
    def __init__(self, repo_dir: Path, *, io: PromptIO | None = None, docker: DockerRunner | None = None) -> None:
        self.repo_dir = repo_dir
        self.io = io or PromptIO()
        self.docker = docker or DockerRunner(repo_dir)

    @property
    def deploy_dir(self) -> Path:
        return self.repo_dir / ".deploy"

    def ensure_deploy_dirs(self) -> None:
        for relative in ("bots", "registry", "provider-auth", "workspaces", "logs"):
            (self.deploy_dir / relative).mkdir(parents=True, exist_ok=True)

    def bot_env_file(self, slug: str) -> Path:
        return self.deploy_dir / "bots" / slug / ".env"

    def registry_env_file(self) -> Path:
        return self.deploy_dir / "registry" / ".env"

    def workspace_conf_file(self, slug: str) -> Path:
        return self.deploy_dir / "workspaces" / slug / "workspace.conf"

    def workspace_members_file(self, slug: str) -> Path:
        return self.deploy_dir / "workspaces" / slug / "members.txt"

    def list_bot_slugs(self) -> list[str]:
        bots_dir = self.deploy_dir / "bots"
        if not bots_dir.exists():
            return []
        return sorted(path.name for path in bots_dir.iterdir() if (path / ".env").exists())

    def count_bots(self) -> int:
        return len(self.list_bot_slugs())

    def list_workspace_slugs(self) -> list[str]:
        ws_dir = self.deploy_dir / "workspaces"
        if not ws_dir.exists():
            return []
        return sorted(path.name for path in ws_dir.iterdir() if (path / "workspace.conf").exists())

    def has_local_registry(self) -> bool:
        return self.registry_env_file().exists()

    def _registry_bind_host(self, values: OrderedDict[str, str] | None = None) -> str:
        current = values if values is not None else parse_env_file(self.registry_env_file())
        return _normalize_bind_host(current.get("REGISTRY_BIND_HOST", "127.0.0.1"))

    def _registry_port(self, values: OrderedDict[str, str] | None = None) -> int:
        current = values if values is not None else parse_env_file(self.registry_env_file())
        raw = current.get("REGISTRY_PORT", str(DEFAULT_REGISTRY_PORT)) or str(DEFAULT_REGISTRY_PORT)
        try:
            port = int(raw)
        except ValueError as exc:
            raise OctopusError(f"Invalid REGISTRY_PORT value: {raw!r}") from exc
        if port <= 0 or port > 65535:
            raise OctopusError(f"Registry port must be between 1 and 65535, got {port}.")
        return port

    def _registry_host_base_url(self, values: OrderedDict[str, str] | None = None) -> str:
        current = values if values is not None else parse_env_file(self.registry_env_file())
        bind_host = self._registry_bind_host(current)
        port = self._registry_port(current)
        if bind_host == "0.0.0.0" or _is_loopback_host(bind_host):
            host = "127.0.0.1"
        else:
            host = bind_host
        return f"http://{host}:{port}"

    def _default_registry_public_url(self, bind_host: str, port: int) -> str:
        if bind_host == "0.0.0.0":
            raise OctopusError("A public registry URL is required when binding the registry to 0.0.0.0.")
        host = "127.0.0.1" if _is_loopback_host(bind_host) else bind_host
        return f"http://{host}:{port}"

    def _registry_public_url(self, values: OrderedDict[str, str] | None = None) -> str:
        current = values if values is not None else parse_env_file(self.registry_env_file())
        configured = str(current.get("REGISTRY_PUBLIC_URL", "") or "").strip()
        if configured:
            return _parse_registry_url(configured)[0]
        return self._default_registry_public_url(
            self._registry_bind_host(current),
            self._registry_port(current),
        )

    def registry_ui_url(self) -> str:
        return f"{self._registry_public_url().rstrip('/')}/ui"

    def local_registry_public_base_url(self) -> str:
        return self._registry_public_url()

    def local_registry_host_base_url(self) -> str:
        return self._registry_host_base_url()

    def _registry_state_from_values(
        self,
        values: OrderedDict[str, str] | None,
        *,
        configured: bool,
        running: bool,
    ) -> RegistryState:
        current = values if values is not None else OrderedDict()
        bind_host = self._registry_bind_host(current)
        port = self._registry_port(current)
        host_base_url = self._registry_host_base_url(current)
        public_url = self._registry_public_url(current)
        return RegistryState(
            configured=configured,
            running=running,
            env_file=self.registry_env_file(),
            bind_host=bind_host,
            port=port,
            public_url=public_url,
            host_base_url=host_base_url,
            ui_url=f"{public_url.rstrip('/')}/ui",
            enroll_token=current.get("REGISTRY_ENROLL_TOKEN", ""),
            ui_token=current.get("REGISTRY_UI_TOKEN", ""),
        )

    def _validated_registry_deploy_values(
        self,
        deploy: RegistryDeployOptions | None = None,
        *,
        existing: OrderedDict[str, str] | None = None,
        creating: bool = False,
    ) -> OrderedDict[str, str]:
        current = OrderedDict(existing or parse_env_file(self.registry_env_file()))
        deploy = deploy or RegistryDeployOptions()
        bind_host = _normalize_bind_host(deploy.bind_host or current.get("REGISTRY_BIND_HOST", "127.0.0.1"))
        explicit_port = deploy.port is not None
        if explicit_port:
            port = int(deploy.port)
        elif creating and not deploy.bind_host and "REGISTRY_PORT" not in current:
            port = pick_available_port_for_host("127.0.0.1", start=DEFAULT_REGISTRY_PORT)
        else:
            port = self._registry_port(current)
        if port <= 0 or port > 65535:
            raise OctopusError(f"Registry port must be between 1 and 65535, got {port}.")
        raw_public = str(deploy.public_url or current.get("REGISTRY_PUBLIC_URL", "") or "").strip()
        if raw_public:
            public_url, _ = _parse_registry_url(raw_public)
        else:
            public_url = self._default_registry_public_url(bind_host, port)
        current["REGISTRY_BIND_HOST"] = bind_host
        current["REGISTRY_PORT"] = str(port)
        current["REGISTRY_PUBLIC_URL"] = public_url
        return current

    def _replace_registry_record(
        self,
        records: list[RegistryConnection],
        connection: RegistryConnection,
        *,
        previous_id: str | None = None,
    ) -> list[RegistryConnection]:
        updated: list[RegistryConnection] = []
        replaced = False
        for record in records:
            if previous_id and record.registry_id == previous_id:
                if not replaced:
                    updated.append(connection)
                    replaced = True
                continue
            if record.registry_id == connection.registry_id:
                if not replaced:
                    updated.append(connection)
                    replaced = True
                continue
            updated.append(record)
        if not replaced:
            updated.append(connection)
        return updated

    def registry_is_running(self) -> bool:
        result = self.docker.run(
            ["docker", "compose", "-p", "octopus-registry", "ps", "--status", "running", "service"],
            check=False,
        )
        return "service" in result.stdout

    def bot_is_running(self, slug: str) -> bool:
        return bool(self.docker.docker_status_for_slug(slug).startswith("Up"))

    def bot_values(self, slug: str) -> OrderedDict[str, str]:
        return parse_env_file(self.bot_env_file(slug))

    def bot_registry_connections(self, slug: str) -> list[RegistryConnection]:
        return list_registry_connection_records(self.bot_env_file(slug))

    def bot_local_registry_connection(self, slug: str) -> RegistryConnection | None:
        for record in self.bot_registry_connections(slug):
            if record.url == LOCAL_REGISTRY_INTERNAL_URL:
                return record
        return None

    def bot_registry_connection_by_id(self, slug: str, registry_id: str) -> RegistryConnection | None:
        for record in self.bot_registry_connections(slug):
            if record.registry_id == registry_id:
                return record
        return None

    def bot_registry_connection_state(self, slug: str, connection: RegistryConnection) -> str:
        if not connection.url and not connection.enrollment_token:
            return "none"
        if self.bot_registry_has_identity(slug, connection.registry_id):
            return "enrolled"
        return "configured"

    def bot_registry_live_state(self, slug: str, connection: RegistryConnection) -> str:
        connection_state = self.bot_registry_connection_state(slug, connection)
        if connection_state == "configured":
            return "enrollment failed"
        if not self.bot_is_running(slug):
            return "stopped"
        state = self.read_bot_registry_state(slug, connection.registry_id)
        return state.get("connectivity_state", "starting")

    def bot_registry_connection_statuses(self, slug: str) -> list[RegistryConnectionStatus]:
        statuses: list[RegistryConnectionStatus] = []
        for connection in self.bot_registry_connections(slug):
            statuses.append(
                RegistryConnectionStatus(
                    registry_id=connection.registry_id,
                    url=connection.url,
                    scope=connection.scope,
                    connection_state=self.bot_registry_connection_state(slug, connection),
                    live_state=self.bot_registry_live_state(slug, connection),
                    local=connection.url == LOCAL_REGISTRY_INTERNAL_URL,
                )
            )
        return statuses

    def workspace_memberships(self, slug: str) -> list[str]:
        memberships: list[str] = []
        for ws_slug in self.list_workspace_slugs():
            members = self.workspace_members(ws_slug)
            if slug in members:
                memberships.append(ws_slug)
        return memberships

    def workspace_members(self, ws_slug: str) -> list[str]:
        members_file = self.workspace_members_file(ws_slug)
        if not members_file.exists():
            return []
        return [line.strip() for line in members_file.read_text(encoding="utf-8").splitlines() if line.strip()]

    def workspace_root(self, ws_slug: str) -> Path:
        values = parse_env_file(self.workspace_conf_file(ws_slug))
        return Path(values.get("WORKSPACE_ROOT", ""))

    def workspace_mount(self, ws_slug: str) -> str:
        values = parse_env_file(self.workspace_conf_file(ws_slug))
        return values.get("WORKSPACE_MOUNT", f"/workspace/{ws_slug}")

    def workspace_mode(self, ws_slug: str) -> str:
        values = parse_env_file(self.workspace_conf_file(ws_slug))
        return values.get("WORKSPACE_MODE", "rw") or "rw"

    def compute_fingerprint(self, *, kind: str, provider: str = "") -> str:
        if kind == "provider-bot":
            paths = [
                Path("requirements.txt"),
                Path("infra/docker/Dockerfile.bot"),
                Path("app"),
                Path("octopus_sdk"),
                Path("skills"),
                Path("scripts"),
            ]
            seed = f"{kind}:{provider}".encode("utf-8")
        else:
            paths = [
                Path("requirements.txt"),
                Path("infra/docker/Dockerfile.registry"),
                Path("octopus_registry"),
                Path("octopus_sdk"),
            ]
            seed = f"{kind}:registry".encode("utf-8")
        digest = hashlib.sha256(seed)
        for rel_path in sorted(paths):
            absolute = self.repo_dir / rel_path
            if absolute.is_dir():
                for child in sorted(path for path in absolute.rglob("*") if path.is_file()):
                    digest.update(str(child.relative_to(self.repo_dir)).encode("utf-8"))
                    digest.update(child.read_bytes())
            elif absolute.exists():
                digest.update(str(rel_path).encode("utf-8"))
                digest.update(absolute.read_bytes())
        return digest.hexdigest()

    def image_freshness(self) -> dict[str, ImageFreshness]:
        freshness: dict[str, ImageFreshness] = {}
        providers = {self.bot_values(slug).get("BOT_PROVIDER", "claude") for slug in self.list_bot_slugs()}
        if not providers:
            providers = {"claude", "codex"}
        for provider in sorted(providers):
            image = f"octopus-agent:{provider}"
            labels = self.docker.image_labels(image)
            freshness[f"bot:{provider}"] = ImageFreshness(
                image=image,
                fingerprint=self.compute_fingerprint(kind="provider-bot", provider=provider),
                image_exists=self.docker.image_exists(image),
                image_fingerprint=labels.get(MANAGED_IMAGE_FINGERPRINT_LABEL, ""),
            )
        registry_image = "octopus-registry-service:latest"
        labels = self.docker.image_labels(registry_image)
        freshness["registry"] = ImageFreshness(
            image=registry_image,
            fingerprint=self.compute_fingerprint(kind="registry-service"),
            image_exists=self.docker.image_exists(registry_image),
            image_fingerprint=labels.get(MANAGED_IMAGE_FINGERPRINT_LABEL, ""),
        )
        return freshness

    def read_bot_registry_state(self, slug: str, registry_id: str) -> dict[str, str]:
        script = (
            "from pathlib import Path\n"
            "import json, os\n"
            "data_dir = Path(os.environ.get('BOT_DATA_DIR', '/home/bot/data')) / 'agent' / 'registries'\n"
            "path = data_dir / f\"{os.environ.get('OCTOPUS_REGISTRY_ID','')}.json\"\n"
            "if not path.exists():\n"
            "    raise SystemExit(2)\n"
            "print(path.read_text())\n"
        )
        try:
            result = self.docker.bot_compose(
                slug,
                "exec",
                "-T",
                "-e",
                f"OCTOPUS_REGISTRY_ID={registry_id}",
                "bot",
                "python",
                "-c",
                script,
                check=False,
            )
        except subprocess.SubprocessError:
            return {}
        if result.returncode != 0 or not result.stdout.strip():
            return {}
        try:
            raw = json.loads(result.stdout.strip())
        except json.JSONDecodeError:
            return {}
        return {str(key): str(value) for key, value in raw.items()}

    def read_bot_execution_state(self, slug: str) -> dict[str, object]:
        script = (
            "from pathlib import Path\n"
            "import json, os\n"
            "path = Path(os.environ.get('BOT_DATA_DIR', '/home/bot/data')) / 'agent' / 'execution-state.json'\n"
            "if not path.exists():\n"
            "    print(json.dumps({'state': 'healthy', 'provider': '', 'fault_kind': '', 'fault_code': '', 'detail': '', 'faulted_at': '', 'resettable': False, 'last_returncode': None}))\n"
            "    raise SystemExit(0)\n"
            "print(path.read_text())\n"
        )
        if not self.bot_is_running(slug):
            return {"state": "unknown"}
        try:
            result = self.docker.bot_compose(
                slug,
                "exec",
                "-T",
                "bot",
                "python",
                "-c",
                script,
                check=False,
            )
        except subprocess.SubprocessError:
            return {"state": "unknown"}
        if result.returncode != 0 or not result.stdout.strip():
            return {"state": "unknown"}
        try:
            raw = json.loads(result.stdout.strip())
        except json.JSONDecodeError:
            return {"state": "unknown"}
        if not isinstance(raw, dict):
            return {"state": "unknown"}
        return raw

    def clear_bot_registry_state(self, slug: str, registry_ids: list[str] | None = None) -> None:
        ids = registry_ids or []
        script = (
            "from pathlib import Path\n"
            "import os\n"
            "data_dir = Path(os.environ.get('BOT_DATA_DIR', '/home/bot/data')) / 'agent' / 'registries'\n"
            "registry_ids = [item for item in os.environ.get('OCTOPUS_CLEAR_REGISTRY_IDS','').split() if item]\n"
            "if not registry_ids:\n"
            "    if data_dir.exists():\n"
            "        for path in data_dir.glob('*.json'):\n"
            "            path.unlink(missing_ok=True)\n"
            "else:\n"
            "    for registry_id in registry_ids:\n"
            "        (data_dir / f'{registry_id}.json').unlink(missing_ok=True)\n"
        )
        try:
            self.docker.bot_compose(
                slug,
                "run",
                "--rm",
                "-e",
                f"OCTOPUS_CLEAR_REGISTRY_IDS={' '.join(ids)}",
                "bot-provider",
                "python",
                "-c",
                script,
                capture_output=False,
                check=False,
            )
        except subprocess.SubprocessError:
            return

    def bot_registry_has_identity(self, slug: str, registry_id: str) -> bool:
        state = self.read_bot_registry_state(slug, registry_id)
        return bool(state.get("agent_id") and state.get("agent_token"))

    def bot_local_registry_connection_state(self, slug: str) -> str:
        connection = self.bot_local_registry_connection(slug)
        if connection is None:
            return "none"
        return self.bot_registry_connection_state(slug, connection)

    def bot_local_registry_live_state(self, slug: str) -> str:
        connection = self.bot_local_registry_connection(slug)
        if connection is None:
            return "none"
        return self.bot_registry_live_state(slug, connection)

    def inspect_state(self) -> SystemState:
        self.ensure_deploy_dirs()
        bots: list[BotState] = []
        for slug in self.list_bot_slugs():
            values = self.bot_values(slug)
            execution_state = self.read_bot_execution_state(slug)
            bots.append(
                BotState(
                    slug=slug,
                    display_name=values.get("BOT_DISPLAY_NAME", slug),
                    telegram_username=values.get("BOT_TELEGRAM_USERNAME", ""),
                    telegram_id=values.get("BOT_TELEGRAM_ID", ""),
                    provider=values.get("BOT_PROVIDER", "claude"),
                    mode=values.get("BOT_AGENT_MODE", "standalone") or "standalone",
                    env_file=self.bot_env_file(slug),
                    running=self.bot_is_running(slug),
                    docker_status=self.docker.docker_status_for_slug(slug),
                    role=values.get("BOT_ROLE", ""),
                    tags=values.get("BOT_AGENT_TAGS", ""),
                    registry_connections=self.bot_registry_connections(slug),
                    registry_connection_statuses=self.bot_registry_connection_statuses(slug),
                    local_registry_connection_state=self.bot_local_registry_connection_state(slug),
                    local_registry_live_state=self.bot_local_registry_live_state(slug),
                    execution_state=str(execution_state.get("state", "unknown") or "unknown"),
                    execution_provider=str(execution_state.get("provider", "") or ""),
                    execution_fault_kind=str(execution_state.get("fault_kind", "") or ""),
                    execution_fault_code=str(execution_state.get("fault_code", "") or ""),
                    execution_fault_detail=str(execution_state.get("detail", "") or ""),
                    execution_faulted_at=str(execution_state.get("faulted_at", "") or ""),
                    execution_resettable=bool(execution_state.get("resettable", False)),
                    execution_last_returncode=(
                        None
                        if execution_state.get("last_returncode") in (None, "")
                        else int(execution_state.get("last_returncode", 0))
                    ),
                    workspace_memberships=self.workspace_memberships(slug),
                )
            )
        registry_values = parse_env_file(self.registry_env_file())
        registry = self._registry_state_from_values(
            registry_values,
            configured=self.has_local_registry(),
            running=self.registry_is_running() if self.has_local_registry() else False,
        )
        workspaces = [
            Workspace(
                slug=ws_slug,
                root=self.workspace_root(ws_slug),
                mount=self.workspace_mount(ws_slug),
                mode=self.workspace_mode(ws_slug),
                members=self.workspace_members(ws_slug),
            )
            for ws_slug in self.list_workspace_slugs()
        ]
        providers = {bot.provider for bot in bots} or {"claude", "codex"}
        provider_auth = self.provider_auth_states(sorted(providers))
        return SystemState(
            repo_dir=self.repo_dir,
            bots=bots,
            registry=registry,
            workspaces=workspaces,
            provider_auth=provider_auth,
            freshness=self.image_freshness(),
        )

    def provider_auth_states(self, providers: list[str], *, live: bool = False) -> list[ProviderAuthState]:
        return [self.provider_auth_state(provider, live=live) for provider in sorted(set(providers))]

    def provider_auth_state(self, provider: str, *, live: bool = False) -> ProviderAuthState:
        configured = provider_has_auth_files(self.repo_dir, provider)
        state = ProviderAuthState(provider=provider, configured=configured)
        if not configured or not live:
            return state
        healthy, output = self.provider_live_health_output(provider, build_if_stale=False)
        state.detail = health_detail(output)
        if healthy is None:
            return state
        state.live_checked = True
        state.healthy = healthy
        return state

    def bot_aliases(self, bot: BotState) -> set[str]:
        return collect_exact_aliases(
            slug=bot.slug,
            display_name=bot.display_name,
            aliases=(bot.telegram_username,),
        )

    def resolve_bot(self, selector: str, state: SystemState) -> BotState:
        selector = selector.strip()
        alias_matches = [
            bot
            for bot in state.bots
            if matches_exact_alias(
                selector,
                slug=bot.slug,
                display_name=bot.display_name,
                aliases=(bot.telegram_username,),
            )
        ]
        if len(alias_matches) == 1:
            return alias_matches[0]
        if not alias_matches:
            raise OctopusError(f"No bot matches '{selector.strip().lower()}'.")
        labels = ", ".join(bot.label for bot in alias_matches)
        raise OctopusError(f"'{selector.strip().lower()}' is ambiguous. Candidates: {labels}")

    def resolve_targets(self, selectors: list[str], action: Action, state: SystemState) -> list[ResolvedTarget]:
        if not selectors:
            if action in {Action.START, Action.STOP, Action.RESTART, Action.REDEPLOY}:
                targets: list[ResolvedTarget] = []
                if state.registry.configured:
                    targets.append(ResolvedTarget(TargetKind.REGISTRY, "registry", "registry"))
                targets.extend(ResolvedTarget(TargetKind.BOT, bot.slug, bot.label) for bot in state.bots)
                return targets
            if action == Action.CONNECT:
                return [
                    ResolvedTarget(TargetKind.BOT, bot.slug, bot.label)
                    for bot in state.bots
                    if bot.local_registry_live_state != "connected"
                ]
            if action == Action.DISCONNECT:
                return [
                    ResolvedTarget(TargetKind.BOT, bot.slug, bot.label)
                    for bot in state.bots
                    if bot.local_registry_connection_state != "none"
                ]
            raise OctopusError("This action requires a target.")
        resolved: list[ResolvedTarget] = []
        for selector in selectors:
            lowered = selector.strip().lower()
            if lowered == "registry":
                resolved.append(ResolvedTarget(TargetKind.REGISTRY, "registry", "registry"))
                continue
            if lowered == "bots":
                resolved.extend(ResolvedTarget(TargetKind.BOT, bot.slug, bot.label) for bot in state.bots)
                continue
            bot = self.resolve_bot(selector, state)
            resolved.append(ResolvedTarget(TargetKind.BOT, bot.slug, bot.label))
        deduped: list[ResolvedTarget] = []
        seen: set[tuple[TargetKind, str]] = set()
        for target in resolved:
            key = (target.kind, target.identifier)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(target)
        return deduped

    def plan_action(self, action: Action, targets: list[ResolvedTarget], state: SystemState) -> ExecutionPlan:
        rebuild_images: list[str] = []
        recreate_targets: list[str] = []
        restart_targets: list[str] = []
        notes: list[str] = []
        if action == Action.REDEPLOY:
            for target in targets:
                if target.kind == TargetKind.REGISTRY:
                    rebuild_images.append("octopus-registry-service:latest")
                    recreate_targets.append("registry")
                    notes.append("Registry data volume will be preserved.")
                else:
                    provider = next(bot.provider for bot in state.bots if bot.slug == target.identifier)
                    image = f"octopus-agent:{provider}"
                    if image not in rebuild_images:
                        rebuild_images.append(image)
                    recreate_targets.append(target.label)
                    notes.append(f"Bot state for {target.label} will be preserved.")
        elif action == Action.RESTART:
            restart_targets = [target.label for target in targets]
            for target in targets:
                if target.kind == TargetKind.REGISTRY:
                    notes.append("Registry data volume will be preserved.")
                else:
                    notes.append(f"Bot state for {target.label} will be preserved.")
        elif action == Action.START:
            restart_targets = [target.label for target in targets]
        elif action == Action.STOP:
            restart_targets = [target.label for target in targets]
        elif action == Action.CONNECT:
            notes.append("Bots will be connected to the local registry.")
        elif action == Action.DISCONNECT:
            notes.append("Only the registry connection will be removed; bot data will be preserved.")
        return ExecutionPlan(
            action=action,
            targets=targets,
            rebuild_images=rebuild_images,
            recreate_targets=recreate_targets,
            restart_targets=restart_targets,
            notes=notes,
        )

    def print_plan(self, plan: ExecutionPlan) -> None:
        labels = ", ".join(target.label for target in plan.targets) or "(none)"
        self.io.print(f"Will {plan.action.value}: {labels}")
        if plan.rebuild_images:
            self.io.print(f"Will rebuild images: {', '.join(plan.rebuild_images)}")
        if plan.recreate_targets:
            self.io.print(f"Will recreate: {', '.join(plan.recreate_targets)}")
        if plan.restart_targets and plan.action in {Action.START, Action.STOP, Action.RESTART}:
            self.io.print(f"Will affect: {', '.join(plan.restart_targets)}")
        for note in plan.notes:
            self.io.print(note)

    def confirm_plan(self, plan: ExecutionPlan, *, yes: bool) -> None:
        self.print_plan(plan)
        if yes:
            return
        answer = self.io.prompt("Proceed? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            raise OctopusError("Cancelled.")

    def build_provider_image(self, provider: str) -> None:
        fingerprint = self.compute_fingerprint(kind="provider-bot", provider=provider)
        self.io.print(f"Building bot image for {provider}...")
        build_args = [
            "docker",
            "build",
            "-f",
            "infra/docker/Dockerfile.bot",
            "--build-arg",
            f"BOT_PROVIDER={provider}",
            "--build-arg",
            f"CLAUDE_INSTALL_METHOD={os.environ.get('CLAUDE_INSTALL_METHOD', 'npm')}",
            "--build-arg",
            f"CLAUDE_CLI_NPM_PACKAGE={os.environ.get('CLAUDE_CLI_NPM_PACKAGE', '@anthropic-ai/claude-code')}",
            "--build-arg",
            f"CLAUDE_INSTALL_URL={os.environ.get('CLAUDE_INSTALL_URL', 'https://claude.ai/install.sh')}",
            "--label",
            f"{MANAGED_IMAGE_KIND_LABEL}=provider-bot",
            "--label",
            f"{MANAGED_IMAGE_PROVIDER_LABEL}={provider}",
            "--label",
            f"{MANAGED_IMAGE_FINGERPRINT_LABEL}={fingerprint}",
            "-t",
            f"octopus-agent:{provider}",
            ".",
        ]
        log_path = self.deploy_dir / "logs" / f"docker-build-{provider}.log"
        self.ensure_deploy_dirs()
        result = self.docker.run(build_args, capture_output=True, check=False)
        log_path.write_text((result.stdout or "") + (result.stderr or ""), encoding="utf-8")
        if result.returncode != 0:
            raise OctopusError(f"Bot image build failed for provider '{provider}'. Full docker build log: {log_path}")

    def build_registry_image(self) -> None:
        fingerprint = self.compute_fingerprint(kind="registry-service")
        self.io.print("Building registry image...")
        log_path = self.deploy_dir / "logs" / "docker-build-registry.log"
        self.ensure_deploy_dirs()
        result = self.docker.run(
            [
                "docker",
                "build",
                "-f",
                "infra/docker/Dockerfile.registry",
                "--label",
                f"{MANAGED_IMAGE_KIND_LABEL}=registry-service",
                "--label",
                f"{MANAGED_IMAGE_FINGERPRINT_LABEL}={fingerprint}",
                "-t",
                "octopus-registry-service:latest",
                ".",
            ],
            capture_output=True,
            check=False,
        )
        log_path.write_text((result.stdout or "") + (result.stderr or ""), encoding="utf-8")
        if result.returncode != 0:
            raise OctopusError(f"Registry image build failed. Full docker build log: {log_path}")

    def ensure_provider_image_ready(self, provider: str, *, force: bool = False) -> None:
        freshness = self.image_freshness()[f"bot:{provider}"]
        if force or freshness.stale:
            self.build_provider_image(provider)

    def ensure_registry_image_ready(self, *, force: bool = False) -> None:
        freshness = self.image_freshness()["registry"]
        if force or freshness.stale:
            self.build_registry_image()

    def provider_live_health_output(self, provider: str, *, build_if_stale: bool = True) -> tuple[bool | None, str]:
        try:
            if build_if_stale:
                self.ensure_provider_image_ready(provider)
            else:
                freshness = self.image_freshness().get(f"bot:{provider}")
                if freshness is not None and not freshness.image_exists:
                    return None, "Provider image is missing."
            result = self.docker.provider_compose(
                provider,
                "run",
                "--rm",
                "bot-provider",
                "python",
                "-m",
                "app.main",
                "--provider-health",
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return None, str(exc)
        output = ((result.stdout or "") + (result.stderr or "")).strip()
        return result.returncode == 0, output

    def ensure_provider_auth_ready(self, provider: str) -> None:
        if provider_has_auth_files(self.repo_dir, provider):
            healthy, output = self.provider_live_health_output(provider)
            if healthy is True:
                return
            self.io.error("Stored provider auth is present but not valid. Starting the login flow now.")
            if output:
                self.io.error(output)
        else:
            self.io.error("Provider authentication is required. Starting the login flow now.")
        self.ensure_provider_image_ready(provider)
        result = self.docker.provider_compose(
            provider,
            "run",
            "--rm",
            "bot-provider",
            "sh",
            "/app/scripts/provider/container_provider_login.sh",
            capture_output=False,
            check=False,
        )
        if result.returncode != 0 or not provider_has_auth_files(self.repo_dir, provider):
            raise OctopusError(
                f"Provider login did not complete for {provider}. Finish login, then run ./octopus again."
            )
        healthy, output = self.provider_live_health_output(provider)
        if healthy is not True:
            detail = f"\n{output}" if output else ""
            raise OctopusError(
                f"Provider login did not complete for {provider}. Finish login, then run ./octopus again.{detail}"
            )

    def ensure_local_registry(
        self,
        *,
        force_rebuild: bool = False,
        deploy: RegistryDeployOptions | None = None,
    ) -> RegistryState:
        self.ensure_deploy_dirs()
        self.ensure_registry_image_ready(force=force_rebuild)
        created = False
        if not self.has_local_registry():
            created = True
            values = OrderedDict(
                {
                    "REGISTRY_ENROLL_TOKEN": secrets.token_urlsafe(24),
                    "REGISTRY_UI_TOKEN": secrets.token_urlsafe(24),
                    "REGISTRY_ALLOW_HTTP": "1",
                }
            )
        else:
            values = parse_env_file(self.registry_env_file())
        values = self._validated_registry_deploy_values(deploy, existing=values, creating=created)
        write_env_file(self.registry_env_file(), values)
        self.docker.registry_compose("up", "-d", "--remove-orphans", "service", capture_output=False)
        state = self.inspect_state().registry
        if created:
            self.io.print(f"Registry started: {state.ui_url}")
            self.io.print("")
            self.io.print(f"  UI password (shown once): {state.ui_token}")
            self.io.print("  Stored in: .deploy/registry/.env (REGISTRY_UI_TOKEN)")
        return state

    def start_registry(
        self,
        *,
        force_rebuild: bool = False,
        force_recreate: bool = False,
        deploy: RegistryDeployOptions | None = None,
    ) -> None:
        self.ensure_deploy_dirs()
        self.ensure_registry_image_ready(force=force_rebuild)
        if not self.has_local_registry():
            self.ensure_local_registry(force_rebuild=force_rebuild, deploy=deploy)
            return
        values = self._validated_registry_deploy_values(deploy, existing=parse_env_file(self.registry_env_file()), creating=False)
        write_env_file(self.registry_env_file(), values)
        args = ["up", "-d", "--remove-orphans"]
        if force_recreate:
            args.append("--force-recreate")
        args.append("service")
        self.docker.registry_compose(*args, capture_output=False)

    def stop_registry(self) -> None:
        if not self.has_local_registry():
            self.io.print("Local registry is not configured.")
            return
        self.docker.registry_compose("down", "--remove-orphans", capture_output=False, check=False)
        self.io.print("Local registry stopped.")

    def start_bot(self, slug: str, *, force_rebuild: bool = False, force_recreate: bool = False) -> None:
        provider = self.bot_values(slug).get("BOT_PROVIDER", "claude")
        self.ensure_provider_image_ready(provider, force=force_rebuild)
        self.reconcile_bot_registry_connections(slug)
        args = ["up", "-d"]
        if force_recreate:
            args.append("--force-recreate")
        args.append("bot")
        self.docker.bot_compose(slug, *args, capture_output=False)
        time.sleep(3)
        if not self.bot_is_running(slug):
            raise OctopusError(f"Bot {slug} failed to stay up after startup.")

    def stop_bot(self, slug: str) -> None:
        self.docker.bot_compose(slug, "stop", "bot", capture_output=False, check=False)

    def restart_bot(self, slug: str, *, force_rebuild: bool = False) -> None:
        self.stop_bot(slug)
        self.start_bot(slug, force_rebuild=force_rebuild, force_recreate=force_rebuild)

    def run_bot_doctor(self, slug: str, *, live_provider: bool = False) -> str:
        provider = self.bot_values(slug).get("BOT_PROVIDER", "claude")
        self.ensure_provider_image_ready(provider)
        args = ["run", "--rm", "bot", "python", "-m", "app.main", "--doctor"]
        if live_provider:
            args.append("--doctor-live-provider")
        result = self.docker.bot_compose(slug, *args, check=False)
        return (result.stdout or "") + (result.stderr or "")

    def follow_logs(self, target: ResolvedTarget, *, follow: bool = True) -> int:
        if target.kind == TargetKind.REGISTRY:
            args = ["logs"]
            if follow:
                args.append("-f")
            args.append("service")
            result = self.docker.registry_compose(*args, capture_output=False, check=False)
        else:
            args = ["logs"]
            if follow:
                args.append("-f")
            args.append("bot")
            result = self.docker.bot_compose(target.identifier, *args, capture_output=False, check=False)
        return result.returncode

    def open_shell(self, target: ResolvedTarget) -> int:
        if target.kind == TargetKind.REGISTRY:
            result = self.docker.registry_compose("exec", "service", "sh", capture_output=False, check=False)
        else:
            result = self.docker.bot_compose(target.identifier, "exec", "bot", "sh", capture_output=False, check=False)
        return result.returncode

    def registry_identity_valid(self, connection: RegistryConnection, state: dict[str, str]) -> bool:
        agent_id = state.get("agent_id", "")
        agent_token = state.get("agent_token", "")
        if not agent_id or not agent_token:
            return False
        base_url = self.local_registry_host_base_url() if connection.url == LOCAL_REGISTRY_INTERNAL_URL else connection.url
        request = urllib.request.Request(
            f"{base_url.rstrip('/')}/v1/agents/{agent_id}/status",
            headers={"Authorization": f"Bearer {agent_token}"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                if response.status >= 400:
                    return False
                payload = json.loads(response.read() or b"{}")
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError, ValueError):
            return False
        response_agent_id = str(payload.get("agent_id", "")).strip()
        return not response_agent_id or response_agent_id == agent_id

    def verify_registry_enrollment(self, slug: str, registry_id: str) -> None:
        for _ in range(10):
            if self.bot_registry_has_identity(slug, registry_id):
                return
            time.sleep(2)
        raise OctopusError(f"Registry enrollment has not completed yet for {slug}.")

    def reconcile_bot_registry_connections(self, slug: str) -> None:
        invalid_ids: list[str] = []
        for connection in self.bot_registry_connections(slug):
            state = self.read_bot_registry_state(slug, connection.registry_id)
            if not state:
                continue
            if not self.registry_identity_valid(connection, state):
                invalid_ids.append(connection.registry_id)
        if invalid_ids:
            self.clear_bot_registry_state(slug, invalid_ids)

    def configure_bot_registry_connections(self, slug: str, records: list[RegistryConnection], *, mode: str = "registry") -> None:
        env_file = self.bot_env_file(slug)
        upsert_env_value(env_file, "BOT_AGENT_MODE", mode)
        write_registry_connection_records(env_file, records)

    def _unique_registry_id(self, records: list[RegistryConnection], base: str) -> str:
        candidate = normalize_slug(base, fallback="registry") or "registry"
        existing = {record.registry_id for record in records}
        if candidate not in existing:
            return candidate
        suffix = 2
        while f"{candidate}-{suffix}" in existing:
            suffix += 1
        return f"{candidate}-{suffix}"

    def _derived_registry_id(self, registry_url: str, records: list[RegistryConnection]) -> str:
        parsed = urlparse(registry_url)
        host = (parsed.hostname or "registry").strip() or "registry"
        base = normalize_slug(host, fallback="registry") or "registry"
        port = parsed.port
        if port and port not in {80, 443}:
            base = normalize_slug(f"{base}-{port}", fallback=base)
        return self._unique_registry_id(records, base)

    def connect_bot_to_registry(
        self,
        slug: str,
        *,
        registry_url: str,
        enrollment_token: str,
        desired_scope: str = "full",
        registry_id: str = "",
    ) -> RegistryConnection:
        normalized_url, _ = _parse_registry_url(registry_url)
        if normalized_url.rstrip("/") == LOCAL_REGISTRY_INTERNAL_URL.rstrip("/"):
            raise OctopusError("Use ./octopus connect without --registry-url to connect a bot to the local registry.")
        token = str(enrollment_token or "").strip()
        if not token:
            raise OctopusError("A remote registry enroll token is required.")
        records = list(self.bot_registry_connections(slug))
        scope = desired_scope or "full"
        selected_id = normalize_slug(registry_id, fallback="registry") if registry_id else ""
        connection: RegistryConnection | None = None
        if selected_id:
            connection = next((record for record in records if record.registry_id == selected_id), None)
        if connection is None:
            connection = next((record for record in records if record.url.rstrip("/") == normalized_url), None)
        previous_id = connection.registry_id if connection is not None else None
        if connection is None:
            connection = RegistryConnection(
                registry_id=selected_id or self._derived_registry_id(normalized_url, records),
                url=normalized_url,
                enrollment_token=token,
                scope=scope,
            )
        else:
            new_id = selected_id or connection.registry_id
            duplicate = next(
                (record for record in records if record.registry_id == new_id and record.registry_id != connection.registry_id),
                None,
            )
            if duplicate is not None:
                raise OctopusError(f"{slug} already has a registry connection named '{new_id}'.")
            connection.registry_id = new_id
            connection.url = normalized_url
            connection.enrollment_token = token
            connection.scope = scope
        self.configure_bot_registry_connections(
            slug,
            self._replace_registry_record(records, connection, previous_id=previous_id),
        )
        state = self.read_bot_registry_state(slug, connection.registry_id)
        if state and not self.registry_identity_valid(connection, state):
            self.clear_bot_registry_state(slug, [connection.registry_id])
        self.restart_bot(slug, force_rebuild=False)
        self.verify_registry_enrollment(slug, connection.registry_id)
        return connection

    def prepare_bot_for_local_registry(self, slug: str, *, desired_scope: str = "full") -> RegistryConnection:
        registry = self.ensure_local_registry()
        if not registry.enroll_token:
            raise OctopusError("Local registry setup is incomplete.")
        connection = self.bot_local_registry_connection(slug)
        records = list(self.bot_registry_connections(slug))
        if connection is None:
            registry_id = "local"
            existing_ids = {record.registry_id for record in records}
            suffix = 2
            while registry_id in existing_ids:
                registry_id = f"local-{suffix}"
                suffix += 1
            connection = RegistryConnection(
                registry_id=registry_id,
                url=LOCAL_REGISTRY_INTERNAL_URL,
                enrollment_token=registry.enroll_token,
                scope=desired_scope,
            )
        else:
            connection.enrollment_token = registry.enroll_token
            connection.scope = desired_scope or connection.scope
        self.configure_bot_registry_connections(slug, self._replace_registry_record(records, connection))
        state = self.read_bot_registry_state(slug, connection.registry_id)
        if state and not self.registry_identity_valid(connection, state):
            self.clear_bot_registry_state(slug, [connection.registry_id])
        return connection

    def connect_bot_to_local_registry(self, slug: str, *, desired_scope: str = "full") -> None:
        connection = self.prepare_bot_for_local_registry(slug, desired_scope=desired_scope)
        self.restart_bot(slug, force_rebuild=False)
        self.verify_registry_enrollment(slug, connection.registry_id)

    def disconnect_bot_registry(self, slug: str, *, registry_id: str = "") -> RegistryConnection:
        connection = self.bot_registry_connection_by_id(slug, registry_id) if registry_id else self.bot_local_registry_connection(slug)
        if connection is None:
            if registry_id:
                raise OctopusError(f"{slug} has no registry connection named '{registry_id}'.")
            raise OctopusError(f"{slug} has no local registry connection.")
        records = [record for record in self.bot_registry_connections(slug) if record.registry_id != connection.registry_id]
        env_file = self.bot_env_file(slug)
        if records:
            self.configure_bot_registry_connections(slug, records)
        else:
            upsert_env_value(env_file, "BOT_AGENT_MODE", "standalone")
            write_registry_connection_records(env_file, [])
        self.clear_bot_registry_state(slug, [connection.registry_id])
        self.restart_bot(slug, force_rebuild=False)
        return connection

    def disconnect_bot__local_registry(self, slug: str) -> None:
        self.disconnect_bot_registry(slug)

    def clean_all(self) -> None:
        answer = self.io.prompt("Type 'yes' to confirm: ")
        if answer != "yes":
            self.io.print("Cancelled.")
            return
        for slug in self.list_bot_slugs():
            self.docker.bot_compose(slug, "down", "--remove-orphans", capture_output=False, check=False)
        if self.has_local_registry():
            self.docker.registry_compose("down", "--remove-orphans", capture_output=False, check=False)
        result = self.docker.run(
            [
                "docker",
                "ps",
                "-a",
                "--filter",
                "name=octopus-",
                "--filter",
                "name=telegram_bot_test_pg",
                "--format",
                "{{.Names}}",
            ],
            check=False,
        )
        for name in [line.strip() for line in result.stdout.splitlines() if line.strip()]:
            self.docker.run(["docker", "stop", name], capture_output=False, check=False)
            self.docker.run(["docker", "rm", "-v", name], capture_output=False, check=False)
        for volume in self.docker.run(
            ["docker", "volume", "ls", "--filter", "name=octopus", "--format", "{{.Name}}"],
            check=False,
        ).stdout.splitlines():
            volume = volume.strip()
            if volume:
                self.docker.run(["docker", "volume", "rm", volume], capture_output=False, check=False)
        for network in self.docker.run(
            ["docker", "network", "ls", "--filter", "name=octopus", "--format", "{{.Name}}"],
            check=False,
        ).stdout.splitlines():
            network = network.strip()
            if network:
                self.docker.run(["docker", "network", "rm", network], capture_output=False, check=False)
        for image in self.docker.run(
            ["docker", "image", "ls", "--filter", "reference=octopus-agent:*", "--format", "{{.Repository}}:{{.Tag}}"],
            check=False,
        ).stdout.splitlines():
            image = image.strip()
            if image:
                self.docker.run(["docker", "image", "rm", image], capture_output=False, check=False)
        for image in self.docker.run(
            ["docker", "image", "ls", "--filter", "reference=octopus-registry-service*", "--format", "{{.Repository}}:{{.Tag}}"],
            check=False,
        ).stdout.splitlines():
            image = image.strip()
            if image:
                self.docker.run(["docker", "image", "rm", image], capture_output=False, check=False)
        self.docker.run(["docker", "volume", "prune", "-f"], capture_output=False, check=False)
        self.docker.run(["docker", "builder", "prune", "-af"], capture_output=False, check=False)
        if self.deploy_dir.exists():
            shutil.rmtree(self.deploy_dir)
        self.io.print("Clean complete. Run ./octopus to start fresh.")

    def write_bot_env(
        self,
        *,
        slug: str,
        telegram_id: str,
        username: str,
        display_name: str,
        token: str,
        provider: str,
        mode: str,
        allowed_users: str = "",
        role: str = "",
        tags: str = "",
        description: str = "",
        skills: str = "",
        timeout_seconds: str = "3600",
        working_dir: str = "/home/bot",
        completion_webhook_url: str = "",
    ) -> Path:
        env_file = self.bot_env_file(slug)
        values = OrderedDict()
        values["BOT_INSTANCE"] = slug
        values["BOT_SLUG"] = slug
        values["BOT_AGENT_SLUG"] = slug
        values["BOT_TELEGRAM_ID"] = telegram_id
        values["BOT_TELEGRAM_USERNAME"] = username
        values["BOT_DISPLAY_NAME"] = display_name
        values["BOT_AGENT_DISPLAY_NAME"] = display_name
        values["TELEGRAM_BOT_TOKEN"] = token
        values["BOT_PROVIDER"] = provider
        values["BOT_AGENT_MODE"] = "standalone"
        values["BOT_COMPACT_MODE"] = "1"
        if role:
            values["BOT_ROLE"] = role
            values["BOT_AGENT_ROLE"] = role
        if tags:
            values["BOT_AGENT_TAGS"] = tags
        if description:
            values["BOT_AGENT_DESCRIPTION"] = description
        if skills:
            values["BOT_SKILLS"] = skills
        if mode == "autonomous":
            values["BOT_AUTONOMOUS"] = "1"
            values["BOT_APPROVAL_MODE"] = "off"
            values["BOT_ALLOW_OPEN"] = "0"
            values["BOT_ALLOWED_USERS"] = allowed_users
        elif mode == "safe":
            values["BOT_AUTONOMOUS"] = "0"
            values["BOT_APPROVAL_MODE"] = "on"
            if allowed_users:
                values["BOT_ALLOWED_USERS"] = allowed_users
                values["BOT_ALLOW_OPEN"] = "0"
            else:
                values["BOT_ALLOW_OPEN"] = "1"
        else:
            if allowed_users:
                values["BOT_ALLOWED_USERS"] = allowed_users
                values["BOT_ALLOW_OPEN"] = "0"
            else:
                values["BOT_ALLOW_OPEN"] = "1"
        values["BOT_TIMEOUT_SECONDS"] = timeout_seconds
        values["BOT_WORKING_DIR"] = working_dir
        values["BOT_DATA_DIR"] = "/home/bot/data"
        values["BOT_CREDENTIAL_KEY"] = secrets.token_urlsafe(32)
        if completion_webhook_url:
            values["BOT_COMPLETION_WEBHOOK_URL"] = completion_webhook_url
        write_env_file(env_file, values)
        return env_file

    def create_workspace(self, name: str, host_path: str) -> None:
        if not re.match(r"^[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?$|^[a-z0-9]$", name):
            raise OctopusError("Workspace name must be a lowercase slug (a-z, 0-9, hyphens), 1-32 chars.")
        root = Path(host_path)
        if not root.is_absolute():
            raise OctopusError("Host path must be absolute.")
        if not root.is_dir():
            raise OctopusError(f"Host path '{host_path}' does not exist or is not a directory.")
        ws_dir = self.deploy_dir / "workspaces" / name
        if ws_dir.exists():
            raise OctopusError(f"Workspace '{name}' already exists.")
        ws_dir.mkdir(parents=True, exist_ok=True)
        write_env_file(
            ws_dir / "workspace.conf",
            OrderedDict(
                {
                    "WORKSPACE_ROOT": str(root),
                    "WORKSPACE_MOUNT": f"/workspace/{name}",
                    "WORKSPACE_MODE": "rw",
                }
            ),
        )
        (ws_dir / "members.txt").write_text("", encoding="utf-8")

    def render_bot_workspace_env_content(self, slug: str) -> str:
        env_values = self.bot_values(slug)
        existing_projects = env_values.get("BOT_PROJECTS", "")
        existing_tags = env_values.get("BOT_AGENT_TAGS", "")
        workspace_entries: list[str] = []
        workspace_tags: list[str] = []
        for ws_slug in self.workspace_memberships(slug):
            mount = self.workspace_mount(ws_slug)
            policy = "inspect" if self.workspace_mode(ws_slug) == "ro" else "edit"
            workspace_entries.append(f"{ws_slug}:{mount}|{policy}")
            workspace_tags.append(f"workspace:{ws_slug}")
        merged_projects = list(workspace_entries)
        existing_names = {entry.split(":", 1)[0] for entry in workspace_entries}
        if existing_projects:
            for entry in [part.strip() for part in existing_projects.split(",") if part.strip()]:
                name = entry.split(":", 1)[0]
                if name not in existing_names:
                    merged_projects.append(entry)
        merged_tags = list(workspace_tags)
        if existing_tags:
            for tag in [part.strip() for part in existing_tags.split(",") if part.strip()]:
                if tag not in merged_tags:
                    merged_tags.append(tag)
        return (
            "# Machine-generated by ./octopus Workspaces menu — do not edit.\n"
            "# Regenerated on every workspace mutation.\n"
            f"BOT_PROJECTS={','.join(merged_projects)}\n"
            f"BOT_AGENT_TAGS={','.join(merged_tags)}\n"
        )

    def write_bot_workspace_compose_override(self, slug: str, output_path: Path, services: list[str]) -> None:
        memberships = self.workspace_memberships(slug)
        ws_env_path = self.deploy_dir / "bots" / slug / "workspace.env"
        lines = ["services:"]
        for service in services:
            lines.append(f"  {service}:")
            lines.append("    env_file:")
            lines.append(f"      - {ws_env_path.relative_to(self.repo_dir)}")
            lines.append("    volumes:")
            for ws_slug in memberships:
                lines.append(
                    f"      - {self.workspace_root(ws_slug)}:{self.workspace_mount(ws_slug)}:{self.workspace_mode(ws_slug)}"
                )
        output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def regenerate_bot_workspace_env(self, slug: str) -> None:
        ws_env_path = self.deploy_dir / "bots" / slug / "workspace.env"
        compose_override = self.deploy_dir / "bots" / slug / "docker-compose.workspace.yml"
        shared_override = self.deploy_dir / "bots" / slug / "docker-compose.workspace-shared.yml"
        memberships = self.workspace_memberships(slug)
        if not memberships:
            for path in (ws_env_path, compose_override, shared_override):
                if path.exists():
                    path.unlink()
            return
        ws_env_path.write_text(self.render_bot_workspace_env_content(slug), encoding="utf-8")
        ws_env_path.chmod(0o600)
        self.write_bot_workspace_compose_override(slug, compose_override, ["bot", "bot-provider"])
        self.write_bot_workspace_compose_override(slug, shared_override, ["bot", "bot-provider", "bot-webhook", "bot-worker"])

    def add_bot_to_workspace(self, ws_slug: str, bot_slug: str) -> None:
        if not self.workspace_conf_file(ws_slug).exists():
            raise OctopusError(f"Workspace '{ws_slug}' does not exist.")
        if not self.bot_env_file(bot_slug).exists():
            raise OctopusError(f"Bot '{bot_slug}' is not configured.")
        members = self.workspace_members(ws_slug)
        if bot_slug not in members:
            members.append(bot_slug)
            self.workspace_members_file(ws_slug).write_text("\n".join(sorted(members)) + "\n", encoding="utf-8")
        self.regenerate_bot_workspace_env(bot_slug)

    def remove_bot__workspace(self, ws_slug: str, bot_slug: str) -> None:
        members = [member for member in self.workspace_members(ws_slug) if member != bot_slug]
        self.workspace_members_file(ws_slug).write_text("\n".join(sorted(members)) + ("\n" if members else ""), encoding="utf-8")
        self.regenerate_bot_workspace_env(bot_slug)

    def maybe_join_autonomous_workspace(self, slug: str, workspace_path: str) -> None:
        if not workspace_path:
            return
        root = Path(workspace_path)
        if not root.is_dir():
            self.io.error(f"Workspace directory does not exist: {workspace_path}")
            return
        ws_name = normalize_slug(root.name) or "workspace"
        if not self.workspace_conf_file(ws_name).exists():
            self.create_workspace(ws_name, str(root))
        self.add_bot_to_workspace(ws_name, slug)

    def add_bot_interactive(self) -> None:
        self.ensure_deploy_dirs()
        self.io.error("You need a Telegram bot token before the bot can start.")
        self.io.error("  Step 1: Open BotFather in Telegram:")
        self.io.error("          https://t.me/BotFather")
        self.io.error("  Step 2: Send: /newbot")
        self.io.error("  Step 3: Pick a display name and a username ending in 'bot'.")
        while True:
            token = self.io.prompt("Paste your Telegram bot token: ").strip()
            if telegram_token_is_placeholder(token):
                self.io.error("That still looks like a placeholder token. Copy the full token @BotFather.")
                continue
            if not telegram_token_format_valid(token):
                self.io.error("Telegram bot tokens look like digits:letters @BotFather.")
                continue
            try:
                telegram_id, username, display_name = validate_telegram_token(token)
            except OctopusError as exc:
                self.io.error(str(exc))
                continue
            break
        slug = normalize_slug(username) or "bot"
        if self.bot_env_file(slug).exists():
            raise OctopusError(f"Bot '{slug}' is already configured.")
        provider = prompt_with_default(self.io, "Provider (claude or codex)", "claude")
        while provider not in {"claude", "codex"}:
            self.io.error("Choose 'claude' or 'codex'.")
            provider = prompt_with_default(self.io, "Provider (claude or codex)", "claude")
        self.io.print("Setup mode:")
        self.io.print("  1. Autonomous")
        self.io.print("  2. Safe")
        self.io.print("  3. Advanced")
        choice = self.io.prompt("Choose a mode [2]: ").strip().lower() or "2"
        setup_mode = {"1": "autonomous", "2": "safe", "3": "advanced"}.get(choice, "safe")
        allowed_users = ""
        role = ""
        tags = ""
        description = ""
        skills = ""
        working_dir = "/home/bot"
        timeout_seconds = "3600"
        completion_webhook_url = ""
        autonomous_workspace = ""
        if setup_mode == "autonomous":
            allowed_users = self.io.prompt("Your Telegram user ID (required for autonomous mode): ").strip()
            autonomous_workspace = self.io.prompt("Workspace directory (blank to skip): ").strip()
        elif setup_mode == "advanced":
            role = prompt_with_default(self.io, "Role", "")
            tags = prompt_with_default(self.io, "Tags (comma-separated)", "")
            description = prompt_with_default(self.io, "Description", "")
            skills = prompt_with_default(self.io, "Skills (comma-separated)", "")
            allowed_users = prompt_with_default(self.io, "Allowed users (blank = open)", "")
            working_dir = prompt_with_default(self.io, "Working directory", working_dir)
            timeout_seconds = prompt_with_default(self.io, "Timeout seconds", timeout_seconds)
            completion_webhook_url = prompt_with_default(self.io, "Completion webhook URL", "")
        self.write_bot_env(
            slug=slug,
            telegram_id=telegram_id,
            username=username,
            display_name=display_name,
            token=token,
            provider=provider,
            mode=setup_mode,
            allowed_users=allowed_users,
            role=role,
            tags=tags,
            description=description,
            skills=skills,
            timeout_seconds=timeout_seconds,
            working_dir=working_dir,
            completion_webhook_url=completion_webhook_url,
        )
        self.maybe_join_autonomous_workspace(slug, autonomous_workspace)
        self.ensure_provider_image_ready(provider)
        self.ensure_provider_auth_ready(provider)
        self.docker.ensure_network()
        local_registry_connection = self.prepare_bot_for_local_registry(slug)
        doctor_output = self.run_bot_doctor(slug)
        if "FAIL:" in doctor_output or "Overall status: unhealthy" in doctor_output:
            raise OctopusError(doctor_output.strip())
        self.start_bot(slug)
        self.verify_registry_enrollment(slug, local_registry_connection.registry_id)
        self.io.print(f"Bot is running. Open Telegram and message @{username}.")
        self.io.print("Use ./octopus status to check health.")
