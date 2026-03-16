"""Parent-side delegation state helpers."""

from __future__ import annotations

from dataclasses import replace

from app.agents.types import RoutedTaskResult
from app.session_state import DelegatedTask, PendingDelegation

_ACTIVE_DELEGATION_STATES = {"", "pending", "proposed", "queued", "leased", "running", "submitted"}


def build_delegation_plan(
    conversation_ref: str,
    title: str,
    resume_instruction: str,
    tasks: list[dict[str, str]],
) -> PendingDelegation:
    """Build a PendingDelegation from provider-supplied child-task descriptors."""
    delegated_tasks = [
        DelegatedTask(
            routed_task_id=str(task["routed_task_id"]),
            title=str(task["title"]),
            target_agent_id=str(task["target_agent_id"]),
            instructions=str(task["instructions"]),
            status="proposed",
        )
        for task in tasks
    ]
    return PendingDelegation(
        conversation_ref=conversation_ref,
        title=title,
        resume_instruction=resume_instruction,
        tasks=delegated_tasks,
    )


def apply_routed_result(
    pending: PendingDelegation | None,
    *,
    routed_task_id: str,
    result: RoutedTaskResult,
) -> tuple[PendingDelegation | None, bool]:
    """Apply one child result onto the parent-side delegation tracker."""
    if pending is None:
        return None, False

    updated = False
    tasks: list[DelegatedTask] = []
    for task in pending.tasks:
        if task.routed_task_id != routed_task_id:
            tasks.append(task)
            continue
        tasks.append(
            replace(
                task,
                status=result.status or "completed",
                summary=result.summary,
                full_text=result.full_text,
                follow_up_questions=list(result.follow_up_questions),
                completed_at=result.completed_at,
            )
        )
        updated = True
    if not updated:
        return pending, False
    return replace(pending, tasks=tasks), True


def delegation_ready_to_resume(pending: PendingDelegation | None) -> bool:
    if pending is None or not pending.tasks:
        return False
    for task in pending.tasks:
        if (task.status or "").strip().lower() in _ACTIVE_DELEGATION_STATES:
            return False
    return True


def build_resume_prompt(pending: PendingDelegation) -> str:
    """Build the synthetic parent continuation prompt once all child results arrive."""
    intro = pending.resume_instruction.strip() or (
        "Delegated task results are ready. Continue the parent task using the child outputs below. "
        "Synthesize the results, note any conflicts, and either answer the user or ask the next necessary question."
    )
    sections = [intro]
    if pending.title.strip():
        sections.append(f"Delegation plan: {pending.title.strip()}")
    for index, task in enumerate(pending.tasks, start=1):
        lines = [
            f"Child task {index}: {task.title or task.routed_task_id}",
            f"Routed task id: {task.routed_task_id}",
            f"Status: {task.status or 'completed'}",
        ]
        if task.summary:
            lines.append(f"Summary: {task.summary}")
        if task.full_text:
            lines.append("Full result:")
            lines.append(task.full_text)
        for question in task.follow_up_questions:
            if question:
                lines.append(f"Follow-up question: {question}")
        sections.append("\n".join(lines))
    return "\n\n".join(section for section in sections if section).strip()
