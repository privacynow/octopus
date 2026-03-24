from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class TargetKind(str, Enum):
    REGISTRY = "registry"
    BOT = "bot"


class Action(str, Enum):
    STATUS = "status"
    START = "start"
    STOP = "stop"
    RESTART = "restart"
    REDEPLOY = "redeploy"
    CONNECT = "connect"
    DISCONNECT = "disconnect"
    LOGS = "logs"
    SHELL = "shell"
    DOCTOR = "doctor"
    HELP = "help"


@dataclass(slots=True)
class RegistryConnection:
    registry_id: str
    url: str
    enrollment_token: str
    scope: str = "full"


@dataclass(slots=True)
class Workspace:
    slug: str
    root: Path
    mount: str
    mode: str = "rw"
    members: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ProviderAuthState:
    provider: str
    configured: bool


@dataclass(slots=True)
class ImageFreshness:
    image: str
    fingerprint: str
    image_exists: bool
    image_fingerprint: str = ""

    @property
    def stale(self) -> bool:
        if not self.image_exists:
            return True
        return self.image_fingerprint != self.fingerprint


@dataclass(slots=True)
class BotState:
    slug: str
    display_name: str
    telegram_username: str
    telegram_id: str
    provider: str
    mode: str
    env_file: Path
    running: bool
    docker_status: str = ""
    role: str = ""
    tags: str = ""
    registry_connections: list[RegistryConnection] = field(default_factory=list)
    local_registry_connection_state: str = "none"
    local_registry_live_state: str = "none"
    workspace_memberships: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        base = self.display_name or self.slug
        if self.telegram_username:
            return f"{base} (@{self.telegram_username})"
        return base


@dataclass(slots=True)
class RegistryState:
    configured: bool
    running: bool
    env_file: Path
    port: int = 8787
    ui_url: str = "http://localhost:8787/ui"
    enroll_token: str = ""
    ui_token: str = ""


@dataclass(slots=True)
class SystemState:
    repo_dir: Path
    bots: list[BotState]
    registry: RegistryState
    workspaces: list[Workspace]
    provider_auth: list[ProviderAuthState]
    freshness: dict[str, ImageFreshness]

    @property
    def has_bots(self) -> bool:
        return bool(self.bots)


@dataclass(slots=True)
class ResolvedTarget:
    kind: TargetKind
    identifier: str
    label: str


@dataclass(slots=True)
class ExecutionPlan:
    action: Action
    targets: list[ResolvedTarget]
    rebuild_images: list[str] = field(default_factory=list)
    recreate_targets: list[str] = field(default_factory=list)
    restart_targets: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
