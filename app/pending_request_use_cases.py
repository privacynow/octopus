"""Concern-owned use cases for pending approval and retry workflows."""

from __future__ import annotations

from dataclasses import dataclass

from app import user_messages as _msg
from app.config import BotConfig
from app.request_flow import classify_pending_validation, extra_dirs_from_denials, validate_pending
from app.session_state import PendingApproval, PendingRetry, SessionState
from app.workflows.pending_request import (
    PendingRequestDisposition,
    PendingRequestWorkflowModel,
    run_pending_request_event,
)


@dataclass(frozen=True)
class PendingExecutionPlan:
    prompt: str
    image_paths: tuple[str, ...]
    request_user_id: str
    trust_tier: str
    extra_dirs: tuple[str, ...]


@dataclass(frozen=True)
class PendingRequestOutcome:
    status: str
    mutated: bool = False
    message: str = ""
    execution_plan: PendingExecutionPlan | None = None


class PendingRequestUseCases:
    """Canonical pending approval/retry flows shared by surfaces."""

    def _invalid_result(
        self,
        session: SessionState,
        pending: PendingApproval | PendingRetry,
        *,
        cfg: BotConfig,
        provider_name: str,
    ) -> PendingRequestOutcome:
        session.clear_pending()
        return PendingRequestOutcome(
            status="invalid",
            mutated=True,
            message=validate_pending(pending, session, cfg, provider_name) or _msg.approval_request_no_longer_valid(),
        )

    def approve(
        self,
        session: SessionState,
        *,
        cfg: BotConfig,
        provider_name: str,
    ) -> PendingRequestOutcome:
        pending = session.pending_approval or session.pending_retry
        if not pending:
            return PendingRequestOutcome(
                status="no_pending",
                message=_msg.approval_no_pending_approve(),
            )
        state = "pending_approval" if session.pending_approval else "pending_retry"
        classification = classify_pending_validation(pending, session, cfg, provider_name)
        event_name = (
            "approve_execute" if classification == "ok"
            else "expire" if classification == "expired"
            else "invalidate_stale"
        )
        model = PendingRequestWorkflowModel(state=state, validation_result=classification)
        result = run_pending_request_event(model, event_name, validation_result=classification)
        if not result.allowed or result.disposition != PendingRequestDisposition.executed:
            return self._invalid_result(session, pending, cfg=cfg, provider_name=provider_name)
        denials = getattr(pending, "denials", None) or []
        plan = PendingExecutionPlan(
            prompt=pending.prompt,
            image_paths=tuple(pending.image_paths),
            request_user_id=pending.request_user_id,
            trust_tier=getattr(pending, "trust_tier", "trusted"),
            extra_dirs=tuple(extra_dirs_from_denials(denials) if denials else ()),
        )
        session.clear_pending()
        return PendingRequestOutcome(
            status="execute",
            mutated=True,
            execution_plan=plan,
        )

    def reject(self, session: SessionState) -> PendingRequestOutcome:
        if not session.has_pending:
            return PendingRequestOutcome(
                status="no_pending",
                message=_msg.approval_no_pending_reject(),
            )
        state = "pending_approval" if session.pending_approval else "pending_retry"
        model = PendingRequestWorkflowModel(state=state)
        run_pending_request_event(model, "reject")
        session.clear_pending()
        return PendingRequestOutcome(
            status="rejected",
            mutated=True,
            message=_msg.approval_rejected(),
        )

    def retry_skip(self, session: SessionState) -> PendingRequestOutcome:
        session.clear_pending()
        return PendingRequestOutcome(
            status="skipped",
            mutated=True,
            message=_msg.retry_skip_confirmation(),
        )

    def retry_allow(
        self,
        session: SessionState,
        *,
        cfg: BotConfig,
        provider_name: str,
    ) -> PendingRequestOutcome:
        pending = session.pending_retry
        if not pending:
            return PendingRequestOutcome(
                status="no_pending",
                message=_msg.retry_nothing_pending(),
            )
        classification = classify_pending_validation(pending, session, cfg, provider_name)
        event_name = (
            "approve_execute" if classification == "ok"
            else "expire" if classification == "expired"
            else "invalidate_stale"
        )
        model = PendingRequestWorkflowModel(state="pending_retry", validation_result=classification)
        result = run_pending_request_event(model, event_name, validation_result=classification)
        if not result.allowed or result.disposition != PendingRequestDisposition.executed:
            return self._invalid_result(session, pending, cfg=cfg, provider_name=provider_name)
        denial_dirs = tuple(extra_dirs_from_denials(pending.denials or []))
        if denial_dirs and provider_name == "codex":
            session.provider_state["thread_id"] = None
        plan = PendingExecutionPlan(
            prompt=pending.prompt,
            image_paths=tuple(pending.image_paths),
            request_user_id=pending.request_user_id,
            trust_tier=getattr(pending, "trust_tier", "trusted"),
            extra_dirs=denial_dirs,
        )
        session.clear_pending()
        return PendingRequestOutcome(
            status="execute",
            mutated=True,
            execution_plan=plan,
        )


_USE_CASES = PendingRequestUseCases()


def get_pending_request_use_cases() -> PendingRequestUseCases:
    return _USE_CASES
