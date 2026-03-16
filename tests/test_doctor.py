import datetime
import time
from pathlib import Path

from app.agents.state import AgentRuntimeState, save_agent_runtime_state
from app.doctor import collect_doctor_report, scan_stale_delegations
from app.storage import default_session, save_session
from tests.support.config_support import make_config
from tests.support.handler_support import FakeProvider
from app.identity import telegram_actor_key, telegram_conversation_key, telegram_event_id


async def test_doctor_warns_when_registry_degraded(tmp_path: Path):
    config = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registry_url="http://registry.test",
        agent_registry_enroll_token="enroll-secret",
        working_dir=tmp_path,
    )
    provider = FakeProvider()
    save_agent_runtime_state(
        tmp_path,
        AgentRuntimeState(connectivity_state="degraded", last_error="timeout"),
    )

    report = await collect_doctor_report(config, provider)

    assert any("Registry connectivity is degraded" in warning for warning in report.warnings)


async def test_doctor_warns_when_registry_not_enrolled(tmp_path: Path):
    config = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registry_url="http://registry.test",
        agent_registry_enroll_token="enroll-secret",
    )
    provider = FakeProvider()

    report = await collect_doctor_report(config, provider)

    assert any("Registry enrollment has not completed" in warning for warning in report.warnings)


async def test_doctor_clean_when_registry_connected_and_enrolled(tmp_path: Path):
    config = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registry_url="http://registry.test",
        agent_registry_enroll_token="enroll-secret",
        working_dir=tmp_path,
    )
    provider = FakeProvider()
    save_agent_runtime_state(
        tmp_path,
        AgentRuntimeState(
            agent_id="abc",
            agent_token="secret",
            connectivity_state="connected",
            last_successful_contact_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        ),
    )

    report = await collect_doctor_report(config, provider)

    assert report.errors == []
    assert not any("Registry" in warning for warning in report.warnings)
    assert not any("enrollment has not completed" in warning for warning in report.warnings)


async def test_doctor_warns_stale_last_contact(tmp_path: Path):
    config = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registry_url="http://registry.test",
        agent_registry_enroll_token="enroll-secret",
    )
    provider = FakeProvider()
    stale_contact = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=10)
    save_agent_runtime_state(
        tmp_path,
        AgentRuntimeState(
            agent_id="abc",
            agent_token="secret",
            connectivity_state="connected",
            last_successful_contact_at=stale_contact.isoformat(),
        ),
    )

    report = await collect_doctor_report(config, provider)

    assert any("last successful contact" in warning for warning in report.warnings)


async def test_doctor_warns_when_registry_connected_without_agent_id(tmp_path: Path):
    config = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registry_url="http://registry.test",
        agent_registry_enroll_token="enroll-secret",
        working_dir=tmp_path,
    )
    provider = FakeProvider()
    save_agent_runtime_state(
        tmp_path,
        AgentRuntimeState(
            agent_id="",
            agent_token="secret",
            connectivity_state="connected",
            last_successful_contact_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        ),
    )

    report = await collect_doctor_report(config, provider)

    assert any("registry state may be corrupt" in warning for warning in report.warnings)


async def test_doctor_warns_stale_pending_delegation(tmp_path: Path):
    config = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registry_url="http://registry.test",
        agent_registry_enroll_token="enroll-secret",
    )
    provider = FakeProvider()
    save_agent_runtime_state(
        tmp_path,
        AgentRuntimeState(
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

    report = await collect_doctor_report(config, provider)

    assert any("delegation plans awaiting user approval" in warning for warning in report.warnings)


async def test_doctor_stale_pending_delegation_accepts_iso_timestamp(tmp_path: Path):
    config = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registry_url="http://registry.test",
        agent_registry_enroll_token="enroll-secret",
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
    save_agent_runtime_state(
        tmp_path,
        AgentRuntimeState(connectivity_state="degraded", last_error="timeout"),
    )

    report = await collect_doctor_report(config, provider)

    assert not any("Registry" in warning for warning in report.warnings)
