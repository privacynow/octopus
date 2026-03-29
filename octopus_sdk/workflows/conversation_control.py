"""SDK-owned conversation control workflows."""

from __future__ import annotations

from pathlib import Path

from octopus_sdk.messages import MessageTemplatePort
from octopus_sdk.sessions import SessionState, default_session, session_from_dict
from octopus_sdk.work_queue import CancelRequestResult, WorkQueuePort
from octopus_sdk.workflows.conversation import (
    ConversationCancelOutcome,
    ConversationControlPort,
    ConversationResetOutcome,
    ProviderStateFactory,
)
from octopus_sdk.workflows.skills import RuntimeSkillSetupPort


class ConversationControlUseCases(ConversationControlPort):
    """Canonical conversation-level control flows shared by channels."""

    def __init__(
        self,
        *,
        messages: MessageTemplatePort,
        setup: RuntimeSkillSetupPort,
        work_queue: WorkQueuePort,
    ) -> None:
        self._messages = messages
        self._setup = setup
        self._work_queue = work_queue

    def reset_session(
        self,
        session: SessionState,
        *,
        actor_key: str,
        provider_name: str,
        provider_state_factory: ProviderStateFactory,
        approval_mode_default: str,
        default_role: str,
        default_skills: tuple[str, ...],
        conversation_key: str,
    ) -> ConversationResetOutcome:
        foreign = self._setup.foreign_setup(session, actor_key=actor_key)
        if foreign.setup is not None:
            return ConversationResetOutcome(status="foreign_setup", message="")
        approval_mode = session.approval_mode if session.approval_mode_explicit else approval_mode_default
        replacement = session_from_dict(
            default_session(
                provider_name,
                provider_state_factory(conversation_key),
                approval_mode,
                default_role,
                default_skills,
            )
        )
        if session.approval_mode_explicit:
            replacement.approval_mode_explicit = True
        return ConversationResetOutcome(
            status="reset",
            message=f"Fresh {provider_name} conversation started.",
            replacement_session=replacement,
            cleanup_scripts=True,
        )

    def cancel_conversation(
        self,
        session: SessionState,
        *,
        data_dir: Path,
        conversation_key: str,
        actor_key: str,
        live_cancel_event=None,
        cancel_request_event_id: str = "",
        allow_override: bool = False,
    ) -> ConversationCancelOutcome:
        local_live_cancel = live_cancel_event is not None
        if live_cancel_event is not None:
            live_cancel_event.set()
        result = self._work_queue.request_cancel(
            data_dir,
            conversation_key,
            actor_key,
            cancel_request_event_id=cancel_request_event_id,
        )
        if result == CancelRequestResult.claimed_cancel_requested or local_live_cancel:
            return ConversationCancelOutcome(status="live_cancel_requested", message=self._messages.cancel_live_requested())
        if result == CancelRequestResult.queued_cancelled:
            return ConversationCancelOutcome(status="queued_cancelled", message=self._messages.cancel_queued_superseded())
        decision = self._setup.cancel(session, actor_key=actor_key, allow_override=allow_override)
        if decision.status == "cancelled":
            return ConversationCancelOutcome(
                status="setup_cancelled",
                mutated=True,
                message=self._messages.credential_setup_cancelled(),
            )
        if decision.status == "foreign_setup":
            return ConversationCancelOutcome(
                status="setup_foreign",
                message=self._messages.credential_setup_another_user_in_progress(),
            )
        if session.has_pending:
            session.clear_pending()
            return ConversationCancelOutcome(
                status="pending_cancelled",
                mutated=True,
                message=self._messages.cancel_pending_request(),
            )
        return ConversationCancelOutcome(
            status="nothing_to_cancel",
            message=self._messages.nothing_to_cancel(),
        )
