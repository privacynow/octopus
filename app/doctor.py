"""Health checks and session diagnostics — shared by CLI and Telegram /doctor."""

import dataclasses
import time
from pathlib import Path
from typing import Any, Callable

from app.config import BotConfig, validate_config
from app.providers.base import Provider
from app.storage import list_sessions, load_session

_STALE_PENDING_SECONDS = 3600   # 1 hour
_STALE_SETUP_SECONDS = 600      # 10 minutes


@dataclasses.dataclass
class DoctorReport:
    errors: list[str] = dataclasses.field(default_factory=list)
    warnings: list[str] = dataclasses.field(default_factory=list)


async def collect_doctor_report(
    config: BotConfig,
    provider: Provider,
    *,
    session: dict[str, Any] | None = None,
    user_id: int | None = None,
    encryption_key: bytes | None = None,
) -> DoctorReport:
    """Run all health checks and return a structured report.

    If session/user_id/encryption_key are provided, also validates
    active skills for the caller's chat.
    """
    report = DoctorReport()

    # Config validation
    report.errors.extend(validate_config(config))

    # Provider health — cheap local check
    report.errors.extend(provider.check_health())

    # Provider runtime health — expensive, skip if already broken
    if not report.errors:
        report.errors.extend(await provider.check_runtime_health())

    # Managed store health
    try:
        from app.store import ensure_managed_dirs, check_schema
        ensure_managed_dirs()
        check_schema()
    except RuntimeError as e:
        report.errors.append(str(e))
    except Exception as e:
        report.errors.append(f"Managed store check failed: {e}")

    # Per-chat skill validation (only from Telegram /doctor)
    if session is not None and user_id is not None and encryption_key is not None:
        from app.skills import validate_active_skills
        report.errors.extend(validate_active_skills(
            session.get("active_skills", []),
            user_id=user_id,
            data_dir=config.data_dir,
            encryption_key=encryption_key,
        ))

    # Advisory: admin not explicitly set
    total_users = len(config.allowed_user_ids) + len(config.allowed_usernames)
    if total_users > 1 and not config.admin_users_explicit:
        report.warnings.append(
            "BOT_ADMIN_USERS not set \u2014 all allowed users have admin "
            "privileges (install/uninstall skills). Set BOT_ADMIN_USERS to restrict.")

    # Stale session scan
    stale_pending, stale_setup = scan_stale_sessions(
        config.data_dir, config.provider_name,
        provider.new_provider_state, config.approval_mode,
    )
    if stale_pending:
        report.warnings.append(
            f"{stale_pending} session(s) with stale pending approval requests (>1h old).")
    if stale_setup:
        report.warnings.append(
            f"{stale_setup} session(s) with stale credential setup (>10m old).")

    return report


def scan_stale_sessions(
    data_dir: Path,
    provider_name: str,
    provider_state_factory: Callable,
    approval_mode: str,
) -> tuple[int, int]:
    """Scan sessions for stale pending/setup entries.

    Returns (stale_pending_count, stale_setup_count).
    """
    stale_pending = 0
    stale_setup = 0
    now = time.time()
    for info in list_sessions(data_dir):
        if not info["has_pending"] and not info["has_setup"]:
            continue
        session_data = load_session(
            data_dir, info["chat_id"], provider_name,
            provider_state_factory, approval_mode,
        )
        pending = session_data.get("pending_request")
        if pending and (now - pending.get("created_at", 0)) > _STALE_PENDING_SECONDS:
            stale_pending += 1
        setup = session_data.get("awaiting_skill_setup")
        if setup and (now - setup.get("started_at", 0)) > _STALE_SETUP_SECONDS:
            stale_setup += 1
    return stale_pending, stale_setup


def check_prompt_size_cross_chat(
    data_dir: Path,
    skill_name: str,
    provider_name: str,
    provider_state_factory: Callable,
    approval_mode: str,
) -> list[str]:
    """Check prompt size in all chats where skill_name is active.

    Returns list of warning strings for chats over threshold.
    """
    from app.skills import filter_resolvable_skills, check_prompt_size
    warnings: list[str] = []
    for info in list_sessions(data_dir):
        active = filter_resolvable_skills(info.get("active_skills", []))
        if skill_name not in active:
            continue
        session_data = load_session(
            data_dir, info["chat_id"], provider_name,
            provider_state_factory, approval_mode,
        )
        role = session_data.get("role", "")
        warning = check_prompt_size(role, active)
        if warning:
            warnings.append(f"  Chat {info['chat_id']}: {warning}")
    return warnings
