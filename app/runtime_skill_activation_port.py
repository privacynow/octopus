"""Contracts for session-backed runtime skill activation workflows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from app.session_state import AwaitingSkillSetup, SessionState


@dataclass(frozen=True)
class ConversationSkillItem:
    name: str
    display_name: str
    description: str
    source_kind: str
    has_custom_override: bool


@dataclass(frozen=True)
class ConversationSkillListing:
    active_skills: tuple[str, ...]
    active_skill_details: tuple[ConversationSkillItem, ...]


@dataclass(frozen=True)
class ConversationSkillMutationOutcome:
    status: str
    mutated: bool = False
    first_requirement: dict[str, Any] | None = None
    projected_size: int = 0
    prompt_size_threshold: int = 0
    foreign_setup_user: str = ""
    foreign_setup: AwaitingSkillSetup | None = None


class RuntimeSkillActivationPort(Protocol):
    def list_conversation_skills(self, active_skills: list[str]) -> ConversationSkillListing: ...

    def begin_activate(
        self,
        session: SessionState,
        *,
        user_id: str,
        skill_name: str,
        confirm: bool = False,
    ) -> ConversationSkillMutationOutcome: ...

    def confirm_activate(
        self,
        session: SessionState,
        skill_name: str,
    ) -> ConversationSkillMutationOutcome: ...

    def begin_setup(
        self,
        session: SessionState,
        *,
        user_id: str,
        skill_name: str,
    ) -> ConversationSkillMutationOutcome: ...

    def deactivate(
        self,
        session: SessionState,
        *,
        user_id: str,
        skill_name: str,
    ) -> ConversationSkillMutationOutcome: ...

    def clear(
        self,
        session: SessionState,
        *,
        user_id: str,
    ) -> ConversationSkillMutationOutcome: ...
