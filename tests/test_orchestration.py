from app.agents.orchestration import build_delegation_plan


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
