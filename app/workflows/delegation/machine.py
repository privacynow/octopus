"""Functional decision machine for delegation progression."""

from __future__ import annotations

from dataclasses import dataclass, replace

from app.session_state import DelegatedTask, PendingDelegation
from app.workflows.delegation.contracts import DelegationTaskDraft

CHILD_ACTIVE_STATUSES = frozenset({"pending", "proposed", "queued", "leased", "running", "submitted"})
CHILD_TERMINAL_STATUSES = frozenset({"completed", "failed"})
PARENT_TERMINAL_STATUSES = frozenset({"completed", "partial_failed", "cancelled"})

_ALLOWED_CHILD_TRANSITIONS = {
    "pending": frozenset({"pending", "submitted", "queued", "leased", "running", "completed", "failed"}),
    "proposed": frozenset({"proposed", "submitted", "queued", "leased", "running", "completed", "failed"}),
    "submitted": frozenset({"submitted", "queued", "leased", "running", "completed", "failed"}),
    "queued": frozenset({"queued", "leased", "running", "completed", "failed"}),
    "leased": frozenset({"leased", "running", "completed", "failed"}),
    "running": frozenset({"running", "completed", "failed"}),
    "completed": frozenset({"completed"}),
    "failed": frozenset({"failed"}),
}


def normalize_parent_status(status: str) -> str:
    text = (status or "").strip().lower()
    return text or "proposed"


def normalize_child_status(status: str) -> str:
    text = (status or "").strip().lower()
    return text or "proposed"


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
    return normalize_parent_status(pending.status) in {"completed", "partial_failed"}


def _derive_parent_status(tasks: tuple[DelegatedTask, ...]) -> str:
    if not tasks:
        return "proposed"
    statuses = [normalize_child_status(task.status) for task in tasks]
    if all(status in CHILD_TERMINAL_STATUSES for status in statuses):
        return "partial_failed" if "failed" in statuses else "completed"
    if any(status in {"pending", "submitted", "queued", "leased", "running"} for status in statuses):
        return "submitted"
    return "proposed"


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
    summary: str = ""
    full_text: str = ""
    follow_up_questions: tuple[str, ...] = ()
    completed_at: str = ""


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
    allowed = _ALLOWED_CHILD_TRANSITIONS.get(current_status, frozenset())
    if next_status not in allowed:
        return task
    return replace(
        task,
        status=next_status,
        summary=action.summary or task.summary,
        full_text=action.full_text or task.full_text,
        follow_up_questions=list(action.follow_up_questions) if action.follow_up_questions else list(task.follow_up_questions),
        completed_at=action.completed_at or task.completed_at,
    )


def decide_delegation_action(snapshot: DelegationSnapshot, action: DelegationAction) -> DelegationDecision:
    pending = snapshot.pending

    if isinstance(action, ProposeDelegationAction):
        tasks = tuple(
            DelegatedTask(
                routed_task_id=item.routed_task_id,
                title=item.title,
                target_agent_id=item.target_agent_id,
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
        return DelegationDecision(
            status="cancelled",
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
            next_task = _task_with_status(task, action)
            updated = updated or next_task != task
            tasks.append(next_task)
        if not updated:
            return DelegationDecision(status="not_found", ok=True, pending=pending, matched=False)
        updated_pending = replace(
            pending,
            tasks=tasks,
            status=_derive_parent_status(tuple(tasks)),
        )
        return DelegationDecision(
            status=normalize_parent_status(updated_pending.status),
            ok=True,
            effects=DelegationEffects(set_pending=updated_pending),
            pending=updated_pending,
            matched=True,
            ready_to_resume=delegation_ready_to_resume(updated_pending),
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
