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

from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from octopus_sdk.execution_context import resolve_execution_context
from octopus_sdk.sessions import PendingApproval, PendingRetry, SessionState

if TYPE_CHECKING:
    from octopus_sdk.config import BotConfigBase
    from octopus_sdk.execution_context import ResolvedExecutionContext, SkillCatalogView


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _approval_expired(minutes: int) -> str:
    return f"This request has expired (it was created {minutes} minutes ago). Please send your message again."


def _approval_expired_fallback() -> str:
    return "This request has expired."


def _approval_context_changed() -> str:
    return "This request can't continue because the chat context changed. Please send your message again."


def _age_seconds(created_at: float | str, *, now: datetime) -> float | None:
    if created_at in (None, "", 0, 0.0):
        return None
    if isinstance(created_at, (int, float)):
        return max(0.0, float(now.timestamp()) - float(created_at))
    try:
        parsed = datetime.fromisoformat(str(created_at))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(0.0, (now - parsed.astimezone(timezone.utc)).total_seconds())


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
    age = _age_seconds(created_at, now=_utc_now())
    if age is not None and age > ttl:
        minutes = int(age // 60)
        return _approval_expired(minutes)
    return None


def current_context_hash(
    session: SessionState,
    config: "BotConfigBase",
    provider_name: str,
    trust_tier: str = "trusted",
    *,
    catalog: "SkillCatalogView | None" = None,
) -> str:
    """Compute the current context hash from session + config.

    trust_tier must match the tier used when the pending request was created,
    otherwise the hash will differ even when nothing actually changed.
    """
    return resolve_execution_context(
        session,
        config,
        provider_name,
        trust_tier=trust_tier,
        catalog=catalog,
    ).context_hash


def classify_pending_validation(
    pending: PendingApproval | PendingRetry,
    session: SessionState,
    config: "BotConfigBase",
    provider_name: str,
    *,
    catalog: "SkillCatalogView | None" = None,
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
        session,
        config,
        provider_name,
        trust_tier=trust_tier,
        catalog=catalog,
    ):
        return "context_changed"
    return "ok"


def validate_pending(
    pending: PendingApproval | PendingRetry,
    session: SessionState,
    config: "BotConfigBase",
    provider_name: str,
    *,
    catalog: "SkillCatalogView | None" = None,
) -> str | None:
    """Validate a pending request. Returns error message, or None if valid.

    Reads trust_tier from the pending object so the hash is recomputed
    with the same identity shape that created it.
    """
    kind = classify_pending_validation(
        pending,
        session,
        config,
        provider_name,
        catalog=catalog,
    )
    if kind == "expired":
        return pending_expired(pending, config.timeout_seconds) or _approval_expired_fallback()
    if kind == "context_changed":
        return _approval_context_changed()
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
