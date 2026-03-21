"""Canonical runtime-health collection, projection, and formatting."""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Generic, Protocol, TYPE_CHECKING, TypeVar

import httpx

from app.config import ProcessRole, RuntimeMode, validate_config
from app.registry_errors import registry_error_detail
from app.session_state import session_from_dict
from app.storage import list_sessions, load_session
from app.time_utils import age_seconds, utc_now

if TYPE_CHECKING:
    from app.config import BotConfig
    from app.providers.base import Provider

log = logging.getLogger(__name__)

_RUNTIME_HEALTH_SCHEMA_VERSION = 1
_STALE_PENDING_SECONDS = 3600
_STALE_SETUP_SECONDS = 600
_STALE_DELEGATION_SECONDS = 3600
_STALE_WORKER_HEARTBEAT_SECONDS = 90.0


@dataclass(frozen=True)
class QueueSnapshot:
    """Backend-neutral queue summary for Shared Runtime observability."""

    fresh_queued_count: int = 0
    recovery_queued_count: int = 0
    claimed_count: int = 0
    pending_recovery_count: int = 0
    cancel_requested_claimed_count: int = 0
    oldest_fresh_queued_at: str | None = None
    oldest_recovery_queued_at: str | None = None
    oldest_claimed_at: str | None = None
    oldest_pending_recovery_at: str | None = None


@dataclass(frozen=True)
class WorkerHeartbeat:
    """Durable liveness snapshot for a worker process."""

    worker_id: str
    process_role: str
    started_at: str
    last_seen_at: str
    current_item_id: str = ""
    current_conversation_key: str = ""
    current_kind: str = ""
    items_processed: int = 0
    stale_recoveries_seen: int = 0
    last_error: str = ""


@dataclass(frozen=True)
class SharedRuntimeSnapshot:
    """Combined queue and worker summary for operator channels."""

    queue: QueueSnapshot = field(default_factory=QueueSnapshot)
    workers: tuple[WorkerHeartbeat, ...] = ()
    healthy_worker_count: int = 0
    stale_worker_count: int = 0


@dataclass(frozen=True)
class RuntimeDiagnostic:
    """One normalized health observation."""

    level: str
    code: str
    message: str


@dataclass(frozen=True)
class RuntimeHealthSummary:
    """Compact health summary derived once from the canonical report."""

    status: str = "healthy"
    healthy_worker_count: int = 0
    stale_worker_count: int = 0
    fresh_queued_count: int = 0
    claimed_count: int = 0
    pending_recovery_count: int = 0
    recovery_queued_count: int = 0
    oldest_claim_age_seconds: int | None = None
    warning_count: int = 0
    error_count: int = 0


@dataclass(frozen=True)
class RuntimeHealthReport:
    """Canonical runtime-health report shared by all operator channels."""

    schema_version: int = _RUNTIME_HEALTH_SCHEMA_VERSION
    generated_at: str = field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )
    summary: RuntimeHealthSummary = field(default_factory=RuntimeHealthSummary)
    snapshot: SharedRuntimeSnapshot | None = None
    diagnostics: tuple[RuntimeDiagnostic, ...] = ()


@dataclass(frozen=True)
class SessionHealthContext:
    """Optional per-conversation context for session-aware checks."""

    session: dict[str, Any]
    user_id: str
    resolved_active_skills: tuple[str, ...] = ()


class RuntimeHealthProvider(Protocol):
    """Collect canonical runtime-health reports."""

    async def collect(
        self,
        config: BotConfig,
        provider: Provider,
        *,
        caller_is_bot: bool = False,
        session_context: SessionHealthContext | None = None,
    ) -> RuntimeHealthReport:
        ...


T = TypeVar("T")


class RuntimeHealthProjector(Protocol, Generic[T]):
    """Project canonical health into another channel's wire/storage shape."""

    def project(self, report: RuntimeHealthReport) -> T:
        ...


class RuntimeHealthFormatter(Protocol):
    """Format canonical health for human-readable channels."""

    def format(self, report: RuntimeHealthReport) -> list[str] | str:
        ...


def _diag(level: str, code: str, message: str) -> RuntimeDiagnostic:
    return RuntimeDiagnostic(level=level, code=code, message=message)


def _content_store_failure_message(exc: BaseException) -> str:
    return (
        "Content store check failed: "
        f"{exc.__class__.__name__}. "
        "Check BOT_DATABASE_URL and content-store connectivity."
    )


def _session_store_failure_message(exc: BaseException) -> str:
    text = str(exc).lower()
    if "not a database" in text or "corrupt" in text:
        return "Session database appears corrupt or unreadable."
    if "schema" in text or "newer" in text:
        return (
            "Session database schema is newer than this bot build. "
            "Upgrade the bot or rebuild the session store with a compatible version."
        )
    return (
        "Session database error: "
        f"{exc.__class__.__name__}. "
        "Check session-store integrity and database connectivity."
    )


def _shared_runtime_failure_message(exc: BaseException) -> str:
    return (
        "Shared Runtime health check failed: "
        f"{exc.__class__.__name__}. "
        "Check the work queue and runtime storage backend."
    )


def _summary_status(diagnostics: tuple[RuntimeDiagnostic, ...]) -> str:
    if any(item.level == "error" for item in diagnostics):
        return "unhealthy"
    if any(item.level == "warning" for item in diagnostics):
        return "degraded"
    return "healthy"


def _build_summary(
    diagnostics: tuple[RuntimeDiagnostic, ...],
    snapshot: SharedRuntimeSnapshot | None,
) -> RuntimeHealthSummary:
    queue = snapshot.queue if snapshot else QueueSnapshot()
    oldest_claim_age = age_seconds(queue.oldest_claimed_at, now=utc_now())
    return RuntimeHealthSummary(
        status=_summary_status(diagnostics),
        healthy_worker_count=snapshot.healthy_worker_count if snapshot else 0,
        stale_worker_count=snapshot.stale_worker_count if snapshot else 0,
        fresh_queued_count=queue.fresh_queued_count,
        claimed_count=queue.claimed_count,
        pending_recovery_count=queue.pending_recovery_count,
        recovery_queued_count=queue.recovery_queued_count,
        oldest_claim_age_seconds=None if oldest_claim_age is None else int(max(0, oldest_claim_age)),
        warning_count=sum(1 for item in diagnostics if item.level == "warning"),
        error_count=sum(1 for item in diagnostics if item.level == "error"),
    )


def report_to_dict(report: RuntimeHealthReport) -> dict[str, Any]:
    """Convert a canonical health report into a JSON-safe mapping."""
    return _to_wire(report)


def report_from_dict(payload: dict[str, Any] | None) -> RuntimeHealthReport | None:
    """Rehydrate a canonical health report from a stored mapping."""
    if not payload:
        return None
    summary = payload.get("summary") or {}
    snapshot = payload.get("snapshot")
    diagnostics = tuple(
        RuntimeDiagnostic(
            level=str(item.get("level", "info")),
            code=str(item.get("code", "")),
            message=str(item.get("message", "")),
        )
        for item in (payload.get("diagnostics") or [])
        if isinstance(item, dict)
    )
    hydrated_snapshot: SharedRuntimeSnapshot | None = None
    if isinstance(snapshot, dict):
        queue_payload = snapshot.get("queue") or {}
        workers_payload = snapshot.get("workers") or []
        hydrated_snapshot = SharedRuntimeSnapshot(
            queue=QueueSnapshot(
                fresh_queued_count=int(queue_payload.get("fresh_queued_count", 0) or 0),
                recovery_queued_count=int(queue_payload.get("recovery_queued_count", 0) or 0),
                claimed_count=int(queue_payload.get("claimed_count", 0) or 0),
                pending_recovery_count=int(queue_payload.get("pending_recovery_count", 0) or 0),
                cancel_requested_claimed_count=int(queue_payload.get("cancel_requested_claimed_count", 0) or 0),
                oldest_fresh_queued_at=queue_payload.get("oldest_fresh_queued_at"),
                oldest_recovery_queued_at=queue_payload.get("oldest_recovery_queued_at"),
                oldest_claimed_at=queue_payload.get("oldest_claimed_at"),
                oldest_pending_recovery_at=queue_payload.get("oldest_pending_recovery_at"),
            ),
            workers=tuple(
                WorkerHeartbeat(
                    worker_id=str(worker.get("worker_id", "")),
                    process_role=str(worker.get("process_role", "")),
                    started_at=str(worker.get("started_at", "")),
                    last_seen_at=str(worker.get("last_seen_at", "")),
                    current_item_id=str(worker.get("current_item_id", "")),
                    current_conversation_key=str(worker.get("current_conversation_key", "")),
                    current_kind=str(worker.get("current_kind", "")),
                    items_processed=int(worker.get("items_processed", 0) or 0),
                    stale_recoveries_seen=int(worker.get("stale_recoveries_seen", 0) or 0),
                    last_error=str(worker.get("last_error", "")),
                )
                for worker in workers_payload
                if isinstance(worker, dict)
            ),
            healthy_worker_count=int(snapshot.get("healthy_worker_count", 0) or 0),
            stale_worker_count=int(snapshot.get("stale_worker_count", 0) or 0),
        )
    return RuntimeHealthReport(
        schema_version=int(payload.get("schema_version", _RUNTIME_HEALTH_SCHEMA_VERSION) or _RUNTIME_HEALTH_SCHEMA_VERSION),
        generated_at=str(payload.get("generated_at", "") or ""),
        summary=RuntimeHealthSummary(
            status=str(summary.get("status", "healthy")),
            healthy_worker_count=int(summary.get("healthy_worker_count", 0) or 0),
            stale_worker_count=int(summary.get("stale_worker_count", 0) or 0),
            fresh_queued_count=int(summary.get("fresh_queued_count", 0) or 0),
            claimed_count=int(summary.get("claimed_count", 0) or 0),
            pending_recovery_count=int(summary.get("pending_recovery_count", 0) or 0),
            recovery_queued_count=int(summary.get("recovery_queued_count", 0) or 0),
            oldest_claim_age_seconds=(
                None
                if summary.get("oldest_claim_age_seconds") in (None, "")
                else int(summary.get("oldest_claim_age_seconds", 0))
            ),
            warning_count=int(summary.get("warning_count", 0) or 0),
            error_count=int(summary.get("error_count", 0) or 0),
        ),
        snapshot=hydrated_snapshot,
        diagnostics=diagnostics,
    )


class RuntimeHealthJsonProjector(RuntimeHealthProjector[dict[str, Any]]):
    """Project canonical runtime health into a JSON-safe dict."""

    def project(self, report: RuntimeHealthReport) -> dict[str, Any]:
        return report_to_dict(report)


class DoctorTextFormatter(RuntimeHealthFormatter):
    """Render canonical runtime health for Telegram/CLI doctor channels."""

    def format(self, report: RuntimeHealthReport) -> list[str]:
        parts: list[str] = []
        parts.append(f"Overall status: {report.summary.status}")
        if report.snapshot is not None:
            parts.append(
                "Shared Runtime workers: "
                f"{report.summary.healthy_worker_count} healthy, "
                f"{report.summary.stale_worker_count} stale"
            )
            parts.append(
                "Queue: "
                f"{report.summary.fresh_queued_count} fresh queued, "
                f"{report.summary.claimed_count} claimed, "
                f"{report.summary.pending_recovery_count} pending recovery, "
                f"{report.summary.recovery_queued_count} recovery queued"
            )
            if report.summary.oldest_claim_age_seconds is not None:
                parts.append(
                    f"Oldest claim age: {_format_age_label(float(report.summary.oldest_claim_age_seconds))}"
                )
        for item in report.diagnostics:
            prefix = {
                "info": "INFO",
                "warning": "WARN",
                "error": "FAIL",
            }.get(item.level, item.level.upper())
            parts.append(f"{prefix}: {item.message}")
        return parts


class CanonicalRuntimeHealthProvider(RuntimeHealthProvider):
    """Single owner of runtime-health collection and evaluation rules."""

    async def collect(
        self,
        config: BotConfig,
        provider: Provider,
        *,
        caller_is_bot: bool = False,
        session_context: SessionHealthContext | None = None,
    ) -> RuntimeHealthReport:
        diagnostics: list[RuntimeDiagnostic] = []
        snapshot: SharedRuntimeSnapshot | None = None

        diagnostics.extend(
            _diag("error", "config.invalid", message)
            for message in validate_config(config)
        )
        diagnostics.extend(
            _diag("error", "provider.health_failed", message)
            for message in provider.check_health()
        )

        try:
            from app.content_store import get_content_store

            get_content_store()
        except Exception as exc:
            log.exception(
                "Content store health check failed: %s",
                exc.__class__.__name__,
            )
            diagnostics.append(
                _diag(
                    "error",
                    "content_store.health_failed",
                    _content_store_failure_message(exc),
                )
            )

        if not any(item.level == "error" for item in diagnostics) and config.process_role != ProcessRole.WEBHOOK.value:
            diagnostics.extend(
                _diag("error", "provider.runtime_unavailable", message)
                for message in await provider.check_runtime_health()
            )

        if session_context is not None:
            from app.skill_catalog_service import get_skill_catalog_service
            from app.credential_service import get_credential_service

            credential_service = get_credential_service()

            user_credentials = credential_service.load_for_skills(
                session_context.user_id,
                list(session_context.resolved_active_skills),
            )
            for skill_name in session_context.resolved_active_skills:
                missing = credential_service.missing_requirements(
                    get_skill_catalog_service().requirements(skill_name),
                    user_credentials.get(skill_name, {}),
                )
                if not missing:
                    continue
                missing_keys = ", ".join(item.key for item in missing)
                diagnostics.append(
                    _diag(
                        "warning",
                        "skills.missing_credentials",
                        f"Missing credentials for {skill_name}: {missing_keys}",
                    )
                )

        total_users = len(config.allowed_actor_keys) + len(config.allowed_usernames)
        if total_users > 1 and not config.admin_users_explicit:
            diagnostics.append(
                _diag(
                    "warning",
                    "auth.admins_unrestricted",
                    "BOT_ADMIN_USERS not set — all allowed users have admin privileges (install/uninstall skills). Set BOT_ADMIN_USERS to restrict.",
                )
            )

        if config.bot_mode == "poll" and config.webhook_url:
            diagnostics.append(
                _diag(
                    "warning",
                    "telegram.webhook_poll_mismatch",
                    "Bot is in polling mode but BOT_WEBHOOK_URL is configured. If another process is running in webhook mode, updates may conflict. Use only one delivery mode per bot token.",
                )
            )
        if not caller_is_bot:
            conflict = await check_polling_conflict(config.telegram_token)
            if conflict:
                diagnostics.append(_diag("warning", "telegram.polling_conflict", conflict))

        if config.allow_open:
            if not config.public_working_dir:
                diagnostics.append(
                    _diag(
                        "warning",
                        "public.missing_working_dir",
                        "BOT_ALLOW_OPEN=1 but BOT_PUBLIC_WORKING_DIR not set — public users will use the operator's main working directory. Set BOT_PUBLIC_WORKING_DIR to isolate public access.",
                    )
                )
            if config.rate_limit_per_minute == 0 and config.rate_limit_per_hour == 0:
                diagnostics.append(
                    _diag(
                        "warning",
                        "public.no_rate_limit",
                        "BOT_ALLOW_OPEN=1 with no rate limits configured — public users could overwhelm the bot. Set BOT_RATE_LIMIT_PER_MINUTE / BOT_RATE_LIMIT_PER_HOUR or defaults of 5/min, 30/hr will apply.",
                    )
                )

        diagnostics.extend(_collect_registry_diagnostics(config))

        if config.data_dir.is_dir():
            try:
                stale_pending, stale_setup = scan_stale_sessions(
                    config.data_dir,
                    config.provider_name,
                    provider.new_provider_state,
                    config.approval_mode,
                )
                if stale_pending:
                    diagnostics.append(
                        _diag(
                            "warning",
                            "session.stale_pending",
                            f"{stale_pending} session(s) with stale pending approval requests (>1h old).",
                        )
                    )
                if stale_setup:
                    diagnostics.append(
                        _diag(
                            "warning",
                            "session.stale_setup",
                            f"{stale_setup} session(s) with stale credential setup (>10m old).",
                        )
                    )
                stale_delegation = scan_stale_delegations(
                    config.data_dir,
                    config.provider_name,
                    provider.new_provider_state,
                    config.approval_mode,
                )
                if stale_delegation:
                    diagnostics.append(
                        _diag(
                            "warning",
                            "delegation.stale_proposed",
                            f"{stale_delegation} session(s) with delegation plans awaiting user approval for >1h. The user has not approved or cancelled delegation. Use /doctor in-chat to review.",
                        )
                    )
            except Exception as exc:
                log.exception(
                    "Session database health check failed: %s",
                    exc.__class__.__name__,
                )
                diagnostics.append(
                    _diag(
                        "error",
                        "session.db_error",
                        _session_store_failure_message(exc),
                    )
                )

        snapshot, shared_diagnostics = _collect_shared_runtime_snapshot(config)
        diagnostics.extend(shared_diagnostics)

        diagnostics_tuple = tuple(diagnostics)
        return RuntimeHealthReport(
            summary=_build_summary(diagnostics_tuple, snapshot),
            snapshot=snapshot,
            diagnostics=diagnostics_tuple,
        )


def _collect_registry_diagnostics(config: BotConfig) -> list[RuntimeDiagnostic]:
    diagnostics: list[RuntimeDiagnostic] = []
    if config.agent_mode != "registry":
        return diagnostics

    if not config.agent_registries:
        diagnostics.append(
            _diag(
                "warning",
                "registry.missing_connections",
                "BOT_AGENT_MODE=registry but no BOT_AGENT_REGISTRY_<n>_* connections are configured.",
            )
        )
        return diagnostics
    if not config.data_dir.is_dir():
        return diagnostics

    from app.agents.state import load_runtime_registry_connection_state

    for registry in config.agent_registries:
        if not registry.url:
            diagnostics.append(
                _diag(
                    "warning",
                    "registry.missing_url",
                    f"Registry '{registry.registry_id}' is missing a URL. This connection will stay degraded until configured.",
                )
            )
        if not registry.enroll_token:
            diagnostics.append(
                _diag(
                    "warning",
                    "registry.missing_enroll_token",
                    f"Registry '{registry.registry_id}' is missing an enrollment token. First-time enrollment will fail until a token is provided.",
                )
            )

        agent_state = load_runtime_registry_connection_state(
            config.data_dir,
            registry.registry_id,
            registry_scope=registry.registry_scope,
        )
        if agent_state.connectivity_state == "degraded":
            detail_text = registry_error_detail(agent_state.last_error, agent_state.last_error_detail)
            detail = f": {detail_text}" if detail_text else ""
            diagnostics.append(
                _diag(
                    "warning",
                    "registry.degraded_connectivity",
                    f"Registry '{registry.registry_id}' connectivity is degraded{detail}.",
                )
            )
        elif agent_state.connectivity_state == "standalone":
            if not agent_state.agent_id:
                diagnostics.append(
                    _diag(
                        "warning",
                        "registry.not_enrolled",
                        f"Registry '{registry.registry_id}' enrollment has not completed.",
                    )
                )
        elif agent_state.connectivity_state == "connected" and not agent_state.agent_id:
            diagnostics.append(
                _diag(
                    "warning",
                    "registry.missing_agent_id",
                    "Registry '%s' reports connected but agent_id is missing — state may be corrupt. "
                    "Delete data/agent/registries/%s.json and restart."
                    % (registry.registry_id, registry.registry_id),
                )
            )

        if agent_state.last_successful_contact_at:
            try:
                last = datetime.datetime.fromisoformat(agent_state.last_successful_contact_at)
                if last.tzinfo is None:
                    last = last.replace(tzinfo=datetime.timezone.utc)
                age = (datetime.datetime.now(datetime.timezone.utc) - last).total_seconds()
                if age > 300:
                    minutes = int(age // 60)
                    diagnostics.append(
                        _diag(
                            "warning",
                            "registry.stale_contact",
                            f"Registry '{registry.registry_id}': last successful contact was {minutes}m ago.",
                        )
                    )
            except ValueError:
                pass

    return diagnostics


def _collect_shared_runtime_snapshot(
    config: BotConfig,
) -> tuple[SharedRuntimeSnapshot | None, list[RuntimeDiagnostic]]:
    diagnostics: list[RuntimeDiagnostic] = []
    if config.runtime_mode != RuntimeMode.SHARED.value:
        return None, diagnostics
    if not config.database_url and not config.data_dir.is_dir():
        diagnostics.append(
            _diag(
                "warning",
                "shared.data_dir_uninitialized",
                "Shared Runtime data directory has not been initialized yet.",
            )
        )
        return None, diagnostics

    try:
        from app import work_queue

        queue = work_queue.get_queue_snapshot(config.data_dir)
        workers = work_queue.list_worker_heartbeats(config.data_dir)
    except Exception as exc:
        log.exception(
            "Shared Runtime health check failed: %s",
            exc.__class__.__name__,
        )
        diagnostics.append(
            _diag(
                "error",
                "shared.health_check_failed",
                _shared_runtime_failure_message(exc),
            )
        )
        return None, diagnostics

    now = utc_now()
    healthy_workers: list[WorkerHeartbeat] = []
    stale_workers: list[WorkerHeartbeat] = []
    total_stale_recoveries = 0
    for heartbeat in workers:
        total_stale_recoveries += heartbeat.stale_recoveries_seen
        last_seen_age = age_seconds(heartbeat.last_seen_at, now=now)
        if last_seen_age is not None and last_seen_age <= _STALE_WORKER_HEARTBEAT_SECONDS:
            healthy_workers.append(heartbeat)
        else:
            stale_workers.append(heartbeat)

    snapshot = SharedRuntimeSnapshot(
        queue=queue,
        workers=tuple(workers),
        healthy_worker_count=len(healthy_workers),
        stale_worker_count=len(stale_workers),
    )

    if not healthy_workers:
        diagnostics.append(
            _diag(
                "error",
                "shared.no_healthy_workers",
                "Shared Runtime has no healthy worker heartbeats within 90s.",
            )
        )
    elif stale_workers:
        stale_ids = ", ".join(sorted(item.worker_id for item in stale_workers))
        diagnostics.append(
            _diag(
                "warning",
                "shared.stale_worker_heartbeats",
                f"Shared Runtime has {len(stale_workers)} stale worker heartbeat(s): {stale_ids}",
            )
        )

    oldest_claim_age = age_seconds(queue.oldest_claimed_at, now=now)
    if oldest_claim_age is not None:
        if oldest_claim_age >= config.claim_lease_ttl_seconds:
            diagnostics.append(
                _diag(
                    "error",
                    "shared.claim_exceeds_lease_ttl",
                    "Oldest claimed work item exceeds BOT_CLAIM_LEASE_TTL. Lease recovery may be stalled.",
                )
            )
        elif oldest_claim_age >= max(60.0, config.claim_lease_ttl_seconds * 0.75):
            diagnostics.append(
                _diag(
                    "warning",
                    "shared.claim_approaching_lease_ttl",
                    "Oldest claimed work item is approaching BOT_CLAIM_LEASE_TTL.",
                )
            )

    if queue.pending_recovery_count:
        diagnostics.append(
            _diag(
                "warning",
                "shared.pending_recovery_backlog",
                f"Shared Runtime has {queue.pending_recovery_count} item(s) awaiting replay/discard.",
            )
        )
    if queue.recovery_queued_count:
        diagnostics.append(
            _diag(
                "warning",
                "shared.recovery_notice_backlog",
                f"Shared Runtime has {queue.recovery_queued_count} replay item(s) queued for notice delivery.",
            )
        )
    if (queue.fresh_queued_count + queue.recovery_queued_count) > 100:
        diagnostics.append(
            _diag(
                "warning",
                "shared.queue_depth_high",
                "Shared Runtime queue depth exceeds 100 queued items.",
            )
        )
    if total_stale_recoveries > 0:
        diagnostics.append(
            _diag(
                "info",
                "shared.lease_recoveries_seen",
                f"Lease recoveries seen by live workers: {total_stale_recoveries}",
            )
        )
    if queue.cancel_requested_claimed_count:
        diagnostics.append(
            _diag(
                "info",
                "shared.claims_cancel_requested",
                f"Claimed items with cancel requested: {queue.cancel_requested_claimed_count}",
            )
        )

    return snapshot, diagnostics


async def collect_runtime_health_report(
    config: BotConfig,
    provider: Provider,
    *,
    caller_is_bot: bool = False,
    session_context: SessionHealthContext | None = None,
    runtime_health_provider: RuntimeHealthProvider | None = None,
) -> RuntimeHealthReport:
    provider_impl = runtime_health_provider or CanonicalRuntimeHealthProvider()
    return await provider_impl.collect(
        config,
        provider,
        caller_is_bot=caller_is_bot,
        session_context=session_context,
    )


def format_runtime_health_for_doctor(
    report: RuntimeHealthReport,
    *,
    formatter: RuntimeHealthFormatter | None = None,
) -> list[str]:
    formatter_impl = formatter or DoctorTextFormatter()
    formatted = formatter_impl.format(report)
    if isinstance(formatted, str):
        return [formatted]
    return list(formatted)


def project_runtime_health(
    report: RuntimeHealthReport,
    *,
    projector: RuntimeHealthProjector[T] | None = None,
) -> T:
    projector_impl = projector or RuntimeHealthJsonProjector()
    return projector_impl.project(report)


def scan_stale_sessions(
    data_dir: Path,
    provider_name: str,
    provider_state_factory,
    approval_mode: str,
) -> tuple[int, int]:
    """Scan sessions for stale pending/setup entries."""
    stale_pending = 0
    stale_setup = 0
    now = utc_now()
    for info in list_sessions(data_dir):
        if not info["has_pending"] and not info["has_setup"]:
            continue
        raw_session = load_session(
            data_dir, info["conversation_key"], provider_name, provider_state_factory, approval_mode,
        )
        session = session_from_dict(raw_session)
        pending = session.pending_approval or session.pending_retry
        pending_raw = raw_session.get("pending_approval") or raw_session.get("pending_retry") or {}
        pending_created_at = pending.created_at if pending else pending_raw.get("created_at")
        pending_age = age_seconds(pending_created_at, now=now)
        if pending_age is not None and pending_age > _STALE_PENDING_SECONDS:
            stale_pending += 1
        setup = session.awaiting_skill_setup
        setup_raw = raw_session.get("awaiting_skill_setup") or {}
        setup_started_at = setup.started_at if setup else setup_raw.get("started_at")
        setup_age = age_seconds(setup_started_at, now=now)
        if setup_age is not None and setup_age > _STALE_SETUP_SECONDS:
            stale_setup += 1
    return stale_pending, stale_setup


def scan_stale_delegations(
    data_dir: Path,
    provider_name: str,
    provider_state_factory,
    approval_mode: str,
    *,
    stale_proposed_seconds: float = _STALE_DELEGATION_SECONDS,
) -> int:
    """Return count of sessions with proposed delegation plans older than threshold."""
    stale = 0
    now = utc_now()
    for info in list_sessions(data_dir):
        session = session_from_dict(
            load_session(data_dir, info["conversation_key"], provider_name, provider_state_factory, approval_mode)
        )
        delegation = session.pending_delegation
        if delegation is None:
            continue
        if not any(task.status == "proposed" for task in delegation.tasks):
            continue
        delegation_age = age_seconds(delegation.created_at, now=now)
        if delegation_age is not None and delegation_age > stale_proposed_seconds:
            stale += 1
    return stale


async def check_polling_conflict(token: str) -> str | None:
    """Probe Telegram getUpdates to detect a conflicting poller."""
    parts = token.split(":", 1)
    if len(parts) != 2 or not parts[0].isdigit() or len(parts[1]) < 30:
        return None
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.post(url, json={"limit": 1, "timeout": 0})
        if response.status_code == 409:
            return (
                "Polling conflict detected (HTTP 409) — another process is already "
                "polling with this bot token. Stop the other process or switch to "
                "webhook mode."
            )
    except Exception as exc:
        log.debug("Polling conflict check failed: %s", exc)
    return None


def _format_age_label(age: float) -> str:
    seconds = max(0, int(age))
    if seconds < 60:
        return f"{seconds}s"
    minutes, rem = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {rem}s"
    hours, rem_minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {rem_minutes}m"
    days, rem_hours = divmod(hours, 24)
    return f"{days}d {rem_hours}h"


def _to_wire(value: Any) -> Any:
    if isinstance(value, RuntimeHealthReport):
        return {
            "schema_version": value.schema_version,
            "generated_at": value.generated_at,
            "summary": _to_wire(value.summary),
            "snapshot": _to_wire(value.snapshot),
            "diagnostics": [_to_wire(item) for item in value.diagnostics],
        }
    if isinstance(value, RuntimeHealthSummary):
        return {
            "status": value.status,
            "healthy_worker_count": value.healthy_worker_count,
            "stale_worker_count": value.stale_worker_count,
            "fresh_queued_count": value.fresh_queued_count,
            "claimed_count": value.claimed_count,
            "pending_recovery_count": value.pending_recovery_count,
            "recovery_queued_count": value.recovery_queued_count,
            "oldest_claim_age_seconds": value.oldest_claim_age_seconds,
            "warning_count": value.warning_count,
            "error_count": value.error_count,
        }
    if isinstance(value, SharedRuntimeSnapshot):
        return {
            "queue": _to_wire(value.queue),
            "workers": [_to_wire(item) for item in value.workers],
            "healthy_worker_count": value.healthy_worker_count,
            "stale_worker_count": value.stale_worker_count,
        }
    if isinstance(value, QueueSnapshot):
        return {
            "fresh_queued_count": value.fresh_queued_count,
            "recovery_queued_count": value.recovery_queued_count,
            "claimed_count": value.claimed_count,
            "pending_recovery_count": value.pending_recovery_count,
            "cancel_requested_claimed_count": value.cancel_requested_claimed_count,
            "oldest_fresh_queued_at": value.oldest_fresh_queued_at,
            "oldest_recovery_queued_at": value.oldest_recovery_queued_at,
            "oldest_claimed_at": value.oldest_claimed_at,
            "oldest_pending_recovery_at": value.oldest_pending_recovery_at,
        }
    if isinstance(value, WorkerHeartbeat):
        return {
            "worker_id": value.worker_id,
            "process_role": value.process_role,
            "started_at": value.started_at,
            "last_seen_at": value.last_seen_at,
            "current_item_id": value.current_item_id,
            "current_conversation_key": value.current_conversation_key,
            "current_kind": value.current_kind,
            "items_processed": value.items_processed,
            "stale_recoveries_seen": value.stale_recoveries_seen,
            "last_error": value.last_error,
        }
    if isinstance(value, RuntimeDiagnostic):
        return {
            "level": value.level,
            "code": value.code,
            "message": value.message,
        }
    return value
