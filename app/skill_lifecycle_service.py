"""Shared lifecycle service for runtime skill activation and setup flows.

This service owns the skill-specific state transitions that were previously
spread across Telegram handlers and command helpers. Surfaces should call this
service and only handle rendering plus persistence.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.request_flow import (
    build_setup_state,
    foreign_skill_setup,
)
from app.session_state import AwaitingSkillSetup, SessionState
from app.skill_activation_service import get_skill_activation_service
from app.skill_catalog_service import get_skill_catalog_service
from app.provider_guidance_service import get_provider_guidance_service
from app.skills import (
    PROMPT_SIZE_WARNING_THRESHOLD,
    load_user_credentials,
)


@dataclass(frozen=True)
class SkillAddDecision:
    status: str
    mutated: bool = False
    foreign_setup: AwaitingSkillSetup | None = None
    setup_state: AwaitingSkillSetup | None = None
    first_requirement: dict[str, Any] | None = None
    projected_size: int = 0
    prompt_size_threshold: int = PROMPT_SIZE_WARNING_THRESHOLD


@dataclass(frozen=True)
class SkillSetupDecision:
    status: str
    mutated: bool = False
    foreign_setup: AwaitingSkillSetup | None = None
    setup_state: AwaitingSkillSetup | None = None
    first_requirement: dict[str, Any] | None = None


@dataclass(frozen=True)
class SkillRemoveDecision:
    status: str
    mutated: bool = False
    foreign_setup: AwaitingSkillSetup | None = None


@dataclass(frozen=True)
class SkillAdvanceDecision:
    status: str
    mutated: bool = False
    next_requirement: dict[str, Any] | None = None
    skill_name: str = ""


class SkillLifecycleService:
    """Shared lifecycle decisions for runtime skill flows."""

    def __init__(self) -> None:
        self._catalog = get_skill_catalog_service()
        self._activation = get_skill_activation_service()
        self._guidance = get_provider_guidance_service()

    def list_active(self, session: SessionState) -> list[str]:
        return self._activation.list_active(session)

    def _missing_requirements(
        self,
        skill_name: str,
        user_credentials: dict[str, dict[str, str]],
    ):
        requirements = self._catalog.requirements(skill_name)
        skill_creds = user_credentials.get(skill_name, {})
        return [item for item in requirements if item.key not in skill_creds]

    def begin_add(
        self,
        session: SessionState,
        *,
        user_id: str,
        skill_name: str,
        data_dir: Path,
        encryption_key: bytes,
    ) -> SkillAddDecision:
        if not self._catalog.has_skill(skill_name):
            return SkillAddDecision(status="unknown")

        active = self._activation.list_active(session)
        requirements = self._catalog.requirements(skill_name)
        if requirements:
            user_creds = load_user_credentials(data_dir, user_id, encryption_key)
            missing = self._missing_requirements(skill_name, user_creds)
            if missing:
                foreign = foreign_skill_setup(session, user_id)
                if foreign:
                    return SkillAddDecision(
                        status="foreign_setup",
                        foreign_setup=foreign,
                    )
                setup = build_setup_state(user_id, skill_name, missing)
                session.awaiting_skill_setup = setup
                return SkillAddDecision(
                    status="needs_setup",
                    mutated=True,
                    setup_state=setup,
                    first_requirement=setup.remaining[0] if setup.remaining else None,
                )

        if skill_name in active:
            return SkillAddDecision(status="already_active")

        projected_size, over = self._guidance.estimate_prompt_size(
            session.role,
            active,
            skill_name,
        )
        if over:
            return SkillAddDecision(
                status="needs_confirmation",
                projected_size=projected_size,
            )

        self._activation.activate(session, skill_name)
        return SkillAddDecision(status="activated", mutated=True)

    def confirm_add(self, session: SessionState, skill_name: str) -> SkillAddDecision:
        mutated = self._activation.activate(session, skill_name)
        return SkillAddDecision(
            status="activated" if mutated else "already_active",
            mutated=mutated,
        )

    def begin_setup(
        self,
        session: SessionState,
        *,
        user_id: str,
        skill_name: str,
    ) -> SkillSetupDecision:
        if not self._catalog.has_skill(skill_name):
            return SkillSetupDecision(status="unknown")
        requirements = self._catalog.requirements(skill_name)
        if not requirements:
            return SkillSetupDecision(status="no_requirements")
        foreign = foreign_skill_setup(session, user_id)
        if foreign:
            return SkillSetupDecision(status="foreign_setup", foreign_setup=foreign)
        setup = build_setup_state(user_id, skill_name, requirements)
        session.awaiting_skill_setup = setup
        return SkillSetupDecision(
            status="started",
            mutated=True,
            setup_state=setup,
            first_requirement=setup.remaining[0] if setup.remaining else None,
        )

    def remove(
        self,
        session: SessionState,
        *,
        user_id: str,
        skill_name: str,
    ) -> SkillRemoveDecision:
        had_setup = session.awaiting_skill_setup is not None
        foreign = foreign_skill_setup(session, user_id, skill_name=skill_name)
        if foreign:
            return SkillRemoveDecision(status="foreign_setup", foreign_setup=foreign)
        mutated = had_setup and session.awaiting_skill_setup is None
        removed = self._activation.deactivate(session, skill_name)
        setup = session.awaiting_skill_setup
        if setup and setup.skill == skill_name and setup.user_id == user_id:
            session.awaiting_skill_setup = None
            mutated = True
        mutated = mutated or removed
        if removed:
            return SkillRemoveDecision(status="removed", mutated=mutated)
        return SkillRemoveDecision(status="not_active", mutated=mutated)

    def clear(self, session: SessionState, *, user_id: str) -> SkillRemoveDecision:
        foreign = foreign_skill_setup(session, user_id)
        if foreign:
            return SkillRemoveDecision(status="foreign_setup", foreign_setup=foreign)
        mutated = bool(session.active_skills) or session.awaiting_skill_setup is not None
        self._activation.clear(session)
        session.awaiting_skill_setup = None
        return SkillRemoveDecision(status="cleared", mutated=mutated)

    def cancel_setup(
        self,
        session: SessionState,
        *,
        user_id: str,
        allow_override: bool = False,
    ) -> SkillRemoveDecision:
        setup = session.awaiting_skill_setup
        if not setup:
            return SkillRemoveDecision(status="no_setup")
        if setup.user_id != user_id and not allow_override:
            return SkillRemoveDecision(status="foreign_setup", foreign_setup=setup)
        session.awaiting_skill_setup = None
        return SkillRemoveDecision(status="cancelled", mutated=True)

    def complete_current_requirement(
        self,
        session: SessionState,
        *,
        user_id: str,
    ) -> SkillAdvanceDecision:
        setup = session.awaiting_skill_setup
        if not setup or setup.user_id != user_id or not setup.remaining:
            return SkillAdvanceDecision(status="no_setup")
        setup.remaining.pop(0)
        if setup.remaining:
            return SkillAdvanceDecision(
                status="next_requirement",
                mutated=True,
                next_requirement=setup.remaining[0],
                skill_name=setup.skill,
            )
        skill_name = setup.skill
        session.awaiting_skill_setup = None
        self._activation.activate(session, skill_name)
        return SkillAdvanceDecision(
            status="ready",
            mutated=True,
            skill_name=skill_name,
        )


_SERVICE = SkillLifecycleService()


def get_skill_lifecycle_service() -> SkillLifecycleService:
    return _SERVICE
