import datetime
from pathlib import Path
from unittest.mock import patch

from app import runtime_backend, work_queue
from app.identity import telegram_actor_key, telegram_conversation_key, telegram_event_id
from app.runtime_health import (
    CanonicalRuntimeHealthProvider,
    QueueSnapshot,
    RuntimeDiagnostic,
    RuntimeHealthReport,
    RuntimeHealthSummary,
    SessionHealthContext,
    SharedRuntimeSnapshot,
    WorkerHeartbeat,
    collect_runtime_health_report,
    format_runtime_health_for_doctor,
    project_runtime_health,
    report_from_dict,
)
from app.storage import ensure_data_dirs
from tests.support.config_support import make_config
from tests.support.handler_support import FakeProvider


async def test_runtime_health_provider_collects_shared_snapshot(tmp_path: Path):
    ensure_data_dirs(tmp_path)
    config = make_config(
        data_dir=tmp_path,
        working_dir=tmp_path,
        runtime_mode="shared",
        process_role="worker",
        bot_mode="webhook",
        webhook_url="https://bot.example.com/webhook",
        allow_open=False,
        allowed_actor_keys=frozenset({telegram_actor_key(42)}),
        admin_users_explicit=True,
    )
    provider = FakeProvider()
    runtime_backend.init(config)
    try:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        work_queue.upsert_worker_heartbeat(
            tmp_path,
            WorkerHeartbeat(
                worker_id="worker01:123:abc",
                process_role="worker",
                started_at=now,
                last_seen_at=now,
                items_processed=3,
                stale_recoveries_seen=2,
            ),
        )
        work_queue.record_and_admit_message(
            tmp_path,
            telegram_event_id(9001),
            telegram_conversation_key(77),
            telegram_actor_key(42),
            "message",
            '{"text":"hello"}',
        )

        report = await collect_runtime_health_report(config, provider)

        assert report.schema_version == 1
        assert report.snapshot is not None
        assert report.snapshot.healthy_worker_count == 1
        assert report.snapshot.queue.fresh_queued_count == 1
        assert report.summary.healthy_worker_count == 1
        assert report.summary.fresh_queued_count == 1
        assert any(item.code == "shared.lease_recoveries_seen" for item in report.diagnostics)
        assert not any(item.code == "provider.runtime_unavailable" for item in report.diagnostics)
    finally:
        runtime_backend.reset_for_test()


async def test_runtime_health_provider_checks_auth_health_for_worker_role(tmp_path: Path):
    class AuthFailProvider(FakeProvider):
        async def check_auth_health(self):
            return ["provider auth unavailable"]

    config = make_config(
        data_dir=tmp_path,
        working_dir=tmp_path,
        runtime_mode="shared",
        process_role="worker",
        bot_mode="webhook",
        webhook_url="https://bot.example.com/webhook",
        allow_open=False,
        allowed_actor_keys=frozenset({telegram_actor_key(42)}),
        admin_users_explicit=True,
    )

    report = await collect_runtime_health_report(config, AuthFailProvider())

    assert any(item.code == "provider.auth_unavailable" for item in report.diagnostics)
    assert report.summary.status == "unhealthy"


async def test_runtime_health_provider_checks_auth_once_per_process_lifetime(tmp_path: Path):
    class CountingProvider(FakeProvider):
        def __init__(self):
            super().__init__()
            self.auth_checks = 0

        async def check_auth_health(self):
            self.auth_checks += 1
            return []

    config = make_config(
        data_dir=tmp_path,
        working_dir=tmp_path,
        runtime_mode="shared",
        process_role="worker",
        bot_mode="webhook",
        webhook_url="https://bot.example.com/webhook",
        allow_open=False,
        allowed_actor_keys=frozenset({telegram_actor_key(42)}),
        admin_users_explicit=True,
    )
    provider = CountingProvider()
    runtime_health_provider = CanonicalRuntimeHealthProvider()

    await collect_runtime_health_report(
        config,
        provider,
        runtime_health_provider=runtime_health_provider,
    )
    await collect_runtime_health_report(
        config,
        provider,
        runtime_health_provider=runtime_health_provider,
    )

    assert provider.auth_checks == 1


async def test_runtime_health_provider_live_probe_is_opt_in(tmp_path: Path):
    class RuntimeFailProvider(FakeProvider):
        async def check_runtime_health(self):
            return ["provider runtime unavailable"]

    config = make_config(
        data_dir=tmp_path,
        working_dir=tmp_path,
        runtime_mode="shared",
        process_role="worker",
        bot_mode="webhook",
        webhook_url="https://bot.example.com/webhook",
        allow_open=False,
        allowed_actor_keys=frozenset({telegram_actor_key(42)}),
        admin_users_explicit=True,
    )

    default_report = await collect_runtime_health_report(config, RuntimeFailProvider())
    live_report = await collect_runtime_health_report(
        config,
        RuntimeFailProvider(),
        include_provider_runtime_probe=True,
    )

    assert not any(item.code == "provider.runtime_unavailable" for item in default_report.diagnostics)
    assert any(item.code == "provider.runtime_unavailable" for item in live_report.diagnostics)


def test_runtime_health_projector_round_trip_preserves_report():
    report = RuntimeHealthReport(
        generated_at="2026-03-16T00:00:00+00:00",
        summary=RuntimeHealthSummary(
            status="degraded",
            healthy_worker_count=2,
            stale_worker_count=1,
            fresh_queued_count=4,
            claimed_count=1,
            pending_recovery_count=1,
            recovery_queued_count=0,
            oldest_claim_age_seconds=17,
            warning_count=2,
            error_count=0,
        ),
        snapshot=SharedRuntimeSnapshot(
            queue=QueueSnapshot(
                fresh_queued_count=4,
                recovery_queued_count=0,
                claimed_count=1,
                pending_recovery_count=1,
                oldest_claimed_at="2026-03-16T00:00:10+00:00",
            ),
            workers=(
                WorkerHeartbeat(
                    worker_id="host:111:aaa",
                    process_role="worker",
                    started_at="2026-03-16T00:00:00+00:00",
                    last_seen_at="2026-03-16T00:00:05+00:00",
                    items_processed=7,
                ),
            ),
            healthy_worker_count=2,
            stale_worker_count=1,
        ),
        diagnostics=(
            RuntimeDiagnostic(
                level="warning",
                code="shared.pending_recovery_backlog",
                message="Shared Runtime has 1 item awaiting replay/discard.",
            ),
        ),
    )

    payload = project_runtime_health(report)
    hydrated = report_from_dict(payload)

    assert hydrated is not None
    assert hydrated.schema_version == 1
    assert hydrated.summary == report.summary
    assert hydrated.snapshot == report.snapshot
    assert hydrated.diagnostics == report.diagnostics


def test_runtime_health_formatter_renders_summary_and_diagnostics():
    report = RuntimeHealthReport(
        summary=RuntimeHealthSummary(
            status="degraded",
            healthy_worker_count=1,
            stale_worker_count=1,
            fresh_queued_count=2,
            claimed_count=1,
            pending_recovery_count=0,
            recovery_queued_count=1,
            oldest_claim_age_seconds=42,
            warning_count=1,
            error_count=0,
        ),
        snapshot=SharedRuntimeSnapshot(
            queue=QueueSnapshot(
                fresh_queued_count=2,
                recovery_queued_count=1,
                claimed_count=1,
            ),
            healthy_worker_count=1,
            stale_worker_count=1,
        ),
        diagnostics=(
            RuntimeDiagnostic(
                level="warning",
                code="shared.stale_worker_heartbeats",
                message="Shared Runtime has 1 stale worker heartbeat.",
            ),
        ),
    )

    lines = format_runtime_health_for_doctor(report)

    assert lines[0] == "Overall status: degraded"
    assert any("Shared Runtime workers: 1 healthy, 1 stale" in line for line in lines)
    assert any("Queue: 2 fresh queued, 1 claimed, 0 pending recovery, 1 recovery queued" in line for line in lines)
    assert any("Oldest claim age:" in line for line in lines)
    assert any("WARN: Shared Runtime has 1 stale worker heartbeat." == line for line in lines)


async def test_runtime_health_sanitizes_content_store_failure_details(tmp_path: Path):
    config = make_config(data_dir=tmp_path, working_dir=tmp_path)
    provider = FakeProvider()

    with patch(
        "app.content_store.get_content_store",
        side_effect=RuntimeError("postgresql://bot:secret@example.com/bot refused connection"),
    ):
        report = await collect_runtime_health_report(config, provider)

    diagnostics = [
        item.message for item in report.diagnostics if item.code == "content_store.health_failed"
    ]
    assert diagnostics
    assert "secret@example.com" not in diagnostics[0]
    assert "RuntimeError" in diagnostics[0]


async def test_runtime_health_sanitizes_session_database_failure_details(tmp_path: Path, monkeypatch):
    config = make_config(data_dir=tmp_path, working_dir=tmp_path)
    provider = FakeProvider()
    tmp_path.mkdir(exist_ok=True)

    def _raise_db_error(*_args, **_kwargs):
        raise RuntimeError("postgresql://bot:secret@example.com/bot refused connection")

    monkeypatch.setattr("app.runtime_health.scan_stale_sessions", _raise_db_error)

    report = await collect_runtime_health_report(config, provider)

    diagnostics = [item.message for item in report.diagnostics if item.code == "session.db_error"]
    assert diagnostics
    assert "secret@example.com" not in diagnostics[0]
    assert "RuntimeError" in diagnostics[0]


async def test_runtime_health_classifies_session_schema_mismatch_without_raw_text(tmp_path: Path, monkeypatch):
    config = make_config(data_dir=tmp_path, working_dir=tmp_path)
    provider = FakeProvider()
    tmp_path.mkdir(exist_ok=True)

    def _raise_schema_error(*_args, **_kwargs):
        raise RuntimeError("schema_version=99 is newer than supported")

    monkeypatch.setattr("app.runtime_health.scan_stale_sessions", _raise_schema_error)

    report = await collect_runtime_health_report(config, provider)

    diagnostics = [item.message for item in report.diagnostics if item.code == "session.db_error"]
    assert diagnostics
    assert "schema is newer" in diagnostics[0].lower()
    assert "schema_version=99" not in diagnostics[0]


async def test_runtime_health_loads_credentials_only_for_resolved_active_skills(tmp_path: Path, monkeypatch):
    config = make_config(data_dir=tmp_path, working_dir=tmp_path)
    provider = FakeProvider()
    calls: list[tuple[str, tuple[str, ...]]] = []

    class FakeCredentialService:
        def load(self, actor_key):
            raise AssertionError(f"unexpected full credential load for {actor_key}")

        def load_for_skills(self, actor_key, skill_names):
            calls.append((actor_key, tuple(skill_names)))
            return {"github-integration": {}}

        def missing_requirements(self, requirements, credential_values):
            del credential_values
            return list(requirements)

    monkeypatch.setattr(
        "app.credential_service.get_credential_service",
        lambda: FakeCredentialService(),
    )

    report = await collect_runtime_health_report(
        config,
        provider,
        session_context=SessionHealthContext(
            session={},
            actor_key=telegram_actor_key(42),
            resolved_active_skills=("github-integration",),
        ),
    )

    assert calls == [(telegram_actor_key(42), ("github-integration",))]
    assert any(item.code == "skills.missing_credentials" for item in report.diagnostics)
