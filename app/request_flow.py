"""Request orchestration — pure business logic, no transport dependency.

This module contains the service-layer logic for request execution,
approval validation, and denial handling. Credential setup lives in the
credential-domain modules.

Design rules:
- No Telegram imports.  No message sending.  No progress updates.
- Functions receive explicit parameters (no module-global singletons).
- Returns typed results; handlers decide how to render them.
- Execution-scope fields (active_skills, working_dir, file_policy, etc.)
  must come from ResolvedExecutionContext, never from raw SessionState.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from app.execution_context import resolve_execution_context
from app.time_utils import age_seconds, utc_now
from app.user_messages import (
    approval_context_changed,
    approval_expired,
    approval_expired_fallback,
)
from app.session_state import PendingApproval, PendingRetry, SessionState

if TYPE_CHECKING:
    from app.config import BotConfig
    from app.execution_context import ResolvedExecutionContext


# ---------------------------------------------------------------------------
# Pending request validation
# ---------------------------------------------------------------------------

def pending_expired(
    pending: PendingApproval | PendingRetry,
    timeout_seconds: int,
) -> str | None:
    """Return an expiry message if the pending request is too old, else None."""
    created_at = pending.created_at
    if created_at in (None, "", 0, 0.0):
        return None
    ttl = max(3600, timeout_seconds)
    age = age_seconds(created_at, now=utc_now())
    if age is not None and age > ttl:
        minutes = int(age // 60)
        return approval_expired(minutes)
    return None


def current_context_hash(
    session: SessionState,
    config: "BotConfig",
    provider_name: str,
    trust_tier: str = "trusted",
) -> str:
    """Compute the current context hash from session + config.

    trust_tier must match the tier used when the pending request was created,
    otherwise the hash will differ even when nothing actually changed.
    """
    return resolve_execution_context(session, config, provider_name, trust_tier=trust_tier).context_hash


def classify_pending_validation(
    pending: PendingApproval | PendingRetry,
    session: SessionState,
    config: "BotConfig",
    provider_name: str,
) -> str:
    """Classify pending request for the workflow machine.

    Returns "ok" | "expired" | "context_changed". Used by handlers to choose
    the transition (approve_execute / expire / invalidate_stale) and by the
    machine for guards.
    """
    expiry_msg = pending_expired(pending, config.timeout_seconds)
    if expiry_msg:
        return "expired"
    trust_tier = getattr(pending, "trust_tier", "trusted")
    if pending.context_hash and pending.context_hash != current_context_hash(
        session, config, provider_name, trust_tier=trust_tier,
    ):
        return "context_changed"
    return "ok"


def validate_pending(
    pending: PendingApproval | PendingRetry,
    session: SessionState,
    config: "BotConfig",
    provider_name: str,
) -> str | None:
    """Validate a pending request. Returns error message, or None if valid.

    Reads trust_tier from the pending object so the hash is recomputed
    with the same identity shape that created it.
    """
    kind = classify_pending_validation(pending, session, config, provider_name)
    if kind == "expired":
        return pending_expired(pending, config.timeout_seconds) or approval_expired_fallback()
    if kind == "context_changed":
        return approval_context_changed()
    return None


# ---------------------------------------------------------------------------
# Denial helpers
# ---------------------------------------------------------------------------

def extra_dirs_from_denials(denials: list[dict]) -> list[str]:
    """Extract directory paths from permission denial tool_input fields.

    For file paths (file_path, path): add the parent directory.
    For directory values: add the directory itself (not its parent).
    For commands: add "/" (needs broad access).
    """
    dirs: set[str] = set()
    for d in denials:
        inp = d.get("tool_input", {})
        for key in ("file_path", "path"):
            val = inp.get(key, "")
            if val:
                dirs.add(str(Path(val).parent))
        dir_val = inp.get("directory", "")
        if dir_val:
            dirs.add(str(Path(dir_val)))
        if "command" in inp:
            dirs.add("/")
    return list(dirs)
