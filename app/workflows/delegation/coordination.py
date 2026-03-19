"""Concern-owned workflow helpers for delegation progression."""

from __future__ import annotations

from typing import Any

from app.agents.types import RoutedTaskResult
from app.formatting import trim_text
from app.session_state import DelegatedTask, PendingDelegation
from app.workflows.delegation.contracts import (
    DelegationApprovalPreparation,
    DelegationTaskDraft,
    DelegationUpdateOutcome,
)
from app.workflows.delegation.machine import (
    CHILD_ACTIVE_STATUSES,
    CHILD_TERMINAL_STATUSES,
    CancelDelegationAction,
    DelegationSnapshot,
    FinalizeResumeAction,
    PrepareApprovalAction,
    ProposeDelegationAction,
    UpdateTaskStatusAction,
    all_tasks_terminal,
    any_task_failed,
    decide_delegation_action,
    delegation_ready_to_resume,
    normalize_child_status,
)


def build_delegation_plan(
    conversation_ref: str,
    title: str,
    resume_instruction: str,
    tasks: list[dict[str, str]],
) -> PendingDelegation:
    decision = decide_delegation_action(
        DelegationSnapshot(pending=None),
        ProposeDelegationAction(
            conversation_ref=conversation_ref,
            title=title,
            resume_instruction=resume_instruction,
            tasks=tuple(
                DelegationTaskDraft(
                    routed_task_id=str(task["routed_task_id"]),
                    title=str(task.get("title", "")),
                    target_agent_id=str(task.get("target_agent_id", "")),
                    instructions=str(task.get("instructions", "")),
                )
                for task in tasks
            ),
        ),
    )
    pending = decision.effects.set_pending
    if pending is None:
        raise RuntimeError("Delegation plan creation did not produce pending state")
    return pending


def prepare_delegation_approval(
    pending: PendingDelegation | None,
    *,
    conversation_ref: str,
) -> DelegationApprovalPreparation:
    decision = decide_delegation_action(
        DelegationSnapshot(pending=pending),
        PrepareApprovalAction(conversation_ref=conversation_ref),
    )
    return DelegationApprovalPreparation(
        status=decision.status,
        pending=decision.pending,
        tasks_to_submit=decision.effects.tasks_to_submit,
    )


def mark_task_submitted(
    pending: PendingDelegation | None,
    *,
    routed_task_id: str,
) -> DelegationUpdateOutcome:
    decision = decide_delegation_action(
        DelegationSnapshot(pending=pending),
        UpdateTaskStatusAction(routed_task_id=routed_task_id, status="submitted"),
    )
    return DelegationUpdateOutcome(
        status=decision.status,
        pending=decision.effects.set_pending if decision.effects.set_pending is not None else decision.pending,
        matched=decision.matched,
        ready_to_resume=decision.ready_to_resume,
    )


def apply_routed_result(
    pending: PendingDelegation | None,
    *,
    routed_task_id: str,
    result: RoutedTaskResult,
) -> DelegationUpdateOutcome:
    decision = decide_delegation_action(
        DelegationSnapshot(pending=pending),
        UpdateTaskStatusAction(
            routed_task_id=routed_task_id,
            status=result.status or "completed",
            summary=result.summary,
            full_text=result.full_text,
            follow_up_questions=tuple(result.follow_up_questions),
            completed_at=result.completed_at,
        ),
    )
    updated_pending = decision.effects.set_pending if decision.effects.set_pending is not None else decision.pending
    resume_prompt = build_resume_prompt(updated_pending) if decision.ready_to_resume and updated_pending is not None else ""
    completion_message = (
        build_delegation_completion_message(updated_pending)
        if decision.ready_to_resume and updated_pending is not None
        else ""
    )
    return DelegationUpdateOutcome(
        status=decision.status,
        pending=updated_pending,
        matched=decision.matched,
        ready_to_resume=decision.ready_to_resume,
        resume_prompt=resume_prompt,
        completion_message=completion_message,
    )


def cancel_delegation(
    pending: PendingDelegation | None,
    *,
    conversation_ref: str,
) -> DelegationUpdateOutcome:
    decision = decide_delegation_action(
        DelegationSnapshot(pending=pending),
        CancelDelegationAction(conversation_ref=conversation_ref),
    )
    return DelegationUpdateOutcome(
        status=decision.status,
        pending=decision.effects.set_pending if decision.effects.set_pending is not None else decision.pending,
    )


def finalize_resumed_delegation(
    pending: PendingDelegation | None,
    *,
    conversation_ref: str,
) -> DelegationUpdateOutcome:
    decision = decide_delegation_action(
        DelegationSnapshot(pending=pending),
        FinalizeResumeAction(conversation_ref=conversation_ref),
    )
    return DelegationUpdateOutcome(
        status=decision.status,
        pending=decision.effects.set_pending if decision.effects.set_pending is not None else decision.pending,
    )


def build_resume_prompt(pending: PendingDelegation | None) -> str:
    if pending is None:
        return ""
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
    channel_egress: Any,
) -> None:
    message = build_delegation_completion_message(delegation)
    if not message:
        return
    await channel_egress.send_text(message)
