from app.agents.orchestration import (
    all_tasks_terminal,
    any_task_failed,
    apply_routed_result,
    build_delegation_completion_message,
    build_delegation_plan,
)
from app.agents.types import RoutedTaskResult


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
    assert task.target_agent_id == "test-writer-1"
    assert task.instructions == "Write focused regression tests."


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

    plan, matched = apply_routed_result(
        plan,
        routed_task_id="task-1",
        result=RoutedTaskResult(routed_task_id="task-1", status="completed", summary="done"),
    )
    assert matched is True
    assert plan is not None
    assert plan.status == ""
    assert all_tasks_terminal(plan) is False

    plan, matched = apply_routed_result(
        plan,
        routed_task_id="task-2",
        result=RoutedTaskResult(routed_task_id="task-2", status="completed", summary="done"),
    )
    assert matched is True
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

    plan, _ = apply_routed_result(
        plan,
        routed_task_id="task-1",
        result=RoutedTaskResult(routed_task_id="task-1", status="completed", summary="done"),
    )
    plan, _ = apply_routed_result(
        plan,
        routed_task_id="task-2",
        result=RoutedTaskResult(routed_task_id="task-2", status="failed", summary="boom", full_text="Tool crashed"),
    )
    assert plan is not None
    assert plan.status == "partial_failed"
    assert all_tasks_terminal(plan) is True
    assert any_task_failed(plan) is True


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
