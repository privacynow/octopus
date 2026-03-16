"""Tests for agent-mode config/runtime foundation."""

import asyncio
from pathlib import Path

from app.agents.bridge import admit_registry_delivery, registry_chat_id
from app.agents.delivery import handle_registry_delivery
from app.agents.runtime import AgentRuntime
from app.agents.state import load_agent_runtime_state
from app.config import derive_agent_slug
from tests.support.config_support import make_config


def test_derive_agent_slug_normalizes_display_name():
    assert derive_agent_slug(" Product Bot / Reviewer ") == "product-bot-reviewer"
    assert derive_agent_slug("!!!", fallback="fallback-agent") == "fallback-agent"


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
        agent_skills=("planning", "delegation"),
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


async def test_admit_registry_delivery_busy_returns_retry_later(monkeypatch, tmp_path: Path):
    async def should_not_run(*args, **kwargs):
        raise AssertionError("bind/timeline should not run for busy delivery")

    monkeypatch.setattr("app.agents.bridge.bind_conversation", should_not_run)
    monkeypatch.setattr("app.agents.bridge.publish_timeline_event", should_not_run)
    monkeypatch.setattr(
        "app.agents.bridge.work_queue.record_and_admit_message",
        lambda *args, **kwargs: ("busy", None),
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

    assert outcome_message == "retry_later"
    assert outcome_task == "retry_later"


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
    seen: list[tuple[str, int, str]] = []

    async def fake_approve(chat_id: int, message) -> None:
        seen.append(("approve", chat_id, message.conversation_ref))

    async def fake_cancel(chat_id: int, message, *, actor_user_id: int = 0, allow_admin_override: bool = False, update_id: int | None = None) -> None:
        del actor_user_id, allow_admin_override, update_id
        seen.append(("cancel", chat_id, message.conversation_ref))

    monkeypatch.setattr("app.telegram_handlers.approve_pending", fake_approve)
    monkeypatch.setattr("app.telegram_handlers.cancel_chat_operation", fake_cancel)

    config = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registry_url="http://registry.test",
        agent_registry_enroll_token="enroll-secret",
    )

    approve_outcome = await handle_registry_delivery(
        config,
        {
            "kind": "surface_action",
            "payload": {"conversation_id": "conv-approve", "action": "approve"},
        },
    )
    control_outcome = await handle_registry_delivery(
        config,
        {
            "kind": "control",
            "payload": {"conversation_id": "conv-cancel", "action": "cancel"},
        },
    )

    assert approve_outcome == "accepted"
    assert control_outcome == "accepted"
    assert seen == [
        ("approve", registry_chat_id("conv-approve"), "conv-approve"),
        ("cancel", registry_chat_id("conv-cancel"), "conv-cancel"),
    ]
