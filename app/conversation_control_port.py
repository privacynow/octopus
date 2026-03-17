"""Contracts for conversation control workflows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from app.session_state import SessionState

ProviderStateFactory = Callable[[], dict]


@dataclass(frozen=True)
class ConversationResetOutcome:
    status: str
    message: str = ""
    replacement_session: SessionState | None = None
    cleanup_scripts: bool = False


@dataclass(frozen=True)
class ConversationCancelOutcome:
    status: str
    mutated: bool = False
    message: str = ""


class ConversationControlPort(Protocol):
    def reset_session(
        self,
        session: SessionState,
        *,
        user_id: str,
        provider_name: str,
        provider_state_factory: ProviderStateFactory,
        approval_mode_default: str,
        default_role: str,
        default_skills: tuple[str, ...],
    ) -> ConversationResetOutcome: ...

    def cancel_conversation(
        self,
        session: SessionState,
        *,
        data_dir: Path,
        conversation_key: str,
        actor_key: str,
        live_cancel_event: Any = None,
        cancel_request_event_id: str = "",
        allow_override: bool = False,
    ) -> ConversationCancelOutcome: ...
