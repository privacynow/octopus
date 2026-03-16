"""Tests for agent-mode config/runtime foundation."""

from pathlib import Path

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


async def test_handle_registry_routed_result_publishes_parent_timeline(monkeypatch, tmp_path: Path):
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

    assert outcome == "accepted"
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
