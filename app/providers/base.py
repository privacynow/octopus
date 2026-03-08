"""Provider protocol and shared result dataclass."""

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class RunResult:
    text: str
    returncode: int = 0
    timed_out: bool = False
    provider_state_updates: dict[str, Any] = field(default_factory=dict)
    denials: list[dict[str, Any]] = field(default_factory=list)


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
        extra_dirs: list[str] | None = None,
    ) -> RunResult:
        """Execute a prompt against the CLI backend."""
        ...

    async def run_preflight(
        self,
        prompt: str,
        image_paths: list[str],
        progress: ProgressSink,
    ) -> RunResult:
        """Run a read-only approval preflight."""
        ...

    def check_health(self) -> list[str]:
        """Return list of problems, empty if healthy. Cheap checks only."""
        ...
