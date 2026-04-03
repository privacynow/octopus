"""SDK-owned provider-guidance lifecycle management workflows."""

from __future__ import annotations

from octopus_sdk.content_models import ProviderGuidanceRevisionRecord, ProviderGuidanceTrackRecord
from octopus_sdk.content_store import ContentStorePort
from octopus_sdk.workflows.lifecycle_machine import (
    LifecycleDecision,
    build_lifecycle_snapshot,
    decide_lifecycle_action,
)
from octopus_sdk.workflows.provider_guidance import (
    ProviderGuidanceLifecycleApproval,
    ProviderGuidanceLifecycleDetail,
    ProviderGuidanceLifecycleMutation,
    ProviderGuidanceLifecycleRevision,
    ProviderGuidanceManagementPort,
)


class ProviderGuidanceManagementUseCases(ProviderGuidanceManagementPort):
    """Lifecycle management for mutable provider-guidance tracks."""

    def __init__(self, *, store: ContentStorePort) -> None:
        self._store = store

    def _track(self, provider_name: str, *, scope_kind: str, scope_key: str) -> ProviderGuidanceTrackRecord | None:
        return self._store.get_provider_guidance(provider_name, scope_kind=scope_kind, scope_key=scope_key)

    def _detail__track(self, track: ProviderGuidanceTrackRecord) -> ProviderGuidanceLifecycleDetail:
        runtime_track = self._store.resolve_provider_guidance(
            track.provider,
            instance_key=track.scope_key if track.scope_kind == "instance" else "",
        )
        revisions = tuple(
            ProviderGuidanceLifecycleRevision(
                revision_id=item.revision_id,
                status=item.status,
                created_by=item.created_by,
                created_at=item.created_at,
                is_published=(item.revision_id == track.published_revision_id),
            )
            for item in self._store.list_provider_guidance_revisions(
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
            for item in self._store.list_provider_guidance_approvals(
                track.provider,
                scope_kind=track.scope_kind,
                scope_key=track.scope_key,
            )
        )
        return ProviderGuidanceLifecycleDetail(
            provider=track.provider,
            scope_kind=track.scope_kind,
            scope_key=track.scope_key,
            draft_body=track.revision.content,
            published_body=runtime_track.revision.content if runtime_track is not None else "",
            lifecycle_status=track.revision.status,
            active_revision_id=track.active_revision_id,
            published_revision_id=track.published_revision_id,
            runtime_available=bool(track.published_revision_id),
            revisions=revisions,
            approvals=approvals,
        )

    def _lifecycle_snapshot(self, track: ProviderGuidanceTrackRecord):
        return build_lifecycle_snapshot(
            track,
            self._store.get_latest_provider_guidance_approval_action(
                track.provider,
                track.active_revision_id,
                scope_kind=track.scope_kind,
                scope_key=track.scope_key,
            ),
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
        return f"Cannot {action} provider guidance for '{provider_name}' state '{track.revision.status}'."

    def _apply_transition(
        self,
        track: ProviderGuidanceTrackRecord,
        *,
        action: str,
        actor_key: str,
        note: str = "",
    ) -> ProviderGuidanceLifecycleMutation:
        decision = decide_lifecycle_action(self._lifecycle_snapshot(track), action)
        if not decision.ok:
            return ProviderGuidanceLifecycleMutation(
                status=decision.status,
                ok=False,
                message=self._transition_message(track.provider, action, decision, track),
                detail=self._detail__track(track),
            )
        effects = decision.effects
        if effects.set_status is not None or effects.published_pointer != "unchanged" or effects.approval_action is not None:
            self._store.apply_provider_guidance_lifecycle_transition(
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
        return self._detail__track(track)

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
        self._store.upsert_provider_guidance_draft(updated)
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
