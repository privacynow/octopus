"""Runtime-skill approval lifecycle workflows."""

from __future__ import annotations

from app.content_store import get_content_store
from app.skill_catalog_service import get_skill_catalog_service
from app.workflows.lifecycle_machine import (
    LifecycleDecision,
    build_lifecycle_snapshot,
    decide_lifecycle_action,
)
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

    def _review_track(self, skill_name: str):
        track = self._catalog().resolve_track(skill_name)
        if track is None or track.source_kind != "custom" or not track.is_mutable:
            return None
        return track

    def _lifecycle_snapshot(self, track):
        return build_lifecycle_snapshot(
            track,
            self._authoring()._latest_action_for_revision(track.slug, track.active_revision_id),
        )

    def _transition_message(self, skill_name: str, action: str, decision: LifecycleDecision) -> str:
        if decision.status == "approved":
            return f"Approved '{skill_name}'."
        if decision.status == "already_approved":
            return f"Skill '{skill_name}' is already approved."
        if decision.status == "rejected":
            return f"Rejected '{skill_name}'. Back to draft."
        if decision.status == "already_rejected":
            return f"Skill '{skill_name}' is already back in draft after rejection."
        return f"Skill '{skill_name}' is not awaiting review."

    def approve(self, skill_name: str, *, actor_key: str, note: str = "") -> RuntimeSkillLifecycleMutation:
        track = self._review_track(skill_name)
        if track is None:
            return RuntimeSkillLifecycleMutation(
                status="missing",
                ok=False,
                message=f"Custom skill '{skill_name}' not found.",
            )
        decision = decide_lifecycle_action(self._lifecycle_snapshot(track), "approve")
        if not decision.ok:
            return RuntimeSkillLifecycleMutation(
                status=decision.status,
                ok=False,
                message=self._transition_message(skill_name, "approve", decision),
                detail=self._authoring().detail(skill_name),
            )
        effects = decision.effects
        if effects.set_status is not None or effects.published_pointer != "unchanged" or effects.approval_action is not None:
            self._store().apply_skill_lifecycle_transition(
                skill_name,
                track.active_revision_id,
                set_status=effects.set_status,
                published_pointer=effects.published_pointer,
                approval_action=effects.approval_action,
                actor=actor_key,
                note=note,
            )
        detail = self._authoring().detail(skill_name)
        return RuntimeSkillLifecycleMutation(
            status=decision.status,
            ok=detail is not None,
            message=self._transition_message(skill_name, "approve", decision),
            detail=detail,
        )

    def reject(self, skill_name: str, *, actor_key: str, note: str = "") -> RuntimeSkillLifecycleMutation:
        track = self._review_track(skill_name)
        if track is None:
            return RuntimeSkillLifecycleMutation(
                status="missing",
                ok=False,
                message=f"Custom skill '{skill_name}' not found.",
            )
        decision = decide_lifecycle_action(self._lifecycle_snapshot(track), "reject")
        if not decision.ok:
            return RuntimeSkillLifecycleMutation(
                status=decision.status,
                ok=False,
                message=self._transition_message(skill_name, "reject", decision),
                detail=self._authoring().detail(skill_name),
            )
        effects = decision.effects
        if effects.set_status is not None or effects.published_pointer != "unchanged" or effects.approval_action is not None:
            self._store().apply_skill_lifecycle_transition(
                skill_name,
                track.active_revision_id,
                set_status=effects.set_status,
                published_pointer=effects.published_pointer,
                approval_action=effects.approval_action,
                actor=actor_key,
                note=note,
            )
        detail = self._authoring().detail(skill_name)
        return RuntimeSkillLifecycleMutation(
            status=decision.status,
            ok=detail is not None,
            message=self._transition_message(skill_name, "reject", decision),
            detail=detail,
        )


_USE_CASES = RuntimeSkillApprovalUseCases()


def get_runtime_skill_approval_use_cases() -> RuntimeSkillApprovalUseCases:
    return _USE_CASES
