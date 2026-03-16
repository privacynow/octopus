"""Tests for the FastAPI registry control-plane service."""

from pathlib import Path

from fastapi.testclient import TestClient

from app.registry_service.app import app


def _configure_registry(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("REGISTRY_DB_PATH", str(tmp_path / "registry.sqlite3"))
    monkeypatch.setenv("REGISTRY_ENROLL_TOKEN", "enroll-secret")
    monkeypatch.setenv("REGISTRY_UI_TOKEN", "ui-secret")


def _enroll_and_register(client: TestClient, name: str, slug: str) -> tuple[str, str]:
    enroll = client.post(
        "/v1/agents/enroll",
        json={
            "enrollment_token": "enroll-secret",
            "agent_card": {
                "display_name": name,
                "slug": slug,
                "role": "developer",
                "skills": ["python", "tests"],
                "tags": ["backend"],
                "description": "Writes and tests code",
                "provider": "codex",
                "mode": "registry",
                "connectivity_state": "degraded",
                "surface_capabilities": ["telegram", "registry"],
                "version": "test",
            },
        },
    )
    assert enroll.status_code == 200
    agent_id = enroll.json()["agent_id"]
    token = enroll.json()["agent_token"]
    register = client.post(
        "/v1/agents/register",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "agent_card": {
                "display_name": name,
                "slug": slug,
                "role": "developer",
                "skills": ["python", "tests"],
                "tags": ["backend"],
                "description": "Writes and tests code",
                "provider": "codex",
                "mode": "registry",
                "surface_capabilities": ["telegram", "registry"],
                "version": "test",
            },
            "connectivity_state": "connected",
            "current_capacity": 0,
            "max_capacity": 2,
        },
    )
    assert register.status_code == 200
    return agent_id, token


def test_registry_enroll_register_heartbeat_and_search(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    agent_id, token = _enroll_and_register(client, "Dev Bot", "dev-bot")

    heartbeat = client.post(
        "/v1/agents/heartbeat",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "connectivity_state": "connected",
            "current_capacity": 1,
            "max_capacity": 3,
        },
    )
    assert heartbeat.status_code == 200
    assert heartbeat.json()["agent"]["agent_id"] == agent_id

    search = client.post(
        "/v1/agents/discovery/search",
        headers={"Authorization": f"Bearer {token}"},
        json={"role": "developer", "skills": ["python"], "required_state": "connected"},
    )
    assert search.status_code == 200
    agents = search.json()["agents"]
    assert len(agents) == 1
    assert agents[0]["slug"] == "dev-bot"
    assert agents[0]["connectivity_state"] == "connected"


def test_registry_bind_conversation_is_visible_in_ui(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    _, token = _enroll_and_register(client, "Dev Bot", "dev-bot")
    bind = client.post(
        "/v1/agents/conversations/bind",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "conversation_id": "telegram:dev-bot:123",
            "title": "Telegram chat 123",
            "origin_surface": "telegram",
            "external_id": "123",
        },
    )
    assert bind.status_code == 200
    assert bind.json()["conversation_id"] == "telegram:dev-bot:123"

    conversations = client.get(
        "/v1/ui/conversations",
        headers={"Authorization": "Bearer ui-secret"},
    )
    assert conversations.status_code == 200
    items = conversations.json()["conversations"]
    assert len(items) == 1
    assert items[0]["conversation_id"] == "telegram:dev-bot:123"
    assert items[0]["title"] == "Telegram chat 123"


def test_registry_ui_conversation_routes_surface_input_to_polled_bot(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    agent_id, token = _enroll_and_register(client, "Product Bot", "product-bot-2")
    create = client.post(
        "/v1/ui/conversations",
        headers={"Authorization": "Bearer ui-secret"},
        json={
            "target_agent_id": agent_id,
            "title": "Spec review",
            "message_text": "Please refine this PRD.",
        },
    )
    assert create.status_code == 200
    conversation_id = create.json()["conversation_id"]

    poll = client.get(
        "/v1/agents/poll",
        headers={"Authorization": f"Bearer {token}"},
        params={"cursor": "0", "limit": 20, "wait_seconds": 0},
    )
    assert poll.status_code == 200
    deliveries = poll.json()["deliveries"]
    assert len(deliveries) == 1
    assert deliveries[0]["kind"] == "surface_input"
    assert deliveries[0]["payload"]["conversation_id"] == conversation_id
    assert deliveries[0]["payload"]["text"] == "Please refine this PRD."

    ack = client.post(
        "/v1/agents/ack",
        headers={"Authorization": f"Bearer {token}"},
        json={"delivery_ids": [deliveries[0]["delivery_id"]], "classification": "accepted"},
    )
    assert ack.status_code == 200

    timeline = client.get(
        f"/v1/ui/conversations/{conversation_id}/timeline",
        headers={"Authorization": "Bearer ui-secret"},
    )
    assert timeline.status_code == 200
    assert timeline.json()["events"][0]["title"] == "Conversation started"


def test_publish_timeline_stores_events(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    agent_id, token = _enroll_and_register(client, "Registry Bot", "registry-bot")
    bind = client.post(
        "/v1/agents/conversations/bind",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "conversation_id": "conv-timeline-1",
            "title": "Timeline conversation",
            "origin_surface": "registry",
            "external_id": "conv-timeline-1",
        },
    )
    assert bind.status_code == 200

    publish = client.post(
        "/v1/agents/timeline",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "events": [
                {
                    "event_id": "evt-1",
                    "conversation_id": "conv-timeline-1",
                    "kind": "started",
                    "title": "Conversation started",
                    "body": "",
                    "created_at": "2026-03-15T00:00:00+00:00",
                },
                {
                    "event_id": "evt-2",
                    "conversation_id": "conv-timeline-1",
                    "kind": "completed",
                    "title": "Done",
                    "body": "Finished work",
                    "created_at": "2026-03-15T00:00:01+00:00",
                },
            ]
        },
    )
    assert publish.status_code == 200

    timeline = client.get(
        "/v1/ui/conversations/conv-timeline-1/timeline",
        headers={"Authorization": "Bearer ui-secret"},
    )
    assert timeline.status_code == 200
    events = timeline.json()["events"]
    assert [event["event_id"] for event in events] == ["evt-1", "evt-2"]
    assert [event["kind"] for event in events] == ["started", "completed"]


def test_ui_bootstrap_includes_timeline_event_count(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    _, token = _enroll_and_register(client, "Registry Bot", "registry-bot-count")
    bind = client.post(
        "/v1/agents/conversations/bind",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "conversation_id": "conv-count-1",
            "title": "Counted timeline",
            "origin_surface": "registry",
            "external_id": "conv-count-1",
        },
    )
    assert bind.status_code == 200
    publish = client.post(
        "/v1/agents/timeline",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "events": [
                {
                    "event_id": "evt-count-1",
                    "conversation_id": "conv-count-1",
                    "kind": "started",
                    "title": "Conversation started",
                    "created_at": "2026-03-15T00:00:00+00:00",
                },
                {
                    "event_id": "evt-count-2",
                    "conversation_id": "conv-count-1",
                    "kind": "progress",
                    "title": "Working…",
                    "body": "Inspecting task",
                    "created_at": "2026-03-15T00:00:01+00:00",
                },
            ]
        },
    )
    assert publish.status_code == 200

    bootstrap = client.get(
        "/v1/ui/bootstrap",
        headers={"Authorization": "Bearer ui-secret"},
    )
    assert bootstrap.status_code == 200
    conversations = bootstrap.json()["conversations"]
    assert conversations[0]["conversation_id"] == "conv-count-1"
    assert conversations[0]["timeline_event_count"] == 2


def test_ui_create_conversation_creates_delivery(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    agent_id, token = _enroll_and_register(client, "Product Bot", "product-bot-delivery")
    create = client.post(
        "/v1/ui/conversations",
        headers={"Authorization": "Bearer ui-secret"},
        json={
            "target_agent_id": agent_id,
            "title": "UI created work",
            "message_text": "Start from the registry UI.",
        },
    )
    assert create.status_code == 200
    conversation_id = create.json()["conversation_id"]

    poll = client.get(
        "/v1/agents/poll",
        headers={"Authorization": f"Bearer {token}"},
        params={"cursor": "0", "limit": 20, "wait_seconds": 0},
    )
    assert poll.status_code == 200
    deliveries = poll.json()["deliveries"]
    assert len(deliveries) == 1
    assert deliveries[0]["kind"] == "surface_input"
    assert deliveries[0]["payload"]["conversation_id"] == conversation_id
    assert deliveries[0]["payload"]["text"] == "Start from the registry UI."


def test_ui_action_delivery_includes_conversation_ref(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    agent_id, token = _enroll_and_register(client, "Product Bot", "product-bot-action")
    create = client.post(
        "/v1/ui/conversations",
        headers={"Authorization": "Bearer ui-secret"},
        json={
            "target_agent_id": agent_id,
            "title": "Actionable work",
            "message_text": "Start this from the registry UI.",
        },
    )
    assert create.status_code == 200
    conversation_id = create.json()["conversation_id"]

    action = client.post(
        f"/v1/ui/conversations/{conversation_id}/actions",
        headers={"Authorization": "Bearer ui-secret"},
        json={"action": "approve_delegation"},
    )
    assert action.status_code == 200

    poll = client.get(
        "/v1/agents/poll",
        headers={"Authorization": f"Bearer {token}"},
        params={"cursor": "0", "limit": 20, "wait_seconds": 0},
    )
    assert poll.status_code == 200
    deliveries = [item for item in poll.json()["deliveries"] if item["kind"] == "surface_action"]
    assert len(deliveries) == 1
    assert deliveries[0]["payload"]["conversation_ref"] == conversation_id
    assert deliveries[0]["payload"]["action"] == "approve_delegation"


def test_cancel_conversation_marks_status_cancelling_and_late_progress_does_not_reopen(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    agent_id, token = _enroll_and_register(client, "Product Bot", "product-bot-cancel")
    create = client.post(
        "/v1/ui/conversations",
        headers={"Authorization": "Bearer ui-secret"},
        json={
            "target_agent_id": agent_id,
            "title": "Cancelable work",
            "message_text": "Start this task.",
        },
    )
    assert create.status_code == 200
    conversation_id = create.json()["conversation_id"]

    cancel = client.post(
        f"/v1/ui/conversations/{conversation_id}/cancel",
        headers={"Authorization": "Bearer ui-secret"},
    )
    assert cancel.status_code == 200

    publish = client.post(
        "/v1/agents/timeline",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "events": [
                {
                    "event_id": "evt-cancel-progress",
                    "conversation_id": conversation_id,
                    "kind": "progress",
                    "title": "Working…",
                    "body": "Still winding down",
                    "created_at": "2026-03-15T00:00:02+00:00",
                }
            ]
        },
    )
    assert publish.status_code == 200

    conversation = client.get(
        f"/v1/ui/conversations/{conversation_id}",
        headers={"Authorization": "Bearer ui-secret"},
    )
    assert conversation.status_code == 200
    assert conversation.json()["status"] == "cancelling"


def test_publish_timeline_rejects_foreign_conversation(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    _, owner_token = _enroll_and_register(client, "Owner Bot", "owner-bot")
    _, other_token = _enroll_and_register(client, "Other Bot", "other-bot")

    bind = client.post(
        "/v1/agents/conversations/bind",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={
            "conversation_id": "conv-owner-1",
            "title": "Owner conversation",
            "origin_surface": "registry",
            "external_id": "conv-owner-1",
        },
    )
    assert bind.status_code == 200

    publish = client.post(
        "/v1/agents/timeline",
        headers={"Authorization": f"Bearer {other_token}"},
        json={
            "events": [
                {
                    "event_id": "evt-foreign-1",
                    "conversation_id": "conv-owner-1",
                    "kind": "started",
                    "title": "Should fail",
                    "created_at": "2026-03-15T00:00:00+00:00",
                }
            ]
        },
    )
    assert publish.status_code == 401
    assert "does not belong to agent" in publish.json()["detail"]


def test_registry_routed_result_returns_to_origin_agent(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    origin_id, origin_token = _enroll_and_register(client, "Product Bot", "product-origin")
    target_id, target_token = _enroll_and_register(client, "Reviewer Bot", "reviewer-target")

    routed = client.post(
        "/v1/agents/routed-tasks",
        headers={"Authorization": f"Bearer {origin_token}"},
        json={
            "routed_task_id": "task-1",
            "parent_conversation_id": "conv-1",
            "origin_agent_id": origin_id,
            "target_agent_id": target_id,
            "title": "Review test plan",
            "instructions": "Find missing test coverage.",
            "context": {},
            "constraints": {},
            "requested_capabilities": ["reviewer", "tests"],
            "priority": "normal",
            "created_at": "2026-03-15T00:00:00+00:00",
        },
    )
    assert routed.status_code == 200

    target_poll = client.get(
        "/v1/agents/poll",
        headers={"Authorization": f"Bearer {target_token}"},
        params={"cursor": "0", "limit": 20, "wait_seconds": 0},
    )
    assert target_poll.status_code == 200
    assert target_poll.json()["deliveries"][0]["kind"] == "routed_task"

    result = client.post(
        "/v1/agents/routed-tasks/task-1/result",
        headers={"Authorization": f"Bearer {target_token}"},
        json={
            "routed_task_id": "task-1",
            "status": "completed",
            "summary": "Added missing tests",
            "full_text": "Test plan updated with edge cases.",
            "artifacts": [],
            "follow_up_questions": [],
            "completed_at": "2026-03-15T00:01:00+00:00",
        },
    )
    assert result.status_code == 200

    origin_poll = client.get(
        "/v1/agents/poll",
        headers={"Authorization": f"Bearer {origin_token}"},
        params={"cursor": "0", "limit": 20, "wait_seconds": 0},
    )
    assert origin_poll.status_code == 200
    origin_deliveries = origin_poll.json()["deliveries"]
    assert any(item["kind"] == "routed_result" for item in origin_deliveries)
