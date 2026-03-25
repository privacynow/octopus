from pathlib import Path
from types import SimpleNamespace

import pytest

import app.channels.telegram.delegation_channel as delegation_channel
from octopus_sdk.registry.models import CoordinationActionResult, DelegationIntent, DelegationTaskDraft, TargetSelector
from octopus_sdk.agent_directory import AuthorityResolution
from app.channels.telegram.state import build_telegram_runtime
from octopus_sdk.sessions import SessionState
from tests.support.handler_support import FakeChat, FakeMessage, FakeProvider, make_config
from tests.support.config_support import make_registry_connection


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
        make_config(
            tmp_path,
            agent_mode="registry",
            agent_registries=(make_registry_connection(),),
            registry_agent_ids={"default": "agent-primary"},
        ),
        FakeProvider("codex"),
    )
    message = FakeMessage(chat=FakeChat(12345), text="delegate")
    session = SessionState(provider="codex", provider_state={}, approval_mode="off")
    result = SimpleNamespace(
        text="delegate this work",
        coordination_intent=DelegationIntent(
            title="Delegate this",
            resume_instruction="resume",
            tasks=[
                DelegationTaskDraft(
                    draft_id="task-1",
                    selector=TargetSelector(kind="agent", value="agent-reviewer", preferred_agent_id="agent-reviewer"),
                    title="Review docs",
                    instructions="Review the current docs",
                )
            ],
        ),
    )
    created = []
    submitted = []

    async def _create_conversation(**kwargs):
        created.append(kwargs)
        return "conversation-id"

    async def _submit_action(*, conversation_id, envelope):
        submitted.append((conversation_id, envelope))
        return CoordinationActionResult(
            conversation_id=conversation_id,
            action_id=envelope.action_id,
            action=envelope.action,
            accepted=True,
            proposal_id="proposal-1",
        )

    monkeypatch.setattr(
        runtime.services.control_plane.conversation_projection,
        "create_conversation",
        _create_conversation,
    )
    monkeypatch.setattr(
        runtime.services.control_plane.conversation_projection,
        "submit_action",
        _submit_action,
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
    assert session.pending_delegation.proposal_id == "proposal-1"
    assert session.pending_delegation.conversation_ref == "conversation-id"
    assert session.pending_delegation.title == "Delegate this"
    assert len(session.pending_delegation.tasks) == 1
    assert created[0]["external_conversation_ref"] == "12345"
    assert submitted[0][0] == "conversation-id"
    assert submitted[0][1].action == "delegate_tasks"
    assert message.replies[-1]["reply_markup"] is not None
    assert "Delegation plan" in message.replies[-1]["text"]
    assert "ready via" in message.replies[-1]["text"]


@pytest.mark.asyncio
async def test_propose_delegation_plan_marks_unavailable_targets_in_rendered_plan(monkeypatch, tmp_path: Path):
    runtime = build_telegram_runtime(
        make_config(
            tmp_path,
            agent_mode="registry",
            agent_registries=(make_registry_connection(),),
            registry_agent_ids={"default": "agent-primary"},
        ),
        FakeProvider("codex"),
    )
    message = FakeMessage(chat=FakeChat(12345), text="delegate")
    session = SessionState(provider="codex", provider_state={}, approval_mode="off")
    result = SimpleNamespace(
        text="delegate this work",
        coordination_intent=DelegationIntent(
            title="Delegate this",
            resume_instruction="resume",
            tasks=[
                DelegationTaskDraft(
                    draft_id="task-1",
                    selector=TargetSelector(kind="agent", value="agent-reviewer", preferred_agent_id="agent-reviewer"),
                    title="Review docs",
                    instructions="Review the current docs",
                )
            ],
        ),
    )
    async def _create_conversation(**kwargs):
        del kwargs
        return "conversation-id"

    async def _submit_action(*, conversation_id, envelope):
        del envelope
        return CoordinationActionResult(
            conversation_id=conversation_id,
            action_id="proposal-action",
            action="delegate_tasks",
            accepted=True,
            proposal_id="proposal-1",
        )

    monkeypatch.setattr(
        runtime.services.control_plane.conversation_projection,
        "create_conversation",
        _create_conversation,
    )
    monkeypatch.setattr(
        runtime.services.control_plane.conversation_projection,
        "submit_action",
        _submit_action,
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


@pytest.mark.asyncio
async def test_propose_delegation_plan_autonomous_registry_origin_uses_bound_external_ref(
    monkeypatch,
    tmp_path: Path,
):
    runtime = build_telegram_runtime(
        make_config(
            tmp_path,
            autonomous=True,
            approval_mode="off",
            agent_mode="registry",
            agent_registries=(make_registry_connection(),),
            registry_agent_ids={"default": "agent-primary"},
        ),
        FakeProvider("codex"),
    )
    message = FakeMessage(chat=FakeChat(12345), text="delegate")
    message.external_id = "registry-ui-conv-1"
    message.authority_ref = "registry:default"
    session = SessionState(provider="codex", provider_state={}, approval_mode="off")
    result = SimpleNamespace(
        text="delegate this work",
        coordination_intent=DelegationIntent(
            title="Delegate this",
            resume_instruction="resume",
            tasks=[
                DelegationTaskDraft(
                    draft_id="task-1",
                    selector=TargetSelector(kind="agent", value="agent-reviewer", preferred_agent_id="agent-reviewer"),
                    title="Review docs",
                    instructions="Review the current docs",
                )
            ],
        ),
    )
    submitted = []

    async def _submit_action(*, conversation_id, envelope):
        submitted.append((conversation_id, envelope))
        if envelope.action == "delegate_tasks":
            return CoordinationActionResult(
                conversation_id=conversation_id,
                action_id=envelope.action_id,
                action=envelope.action,
                accepted=True,
                proposal_id="proposal-1",
            )
        return CoordinationActionResult(
            conversation_id=conversation_id,
            action_id=envelope.action_id,
            action=envelope.action,
            accepted=True,
            proposal_id="proposal-1",
            routed_tasks=[
                {
                    "routed_task_id": "server-task-1",
                    "target_agent_id": "agent-reviewer",
                    "authority_ref": "",
                    "title": "Review docs",
                    "status": "queued",
                }
            ],
        )

    monkeypatch.setattr(
        runtime.services.control_plane.conversation_projection,
        "submit_action",
        _submit_action,
    )

    outcome = await delegation_channel.propose_delegation_plan(
        runtime,
        "registry:conversation:conv-1",
        message,
        session,
        conversation_ref="registry:default:conversation:conv-1",
        result=result,
    )

    assert outcome.status == "delegation_submitted"
    assert [envelope.action for _, envelope in submitted] == ["delegate_tasks", "approve_delegation"]
    assert submitted[0][0] == submitted[1][0]
    assert session.pending_delegation is not None
    assert session.pending_delegation.status == "submitted"
    assert session.pending_delegation.tasks[0].status == "submitted"
