"""Content-store contract: backend-neutral runtime skill and guidance behavior."""

from pathlib import Path

import pytest

from app.content_models import (
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
            version_label="v1",
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
