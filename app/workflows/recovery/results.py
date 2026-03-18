"""Explicit recovery transition outcomes and validation errors."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class OtherClaimedForChat(Exception):
    """Another item for the same chat is already claimed; claim or reclaim blocked."""


class BlockedReplay(Exception):
    """Replay requested but another item for the same chat is claimed."""


class NotStaleClaim(Exception):
    """recover_stale_claim was invoked but the claim is not stale."""


class TransportStateCorruption(Exception):
    """DB state is not a valid transport state; treat as corruption."""


class TransportDisposition(str, Enum):
    ok = "ok"
    already_claimed_by_worker = "already_claimed_by_worker"
    other_claimed_for_chat = "other_claimed_for_chat"
    blocked_replay = "blocked_replay"
    already_handled = "already_handled"
    discarded = "discarded"
    replayed = "replayed"
    superseded = "superseded"
    stale_recovered = "stale_recovered"
    done = "done"
    failed = "failed"
    invalid_transition = "invalid_transition"
    guard_failed = "guard_failed"


@dataclass(frozen=True)
class TransitionResult:
    allowed: bool
    new_state: str | None
    disposition: TransportDisposition
    reason: str = ""
    user_message_key: str | None = None
    extra: dict[str, Any] | None = None
