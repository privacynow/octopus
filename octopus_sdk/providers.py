"""Provider protocol and shared result dataclass."""

from __future__ import annotations

import asyncio

from collections.abc import Iterator, Mapping, MutableMapping
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from octopus_sdk.registry.models import DelegationIntent

JsonScalar = str | int | float | bool | None
JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


@dataclass
class ProviderStateRecord(MutableMapping[str, JsonValue]):
    values: dict[str, JsonValue] = field(default_factory=dict)

    def __getitem__(self, key: str) -> JsonValue:
        return self.values[key]

    def __setitem__(self, key: str, value: JsonValue) -> None:
        self.values[key] = value

    def __delitem__(self, key: str) -> None:
        del self.values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.values)

    def __len__(self) -> int:
        return len(self.values)

    def get(self, key: str, default: JsonValue = None) -> JsonValue:
        return self.values.get(key, default)

    def update(
        self,
        other: Mapping[str, JsonValue] | "ProviderStateRecord" | None = None,
        /,
        **kwargs: JsonValue,
    ) -> None:
        if other:
            if isinstance(other, ProviderStateRecord):
                self.values.update(other.values)
            else:
                self.values.update(dict(other))
        if kwargs:
            self.values.update(kwargs)

    def to_dict(self) -> dict[str, JsonValue]:
        return dict(self.values)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, ProviderStateRecord):
            return self.values == other.values
        if isinstance(other, Mapping):
            return self.values == dict(other)
        return False


@dataclass(frozen=True)
class DenialRecord(Mapping[str, JsonValue]):
    values: dict[str, JsonValue] = field(default_factory=dict)

    def __getitem__(self, key: str) -> JsonValue:
        return self.values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.values)

    def __len__(self) -> int:
        return len(self.values)

    def get(self, key: str, default: JsonValue = None) -> JsonValue:
        return self.values.get(key, default)

    def to_dict(self) -> dict[str, JsonValue]:
        return dict(self.values)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, DenialRecord):
            return self.values == other.values
        if isinstance(other, Mapping):
            return self.values == dict(other)
        return False


@dataclass(frozen=True)
class CredentialEnvRecord(Mapping[str, str]):
    values: dict[str, str] = field(default_factory=dict)

    def __getitem__(self, key: str) -> str:
        return self.values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.values)

    def __len__(self) -> int:
        return len(self.values)

    def get(self, key: str, default: str | None = None) -> str | None:
        return self.values.get(key, default)

    def to_dict(self) -> dict[str, str]:
        return dict(self.values)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, CredentialEnvRecord):
            return self.values == other.values
        if isinstance(other, Mapping):
            return self.values == dict(other)
        return False


@dataclass(frozen=True)
class ProviderConfigRecord(Mapping[str, JsonValue]):
    values: dict[str, JsonValue] = field(default_factory=dict)

    def __getitem__(self, key: str) -> JsonValue:
        return self.values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.values)

    def __len__(self) -> int:
        return len(self.values)

    def get(self, key: str, default: JsonValue = None) -> JsonValue:
        return self.values.get(key, default)

    def to_dict(self) -> dict[str, JsonValue]:
        return dict(self.values)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, ProviderConfigRecord):
            return self.values == other.values
        if isinstance(other, Mapping):
            return self.values == dict(other)
        return False


def coerce_provider_state(value: Mapping[str, JsonValue] | ProviderStateRecord | None) -> ProviderStateRecord:
    if isinstance(value, ProviderStateRecord):
        return value
    if value is None:
        return ProviderStateRecord()
    return ProviderStateRecord(dict(value))


def coerce_denial_records(
    values: list[DenialRecord] | tuple[DenialRecord, ...] | list[Mapping[str, JsonValue]] | None,
) -> list[DenialRecord]:
    if not values:
        return []
    records: list[DenialRecord] = []
    for value in values:
        if isinstance(value, DenialRecord):
            records.append(value)
        else:
            records.append(DenialRecord(dict(value)))
    return records


def coerce_credential_env(
    value: Mapping[str, str] | CredentialEnvRecord | None,
) -> CredentialEnvRecord:
    if isinstance(value, CredentialEnvRecord):
        return value
    if value is None:
        return CredentialEnvRecord()
    return CredentialEnvRecord(dict(value))


def coerce_provider_config(
    value: Mapping[str, JsonValue] | ProviderConfigRecord | None,
) -> ProviderConfigRecord:
    if isinstance(value, ProviderConfigRecord):
        return value
    if value is None:
        return ProviderConfigRecord()
    return ProviderConfigRecord(dict(value))


@dataclass(frozen=True)
class FileChangeRecord:
    path: str
    change_type: str
    summary: str


@dataclass(frozen=True)
class ToolExecutionRecord:
    tool_name: str
    call_id: str
    status: str
    input_summary: str
    output_summary: str
    duration_ms: int | None = None
    file_changes: tuple[FileChangeRecord, ...] = ()


@dataclass
class RunResult:
    text: str
    working_dir: str = ""
    returncode: int = 0
    timed_out: bool = False
    resume_failed: bool = False  # True only when --resume target is dead/invalid
    provider_state_updates: ProviderStateRecord = field(default_factory=ProviderStateRecord)
    denials: list[DenialRecord] = field(default_factory=list)
    cancelled: bool = False
    coordination_intent: DelegationIntent | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_prompt_tokens: int | None = None
    cached_completion_tokens: int | None = None
    cost_usd: float = 0.0
    tool_executions: list[ToolExecutionRecord] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.provider_state_updates = coerce_provider_state(self.provider_state_updates)
        self.denials = coerce_denial_records(self.denials)


@dataclass
class PreflightContext:
    """Sanitized context for approval planning — no secrets, no tool wiring."""
    extra_dirs: list[str]
    system_prompt: str
    capability_summary: str  # Phase 3; empty string in Phase 1
    working_dir: str = ""  # Per-chat project override; empty = use config default
    file_policy: str = ""  # "inspect" or "edit"; empty = use config default
    effective_model: str = ""  # resolved from model profiles; empty = use config.model


@dataclass
class RunContext(PreflightContext):
    """Full execution context — extends PreflightContext with secrets and provider config."""
    provider_config: ProviderConfigRecord = field(default_factory=ProviderConfigRecord)  # Phase 3
    credential_env: CredentialEnvRecord = field(default_factory=CredentialEnvRecord)  # Phase 2
    skip_permissions: bool = False  # bypass permission checks (user already approved)

    def __post_init__(self) -> None:
        self.provider_config = coerce_provider_config(self.provider_config)
        self.credential_env = coerce_credential_env(self.credential_env)


class ProgressSink(Protocol):
    """Rate-limited HTML message editor. Providers call this with pre-formatted HTML."""

    async def update(self, html_text: str, *, force: bool = False) -> None: ...


@runtime_checkable
class Provider(Protocol):
    name: str

    def new_provider_state(self, conversation_key: str) -> ProviderStateRecord:
        """Return provider-specific fields for a fresh session.
        """
        ...

    async def run(
        self,
        provider_state: ProviderStateRecord,
        prompt: str,
        image_paths: list[str],
        progress: ProgressSink,
        context: RunContext | None = None,
        cancel: asyncio.Event | None = None,
    ) -> RunResult:
        """Execute a prompt against the CLI backend."""
        ...

    async def run_preflight(
        self,
        prompt: str,
        image_paths: list[str],
        progress: ProgressSink,
        context: PreflightContext | None = None,
        cancel: asyncio.Event | None = None,
    ) -> RunResult:
        """Run a read-only approval preflight."""
        ...

    def check_health(self) -> list[str]:
        """Return list of problems, empty if healthy. Cheap local checks only
        (e.g. binary exists in PATH). Must not do blocking I/O."""
        ...

    async def check_auth_health(self) -> list[str]:
        """Return startup-safe auth problems, empty if authenticated.

        May use local subprocesses and on-disk auth artifacts, but must not
        require a live model round-trip or other expensive provider inference.
        """
        ...

    async def check_runtime_health(self) -> list[str]:
        """Return list of problems from deep runtime probes.

        This may include a real provider request. Uses async subprocess and is
        safe to await in the event loop, but should not gate normal startup.
        """
        ...
