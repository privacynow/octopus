import time

from app.workflows.delegation.coordination import (
    all_tasks_terminal,
    any_task_failed,
    apply_routed_result,
    build_delegation_completion_message,
    build_delegation_plan,
    expire_stale_delegations,
    mark_task_submitted,
)
from octopus_sdk.registry.models import RoutedTaskResult


def test_build_delegation_plan_sets_proposed_status():
    plan = build_delegation_plan(
        "telegram:agent:12345",
        "Ship the feature",
        "Continue after the delegated work completes.",
        [
            {
                "routed_task_id": "task-1",
                "title": "Implement the API",
                "target_agent_id": "developer-1",
                "instructions": "Build the endpoint and validate inputs.",
            },
            {
                "routed_task_id": "task-2",
                "title": "Review the changes",
                "target_agent_id": "reviewer-1",
                "instructions": "Review correctness and test coverage.",
            },
        ],
    )

    assert [task.status for task in plan.tasks] == ["proposed", "proposed"]


def test_build_delegation_plan_preserves_task_fields():
    plan = build_delegation_plan(
        "registry:conv-1",
        "Spec delegation",
        "Resume when both child tasks return.",
        [
            {
                "routed_task_id": "task-3",
                "title": "Draft tests",
                "target_agent_id": "test-writer-1",
                "instructions": "Write focused regression tests.",
            },
        ],
    )

    task = plan.tasks[0]
    assert plan.conversation_ref == "registry:conv-1"
    assert plan.title == "Spec delegation"
    assert plan.resume_instruction == "Resume when both child tasks return."
    assert task.routed_task_id == "task-3"
    assert task.title == "Draft tests"
    assert task.authority_ref == ""
    assert task.target_agent_id == "test-writer-1"
    assert task.instructions == "Write focused regression tests."


def test_build_delegation_plan_does_not_translate_registry_id_to_authority_ref():
    plan = build_delegation_plan(
        "registry:conv-legacy",
        "Spec delegation",
        "Resume when the child task returns.",
        [
            {
                "routed_task_id": "task-legacy",
                "registry_id": "prod",
                "title": "Draft tests",
                "target_agent_id": "test-writer-1",
                "instructions": "Write focused regression tests.",
            },
        ],
    )

    assert plan.tasks[0].authority_ref == ""


def test_pending_delegation_status_transitions_completed():
    plan = build_delegation_plan(
        "registry:conv-1",
        "Spec delegation",
        "Resume when both child tasks return.",
        [
            {
                "routed_task_id": "task-1",
                "title": "Implement",
                "target_agent_id": "developer-1",
                "instructions": "Build it.",
            },
            {
                "routed_task_id": "task-2",
                "title": "Review",
                "target_agent_id": "reviewer-1",
                "instructions": "Review it.",
            },
        ],
    )
    plan.tasks[0].status = "submitted"
    plan.tasks[1].status = "submitted"

    outcome = apply_routed_result(
        plan,
        routed_task_id="task-1",
        result=RoutedTaskResult(routed_task_id="task-1", status="completed", transition_id="task-1-complete", summary="done"),
    )
    assert outcome.matched is True
    plan = outcome.pending
    assert plan is not None
    assert plan.status == "submitted"
    assert all_tasks_terminal(plan) is False

    outcome = apply_routed_result(
        plan,
        routed_task_id="task-2",
        result=RoutedTaskResult(routed_task_id="task-2", status="completed", transition_id="task-2-complete", summary="done"),
    )
    assert outcome.matched is True
    plan = outcome.pending
    assert plan is not None
    assert plan.status == "completed"
    assert all_tasks_terminal(plan) is True
    assert any_task_failed(plan) is False


def test_pending_delegation_status_transitions_partial_failed():
    plan = build_delegation_plan(
        "registry:conv-2",
        "Spec delegation",
        "Resume when both child tasks return.",
        [
            {
                "routed_task_id": "task-1",
                "title": "Implement",
                "target_agent_id": "developer-1",
                "instructions": "Build it.",
            },
            {
                "routed_task_id": "task-2",
                "title": "Review",
                "target_agent_id": "reviewer-1",
                "instructions": "Review it.",
            },
        ],
    )
    for task in plan.tasks:
        task.status = "submitted"

    first = apply_routed_result(
        plan,
        routed_task_id="task-1",
        result=RoutedTaskResult(routed_task_id="task-1", status="completed", transition_id="task-1-complete", summary="done"),
    )
    assert first.pending is not None
    second = apply_routed_result(
        first.pending,
        routed_task_id="task-2",
        result=RoutedTaskResult(routed_task_id="task-2", status="failed", transition_id="task-2-fail", summary="boom", full_text="Tool crashed"),
    )
    plan = second.pending
    assert plan is not None
    assert plan.status == "partial_failed"
    assert all_tasks_terminal(plan) is True
    assert any_task_failed(plan) is True


def test_apply_routed_result_matches_registry_provenance_when_task_ids_overlap():
    plan = build_delegation_plan(
        "registry:prod:conversation:conv-1",
        "Spec delegation",
        "Resume when both child tasks return.",
        [
            {
                "routed_task_id": "task-shared",
                "authority_ref": "registry:prod",
                "title": "Prod task",
                "target_agent_id": "developer-prod",
                "instructions": "Handle prod.",
            },
            {
                "routed_task_id": "task-shared",
                "authority_ref": "registry:ops",
                "title": "Ops task",
                "target_agent_id": "developer-ops",
                "instructions": "Handle ops.",
            },
        ],
    )
    for task in plan.tasks:
        task.status = "submitted"

    outcome = apply_routed_result(
        plan,
        routed_task_id="task-shared",
        authority_ref="registry:ops",
        result=RoutedTaskResult(routed_task_id="task-shared", status="completed", transition_id="task-shared-complete", summary="ops done"),
    )

    assert outcome.pending is not None
    assert outcome.pending.tasks[0].status == "submitted"
    assert outcome.pending.tasks[1].status == "completed"


def test_build_delegation_completion_message_partial_failed_names_failed_tasks():
    plan = build_delegation_plan(
        "registry:conv-3",
        "Spec delegation",
        "Resume when both child tasks return.",
        [
            {
                "routed_task_id": "task-1",
                "title": "Implement",
                "target_agent_id": "developer-1",
                "instructions": "Build it.",
            },
            {
                "routed_task_id": "task-2",
                "title": "Review",
                "target_agent_id": "reviewer-1",
                "instructions": "Review it.",
            },
        ],
    )
    plan.tasks[0].status = "completed"
    plan.tasks[0].summary = "Implemented."
    plan.tasks[1].status = "failed"
    plan.tasks[1].full_text = "Review tool crashed."
    plan.status = "partial_failed"

    message = build_delegation_completion_message(plan)

    assert "Some delegated tasks failed." in message
    assert "while I synthesize the final answer." in message
    assert "Review [failed]" in message
    assert "Review tool crashed." in message
    assert "retry the failed tasks" in message


def test_build_delegation_completion_message_completed_is_explicitly_preliminary():
    plan = build_delegation_plan(
        "registry:conv-4",
        "Spec delegation",
        "Resume when both child tasks return.",
        [
            {
                "routed_task_id": "task-1",
                "title": "Implement",
                "target_agent_id": "developer-1",
                "instructions": "Build it.",
            },
        ],
    )
    plan.tasks[0].status = "completed"
    plan.tasks[0].summary = "Implemented."
    plan.status = "completed"

    message = build_delegation_completion_message(plan)

    assert "All delegated tasks completed." in message
    assert "while I synthesize the final answer." in message


def test_expire_stale_delegations_transitions_submitted_tasks_to_failed():
    plan = build_delegation_plan(
        "registry:conv-timeout",
        "Spec delegation",
        "Resume when both child tasks return.",
        [
            {
                "routed_task_id": "task-1",
                "title": "Implement",
                "target_agent_id": "developer-1",
                "instructions": "Build it.",
            },
            {
                "routed_task_id": "task-2",
                "title": "Review",
                "target_agent_id": "reviewer-1",
                "instructions": "Review it.",
            },
        ],
    )
    for task in plan.tasks:
        task.status = "submitted"
    plan.created_at = 0.0

    outcome = expire_stale_delegations(plan, timeout_seconds=3600)

    assert outcome.expired is True
    assert outcome.pending is not None
    assert outcome.pending.status == "partial_failed"
    assert [task.status for task in outcome.pending.tasks] == ["failed", "failed"]
    assert "delegation timed out" in outcome.pending.tasks[0].summary


def test_mark_task_submitted_stamps_submission_time():
    plan = build_delegation_plan(
        "registry:conv-submit",
        "Spec delegation",
        "Resume when child tasks return.",
        [
            {
                "routed_task_id": "task-1",
                "title": "Implement",
                "target_agent_id": "developer-1",
                "instructions": "Build it.",
            }
        ],
    )

    outcome = mark_task_submitted(
        plan,
        routed_task_id="task-1",
    )

    assert outcome.matched is True
    assert outcome.pending is not None
    assert outcome.pending.tasks[0].status == "submitted"
    assert outcome.pending.tasks[0].submitted_at


def test_expire_stale_delegations_uses_submission_time_for_submitted_tasks():
    plan = build_delegation_plan(
        "registry:conv-submitted-at",
        "Spec delegation",
        "Resume when child tasks return.",
        [
            {
                "routed_task_id": "task-1",
                "title": "Implement",
                "target_agent_id": "developer-1",
                "instructions": "Build it.",
            }
        ],
    )
    now = time.time()
    plan.created_at = now - 10_000
    plan.tasks[0].status = "submitted"
    plan.tasks[0].submitted_at = now - 10

    outcome = expire_stale_delegations(plan, timeout_seconds=3600)

    assert outcome.expired is False
    assert outcome.pending is plan


def test_expire_stale_delegations_uses_creation_time_for_unsubmitted_tasks():
    plan = build_delegation_plan(
        "registry:conv-approval-expiry",
        "Spec delegation",
        "Resume when child tasks return.",
        [
            {
                "routed_task_id": "task-1",
                "title": "Implement",
                "target_agent_id": "developer-1",
                "instructions": "Build it.",
            }
        ],
    )
    plan.created_at = 0.0

    outcome = expire_stale_delegations(plan, timeout_seconds=3600)

    assert outcome.expired is True
    assert outcome.expired_kind == "approval_expired"
    assert outcome.pending is not None
    assert outcome.pending.tasks[0].status == "failed"
    assert "approval expired" in outcome.pending.tasks[0].summary


def test_expire_stale_delegations_within_timeout_leaves_pending_unchanged():
    plan = build_delegation_plan(
        "registry:conv-fresh",
        "Spec delegation",
        "Resume when both child tasks return.",
        [
            {
                "routed_task_id": "task-1",
                "title": "Implement",
                "target_agent_id": "developer-1",
                "instructions": "Build it.",
            },
        ],
    )

    outcome = expire_stale_delegations(plan, timeout_seconds=3600)

    assert outcome.expired is False
    assert outcome.pending is plan
