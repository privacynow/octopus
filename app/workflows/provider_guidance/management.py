"""Provider-guidance lifecycle management workflows."""

from __future__ import annotations

from app.content_models import ProviderGuidanceRevisionRecord, ProviderGuidanceTrackRecord
from app.content_store import get_content_store
from app.workflows.lifecycle_machine import LifecycleDecision, LifecycleSnapshot, decide_lifecycle_action
from app.workflows.provider_guidance.contracts import (
    ProviderGuidanceLifecycleApproval,
    ProviderGuidanceLifecycleDetail,
    ProviderGuidanceLifecycleMutation,
    ProviderGuidanceLifecycleRevision,
    ProviderGuidanceManagementPort,
)


class ProviderGuidanceManagementUseCases(ProviderGuidanceManagementPort):
    """Lifecycle management for mutable provider-guidance tracks."""

    def _store(self):
        return get_content_store()

    def _track(self, provider_name: str, *, scope_kind: str, scope_key: str) -> ProviderGuidanceTrackRecord | None:
        return self._store().get_provider_guidance(provider_name, scope_kind=scope_kind, scope_key=scope_key)

    def _detail_from_track(self, track: ProviderGuidanceTrackRecord) -> ProviderGuidanceLifecycleDetail:
        revisions = tuple(
            ProviderGuidanceLifecycleRevision(
                revision_id=item.revision_id,
                status=item.status,
                created_by=item.created_by,
                created_at=item.created_at,
                is_published=(item.revision_id == track.published_revision_id),
            )
            for item in self._store().list_provider_guidance_revisions(
                track.provider,
                scope_kind=track.scope_kind,
                scope_key=track.scope_key,
            )
        )
        approvals = tuple(
            ProviderGuidanceLifecycleApproval(
                revision_id=item.revision_id,
                action=item.action,
                actor=item.actor,
                note=item.note,
                created_at=item.created_at,
            )
            for item in self._store().list_provider_guidance_approvals(
                track.provider,
                scope_kind=track.scope_kind,
                scope_key=track.scope_key,
            )
        )
        return ProviderGuidanceLifecycleDetail(
            provider=track.provider,
            scope_kind=track.scope_kind,
            scope_key=track.scope_key,
            body=track.revision.content,
            lifecycle_status=track.revision.status,
            active_revision_id=track.active_revision_id,
            published_revision_id=track.published_revision_id,
            runtime_available=bool(track.published_revision_id),
            revisions=revisions,
            approvals=approvals,
        )

    def _latest_action(
        self,
        provider_name: str,
        *,
        revision_id: str,
        scope_kind: str,
        scope_key: str,
    ) -> str:
        for item in self._store().list_provider_guidance_approvals(
            provider_name,
            scope_kind=scope_kind,
            scope_key=scope_key,
        ):
            if item.revision_id == revision_id:
                return item.action
        return ""

    def _snapshot(self, track: ProviderGuidanceTrackRecord) -> LifecycleSnapshot:
        published_revision_id = track.published_revision_id or ""
        return LifecycleSnapshot(
            revision_status=track.revision.status,
            latest_action=self._latest_action(
                track.provider,
                revision_id=track.active_revision_id,
                scope_kind=track.scope_kind,
                scope_key=track.scope_key,
            ),
            has_published_revision=bool(published_revision_id),
            published_revision_matches_active=(published_revision_id == track.active_revision_id and bool(published_revision_id)),
        )

    def _transition_message(
        self,
        provider_name: str,
        action: str,
        decision: LifecycleDecision,
        track: ProviderGuidanceTrackRecord,
    ) -> str:
        if decision.status == "submitted":
            return f"Submitted provider guidance for '{provider_name}'."
        if decision.status == "already_submitted":
            return f"Provider guidance for '{provider_name}' is already submitted for review."
        if decision.status == "approved":
            return f"Approved provider guidance for '{provider_name}'."
        if decision.status == "already_approved":
            return f"Provider guidance for '{provider_name}' is already approved."
        if decision.status == "rejected":
            return f"Rejected provider guidance for '{provider_name}'. Back to draft."
        if decision.status == "already_rejected":
            return f"Provider guidance for '{provider_name}' is already back in draft after rejection."
        if decision.status == "published":
            return f"Published provider guidance for '{provider_name}'."
        if decision.status == "already_published":
            return f"Provider guidance for '{provider_name}' is already published."
        if decision.status == "archived":
            return f"Archived provider guidance for '{provider_name}'."
        if decision.status == "already_archived":
            return f"Provider guidance for '{provider_name}' is already archived."
        if decision.status == "approval_required":
            return f"Provider guidance for '{provider_name}' must be approved before publishing."
        if action in {"approve", "reject"}:
            return f"Provider guidance for '{provider_name}' is not awaiting review."
        return f"Cannot {action} provider guidance for '{provider_name}' from state '{track.revision.status}'."

    def _apply_transition(
        self,
        track: ProviderGuidanceTrackRecord,
        *,
        action: str,
        actor_key: str,
        note: str = "",
    ) -> ProviderGuidanceLifecycleMutation:
        decision = decide_lifecycle_action(self._snapshot(track), action)
        if not decision.ok:
            return ProviderGuidanceLifecycleMutation(
                status=decision.status,
                ok=False,
                message=self._transition_message(track.provider, action, decision, track),
                detail=self._detail_from_track(track),
            )
        effects = decision.effects
        if effects.set_status is not None or effects.published_pointer != "unchanged" or effects.approval_action is not None:
            self._store().apply_provider_guidance_lifecycle_transition(
                track.provider,
                track.active_revision_id,
                set_status=effects.set_status,
                published_pointer=effects.published_pointer,
                approval_action=effects.approval_action,
                actor=actor_key,
                note=note,
                scope_kind=track.scope_kind,
                scope_key=track.scope_key,
            )
        detail = self.detail(track.provider, scope_kind=track.scope_kind, scope_key=track.scope_key)
        return ProviderGuidanceLifecycleMutation(
            status=decision.status,
            ok=detail is not None,
            message=self._transition_message(track.provider, action, decision, track),
            detail=detail,
        )

    def detail(
        self,
        provider_name: str,
        *,
        scope_kind: str = "system",
        scope_key: str = "",
    ) -> ProviderGuidanceLifecycleDetail | None:
        track = self._track(provider_name, scope_kind=scope_kind, scope_key=scope_key)
        if track is None:
            return None
        return self._detail_from_track(track)

    def edit_draft(
        self,
        provider_name: str,
        *,
        actor_key: str,
        body: str,
        scope_kind: str = "system",
        scope_key: str = "",
    ) -> ProviderGuidanceLifecycleMutation:
        track = self._track(provider_name, scope_kind=scope_kind, scope_key=scope_key)
        if track is None:
            return ProviderGuidanceLifecycleMutation(
                status="missing",
                ok=False,
                message=f"Provider guidance for '{provider_name}' not found.",
            )
        text = body.strip()
        if not text:
            return ProviderGuidanceLifecycleMutation(
                status="invalid",
                ok=False,
                message="Guidance body cannot be empty.",
            )
        updated = ProviderGuidanceTrackRecord(
            provider=track.provider,
            scope_kind=track.scope_kind,
            scope_key=track.scope_key,
            is_mutable=True,
            published_revision_id=track.published_revision_id,
            revision=ProviderGuidanceRevisionRecord(
                content=text,
                format=track.revision.format,
                created_by=actor_key,
                status="draft",
            ),
        )
        self._store().upsert_provider_guidance_draft(updated)
        detail = self.detail(provider_name, scope_kind=scope_kind, scope_key=scope_key)
        return ProviderGuidanceLifecycleMutation(
            status="draft_saved",
            ok=detail is not None,
            message=f"Saved draft provider guidance for '{provider_name}'.",
            detail=detail,
        )

    def submit(
        self,
        provider_name: str,
        *,
        actor_key: str,
        note: str = "",
        scope_kind: str = "system",
        scope_key: str = "",
    ) -> ProviderGuidanceLifecycleMutation:
        track = self._track(provider_name, scope_kind=scope_kind, scope_key=scope_key)
        if track is None:
            return ProviderGuidanceLifecycleMutation(status="missing", ok=False, message=f"Provider guidance for '{provider_name}' not found.")
        return self._apply_transition(track, action="submit", actor_key=actor_key, note=note)

    def approve(
        self,
        provider_name: str,
        *,
        actor_key: str,
        note: str = "",
        scope_kind: str = "system",
        scope_key: str = "",
    ) -> ProviderGuidanceLifecycleMutation:
        track = self._track(provider_name, scope_kind=scope_kind, scope_key=scope_key)
        if track is None:
            return ProviderGuidanceLifecycleMutation(status="missing", ok=False, message=f"Provider guidance for '{provider_name}' not found.")
        return self._apply_transition(track, action="approve", actor_key=actor_key, note=note)

    def reject(
        self,
        provider_name: str,
        *,
        actor_key: str,
        note: str = "",
        scope_kind: str = "system",
        scope_key: str = "",
    ) -> ProviderGuidanceLifecycleMutation:
        track = self._track(provider_name, scope_kind=scope_kind, scope_key=scope_key)
        if track is None:
            return ProviderGuidanceLifecycleMutation(status="missing", ok=False, message=f"Provider guidance for '{provider_name}' not found.")
        return self._apply_transition(track, action="reject", actor_key=actor_key, note=note)

    def publish(
        self,
        provider_name: str,
        *,
        actor_key: str,
        note: str = "",
        scope_kind: str = "system",
        scope_key: str = "",
    ) -> ProviderGuidanceLifecycleMutation:
        track = self._track(provider_name, scope_kind=scope_kind, scope_key=scope_key)
        if track is None:
            return ProviderGuidanceLifecycleMutation(status="missing", ok=False, message=f"Provider guidance for '{provider_name}' not found.")
        return self._apply_transition(track, action="publish", actor_key=actor_key, note=note)

    def archive(
        self,
        provider_name: str,
        *,
        actor_key: str,
        note: str = "",
        scope_kind: str = "system",
        scope_key: str = "",
    ) -> ProviderGuidanceLifecycleMutation:
        track = self._track(provider_name, scope_kind=scope_kind, scope_key=scope_key)
        if track is None:
            return ProviderGuidanceLifecycleMutation(status="missing", ok=False, message=f"Provider guidance for '{provider_name}' not found.")
        return self._apply_transition(track, action="archive", actor_key=actor_key, note=note)


_USE_CASES = ProviderGuidanceManagementUseCases()


def get_provider_guidance_management_use_cases() -> ProviderGuidanceManagementUseCases:
    return _USE_CASES
