"""Explicit transition outcomes for workflow machines.

Repository and handlers use these to decide what to do after a transition
attempt (e.g. blocked_replay for recovery flows). Outcomes returned by the
machine come from the transition table and guards. Repository-level outcomes
(such as already_handled) are used by callers when they observe DB state
(e.g. row missing or already terminal) and are not returned by the machine.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Domain exceptions (raised by machine validators; repository maps to TransitionResult)
# ---------------------------------------------------------------------------


class OtherClaimedForChat(Exception):
    """Another item for the same chat is already claimed; claim or reclaim blocked."""


class BlockedReplay(Exception):
    """Replay requested but another item for the same chat is claimed."""


class NotStaleClaim(Exception):
    """recover_stale_claim was invoked but the claim is not stale (guard failed)."""


class TransportStateCorruption(Exception):
    """DB state is not a valid transport state; treat as corruption, do not no-op."""


class TransportDisposition(str, Enum):
    """Classification of transport/recovery transition outcomes.

    The machine returns only: ok, already_claimed_by_worker, other_claimed_for_chat,
    blocked_replay, discarded, replayed, superseded, stale_recovered, done, failed,
    invalid_transition, guard_failed. already_handled is for repository/caller use
    when the row is already terminal or missing (idempotent no-op); the machine
    never returns it.
    """

    ok = "ok"
    # Pre-claimed by same worker (no state change, reuse item)
    already_claimed_by_worker = "already_claimed_by_worker"
    # Cannot claim: another item for this chat is claimed
    other_claimed_for_chat = "other_claimed_for_chat"
    # Replay requested but another item for chat is claimed
    blocked_replay = "blocked_replay"
    # Repository/caller only: row already terminal or missing (idempotent). Not returned by machine.
    already_handled = "already_handled"
    # User discarded recovery
    discarded = "discarded"
    # User replayed; item moved back to claimed
    replayed = "replayed"
    # Fresh message superseded pending recovery
    superseded = "superseded"
    # Stale claim recovered to queued
    stale_recovered = "stale_recovered"
    # Terminal: done
    done = "done"
    # Terminal: failed
    failed = "failed"
    # Invalid transition from current state
    invalid_transition = "invalid_transition"
    # Guard failed (e.g. per-chat invariant)
    guard_failed = "guard_failed"


@dataclass(frozen=True)
class TransitionResult:
    """Result of asking the workflow machine to validate a transition.

    Repository code uses this to decide whether to commit and what to
    return to callers. No side effects inside the machine.
    """

    allowed: bool
    new_state: str | None  # None if transition not allowed or no change
    disposition: TransportDisposition
    reason: str = ""
    user_message_key: str | None = None  # Optional i18n key for user-facing message
    extra: dict[str, Any] | None = None
