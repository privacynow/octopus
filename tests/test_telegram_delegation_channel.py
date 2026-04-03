from pathlib import Path
from types import SimpleNamespace

import pytest

import app.workflows.delegation.telegram as delegation_channel
from app.agents.state import RegistryConnectionState, save_registry_connection_state
from octopus_sdk.registry.models import CoordinationActionResult, DelegationIntent, DelegationTaskDraft, RoutedTaskRef, TargetSelector
from octopus_sdk.agent_directory import AuthorityResolution
from octopus_sdk.identity import telegram_conversation_ref
from app.channels.telegram.state import build_telegram_runtime
from octopus_sdk.providers import ProviderStateRecord
from octopus_sdk.sessions import SessionState
from app.runtime.session_runtime import load_runtime_session
from tests.support.handler_support import FakeChat, FakeMessage, FakeProvider, make_config
from tests.support.config_support import make_registry_connection
from tests.support.service_support import build_test_bot_services


def _save_live_registry_state(tmp_path: Path, *, registry_id: str = "default", agent_id: str = "agent-primary") -> None:
    save_registry_connection_state(
        tmp_path,
        RegistryConnectionState(
            registry_id=registry_id,
            registry_scope="full",
            agent_id=agent_id,
            connectivity_state="connected",
        ),
    )


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
    cfg = make_config(
        tmp_path,
        agent_mode="registry",
        agent_registries=(make_registry_connection(),),
        registry_agent_ids={"default": "agent-primary"},
    )
    runtime = build_telegram_runtime(
        cfg,
        FakeProvider("codex"),
        services=build_test_bot_services(config=cfg),
    )
    _save_live_registry_state(tmp_path)
    message = FakeMessage(chat=FakeChat(12345), text="delegate")
    session = SessionState(provider="codex", provider_state=ProviderStateRecord(), approval_mode="off")
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
        conversation_ref=telegram_conversation_ref(cfg, message.chat.id),
        result=result,
    )

    assert outcome.status == "delegation_proposed"
    assert session.pending_delegation is not None
    assert session.pending_delegation.proposal_id == "proposal-1"
    assert session.pending_delegation.conversation_ref == "conversation-id"
    assert session.pending_delegation.title == "Delegate this"
    assert len(session.pending_delegation.tasks) == 1
    assert created[0]["external_conversation_ref"] == telegram_conversation_ref(cfg, message.chat.id)
    assert submitted[0][0] == "conversation-id"
    assert submitted[0][1].action == "delegate_tasks"
    assert submitted[0][1].payload["origin_transport_ref"] == telegram_conversation_ref(cfg, message.chat.id)
    assert message.replies[-1]["reply_markup"] is not None
    assert "Delegation plan" in message.replies[-1]["text"]
    assert "ready via" in message.replies[-1]["text"]


@pytest.mark.asyncio
async def test_propose_delegation_plan_marks_unavailable_targets_in_rendered_plan(monkeypatch, tmp_path: Path):
    cfg = make_config(
        tmp_path,
        agent_mode="registry",
        agent_registries=(make_registry_connection(),),
        registry_agent_ids={"default": "agent-primary"},
    )
    runtime = build_telegram_runtime(
        cfg,
        FakeProvider("codex"),
        services=build_test_bot_services(config=cfg),
    )
    _save_live_registry_state(tmp_path)
    message = FakeMessage(chat=FakeChat(12345), text="delegate")
    session = SessionState(provider="codex", provider_state=ProviderStateRecord(), approval_mode="off")
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
        conversation_ref=telegram_conversation_ref(cfg, message.chat.id),
        result=result,
    )

    assert "registry unavailable" in message.replies[-1]["text"].lower()
    assert "could not be reached" in message.replies[-1]["text"].lower()


@pytest.mark.asyncio
async def test_propose_delegation_plan_autonomous_registry_origin_uses_bound_external_ref(
    monkeypatch,
    tmp_path: Path,
):
    cfg = make_config(
        tmp_path,
        autonomous=True,
        approval_mode="off",
        agent_mode="registry",
        agent_registries=(make_registry_connection(),),
        registry_agent_ids={"default": "agent-primary"},
    )
    runtime = build_telegram_runtime(
        cfg,
        FakeProvider("codex"),
        services=build_test_bot_services(config=cfg),
    )
    _save_live_registry_state(tmp_path)
    message = FakeMessage(chat=FakeChat(12345), text="delegate")
    message.external_id = "registry-ui-conv-1"
    message.authority_ref = "registry:default"
    session = SessionState(provider="codex", provider_state=ProviderStateRecord(), approval_mode="off")
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


@pytest.mark.asyncio
async def test_submit_direct_assignment_uses_live_registry_state_not_config_snapshot(
    monkeypatch,
    tmp_path: Path,
):
    cfg = make_config(
        tmp_path,
        agent_mode="registry",
        agent_registries=(make_registry_connection(),),
        registry_agent_ids={},
    )
    runtime = build_telegram_runtime(
        cfg,
        FakeProvider("codex"),
        services=build_test_bot_services(config=cfg),
    )
    _save_live_registry_state(tmp_path, agent_id="live-agent")
    message = FakeMessage(chat=FakeChat(12345), text="/delegate @agent-reviewer do work")
    created: list[dict] = []
    submitted: list[tuple[str, object]] = []
    qualified_ref = telegram_conversation_ref(cfg, message.chat.id)

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
            routed_tasks=[
                RoutedTaskRef(
                    routed_task_id="task-direct-1",
                    target_agent_id="agent-reviewer",
                    title="Direct assignment",
                    status="queued",
                )
            ],
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

    result = await delegation_channel.submit_direct_assignment(
        runtime,
        "tg:12345",
        message,
        conversation_ref=qualified_ref,
        selector=TargetSelector(kind="agent", value="agent-reviewer", preferred_agent_id="agent-reviewer"),
        title="Direct assignment",
        instructions="Do the work",
        message_text="/delegate @agent-reviewer do work",
    )

    assert result.accepted is True
    assert created and created[0]["target_agent_id"] == "live-agent"
    assert created[0]["external_conversation_ref"] == qualified_ref
    assert submitted and submitted[0][0] == "conversation-id"
    assert submitted[0][1].payload["origin_transport_ref"] == qualified_ref
    session = load_runtime_session(
        tmp_path,
        "tg:12345",
        provider_name=runtime.provider.name,
        provider_state_factory=runtime.provider.new_provider_state,
        approval_mode=cfg.approval_mode,
        default_role=cfg.role,
        default_skills=cfg.default_skills,
    )
    assert session.pending_delegation is not None
    assert session.pending_delegation.origin_conversation_key == "tg:12345"
    assert session.pending_delegation.status == "submitted"
    assert session.pending_delegation.tasks[0].routed_task_id == "task-direct-1"
    assert session.pending_delegation.tasks[0].status == "submitted"


@pytest.mark.asyncio
async def test_submit_direct_assignment_derives_requested_skills_from_skill_selector(
    monkeypatch,
    tmp_path: Path,
):
    cfg = make_config(
        tmp_path,
        agent_mode="registry",
        agent_registries=(make_registry_connection(),),
        registry_agent_ids={},
    )
    runtime = build_telegram_runtime(
        cfg,
        FakeProvider("codex"),
        services=build_test_bot_services(config=cfg),
    )
    _save_live_registry_state(tmp_path, agent_id="live-agent")
    message = FakeMessage(chat=FakeChat(12345), text="/delegate @skill:architecture review this")
    submitted: list[tuple[str, object]] = []
    qualified_ref = telegram_conversation_ref(cfg, message.chat.id)

    async def _create_conversation(**kwargs):
        return "conversation-id"

    async def _submit_action(*, conversation_id, envelope):
        submitted.append((conversation_id, envelope))
        return CoordinationActionResult(
            conversation_id=conversation_id,
            action_id=envelope.action_id,
            action=envelope.action,
            accepted=True,
            routed_tasks=[
                RoutedTaskRef(
                    routed_task_id="task-direct-skill-1",
                    target_agent_id="agent-architecture",
                    title="Architecture review",
                    status="queued",
                )
            ],
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

    await delegation_channel.submit_direct_assignment(
        runtime,
        "tg:12345",
        message,
        conversation_ref=qualified_ref,
        selector=TargetSelector(kind="skill", value="architecture"),
        title="Architecture review",
        instructions="Review this design.",
        message_text="/delegate @skill:architecture review this",
    )

    assert submitted
    assert submitted[0][1].payload["requested_skills"] == ["architecture"]
