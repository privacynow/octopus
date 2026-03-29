"""SDK-owned pending request workflows."""

from __future__ import annotations

from octopus_sdk.config import BotConfigBase
from octopus_sdk.messages import MessageTemplatePort
from octopus_sdk.request_flow import classify_pending_validation, extra_dirs_from_denials, validate_pending
from octopus_sdk.sessions import PendingApproval, PendingRetry, SessionState
from octopus_sdk.workflows.pending import (
    PendingExecutionPlan,
    PendingRequestOutcome,
    PendingRequestPort,
)
from octopus_sdk.workflows.pending_machine import (
    PendingRequestDisposition,
    PendingRequestWorkflowModel,
    run_pending_request_event,
)
from octopus_sdk.workflows.skills import RuntimeSkillCatalogPort


class PendingRequestUseCases(PendingRequestPort):
    """Canonical pending approval/retry flows shared by channels."""

    def __init__(
        self,
        *,
        messages: MessageTemplatePort,
        catalog: RuntimeSkillCatalogPort,
    ) -> None:
        self._messages = messages
        self._catalog = catalog

    def _invalid_result(
        self,
        session: SessionState,
        pending: PendingApproval | PendingRetry,
        *,
        cfg: BotConfigBase,
        provider_name: str,
    ) -> PendingRequestOutcome:
        session.clear_pending()
        return PendingRequestOutcome(
            status="invalid",
            mutated=True,
            message=(
                validate_pending(
                    pending,
                    session,
                    cfg,
                    provider_name,
                    catalog=self._catalog,
                )
                or self._messages.approval_request_no_longer_valid()
            ),
        )

    def approve(
        self,
        session: SessionState,
        *,
        cfg: BotConfigBase,
        provider_name: str,
    ) -> PendingRequestOutcome:
        pending = session.pending_approval or session.pending_retry
        if not pending:
            return PendingRequestOutcome(
                status="no_pending",
                message=self._messages.approval_no_pending_approve(),
            )
        state = "pending_approval" if session.pending_approval else "pending_retry"
        classification = classify_pending_validation(
            pending,
            session,
            cfg,
            provider_name,
            catalog=self._catalog,
        )
        event_name = (
            "approve_execute"
            if classification == "ok"
            else "expire" if classification == "expired" else "invalidate_stale"
        )
        model = PendingRequestWorkflowModel(state=state, validation_result=classification)
        result = run_pending_request_event(model, event_name, validation_result=classification)
        if not result.allowed or result.disposition != PendingRequestDisposition.executed:
            return self._invalid_result(session, pending, cfg=cfg, provider_name=provider_name)
        execution_plan = self._execution_plan_for_pending(pending)
        self._reset_provider_retry_state(
            session,
            provider_name=provider_name,
            pending=pending,
        )
        session.clear_pending()
        return PendingRequestOutcome(
            status="approved",
            mutated=True,
            execution_plan=execution_plan,
        )

    def _execution_plan_for_pending(
        self,
        pending: PendingApproval | PendingRetry,
    ) -> PendingExecutionPlan:
        denials = getattr(pending, "denials", None) or []
        return PendingExecutionPlan(
            prompt=pending.prompt,
            image_paths=tuple(pending.image_paths),
            actor_key=pending.actor_key,
            trust_tier=pending.trust_tier,
            extra_dirs=tuple(extra_dirs_from_denials(denials)),
        )

    def _reset_provider_retry_state(
        self,
        session: SessionState,
        *,
        provider_name: str,
        pending: PendingApproval | PendingRetry,
    ) -> None:
        if provider_name != "codex":
            return
        if not isinstance(pending, PendingRetry):
            return
        session.provider_state["thread_id"] = None

    def retry_allow(
        self,
        session: SessionState,
        *,
        cfg: BotConfigBase,
        provider_name: str,
    ) -> PendingRequestOutcome:
        pending = session.pending_retry
        if pending is None:
            return PendingRequestOutcome(
                status="no_retry",
                message=self._messages.retry_nothing_pending(),
            )
        classification = classify_pending_validation(
            pending,
            session,
            cfg,
            provider_name,
            catalog=self._catalog,
        )
        model = PendingRequestWorkflowModel(state="pending_retry", validation_result=classification)
        result = run_pending_request_event(
            model,
            "approve_execute" if classification == "ok" else "expire" if classification == "expired" else "invalidate_stale",
            validation_result=classification,
        )
        if not result.allowed or result.disposition != PendingRequestDisposition.executed:
            return self._invalid_result(session, pending, cfg=cfg, provider_name=provider_name)
        execution_plan = self._execution_plan_for_pending(pending)
        self._reset_provider_retry_state(
            session,
            provider_name=provider_name,
            pending=pending,
        )
        session.clear_pending()
        return PendingRequestOutcome(
            status="approved",
            mutated=True,
            execution_plan=execution_plan,
        )

    def reject(self, session: SessionState) -> PendingRequestOutcome:
        pending = session.pending_approval or session.pending_retry
        if not pending:
            return PendingRequestOutcome(
                status="no_pending",
                message=self._messages.approval_no_pending_reject(),
            )
        state = "pending_approval" if session.pending_approval else "pending_retry"
        model = PendingRequestWorkflowModel(state=state)
        result = run_pending_request_event(model, "reject")
        session.clear_pending()
        return PendingRequestOutcome(
            status="rejected" if result.allowed else "invalid",
            mutated=True,
            message=self._messages.approval_rejected(),
        )

    def retry_skip(self, session: SessionState) -> PendingRequestOutcome:
        if not session.pending_retry:
            return PendingRequestOutcome(
                status="no_retry",
                message=self._messages.retry_nothing_pending(),
            )
        model = PendingRequestWorkflowModel(state="pending_retry")
        result = run_pending_request_event(model, "reject")
        session.clear_pending()
        return PendingRequestOutcome(
            status="skipped" if result.allowed else "invalid",
            mutated=True,
            message=self._messages.retry_skip_confirmation(),
        )
