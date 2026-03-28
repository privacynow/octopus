"""Tests for agent-mode config/runtime foundation."""

import asyncio
import json
import logging
from pathlib import Path

import httpx
import pytest

from app import work_queue
import app.agents.state as agent_state_module
from app.agents.client import AgentRegistryClient, RegistryClientError
from app.channels.registry.delivery_transport import (
    admit_registry_delivery,
    build_registry_delivery_runtime,
    handle_registry_delivery,
)
import app.runtime.registry_participant as agent_runtime_module
from app.runtime.registry_participant import AgentRuntime, _registered_card_hash
from app.agents.state import RegistryConnectionState
from octopus_sdk.registry.models import AgentDiscoveryQuery
from app.channels.registry.refs import registry_conversation_ref, registry_task_ref
from app.agents.registry_capabilities import registry_authority_ref
from app.control_plane.bus import ControlPlaneBus
from app.control_plane.directory import build_control_plane_directory
from app.config import derive_agent_slug
import octopus_sdk.identity as identity_module
from octopus_sdk.identity import (
    bot_identity,
    conversation_key_for_ref,
    load_bot_identity_state,
    telegram_conversation_ref,
)
from octopus_sdk.inbound_types import deserialize_inbound
from octopus_sdk.transport import InboundSubmissionResult
from octopus_sdk.transport import TransportBindingRecord
from app.runtime.services import build_bus_bot_services
from app.runtime_health import RuntimeHealthReport, RuntimeHealthSummary
from octopus_sdk.workflows.delegation import DelegationUpdateOutcome
from octopus_sdk.sessions import DelegatedTask, PendingDelegation
from app.agents.state import (
    load_registry_connection_state,
    load_runtime_registry_connection_state,
    save_registry_connection_state,
)
from tests.support.config_support import make_config, make_registry_connection
from tests.support.handler_support import current_runtime, fresh_env
from tests.support.service_support import build_test_bot_services


def _reg_conv(conversation_ref: str) -> str:
    return conversation_key_for_ref(conversation_ref)


class _QueuedRegistrySubmitter:
    async def submit(self, envelope, *, worker_id=None):
        del envelope, worker_id
        return InboundSubmissionResult(status="queued", item_id="queued-item")

    async def admit_message(self, envelope):
        del envelope
        return InboundSubmissionResult(status="queued", item_id="queued-item")

    async def enqueue(self, envelope, *, worker_id=None):
        del envelope, worker_id
        return InboundSubmissionResult(status="queued", item_id="queued-item")

    async def record(self, envelope):
        del envelope
        return True


def test_derive_agent_slug_normalizes_display_name():
    assert derive_agent_slug(" Product Bot / Reviewer ") == "product-bot-reviewer"
    assert derive_agent_slug("!!!", fallback="fallback-agent") == "fallback-agent"


def test_requested_card_uses_agent_capabilities_without_default_skill_fallback(tmp_path: Path):
    config = make_config(
        data_dir=tmp_path,
        default_skills=("github-integration",),
        agent_capabilities=(),
        agent_display_name="Product Bot",
    )

    card = AgentRuntime(config).requested_card()

    assert card.capabilities == []


def test_requested_card_uses_neutral_version_when_no_product_version_is_defined(tmp_path: Path):
    config = make_config(data_dir=tmp_path, agent_display_name="Product Bot")

    card = AgentRuntime(config).requested_card()

    assert card.version == ""
    assert card.version != "phase-19-foundation"


def test_agent_runtime_source_has_no_internal_rollout_version_marker() -> None:
    assert "phase-19-foundation" not in Path(agent_runtime_module.__file__).read_text()


def test_telegram_conversation_ref_uses_stable_bot_identity(tmp_path: Path):
    config = make_config(data_dir=tmp_path)

    conversation_ref = telegram_conversation_ref(config, 12345)

    assert conversation_ref == f"telegram:{bot_identity(tmp_path)}:12345"


def test_registry_connection_state_requires_explicit_registry_id() -> None:
    with pytest.raises(TypeError):
        RegistryConnectionState()


def test_load_registry_connection_state_logs_when_file_is_corrupt(tmp_path: Path, caplog):
    state_path = tmp_path / "agent" / "registries" / "default.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text("{not-json", encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        state = load_registry_connection_state(tmp_path, "default")

    assert state == RegistryConnectionState(registry_id="default")
    assert any("Registry connection state load failed" in record.message for record in caplog.records)


def test_load_registry_connection_state_normalizes_raw_last_error(tmp_path: Path):
    state_path = tmp_path / "agent" / "registries" / "default.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        '{"connectivity_state":"degraded","last_error":"registry unavailable"}',
        encoding="utf-8",
    )

    state = load_registry_connection_state(tmp_path, "default")

    assert state.last_error == "registry_request_failed"
    assert state.last_error_detail == "registry unavailable"


def test_save_registry_connection_state_uses_private_file_permissions(tmp_path: Path):
    save_registry_connection_state(
        tmp_path,
        RegistryConnectionState(
            registry_id="default",
            agent_id="agent-1",
            agent_token="secret-token",
        ),
    )

    state_path = tmp_path / "agent" / "registries" / "default.json"
    mode = state_path.stat().st_mode & 0o777

    assert mode == 0o600


def test_registry_channel_services_resolve_runtime_agent_id_after_enrollment(tmp_path: Path):
    registry = make_registry_connection(registry_id="local")
    config = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registries=(registry,),
    )
    services = build_bus_bot_services(
        ControlPlaneBus(tmp_path),
        build_control_plane_directory(
            {registry_authority_ref("local"): {"conversation_projection"}}
        ),
        config=config,
        agent_id_for_authority=lambda authority_ref: load_runtime_registry_connection_state(
            tmp_path,
            authority_ref.rsplit(":", 1)[-1],
        ).agent_id,
    )

    save_registry_connection_state(
        tmp_path,
        RegistryConnectionState(
            registry_id="local",
            registry_scope="full",
            agent_id="agent-live",
            agent_token="token-live",
        ),
    )

    projection = services.control_plane.conversation_projection

    assert projection._agent_id_for_authority("registry:local") == "agent-live"


def test_bot_identity_preserves_existing_file_when_atomic_replace_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    identity_path = tmp_path / "agent" / "bot_identity.json"
    identity_path.parent.mkdir(parents=True, exist_ok=True)
    original = {
        "bot_id": "stable-bot-id",
        "created_at": "2026-01-01T00:00:00Z",
    }
    identity_path.write_text(json.dumps(original), encoding="utf-8")

    def fail_replace(src: Path, dst: Path) -> None:
        raise OSError("rename failed")

    monkeypatch.setattr(identity_module.os, "replace", fail_replace)

    with pytest.raises(OSError, match="rename failed"):
        identity_module._save_bot_identity_state(
            identity_path,
            identity_module.BotIdentityState(
                bot_id="new-bot-id",
                created_at="2026-02-01T00:00:00Z",
            ),
        )

    assert json.loads(identity_path.read_text(encoding="utf-8")) == original
    assert not list(identity_path.parent.glob("*.tmp"))


def test_bot_identity_creates_and_reuses_stable_runtime_id(tmp_path: Path):
    first = bot_identity(tmp_path)
    second = bot_identity(tmp_path)
    state = load_bot_identity_state(tmp_path)
    identity_path = tmp_path / "agent" / "bot_identity.json"

    assert first == second == state.bot_id
    assert len(first) == 32
    assert state.created_at.endswith("Z")
    assert identity_path.exists()
    assert identity_path.stat().st_mode & 0o777 == 0o600


def test_bot_identity_regenerates_when_file_is_corrupt(tmp_path: Path, caplog):
    identity_path = tmp_path / "agent" / "bot_identity.json"
    identity_path.parent.mkdir(parents=True, exist_ok=True)
    identity_path.write_text("{not-json", encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        new_id = bot_identity(tmp_path)

    state = load_bot_identity_state(tmp_path)

    assert new_id == state.bot_id
    assert state.created_at.endswith("Z")
    assert any("Bot identity load failed" in record.message for record in caplog.records)


def test_registry_connection_state_round_trips_per_connection_file(tmp_path: Path):
    state = RegistryConnectionState(
        registry_id="prod",
        registry_scope="coordination",
        agent_id="agent-1",
        agent_token="secret-token",
        poll_cursor="42",
    )

    save_registry_connection_state(tmp_path, state)
    restored = load_registry_connection_state(tmp_path, "prod")
    state_path = tmp_path / "agent" / "registries" / "prod.json"

    assert restored == state
    assert state_path.exists()
    assert state_path.stat().st_mode & 0o777 == 0o600


def test_save_registry_connection_state_preserves_existing_file_when_atomic_replace_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    state_path = tmp_path / "agent" / "registries" / "prod.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    original = {
        "registry_id": "prod",
        "registry_scope": "full",
        "agent_id": "agent-1",
        "agent_token": "token-1",
    }
    state_path.write_text(json.dumps(original), encoding="utf-8")

    def fail_replace(src: Path, dst: Path) -> None:
        raise OSError("rename failed")

    monkeypatch.setattr(agent_state_module.os, "replace", fail_replace)

    with pytest.raises(OSError, match="rename failed"):
        save_registry_connection_state(
            tmp_path,
            RegistryConnectionState(
                registry_id="prod",
                registry_scope="coordination",
                agent_id="agent-2",
                agent_token="token-2",
            ),
        )

    assert json.loads(state_path.read_text(encoding="utf-8")) == original
    assert not list(state_path.parent.glob("*.tmp"))


def test_registry_connection_state_uses_defaults_when_missing_or_corrupt(tmp_path: Path, caplog):
    missing = load_registry_connection_state(tmp_path, "analytics")
    assert missing == RegistryConnectionState(registry_id="analytics")

    corrupt_path = tmp_path / "agent" / "registries" / "analytics.json"
    corrupt_path.parent.mkdir(parents=True, exist_ok=True)
    corrupt_path.write_text("{not-json", encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        restored = load_registry_connection_state(tmp_path, "analytics")

    assert restored == RegistryConnectionState(registry_id="analytics")
    assert any("Registry connection state load failed" in record.message for record in caplog.records)


def test_runtime_registry_connection_state_applies_requested_scope_when_file_is_missing(tmp_path: Path):
    state = load_runtime_registry_connection_state(
        tmp_path,
        "default",
        registry_scope="coordination",
    )

    assert state == RegistryConnectionState(
        registry_id="default",
        registry_scope="coordination",
    )


def test_runtime_registry_connection_state_uses_requested_scope_when_file_omits_scope(tmp_path: Path):
    state_path = tmp_path / "agent" / "registries" / "default.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "registry_id": "default",
                "agent_id": "agent-1",
                "agent_token": "secret-token",
            }
        ),
        encoding="utf-8",
    )

    state = load_runtime_registry_connection_state(
        tmp_path,
        "default",
        registry_scope="coordination",
    )

    assert state == RegistryConnectionState(
        registry_id="default",
        registry_scope="coordination",
        agent_id="agent-1",
        agent_token="secret-token",
    )


def test_runtime_registry_connection_state_keeps_explicit_persisted_scope(tmp_path: Path):
    state_path = tmp_path / "agent" / "registries" / "default.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "registry_id": "default",
                "registry_scope": "full",
                "agent_id": "agent-1",
            }
        ),
        encoding="utf-8",
    )

    state = load_runtime_registry_connection_state(
        tmp_path,
        "default",
        registry_scope="coordination",
    )

    assert state == RegistryConnectionState(
        registry_id="default",
        registry_scope="full",
        agent_id="agent-1",
    )


async def test_agent_runtime_standalone_marks_state(tmp_path: Path):
    config = make_config(
        data_dir=tmp_path,
        agent_mode="standalone",
        agent_display_name="Standalone Bot",
    )
    runtime = AgentRuntime(config)

    result = await runtime.sync_once()
    state = runtime.state

    assert result == "standalone"
    assert state.connectivity_state == "standalone"
    assert state.agent_id == ""
    assert state.agent_token == ""


async def test_agent_runtime_registry_without_url_degrades(tmp_path: Path):
    config = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registries=(make_registry_connection(url="", enroll_token="token"),),
        agent_display_name="Registry Bot",
    )
    runtime = AgentRuntime(config, registry=config.agent_registries[0])

    result = await runtime.sync_once()
    state = load_runtime_registry_connection_state(tmp_path, "default")

    assert result == "degraded"
    assert state.connectivity_state == "degraded"
    assert state.last_error == "registry_url_missing"
    assert state.last_error_detail == "Registry URL not configured."


def test_agent_runtime_registry_mode_requires_explicit_registry(tmp_path: Path):
    config = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registries=(make_registry_connection(),),
    )

    with pytest.raises(ValueError, match="explicit registry connection"):
        AgentRuntime(config)


async def test_registry_client_error_omits_response_body():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer secret-token"
        return httpx.Response(
            500,
            text="<html>stack trace secret-token should not escape</html>",
            headers={"content-type": "text/html"},
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://registry.test",
    ) as client:
        registry = AgentRegistryClient(
            "http://registry.test",
            agent_token="secret-token",
            client=client,
        )
        with pytest.raises(RegistryClientError) as excinfo:
            await registry.search(AgentDiscoveryQuery(free_text="python"))

    exc = excinfo.value
    assert exc.error_code == "registry_server_error"
    assert exc.status_code == 500
    assert str(exc) == "Registry POST /v1/agents/discovery/search failed: HTTP 500"
    assert "stack trace" not in str(exc)
    assert "secret-token" not in str(exc)
    assert "HTTP 500" in exc.operator_detail


async def test_agent_runtime_persists_safe_registry_error_code_and_detail(monkeypatch, tmp_path: Path):
    class FakeRegistryClient:
        def __init__(self, base_url: str, *, agent_token: str = "", timeout_seconds: float = 10.0, client=None):
            self.base_url = base_url
            self.agent_token = agent_token

        async def enroll(self, card, enrollment_token: str):
            return {
                "agent_id": "agent-123",
                "slug": "product-bot",
                "agent_token": "secret-token",
                "poll_cursor": "0",
            }

        async def register(self, card, *, connectivity_state: str, current_capacity: int, max_capacity: int):
            raise RegistryClientError(
                "Registry POST /v1/agents/register failed: HTTP 500",
                error_code="registry_server_error",
                operator_detail="Registry POST /v1/agents/register failed with HTTP 500.",
                status_code=500,
            )

    monkeypatch.setattr("app.runtime.registry_participant.AgentRegistryClient", FakeRegistryClient)
    config = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registries=(make_registry_connection(),),
    )
    runtime = AgentRuntime(config, registry=config.agent_registries[0])

    result = await runtime.sync_once()
    state = load_runtime_registry_connection_state(tmp_path, "default")

    assert result == "degraded"
    assert state.connectivity_state == "degraded"
    assert state.last_error == "registry_server_error"
    assert state.last_error_detail == "Registry POST /v1/agents/register failed with HTTP 500."


async def test_agent_runtime_registry_enrolls_and_registers(monkeypatch, tmp_path: Path):
    calls: list[tuple[str, str, str]] = []

    class FakeRegistryClient:
        def __init__(self, base_url: str, *, agent_token: str = "", timeout_seconds: float = 10.0, client=None):
            self.base_url = base_url
            self.agent_token = agent_token

        async def enroll(self, card, enrollment_token: str):
            calls.append(("enroll", card.display_name, enrollment_token))
            return {
                "agent_id": "agent-123",
                "slug": "product-bot",
                "agent_token": "secret-token",
                "poll_cursor": "0",
            }

        async def register(self, card, *, connectivity_state: str, current_capacity: int, max_capacity: int):
            calls.append(("register", card.slug, connectivity_state))
            return {"ok": True}

        async def heartbeat(self, *, connectivity_state: str, current_capacity: int, max_capacity: int, runtime_health: dict | None = None):
            del runtime_health
            calls.append(("heartbeat", connectivity_state, str(current_capacity)))
            return {"ok": True}

    monkeypatch.setattr("app.runtime.registry_participant.AgentRegistryClient", FakeRegistryClient)
    config = make_config(
        data_dir=tmp_path,
        provider_name="codex",
        agent_mode="registry",
        agent_display_name="Product Bot",
        agent_slug="product-bot",
        agent_role="product",
        agent_capabilities=("planning", "delegation"),
        agent_registries=(make_registry_connection(),),
    )
    runtime = AgentRuntime(config, registry=config.agent_registries[0])

    result = await runtime.sync_once()
    state = load_runtime_registry_connection_state(tmp_path, "default")

    assert result == "connected"
    assert state.connectivity_state == "connected"
    assert state.agent_id == "agent-123"
    assert state.agent_token == "secret-token"
    assert calls == [
        ("enroll", "Product Bot", "enroll-secret"),
        ("register", "product-bot", "connected"),
        ("heartbeat", "connected", "0"),
    ]


async def test_agent_runtime_connected_sync_uses_heartbeat_without_re_registering(monkeypatch, tmp_path: Path):
    calls: list[tuple[str, str]] = []

    class FakeRegistryClient:
        def __init__(self, base_url: str, *, agent_token: str = "", timeout_seconds: float = 10.0, client=None):
            self.base_url = base_url
            self.agent_token = agent_token

        async def heartbeat(
            self,
            *,
            connectivity_state: str,
            current_capacity: int,
            max_capacity: int,
            runtime_health: dict | None = None,
        ):
            del runtime_health, current_capacity, max_capacity
            calls.append(("heartbeat", connectivity_state))
            return {"ok": True}

        async def register(self, card, *, connectivity_state: str, current_capacity: int, max_capacity: int):
            del card, connectivity_state, current_capacity, max_capacity
            calls.append(("register", "unexpected"))
            return {"ok": True}

    monkeypatch.setattr("app.runtime.registry_participant.AgentRegistryClient", FakeRegistryClient)
    config = make_config(
        data_dir=tmp_path,
        provider_name="codex",
        agent_mode="registry",
        agent_display_name="Product Bot",
        agent_slug="product-bot",
        agent_role="product",
        agent_capabilities=("planning", "delegation"),
        agent_registries=(make_registry_connection(),),
    )
    runtime = AgentRuntime(config, registry=config.agent_registries[0])
    runtime._state.agent_id = "agent-123"
    runtime._state.agent_token = "secret-token"
    runtime._state.registered_slug = "product-bot"
    runtime._state.connectivity_state = "connected"
    card = runtime.requested_card().model_copy(
        update={"slug": "product-bot", "connectivity_state": "connected"}
    )
    runtime._state.registered_card_hash = _registered_card_hash(card)
    runtime._save_state()

    result = await runtime.sync_once()

    assert result == "connected"
    assert calls == [("heartbeat", "connected")]


async def test_agent_runtime_registry_heartbeat_includes_runtime_health(monkeypatch, tmp_path: Path):
    calls: list[tuple[str, object]] = []

    class FakeRegistryClient:
        def __init__(self, base_url: str, *, agent_token: str = "", timeout_seconds: float = 10.0, client=None):
            self.base_url = base_url
            self.agent_token = agent_token

        async def enroll(self, card, enrollment_token: str):
            return {
                "agent_id": "agent-123",
                "slug": "product-bot",
                "agent_token": "secret-token",
                "poll_cursor": "0",
            }

        async def register(self, card, *, connectivity_state: str, current_capacity: int, max_capacity: int):
            return {"ok": True}

        async def heartbeat(
            self,
            *,
            connectivity_state: str,
            current_capacity: int,
            max_capacity: int,
            runtime_health: dict | None = None,
        ):
            calls.append(("heartbeat", runtime_health))
            return {"ok": True}

    class FakeHealthProvider:
        async def collect(
            self,
            config,
            provider,
            *,
            caller_is_bot=False,
            session_context=None,
            include_provider_runtime_probe=False,
        ):
            assert caller_is_bot is True
            assert include_provider_runtime_probe is False
            return RuntimeHealthReport(
                generated_at="2026-03-16T00:00:00+00:00",
                summary=RuntimeHealthSummary(
                    status="degraded",
                    healthy_worker_count=1,
                    stale_worker_count=0,
                    fresh_queued_count=0,
                    claimed_count=2,
                    pending_recovery_count=0,
                    recovery_queued_count=0,
                    oldest_claim_age_seconds=12,
                    warning_count=1,
                    error_count=0,
                ),
            )

    monkeypatch.setattr("app.runtime.registry_participant.AgentRegistryClient", FakeRegistryClient)
    config = make_config(
        data_dir=tmp_path,
        provider_name="codex",
        agent_mode="registry",
        agent_display_name="Product Bot",
        agent_registries=(make_registry_connection(),),
    )
    runtime = AgentRuntime(
        config,
        runtime_health_provider=FakeHealthProvider(),
        provider=object(),
        registry=config.agent_registries[0],
    )

    assert await runtime.sync_once() == "connected"
    assert len(calls) == 1
    kind, runtime_health = calls[0]
    assert kind == "heartbeat"
    assert runtime_health is not None
    assert runtime_health.model_dump() == {
        "schema_version": 1,
        "generated_at": "2026-03-16T00:00:00+00:00",
        "summary": {
            "ok": None,
            "status": "degraded",
            "healthy_worker_count": 1,
            "stale_worker_count": 0,
            "fresh_queued_count": 0,
            "claimed_count": 2,
            "pending_recovery_count": 0,
            "recovery_queued_count": 0,
            "oldest_claim_age_seconds": 12,
            "warning_count": 1,
            "error_count": 0,
        },
        "snapshot": None,
        "diagnostics": [],
    }


async def test_agent_runtime_poll_dispatches_and_acks(monkeypatch, tmp_path: Path):
    calls: list[tuple[str, object]] = []

    class FakeRegistryClient:
        def __init__(self, base_url: str, *, agent_token: str = "", timeout_seconds: float = 10.0, client=None):
            self.base_url = base_url
            self.agent_token = agent_token

        async def enroll(self, card, enrollment_token: str):
            return {
                "agent_id": "agent-123",
                "slug": "product-bot",
                "agent_token": "secret-token",
                "poll_cursor": "0",
            }

        async def register(self, card, *, connectivity_state: str, current_capacity: int, max_capacity: int):
            return {"ok": True}

        async def heartbeat(self, *, connectivity_state: str, current_capacity: int, max_capacity: int, runtime_health: dict | None = None):
            del runtime_health
            return {"ok": True}

        async def poll(self, *, cursor: str = "0", limit: int = 20, wait_seconds: int = 1):
            calls.append(("poll", cursor))
            return {
                "deliveries": [
                    {
                        "delivery_id": "d1",
                        "registry_id": "default",
                        "kind": "channel_input",
                        "payload": {"conversation_id": "c1", "text": "hello"},
                    },
                    {
                        "delivery_id": "d2",
                        "registry_id": "default",
                        "kind": "channel_action",
                        "payload": {"conversation_id": "c1", "action": "cancel_conversation"},
                    },
                ],
                "next_cursor": "2",
            }

        async def ack(self, delivery_ids, *, classification: str):
            calls.append((classification, tuple(delivery_ids)))
            return {"ok": True}

    monkeypatch.setattr("app.runtime.registry_participant.AgentRegistryClient", FakeRegistryClient)
    seen_deliveries: list[str] = []

    async def handler(delivery):
        seen_deliveries.append(delivery["delivery_id"])
        return "accepted" if delivery["kind"] == "channel_input" else "rejected"

    config = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_display_name="Product Bot",
        agent_registries=(make_registry_connection(),),
    )
    runtime = AgentRuntime(config, delivery_handler=handler, registry=config.agent_registries[0])
    assert await runtime.sync_once() == "connected"

    processed = await runtime.poll_once()
    state = load_runtime_registry_connection_state(tmp_path, "default")

    assert processed == 2
    assert seen_deliveries == ["d1", "d2"]
    assert state.poll_cursor == "2"
    assert calls == [
        ("poll", "0"),
        ("accepted", ("d1",)),
        ("rejected", ("d2",)),
    ]


async def test_agent_runtime_poll_isolates_bad_delivery_and_acks_rest(monkeypatch, tmp_path: Path):
    calls: list[tuple[str, object]] = []

    class FakeRegistryClient:
        def __init__(self, base_url: str, *, agent_token: str = "", timeout_seconds: float = 10.0, client=None):
            self.base_url = base_url
            self.agent_token = agent_token

        async def enroll(self, card, enrollment_token: str):
            return {
                "agent_id": "agent-123",
                "slug": "product-bot",
                "agent_token": "secret-token",
                "poll_cursor": "0",
            }

        async def register(self, card, *, connectivity_state: str, current_capacity: int, max_capacity: int):
            return {"ok": True}

        async def heartbeat(self, *, connectivity_state: str, current_capacity: int, max_capacity: int, runtime_health: dict | None = None):
            del runtime_health
            return {"ok": True}

        async def poll(self, *, cursor: str = "0", limit: int = 20, wait_seconds: int = 1):
            calls.append(("poll", cursor))
            return {
                "deliveries": [
                    {"delivery_id": "d1", "kind": "channel_input", "payload": {"conversation_id": "c1", "text": "hello"}},
                    {"delivery_id": "d2", "kind": "channel_input", "payload": {"conversation_id": "c2", "text": "world"}},
                ],
                "next_cursor": "2",
            }

        async def ack(self, delivery_ids, *, classification: str):
            calls.append((classification, tuple(delivery_ids)))
            return {"ok": True}

    monkeypatch.setattr("app.runtime.registry_participant.AgentRegistryClient", FakeRegistryClient)
    seen_deliveries: list[str] = []

    async def handler(delivery):
        seen_deliveries.append(delivery["delivery_id"])
        if delivery["delivery_id"] == "d1":
            raise ValueError("bad delivery")
        return "accepted"

    config = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_display_name="Product Bot",
        agent_registries=(make_registry_connection(),),
    )
    runtime = AgentRuntime(config, delivery_handler=handler, registry=config.agent_registries[0])
    assert await runtime.sync_once() == "connected"

    processed = await runtime.poll_once()

    assert processed == 2
    assert seen_deliveries == ["d1", "d2"]
    assert calls == [
        ("poll", "0"),
        ("accepted", ("d2",)),
        ("rejected", ("d1",)),
    ]


async def test_agent_runtime_run_forever_survives_unexpected_poll_error(tmp_path: Path):
    config = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registries=(make_registry_connection(),),
    )
    runtime = AgentRuntime(config, registry=config.agent_registries[0])
    stop_event = asyncio.Event()

    async def fake_sync_once():
        return "connected"

    async def fake_poll_once():
        stop_event.set()
        raise RuntimeError("unexpected delivery bug")

    runtime.sync_once = fake_sync_once  # type: ignore[method-assign]
    runtime.poll_once = fake_poll_once  # type: ignore[method-assign]

    await runtime.run_forever(stop_event)


async def test_admit_registry_delivery_queued_is_accepted(monkeypatch, tmp_path: Path):
    seen: list[tuple[str, str]] = []
    egress_kwargs: list[dict[str, object]] = []

    class _FakeEgress:
        async def sync_binding(self, binding):
            seen.append(("bind", str(binding.conversation_ref)))

    class _FakeDispatcher:
        def create_egress(self, conversation_ref, *, config, **kwargs):
            del conversation_ref, config
            egress_kwargs.append(dict(kwargs))
            return _FakeEgress()

    config = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registries=(make_registry_connection(),),
    )

    outcome_message = await admit_registry_delivery(
        config,
        {
            "kind": "channel_input",
            "delivery_id": "delivery-1",
            "registry_id": "prod",
            "payload": {"conversation_id": "conv-1", "text": "hello"},
        },
        submitter=_QueuedRegistrySubmitter(),
        dispatcher=_FakeDispatcher(),
    )
    outcome_task = await admit_registry_delivery(
        config,
        {
            "kind": "routed_task",
            "delivery_id": "delivery-2",
            "registry_id": "prod",
            "payload": {
                "routed_task_id": "task-1",
                "title": "Review",
                "instructions": "Review this change.",
                "origin_agent_id": "origin-1",
                "requested_capabilities": ["reviewer"],
            },
        },
        submitter=_QueuedRegistrySubmitter(),
        dispatcher=_FakeDispatcher(),
    )

    assert outcome_message == "accepted"
    assert outcome_task == "accepted"
    assert ("bind", registry_conversation_ref("prod", "conv-1")) in seen
    assert ("bind", registry_task_ref("prod", "task-1")) not in seen
    assert egress_kwargs == [
        {
            "conversation_key": _reg_conv(registry_conversation_ref("prod", "conv-1")),
            "source": "registry",
        }
    ]
    assert "bot" not in egress_kwargs[0]


async def test_admit_registry_delivery_preserves_external_id_for_qualified_non_registry_ref(
    monkeypatch,
    tmp_path: Path,
):
    seen_bindings: list[dict[str, str]] = []

    class _FakeEgress:
        async def sync_binding(self, binding):
            seen_bindings.append(
                {
                    "conversation_ref": str(binding.conversation_ref),
                    "external_id": str(binding.external_id),
                    "origin_channel": str(binding.origin_channel),
                }
            )

    class _FakeDispatcher:
        def create_egress(self, conversation_ref, *, config, **kwargs):
            del conversation_ref, config, kwargs
            return _FakeEgress()

    config = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registries=(make_registry_connection(),),
    )

    outcome = await admit_registry_delivery(
        config,
        {
            "kind": "channel_input",
            "delivery_id": "delivery-slack-1",
            "registry_id": "prod",
            "payload": {
                "conversation_id": "slack:eng:C0123ABC",
                "text": "hello slack",
            },
        },
        submitter=_QueuedRegistrySubmitter(),
        dispatcher=_FakeDispatcher(),
    )

    assert outcome == "accepted"
    assert seen_bindings == [
        {
            "conversation_ref": "slack:eng:C0123ABC",
            "external_id": "slack:eng:C0123ABC",
            "origin_channel": "registry",
        }
    ]


async def test_admit_registry_delivery_preserves_registry_external_conversation_ref(
    monkeypatch,
    tmp_path: Path,
):
    seen_bindings: list[dict[str, str]] = []

    class _FakeEgress:
        async def sync_binding(self, binding):
            seen_bindings.append(
                {
                    "conversation_ref": str(binding.conversation_ref),
                    "external_id": str(binding.external_id),
                }
            )

    class _FakeDispatcher:
        def create_egress(self, conversation_ref, *, config, **kwargs):
            del conversation_ref, config, kwargs
            return _FakeEgress()

    config = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registries=(make_registry_connection(),),
    )

    outcome = await admit_registry_delivery(
        config,
        {
            "kind": "channel_input",
            "delivery_id": "delivery-reg-1",
            "registry_id": "prod",
            "payload": {
                "conversation_id": "conv-1",
                "text": "hello registry",
                "external_conversation_ref": "operator-conv-1",
            },
        },
        submitter=_QueuedRegistrySubmitter(),
        dispatcher=_FakeDispatcher(),
    )

    assert outcome == "accepted"
    assert seen_bindings == [
        {
            "conversation_ref": registry_conversation_ref("prod", "conv-1"),
            "external_id": "operator-conv-1",
        }
    ]


async def test_admit_registry_delivery_deduplicates_identical_routed_task_title_and_instructions(
    tmp_path: Path,
):
    captured: dict[str, str] = {}

    class _CapturingSubmitter:
        async def admit_message(self, envelope):
            captured["text"] = envelope.event.text
            return InboundSubmissionResult(status="queued", item_id="queued-item")

    config = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registries=(make_registry_connection(),),
    )

    outcome = await admit_registry_delivery(
        config,
        {
            "kind": "routed_task",
            "delivery_id": "delivery-dup-1",
            "registry_id": "prod",
            "payload": {
                "routed_task_id": "task-dup-1",
                "title": "what is 2 + 3",
                "instructions": "what is 2 + 3",
                "origin_agent_id": "origin-1",
            },
        },
        submitter=_CapturingSubmitter(),
        dispatcher=None,
    )

    assert outcome == "accepted"
    assert captured["text"] == "what is 2 + 3"


async def test_admit_registry_delivery_rejects_legacy_surface_input_kind(monkeypatch, tmp_path: Path):
    seen: list[str] = []

    class _FakeDispatcher:
        def create_egress(self, conversation_ref, *, config, **kwargs):
            del conversation_ref, config, kwargs
            seen.append("create_egress")
            raise AssertionError("legacy surface input should not create egress")

    config = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registries=(make_registry_connection(),),
    )

    outcome = await admit_registry_delivery(
        config,
        {
            "kind": "surface_input",
            "delivery_id": "delivery-legacy",
            "payload": {"conversation_id": "conv-legacy", "text": "hello"},
        },
        submitter=_QueuedRegistrySubmitter(),
        dispatcher=_FakeDispatcher(),
    )

    assert outcome == "rejected"
    assert seen == []


async def test_handle_registry_routed_result_does_not_publish_parent_timeline_before_retry_on_startup_race(monkeypatch, tmp_path: Path):
    egress_calls: list[str] = []

    with fresh_env(
        config_overrides={
            "agent_mode": "registry",
            "agent_registries": (make_registry_connection(),),
        }
    ) as (_data_dir, config, prov):
        parent_conversation_ref = telegram_conversation_ref(config, 12345)
        dispatcher = current_runtime().transport_dispatcher
        services = current_runtime().services

        def fake_create_egress(conversation_ref, *, config, **kwargs):
            del config, kwargs
            egress_calls.append(str(conversation_ref))
            raise AssertionError("projection-only registry delivery should not build egress")

        monkeypatch.setattr(dispatcher, "create_egress", fake_create_egress)
        outcome = await handle_registry_delivery(
            config,
            {
                "registry_id": "default",
                "kind": "routed_result",
                "payload": {
                    "routed_task_id": "task-1",
                    "parent_conversation_id": parent_conversation_ref,
                    "result": {
                        "status": "completed",
                        "transition_id": "task-1-complete",
                        "summary": "Summary",
                        "full_text": "Delegated task completed successfully.",
                    },
                },
            },
            runtime=build_registry_delivery_runtime(
                provider_name=prov.name,
                provider_state_factory=prov.new_provider_state,
                services=services,
                submitter=current_runtime().submitter,
                bot=None,
                dispatcher=dispatcher,
            ),
        )

        assert outcome == "retry_later"
        assert egress_calls == []


async def test_admit_registry_delivery_rejects_missing_registry_id(monkeypatch, tmp_path: Path):
    seen: list[str] = []

    class _FakeDispatcher:
        def create_egress(self, conversation_ref, *, config, **kwargs):
            del conversation_ref, config, kwargs
            seen.append("create_egress")
            raise AssertionError("missing registry_id should reject before egress creation")

    config = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registries=(make_registry_connection(),),
    )

    outcome = await admit_registry_delivery(
        config,
        {
            "kind": "channel_input",
            "delivery_id": "delivery-missing-registry",
            "payload": {"conversation_id": "conv-1", "text": "hello"},
        },
        submitter=_QueuedRegistrySubmitter(),
        dispatcher=_FakeDispatcher(),
    )

    assert outcome == "rejected"
    assert seen == []


async def test_handle_registry_channel_action_and_control_dispatch(tmp_path: Path):
    with fresh_env(
        config_overrides={
            "agent_mode": "registry",
            "agent_registries": (make_registry_connection(),),
        }
    ) as (data_dir, cfg, _prov):
        runtime = build_registry_delivery_runtime(
            provider_name=_prov.name,
            provider_state_factory=_prov.new_provider_state,
            services=current_runtime().services,
            submitter=current_runtime().submitter,
            bot=None,
        )

        approve_outcome = await handle_registry_delivery(
            cfg,
            {
                "delivery_id": "d-approve",
                "registry_id": "prod",
                "kind": "channel_action",
                "payload": {"conversation_id": "conv-approve", "action": "approve"},
            },
            runtime=runtime,
        )
        control_outcome = await handle_registry_delivery(
            cfg,
            {
                "delivery_id": "d-cancel",
                "registry_id": "prod",
                "kind": "channel_action",
                "payload": {"conversation_id": "conv-cancel", "action": "cancel_conversation"},
            },
            runtime=runtime,
        )

        assert approve_outcome == "accepted"
        assert control_outcome == "accepted"
        approve_payload = work_queue.get_update_payload(data_dir, "reg:d-approve")
        cancel_payload = work_queue.get_update_payload(data_dir, "reg:d-cancel")
        assert approve_payload is not None
        assert cancel_payload is not None

        approve_event = deserialize_inbound("action", approve_payload)
        cancel_event = deserialize_inbound("action", cancel_payload)
        assert (
            approve_event.action,
            approve_event.conversation_key,
            approve_event.conversation_ref,
        ) == (
            "approve_pending",
            _reg_conv(registry_conversation_ref("prod", "conv-approve")),
            registry_conversation_ref("prod", "conv-approve"),
        )
        assert (
            cancel_event.action,
            cancel_event.conversation_key,
            cancel_event.conversation_ref,
        ) == (
            "cancel_conversation",
            _reg_conv(registry_conversation_ref("prod", "conv-cancel")),
            registry_conversation_ref("prod", "conv-cancel"),
        )


async def test_handle_registry_channel_action_preserves_already_qualified_future_surface_ref(tmp_path: Path):
    with fresh_env(
        config_overrides={
            "agent_mode": "registry",
            "agent_registries": (make_registry_connection(),),
        }
    ) as (data_dir, cfg, _prov):
        runtime = build_registry_delivery_runtime(
            provider_name=_prov.name,
            provider_state_factory=_prov.new_provider_state,
            services=current_runtime().services,
            submitter=current_runtime().submitter,
            bot=None,
        )
        qualified_ref = "slack:eng:12345"

        outcome = await handle_registry_delivery(
            cfg,
            {
                "delivery_id": "d-slack-approve",
                "registry_id": "prod",
                "kind": "channel_action",
                "payload": {"conversation_id": qualified_ref, "action": "approve"},
            },
            runtime=runtime,
        )

        assert outcome == "accepted"
        payload = work_queue.get_update_payload(data_dir, "reg:d-slack-approve")
        assert payload is not None
        event = deserialize_inbound("action", payload)
        assert event.conversation_ref == qualified_ref
        assert event.conversation_key == qualified_ref


async def test_handle_registry_delivery_rejects_legacy_surface_input_kind(monkeypatch, tmp_path: Path):
    seen: list[str] = []

    config = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registries=(make_registry_connection(),),
    )

    class _RejectingDispatcher:
        def create_egress(self, conversation_ref, *, config, **kwargs):
            del config, kwargs
            seen.append(str(conversation_ref))
            raise AssertionError("legacy surface input should not create egress")

    outcome = await handle_registry_delivery(
        config,
        {
            "delivery_id": "d-legacy-input",
            "kind": "surface_input",
            "payload": {"conversation_id": "conv-legacy-input", "text": "hello"},
        },
        runtime=build_registry_delivery_runtime(
            provider_name="claude",
            provider_state_factory=dict,
            services=build_test_bot_services(),
            submitter=_QueuedRegistrySubmitter(),
            bot=None,
            dispatcher=_RejectingDispatcher(),
        ),
    )

    assert outcome == "rejected"
    assert seen == []


async def test_handle_registry_delivery_rejects_legacy_surface_action_kind(tmp_path: Path):
    with fresh_env(
        config_overrides={
            "agent_mode": "registry",
            "agent_registries": (make_registry_connection(),),
        }
    ) as (data_dir, cfg, _prov):
        runtime = build_registry_delivery_runtime(
            provider_name=_prov.name,
            provider_state_factory=_prov.new_provider_state,
            services=current_runtime().services,
            submitter=current_runtime().submitter,
            bot=None,
        )

        outcome = await handle_registry_delivery(
            cfg,
            {
                "delivery_id": "d-legacy-approve",
                "kind": "surface_action",
                "payload": {"conversation_id": "conv-legacy-approve", "action": "approve"},
            },
            runtime=runtime,
        )

        assert outcome == "rejected"
        approve_payload = work_queue.get_update_payload(data_dir, "reg:d-legacy-approve")
        assert approve_payload is None


async def test_handle_registry_delivery_rejects_missing_registry_id_for_registry_owned_kinds(tmp_path: Path):
    with fresh_env(
        config_overrides={
            "agent_mode": "registry",
            "agent_registries": (make_registry_connection(),),
        }
    ) as (_data_dir, cfg, prov):
        runtime = build_registry_delivery_runtime(
            provider_name=prov.name,
            provider_state_factory=prov.new_provider_state,
            services=current_runtime().services,
            submitter=current_runtime().submitter,
            bot=None,
        )

        assert await handle_registry_delivery(
            cfg,
            {
                "delivery_id": "d-missing-action-registry",
                "kind": "channel_action",
                "payload": {"conversation_id": "conv-1", "action": "approve"},
            },
            runtime=runtime,
        ) == "rejected"


async def test_handle_registry_routed_result_preserves_already_qualified_future_surface_parent_ref(
    monkeypatch,
    tmp_path: Path,
):
    with fresh_env(
        config_overrides={
            "agent_mode": "registry",
            "agent_registries": (make_registry_connection(),),
        }
    ) as (_data_dir, cfg, prov):
        seen_ready_refs: list[tuple[str, str]] = []

        class _FakeDispatcher:
            def egress_ready_for_ref(self, conversation_ref, *, config, **kwargs):
                del config
                seen_ready_refs.append(
                    (str(conversation_ref), str(kwargs.get("conversation_key", "")))
                )
                return False

        runtime = build_registry_delivery_runtime(
            provider_name=prov.name,
            provider_state_factory=prov.new_provider_state,
            services=build_test_bot_services(),
            submitter=current_runtime().submitter,
            bot=None,
            dispatcher=_FakeDispatcher(),
        )
        qualified_ref = "slack:eng:12345"

        outcome = await handle_registry_delivery(
            cfg,
            {
                "delivery_id": "d-slack-result",
                "registry_id": "prod",
                "kind": "routed_result",
                "payload": {
                    "routed_task_id": "task-1",
                    "parent_conversation_id": "coord-slack-parent-1",
                    "parent_transport_ref": qualified_ref,
                    "result": {
                        "status": "completed",
                        "transition_id": "task-1-complete",
                        "summary": "done",
                        "full_text": "Delegated task completed successfully.",
                    },
                },
            },
            runtime=runtime,
        )

        assert outcome == "retry_later"
        assert seen_ready_refs == [(qualified_ref, qualified_ref)]
        assert await handle_registry_delivery(
            cfg,
            {
                "delivery_id": "d-missing-result-registry",
                "kind": "routed_result",
                "payload": {
                    "routed_task_id": "task-1",
                    "parent_conversation_id": "telegram:bot-1:12345",
                    "result": {"status": "completed", "transition_id": "task-1-complete-2", "summary": "done"},
                },
            },
            runtime=runtime,
        ) == "rejected"


async def test_handle_registry_routed_result_resumes_non_telegram_parent_using_explicit_transport_ref(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    with fresh_env(
        config_overrides={
            "agent_mode": "registry",
            "agent_registries": (make_registry_connection(),),
        }
    ) as (_data_dir, cfg, prov):
        class _FakeSubmitter:
            def __init__(self) -> None:
                self.envelopes = []

            async def admit_message(self, envelope):
                self.envelopes.append(envelope)
                return InboundSubmissionResult(status="admitted", item_id="resume-item")

        class _FakeEgress:
            def __init__(self) -> None:
                self.sent_texts: list[str] = []

            async def send_text(self, text: str) -> None:
                self.sent_texts.append(text)

        class _FakeDispatcher:
            def __init__(self, egress: _FakeEgress) -> None:
                self.egress = egress
                self.ready_refs: list[tuple[str, str]] = []
                self.created_refs: list[tuple[str, str, str]] = []

            def egress_ready_for_ref(self, conversation_ref, *, config, **kwargs):
                del config
                self.ready_refs.append(
                    (str(conversation_ref), str(kwargs.get("conversation_key", "")))
                )
                return True

            def create_egress(self, conversation_ref, *, config, **kwargs):
                del config
                self.created_refs.append(
                    (
                        str(conversation_ref),
                        str(kwargs.get("conversation_key", "")),
                        str(kwargs.get("external_id", "")),
                    )
                )
                return self.egress

        submitter = _FakeSubmitter()
        egress = _FakeEgress()
        dispatcher = _FakeDispatcher(egress)
        runtime = build_registry_delivery_runtime(
            provider_name=prov.name,
            provider_state_factory=prov.new_provider_state,
            services=build_test_bot_services(),
            submitter=submitter,
            bot=None,
            dispatcher=dispatcher,
        )
        parent_ref = "slack:workspace:channel-42"

        monkeypatch.setattr(
            "app.channels.registry.delivery_transport.apply_runtime_delegation_result",
            lambda *args, **kwargs: DelegationUpdateOutcome(
                status="completed",
                matched=True,
                ready_to_resume=True,
                resume_prompt="Resume with the specialist output.",
                pending=PendingDelegation(
                    conversation_ref="coord-parent-1",
                    origin_conversation_key=parent_ref,
                    proposal_id="proposal-1",
                    title="Ask the specialist",
                    tasks=[
                        DelegatedTask(
                            routed_task_id="task-1",
                            title="Investigate",
                            status="completed",
                            summary="Specialist finished.",
                            full_text="Detailed specialist output.",
                        )
                    ],
                    status="completed",
                ),
            ),
        )

        outcome = await handle_registry_delivery(
            cfg,
            {
                "delivery_id": "d-slack-resume-result",
                "registry_id": "prod",
                "kind": "routed_result",
                "payload": {
                    "routed_task_id": "task-1",
                    "parent_conversation_id": "coord-parent-1",
                    "parent_transport_ref": parent_ref,
                    "result": {
                        "status": "completed",
                        "transition_id": "task-1-complete",
                        "summary": "done",
                        "full_text": "Delegated task completed successfully.",
                    },
                },
            },
            runtime=runtime,
        )

        assert outcome == "accepted"
        assert dispatcher.ready_refs == [(parent_ref, parent_ref)]
        assert dispatcher.created_refs == [(parent_ref, parent_ref, parent_ref)]
        assert submitter.envelopes
        assert submitter.envelopes[0].conversation_ref == parent_ref
        assert submitter.envelopes[0].conversation_key == parent_ref
        assert egress.sent_texts
        assert "All delegated tasks completed" in egress.sent_texts[0]


async def test_handle_registry_routed_result_logs_warning_when_authority_does_not_match(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
):
    with fresh_env(
        config_overrides={
            "agent_mode": "registry",
            "agent_registries": (make_registry_connection(),),
        }
    ) as (_data_dir, cfg, prov):
        class _FakeDispatcher:
            def egress_ready_for_ref(self, conversation_ref, *, config, **kwargs):
                del conversation_ref, config, kwargs
                return True

        monkeypatch.setattr(
            "app.channels.registry.delivery_transport.apply_runtime_delegation_result",
            lambda *args, **kwargs: DelegationUpdateOutcome(status="submitted", matched=False),
        )
        services = build_test_bot_services()
        runtime = build_registry_delivery_runtime(
            provider_name=prov.name,
            provider_state_factory=prov.new_provider_state,
            services=services,
            submitter=current_runtime().submitter,
            bot=None,
            dispatcher=_FakeDispatcher(),
        )

        with caplog.at_level(logging.WARNING):
            outcome = await handle_registry_delivery(
                cfg,
                {
                    "delivery_id": "d-mismatch-result",
                    "registry_id": "prod",
                    "kind": "routed_result",
                    "payload": {
                        "routed_task_id": "task-1",
                        "parent_conversation_id": "coord-telegram-parent-1",
                        "parent_transport_ref": "telegram:bot-1:12345",
                        "result": {
                            "status": "completed",
                            "transition_id": "task-1-complete",
                            "summary": "done",
                            "full_text": "Delegated task completed successfully.",
                        },
                    },
                },
                runtime=runtime,
            )

        assert outcome == "accepted"
        assert any(
            "Routed result for task task-1 authority registry:prod did not match"
            in record.message
            for record in caplog.records
        )


async def test_handle_registry_routed_result_does_not_log_warning_when_result_matches(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
):
    with fresh_env(
        config_overrides={
            "agent_mode": "registry",
            "agent_registries": (make_registry_connection(),),
        }
    ) as (_data_dir, cfg, prov):
        class _FakeDispatcher:
            def egress_ready_for_ref(self, conversation_ref, *, config, **kwargs):
                del conversation_ref, config, kwargs
                return True

        monkeypatch.setattr(
            "app.channels.registry.delivery_transport.apply_runtime_delegation_result",
            lambda *args, **kwargs: DelegationUpdateOutcome(
                status="submitted",
                matched=True,
                ready_to_resume=False,
            ),
        )
        services = build_test_bot_services()
        runtime = build_registry_delivery_runtime(
            provider_name=prov.name,
            provider_state_factory=prov.new_provider_state,
            services=services,
            submitter=current_runtime().submitter,
            bot=None,
            dispatcher=_FakeDispatcher(),
        )

        with caplog.at_level(logging.WARNING):
            outcome = await handle_registry_delivery(
                cfg,
                {
                    "delivery_id": "d-match-result",
                    "registry_id": "prod",
                    "kind": "routed_result",
                    "payload": {
                        "routed_task_id": "task-1",
                        "parent_conversation_id": "coord-telegram-parent-2",
                        "parent_transport_ref": "telegram:bot-1:12345",
                        "result": {
                            "status": "completed",
                            "transition_id": "task-1-complete",
                            "summary": "done",
                            "full_text": "Delegated task completed successfully.",
                        },
                    },
                },
                runtime=runtime,
            )

        assert outcome == "accepted"
        assert not any(
            "did not match any pending delegation task" in record.message
            for record in caplog.records
        )
