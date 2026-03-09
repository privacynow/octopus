"""Provider protocol and shared result dataclass."""

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class RunResult:
    text: str
    returncode: int = 0
    timed_out: bool = False
    provider_state_updates: dict[str, Any] = field(default_factory=dict)
    denials: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class PreflightContext:
    """Sanitized context for approval planning — no secrets, no tool wiring."""
    extra_dirs: list[str]
    system_prompt: str
    capability_summary: str  # Phase 3; empty string in Phase 1


@dataclass
class RunContext(PreflightContext):
    """Full execution context — extends PreflightContext with secrets and provider config."""
    provider_config: dict = field(default_factory=dict)  # Phase 3
    credential_env: dict[str, str] = field(default_factory=dict)  # Phase 2
    skip_permissions: bool = False  # bypass permission checks (user already approved)


@dataclass
class PendingRequest:
    """Typed pending state for approval and retry flows."""
    request_user_id: int
    prompt: str
    image_paths: list[str]
    attachment_dicts: list[dict]  # serialized Attachment objects (approval flow)
    context_hash: str
    denials: list[dict] | None = None  # permission denials (retry flow only)
    created_at: float = 0.0  # time.time() when request was created


def compute_context_hash(
    role: str,
    active_skills: list[str],
    skill_digests: dict[str, str],
    provider_config_digest: str,
    extra_dirs: list[str],
) -> str:
    """SHA-256 of the base execution context (excludes denial-approved dirs)."""
    payload = json.dumps({
        "role": role,
        "active_skills": sorted(active_skills),
        "skill_digests": {k: skill_digests[k] for k in sorted(skill_digests)},
        "provider_config_digest": provider_config_digest,
        "extra_dirs": sorted(extra_dirs),
    }, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


class ProgressSink(Protocol):
    """Rate-limited HTML message editor. Providers call this with pre-formatted HTML."""

    async def update(self, html_text: str, *, force: bool = False) -> None: ...


@runtime_checkable
class Provider(Protocol):
    name: str

    def new_provider_state(self) -> dict[str, Any]:
        """Return provider-specific fields for a fresh session."""
        ...

    async def run(
        self,
        provider_state: dict[str, Any],
        prompt: str,
        image_paths: list[str],
        progress: ProgressSink,
        context: RunContext | None = None,
    ) -> RunResult:
        """Execute a prompt against the CLI backend."""
        ...

    async def run_preflight(
        self,
        prompt: str,
        image_paths: list[str],
        progress: ProgressSink,
        context: PreflightContext | None = None,
    ) -> RunResult:
        """Run a read-only approval preflight."""
        ...

    def check_health(self) -> list[str]:
        """Return list of problems, empty if healthy. Cheap local checks only
        (e.g. binary exists in PATH). Must not do blocking I/O."""
        ...

    async def check_runtime_health(self) -> list[str]:
        """Return list of problems from runtime probes (version check, API ping).
        Uses async subprocess — safe to await in the event loop."""
        ...
