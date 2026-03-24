from pathlib import Path
from types import SimpleNamespace

import pytest

import app.channels.telegram.delegation_channel as delegation_channel
from octopus_sdk.agent_directory import AuthorityResolution
from app.channels.telegram.state import build_telegram_runtime
from octopus_sdk.sessions import SessionState
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
    async def _resolve_target_authority(*, target_agent_id):
        assert target_agent_id == "agent-reviewer"
        return AuthorityResolution(status="resolved", authority_ref="registry:default")

    monkeypatch.setattr(
        runtime.services.control_plane.agent_directory,
        "resolve_target_authority",
        _resolve_target_authority,
    )

    outcome = await delegation_channel.propose_delegation_plan(
        runtime,
        "tg:12345",
        message,
        session,
        conversation_ref="conv-1",
        result=result,
    )

    assert outcome.status == "delegation_proposed"
    assert session.pending_delegation is not None
    assert session.pending_delegation.title == "Delegate this"
    assert len(session.pending_delegation.tasks) == 1
    # delegation.proposed event is now published by execute_request via the event sink, not here
    assert message.replies[-1]["reply_markup"] is not None
    assert "Delegation plan" in message.replies[-1]["text"]
    assert "ready via" in message.replies[-1]["text"]


@pytest.mark.asyncio
async def test_propose_delegation_plan_marks_unavailable_targets_in_rendered_plan(monkeypatch, tmp_path: Path):
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

    async def _resolve_target_authority(*, target_agent_id):
        assert target_agent_id == "agent-reviewer"
        return AuthorityResolution(status="unavailable", error="registry_unreachable")

    monkeypatch.setattr(
        runtime.services.control_plane.agent_directory,
        "resolve_target_authority",
        _resolve_target_authority,
    )

    await delegation_channel.propose_delegation_plan(
        runtime,
        "tg:12345",
        message,
        session,
        conversation_ref="conv-1",
        result=result,
    )

    assert "registry unavailable" in message.replies[-1]["text"].lower()
    assert "could not be reached" in message.replies[-1]["text"].lower()
