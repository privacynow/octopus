from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path

from octopus_sdk.deferred_notifications import DeferredNotification
from octopus_sdk.execution import dispatch_message_request, execute_request
from octopus_sdk.identity import resolve_delegation_parent_identity
from octopus_sdk.inbound_types import InboundEnvelope, InboundMessage, InboundUser, serialize_inbound
from octopus_sdk.registry.models import RoutedTaskRequest, RoutedTaskResult
from octopus_sdk.tests.support import make_sdk_harness, make_transport_identity
from octopus_sdk.work_queue import WorkItemRecord
from octopus_sdk.workflows.delegation import (
    apply_routed_result,
    build_delegation_plan,
    prepare_delegation_approval,
)


def test_sdk_wiring_verification_package_has_no_app_or_registry_imports() -> None:
    package_root = Path(__file__).resolve().parent
    for path in sorted(package_root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(
                    not alias.name.startswith("app") and not alias.name.startswith("octopus_registry")
                    for alias in node.names
                ), f"SDK wiring test imports forbidden package in {path}"
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert not module.startswith("app"), f"SDK wiring test imports app in {path}"
                assert not module.startswith("octopus_registry"), f"SDK wiring test imports octopus_registry in {path}"


async def test_sdk_wiring_verification_exercises_full_workflow_lifecycle(tmp_path: Path) -> None:
    harness = make_sdk_harness(tmp_path, process_role="bot")
    workflows = harness.composer.build_for_testing()
    runtime = harness.build_runtime(workflows)

    admitted = await runtime.submit(
        InboundEnvelope(
            transport="stub",
            event_id="evt-submit-1",
            conversation_key="stub:conversation:1",
            actor_key="stub:user:1",
            received_at=datetime.now(timezone.utc),
            event=InboundMessage(
                user=InboundUser(id="stub:user:1", username="sdk"),
                conversation_key="stub:conversation:1",
                text="hello",
                source="stub",
            ),
        )
    )
    assert admitted.status == "admitted"

    egress = runtime.transport.build_egress(
        conversation_ref="stub:conversation:1",
        config=runtime.config,
    )
    transport_identity = make_transport_identity(
        conversation_key="stub:conversation:1",
        actor="stub:user:1",
        conversation_ref="stub:conversation:1",
    )
    execution_outcome = await execute_request(
        transport_identity,
        "Say hello from the SDK wiring test.",
        [],
        egress,
        runtime=runtime._execution_runtime(),
    )
    assert execution_outcome.status == "completed"
    assert execution_outcome.reply_text == "sdk response"
    assert harness.transport.egresses["stub:conversation:1"].sent_texts == ["sdk response"]

    approval_egress = runtime.transport.build_egress(
        conversation_ref="stub:conversation:2",
        config=runtime.config,
    )
    approval_identity = make_transport_identity(
        conversation_key="stub:conversation:2",
        actor="stub:user:2",
        conversation_ref="stub:conversation:2",
    )
    await dispatch_message_request(
        approval_identity,
        "Need approval",
        [],
        [],
        approval_egress,
        approval_mode="on",
        runtime=runtime._execution_runtime(),
    )
    approval_session = runtime.sessions.load(
        "stub:conversation:2",
        provider_name=runtime.provider.name,
        provider_state_factory=runtime.provider.new_provider_state,
        approval_mode=runtime.config.approval_mode,
        default_role=runtime.config.role,
        default_skills=runtime.config.default_skills,
    )
    assert approval_session.pending_approval is not None
    approval_outcome = runtime.workflows.pending.requests.approve(
        approval_session,
        cfg=runtime.config,
        provider_name=runtime.provider.name,
    )
    assert approval_outcome.status == "approved"
    assert approval_outcome.execution_plan is not None

    skill_session = runtime.sessions.load(
        "stub:conversation:3",
        provider_name=runtime.provider.name,
        provider_state_factory=runtime.provider.new_provider_state,
        approval_mode=runtime.config.approval_mode,
        default_role=runtime.config.role,
        default_skills=runtime.config.default_skills,
    )
    activation_outcome = runtime.workflows.runtime_skills.activation.begin_activate(
        skill_session,
        actor_key="stub:user:3",
        skill_name="docs",
    )
    assert activation_outcome.status == "activated"
    assert "docs" in skill_session.active_skills

    pending_delegation = build_delegation_plan(
        "conv-1",
        "Ask a specialist",
        "Resume when the specialist returns.",
        [
            {
                "draft_id": "draft-1",
                "selector_kind": "agent",
                "selector_value": "m2",
                "title": "Specialist task",
                "instructions": "Answer carefully",
            }
        ],
        origin_conversation_key="stub:conversation:delegation",
        proposal_id="proposal-1",
    )
    delegation_approval = prepare_delegation_approval(
        pending_delegation,
        conversation_ref="conv-1",
    )
    assert delegation_approval.status == "approve_ready"
    assert len(delegation_approval.tasks_to_submit) == 1
    assert pending_delegation.origin_conversation_key == "stub:conversation:delegation"
    parent_ref, parent_key = resolve_delegation_parent_identity(
        parent_transport_ref="stub:conversation:delegation",
        parent_conversation_id="registry:local:conversation:conv-1",
    )
    assert parent_ref == "stub:conversation:delegation"
    assert parent_key == "stub:conversation:delegation"
    resumed = apply_routed_result(
        pending_delegation,
        routed_task_id="draft-1",
        result=RoutedTaskResult(
            routed_task_id="draft-1",
            status="completed",
            transition_id="draft-1-complete",
            summary="specialist finished",
            full_text="specialist output",
        ),
    )
    assert resumed.matched is True
    assert resumed.ready_to_resume is True
    routed_request = RoutedTaskRequest(
        routed_task_id="draft-1",
        parent_conversation_id="conv-1",
        origin_transport_ref=parent_ref,
        origin_agent_id="origin-agent",
        target_agent_id="target-agent",
        title="Specialist task",
        instructions="Answer carefully",
    )
    assert routed_request.origin_transport_ref == "stub:conversation:delegation"

    recovery_event = InboundMessage(
        user=InboundUser(id="stub:user:4", username="recovery"),
        conversation_key="stub:conversation:4",
        text="recover me",
        source="stub",
    )
    payload = serialize_inbound(recovery_event, transport="stub")
    queued, item_id = runtime.work_queue.record_and_enqueue(
        runtime.config.data_dir,
        "evt-recovery-1",
        "stub:conversation:4",
        "stub:user:4",
        "message",
        payload=payload,
    )
    assert queued is True
    assert item_id is not None
    runtime.work_queue.mark_pending_recovery(runtime.config.data_dir, item_id)
    recovery_outcome = runtime.workflows.recovery.replay.prepare_action(
        data_dir=runtime.config.data_dir,
        conversation_key="stub:conversation:4",
        event_id="evt-recovery-1",
        action="recovery_replay",
        worker_id="worker-1",
        config=runtime.config,
    )
    assert recovery_outcome.status == "replay_ready"
    assert recovery_outcome.replay_plan is not None

    await runtime.run()
    assert harness.transport.started is True
    assert harness.transport.stopped is True


async def test_sdk_wiring_verification_enqueues_deferred_notification_for_routed_task_completion(
    tmp_path: Path,
) -> None:
    harness = make_sdk_harness(tmp_path, process_role="bot")
    workflows = harness.composer.build_for_testing()
    runtime = harness.build_runtime(
        workflows,
        local_agent_ids={"registry:local": "agent-target"},
    )
    event = InboundMessage(
        user=InboundUser(id="reg:agent:origin", username="registry"),
        conversation_key="delegation:origin:conv-1",
        text="Specialist task",
        source="registry",
        transport="registry",
        conversation_ref="registry:local:task:task-1",
        routed_task_id="task-1",
        authority_ref="registry:local",
        authorized_actor_key="telegram:42",
    )
    item = WorkItemRecord(
        id="item-routed-1",
        conversation_key="delegation:origin:conv-1",
        event_id="evt-routed-1",
        actor_key="reg:agent:origin",
        kind="message",
        state="claimed",
        created_at="2026-03-28T00:00:00+00:00",
    )

    await runtime.dispatch_claimed_item("message", event, item)

    notifications = harness.deferred_notifications.flush(
        runtime.config.data_dir,
        target_agent_id="agent-target",
        actor_key="telegram:42",
    )
    assert len(notifications) == 1
    assert notifications[0].content == "Task 'Specialist task' completed. Summary: sdk response"


async def test_sdk_wiring_verification_flushes_deferred_notifications_on_next_operator_message(
    tmp_path: Path,
) -> None:
    harness = make_sdk_harness(tmp_path, process_role="bot")
    workflows = harness.composer.build_for_testing()
    runtime = harness.build_runtime(
        workflows,
        local_agent_ids={"registry:local": "agent-target"},
    )
    harness.deferred_notifications.enqueue(
        runtime.config.data_dir,
        DeferredNotification(
            target_agent_id="agent-target",
            actor_key="stub:user:1",
            content="Task 'Specialist task' completed. Summary: sdk response",
            created_at="2026-03-28T00:00:00+00:00",
            expires_at="2026-03-29T00:00:00+00:00",
        ),
    )
    event = InboundMessage(
        user=InboundUser(id="stub:user:1", username="sdk"),
        conversation_key="stub:conversation:1",
        text="hello",
        source="stub",
        transport="stub",
        conversation_ref="stub:conversation:1",
    )
    item = WorkItemRecord(
        id="item-user-1",
        conversation_key="stub:conversation:1",
        event_id="evt-user-1",
        actor_key="stub:user:1",
        kind="message",
        state="claimed",
        created_at="2026-03-28T00:01:00+00:00",
    )

    await runtime.dispatch_claimed_item("message", event, item)

    sent = harness.transport.egresses["stub:conversation:1"].sent_texts
    assert sent == [
        "Task 'Specialist task' completed. Summary: sdk response",
        "sdk response",
    ]
    assert harness.deferred_notifications.flush(
        runtime.config.data_dir,
        target_agent_id="agent-target",
        actor_key="stub:user:1",
    ) == []
