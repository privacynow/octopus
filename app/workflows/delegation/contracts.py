"""Workflow-local contracts for delegation progression."""

from __future__ import annotations

from dataclasses import dataclass

from octopus_sdk.sessions import DelegatedTask, PendingDelegation


@dataclass(frozen=True)
class DelegationTaskDraft:
    routed_task_id: str
    authority_ref: str = ""
    title: str = ""
    target_agent_id: str = ""
    instructions: str = ""


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
