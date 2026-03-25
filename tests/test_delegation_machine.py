"""Machine tests for delegation progression."""

from octopus_sdk.registry.models import DelegationTaskDraft, RoutedTaskResult, TargetSelector
from app.workflows.delegation.machine import (
    CancelDelegationAction,
    DelegationSnapshot,
    FinalizeResumeAction,
    PrepareApprovalAction,
    ProposeDelegationAction,
    UpdateTaskStatusAction,
    decide_delegation_action,
)


def _draft(routed_task_id: str, *, title: str = "Task") -> DelegationTaskDraft:
    return DelegationTaskDraft(
        draft_id=routed_task_id,
        selector=TargetSelector(kind="agent", value="worker-1", preferred_agent_id="worker-1"),
        title=title,
        instructions="Do the work.",
    )


def test_delegation_machine_proposed_to_submitted() -> None:
    proposed = decide_delegation_action(
        DelegationSnapshot(pending=None),
        ProposeDelegationAction(
            conversation_ref="registry:conv-1",
            title="Feature delegation",
            resume_instruction="Resume after children finish.",
            tasks=(_draft("task-1"),),
        ),
    )
    pending = proposed.pending
    assert pending is not None
    assert pending.status == "proposed"

    prepared = decide_delegation_action(
        DelegationSnapshot(pending=pending),
        PrepareApprovalAction(conversation_ref="registry:conv-1"),
    )
    assert prepared.status == "approve_ready"
    assert len(prepared.effects.tasks_to_submit) == 1

    submitted = decide_delegation_action(
        DelegationSnapshot(pending=pending),
        UpdateTaskStatusAction(routed_task_id="task-1", status="submitted"),
    )
    assert submitted.pending is not None
    assert submitted.pending.status == "submitted"
    assert submitted.pending.tasks[0].status == "submitted"


def test_delegation_machine_tracks_task_progression_to_completion() -> None:
    pending = decide_delegation_action(
        DelegationSnapshot(pending=None),
        ProposeDelegationAction(
            conversation_ref="registry:conv-2",
            title="Feature delegation",
            resume_instruction="Resume after children finish.",
            tasks=(_draft("task-1"),),
        ),
    ).pending
    assert pending is not None

    for status in ("queued", "leased", "running", "completed"):
        decision = decide_delegation_action(
            DelegationSnapshot(pending=pending),
            UpdateTaskStatusAction(routed_task_id="task-1", status=status),
        )
        pending = decision.pending
        assert pending is not None
        assert pending.tasks[0].status == status

    assert pending.status == "completed"


def test_delegation_machine_rejects_child_transition_that_store_would_reject() -> None:
    pending = decide_delegation_action(
        DelegationSnapshot(pending=None),
        ProposeDelegationAction(
            conversation_ref="registry:conv-strict",
            title="Feature delegation",
            resume_instruction="Resume after children finish.",
            tasks=(_draft("task-1"),),
        ),
    ).pending
    assert pending is not None

    queued = decide_delegation_action(
        DelegationSnapshot(pending=pending),
        UpdateTaskStatusAction(routed_task_id="task-1", status="queued"),
    )
    assert queued.pending is not None
    unchanged = decide_delegation_action(
        DelegationSnapshot(pending=queued.pending),
        UpdateTaskStatusAction(routed_task_id="task-1", status="running"),
    )
    assert unchanged.pending is not None
    assert unchanged.pending.tasks[0].status == "queued"
    assert unchanged.pending.status == "submitted"


def test_delegation_machine_cancel_before_send_clears_plan() -> None:
    pending = decide_delegation_action(
        DelegationSnapshot(pending=None),
        ProposeDelegationAction(
            conversation_ref="registry:conv-3",
            title="Feature delegation",
            resume_instruction="Resume after children finish.",
            tasks=(_draft("task-1"),),
        ),
    ).pending
    assert pending is not None

    cancelled = decide_delegation_action(
        DelegationSnapshot(pending=pending),
        CancelDelegationAction(conversation_ref="registry:conv-3"),
    )

    assert cancelled.status == "cancelled"
    assert cancelled.effects.clear_pending is True


def test_delegation_machine_applies_routed_result_payload() -> None:
    pending = decide_delegation_action(
        DelegationSnapshot(pending=None),
        ProposeDelegationAction(
            conversation_ref="registry:conv-4",
            title="Feature delegation",
            resume_instruction="Resume after children finish.",
            tasks=(_draft("task-1"),),
        ),
    ).pending
    assert pending is not None

    decision = decide_delegation_action(
        DelegationSnapshot(pending=pending),
        UpdateTaskStatusAction(
            routed_task_id="task-1",
            status="completed",
            summary="Child finished",
            full_text="Detailed delegated result.",
            follow_up_questions=("Anything else?",),
            completed_at="2026-03-18T12:00:00+00:00",
        ),
    )

    assert decision.matched is True
    assert decision.pending is not None
    assert decision.pending.tasks[0].summary == "Child finished"
    assert decision.pending.tasks[0].full_text == "Detailed delegated result."
    assert decision.pending.tasks[0].follow_up_questions == ["Anything else?"]
    assert decision.pending.tasks[0].completed_at == "2026-03-18T12:00:00+00:00"


def test_delegation_machine_marks_all_tasks_complete_ready_to_resume() -> None:
    pending = decide_delegation_action(
        DelegationSnapshot(pending=None),
        ProposeDelegationAction(
            conversation_ref="registry:conv-5",
            title="Feature delegation",
            resume_instruction="Resume after children finish.",
            tasks=(_draft("task-1"), _draft("task-2")),
        ),
    ).pending
    assert pending is not None

    first = decide_delegation_action(
        DelegationSnapshot(pending=pending),
        UpdateTaskStatusAction(routed_task_id="task-1", status="completed"),
    )
    assert first.ready_to_resume is False
    assert first.pending is not None

    second = decide_delegation_action(
        DelegationSnapshot(pending=first.pending),
        UpdateTaskStatusAction(routed_task_id="task-2", status="completed"),
    )
    assert second.pending is not None
    assert second.pending.status == "completed"
    assert second.ready_to_resume is True


def test_delegation_machine_marks_partial_failure_ready_to_resume() -> None:
    pending = decide_delegation_action(
        DelegationSnapshot(pending=None),
        ProposeDelegationAction(
            conversation_ref="registry:conv-6",
            title="Feature delegation",
            resume_instruction="Resume after children finish.",
            tasks=(_draft("task-1"), _draft("task-2")),
        ),
    ).pending
    assert pending is not None

    first = decide_delegation_action(
        DelegationSnapshot(pending=pending),
        UpdateTaskStatusAction(routed_task_id="task-1", status="completed"),
    )
    assert first.pending is not None

    second = decide_delegation_action(
        DelegationSnapshot(pending=first.pending),
        UpdateTaskStatusAction(routed_task_id="task-2", status="failed", summary="Task failed"),
    )
    assert second.pending is not None
    assert second.pending.status == "partial_failed"
    assert second.ready_to_resume is True


def test_delegation_machine_clears_completed_plan_after_resume() -> None:
    pending = decide_delegation_action(
        DelegationSnapshot(pending=None),
        ProposeDelegationAction(
            conversation_ref="registry:conv-7",
            title="Feature delegation",
            resume_instruction="Resume after children finish.",
            tasks=(_draft("task-1"),),
        ),
    ).pending
    assert pending is not None

    completed = decide_delegation_action(
        DelegationSnapshot(pending=pending),
        UpdateTaskStatusAction(routed_task_id="task-1", status="completed"),
    )
    assert completed.pending is not None

    finalized = decide_delegation_action(
        DelegationSnapshot(pending=completed.pending),
        FinalizeResumeAction(conversation_ref="registry:conv-7"),
    )
    assert finalized.status == "cleared_after_resume"
    assert finalized.effects.clear_pending is True
