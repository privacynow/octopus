"""Request orchestration — pure business logic, no transport dependency.

This module contains the service-layer logic for request execution,
approval validation, credential satisfaction, and denial handling.
Handlers call these functions and handle the transport (message sending,
progress bars, inline buttons) themselves.

Design rules:
- No Telegram imports.  No message sending.  No progress updates.
- Functions receive explicit parameters (no module-global singletons).
- Returns typed results; handlers decide how to render them.
- Execution-scope fields (active_skills, working_dir, file_policy, etc.)
  must come from ResolvedExecutionContext, never from raw SessionState.
"""

from __future__ import annotations

import html
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from app.execution_context import resolve_execution_context
from app.user_messages import (
    approval_context_changed,
    approval_expired,
    approval_expired_fallback,
)
from app.session_state import (
    AwaitingSkillSetup,
    PendingApproval,
    PendingRetry,
    SessionState,
)
from app.skills import (
    SkillRequirement,
    build_credential_env,
    check_credentials,
    load_user_credentials,
)

if TYPE_CHECKING:
    from app.config import BotConfig
    from app.execution_context import ResolvedExecutionContext


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SETUP_TIMEOUT_SECONDS = 300  # 5 minutes


# ---------------------------------------------------------------------------
# Credential flow
# ---------------------------------------------------------------------------

def build_setup_state(
    user_id: int,
    skill_name: str,
    missing: list[SkillRequirement],
) -> AwaitingSkillSetup:
    """Build credential-collection state for a skill."""
    return AwaitingSkillSetup(
        user_id=user_id,
        skill=skill_name,
        started_at=time.time(),
        remaining=[
            {"key": r.key, "prompt": r.prompt, "help_url": r.help_url,
             "validate": r.validate}
            for r in missing
        ],
    )


def format_credential_prompt(req: dict) -> str:
    """Format a credential prompt for a single requirement.

    Returns HTML-safe text. help_url is rendered as a clickable Telegram link.
    """
    text = html.escape(req["prompt"])
    if req.get("help_url"):
        url = html.escape(req["help_url"])
        text += f'\n(<a href="{url}">setup guide</a>)'
    return text


def foreign_setup_message(setup: AwaitingSkillSetup) -> str:
    """Format a message about another user's in-progress credential setup."""
    uid = setup.user_id
    elapsed = int(time.time() - setup.started_at)
    minutes = elapsed // 60
    time_str = f"{minutes} min ago" if minutes >= 1 else "just now"
    return (
        f"User {uid} is completing credential setup (started {time_str}). "
        f"Please wait or ask them to finish. An admin can use /cancel to clear it."
    )


def foreign_skill_setup(
    session: SessionState,
    user_id: int,
    skill_name: str | None = None,
) -> AwaitingSkillSetup | None:
    """Return another user's in-progress setup, optionally filtered by skill.

    Auto-expires setups older than SETUP_TIMEOUT_SECONDS so a disappeared
    user can't wedge a shared chat indefinitely.  Mutates session on expiry.
    """
    setup = session.awaiting_skill_setup
    if not setup or setup.user_id == user_id:
        return None
    if skill_name is not None and setup.skill != skill_name:
        return None
    if setup.started_at is None or (time.time() - setup.started_at) > SETUP_TIMEOUT_SECONDS:
        session.awaiting_skill_setup = None
        return None
    return setup


@dataclass
class CredentialCheckResult:
    """Result of checking credential satisfaction for active skills."""
    satisfied: bool
    credential_env: dict[str, str]
    # If not satisfied, one of these is set:
    foreign_setup: AwaitingSkillSetup | None = None  # another user is setting up
    missing_skill: str = ""  # skill that needs setup
    missing_reqs: list[SkillRequirement] | None = None
    setup_state: AwaitingSkillSetup | None = None  # freshly created setup


def check_credential_satisfaction(
    active_skills: list[str],
    session: SessionState,
    user_id: int,
    data_dir: Path,
    encryption_key: bytes,
) -> CredentialCheckResult:
    """Check whether all active skills have credentials.

    active_skills: the resolved skill list (from ResolvedExecutionContext),
    NOT raw session.active_skills.  Public users pass an empty list.

    Pure logic — does not send messages or save session.
    Caller must handle the result (send prompts, save setup state, etc.).
    """
    if not active_skills:
        return CredentialCheckResult(satisfied=True, credential_env={})

    user_creds = load_user_credentials(data_dir, user_id, encryption_key)

    all_missing: list[tuple[str, list[SkillRequirement]]] = []
    for skill_name in active_skills:
        missing = check_credentials(skill_name, user_creds)
        if missing:
            all_missing.append((skill_name, missing))

    if not all_missing:
        env = build_credential_env(active_skills, user_creds)
        return CredentialCheckResult(satisfied=True, credential_env=env)

    # Check for foreign setup blocking this user
    foreign = foreign_skill_setup(session, user_id)
    if foreign:
        return CredentialCheckResult(
            satisfied=False, credential_env={},
            foreign_setup=session.awaiting_skill_setup,
        )

    # Start setup for first missing skill
    skill_name, missing = all_missing[0]
    setup = build_setup_state(user_id, skill_name, missing)
    return CredentialCheckResult(
        satisfied=False, credential_env={},
        missing_skill=skill_name, missing_reqs=missing,
        setup_state=setup,
    )


# ---------------------------------------------------------------------------
# Pending request validation
# ---------------------------------------------------------------------------

def pending_expired(
    pending: PendingApproval | PendingRetry,
    timeout_seconds: int,
) -> str | None:
    """Return an expiry message if the pending request is too old, else None."""
    created_at = pending.created_at
    if not created_at:
        return None
    ttl = max(3600, timeout_seconds)
    age = time.time() - created_at
    if age > ttl:
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
