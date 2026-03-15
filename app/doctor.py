"""Health checks and session diagnostics — shared by CLI and Telegram /doctor."""

import dataclasses
import logging
import time
from pathlib import Path
from typing import Any, Callable

import httpx

from app.config import BotConfig, validate_config
from app.providers.base import Provider
from app.storage import list_sessions, load_session

log = logging.getLogger(__name__)

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
    caller_is_bot: bool = False,
) -> DoctorReport:
    """Run all health checks and return a structured report.

    If session/user_id/encryption_key are provided, also validates
    active skills for the caller's chat.

    caller_is_bot: set True when called from within a running bot process
    (poll or webhook mode).  This skips the getUpdates conflict probe,
    which would 409 against its own poller or conflict with an active webhook.
    """
    report = DoctorReport()

    # Config validation
    report.errors.extend(validate_config(config))

    # Provider health — cheap local check
    report.errors.extend(provider.check_health())

    # Managed store health — cheap local check, run before expensive runtime probe
    try:
        from app.store import ensure_managed_dirs, check_schema
        ensure_managed_dirs()
        check_schema()
    except RuntimeError as e:
        report.errors.append(str(e))
    except Exception as e:
        report.errors.append(f"Managed store check failed: {e}")

    # Provider runtime health — expensive, skip if any cheap check already failed
    if not report.errors:
        report.errors.extend(await provider.check_runtime_health())

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

    # Polling conflict detection
    if config.bot_mode == "poll" and config.webhook_url:
        report.warnings.append(
            "Bot is in polling mode but BOT_WEBHOOK_URL is configured. "
            "If another process is running in webhook mode, updates may conflict. "
            "Use only one delivery mode per bot token.")
    # Only probe getUpdates from CLI --doctor.  A running bot in poll mode
    # would 409 against its own poller; in webhook mode, getUpdates conflicts
    # with the active webhook per Telegram API contract.
    if not caller_is_bot:
        conflict = await check_polling_conflict(config.telegram_token)
        if conflict:
            report.warnings.append(conflict)

    # Public mode advisories
    if config.allow_open:
        if not config.public_working_dir:
            report.warnings.append(
                "BOT_ALLOW_OPEN=1 but BOT_PUBLIC_WORKING_DIR not set \u2014 "
                "public users will use the operator's main working directory. "
                "Set BOT_PUBLIC_WORKING_DIR to isolate public access.")
        if config.rate_limit_per_minute == 0 and config.rate_limit_per_hour == 0:
            report.warnings.append(
                "BOT_ALLOW_OPEN=1 with no rate limits configured \u2014 "
                "public users could overwhelm the bot. "
                "Set BOT_RATE_LIMIT_PER_MINUTE / BOT_RATE_LIMIT_PER_HOUR "
                "or defaults of 5/min, 30/hr will apply.")

    # Stale session scan — skip if data_dir doesn't exist yet (CLI --doctor before first run)
    if config.data_dir.is_dir():
        try:
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
        except Exception as e:
            # SQLite, Postgres (e.g. psycopg.OperationalError), and other storage/connection errors
            report.errors.append(f"Session database error: {e}")

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
        pending = session_data.get("pending_approval") or session_data.get("pending_retry")
        if pending and (now - pending.get("created_at", 0)) > _STALE_PENDING_SECONDS:
            stale_pending += 1
        setup = session_data.get("awaiting_skill_setup")
        if setup and (now - setup.get("started_at", 0)) > _STALE_SETUP_SECONDS:
            stale_setup += 1
    return stale_pending, stale_setup


async def check_polling_conflict(token: str) -> str | None:
    """Probe Telegram getUpdates to detect a conflicting poller.

    Telegram returns HTTP 409 Conflict when another process is already
    polling with the same token.  Returns a warning string if conflict
    detected, None otherwise.
    """
    # Skip probe if the token looks invalid (test tokens, placeholders)
    # Real tokens are ~46 chars like "123456789:AABBCCDDEEFFGGHHIIJJKKLLMMNNOOPPxx"
    parts = token.split(":", 1)
    if len(parts) != 2 or not parts[0].isdigit() or len(parts[1]) < 30:
        return None
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.post(url, json={"limit": 1, "timeout": 0})
        if resp.status_code == 409:
            return (
                "Polling conflict detected (HTTP 409) — another process is already "
                "polling with this bot token. Stop the other process or switch to "
                "webhook mode.")
    except Exception as e:
        log.debug("Polling conflict check failed: %s", e)
    return None


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
