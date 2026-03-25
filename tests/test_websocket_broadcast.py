"""Tests verifying WebSocket broadcasts from registry HTTP endpoints."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("REGISTRY_ALLOW_HTTP", "1")

from app.channels.registry.auth import reset_auth_attempt_limits_for_test
from app.channels.registry import http as registry_http
from app.channels.registry.http import app


def _configure(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("REGISTRY_DB_PATH", str(tmp_path / "registry.sqlite3"))
    monkeypatch.setenv("REGISTRY_ENROLL_TOKEN", "enroll-secret")
    monkeypatch.setenv("REGISTRY_UI_TOKEN", "ui-secret")
    monkeypatch.setenv("REGISTRY_ALLOW_HTTP", "1")
    monkeypatch.delenv("REGISTRY_SESSION_SECRET", raising=False)
    reset_auth_attempt_limits_for_test()


def _login_ui(client: TestClient) -> None:
    resp = client.post("/ui/login", data={"password": "ui-secret"}, follow_redirects=False)
    assert resp.status_code == 303


def _ui_csrf_token(client: TestClient) -> str:
    resp = client.get("/v1/auth/csrf")
    assert resp.status_code == 200
    return resp.json()["csrf_token"]


def _enroll_and_register(client: TestClient, slug: str) -> tuple[str, str]:
    enroll = client.post(
        "/v1/agents/enroll",
        json={
            "enrollment_token": "enroll-secret",
            "agent_card": {
                "display_name": slug,
                "slug": slug,
                "role": "developer",
                "registry_scope": "full",
                "capabilities": ["python"],
                "tags": [],
                "description": slug,
                "provider": "test",
                "mode": "registry",
                "channel_capabilities": ["registry"],
                "version": "test",
                "bot_key": f"bot-{slug}",
            },
        },
    )
    assert enroll.status_code == 200
    agent_id = enroll.json()["agent_id"]
    token = enroll.json()["agent_token"]
    client.post(
        "/v1/agents/register",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "agent_card": {
                "display_name": slug,
                "slug": slug,
                "role": "developer",
                "registry_scope": "full",
                "capabilities": ["python"],
                "tags": [],
                "description": slug,
                "provider": "test",
                "mode": "registry",
                "channel_capabilities": ["registry"],
                "version": "test",
            },
            "connectivity_state": "connected",
            "current_capacity": 0,
            "max_capacity": 2,
        },
    )
    return agent_id, token


def _create_conversation(client: TestClient, token: str, agent_id: str) -> str:
    resp = client.post(
        "/v1/conversations",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "target_agent_id": agent_id,
            "title": "Test conversation",
            "origin_channel": "registry",
            "external_conversation_ref": "ext-1",
        },
    )
    assert resp.status_code == 201
    return resp.json()["conversation_id"]


def _advance_task_lifecycle(store, *, agent_token: str, routed_task_id: str, conversation_id: str, to_running: bool = False) -> None:
    store.update_routed_task_status(
        agent_token,
        routed_task_id,
        {
            "status": "leased",
            "transition_id": f"{routed_task_id}-lease",
            "updated_at": "2026-03-22T00:00:00+00:00",
        },
    )
    if to_running:
        store.update_routed_task_status(
            agent_token,
            routed_task_id,
            {
                "status": "running",
                "transition_id": f"{routed_task_id}-start",
                "summary": "started",
                "timeline_events": [
                    {
                        "event_id": f"evt-{routed_task_id}-start",
                        "conversation_id": conversation_id,
                        "kind": "task.status",
                        "title": "Running",
                        "body": "started",
                        "status": "running",
                        "progress": 1,
                        "metadata": {},
                        "created_at": "2026-03-22T00:00:00+00:00",
                    }
                ],
                "updated_at": "2026-03-22T00:00:01+00:00",
            },
        )


@pytest.fixture()
def _ws_recorder(monkeypatch):
    """Replace _ws_manager.broadcast_event with a recorder."""
    calls: list[dict[str, Any]] = []
    original_manager = registry_http._ws_manager

    async def fake_broadcast(conversation_id: str, agent_id: str, event_data: dict) -> None:
        calls.append({
            "conversation_id": conversation_id,
            "agent_id": agent_id,
            "event_data": event_data,
        })

    monkeypatch.setattr(original_manager, "broadcast_event", fake_broadcast)
    return calls


@pytest.fixture()
def _ws_invalidation_recorder(monkeypatch):
    calls: list[dict[str, Any]] = []
    original_manager = registry_http._ws_manager

    async def fake_broadcast(
        topic: str,
        *,
        reason: str,
        conversation_id: str = "",
        agent_id: str = "",
        routed_task_id: str = "",
    ) -> None:
        calls.append(
            {
                "topic": topic,
                "reason": reason,
                "conversation_id": conversation_id,
                "agent_id": agent_id,
                "routed_task_id": routed_task_id,
            }
        )

    monkeypatch.setattr(original_manager, "broadcast_invalidation", fake_broadcast)
    return calls


@pytest.fixture()
def _ws_progress_recorder(monkeypatch):
    calls: list[dict[str, Any]] = []
    original_manager = registry_http._ws_manager

    async def fake_broadcast(conversation_id: str, agent_id: str, progress_data: dict) -> None:
        calls.append(
            {
                "conversation_id": conversation_id,
                "agent_id": agent_id,
                "progress_data": progress_data,
            }
        )

    monkeypatch.setattr(original_manager, "broadcast_progress", fake_broadcast)
    return calls


@pytest.fixture()
def _ws_heartbeat_recorder(monkeypatch):
    calls: list[dict[str, Any]] = []
    original_manager = registry_http._ws_manager

    async def fake_broadcast(agent_id: str, status_data: dict) -> None:
        calls.append(
            {
                "agent_id": agent_id,
                "status_data": status_data,
            }
        )

    monkeypatch.setattr(original_manager, "broadcast_heartbeat", fake_broadcast)
    return calls


def test_publish_events_broadcasts_via_websocket(
    monkeypatch, tmp_path: Path, _ws_recorder,
) -> None:
    _configure(monkeypatch, tmp_path)
    with TestClient(app) as client:
        agent_id, token = _enroll_and_register(client, "ws-pub-bot")
        conv_id = _create_conversation(client, token, agent_id)

        resp = client.post(
            f"/v1/conversations/{conv_id}/events",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "events": [
                    {
                        "event_id": "evt-ws-1",
                        "kind": "message.bot",
                        "actor": "ws-pub-bot",
                        "content": "Hello from bot",
                        "created_at": "2026-03-22T00:00:00+00:00",
                        "metadata": {},
                    }
                ]
            },
        )

        assert resp.status_code == 200
        assert len(_ws_recorder) == 1
        ev = _ws_recorder[0]["event_data"]
        assert _ws_recorder[0]["conversation_id"] == conv_id
        assert _ws_recorder[0]["agent_id"] == agent_id
        assert ev["kind"] == "message.bot"
        assert ev["event_id"] == "evt-ws-1"
        assert ev["conversation_id"] == conv_id
        assert ev["agent_id"] == agent_id
        assert ev["actor"] == "ws-pub-bot"
        assert ev["content"] == "Hello from bot"
        assert "seq" in ev
        assert "created_at" in ev
        assert "metadata" in ev


def test_publish_events_invalidates_usage_and_approvals(
    monkeypatch, tmp_path: Path, _ws_invalidation_recorder,
) -> None:
    _configure(monkeypatch, tmp_path)
    with TestClient(app) as client:
        agent_id, token = _enroll_and_register(client, "ws-invalidate-bot")
        conv_id = _create_conversation(client, token, agent_id)

        resp = client.post(
            f"/v1/conversations/{conv_id}/events",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "events": [
                    {
                        "event_id": "evt-provider-1",
                        "kind": "provider.response",
                        "actor": "ws-invalidate-bot",
                        "content": "",
                        "created_at": "2026-03-22T00:00:00+00:00",
                        "metadata": {
                            "prompt_tokens": 20,
                            "completion_tokens": 5,
                            "cost_usd": 0.02,
                            "provider": "codex",
                        },
                    },
                    {
                        "event_id": "evt-approval-1",
                        "kind": "approval.requested",
                        "actor": "ws-invalidate-bot",
                        "content": "Need approval",
                        "created_at": "2026-03-22T00:00:01+00:00",
                        "metadata": {
                            "request_kind": "preflight",
                            "actor_key": "telegram:1",
                            "trust_tier": "trusted",
                            "expires_at": "2026-03-22T00:05:00+00:00",
                        },
                    },
                ]
            },
        )

        assert resp.status_code == 200
        topics = {item["topic"] for item in _ws_invalidation_recorder}
        assert {"conversations", "summary", "usage", "approvals"} <= topics


def test_add_message_broadcasts_message_user_event(
    monkeypatch, tmp_path: Path, _ws_recorder,
) -> None:
    _configure(monkeypatch, tmp_path)
    with TestClient(app) as client:
        _login_ui(client)
        csrf = _ui_csrf_token(client)
        agent_id, token = _enroll_and_register(client, "ws-msg-bot")
        conv_id = _create_conversation(client, token, agent_id)

        resp = client.post(
            f"/v1/conversations/{conv_id}/messages",
            headers={"X-CSRF-Token": csrf},
            json={"text": "operator message"},
        )

        assert resp.status_code == 200
        assert len(_ws_recorder) == 1
        assert _ws_recorder[0]["event_data"]["kind"] == "message.user"
        assert _ws_recorder[0]["event_data"]["content"] == "operator message"
        assert _ws_recorder[0]["conversation_id"] == conv_id
        # Full stored event includes seq, event_id, created_at
        assert "event_id" in _ws_recorder[0]["event_data"]
        assert "seq" in _ws_recorder[0]["event_data"]
        assert "created_at" in _ws_recorder[0]["event_data"]


def test_add_action_broadcasts_approval_decided_event(
    monkeypatch, tmp_path: Path, _ws_recorder,
) -> None:
    _configure(monkeypatch, tmp_path)
    with TestClient(app) as client:
        _login_ui(client)
        csrf = _ui_csrf_token(client)
        agent_id, token = _enroll_and_register(client, "ws-action-bot")
        conv_id = _create_conversation(client, token, agent_id)

        resp = client.post(
            f"/v1/conversations/{conv_id}/actions",
            headers={"X-CSRF-Token": csrf},
            json={"action_id": "approval-action-1", "action": "approve", "payload": {"request_id": "approval-1"}},
        )

        assert resp.status_code == 200
        assert len(_ws_recorder) == 1
        assert _ws_recorder[0]["event_data"]["kind"] == "approval.decided"
        assert _ws_recorder[0]["event_data"]["metadata"] == {
            "action": "approve",
            "decided_by": "operator",
            "decision": "approved",
        }
        assert _ws_recorder[0]["conversation_id"] == conv_id
        # Full stored event includes seq, event_id, created_at
        assert "event_id" in _ws_recorder[0]["event_data"]
        assert "seq" in _ws_recorder[0]["event_data"]
        assert "created_at" in _ws_recorder[0]["event_data"]


def test_routed_task_status_broadcasts_task_status_event(
    monkeypatch, tmp_path: Path, _ws_recorder,
) -> None:
    _configure(monkeypatch, tmp_path)
    with TestClient(app) as client:
        origin_id, origin_token = _enroll_and_register(client, "ws-origin-bot")
        target_id, target_token = _enroll_and_register(client, "ws-target-bot")

        # Create a routed task via the store directly
        from app.channels.registry.http import get_store
        store = get_store()
        conversation = store.create_conversation(
            target_agent_id=origin_id,
            title="WS parent conversation",
            origin_channel="registry",
            external_conversation_ref="ws-parent-conv-1",
        )
        store.create_routed_task({
            "routed_task_id": "ws-task-1",
            "parent_conversation_id": conversation["conversation_id"],
            "origin_agent_id": origin_id,
            "target_agent_id": target_id,
            "title": "WebSocket task",
            "instructions": "Test WS broadcast",
            "created_at": "2026-03-22T00:00:00+00:00",
        })
        _advance_task_lifecycle(
            store,
            agent_token=target_token,
            routed_task_id="ws-task-1",
            conversation_id=conversation["conversation_id"],
        )

        resp = client.post(
            "/v1/agents/routed-tasks/ws-task-1/status",
            headers={"Authorization": f"Bearer {target_token}"},
            json={
                "status": "running",
                "transition_id": "ws-task-1-start-http",
                "summary": "halfway",
                "timeline_events": [
                    {
                        "event_id": "evt-ws-task-1",
                        "conversation_id": conversation["conversation_id"],
                        "kind": "task.status",
                        "title": "Running",
                        "body": "halfway there",
                        "status": "running",
                        "progress": 50,
                        "metadata": {},
                        "created_at": "2026-03-22T00:00:00+00:00",
                    }
                ],
            },
        )

        assert resp.status_code == 200
        assert len(_ws_recorder) == 2
        timeline_event = next(item["event_data"] for item in _ws_recorder if item["event_data"]["event_id"] == "evt-ws-task-1")
        assert timeline_event["kind"] == "task.status"
        assert timeline_event["metadata"] == {
            "status": "running",
            "progress": 50,
            "routed_task_id": "ws-task-1",
            "transition_id": "ws-task-1-start-http",
        }
        assert "created_at" in timeline_event


def test_routed_task_create_and_result_invalidate_tasks_and_conversations(
    monkeypatch, tmp_path: Path, _ws_recorder, _ws_invalidation_recorder,
) -> None:
    _configure(monkeypatch, tmp_path)
    with TestClient(app) as client:
        origin_id, origin_token = _enroll_and_register(client, "ws-origin-2")
        target_id, target_token = _enroll_and_register(client, "ws-target-2")
        conv_id = _create_conversation(client, origin_token, origin_id)

        create_resp = client.post(
            "/v1/agents/routed-tasks",
            headers={"Authorization": f"Bearer {origin_token}"},
            json={
                "routed_task_id": "ws-task-2",
                "parent_conversation_id": conv_id,
                "origin_agent_id": origin_id,
                "target_agent_id": target_id,
                "title": "Delegate review",
                "instructions": "Please review it",
                "requested_capabilities": ["python"],
                "created_at": "2026-03-22T00:00:00+00:00",
            },
        )

        assert create_resp.status_code == 200
        assert len(_ws_recorder) == 1
        assert _ws_recorder[0]["event_data"]["kind"] == "task.status"
        assert _ws_recorder[0]["event_data"]["metadata"] == {"status": "queued", "routed_task_id": "ws-task-2"}
        assert _ws_recorder[0]["event_data"]["seq"] > 0

        from app.channels.registry.http import get_store
        store = get_store()
        _advance_task_lifecycle(
            store,
            agent_token=target_token,
            routed_task_id="ws-task-2",
            conversation_id=conv_id,
            to_running=True,
        )

        result_resp = client.post(
            "/v1/agents/routed-tasks/ws-task-2/result",
            headers={"Authorization": f"Bearer {target_token}"},
            json={
                "status": "completed",
                "transition_id": "ws-task-2-complete",
                "summary": "Done",
                "full_text": "All done",
                "completed_at": "2026-03-22T00:01:00+00:00",
            },
        )

        assert result_resp.status_code == 200
        assert len(_ws_recorder) == 2
        assert _ws_recorder[1]["event_data"]["kind"] == "task.status"
        assert _ws_recorder[1]["event_data"]["metadata"] == {
            "status": "completed",
            "routed_task_id": "ws-task-2",
            "transition_id": "ws-task-2-complete",
        }
        assert _ws_recorder[1]["event_data"]["seq"] > 0
        topics = {item["topic"] for item in _ws_invalidation_recorder}
        assert {"tasks", "conversations", "summary"} <= topics


def test_publish_progress_broadcasts_ephemeral_progress(
    monkeypatch, tmp_path: Path, _ws_progress_recorder,
) -> None:
    _configure(monkeypatch, tmp_path)
    with TestClient(app) as client:
        agent_id, token = _enroll_and_register(client, "ws-progress-bot")
        conv_id = _create_conversation(client, token, agent_id)

        resp = client.post(
            f"/v1/conversations/{conv_id}/progress",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "content": "Thinking about the delegation plan",
                "created_at": "2026-03-22T00:00:00+00:00",
            },
        )

        assert resp.status_code == 200
        assert _ws_progress_recorder == [
            {
                "conversation_id": conv_id,
                "agent_id": agent_id,
                "progress_data": {
                    "conversation_id": conv_id,
                    "agent_id": agent_id,
                    "content": "Thinking about the delegation plan",
                    "created_at": "2026-03-22T00:00:00+00:00",
                },
            }
        ]


def test_agent_heartbeat_broadcasts_targeted_update_without_collection_invalidation(
    monkeypatch,
    tmp_path: Path,
    _ws_heartbeat_recorder,
    _ws_invalidation_recorder,
) -> None:
    _configure(monkeypatch, tmp_path)
    with TestClient(app) as client:
        agent_id, token = _enroll_and_register(client, "ws-heartbeat-bot")
        _ws_heartbeat_recorder.clear()
        _ws_invalidation_recorder.clear()

        resp = client.post(
            "/v1/agents/heartbeat",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "connectivity_state": "connected",
                "current_capacity": 1,
                "max_capacity": 2,
            },
        )

        assert resp.status_code == 200
        assert _ws_heartbeat_recorder == [
            {
                "agent_id": agent_id,
                "status_data": resp.json()["agent"],
            }
        ]
        assert _ws_invalidation_recorder == []


def test_routed_task_running_status_without_timeline_events_does_not_broadcast_parent_event(
    monkeypatch,
    tmp_path: Path,
    _ws_recorder,
    _ws_invalidation_recorder,
) -> None:
    _configure(monkeypatch, tmp_path)
    with TestClient(app) as client:
        origin_id, origin_token = _enroll_and_register(client, "ws-origin-running")
        target_id, target_token = _enroll_and_register(client, "ws-target-running")
        conv_id = _create_conversation(client, origin_token, origin_id)

        create_resp = client.post(
            "/v1/agents/routed-tasks",
            headers={"Authorization": f"Bearer {origin_token}"},
            json={
                "routed_task_id": "ws-task-running",
                "parent_conversation_id": conv_id,
                "origin_agent_id": origin_id,
                "target_agent_id": target_id,
                "title": "Compute something",
                "instructions": "Think for a bit",
                "requested_capabilities": ["python"],
                "created_at": "2026-03-24T00:00:00+00:00",
            },
        )

        assert create_resp.status_code == 200
        _ws_recorder.clear()
        _ws_invalidation_recorder.clear()

        from app.channels.registry.http import get_store
        store = get_store()
        _advance_task_lifecycle(
            store,
            agent_token=target_token,
            routed_task_id="ws-task-running",
            conversation_id=conv_id,
        )

        status_resp = client.post(
            "/v1/agents/routed-tasks/ws-task-running/status",
            headers={"Authorization": f"Bearer {target_token}"},
            json={
                "status": "running",
                "transition_id": "ws-task-running-start-http",
                "summary": "Working…",
                "updated_at": "2026-03-24T00:00:10+00:00",
            },
        )

        assert status_resp.status_code == 200
        assert status_resp.json()["events_written"] is True
        assert len(_ws_recorder) == 1
        assert _ws_recorder[0]["event_data"]["metadata"] == {
            "status": "running",
            "routed_task_id": "ws-task-running",
            "transition_id": "ws-task-running-start-http",
        }
        topics = {item["topic"] for item in _ws_invalidation_recorder}
        assert {"tasks", "conversations", "summary"} <= topics
