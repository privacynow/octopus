"""SDK-owned delegation workflow models and progression helpers."""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Awaitable, Callable, Protocol

from octopus_sdk.config import BotConfigBase
from octopus_sdk.identity import normalize_conversation_id, validate_qualified_transport_ref
from octopus_sdk.providers import ProviderStateRecord
from octopus_sdk.registry.models import (
    CoordinationActionResult,
    DelegationIntent,
    DelegationTaskDraft,
    RoutedTaskResult,
    TargetResolutionPreview,
    TargetSelector,
)
from octopus_sdk.registry_participant import RegistryCoordination
from octopus_sdk.sessions import DelegatedTask, PendingDelegation, SessionState
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
from octopus_sdk.time_utils import utc_now_iso

CHILD_ACTIVE_STATUSES = DELEGATED_TASK_ACTIVE_STATES
CHILD_TERMINAL_STATUSES = DELEGATED_TASK_TERMINAL_STATES
PARENT_TERMINAL_STATUSES = PENDING_DELEGATION_TERMINAL_STATES

_DELEGATION_TIMEOUT_SUMMARY = "delegation timed out — no result received"
_DELEGATION_APPROVAL_EXPIRED_SUMMARY = "delegation approval expired — no requests were sent"


def _registry_error_summary(error: str) -> str:
    code = str(error or "").strip()
    if code == "no control plane":
        return "No coordination-capable registry connections are configured."
    if code == "registry_unreachable":
        return "Registry could not be reached."
    if code == "registry_timeout":
        return "Registry timed out."
    if code == "registry_request_failed":
        return "Registry request failed."
    if code == "registry_server_error":
        return "Registry is temporarily unavailable."
    return code or "Registry is temporarily unavailable."


class SessionRuntime(Protocol):
    def load(
        self,
        conversation_key: str,
        *,
        provider_name: str,
        provider_state_factory,
        approval_mode: str,
        default_role: str = "",
        default_skills: tuple[str, ...] = (),
    ) -> SessionState: ...

    def save(
        self,
        conversation_key: str,
        session: SessionState,
    ) -> None: ...


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
class DelegationTargetPreview:
    routed_task_id: str
    status: str
    authority_ref: str = ""
    detail: str = ""


@dataclass(frozen=True)
class DelegationApprovalPreparation:
    status: str
    pending: PendingDelegation | None = None
    tasks_to_submit: tuple[DelegatedTask, ...] = ()


@dataclass(frozen=True)
class DelegationUpdateOutcome:
    status: str
    pending: PendingDelegation | None = None
    matched: bool = False
    ready_to_resume: bool = False
    resume_prompt: str = ""
    completion_message: str = ""


@dataclass(frozen=True)
class DelegationExpirationOutcome:
    status: str
    pending: PendingDelegation | None = None
    expired: bool = False
    expired_kind: str = ""
    ready_to_resume: bool = False
    completion_message: str = ""


@dataclass(frozen=True)
class ParticipantDelegationPlan:
    status: str
    pending: PendingDelegation | None
    previews: tuple[DelegationTargetPreview, ...]
    action_result: CoordinationActionResult | None = None


@dataclass(frozen=True)
class DelegationCommandOutcome:
    status: str
    message: str = ""
    pending: PendingDelegation | None = None


@dataclass(frozen=True)
class ParticipantDelegationRuntime:
    config: BotConfigBase
    provider_name: str
    provider_state_factory: Callable[[str], ProviderStateRecord]
    coordination: RegistryCoordination
    sessions: SessionRuntime


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
    origin_conversation_key: str = ""
    actor_key: str = ""


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


def _trim_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _utc_now_iso() -> str:
    return utc_now_iso()


def _age_seconds(value: float | str | None, *, now: str | None = None) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return time.time() - float(value)
    try:
        ts = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    current = datetime.fromisoformat(now) if now else datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return (current - ts).total_seconds()


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
        follow_up_questions=(
            list(action.follow_up_questions) if action.follow_up_questions else list(task.follow_up_questions)
        ),
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
            origin_conversation_key=action.origin_conversation_key,
            actor_key=action.actor_key,
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
        next_parent_status = (
            parent_transition.new_state if parent_transition.ok else normalize_parent_status(pending.status)
        )
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
            ready_to_resume=(
                parent_transition.ready_to_resume
                if parent_transition.ok
                else delegation_ready_to_resume(updated_pending)
            ),
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


def build_delegation_plan(
    conversation_ref: str,
    title: str,
    resume_instruction: str,
    tasks: list[dict[str, str]],
    *,
    origin_conversation_key: str = "",
    actor_key: str = "",
    proposal_id: str = "",
) -> PendingDelegation:
    decision = decide_delegation_action(
        DelegationSnapshot(pending=None),
        ProposeDelegationAction(
            conversation_ref=conversation_ref,
            origin_conversation_key=origin_conversation_key,
            actor_key=actor_key,
            title=title,
            resume_instruction=resume_instruction,
            tasks=tuple(
                DelegationTaskDraft(
                    draft_id=str(task.get("draft_id") or task.get("routed_task_id") or ""),
                    selector=TargetSelector(
                        kind=str(task.get("selector_kind") or "agent"),
                        value=str(
                            task.get("selector_value")
                            or task.get("target_agent_id")
                            or task.get("target")
                            or ""
                        ),
                        preferred_agent_id=str(
                            task.get("target_agent_id") or task.get("target") or ""
                        ),
                    ),
                    authority_ref=str(task.get("authority_ref", "")),
                    title=str(task.get("title", "")),
                    instructions=str(task.get("instructions", "")),
                    priority=str(task.get("priority", "normal")),
                    requested_capabilities=list(task.get("requested_capabilities", []) or []),
                    context=dict(task.get("context", {}) or {}),
                )
                for task in tasks
            ),
        ),
    )
    pending = decision.effects.set_pending
    if pending is None:
        raise RuntimeError("Delegation plan creation did not produce pending state")
    pending.proposal_id = proposal_id
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


def expire_stale_delegations(
    pending: PendingDelegation | None,
    *,
    timeout_seconds: float,
) -> DelegationExpirationOutcome:
    if pending is None:
        return DelegationExpirationOutcome(status="no_delegation", pending=None)

    updated_pending = pending
    expired_kind = ""
    now = _utc_now_iso()
    delegation_age = _age_seconds(pending.created_at, now=now)
    completed_at = now
    expired = False
    for task in list(updated_pending.tasks):
        current_status = normalize_child_status(task.status)
        if current_status in CHILD_TERMINAL_STATUSES:
            continue
        if current_status == "proposed":
            if delegation_age is None or delegation_age <= timeout_seconds:
                continue
            summary = _DELEGATION_APPROVAL_EXPIRED_SUMMARY
            expired_kind = expired_kind or "approval_expired"
        else:
            task_age = _age_seconds(task.submitted_at or pending.created_at, now=now)
            if task_age is None or task_age <= timeout_seconds:
                continue
            summary = _DELEGATION_TIMEOUT_SUMMARY
            expired_kind = "result_timeout"
        decision = decide_delegation_action(
            DelegationSnapshot(pending=updated_pending),
            UpdateTaskStatusAction(
                routed_task_id=task.routed_task_id,
                authority_ref=task.authority_ref,
                status="failed",
                summary=summary,
                full_text=summary,
                completed_at=completed_at,
            ),
        )
        updated_pending = (
            decision.effects.set_pending
            if decision.effects.set_pending is not None
            else decision.pending
            if decision.pending is not None
            else updated_pending
        )
        expired = expired or decision.matched

    if not expired:
        return DelegationExpirationOutcome(status="not_expired", pending=pending)

    ready_to_resume = delegation_ready_to_resume(updated_pending)
    return DelegationExpirationOutcome(
        status="expired",
        pending=updated_pending,
        expired=True,
        expired_kind=expired_kind or "result_timeout",
        ready_to_resume=ready_to_resume,
        completion_message=(
            build_delegation_completion_message(updated_pending) if ready_to_resume else ""
        ),
    )


def mark_task_submitted(
    pending: PendingDelegation | None,
    *,
    routed_task_id: str,
    authority_ref: str = "",
) -> DelegationUpdateOutcome:
    decision = decide_delegation_action(
        DelegationSnapshot(pending=pending),
        UpdateTaskStatusAction(
            routed_task_id=routed_task_id,
            authority_ref=authority_ref,
            status="submitted",
            submitted_at=time.time(),
        ),
    )
    return DelegationUpdateOutcome(
        status=decision.status,
        pending=(
            decision.effects.set_pending if decision.effects.set_pending is not None else decision.pending
        ),
        matched=decision.matched,
        ready_to_resume=decision.ready_to_resume,
    )


def apply_routed_result(
    pending: PendingDelegation | None,
    *,
    routed_task_id: str,
    authority_ref: str = "",
    result: RoutedTaskResult,
) -> DelegationUpdateOutcome:
    decision = decide_delegation_action(
        DelegationSnapshot(pending=pending),
        UpdateTaskStatusAction(
            routed_task_id=routed_task_id,
            authority_ref=authority_ref,
            status=result.status or "completed",
            summary=result.summary,
            full_text=result.full_text,
            follow_up_questions=tuple(result.follow_up_questions),
            completed_at=result.completed_at,
        ),
    )
    updated_pending = (
        decision.effects.set_pending if decision.effects.set_pending is not None else decision.pending
    )
    resume_prompt = (
        build_resume_prompt(updated_pending)
        if decision.ready_to_resume and updated_pending is not None
        else ""
    )
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
        pending=(
            decision.effects.set_pending if decision.effects.set_pending is not None else decision.pending
        ),
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
        pending=(
            decision.effects.set_pending if decision.effects.set_pending is not None else decision.pending
        ),
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
            lines.append(f"   {_trim_text(detail.strip(), 180)}")
    if delegation.status == "partial_failed":
        lines.append("")
        lines.append("You can retry the failed tasks in a follow-on step if needed.")
    return "\n".join(lines).strip()


async def send_delegation_completion_message(
    delegation: PendingDelegation | None,
    send_text: Callable[[str], Awaitable[None]],
) -> None:
    message = build_delegation_completion_message(delegation)
    if not message:
        return
    await send_text(message)


def _load_session(runtime: ParticipantDelegationRuntime, conversation_key: str) -> SessionState:
    return runtime.sessions.load(
        conversation_key,
        provider_name=runtime.provider_name,
        provider_state_factory=runtime.provider_state_factory,
        approval_mode=runtime.config.approval_mode,
        default_role=runtime.config.role,
        default_skills=runtime.config.default_skills,
    )


def _save_session(
    runtime: ParticipantDelegationRuntime,
    conversation_key: str,
    session: SessionState,
) -> None:
    runtime.sessions.save(conversation_key, session)


async def _coordination_conversation_id(
    runtime: ParticipantDelegationRuntime,
    conversation_key: str,
    *,
    conversation_ref: str,
    origin_channel: str,
    external_ref: str,
    title: str,
) -> str:
    if conversation_ref.startswith("registry:"):
        return normalize_conversation_id(conversation_ref)
    return str(
        await runtime.coordination.ensure_conversation_id(
            conversation_key,
            conversation_ref=conversation_ref,
            origin_channel=origin_channel,
            external_ref=external_ref,
            title=title,
        )
    )


async def preview_participant_targets(
    runtime: ParticipantDelegationRuntime,
    pending: PendingDelegation | None,
    selectors: dict[str, TargetSelector],
) -> tuple[DelegationTargetPreview, ...]:
    previews: list[DelegationTargetPreview] = []
    for task in pending.tasks if pending is not None else ():
        selector = selectors.get(task.routed_task_id)
        if selector is None:
            previews.append(
                DelegationTargetPreview(
                    routed_task_id=task.routed_task_id,
                    status="missing_target",
                    detail="No target selector was specified for this task.",
                )
            )
            continue
        try:
            preview: TargetResolutionPreview = await runtime.coordination.preview_target_resolution(
                selector
            )
        except Exception:
            previews.append(
                DelegationTargetPreview(
                    routed_task_id=task.routed_task_id,
                    status="unavailable",
                    detail="Registry unavailable.",
                )
            )
            continue
        if preview.status == "resolved":
            previews.append(
                DelegationTargetPreview(
                    routed_task_id=task.routed_task_id,
                    status="resolved",
                    authority_ref=preview.authority_ref,
                )
            )
            continue
        if preview.status == "unavailable":
            previews.append(
                DelegationTargetPreview(
                    routed_task_id=task.routed_task_id,
                    status="unavailable",
                    detail=_registry_error_summary(preview.error or "registry_unreachable"),
                )
            )
            continue
        previews.append(
            DelegationTargetPreview(
                routed_task_id=task.routed_task_id,
                status="unresolved",
                detail=f"Could not resolve target {preview.target_label or selector.value}.",
            )
        )
    return tuple(previews)


async def submit_participant_direct_assignment(
    runtime: ParticipantDelegationRuntime,
    conversation_key: str,
    *,
    conversation_ref: str,
    selector: TargetSelector,
    title: str,
    instructions: str,
    message_text: str = "",
    origin_channel: str,
    external_ref: str,
    authorized_actor_key: str = "",
) -> CoordinationActionResult:
    validated_origin_transport_ref = validate_qualified_transport_ref(
        conversation_ref,
        field_name="origin_transport_ref",
    )
    coordination_external_ref = external_ref
    if conversation_ref and not conversation_ref.startswith("registry:"):
        coordination_external_ref = conversation_ref
    conversation_id = await _coordination_conversation_id(
        runtime,
        conversation_key,
        conversation_ref=conversation_ref,
        origin_channel=origin_channel,
        external_ref=coordination_external_ref,
        title=f"{origin_channel.title()} {external_ref}",
    )
    result = await runtime.coordination.direct_assign(
        conversation_id,
        selector=selector,
        title=title,
        instructions=instructions,
        origin_transport_ref=validated_origin_transport_ref,
        authorized_actor_key=authorized_actor_key,
        message_text=message_text,
    )
    if result.accepted and result.routed_tasks:
        pending = build_delegation_plan(
            conversation_id,
            title,
            "",
            [
                {
                    "draft_id": str(result.routed_tasks[0].routed_task_id or result.action_id or title),
                    "title": title,
                    "target_agent_id": (
                        str(result.routed_tasks[0].target_agent_id or "")
                        or selector.preferred_agent_id
                        or selector.value
                    ),
                    "target": (
                        str(result.routed_tasks[0].target_agent_id or "")
                        or selector.preferred_agent_id
                        or selector.value
                    ),
                    "selector_kind": selector.kind,
                    "selector_value": selector.value,
                    "instructions": instructions,
                }
            ],
            origin_conversation_key=conversation_key,
            actor_key=authorized_actor_key,
            proposal_id=result.action_id,
        )
        submitted = mark_task_submitted(
            pending,
            routed_task_id=str(result.routed_tasks[0].routed_task_id or ""),
            authority_ref=str(result.routed_tasks[0].authority_ref or ""),
        )
        session = _load_session(runtime, conversation_key)
        session.pending_delegation = submitted.pending or pending
        _save_session(runtime, conversation_key, session)
    return result


async def propose_participant_delegation(
    runtime: ParticipantDelegationRuntime,
    conversation_key: str,
    session: SessionState,
    *,
    conversation_ref: str,
    title: str,
    intent: DelegationIntent,
    origin_channel: str,
    external_ref: str,
    authorized_actor_key: str = "",
) -> ParticipantDelegationPlan:
    validated_origin_transport_ref = validate_qualified_transport_ref(
        conversation_ref,
        field_name="origin_transport_ref",
    )
    coordination_external_ref = external_ref
    if conversation_ref and not conversation_ref.startswith("registry:"):
        coordination_external_ref = conversation_ref
    conversation_id = await _coordination_conversation_id(
        runtime,
        conversation_key,
        conversation_ref=conversation_ref,
        origin_channel=origin_channel,
        external_ref=coordination_external_ref,
        title=title,
    )
    proposal_result = await runtime.coordination.delegate_tasks(
        conversation_id,
        intent=DelegationIntent(
            title=title,
            resume_instruction=intent.resume_instruction,
            origin_transport_ref=validated_origin_transport_ref,
            authorized_actor_key=authorized_actor_key,
            tasks=list(intent.tasks),
        ),
    )
    pending = build_delegation_plan(
        conversation_id,
        title,
        intent.resume_instruction,
        [
            {
                "draft_id": item.draft_id,
                "title": item.title,
                "target_agent_id": item.selector.preferred_agent_id,
                "target": item.selector.preferred_agent_id or item.selector.value,
                "selector_kind": item.selector.kind,
                "selector_value": item.selector.value,
                "instructions": item.instructions,
                "priority": item.priority,
                "requested_capabilities": list(item.requested_capabilities),
                "context": dict(item.context),
            }
            for item in intent.tasks
        ],
        origin_conversation_key=conversation_key,
        actor_key=authorized_actor_key,
        proposal_id=proposal_result.proposal_id or proposal_result.action_id,
    )
    previews = await preview_participant_targets(
        runtime,
        pending,
        {item.draft_id: item.selector for item in intent.tasks},
    )
    session.pending_delegation = pending
    _save_session(runtime, conversation_key, session)

    if runtime.config.autonomous and session.approval_mode != "on":
        try:
            approval_result = await runtime.coordination.approve_delegation(
                conversation_id,
                proposal_id=pending.proposal_id,
            )
        except Exception:
            session_after = _load_session(runtime, conversation_key)
            if session_after.pending_delegation is not None:
                cancelled = cancel_delegation(
                    session_after.pending_delegation,
                    conversation_ref=session_after.pending_delegation.conversation_ref,
                )
                session_after.pending_delegation = cancelled.pending
                _save_session(runtime, conversation_key, session_after)
            raise
        for index, task_ref in enumerate(approval_result.routed_tasks):
            if index >= len(pending.tasks):
                break
            pending.tasks[index].routed_task_id = task_ref.routed_task_id
            pending.tasks[index].target_agent_id = (
                task_ref.target_agent_id or pending.tasks[index].target_agent_id
            )
            pending.tasks[index].authority_ref = (
                task_ref.authority_ref or pending.tasks[index].authority_ref
            )
            submitted = mark_task_submitted(
                session.pending_delegation,
                routed_task_id=pending.tasks[index].routed_task_id,
                authority_ref=pending.tasks[index].authority_ref,
            )
            session.pending_delegation = submitted.pending
        _save_session(runtime, conversation_key, session)
        return ParticipantDelegationPlan(
            status="delegation_submitted",
            pending=session.pending_delegation,
            previews=previews,
            action_result=approval_result,
        )

    return ParticipantDelegationPlan(
        status="delegation_proposed",
        pending=pending,
        previews=previews,
        action_result=proposal_result,
    )


def _expired_delegation_message(expired_kind: str) -> str:
    if expired_kind == "approval_expired":
        return "Delegation plan expired before approval. Please ask me to delegate again."
    return (
        "Delegation timed out while waiting for delegated results. "
        "Please ask me to delegate again if you still need that work."
    )


async def approve_participant_delegation(
    runtime: ParticipantDelegationRuntime,
    conversation_key: str,
) -> DelegationCommandOutcome:
    session = _load_session(runtime, conversation_key)
    pending = session.pending_delegation
    if pending is None or not pending.proposal_id or not pending.conversation_ref:
        return DelegationCommandOutcome(status="nothing_to_approve", message="Nothing to approve.")
    expiration = expire_stale_delegations(
        pending,
        timeout_seconds=runtime.config.delegation_timeout_seconds,
    )
    if expiration.expired:
        session.pending_delegation = expiration.pending
        _save_session(runtime, conversation_key, session)
        return DelegationCommandOutcome(
            status="expired",
            message=_expired_delegation_message(expiration.expired_kind),
            pending=expiration.pending,
        )
    approval = prepare_delegation_approval(
        pending,
        conversation_ref=pending.conversation_ref,
    )
    if approval.status != "approve_ready":
        return DelegationCommandOutcome(status="nothing_to_approve", message="Nothing to approve.")
    try:
        result = await runtime.coordination.approve_delegation(
            normalize_conversation_id(pending.conversation_ref),
            proposal_id=pending.proposal_id,
        )
    except Exception as exc:
        error_code = str(exc)
        if error_code in {
            "registry_unreachable",
            "registry_timeout",
            "registry_request_failed",
            "no control plane",
        }:
            return DelegationCommandOutcome(
                status="approve_failed",
                message=(
                    "Delegation is unavailable because registry connectivity is degraded. "
                    f"The request was not sent. {_registry_error_summary(error_code)}"
                ),
                pending=pending,
            )
        return DelegationCommandOutcome(
            status="approve_failed",
            message=(
                "Delegation submission failed. "
                f"{_registry_error_summary(error_code)} Please try again after the registry recovers."
            ),
            pending=pending,
        )
    for index, task_ref in enumerate(result.routed_tasks):
        if index >= len(pending.tasks):
            break
        pending.tasks[index].routed_task_id = task_ref.routed_task_id
        pending.tasks[index].target_agent_id = (
            task_ref.target_agent_id or pending.tasks[index].target_agent_id
        )
        pending.tasks[index].authority_ref = (
            task_ref.authority_ref or pending.tasks[index].authority_ref
        )
        submitted = mark_task_submitted(
            session.pending_delegation,
            routed_task_id=pending.tasks[index].routed_task_id,
            authority_ref=pending.tasks[index].authority_ref,
        )
        session.pending_delegation = submitted.pending
    _save_session(runtime, conversation_key, session)
    return DelegationCommandOutcome(
        status="approved",
        message="Delegation approved. Specialist requests were sent.",
        pending=session.pending_delegation,
    )


async def cancel_participant_delegation(
    runtime: ParticipantDelegationRuntime,
    conversation_key: str,
) -> DelegationCommandOutcome:
    session = _load_session(runtime, conversation_key)
    pending = session.pending_delegation
    if pending is None:
        return DelegationCommandOutcome(status="nothing_to_cancel", message="Nothing to cancel.")
    if pending.proposal_id and pending.conversation_ref:
        try:
            await runtime.coordination.cancel_delegation(
                normalize_conversation_id(pending.conversation_ref),
                proposal_id=pending.proposal_id,
            )
        except Exception:
            return DelegationCommandOutcome(
                status="cancel_failed",
                message="Delegation could not be cancelled right now.",
                pending=pending,
            )
    session.pending_delegation = None
    _save_session(runtime, conversation_key, session)
    return DelegationCommandOutcome(
        status="cancelled",
        message="Delegation cancelled. No requests were sent.",
    )
