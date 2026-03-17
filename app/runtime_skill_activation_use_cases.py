"""Concern-owned use cases for session-backed runtime skill activation flows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.session_state import AwaitingSkillSetup, SessionState
from app.skill_lifecycle_service import get_skill_lifecycle_service
from app.runtime_skill_catalog_use_cases import get_runtime_skill_catalog_use_cases


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


class RuntimeSkillActivationUseCases:
    """Canonical activation flows shared by Telegram and registry."""

    def _lifecycle(self):
        return get_skill_lifecycle_service()

    def _catalog(self):
        return get_runtime_skill_catalog_use_cases()

    def list_conversation_skills(self, session: SessionState) -> ConversationSkillListing:
        active = tuple(self._lifecycle().list_active(session))
        details: list[ConversationSkillItem] = []
        for skill_name in active:
            summary = self._catalog().get_skill(skill_name)
            if summary is None:
                details.append(
                    ConversationSkillItem(
                        name=skill_name,
                        display_name=skill_name,
                        description="",
                        source_kind="unknown",
                        has_custom_override=False,
                    )
                )
                continue
            details.append(
                ConversationSkillItem(
                    name=summary.name,
                    display_name=summary.display_name,
                    description=summary.description,
                    source_kind=summary.source_kind,
                    has_custom_override=summary.has_custom_override,
                )
            )
        return ConversationSkillListing(active_skills=active, active_skill_details=tuple(details))

    def begin_activate(
        self,
        session: SessionState,
        *,
        user_id: str,
        skill_name: str,
        data_dir: Path,
        encryption_key: bytes,
        confirm: bool = False,
    ) -> ConversationSkillMutationOutcome:
        decision = self._lifecycle().begin_add(
            session,
            user_id=user_id,
            skill_name=skill_name,
            data_dir=data_dir,
            encryption_key=encryption_key,
        )
        if decision.status == "needs_confirmation" and confirm:
            decision = self._lifecycle().confirm_add(session, skill_name)
        return ConversationSkillMutationOutcome(
            status=decision.status,
            mutated=decision.mutated,
            first_requirement=decision.first_requirement,
            projected_size=decision.projected_size,
            prompt_size_threshold=decision.prompt_size_threshold,
            foreign_setup_user=decision.foreign_setup.user_id if decision.foreign_setup else "",
            foreign_setup=decision.foreign_setup,
        )

    def confirm_activate(self, session: SessionState, skill_name: str) -> ConversationSkillMutationOutcome:
        decision = self._lifecycle().confirm_add(session, skill_name)
        return ConversationSkillMutationOutcome(
            status=decision.status,
            mutated=decision.mutated,
            projected_size=decision.projected_size,
            prompt_size_threshold=decision.prompt_size_threshold,
        )

    def begin_setup(
        self,
        session: SessionState,
        *,
        user_id: str,
        skill_name: str,
    ) -> ConversationSkillMutationOutcome:
        decision = self._lifecycle().begin_setup(session, user_id=user_id, skill_name=skill_name)
        return ConversationSkillMutationOutcome(
            status=decision.status,
            mutated=decision.mutated,
            first_requirement=decision.first_requirement,
            foreign_setup_user=decision.foreign_setup.user_id if decision.foreign_setup else "",
            foreign_setup=decision.foreign_setup,
        )

    def deactivate(
        self,
        session: SessionState,
        *,
        user_id: str,
        skill_name: str,
    ) -> ConversationSkillMutationOutcome:
        decision = self._lifecycle().remove(session, user_id=user_id, skill_name=skill_name)
        return ConversationSkillMutationOutcome(
            status=decision.status,
            mutated=decision.mutated,
            foreign_setup_user=decision.foreign_setup.user_id if decision.foreign_setup else "",
            foreign_setup=decision.foreign_setup,
        )

    def clear(
        self,
        session: SessionState,
        *,
        user_id: str,
    ) -> ConversationSkillMutationOutcome:
        decision = self._lifecycle().clear(session, user_id=user_id)
        return ConversationSkillMutationOutcome(
            status=decision.status,
            mutated=decision.mutated,
            foreign_setup_user=decision.foreign_setup.user_id if decision.foreign_setup else "",
            foreign_setup=decision.foreign_setup,
        )


_USE_CASES = RuntimeSkillActivationUseCases()


def get_runtime_skill_activation_use_cases() -> RuntimeSkillActivationUseCases:
    return _USE_CASES
