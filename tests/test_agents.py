"""Tests for agent-mode config/runtime foundation."""

import asyncio
from pathlib import Path

from app.agents.bridge import admit_registry_delivery, conversation_key_for_ref
from app.agents.delivery import handle_registry_delivery
from app.agents.runtime import AgentRuntime
from app.agents.state import load_agent_runtime_state
from app.config import derive_agent_slug
from app.runtime_health import RuntimeHealthReport, RuntimeHealthSummary
from tests.support.config_support import make_config
from tests.support.handler_support import drain_one_worker_item, fresh_env


def _reg_conv(conversation_ref: str) -> str:
    return conversation_key_for_ref(conversation_ref)


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

    assert card.capabilities == ()


async def test_agent_runtime_standalone_marks_state(tmp_path: Path):
    config = make_config(
        data_dir=tmp_path,
        agent_mode="standalone",
        agent_display_name="Standalone Bot",
    )
    runtime = AgentRuntime(config)

    result = await runtime.sync_once()
    state = load_agent_runtime_state(tmp_path)

    assert result == "standalone"
    assert state.connectivity_state == "standalone"
    assert state.agent_id == ""
    assert state.agent_token == ""


async def test_agent_runtime_registry_without_url_degrades(tmp_path: Path):
    config = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registry_url="",
        agent_registry_enroll_token="token",
        agent_display_name="Registry Bot",
    )
    runtime = AgentRuntime(config)

    result = await runtime.sync_once()
    state = load_agent_runtime_state(tmp_path)

    assert result == "degraded"
    assert state.connectivity_state == "degraded"
    assert "Registry URL not configured" in state.last_error


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
            calls.append(("register", card.agent_id, connectivity_state))
            return {"ok": True}

        async def heartbeat(self, *, connectivity_state: str, current_capacity: int, max_capacity: int, active_work_count: int = 0, timeline_checkpoint: str = ""):
            calls.append(("heartbeat", connectivity_state, str(current_capacity)))
            return {"ok": True}

    monkeypatch.setattr("app.agents.runtime.AgentRegistryClient", FakeRegistryClient)
    config = make_config(
        data_dir=tmp_path,
        provider_name="codex",
        agent_mode="registry",
        agent_display_name="Product Bot",
        agent_slug="product-bot",
        agent_role="product",
        agent_capabilities=("planning", "delegation"),
        agent_registry_url="http://registry.test",
        agent_registry_enroll_token="enroll-secret",
    )
    runtime = AgentRuntime(config)

    result = await runtime.sync_once()
    state = load_agent_runtime_state(tmp_path)

    assert result == "connected"
    assert state.connectivity_state == "connected"
    assert state.agent_id == "agent-123"
    assert state.agent_token == "secret-token"
    assert calls == [
        ("enroll", "Product Bot", "enroll-secret"),
        ("register", "agent-123", "connected"),
        ("heartbeat", "connected", "0"),
    ]


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
            active_work_count: int = 0,
            timeline_checkpoint: str = "",
            runtime_health: dict | None = None,
        ):
            calls.append(("heartbeat", runtime_health, active_work_count))
            return {"ok": True}

    class FakeHealthProvider:
        async def collect(self, config, provider, *, caller_is_bot=False, session_context=None):
            assert caller_is_bot is True
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

    monkeypatch.setattr("app.agents.runtime.AgentRegistryClient", FakeRegistryClient)
    config = make_config(
        data_dir=tmp_path,
        provider_name="codex",
        agent_mode="registry",
        agent_display_name="Product Bot",
        agent_registry_url="http://registry.test",
        agent_registry_enroll_token="enroll-secret",
    )
    runtime = AgentRuntime(
        config,
        runtime_health_provider=FakeHealthProvider(),
        provider=object(),
    )

    assert await runtime.sync_once() == "connected"
    assert calls == [
        (
            "heartbeat",
            {
                "schema_version": 1,
                "generated_at": "2026-03-16T00:00:00+00:00",
                "summary": {
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
            },
            2,
        )
    ]


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

        async def heartbeat(self, *, connectivity_state: str, current_capacity: int, max_capacity: int, active_work_count: int = 0, timeline_checkpoint: str = ""):
            return {"ok": True}

        async def poll(self, *, cursor: str = "0", limit: int = 20, wait_seconds: int = 1):
            calls.append(("poll", cursor))
            return {
                "deliveries": [
                    {"delivery_id": "d1", "kind": "surface_input", "payload": {"conversation_id": "c1", "text": "hello"}},
                    {"delivery_id": "d2", "kind": "control", "payload": {"conversation_id": "c1", "action": "cancel"}},
                ],
                "next_cursor": "2",
            }

        async def ack(self, delivery_ids, *, classification: str):
            calls.append((classification, tuple(delivery_ids)))
            return {"ok": True}

    monkeypatch.setattr("app.agents.runtime.AgentRegistryClient", FakeRegistryClient)
    seen_deliveries: list[str] = []

    async def handler(delivery):
        seen_deliveries.append(delivery["delivery_id"])
        return "accepted" if delivery["kind"] == "surface_input" else "rejected"

    config = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_display_name="Product Bot",
        agent_registry_url="http://registry.test",
        agent_registry_enroll_token="enroll-secret",
    )
    runtime = AgentRuntime(config, delivery_handler=handler)
    assert await runtime.sync_once() == "connected"

    processed = await runtime.poll_once()
    state = load_agent_runtime_state(tmp_path)

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

        async def heartbeat(self, *, connectivity_state: str, current_capacity: int, max_capacity: int, active_work_count: int = 0, timeline_checkpoint: str = ""):
            return {"ok": True}

        async def poll(self, *, cursor: str = "0", limit: int = 20, wait_seconds: int = 1):
            calls.append(("poll", cursor))
            return {
                "deliveries": [
                    {"delivery_id": "d1", "kind": "surface_input", "payload": {"conversation_id": "c1", "text": "hello"}},
                    {"delivery_id": "d2", "kind": "surface_input", "payload": {"conversation_id": "c2", "text": "world"}},
                ],
                "next_cursor": "2",
            }

        async def ack(self, delivery_ids, *, classification: str):
            calls.append((classification, tuple(delivery_ids)))
            return {"ok": True}

    monkeypatch.setattr("app.agents.runtime.AgentRegistryClient", FakeRegistryClient)
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
        agent_registry_url="http://registry.test",
        agent_registry_enroll_token="enroll-secret",
    )
    runtime = AgentRuntime(config, delivery_handler=handler)
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
        agent_registry_url="http://registry.test",
        agent_registry_enroll_token="enroll-secret",
    )
    runtime = AgentRuntime(config)
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

    async def fake_bind(*args, **kwargs):
        del args
        seen.append(("bind", str(kwargs.get("conversation_ref", ""))))

    async def fake_timeline(*args, **kwargs):
        del args
        seen.append(("timeline", str(kwargs.get("conversation_ref", ""))))

    monkeypatch.setattr("app.agents.bridge.bind_conversation", fake_bind)
    monkeypatch.setattr("app.agents.bridge.publish_timeline_event", fake_timeline)
    monkeypatch.setattr(
        "app.agents.bridge.work_queue.record_and_admit_message",
        lambda *args, **kwargs: ("queued", "queued-item"),
    )
    config = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registry_url="http://registry.test",
        agent_registry_enroll_token="enroll-secret",
    )

    outcome_message = await admit_registry_delivery(
        config,
        {
            "kind": "surface_input",
            "delivery_id": "delivery-1",
            "payload": {"conversation_id": "conv-1", "text": "hello"},
        },
    )
    outcome_task = await admit_registry_delivery(
        config,
        {
            "kind": "routed_task",
            "delivery_id": "delivery-2",
            "payload": {
                "routed_task_id": "task-1",
                "title": "Review",
                "instructions": "Review this change.",
                "origin_agent_id": "origin-1",
                "requested_capabilities": ["reviewer"],
            },
        },
    )

    assert outcome_message == "accepted"
    assert outcome_task == "accepted"
    assert ("bind", "conv-1") in seen
    assert ("timeline", "conv-1") in seen
    assert ("bind", "task-1") in seen
    assert ("timeline", "task-1") in seen


async def test_handle_registry_routed_result_publishes_parent_timeline_before_retry_on_startup_race(monkeypatch, tmp_path: Path):
    published: list[dict[str, object]] = []

    async def fake_publish_timeline_event(
        config,
        *,
        conversation_ref: str,
        kind: str,
        title: str,
        body: str = "",
        status: str = "",
        progress: int | None = None,
        metadata: dict[str, object] | None = None,
        event_id: str | None = None,
    ) -> None:
        del config, progress, event_id
        published.append(
            {
                "conversation_ref": conversation_ref,
                "kind": kind,
                "title": title,
                "body": body,
                "status": status,
                "metadata": metadata or {},
            }
        )

    monkeypatch.setattr("app.agents.delivery.publish_timeline_event", fake_publish_timeline_event)
    config = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registry_url="http://registry.test",
        agent_registry_enroll_token="enroll-secret",
    )

    outcome = await handle_registry_delivery(
        config,
        {
            "kind": "routed_result",
            "payload": {
                "routed_task_id": "task-1",
                "parent_conversation_id": "conv-1",
                "result": {
                    "status": "completed",
                    "summary": "Summary",
                    "full_text": "Delegated task completed successfully.",
                },
            },
        },
    )

    assert outcome == "retry_later"
    assert published == [
        {
            "conversation_ref": "conv-1",
            "kind": "delegated_result",
            "title": "Delegated result received",
            "body": "Delegated task completed successfully.",
            "status": "completed",
            "metadata": {"routed_task_id": "task-1"},
        }
    ]


async def test_handle_registry_surface_action_and_control_dispatch(monkeypatch, tmp_path: Path):
    seen: list[tuple[str, str, str]] = []

    async def fake_execute_worker_action(event, item, *, cancel_event=None) -> None:
        del item, cancel_event
        seen.append((event.action, event.conversation_key, event.conversation_ref))

    monkeypatch.setattr("app.telegram_handlers._execute_worker_action", fake_execute_worker_action)

    with fresh_env(
        config_overrides={
            "agent_mode": "registry",
            "agent_registry_url": "http://registry.test",
            "agent_registry_enroll_token": "enroll-secret",
        }
    ) as (data_dir, cfg, _prov):
        approve_outcome = await handle_registry_delivery(
            cfg,
            {
                "delivery_id": "d-approve",
                "kind": "surface_action",
                "payload": {"conversation_id": "conv-approve", "action": "approve"},
            },
        )
        control_outcome = await handle_registry_delivery(
            cfg,
            {
                "delivery_id": "d-cancel",
                "kind": "control",
                "payload": {"conversation_id": "conv-cancel", "action": "cancel"},
            },
        )

        assert approve_outcome == "accepted"
        assert control_outcome == "accepted"
        assert await drain_one_worker_item(data_dir) is True
        assert await drain_one_worker_item(data_dir) is True
        assert seen == [
            ("approve_pending", _reg_conv("conv-approve"), "conv-approve"),
            ("cancel_conversation", _reg_conv("conv-cancel"), "conv-cancel"),
        ]
