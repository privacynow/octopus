"""Content-store contract: backend-neutral runtime skill and guidance behavior."""

from pathlib import Path

import pytest

from octopus_sdk.content_models import (
    ProviderGuidanceRevisionRecord,
    ProviderGuidanceTrackRecord,
    RuntimeSkillTrackRecord,
    SkillFileRecord,
    SkillRevisionRecord,
)
from app.content_seed import seed_builtin_content
from app.content_store_postgres import PostgresContentStore
from app.content_store_sqlite import SQLiteContentStore


def _skill(
    slug: str,
    *,
    source_kind: str,
    body: str = "Body",
    display_name: str | None = None,
    description: str = "",
    source_uri: str = "",
    owner_actor: str = "",
    version_label: str = "v1",
) -> RuntimeSkillTrackRecord:
    return RuntimeSkillTrackRecord(
        slug=slug,
        display_name=display_name or slug.title(),
        description=description or f"{slug} description",
        source_kind=source_kind,
        source_uri=source_uri,
        owner_actor=owner_actor,
        visibility="shared",
        is_mutable=(source_kind == "custom"),
        revision=SkillRevisionRecord(
            instruction_body=body,
            requirements=[{"key": "API_TOKEN", "prompt": "Token"}],
            provider_config={"claude": {"allowed_tools": ["Read"]}},
            files=(
                SkillFileRecord(
                    relative_path="helper.sh",
                    content_text="#!/bin/sh\necho hi\n",
                    content_type="text/x-shellscript",
                    executable=True,
                ),
            ),
            version_label=version_label,
            created_by="test",
        ),
    )


@pytest.fixture(params=["sqlite", "postgres"])
def store(request, tmp_path: Path):
    if request.param == "sqlite":
        yield SQLiteContentStore(tmp_path / "content.db")
        return

    postgres_url = request.getfixturevalue("postgres_content_truncated")
    yield PostgresContentStore(postgres_url)


def test_replace_and_resolve_skill_roundtrip(store):
    record = _skill("code-review", source_kind="builtin", body="Review code")

    store.replace_skill_track(record)

    resolved = store.resolve_skill("code-review")

    assert resolved is not None
    assert resolved.slug == "code-review"
    assert resolved.source_kind == "builtin"
    assert resolved.revision.instruction_body == "Review code"
    assert resolved.revision.requirements[0]["key"] == "API_TOKEN"
    assert resolved.revision.provider_config["claude"]["allowed_tools"] == ["Read"]
    assert resolved.revision.files[0].relative_path == "helper.sh"
    assert resolved.revision.files[0].executable is True


def test_custom_track_overrides_builtin_by_precedence(store):
    store.replace_skill_track(_skill("debugging", source_kind="builtin", body="Builtin body", source_uri="catalog/debugging"))
    store.replace_skill_track(
        _skill(
            "debugging",
            source_kind="custom",
            body="Custom body",
            source_uri="custom/debugging",
            owner_actor="tg:42",
        )
    )

    resolved = store.resolve_skill("debugging")
    tracks = store.list_skill_tracks("debugging")

    assert resolved is not None
    assert resolved.source_kind == "custom"
    assert resolved.revision.instruction_body == "Custom body"
    assert [item.source_kind for item in tracks] == ["custom", "builtin"]


def test_list_skill_summaries_returns_effective_track(store):
    store.replace_skill_track(_skill("testing", source_kind="builtin"))
    store.replace_skill_track(_skill("documentation", source_kind="imported", source_uri="registry/documentation"))

    summaries = {item.slug: item for item in store.list_skill_summaries()}

    assert summaries["testing"].source_kind == "builtin"
    assert summaries["documentation"].source_kind == "imported"
    assert summaries["documentation"].source_uri == "registry/documentation"


def test_provider_guidance_instance_override_wins(store):
    store.replace_provider_guidance(
        ProviderGuidanceTrackRecord(
            provider="claude",
            scope_kind="system",
            scope_key="",
            is_mutable=False,
            revision=ProviderGuidanceRevisionRecord(content="system", created_by="seed"),
        )
    )
    store.replace_provider_guidance(
        ProviderGuidanceTrackRecord(
            provider="claude",
            scope_kind="instance",
            scope_key="bot-a",
            is_mutable=True,
            revision=ProviderGuidanceRevisionRecord(content="instance", created_by="admin"),
        )
    )

    system = store.get_provider_guidance("claude", scope_kind="system", scope_key="")
    effective = store.resolve_provider_guidance("claude", instance_key="bot-a")

    assert system is not None
    assert system.revision.content == "system"
    assert effective is not None
    assert effective.revision.content == "instance"


def test_seed_builtin_content_loads_catalog_and_default_guidance(store):
    seed_builtin_content(store)

    github = store.resolve_skill("github-integration")
    claude = store.get_provider_guidance("claude", scope_kind="system", scope_key="")
    codex = store.get_provider_guidance("codex", scope_kind="system", scope_key="")

    assert github is not None
    assert github.source_kind == "builtin"
    assert any(item.relative_path == "gh-helper.sh" for item in github.revision.files)
    assert "claude" in github.revision.provider_config
    assert "codex" in github.revision.provider_config
    assert claude is not None
    assert codex is not None


def test_unpublished_custom_draft_does_not_override_runtime_resolution(store):
    store.replace_skill_track(_skill("debugging", source_kind="builtin", body="Builtin body"))
    store.upsert_skill_draft(
        _skill(
            "debugging",
            source_kind="custom",
            body="Draft body",
            source_uri="custom/debugging",
            owner_actor="tg:42",
            version_label="draft",
        )
    )

    authoring = store.resolve_skill("debugging")
    runtime = store.resolve_runtime_skill("debugging")
    authoring_summaries = {item.slug: item for item in store.list_skill_summaries()}
    runtime_summaries = {item.slug: item for item in store.list_runtime_skill_summaries()}

    assert authoring is not None
    assert authoring.source_kind == "custom"
    assert authoring.revision.instruction_body == "Draft body"
    assert authoring.revision.status == "draft"
    assert runtime is not None
    assert runtime.source_kind == "builtin"
    assert runtime.revision.instruction_body == "Builtin body"
    assert authoring_summaries["debugging"].has_unpublished_changes is False
    assert runtime_summaries["debugging"].source_kind == "builtin"


def test_publishing_custom_revision_switches_runtime_resolution(store):
    store.replace_skill_track(_skill("helpers", source_kind="builtin", body="Builtin helper"))
    store.upsert_skill_draft(
        _skill(
            "helpers",
            source_kind="custom",
            body="Draft helper",
            source_uri="custom/helpers",
            owner_actor="tg:42",
            version_label="draft",
        )
    )
    current = store.resolve_skill("helpers")
    assert current is not None

    store.set_skill_revision_status("helpers", current.active_revision_id, "review")
    store.append_skill_approval(
        "helpers",
        current.active_revision_id,
        action="approved",
        actor="admin:1",
        note="Looks good",
    )
    store.set_skill_revision_status("helpers", current.active_revision_id, "published")
    store.set_published_skill_revision("helpers", current.active_revision_id)

    runtime = store.resolve_runtime_skill("helpers")
    approvals = store.list_skill_approvals("helpers")
    revisions = store.list_skill_revisions("helpers")

    assert runtime is not None
    assert runtime.source_kind == "custom"
    assert runtime.revision.instruction_body == "Draft helper"
    assert runtime.revision.status == "published"
    assert approvals[0].action == "approved"
    assert revisions[0].status == "published"


def test_latest_skill_approval_action_returns_newest_match_and_empty_for_missing_revision(store):
    store.upsert_skill_draft(
        _skill(
            "helpers",
            source_kind="custom",
            body="Draft helper",
            source_uri="custom/helpers",
            owner_actor="tg:42",
            version_label="draft",
        )
    )
    current = store.resolve_skill("helpers")
    assert current is not None

    store.append_skill_approval("helpers", current.active_revision_id, action="submitted", actor="admin:1")
    store.append_skill_approval("helpers", current.active_revision_id, action="approved", actor="admin:2")

    latest = store.get_latest_skill_approval_action("helpers", current.active_revision_id)
    missing = store.get_latest_skill_approval_action("helpers", "missing-revision")

    assert latest == "approved"
    assert missing == ""


def test_provider_guidance_draft_uses_published_pointer_for_runtime(store):
    store.replace_provider_guidance(
        ProviderGuidanceTrackRecord(
            provider="claude",
            scope_kind="system",
            scope_key="",
            is_mutable=True,
            revision=ProviderGuidanceRevisionRecord(content="published", created_by="seed"),
        )
    )
    store.upsert_provider_guidance_draft(
        ProviderGuidanceTrackRecord(
            provider="claude",
            scope_kind="system",
            scope_key="",
            is_mutable=True,
            revision=ProviderGuidanceRevisionRecord(content="draft", created_by="admin"),
        )
    )

    authoring = store.get_provider_guidance("claude", scope_kind="system", scope_key="")
    runtime = store.resolve_provider_guidance("claude")

    assert authoring is not None
    assert authoring.revision.content == "draft"
    assert authoring.revision.status == "draft"
    assert runtime is not None
    assert runtime.revision.content == "published"

    store.set_provider_guidance_revision_status(
        "claude",
        authoring.active_revision_id,
        "published",
    )
    store.append_provider_guidance_approval(
        "claude",
        authoring.active_revision_id,
        action="published",
        actor="admin:1",
    )
    store.set_published_provider_guidance_revision("claude", authoring.active_revision_id)

    runtime_after = store.resolve_provider_guidance("claude")
    assert runtime_after is not None
    assert runtime_after.revision.content == "draft"


def test_latest_provider_guidance_approval_action_returns_newest_match_and_empty_for_missing_revision(store):
    store.upsert_provider_guidance_draft(
        ProviderGuidanceTrackRecord(
            provider="claude",
            scope_kind="system",
            scope_key="",
            is_mutable=True,
            revision=ProviderGuidanceRevisionRecord(content="draft", created_by="admin"),
        )
    )
    current = store.get_provider_guidance("claude", scope_kind="system", scope_key="")
    assert current is not None

    store.append_provider_guidance_approval(
        "claude",
        current.active_revision_id,
        action="submitted",
        actor="admin:1",
    )
    store.append_provider_guidance_approval(
        "claude",
        current.active_revision_id,
        action="approved",
        actor="admin:2",
    )

    latest = store.get_latest_provider_guidance_approval_action("claude", current.active_revision_id)
    missing = store.get_latest_provider_guidance_approval_action("claude", "missing-revision")

    assert latest == "approved"
    assert missing == ""
