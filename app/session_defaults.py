"""Pure session default factory. Shared by storage facade and SQLite/Postgres backends."""

from datetime import datetime, timezone
from typing import Any


def default_session(
    provider_name: str,
    provider_state: dict[str, Any],
    approval_mode: str,
    role: str = "",
    default_skills: tuple[str, ...] = (),
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "provider": provider_name,
        "provider_state": provider_state,
        "approval_mode": approval_mode,
        "active_skills": list(default_skills),
        "role": role,
        "pending_approval": None,
        "pending_retry": None,
        "awaiting_skill_setup": None,
        "created_at": now,
        "updated_at": now,
    }
