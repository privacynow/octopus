import datetime
import time
from pathlib import Path

from app import runtime_backend, work_queue
from app.agents.state import save_registry_connection_state
from app.agents.types import RegistryConnectionState
from app.runtime_health import (
    WorkerHeartbeat,
    collect_runtime_health_report,
    format_runtime_health_for_doctor,
    scan_stale_delegations,
)
from app.storage import ensure_data_dirs
from app.storage import default_session, save_session
from tests.support.config_support import make_config, make_registry_connection
from tests.support.handler_support import FakeProvider
from app.identity import telegram_actor_key, telegram_conversation_key, telegram_event_id


async def _collect_health(config, provider):
    return await collect_runtime_health_report(config, provider)


def _diagnostic_messages(report, level: str) -> list[str]:
    return [item.message for item in report.diagnostics if item.level == level]


def _doctor_lines(report) -> list[str]:
    return format_runtime_health_for_doctor(report)


async def test_doctor_warns_when_registry_degraded(tmp_path: Path):
    config = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registries=(make_registry_connection(url="http://registry:8787"),),
        working_dir=tmp_path,
    )
    provider = FakeProvider()
    save_registry_connection_state(
        tmp_path,
        RegistryConnectionState(
            registry_id="default",
            connectivity_state="degraded",
            last_error="registry_timeout",
            last_error_detail="Registry poll timed out.",
        ),
    )

    report = await _collect_health(config, provider)

    warnings = _diagnostic_messages(report, "warning")
    assert any("connectivity is degraded" in warning for warning in warnings)
    assert any("Registry poll timed out." in warning for warning in warnings)


async def test_doctor_warns_when_registry_not_enrolled(tmp_path: Path):
    config = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registries=(make_registry_connection(url="http://registry:8787"),),
    )
    provider = FakeProvider()

    report = await _collect_health(config, provider)

    assert any("enrollment has not completed" in warning for warning in _diagnostic_messages(report, "warning"))


async def test_doctor_clean_when_registry_connected_and_enrolled(tmp_path: Path):
    config = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registries=(make_registry_connection(url="http://registry:8787"),),
        working_dir=tmp_path,
    )
    provider = FakeProvider()
    save_registry_connection_state(
        tmp_path,
        RegistryConnectionState(
            registry_id="default",
            agent_id="abc",
            agent_token="secret",
            connectivity_state="connected",
            last_successful_contact_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        ),
    )

    report = await _collect_health(config, provider)

    assert report.summary.error_count == 0
    warnings = _diagnostic_messages(report, "warning")
    assert not any("Registry" in warning for warning in warnings)
    assert not any("enrollment has not completed" in warning for warning in warnings)


async def test_doctor_warns_stale_last_contact(tmp_path: Path):
    config = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registries=(make_registry_connection(url="http://registry:8787"),),
    )
    provider = FakeProvider()
    stale_contact = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=10)
    save_registry_connection_state(
        tmp_path,
        RegistryConnectionState(
            registry_id="default",
            agent_id="abc",
            agent_token="secret",
            connectivity_state="connected",
            last_successful_contact_at=stale_contact.isoformat(),
        ),
    )

    report = await _collect_health(config, provider)

    assert any("last successful contact" in warning for warning in _diagnostic_messages(report, "warning"))


async def test_doctor_warns_when_registry_connected_without_agent_id(tmp_path: Path):
    config = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registries=(make_registry_connection(url="http://registry:8787"),),
        working_dir=tmp_path,
    )
    provider = FakeProvider()
    save_registry_connection_state(
        tmp_path,
        RegistryConnectionState(
            registry_id="default",
            agent_id="",
            agent_token="secret",
            connectivity_state="connected",
            last_successful_contact_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        ),
    )

    report = await _collect_health(config, provider)

    assert any("state may be corrupt" in warning for warning in _diagnostic_messages(report, "warning"))


async def test_doctor_warns_stale_pending_delegation(tmp_path: Path):
    config = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registries=(make_registry_connection(url="http://registry:8787"),),
    )
    provider = FakeProvider()
    save_registry_connection_state(
        tmp_path,
        RegistryConnectionState(
            registry_id="default",
            agent_id="abc",
            agent_token="secret",
            connectivity_state="connected",
            last_successful_contact_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        ),
    )
    session = default_session(provider.name, provider.new_provider_state(), "off")
    session["pending_delegation"] = {
        "conversation_ref": "telegram:agent:1001",
        "title": "Delegation plan",
        "resume_instruction": "Continue when done.",
        "created_at": time.time() - 7200,
        "tasks": [
            {
                "routed_task_id": "task-1",
                "title": "Implement feature",
                "target_agent_id": "developer-1",
                "instructions": "Build the feature.",
                "status": "proposed",
            }
        ],
    }
    save_session(tmp_path, telegram_conversation_key(1001), session)

    assert scan_stale_delegations(
        tmp_path,
        config.provider_name,
        provider.new_provider_state,
        config.approval_mode,
    ) == 1

    report = await _collect_health(config, provider)

    assert any("delegation plans awaiting user approval" in warning for warning in _diagnostic_messages(report, "warning"))


async def test_doctor_stale_pending_delegation_accepts_iso_timestamp(tmp_path: Path):
    config = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registries=(make_registry_connection(url="http://registry:8787"),),
    )
    provider = FakeProvider()
    session = default_session(provider.name, provider.new_provider_state(), "off")
    session["pending_delegation"] = {
        "conversation_ref": "telegram:agent:1002",
        "title": "Delegation plan",
        "resume_instruction": "Continue when done.",
        "created_at": (
            datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=2)
        ).isoformat(),
        "tasks": [
            {
                "routed_task_id": "task-iso",
                "title": "Investigate issue",
                "target_agent_id": "reviewer-1",
                "instructions": "Check the traces.",
                "status": "proposed",
            }
        ],
    }
    save_session(tmp_path, telegram_conversation_key(1002), session)

    assert scan_stale_delegations(
        tmp_path,
        config.provider_name,
        provider.new_provider_state,
        config.approval_mode,
    ) == 1


async def test_doctor_standalone_mode_no_registry_warnings_if_mode_is_standalone(tmp_path: Path):
    config = make_config(
        data_dir=tmp_path,
        agent_mode="standalone",
    )
    provider = FakeProvider()
    save_registry_connection_state(
        tmp_path,
        RegistryConnectionState(
            registry_id="default",
            connectivity_state="degraded",
            last_error="registry_timeout",
            last_error_detail="Registry poll timed out.",
        ),
    )

    report = await _collect_health(config, provider)

    assert not any("Registry" in warning for warning in _diagnostic_messages(report, "warning"))


async def test_doctor_skips_provider_health_probes_for_webhook_role(tmp_path: Path):
    class RuntimeFailProvider(FakeProvider):
        def __init__(self) -> None:
            super().__init__("claude")
            self.auth_checks = 0
            self.runtime_checks = 0

        async def check_auth_health(self):
            self.auth_checks += 1
            return ["provider auth unavailable"]

        async def check_runtime_health(self):
            self.runtime_checks += 1
            return ["provider runtime unavailable"]

    config = make_config(
        data_dir=tmp_path / "shared-not-initialized",
        runtime_mode="shared",
        process_role="webhook",
        bot_mode="webhook",
        webhook_url="https://bot.example.com/webhook",
    )
    provider = RuntimeFailProvider()

    report = await _collect_health(config, provider)

    assert provider.auth_checks == 0
    assert provider.runtime_checks == 0
    assert not any("provider auth unavailable" in err for err in _diagnostic_messages(report, "error"))
    assert not any("provider runtime unavailable" in err for err in _diagnostic_messages(report, "error"))


async def test_doctor_reports_shared_runtime_summary(tmp_path: Path):
    ensure_data_dirs(tmp_path)
    config = make_config(
        data_dir=tmp_path,
        runtime_mode="shared",
        process_role="worker",
        bot_mode="webhook",
        webhook_url="https://bot.example.com/webhook",
    )
    provider = FakeProvider()
    runtime_backend.init(config)
    try:
        work_queue.upsert_worker_heartbeat(
            tmp_path,
            WorkerHeartbeat(
                worker_id="host:123:abc",
                process_role="worker",
                started_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                last_seen_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                items_processed=2,
                stale_recoveries_seen=1,
            ),
        )
        work_queue.record_and_admit_message(
            tmp_path,
            telegram_event_id(5001),
            telegram_conversation_key(100),
            telegram_actor_key(42),
            "message",
            '{"text":"hello"}',
        )

        report = await _collect_health(config, provider)
        lines = _doctor_lines(report)

        assert any("Shared Runtime workers: 1 healthy, 0 stale" in info for info in lines)
        assert any("Queue: 1 fresh queued, 0 claimed, 0 pending recovery, 0 recovery queued" in info for info in lines)
    finally:
        runtime_backend.reset_for_test()


async def test_doctor_errors_when_no_healthy_shared_workers(tmp_path: Path):
    ensure_data_dirs(tmp_path)
    config = make_config(
        data_dir=tmp_path,
        runtime_mode="shared",
        process_role="worker",
        bot_mode="webhook",
        webhook_url="https://bot.example.com/webhook",
    )
    provider = FakeProvider()
    runtime_backend.init(config)
    try:
        report = await _collect_health(config, provider)
        assert any("no healthy worker heartbeats" in err.lower() for err in _diagnostic_messages(report, "error"))
    finally:
        runtime_backend.reset_for_test()
