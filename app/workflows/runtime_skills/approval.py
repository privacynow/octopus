"""Runtime-skill approval lifecycle workflows."""

from __future__ import annotations

from app.content_store import get_content_store
from app.skill_catalog_service import get_skill_catalog_service
from app.workflows.runtime_skills.authoring import get_runtime_skill_authoring_use_cases
from app.workflows.runtime_skills.contracts import (
    RuntimeSkillApprovalPort,
    RuntimeSkillLifecycleMutation,
)


class RuntimeSkillApprovalUseCases(RuntimeSkillApprovalPort):
    """Approval actions for mutable custom runtime skills."""

    def _store(self):
        return get_content_store()

    def _catalog(self):
        return get_skill_catalog_service()

    def _authoring(self):
        return get_runtime_skill_authoring_use_cases()

    def _validate_review_track(self, skill_name: str) -> RuntimeSkillLifecycleMutation | None:
        track = self._catalog().resolve_track(skill_name)
        if track is None or track.source_kind != "custom" or not track.is_mutable:
            return RuntimeSkillLifecycleMutation(
                status="missing",
                ok=False,
                message=f"Custom skill '{skill_name}' not found.",
            )
        if track.revision.status != "review":
            return RuntimeSkillLifecycleMutation(
                status="invalid_state",
                ok=False,
                message=f"Skill '{skill_name}' is not awaiting review.",
                detail=self._authoring().detail(skill_name),
            )
        return None

    def approve(self, skill_name: str, *, actor_key: str, note: str = "") -> RuntimeSkillLifecycleMutation:
        error = self._validate_review_track(skill_name)
        if error is not None:
            return error
        track = self._catalog().resolve_track(skill_name)
        assert track is not None
        self._store().append_skill_approval(
            skill_name,
            track.active_revision_id,
            action="approved",
            actor=actor_key,
            note=note,
        )
        detail = self._authoring().detail(skill_name)
        return RuntimeSkillLifecycleMutation(
            status="approved",
            ok=detail is not None,
            message=f"Approved '{skill_name}'.",
            detail=detail,
        )

    def reject(self, skill_name: str, *, actor_key: str, note: str = "") -> RuntimeSkillLifecycleMutation:
        error = self._validate_review_track(skill_name)
        if error is not None:
            return error
        track = self._catalog().resolve_track(skill_name)
        assert track is not None
        self._store().set_skill_revision_status(skill_name, track.active_revision_id, "draft")
        self._store().append_skill_approval(
            skill_name,
            track.active_revision_id,
            action="rejected",
            actor=actor_key,
            note=note,
        )
        detail = self._authoring().detail(skill_name)
        return RuntimeSkillLifecycleMutation(
            status="rejected",
            ok=detail is not None,
            message=f"Rejected '{skill_name}'. Back to draft.",
            detail=detail,
        )


_USE_CASES = RuntimeSkillApprovalUseCases()


def get_runtime_skill_approval_use_cases() -> RuntimeSkillApprovalUseCases:
    return _USE_CASES
