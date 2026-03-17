"""Health adapters for CLI and Telegram /doctor."""

import dataclasses
from pathlib import Path
from typing import Any, Callable

import httpx

from app.config import BotConfig
from app.providers.base import Provider
from app.storage import list_sessions, load_session
from app.runtime_health import (
    DoctorTextFormatter,
    RuntimeHealthReport,
    SessionHealthContext,
    check_polling_conflict,
    collect_runtime_health_report,
    format_runtime_health_for_doctor,
    scan_stale_delegations as _scan_stale_delegations,
    scan_stale_sessions as _scan_stale_sessions,
)


@dataclasses.dataclass
class DoctorReport:
    infos: list[str] = dataclasses.field(default_factory=list)
    errors: list[str] = dataclasses.field(default_factory=list)
    warnings: list[str] = dataclasses.field(default_factory=list)


def _doctor_report_from_runtime(report: RuntimeHealthReport) -> DoctorReport:
    infos: list[str] = []
    warnings: list[str] = []
    errors: list[str] = []
    for line in format_runtime_health_for_doctor(report, formatter=DoctorTextFormatter()):
        if line.startswith("FAIL: "):
            errors.append(line[6:])
        elif line.startswith("WARN: "):
            warnings.append(line[6:])
        elif line.startswith("INFO: "):
            infos.append(line[6:])
        else:
            infos.append(line)
    return DoctorReport(infos=infos, warnings=warnings, errors=errors)


async def collect_doctor_report(
    config: BotConfig,
    provider: Provider,
    *,
    session: dict[str, Any] | None = None,
    user_id: str | None = None,
    encryption_key: bytes | None = None,
    caller_is_bot: bool = False,
) -> DoctorReport:
    """Compatibility wrapper over canonical runtime health."""
    session_context = None
    if session is not None and user_id is not None and encryption_key is not None:
        session_context = SessionHealthContext(
            session=session,
            user_id=str(user_id),
            encryption_key=encryption_key,
        )
    runtime_report = await collect_runtime_health_report(
        config,
        provider,
        caller_is_bot=caller_is_bot,
        session_context=session_context,
    )
    return _doctor_report_from_runtime(runtime_report)


async def collect_runtime_health(
    config: BotConfig,
    provider: Provider,
    *,
    session: dict[str, Any] | None = None,
    user_id: str | int | None = None,
    encryption_key: bytes | None = None,
    caller_is_bot: bool = False,
) -> RuntimeHealthReport:
    """Collect the canonical runtime-health report for any surface."""
    session_context = None
    if session is not None and user_id is not None and encryption_key is not None:
        session_context = SessionHealthContext(
            session=session,
            user_id=str(user_id),
            encryption_key=encryption_key,
        )
    return await collect_runtime_health_report(
        config,
        provider,
        caller_is_bot=caller_is_bot,
        session_context=session_context,
    )


def format_doctor_report_lines(report: RuntimeHealthReport) -> list[str]:
    """Render the canonical report for Telegram or CLI output."""
    return format_runtime_health_for_doctor(report, formatter=DoctorTextFormatter())


def scan_stale_sessions(
    data_dir: Path,
    provider_name: str,
    provider_state_factory: Callable,
    approval_mode: str,
) -> tuple[int, int]:
    return _scan_stale_sessions(data_dir, provider_name, provider_state_factory, approval_mode)


def scan_stale_delegations(
    data_dir: Path,
    provider_name: str,
    provider_state_factory: Callable,
    approval_mode: str,
    *,
    stale_proposed_seconds: float = 3600,
) -> int:
    return _scan_stale_delegations(
        data_dir,
        provider_name,
        provider_state_factory,
        approval_mode,
        stale_proposed_seconds=stale_proposed_seconds,
    )


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
            data_dir, info["conversation_key"], provider_name,
            provider_state_factory, approval_mode,
        )
        role = session_data.get("role", "")
        warning = check_prompt_size(role, active)
        if warning:
            warnings.append(f"  Conversation {info['conversation_key']}: {warning}")
    return warnings
