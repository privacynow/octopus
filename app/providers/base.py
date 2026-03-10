"""Provider protocol and shared result dataclass."""

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

# Backward-compat re-exports — these types now live in their own modules.
# Production code should import from the authoritative module directly.
# Tests may still reference these until fully migrated.
from app.execution_context import ResolvedExecutionContext as ResolvedContext  # noqa: F401
from app.execution_context import ResolvedExecutionContext  # noqa: F401


# Backward-compat: PendingRequest was a single type for both approval and retry.
# New code uses PendingApproval / PendingRetry from app.session_state.
@dataclass
class PendingRequest:
    """DEPRECATED — use PendingApproval / PendingRetry from app.session_state."""
    request_user_id: int
    prompt: str
    image_paths: list[str]
    attachment_dicts: list[dict] = field(default_factory=list)
    context_hash: str = ""
    denials: list[dict] | None = None
    created_at: float = 0.0


def compute_context_hash(
    role: str = "",
    active_skills: list[str] | None = None,
    skill_digests: dict[str, str] | None = None,
    provider_config_digest: str = "",
    extra_dirs: list[str] | None = None,
    project_id: str = "",
    file_policy: str = "",
    working_dir: str = "",
) -> str:
    """Backward-compat wrapper — delegates to ResolvedExecutionContext.context_hash.

    New code should use ResolvedExecutionContext.context_hash directly.
    """
    ctx = ResolvedExecutionContext(
        role=role,
        active_skills=active_skills or [],
        skill_digests=skill_digests or {},
        provider_config_digest=provider_config_digest,
        base_extra_dirs=extra_dirs or [],
        project_id=project_id,
        working_dir=working_dir,
        file_policy=file_policy,
        provider_name="",
    )
    return ctx.context_hash


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
    working_dir: str = ""  # Per-chat project override; empty = use config default
    file_policy: str = ""  # "inspect" or "edit"; empty = use config default


@dataclass
class RunContext(PreflightContext):
    """Full execution context — extends PreflightContext with secrets and provider config."""
    provider_config: dict = field(default_factory=dict)  # Phase 3
    credential_env: dict[str, str] = field(default_factory=dict)  # Phase 2
    skip_permissions: bool = False  # bypass permission checks (user already approved)


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
