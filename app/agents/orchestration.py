"""Parent-side delegation state helpers."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from app.agents.types import RoutedTaskResult
from app.session_state import DelegatedTask, PendingDelegation
from app.formatting import trim_text

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
    updated_pending = replace(pending, tasks=tasks)
    if all_tasks_terminal(updated_pending):
        updated_pending = replace(
            updated_pending,
            status="partial_failed" if any_task_failed(updated_pending) else "completed",
        )
    return updated_pending, True


def all_tasks_terminal(delegation: PendingDelegation | None) -> bool:
    if delegation is None or not delegation.tasks:
        return False
    return all((task.status or "").strip().lower() in {"completed", "failed"} for task in delegation.tasks)


def any_task_failed(delegation: PendingDelegation | None) -> bool:
    if delegation is None:
        return False
    return any((task.status or "").strip().lower() == "failed" for task in delegation.tasks)


def delegation_ready_to_resume(pending: PendingDelegation | None) -> bool:
    if pending is None or not pending.tasks:
        return False
    if pending.status in {"completed", "partial_failed"}:
        return True
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


def build_delegation_completion_message(delegation: PendingDelegation | None) -> str:
    if delegation is None or not delegation.tasks:
        return ""
    lines: list[str] = []
    if delegation.status == "partial_failed":
        lines.append("Some delegated tasks failed. Here are the raw results while I synthesize the final answer.")
    else:
        lines.append("All delegated tasks completed. Here are the raw results while I synthesize the final answer.")
    lines.append("")
    for index, task in enumerate(delegation.tasks, start=1):
        label = task.title or task.routed_task_id
        status = (task.status or "completed").replace("_", " ")
        lines.append(f"{index}. {label} [{status}]")
        detail = task.summary or task.full_text
        if detail:
            lines.append(f"   {trim_text(detail.strip(), 180)}")
    if delegation.status == "partial_failed":
        lines.append("")
        lines.append("You can retry the failed tasks in a follow-on step if needed.")
    return "\n".join(lines).strip()


async def send_delegation_completion_message(
    delegation: PendingDelegation | None,
    surface: Any,
) -> None:
    message = build_delegation_completion_message(delegation)
    if not message:
        return
    await surface.send_text(message)
