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
    monkeypatch.setenv("REGISTRY_ALLOW_DESTRUCTIVE_MIGRATION", "1")
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
                        "metadata": {},
                    }
                ]
            },
        )

        assert resp.status_code == 200
        assert len(_ws_recorder) == 1
        assert _ws_recorder[0]["conversation_id"] == conv_id
        assert _ws_recorder[0]["agent_id"] == agent_id
        assert _ws_recorder[0]["event_data"]["kind"] == "message.bot"


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
            json={"action": "approve", "payload": {}},
        )

        assert resp.status_code == 200
        assert len(_ws_recorder) == 1
        assert _ws_recorder[0]["event_data"]["kind"] == "approval.decided"
        assert _ws_recorder[0]["event_data"]["action"] == "approve"
        assert _ws_recorder[0]["conversation_id"] == conv_id


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
        store.create_routed_task({
            "routed_task_id": "ws-task-1",
            "parent_conversation_id": "ws-parent-conv-1",
            "origin_agent_id": origin_id,
            "target_agent_id": target_id,
            "title": "WebSocket task",
            "instructions": "Test WS broadcast",
        })

        resp = client.post(
            "/v1/agents/routed-tasks/ws-task-1/status",
            headers={"Authorization": f"Bearer {target_token}"},
            json={
                "status": "running",
                "summary": "halfway",
                "timeline_events": [],
            },
        )

        assert resp.status_code == 200
        assert len(_ws_recorder) == 1
        assert _ws_recorder[0]["event_data"]["kind"] == "task.status"
        assert _ws_recorder[0]["conversation_id"] == "ws-parent-conv-1"
        assert _ws_recorder[0]["event_data"]["routed_task_id"] == "ws-task-1"
