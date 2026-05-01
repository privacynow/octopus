"""SDK-owned runtime-skill authoring lifecycle workflows."""

from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path

from octopus_sdk.content_models import RuntimeSkillTrackRecord, SkillRevisionRecord
from octopus_sdk.content_store import ContentStorePort
from octopus_sdk.providers import ProviderConfigRecord, coerce_provider_config
from octopus_sdk.skill_packages import (
    coerce_skill_requirements,
    coerce_skill_files,
    default_skill_display_name,
    normalize_skill_document_format,
    parse_skill_package_document,
    publish_ready,
    skill_package_document_to_text,
    skill_package_from_track,
    skill_package_hash,
    skill_runtime_available,
    validate_skill_package,
)
from octopus_sdk.runtime.skills import normalize_skill_kind
from octopus_sdk.workflows.lifecycle_machine import (
    LifecycleDecision,
    build_lifecycle_snapshot,
    decide_lifecycle_action,
)
from octopus_sdk.workflows.skills import (
    RuntimeSkillAuthoringPort,
    SkillCatalogServicePort,
    RuntimeSkillLifecycleApproval,
    RuntimeSkillLifecycleDetail,
    RuntimeSkillLifecycleMutation,
    RuntimeSkillPackageArtifact,
    RuntimeSkillLifecycleRevision,
    RuntimeSkillValidationProblem,
)
from octopus_sdk.skill_types import skill_source_label

log = logging.getLogger(__name__)


class RuntimeSkillAuthoringUseCases(RuntimeSkillAuthoringPort):
    """Mutable custom runtime-skill lifecycle orchestration."""

    def __init__(
        self,
        *,
        store: ContentStorePort,
        catalog_service: SkillCatalogServicePort,
    ) -> None:
        self._store = store
        self._catalog = catalog_service

    def _mutable_track(self, skill_name: str) -> RuntimeSkillTrackRecord | None:
        track = self._catalog.resolve_track(skill_name)
        if track is None or track.source_kind != "custom" or not track.is_mutable:
            return None
        return track

    def _detail_from_track(
        self,
        track: RuntimeSkillTrackRecord,
        *,
        revisions: tuple[RuntimeSkillLifecycleRevision, ...] = (),
        approvals: tuple[RuntimeSkillLifecycleApproval, ...] = (),
    ) -> RuntimeSkillLifecycleDetail:
        validation_problems = tuple(
            RuntimeSkillValidationProblem(
                code=item.code,
                message=item.message,
                field_path=item.field_path,
                severity=item.severity,
            )
            for item in validate_skill_package(
                skill_name=track.slug,
                display_name=track.display_name,
                body=track.revision.instruction_body,
                requirements=list(track.revision.requirements),
                provider_config=track.revision.provider_config,
                files=track.revision.files,
            )
        )
        return RuntimeSkillLifecycleDetail(
            name=track.slug,
            display_name=track.display_name,
            description=track.description,
            skill_kind=track.revision.skill_kind,
            source_label=skill_source_label(track.source_kind),
            visibility=track.visibility,
            body=track.revision.instruction_body,
            lifecycle_status=track.revision.status,
            active_revision_id=track.active_revision_id,
            published_revision_id=track.published_revision_id,
            runtime_available=skill_runtime_available(track),
            publish_ready=publish_ready(
                skill_name=track.slug,
                display_name=track.display_name,
                body=track.revision.instruction_body,
                requirements=list(track.revision.requirements),
                provider_config=track.revision.provider_config,
                files=track.revision.files,
            ),
            requirements=tuple(track.revision.requirements),
            provider_config=track.revision.provider_config,
            files=track.revision.files,
            validation_problems=validation_problems,
            revisions=revisions,
            approvals=approvals,
        )

    def _detail__track(self, track: RuntimeSkillTrackRecord) -> RuntimeSkillLifecycleDetail:
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
            for item in self._store.list_skill_revisions(track.slug)
        )
        approvals = tuple(
            RuntimeSkillLifecycleApproval(
                revision_id=item.revision_id,
                action=item.action,
                actor=item.actor,
                note=item.note,
                created_at=item.created_at,
            )
            for item in self._store.list_skill_approvals(track.slug)
        )
        return self._detail_from_track(track, revisions=revisions, approvals=approvals)

    def _lifecycle_snapshot(self, track: RuntimeSkillTrackRecord):
        return build_lifecycle_snapshot(
            track,
            self._store.get_latest_skill_approval_action(track.slug, track.active_revision_id),
        )

    def _transition_message(
        self,
        skill_name: str,
        action: str,
        decision: LifecycleDecision,
        track: RuntimeSkillTrackRecord,
    ) -> str:
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
            return f"Cannot submit skill '{skill_name}' state '{track.revision.status}'."
        if action == "publish":
            return f"Cannot publish skill '{skill_name}' state '{track.revision.status}'."
        return f"Cannot {action} skill '{skill_name}' state '{track.revision.status}'."

    def _apply_transition(
        self,
        track: RuntimeSkillTrackRecord,
        *,
        action: str,
        actor_key: str,
        note: str = "",
    ) -> RuntimeSkillLifecycleMutation:
        if action in {"submit", "publish"}:
            validation_problems = validate_skill_package(
                skill_name=track.slug,
                display_name=track.display_name,
                body=track.revision.instruction_body,
                requirements=list(track.revision.requirements),
                provider_config=track.revision.provider_config,
                files=track.revision.files,
            )
            if validation_problems:
                return RuntimeSkillLifecycleMutation(
                    status="invalid",
                    ok=False,
                    message=(
                        f"Cannot {action} '{track.slug}' until draft validation problems are fixed: "
                        f"{validation_problems[0].message}"
                    ),
                    detail=self._detail__track(track),
                )
        decision = decide_lifecycle_action(self._lifecycle_snapshot(track), action)
        if not decision.ok:
            return RuntimeSkillLifecycleMutation(
                status=decision.status,
                ok=False,
                message=self._transition_message(track.slug, action, decision, track),
                detail=self._detail__track(track),
            )
        effects = decision.effects
        if effects.set_status is not None or effects.published_pointer != "unchanged" or effects.approval_action is not None:
            self._store.apply_skill_lifecycle_transition(
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
        return self._detail__track(track)

    def create_draft(self, skill_name: str, *, owner_actor: str = "") -> RuntimeSkillLifecycleMutation:
        if not skill_name or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789-" for ch in skill_name):
            return RuntimeSkillLifecycleMutation(
                status="invalid",
                ok=False,
                message="Skill names must use lowercase letters, digits, and hyphens.",
            )
        if not skill_name[0].isalpha():
            return RuntimeSkillLifecycleMutation(
                status="invalid",
                ok=False,
                message="Skill names must start with a lowercase letter.",
            )
        if self._catalog.has_skill(skill_name):
            return RuntimeSkillLifecycleMutation(
                status="invalid",
                ok=False,
                message=f"Skill '{skill_name}' already exists.",
            )
        try:
            self._catalog.create_custom_draft(skill_name, owner_actor=owner_actor)
        except ValueError:
            log.warning("Runtime skill draft creation failed for %s", skill_name, exc_info=True)
            return RuntimeSkillLifecycleMutation(
                status="invalid",
                ok=False,
                message="Could not create that draft skill. Check the name and try again.",
            )
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
        body: str | None = None,
        display_name: str | None = None,
        description: str | None = None,
        skill_kind: str | None = None,
        requirements: tuple | None = None,
        provider_config: ProviderConfigRecord | None = None,
        files: tuple | None = None,
        changelog: str = "",
    ) -> RuntimeSkillLifecycleMutation:
        track = self._mutable_track(skill_name)
        if track is None:
            return RuntimeSkillLifecycleMutation(
                status="missing",
                ok=False,
                message=f"Custom skill '{skill_name}' not found.",
            )
        text = track.revision.instruction_body if body is None else body.strip()
        next_display_name = track.display_name if display_name is None else str(display_name).strip()
        next_description = track.description if description is None else description
        next_skill_kind = track.revision.skill_kind if skill_kind is None else normalize_skill_kind(skill_kind)
        next_requirements = (
            tuple(track.revision.requirements)
            if requirements is None
            else coerce_skill_requirements(requirements)
        )
        next_provider_config = (
            track.revision.provider_config
            if provider_config is None
            else coerce_provider_config(provider_config)
        )
        next_files = track.revision.files if files is None else coerce_skill_files(files)
        validation_problems = validate_skill_package(
            skill_name=track.slug,
            display_name=next_display_name,
            body=text,
            requirements=list(next_requirements),
            provider_config=next_provider_config,
            files=next_files,
        )
        if validation_problems:
            detail = self._detail__track(
                RuntimeSkillTrackRecord(
                    slug=track.slug,
                    display_name=next_display_name,
                    description=next_description,
                    source_kind=track.source_kind,
                    revision=SkillRevisionRecord(
                        instruction_body=text,
                        skill_kind=next_skill_kind,
                        requirements=list(next_requirements),
                        provider_config=next_provider_config,
                        files=next_files,
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
                    active_revision_id=track.active_revision_id,
                    published_revision_id=track.published_revision_id,
                )
            )
            return RuntimeSkillLifecycleMutation(
                status="invalid",
                ok=False,
                message=validation_problems[0].message,
                detail=detail,
            )
        updated = RuntimeSkillTrackRecord(
            slug=track.slug,
            display_name=next_display_name,
            description=next_description,
            source_kind=track.source_kind,
            revision=SkillRevisionRecord(
                instruction_body=text,
                skill_kind=next_skill_kind,
                requirements=list(next_requirements),
                provider_config=next_provider_config,
                files=next_files,
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
        self._store.upsert_skill_draft(updated)
        detail = self.detail(skill_name)
        return RuntimeSkillLifecycleMutation(
            status="draft_saved",
            ok=detail is not None,
            message=f"Saved draft for '{skill_name}'.",
            detail=detail,
        )

    def export_package(
        self,
        skill_name: str,
        *,
        revision_scope: str = "draft",
        format: str = "json",
    ) -> RuntimeSkillPackageArtifact | None:
        track = self._mutable_track(skill_name)
        if track is None:
            return None
        try:
            normalized_format = normalize_skill_document_format(format)
        except ValueError:
            normalized_format = "json"
        normalized_scope = "published" if str(revision_scope or "").strip().lower() == "published" else "draft"
        export_track = track
        revision_id = track.active_revision_id
        if normalized_scope == "published":
            published_revision_id = str(track.published_revision_id or "").strip()
            if not published_revision_id:
                return None
            published_revision = next(
                (
                    item
                    for item in self._store.list_skill_revisions(track.slug)
                    if item.revision_id == published_revision_id
                ),
                None,
            )
            if published_revision is None:
                return None
            export_track = RuntimeSkillTrackRecord(
                slug=track.slug,
                display_name=track.display_name,
                description=track.description,
                source_kind=track.source_kind,
                revision=published_revision,
                source_uri=track.source_uri,
                owner_actor=track.owner_actor,
                visibility=track.visibility,
                is_mutable=track.is_mutable,
                archived=track.archived,
                active_revision_id=published_revision_id,
                published_revision_id=published_revision_id,
            )
            revision_id = published_revision_id
        document_text = skill_package_document_to_text(
            skill_package_from_track(export_track),
            format=normalized_format,
            source="runtime-skill-authoring",
            revision_scope=normalized_scope,
            revision_id=revision_id,
        )
        return RuntimeSkillPackageArtifact(
            name=export_track.slug,
            display_name=export_track.display_name,
            file_name=f"{export_track.slug}-{normalized_scope}.skill.{normalized_format}",
            content_type="application/x-yaml" if normalized_format == "yaml" else "application/json",
            content_text=document_text,
            format=normalized_format,
            revision_scope=normalized_scope,
            revision_id=revision_id,
        )

    def import_package(
        self,
        *,
        actor_key: str,
        document_text: str,
        format: str = "json",
        file_name: str = "",
        target_skill_name: str = "",
    ) -> RuntimeSkillLifecycleMutation:
        try:
            package = parse_skill_package_document(document_text, format=format)
        except ValueError as exc:
            return RuntimeSkillLifecycleMutation(
                status="invalid",
                ok=False,
                message=str(exc),
            )
        skill_name = str(target_skill_name or package.skill_name or "").strip().lower()
        if not skill_name:
            return RuntimeSkillLifecycleMutation(
                status="invalid",
                ok=False,
                message="Skill package does not include a valid skill name.",
            )
        package = replace(package, skill_name=skill_name)
        track = self._mutable_track(skill_name)
        if track is not None and skill_package_hash(skill_package_from_track(track)) == skill_package_hash(package):
            return RuntimeSkillLifecycleMutation(
                status="unchanged",
                ok=True,
                message=f"Skill package for '{skill_name}' is already current.",
                detail=self.detail(skill_name),
            )
        if track is None:
            try:
                self._catalog.create_custom_draft(skill_name, owner_actor=actor_key)
            except ValueError as exc:
                return RuntimeSkillLifecycleMutation(
                    status="invalid",
                    ok=False,
                    message=str(exc),
                )
        imported = self.edit_draft(
            skill_name,
            actor_key=actor_key,
            body=package.body,
            display_name=package.display_name or default_skill_display_name(skill_name),
            description=package.description,
            skill_kind=package.skill_kind,
            requirements=package.requirements,
            provider_config=package.provider_config,
            files=package.files,
            changelog=f"Imported from {Path(str(file_name or 'package')).name}",
        )
        if imported.ok:
            return RuntimeSkillLifecycleMutation(
                status="imported",
                ok=True,
                message=f"Imported skill package into '{skill_name}'.",
                detail=imported.detail,
            )
        return imported

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
