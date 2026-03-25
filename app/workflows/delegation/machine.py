"""Functional decision machine for delegation progression."""

from __future__ import annotations

import time
from dataclasses import dataclass, replace

from octopus_sdk.registry.models import DelegationTaskDraft
from octopus_sdk.sessions import DelegatedTask, PendingDelegation
from octopus_sdk.task_protocol import (
    DELEGATED_TASK_ACTIVE_STATES,
    DELEGATED_TASK_TERMINAL_STATES,
    PENDING_DELEGATION_TERMINAL_STATES,
    PendingDelegationSnapshot,
    PendingDelegationTransitionRequest,
    apply_pending_delegation_transition,
    delegation_ready_to_resume as pending_delegation_ready_to_resume,
    normalize_delegated_task_status,
    normalize_pending_delegation_status,
    validate_delegated_task_transition,
)

CHILD_ACTIVE_STATUSES = DELEGATED_TASK_ACTIVE_STATES
CHILD_TERMINAL_STATUSES = DELEGATED_TASK_TERMINAL_STATES
PARENT_TERMINAL_STATUSES = PENDING_DELEGATION_TERMINAL_STATES


def normalize_parent_status(status: str) -> str:
    return normalize_pending_delegation_status(status)


def normalize_child_status(status: str) -> str:
    return normalize_delegated_task_status(status)


def all_tasks_terminal(pending: PendingDelegation | None) -> bool:
    if pending is None or not pending.tasks:
        return False
    return all(normalize_child_status(task.status) in CHILD_TERMINAL_STATUSES for task in pending.tasks)


def any_task_failed(pending: PendingDelegation | None) -> bool:
    if pending is None:
        return False
    return any(normalize_child_status(task.status) == "failed" for task in pending.tasks)


def delegation_ready_to_resume(pending: PendingDelegation | None) -> bool:
    if pending is None:
        return False
    return pending_delegation_ready_to_resume(pending.status)


@dataclass(frozen=True)
class DelegationSnapshot:
    pending: PendingDelegation | None


@dataclass(frozen=True)
class DelegationEffects:
    set_pending: PendingDelegation | None = None
    clear_pending: bool = False
    tasks_to_submit: tuple[DelegatedTask, ...] = ()


@dataclass(frozen=True)
class DelegationDecision:
    status: str
    ok: bool
    effects: DelegationEffects = DelegationEffects()
    pending: PendingDelegation | None = None
    matched: bool = False
    ready_to_resume: bool = False


@dataclass(frozen=True)
class ProposeDelegationAction:
    conversation_ref: str
    title: str
    resume_instruction: str
    tasks: tuple[DelegationTaskDraft, ...]


@dataclass(frozen=True)
class PrepareApprovalAction:
    conversation_ref: str


@dataclass(frozen=True)
class CancelDelegationAction:
    conversation_ref: str


@dataclass(frozen=True)
class UpdateTaskStatusAction:
    routed_task_id: str
    status: str
    authority_ref: str = ""
    summary: str = ""
    full_text: str = ""
    follow_up_questions: tuple[str, ...] = ()
    completed_at: str = ""
    submitted_at: float | str = 0.0


@dataclass(frozen=True)
class FinalizeResumeAction:
    conversation_ref: str


DelegationAction = (
    ProposeDelegationAction
    | PrepareApprovalAction
    | CancelDelegationAction
    | UpdateTaskStatusAction
    | FinalizeResumeAction
)


def _task_with_status(task: DelegatedTask, action: UpdateTaskStatusAction) -> DelegatedTask:
    next_status = normalize_child_status(action.status)
    current_status = normalize_child_status(task.status)
    decision = validate_delegated_task_transition(current_status, next_status)
    if not decision.ok:
        return task
    submitted_at = task.submitted_at
    if next_status == "submitted":
        submitted_at = action.submitted_at or task.submitted_at or time.time()
    return replace(
        task,
        status=next_status,
        authority_ref=action.authority_ref or task.authority_ref,
        summary=action.summary or task.summary,
        full_text=action.full_text or task.full_text,
        follow_up_questions=list(action.follow_up_questions) if action.follow_up_questions else list(task.follow_up_questions),
        completed_at=action.completed_at or task.completed_at,
        submitted_at=submitted_at,
    )


def decide_delegation_action(snapshot: DelegationSnapshot, action: DelegationAction) -> DelegationDecision:
    pending = snapshot.pending

    if isinstance(action, ProposeDelegationAction):
        tasks = tuple(
            DelegatedTask(
                routed_task_id=item.draft_id,
                title=item.title,
                authority_ref=item.authority_ref,
                target_agent_id=item.selector.preferred_agent_id or item.selector.value,
                instructions=item.instructions,
                status="proposed",
            )
            for item in action.tasks
        )
        pending = PendingDelegation(
            conversation_ref=action.conversation_ref,
            title=action.title,
            resume_instruction=action.resume_instruction,
            tasks=list(tasks),
            status="proposed",
        )
        return DelegationDecision(
            status="proposed",
            ok=True,
            effects=DelegationEffects(set_pending=pending),
            pending=pending,
        )

    if pending is None:
        return DelegationDecision(status="no_delegation", ok=True)

    if isinstance(action, PrepareApprovalAction):
        if pending.conversation_ref and pending.conversation_ref != action.conversation_ref:
            return DelegationDecision(status="no_delegation", ok=True)
        tasks_to_submit = tuple(task for task in pending.tasks if normalize_child_status(task.status) == "proposed")
        if not tasks_to_submit:
            return DelegationDecision(status="nothing_to_approve", ok=True, pending=pending)
        return DelegationDecision(
            status="approve_ready",
            ok=True,
            effects=DelegationEffects(tasks_to_submit=tasks_to_submit),
            pending=pending,
        )

    if isinstance(action, CancelDelegationAction):
        if pending.conversation_ref and pending.conversation_ref != action.conversation_ref:
            return DelegationDecision(status="no_delegation", ok=True, pending=pending)
        if any(normalize_child_status(task.status) != "proposed" for task in pending.tasks):
            return DelegationDecision(status="not_cancellable", ok=True, pending=pending)
        parent_transition = apply_pending_delegation_transition(
            PendingDelegationSnapshot(
                status=pending.status,
                task_statuses=tuple(task.status for task in pending.tasks),
            ),
            PendingDelegationTransitionRequest(transition="cancel"),
        )
        if not parent_transition.ok:
            return DelegationDecision(status="not_cancellable", ok=True, pending=pending)
        return DelegationDecision(
            status=parent_transition.new_state,
            ok=True,
            effects=DelegationEffects(clear_pending=True),
        )

    if isinstance(action, UpdateTaskStatusAction):
        updated = False
        tasks: list[DelegatedTask] = []
        for task in pending.tasks:
            if task.routed_task_id != action.routed_task_id:
                tasks.append(task)
                continue
            if action.authority_ref and task.authority_ref and task.authority_ref != action.authority_ref:
                tasks.append(task)
                continue
            next_task = _task_with_status(task, action)
            updated = updated or next_task != task
            tasks.append(next_task)
        if not updated:
            return DelegationDecision(status="not_found", ok=True, pending=pending, matched=False)
        parent_transition = apply_pending_delegation_transition(
            PendingDelegationSnapshot(
                status=pending.status,
                task_statuses=tuple(task.status for task in pending.tasks),
            ),
            PendingDelegationTransitionRequest(
                transition="sync_children",
                task_statuses=tuple(task.status for task in tasks),
            ),
        )
        next_parent_status = parent_transition.new_state if parent_transition.ok else normalize_parent_status(pending.status)
        updated_pending = replace(
            pending,
            tasks=tasks,
            status=next_parent_status,
        )
        return DelegationDecision(
            status=normalize_parent_status(updated_pending.status),
            ok=True,
            effects=DelegationEffects(set_pending=updated_pending),
            pending=updated_pending,
            matched=True,
            ready_to_resume=parent_transition.ready_to_resume if parent_transition.ok else delegation_ready_to_resume(updated_pending),
        )

    if isinstance(action, FinalizeResumeAction):
        if pending.conversation_ref and pending.conversation_ref != action.conversation_ref:
            return DelegationDecision(status="no_delegation", ok=True, pending=pending)
        if not delegation_ready_to_resume(pending):
            return DelegationDecision(status="not_ready", ok=True, pending=pending)
        return DelegationDecision(
            status="cleared_after_resume",
            ok=True,
            effects=DelegationEffects(clear_pending=True),
        )

    raise ValueError(f"Unknown delegation action: {action!r}")
