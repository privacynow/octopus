"""SDK workflow contracts for recovery replay and recovery notices."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Protocol

from octopus_sdk.inbound_types import InboundMessage


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


@dataclass(frozen=True)
class WorkerRecoveryNotice:
    update_id: int
    preview: str
    prompt: str
    run_again_label: str
    skip_label: str


@dataclass(frozen=True)
class WorkerRecoveryOutcome:
    status: str
    notice: WorkerRecoveryNotice | None = None


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
        config: object | None = None,
        dispatcher: object | None = None,
    ) -> RecoveryActionOutcome: ...

    def complete_replay(self, *, data_dir: Path, item_id: str) -> None: ...

    def fail_replay(self, *, data_dir: Path, item_id: str, error: str = "replay_failed") -> None: ...

    async def dispatch_worker_recovery(
        self,
        *,
        data_dir: Path,
        item_id: str,
        original_text: str,
        update_id: int,
        bind_egress: Callable[[], Awaitable[None]],
        send_notice: Callable[[WorkerRecoveryNotice], Awaitable[None]],
    ) -> WorkerRecoveryOutcome: ...
