from app.session_state import DelegatedTask, PendingDelegation, SessionState, session_from_dict, session_to_dict


def test_delegated_task_instructions_round_trips():
    session = SessionState(
        provider="claude",
        provider_state={},
        approval_mode="off",
        pending_delegation=PendingDelegation(
            conversation_ref="telegram:agent:12345",
            title="Delegation plan",
            resume_instruction="Continue when the child tasks finish.",
            tasks=[
                DelegatedTask(
                    routed_task_id="task-1",
                    authority_ref="registry:prod",
                    title="Implement feature",
                    target_agent_id="developer-1",
                    instructions="Add the endpoint and tests.",
                    status="proposed",
                ),
                DelegatedTask(
                    routed_task_id="task-2",
                    authority_ref="registry:ops",
                    title="Review feature",
                    target_agent_id="reviewer-1",
                    instructions="Review for correctness and risk.",
                    status="submitted",
                ),
            ],
        ),
    )

    restored = session_from_dict(session_to_dict(session))

    assert restored.pending_delegation is not None
    assert restored.pending_delegation.status == ""
    assert [task.instructions for task in restored.pending_delegation.tasks] == [
        "Add the endpoint and tests.",
        "Review for correctness and risk.",
    ]
    assert [task.authority_ref for task in restored.pending_delegation.tasks] == [
        "registry:prod",
        "registry:ops",
    ]


def test_pending_delegation_status_round_trips():
    session = SessionState(
        provider="claude",
        provider_state={},
        approval_mode="off",
        pending_delegation=PendingDelegation(
            conversation_ref="registry:conv-1",
            title="Delegation plan",
            status="partial_failed",
            tasks=[
                DelegatedTask(
                    routed_task_id="task-1",
                    title="Implement feature",
                    target_agent_id="developer-1",
                    instructions="Add the endpoint and tests.",
                    status="failed",
                )
            ],
        ),
    )

    restored = session_from_dict(session_to_dict(session))

    assert restored.pending_delegation is not None
    assert restored.pending_delegation.status == "partial_failed"
