"""Session-backed activation service for runtime skills.

This keeps activation ownership in session state while giving handlers and UI
surfaces a shared seam instead of mutating ``session.active_skills`` directly.
"""

from __future__ import annotations

from app.session_state import SessionState
from app.skill_catalog_service import get_skill_catalog_service


class SkillActivationService:
    """Session-state backed runtime skill activation service."""

    def normalize(self, session: SessionState) -> list[str]:
        catalog = get_skill_catalog_service()
        active = list(session.active_skills)
        kept = catalog.filter_resolvable(active)
        if kept == active:
            return []
        pruned = [name for name in active if name not in kept]
        session.active_skills = kept
        return pruned

    def list_active(self, session: SessionState) -> list[str]:
        return list(session.active_skills)

    def activate(self, session: SessionState, skill_name: str) -> bool:
        if skill_name in session.active_skills:
            return False
        session.active_skills.append(skill_name)
        return True

    def deactivate(self, session: SessionState, skill_name: str) -> bool:
        if skill_name not in session.active_skills:
            return False
        session.active_skills.remove(skill_name)
        return True

    def clear(self, session: SessionState) -> None:
        session.active_skills = []


_SERVICE = SkillActivationService()


def get_skill_activation_service() -> SkillActivationService:
    return _SERVICE
