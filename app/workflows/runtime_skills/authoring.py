"""Runtime-skill authoring lifecycle workflows."""

from __future__ import annotations

from app.content_models import RuntimeSkillTrackRecord, SkillRevisionRecord
from app.content_store import get_content_store
from app.skill_catalog_service import get_skill_catalog_service
from app.workflows.lifecycle_machine import (
    LifecycleDecision,
    build_lifecycle_snapshot,
    decide_lifecycle_action,
)
from app.workflows.runtime_skills.contracts import (
    RuntimeSkillAuthoringPort,
    RuntimeSkillLifecycleApproval,
    RuntimeSkillLifecycleDetail,
    RuntimeSkillLifecycleMutation,
    RuntimeSkillLifecycleRevision,
)


class RuntimeSkillAuthoringUseCases(RuntimeSkillAuthoringPort):
    """Mutable custom runtime-skill lifecycle orchestration."""

    def _store(self):
        return get_content_store()

    def _catalog(self):
        return get_skill_catalog_service()

    def _mutable_track(self, skill_name: str) -> RuntimeSkillTrackRecord | None:
        track = self._catalog().resolve_track(skill_name)
        if track is None or track.source_kind != "custom" or not track.is_mutable:
            return None
        return track

    def _detail_from_track(self, track: RuntimeSkillTrackRecord) -> RuntimeSkillLifecycleDetail:
        revisions = tuple(
            RuntimeSkillLifecycleRevision(
                revision_id=item.revision_id,
                version_label=item.version_label,
                status=item.status,
                changelog=item.changelog,
                created_by=item.created_by,
                created_at=item.created_at,
                is_published=(item.revision_id == track.published_revision_id),
            )
            for item in self._store().list_skill_revisions(track.slug)
        )
        approvals = tuple(
            RuntimeSkillLifecycleApproval(
                revision_id=item.revision_id,
                action=item.action,
                actor=item.actor,
                note=item.note,
                created_at=item.created_at,
            )
            for item in self._store().list_skill_approvals(track.slug)
        )
        return RuntimeSkillLifecycleDetail(
            name=track.slug,
            display_name=track.display_name,
            description=track.description,
            visibility=track.visibility,
            body=track.revision.instruction_body,
            lifecycle_status=track.revision.status,
            active_revision_id=track.active_revision_id,
            published_revision_id=track.published_revision_id,
            runtime_available=bool(track.published_revision_id),
            revisions=revisions,
            approvals=approvals,
        )

    def _latest_action_for_revision(self, skill_name: str, revision_id: str) -> str:
        for item in self._store().list_skill_approvals(skill_name):
            if item.revision_id == revision_id:
                return item.action
        return ""

    def _lifecycle_snapshot(self, track: RuntimeSkillTrackRecord):
        return build_lifecycle_snapshot(
            track,
            self._latest_action_for_revision(track.slug, track.active_revision_id),
        )

    def _transition_message(self, skill_name: str, action: str, decision: LifecycleDecision, track: RuntimeSkillTrackRecord) -> str:
        if decision.status == "submitted":
            return f"Submitted '{skill_name}' for review."
        if decision.status == "already_submitted":
            return f"Skill '{skill_name}' is already submitted for review."
        if decision.status == "published":
            return f"Published '{skill_name}'."
        if decision.status == "already_published":
            return f"Skill '{skill_name}' is already published."
        if decision.status == "archived":
            return f"Archived '{skill_name}'."
        if decision.status == "already_archived":
            return f"Skill '{skill_name}' is already archived."
        if decision.status == "approval_required":
            return f"Skill '{skill_name}' must be approved before publishing."
        if action == "submit":
            return f"Cannot submit skill '{skill_name}' from state '{track.revision.status}'."
        if action == "publish":
            return f"Cannot publish skill '{skill_name}' from state '{track.revision.status}'."
        return f"Cannot {action} skill '{skill_name}' from state '{track.revision.status}'."

    def _apply_transition(
        self,
        track: RuntimeSkillTrackRecord,
        *,
        action: str,
        actor_key: str,
        note: str = "",
    ) -> RuntimeSkillLifecycleMutation:
        decision = decide_lifecycle_action(self._lifecycle_snapshot(track), action)
        if not decision.ok:
            return RuntimeSkillLifecycleMutation(
                status=decision.status,
                ok=False,
                message=self._transition_message(track.slug, action, decision, track),
                detail=self._detail_from_track(track),
            )
        effects = decision.effects
        if effects.set_status is not None or effects.published_pointer != "unchanged" or effects.approval_action is not None:
            self._store().apply_skill_lifecycle_transition(
                track.slug,
                track.active_revision_id,
                set_status=effects.set_status,
                published_pointer=effects.published_pointer,
                approval_action=effects.approval_action,
                actor=actor_key,
                note=note,
            )
        detail = self.detail(track.slug)
        return RuntimeSkillLifecycleMutation(
            status=decision.status,
            ok=detail is not None,
            message=self._transition_message(track.slug, action, decision, track),
            detail=detail,
        )

    def detail(self, skill_name: str) -> RuntimeSkillLifecycleDetail | None:
        track = self._mutable_track(skill_name)
        if track is None:
            return None
        return self._detail_from_track(track)

    def create_draft(self, skill_name: str, *, owner_actor: str = "") -> RuntimeSkillLifecycleMutation:
        try:
            self._catalog().create_custom_draft(skill_name, owner_actor=owner_actor)
        except ValueError as exc:
            return RuntimeSkillLifecycleMutation(status="invalid", ok=False, message=str(exc))
        detail = self.detail(skill_name)
        return RuntimeSkillLifecycleMutation(
            status="created",
            ok=detail is not None,
            message=f"Created draft skill '{skill_name}'.",
            detail=detail,
        )

    def edit_draft(
        self,
        skill_name: str,
        *,
        actor_key: str,
        body: str,
        description: str | None = None,
        changelog: str = "",
    ) -> RuntimeSkillLifecycleMutation:
        track = self._mutable_track(skill_name)
        if track is None:
            return RuntimeSkillLifecycleMutation(
                status="missing",
                ok=False,
                message=f"Custom skill '{skill_name}' not found.",
            )
        text = body.strip()
        if not text:
            return RuntimeSkillLifecycleMutation(
                status="invalid",
                ok=False,
                message="Draft body cannot be empty.",
            )
        updated = RuntimeSkillTrackRecord(
            slug=track.slug,
            display_name=track.display_name,
            description=track.description if description is None else description,
            source_kind=track.source_kind,
            revision=SkillRevisionRecord(
                instruction_body=text,
                requirements=list(track.revision.requirements),
                provider_config=dict(track.revision.provider_config),
                files=track.revision.files,
                version_label="draft",
                changelog=changelog,
                created_by=actor_key,
                status="draft",
            ),
            source_uri=track.source_uri,
            owner_actor=track.owner_actor,
            visibility=track.visibility,
            is_mutable=track.is_mutable,
            archived=False,
            published_revision_id=track.published_revision_id,
        )
        self._store().upsert_skill_draft(updated)
        detail = self.detail(skill_name)
        return RuntimeSkillLifecycleMutation(
            status="draft_saved",
            ok=detail is not None,
            message=f"Saved draft for '{skill_name}'.",
            detail=detail,
        )

    def submit(self, skill_name: str, *, actor_key: str, note: str = "") -> RuntimeSkillLifecycleMutation:
        track = self._mutable_track(skill_name)
        if track is None:
            return RuntimeSkillLifecycleMutation(status="missing", ok=False, message=f"Custom skill '{skill_name}' not found.")
        return self._apply_transition(track, action="submit", actor_key=actor_key, note=note)

    def publish(self, skill_name: str, *, actor_key: str, note: str = "") -> RuntimeSkillLifecycleMutation:
        track = self._mutable_track(skill_name)
        if track is None:
            return RuntimeSkillLifecycleMutation(status="missing", ok=False, message=f"Custom skill '{skill_name}' not found.")
        return self._apply_transition(track, action="publish", actor_key=actor_key, note=note)

    def archive(self, skill_name: str, *, actor_key: str, note: str = "") -> RuntimeSkillLifecycleMutation:
        track = self._mutable_track(skill_name)
        if track is None:
            return RuntimeSkillLifecycleMutation(status="missing", ok=False, message=f"Custom skill '{skill_name}' not found.")
        return self._apply_transition(track, action="archive", actor_key=actor_key, note=note)


_USE_CASES = RuntimeSkillAuthoringUseCases()


def get_runtime_skill_authoring_use_cases() -> RuntimeSkillAuthoringUseCases:
    return _USE_CASES
