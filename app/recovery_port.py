"""Contracts for recovery replay and discard workflows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from app.transport import InboundMessage


@dataclass(frozen=True)
class RecoveryReplayPlan:
    item_id: str
    event: InboundMessage
    trust_tier: str


@dataclass(frozen=True)
class RecoveryActionOutcome:
    status: str
    toast_message: str = ""
    edit_message: str = ""
    show_alert: bool = False
    replay_plan: RecoveryReplayPlan | None = None


class RecoveryPort(Protocol):
    def prepare_action(
        self,
        *,
        data_dir: Path,
        conversation_key: str,
        event_id: str,
        action: str,
        worker_id: str,
        ignore_claimed_item_id: str = "",
        config: Any,
    ) -> RecoveryActionOutcome: ...

    def complete_replay(self, *, data_dir: Path, item_id: str) -> None: ...

    def fail_replay(self, *, data_dir: Path, item_id: str, error: str = "replay_failed") -> None: ...
