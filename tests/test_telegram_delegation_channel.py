from pathlib import Path
from types import SimpleNamespace

import pytest

import app.channels.telegram.delegation_channel as delegation_channel
from app.channels.telegram.state import build_telegram_runtime
from app.session_state import SessionState
from tests.support.handler_support import FakeChat, FakeMessage, FakeProvider, make_config


def test_parse_delegation_callback_accepts_known_format():
    assert delegation_channel.parse_delegation_callback("delegation_approve:12345") == (
        "delegation_approve",
        12345,
    )
    assert delegation_channel.parse_delegation_callback("delegation_cancel:9") == (
        "delegation_cancel",
        9,
    )
    assert delegation_channel.parse_delegation_callback("delegation_approve:not-a-number") is None
    assert delegation_channel.parse_delegation_callback("delegation_approve") is None


@pytest.mark.asyncio
async def test_propose_delegation_plan_persists_state_and_sends_plan(monkeypatch, tmp_path: Path):
    runtime = build_telegram_runtime(
        make_config(tmp_path),
        FakeProvider("codex"),
    )
    message = FakeMessage(chat=FakeChat(12345), text="delegate")
    session = SessionState(provider="codex", provider_state={}, approval_mode="off")
    result = SimpleNamespace(
        delegation_title="Delegate this",
        text="delegate this work",
        delegation_resume_instruction="resume",
        delegation_tasks=[
            {
                "routed_task_id": "task-1",
                "title": "Review docs",
                "target_agent_id": "agent-reviewer",
                "instructions": "Review the current docs",
            },
        ],
    )
    published = []

    async def _record_publish(runtime, message, delegation):
        published.append((runtime, message, delegation))

    monkeypatch.setattr(delegation_channel, "publish_delegation_proposed_event", _record_publish)

    outcome = await delegation_channel.propose_delegation_plan(
        runtime,
        12345,
        message,
        session,
        conversation_ref="conv-1",
        result=result,
    )

    assert outcome.status == "delegation_proposed"
    assert session.pending_delegation is not None
    assert session.pending_delegation.title == "Delegate this"
    assert len(session.pending_delegation.tasks) == 1
    assert published and published[0][2] is session.pending_delegation
    assert message.replies[-1]["reply_markup"] is not None
    assert "Delegation plan" in message.replies[-1]["text"]


@pytest.mark.asyncio
async def test_publish_delegation_proposed_event_uses_conversation_projection_port(monkeypatch, tmp_path: Path):
    runtime = build_telegram_runtime(
        make_config(tmp_path),
        FakeProvider("codex"),
    )
    delegation = delegation_channel.build_delegation_plan(
        "telegram:bot-1:12345",
        "Delegate this",
        "resume",
        [
            {
                "routed_task_id": "task-1",
                "title": "Review docs",
                "target_agent_id": "agent-reviewer",
                "instructions": "Review the docs",
            },
        ],
    )
    published: list[dict[str, object]] = []

    async def _record(**kwargs):
        published.append(kwargs)

    async def _fail(*args, **kwargs):
        raise AssertionError("message publish_timeline shortcut should not be used")

    monkeypatch.setattr(
        runtime.services.control_plane.conversation_projection,
        "publish_external_timeline",
        _record,
    )

    await delegation_channel.publish_delegation_proposed_event(
        runtime,
        SimpleNamespace(publish_timeline=_fail),
        delegation,
    )

    assert published
    assert published[0]["conversation_ref"] == "telegram:bot-1:12345"
    assert published[0]["kind"] == "delegation_proposed"
