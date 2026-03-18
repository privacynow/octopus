"""Provider-guidance lifecycle management workflows."""

from __future__ import annotations

from app.content_models import ProviderGuidanceRevisionRecord, ProviderGuidanceTrackRecord
from app.content_store import get_content_store
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
        if track.revision.status != "draft":
            return ProviderGuidanceLifecycleMutation(
                status="invalid_state",
                ok=False,
                message=f"Cannot submit provider guidance for '{provider_name}' from state '{track.revision.status}'.",
                detail=self._detail_from_track(track),
            )
        self._store().set_provider_guidance_revision_status(
            provider_name,
            track.active_revision_id,
            "review",
            scope_kind=scope_kind,
            scope_key=scope_key,
        )
        self._store().append_provider_guidance_approval(
            provider_name,
            track.active_revision_id,
            action="submitted",
            actor=actor_key,
            note=note,
            scope_kind=scope_kind,
            scope_key=scope_key,
        )
        detail = self.detail(provider_name, scope_kind=scope_kind, scope_key=scope_key)
        return ProviderGuidanceLifecycleMutation(
            status="submitted",
            ok=detail is not None,
            message=f"Submitted provider guidance for '{provider_name}'.",
            detail=detail,
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
        if track.revision.status != "review":
            return ProviderGuidanceLifecycleMutation(
                status="invalid_state",
                ok=False,
                message=f"Provider guidance for '{provider_name}' is not awaiting review.",
                detail=self._detail_from_track(track),
            )
        self._store().append_provider_guidance_approval(
            provider_name,
            track.active_revision_id,
            action="approved",
            actor=actor_key,
            note=note,
            scope_kind=scope_kind,
            scope_key=scope_key,
        )
        detail = self.detail(provider_name, scope_kind=scope_kind, scope_key=scope_key)
        return ProviderGuidanceLifecycleMutation(
            status="approved",
            ok=detail is not None,
            message=f"Approved provider guidance for '{provider_name}'.",
            detail=detail,
        )

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
        if track.revision.status != "review":
            return ProviderGuidanceLifecycleMutation(
                status="invalid_state",
                ok=False,
                message=f"Provider guidance for '{provider_name}' is not awaiting review.",
                detail=self._detail_from_track(track),
            )
        self._store().set_provider_guidance_revision_status(
            provider_name,
            track.active_revision_id,
            "draft",
            scope_kind=scope_kind,
            scope_key=scope_key,
        )
        self._store().append_provider_guidance_approval(
            provider_name,
            track.active_revision_id,
            action="rejected",
            actor=actor_key,
            note=note,
            scope_kind=scope_kind,
            scope_key=scope_key,
        )
        detail = self.detail(provider_name, scope_kind=scope_kind, scope_key=scope_key)
        return ProviderGuidanceLifecycleMutation(
            status="rejected",
            ok=detail is not None,
            message=f"Rejected provider guidance for '{provider_name}'. Back to draft.",
            detail=detail,
        )

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
        latest_action = self._latest_action(
            provider_name,
            revision_id=track.active_revision_id,
            scope_kind=scope_kind,
            scope_key=scope_key,
        )
        if latest_action != "approved":
            return ProviderGuidanceLifecycleMutation(
                status="approval_required",
                ok=False,
                message=f"Provider guidance for '{provider_name}' must be approved before publishing.",
                detail=self._detail_from_track(track),
            )
        self._store().set_provider_guidance_revision_status(
            provider_name,
            track.active_revision_id,
            "published",
            scope_kind=scope_kind,
            scope_key=scope_key,
        )
        self._store().set_published_provider_guidance_revision(
            provider_name,
            track.active_revision_id,
            scope_kind=scope_kind,
            scope_key=scope_key,
        )
        self._store().append_provider_guidance_approval(
            provider_name,
            track.active_revision_id,
            action="published",
            actor=actor_key,
            note=note,
            scope_kind=scope_kind,
            scope_key=scope_key,
        )
        detail = self.detail(provider_name, scope_kind=scope_kind, scope_key=scope_key)
        return ProviderGuidanceLifecycleMutation(
            status="published",
            ok=detail is not None,
            message=f"Published provider guidance for '{provider_name}'.",
            detail=detail,
        )

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
        self._store().set_provider_guidance_revision_status(
            provider_name,
            track.active_revision_id,
            "archived",
            scope_kind=scope_kind,
            scope_key=scope_key,
        )
        self._store().clear_published_provider_guidance_revision(
            provider_name,
            scope_kind=scope_kind,
            scope_key=scope_key,
        )
        self._store().append_provider_guidance_approval(
            provider_name,
            track.active_revision_id,
            action="archived",
            actor=actor_key,
            note=note,
            scope_kind=scope_kind,
            scope_key=scope_key,
        )
        detail = self.detail(provider_name, scope_kind=scope_kind, scope_key=scope_key)
        return ProviderGuidanceLifecycleMutation(
            status="archived",
            ok=detail is not None,
            message=f"Archived provider guidance for '{provider_name}'.",
            detail=detail,
        )


_USE_CASES = ProviderGuidanceManagementUseCases()


def get_provider_guidance_management_use_cases() -> ProviderGuidanceManagementUseCases:
    return _USE_CASES
