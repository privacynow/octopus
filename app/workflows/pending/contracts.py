"""Workflow-local contracts for pending approval and retry flows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.config import BotConfig
from app.session_state import SessionState


@dataclass(frozen=True)
class PendingExecutionPlan:
    prompt: str
    image_paths: tuple[str, ...]
    actor_key: str
    trust_tier: str
    extra_dirs: tuple[str, ...]


@dataclass(frozen=True)
class PendingRequestOutcome:
    status: str
    mutated: bool = False
    message: str = ""
    execution_plan: PendingExecutionPlan | None = None


class PendingRequestPort(Protocol):
    def approve(
        self,
        session: SessionState,
        *,
        cfg: BotConfig,
        provider_name: str,
    ) -> PendingRequestOutcome: ...

    def reject(self, session: SessionState) -> PendingRequestOutcome: ...

    def retry_skip(self, session: SessionState) -> PendingRequestOutcome: ...

    def retry_allow(
        self,
        session: SessionState,
        *,
        cfg: BotConfig,
        provider_name: str,
    ) -> PendingRequestOutcome: ...
