from __future__ import annotations

import json
from typing import Literal

from octopus_sdk.content_models import (
    LifecycleApprovalRecord,
    ProviderGuidanceRevisionRecord,
    ProviderGuidanceTrackRecord,
    RuntimeSkillSummary,
    RuntimeSkillTrackRecord,
    SkillFileRecord,
    SkillRevisionRecord,
    skill_precedence,
)

from octopus_registry.store_base import utcnow_iso
from octopus_registry.store_dialect import StoreDialect
from octopus_registry.store_shared.common import record, records


def _parse_json(raw: object, default: object) -> object:
    if raw is None:
        return default
    if isinstance(raw, (list, dict)):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _stable_json(value: object) -> str:
    return json.dumps(value, sort_keys=True)


def _skill_revision_id(track: RuntimeSkillTrackRecord) -> str:
    return track.revision.revision_id or f"{track.slug}|{track.revision.digest}"


def _guidance_revision_id(track: ProviderGuidanceTrackRecord) -> str:
    key = f"{track.provider}|{track.scope_kind}|{track.scope_key}"
    return track.revision.revision_id or f"{key}|{track.revision.digest}"


def _skill_files_payload(track: RuntimeSkillTrackRecord) -> list[dict[str, object]]:
    return [
        {
            "relative_path": item.relative_path,
            "content_text": item.content_text,
            "content_type": item.content_type,
            "executable": item.executable,
        }
        for item in track.revision.files
    ]


def _skill_row_to_track(row: dict[str, object]) -> RuntimeSkillTrackRecord:
    files = tuple(
        SkillFileRecord(
            relative_path=item.get("relative_path", ""),
            content_text=item.get("content_text", ""),
            content_type=item.get("content_type", "text/plain"),
            executable=bool(item.get("executable", False)),
        )
        for item in _parse_json(row.get("files_json", []), [])
        if isinstance(item, dict)
    )
    revision = SkillRevisionRecord(
        instruction_body=str(row.get("instruction_body", "") or ""),
        requirements=_parse_json(row.get("requirements_json", []), []),
        provider_config=_parse_json(row.get("provider_config_json", {}), {}),
        files=files,
        version_label=str(row.get("version_label", "") or ""),
        changelog=str(row.get("changelog", "") or ""),
        created_by=str(row.get("created_by", "") or ""),
        created_at=str(row.get("created_at", "") or ""),
        revision_id=str(row.get("revision_id", row.get("active_revision_id", "")) or ""),
        status=str(row.get("status", "published") or "published"),
    )
    return RuntimeSkillTrackRecord(
        slug=str(row.get("slug", "") or ""),
        display_name=str(row.get("display_name", "") or ""),
        description=str(row.get("description", "") or ""),
        source_kind=str(row.get("source_kind", "custom") or "custom"),
        revision=revision,
        source_uri=str(row.get("source_uri", "") or ""),
        owner_actor=str(row.get("owner_actor", "") or ""),
        visibility=str(row.get("visibility", "private") or "private"),
        is_mutable=bool(row.get("is_mutable", True)),
        archived=bool(row.get("archived", False)),
        active_revision_id=str(row.get("active_revision_id", "") or ""),
        published_revision_id=str(row.get("published_revision_id", "") or ""),
    )


def _guidance_row_to_track(row: dict[str, object]) -> ProviderGuidanceTrackRecord:
    return ProviderGuidanceTrackRecord(
        provider=str(row.get("provider", "") or ""),
        scope_kind=str(row.get("scope_kind", "") or ""),
        scope_key=str(row.get("scope_key", "") or ""),
        is_mutable=bool(row.get("is_mutable", True)),
        active_revision_id=str(row.get("active_revision_id", "") or ""),
        published_revision_id=str(row.get("published_revision_id", "") or ""),
        revision=ProviderGuidanceRevisionRecord(
            content=str(row.get("content", "") or ""),
            format=str(row.get("format", "text") or "text"),
            created_by=str(row.get("created_by", "") or ""),
            created_at=str(row.get("created_at", "") or ""),
            revision_id=str(row.get("revision_id", "") or ""),
            status=str(row.get("status", "published") or "published"),
        ),
    )


def _skill_rows_for_slug(
    conn,
    *,
    dialect: StoreDialect,
    slug: str,
    runtime_only: bool,
) -> list[dict[str, object]]:
    revision_ref = (
        "CASE WHEN s.published_revision_id != '' THEN s.published_revision_id ELSE s.active_revision_id END"
        if runtime_only else
        "s.active_revision_id"
    )
    extra_where = "AND s.published_revision_id != ''" if runtime_only else ""
    sql = f"""
        SELECT
            s.slug, s.display_name, s.description, s.source_kind,
            s.source_uri, s.owner_actor, s.visibility, s.is_mutable,
            s.archived, s.active_revision_id, s.published_revision_id,
            rev.revision_id, rev.instruction_body, rev.requirements_json,
            rev.provider_config_json, rev.files_json, rev.version_label,
            rev.changelog, rev.status, rev.created_by, rev.created_at
        FROM {dialect.qualify('runtime_skills')} s
        JOIN {dialect.qualify('skill_revisions')} rev ON rev.revision_id = {revision_ref}
        WHERE s.slug = {dialect.placeholder(1)}
        {extra_where}
    """
    return dialect.fetchall(conn, sql, (slug,))


def replace_skill_track(
    conn,
    *,
    dialect: StoreDialect,
    track: RuntimeSkillTrackRecord,
) -> None:
    _upsert_registry_skill(conn, dialect=dialect, track=track, status="published", publish=True)


def upsert_skill_draft(
    conn,
    *,
    dialect: StoreDialect,
    track: RuntimeSkillTrackRecord,
) -> None:
    _upsert_registry_skill(conn, dialect=dialect, track=track, status="draft", publish=False)


def _upsert_registry_skill(
    conn,
    *,
    dialect: StoreDialect,
    track: RuntimeSkillTrackRecord,
    status: str,
    publish: bool,
) -> None:
    now = utcnow_iso()
    revision_id = _skill_revision_id(track)
    existing = dialect.fetchone(
        conn,
        f"SELECT published_revision_id FROM {dialect.qualify('runtime_skills')} WHERE slug = {dialect.placeholder(1)}",
        (track.slug,),
    )
    published_revision_id = revision_id if publish else str(existing.get("published_revision_id") or "") if existing else ""
    files_json = _stable_json(_skill_files_payload(track))
    dialect.execute(
        conn,
        f"""
        INSERT INTO {dialect.qualify('runtime_skills')} (
            slug, display_name, description, source_kind, source_uri, owner_actor,
            visibility, is_mutable, archived, instruction_body, requirements_json,
            provider_config_json, files_json, active_revision_id, published_revision_id,
            created_at, updated_at
        ) VALUES (
            {dialect.placeholder(1)}, {dialect.placeholder(2)}, {dialect.placeholder(3)},
            {dialect.placeholder(4)}, {dialect.placeholder(5)}, {dialect.placeholder(6)},
            {dialect.placeholder(7)}, {dialect.placeholder(8)}, {dialect.placeholder(9)},
            {dialect.placeholder(10)}, {dialect.placeholder(11)}, {dialect.placeholder(12)},
            {dialect.placeholder(13)}, {dialect.placeholder(14)}, {dialect.placeholder(15)},
            {dialect.placeholder(16)}, {dialect.placeholder(17)}
        )
        ON CONFLICT(slug) DO UPDATE SET
            display_name = excluded.display_name,
            description = excluded.description,
            source_kind = excluded.source_kind,
            source_uri = excluded.source_uri,
            owner_actor = excluded.owner_actor,
            visibility = excluded.visibility,
            is_mutable = excluded.is_mutable,
            archived = excluded.archived,
            instruction_body = excluded.instruction_body,
            requirements_json = excluded.requirements_json,
            provider_config_json = excluded.provider_config_json,
            files_json = excluded.files_json,
            active_revision_id = excluded.active_revision_id,
            published_revision_id = excluded.published_revision_id,
            updated_at = excluded.updated_at
        """,
        (
            track.slug,
            track.display_name,
            track.description,
            track.source_kind,
            track.source_uri,
            track.owner_actor,
            track.visibility,
            bool(track.is_mutable),
            bool(track.archived),
            track.revision.instruction_body,
            _stable_json(track.revision.requirements),
            _stable_json(track.revision.provider_config),
            files_json,
            revision_id,
            published_revision_id,
            now,
            now,
        ),
    )
    dialect.execute(
        conn,
        f"""
        INSERT INTO {dialect.qualify('skill_revisions')} (
            revision_id, slug, instruction_body, requirements_json,
            provider_config_json, files_json, version_label, changelog,
            status, created_by, created_at
        ) VALUES (
            {dialect.placeholder(1)}, {dialect.placeholder(2)}, {dialect.placeholder(3)},
            {dialect.placeholder(4)}, {dialect.placeholder(5)}, {dialect.placeholder(6)},
            {dialect.placeholder(7)}, {dialect.placeholder(8)}, {dialect.placeholder(9)},
            {dialect.placeholder(10)}, {dialect.placeholder(11)}
        )
        ON CONFLICT(revision_id) DO UPDATE SET
            instruction_body = excluded.instruction_body,
            requirements_json = excluded.requirements_json,
            provider_config_json = excluded.provider_config_json,
            files_json = excluded.files_json,
            version_label = excluded.version_label,
            changelog = excluded.changelog,
            status = excluded.status,
            created_by = excluded.created_by,
            created_at = excluded.created_at
        """,
        (
            revision_id,
            track.slug,
            track.revision.instruction_body,
            _stable_json(track.revision.requirements),
            _stable_json(track.revision.provider_config),
            files_json,
            track.revision.version_label,
            track.revision.changelog,
            status,
            track.revision.created_by,
            track.revision.created_at or now,
        ),
    )


def delete_skill_track(
    conn,
    *,
    dialect: StoreDialect,
    slug: str,
) -> bool:
    existed = (
        dialect.fetchone(
            conn,
            f"SELECT 1 AS found FROM {dialect.qualify('runtime_skills')} WHERE slug = {dialect.placeholder(1)}",
            (slug,),
        )
        is not None
    )
    dialect.execute(
        conn,
        f"DELETE FROM {dialect.qualify('skill_revisions')} WHERE slug = {dialect.placeholder(1)}",
        (slug,),
    )
    dialect.execute(
        conn,
        f"DELETE FROM {dialect.qualify('skill_approvals')} WHERE slug = {dialect.placeholder(1)}",
        (slug,),
    )
    dialect.execute(
        conn,
        f"DELETE FROM {dialect.qualify('runtime_skills')} WHERE slug = {dialect.placeholder(1)}",
        (slug,),
    )
    return existed


def list_skill_tracks(
    conn,
    *,
    dialect: StoreDialect,
    slug: str,
) -> list[RuntimeSkillTrackRecord]:
    records_out = [_skill_row_to_track(row) for row in _skill_rows_for_slug(conn, dialect=dialect, slug=slug, runtime_only=False)]
    return sorted(records_out, key=lambda item: skill_precedence(item.source_kind), reverse=True)


def resolve_skill(
    conn,
    *,
    dialect: StoreDialect,
    slug: str,
) -> RuntimeSkillTrackRecord | None:
    tracks = list_skill_tracks(conn, dialect=dialect, slug=slug)
    return tracks[0] if tracks else None


def resolve_runtime_skill(
    conn,
    *,
    dialect: StoreDialect,
    slug: str,
) -> RuntimeSkillTrackRecord | None:
    records_out = [_skill_row_to_track(row) for row in _skill_rows_for_slug(conn, dialect=dialect, slug=slug, runtime_only=True)]
    records_out = sorted(records_out, key=lambda item: skill_precedence(item.source_kind), reverse=True)
    return records_out[0] if records_out else None


def _skill_summaries(
    conn,
    *,
    dialect: StoreDialect,
    runtime_only: bool,
) -> list[RuntimeSkillSummary]:
    rows = dialect.fetchall(
        conn,
        f"SELECT slug FROM {dialect.qualify('runtime_skills')} ORDER BY lower(slug)",
    )
    resolver = resolve_runtime_skill if runtime_only else resolve_skill
    summaries: list[RuntimeSkillSummary] = []
    for row in rows:
        item = resolver(conn, dialect=dialect, slug=str(row["slug"] or ""))
        if item is None:
            continue
        summaries.append(
            RuntimeSkillSummary(
                slug=item.slug,
                display_name=item.display_name,
                description=item.description,
                source_kind=item.source_kind,
                source_uri=item.source_uri,
                visibility=item.visibility,
                is_mutable=item.is_mutable,
                digest=item.revision.digest,
                status=item.revision.status,
                runtime_available=bool(item.published_revision_id) or not item.is_mutable,
                has_unpublished_changes=bool(item.published_revision_id)
                and item.published_revision_id != item.active_revision_id,
            )
        )
    return summaries


def list_skill_summaries(conn, *, dialect: StoreDialect) -> list[RuntimeSkillSummary]:
    return _skill_summaries(conn, dialect=dialect, runtime_only=False)


def list_runtime_skill_summaries(conn, *, dialect: StoreDialect) -> list[RuntimeSkillSummary]:
    return _skill_summaries(conn, dialect=dialect, runtime_only=True)


def list_skill_revisions(
    conn,
    *,
    dialect: StoreDialect,
    slug: str,
) -> list[SkillRevisionRecord]:
    rows = dialect.fetchall(
        conn,
        f"""
        SELECT revision_id, instruction_body, requirements_json, provider_config_json,
               files_json, version_label, changelog, status, created_by, created_at
        FROM {dialect.qualify('skill_revisions')}
        WHERE slug = {dialect.placeholder(1)}
        ORDER BY created_at DESC, revision_id DESC
        """,
        (slug,),
    )
    return [
        SkillRevisionRecord(
            instruction_body=str(row["instruction_body"] or ""),
            requirements=_parse_json(row["requirements_json"], []),
            provider_config=_parse_json(row["provider_config_json"], {}),
            files=tuple(
                SkillFileRecord(
                    relative_path=item.get("relative_path", ""),
                    content_text=item.get("content_text", ""),
                    content_type=item.get("content_type", "text/plain"),
                    executable=bool(item.get("executable", False)),
                )
                for item in _parse_json(row["files_json"], [])
                if isinstance(item, dict)
            ),
            version_label=str(row["version_label"] or ""),
            changelog=str(row["changelog"] or ""),
            created_by=str(row["created_by"] or ""),
            created_at=str(row["created_at"] or ""),
            revision_id=str(row["revision_id"] or ""),
            status=str(row["status"] or ""),
        )
        for row in rows
    ]


def list_skill_approvals(
    conn,
    *,
    dialect: StoreDialect,
    slug: str,
) -> list[LifecycleApprovalRecord]:
    rows = dialect.fetchall(
        conn,
        f"""
        SELECT record_id, revision_id, action, actor, note, created_at
        FROM {dialect.qualify('skill_approvals')}
        WHERE slug = {dialect.placeholder(1)}
        ORDER BY created_at DESC, record_id DESC
        """,
        (slug,),
    )
    return records(LifecycleApprovalRecord, rows)


def get_latest_skill_approval_action(
    conn,
    *,
    dialect: StoreDialect,
    slug: str,
    revision_id: str,
) -> str:
    row = dialect.fetchone(
        conn,
        f"""
        SELECT action
        FROM {dialect.qualify('skill_approvals')}
        WHERE slug = {dialect.placeholder(1)} AND revision_id = {dialect.placeholder(2)}
        ORDER BY created_at DESC, record_id DESC
        LIMIT 1
        """,
        (slug, revision_id),
    )
    return str(row["action"]) if row is not None else ""


def append_skill_approval(
    conn,
    *,
    dialect: StoreDialect,
    slug: str,
    revision_id: str,
    action: str,
    actor: str,
    note: str = "",
) -> LifecycleApprovalRecord:
    now = utcnow_iso()
    record_id = f"{slug}|{revision_id}|{action}|{now}"
    dialect.execute(
        conn,
        f"""
        INSERT INTO {dialect.qualify('skill_approvals')} (
            record_id, slug, revision_id, action, actor, note, created_at
        ) VALUES (
            {dialect.placeholder(1)}, {dialect.placeholder(2)}, {dialect.placeholder(3)},
            {dialect.placeholder(4)}, {dialect.placeholder(5)}, {dialect.placeholder(6)},
            {dialect.placeholder(7)}
        )
        """,
        (record_id, slug, revision_id, action, actor, note, now),
    )
    return record(LifecycleApprovalRecord, {
        "record_id": record_id,
        "revision_id": revision_id,
        "action": action,
        "actor": actor,
        "note": note,
        "created_at": now,
    })


def set_skill_revision_status(
    conn,
    *,
    dialect: StoreDialect,
    slug: str,
    revision_id: str,
    status: str,
) -> None:
    dialect.execute(
        conn,
        f"""
        UPDATE {dialect.qualify('skill_revisions')}
        SET status = {dialect.placeholder(1)}
        WHERE slug = {dialect.placeholder(2)} AND revision_id = {dialect.placeholder(3)}
        """,
        (status, slug, revision_id),
    )


def set_published_skill_revision(
    conn,
    *,
    dialect: StoreDialect,
    slug: str,
    revision_id: str,
) -> None:
    dialect.execute(
        conn,
        f"""
        UPDATE {dialect.qualify('runtime_skills')}
        SET published_revision_id = {dialect.placeholder(1)}, updated_at = {dialect.placeholder(2)}
        WHERE slug = {dialect.placeholder(3)}
        """,
        (revision_id, utcnow_iso(), slug),
    )


def clear_published_skill_revision(
    conn,
    *,
    dialect: StoreDialect,
    slug: str,
) -> None:
    dialect.execute(
        conn,
        f"""
        UPDATE {dialect.qualify('runtime_skills')}
        SET published_revision_id = '', updated_at = {dialect.placeholder(1)}
        WHERE slug = {dialect.placeholder(2)}
        """,
        (utcnow_iso(), slug),
    )


def apply_skill_lifecycle_transition(
    conn,
    *,
    dialect: StoreDialect,
    slug: str,
    revision_id: str,
    set_status: str | None = None,
    published_pointer: Literal["unchanged", "set_active", "clear"] = "unchanged",
    approval_action: str | None = None,
    actor: str = "",
    note: str = "",
) -> LifecycleApprovalRecord | None:
    result: LifecycleApprovalRecord | None = None
    now = utcnow_iso()
    record_id = f"{slug}|{revision_id}|{approval_action}|{now}" if approval_action else ""
    if set_status is not None:
        set_skill_revision_status(conn, dialect=dialect, slug=slug, revision_id=revision_id, status=set_status)
    if published_pointer == "set_active":
        set_published_skill_revision(conn, dialect=dialect, slug=slug, revision_id=revision_id)
    elif published_pointer == "clear":
        clear_published_skill_revision(conn, dialect=dialect, slug=slug)
    if approval_action is not None:
        dialect.execute(
            conn,
            f"""
            INSERT INTO {dialect.qualify('skill_approvals')} (
                record_id, slug, revision_id, action, actor, note, created_at
            ) VALUES (
                {dialect.placeholder(1)}, {dialect.placeholder(2)}, {dialect.placeholder(3)},
                {dialect.placeholder(4)}, {dialect.placeholder(5)}, {dialect.placeholder(6)},
                {dialect.placeholder(7)}
            )
            """,
            (record_id, slug, revision_id, approval_action, actor, note, now),
        )
        result = record(LifecycleApprovalRecord, {
            "record_id": record_id,
            "revision_id": revision_id,
            "action": approval_action,
            "actor": actor,
            "note": note,
            "created_at": now,
        })
    return result


def replace_provider_guidance(
    conn,
    *,
    dialect: StoreDialect,
    track: ProviderGuidanceTrackRecord,
) -> None:
    _upsert_registry_guidance(conn, dialect=dialect, track=track, status="published", publish=True)


def upsert_provider_guidance_draft(
    conn,
    *,
    dialect: StoreDialect,
    track: ProviderGuidanceTrackRecord,
) -> None:
    _upsert_registry_guidance(conn, dialect=dialect, track=track, status="draft", publish=False)


def _upsert_registry_guidance(
    conn,
    *,
    dialect: StoreDialect,
    track: ProviderGuidanceTrackRecord,
    status: str,
    publish: bool,
) -> None:
    now = utcnow_iso()
    revision_id = _guidance_revision_id(track)
    existing = dialect.fetchone(
        conn,
        (
            f"SELECT published_revision_id FROM {dialect.qualify('provider_guidance')} "
            f"WHERE provider = {dialect.placeholder(1)} AND scope_kind = {dialect.placeholder(2)} AND scope_key = {dialect.placeholder(3)}"
        ),
        (track.provider, track.scope_kind, track.scope_key),
    )
    published_revision_id = revision_id if publish else str(existing.get("published_revision_id") or "") if existing else ""
    dialect.execute(
        conn,
        f"""
        INSERT INTO {dialect.qualify('provider_guidance')} (
            provider, scope_kind, scope_key, content, format, is_mutable,
            active_revision_id, published_revision_id, created_at, updated_at
        ) VALUES (
            {dialect.placeholder(1)}, {dialect.placeholder(2)}, {dialect.placeholder(3)},
            {dialect.placeholder(4)}, {dialect.placeholder(5)}, {dialect.placeholder(6)},
            {dialect.placeholder(7)}, {dialect.placeholder(8)}, {dialect.placeholder(9)},
            {dialect.placeholder(10)}
        )
        ON CONFLICT(provider, scope_kind, scope_key) DO UPDATE SET
            content = excluded.content,
            format = excluded.format,
            is_mutable = excluded.is_mutable,
            active_revision_id = excluded.active_revision_id,
            published_revision_id = excluded.published_revision_id,
            updated_at = excluded.updated_at
        """,
        (
            track.provider,
            track.scope_kind,
            track.scope_key,
            track.revision.content,
            track.revision.format,
            bool(track.is_mutable),
            revision_id,
            published_revision_id,
            now,
            now,
        ),
    )
    dialect.execute(
        conn,
        f"""
        INSERT INTO {dialect.qualify('guidance_revisions')} (
            revision_id, provider, scope_kind, scope_key, content, format,
            status, created_by, created_at
        ) VALUES (
            {dialect.placeholder(1)}, {dialect.placeholder(2)}, {dialect.placeholder(3)},
            {dialect.placeholder(4)}, {dialect.placeholder(5)}, {dialect.placeholder(6)},
            {dialect.placeholder(7)}, {dialect.placeholder(8)}, {dialect.placeholder(9)}
        )
        ON CONFLICT(revision_id) DO UPDATE SET
            content = excluded.content,
            format = excluded.format,
            status = excluded.status,
            created_by = excluded.created_by,
            created_at = excluded.created_at
        """,
        (
            revision_id,
            track.provider,
            track.scope_kind,
            track.scope_key,
            track.revision.content,
            track.revision.format,
            status,
            track.revision.created_by,
            track.revision.created_at or now,
        ),
    )


def get_provider_guidance(
    conn,
    *,
    dialect: StoreDialect,
    provider: str,
    scope_kind: str = "system",
    scope_key: str = "",
) -> ProviderGuidanceTrackRecord | None:
    row = dialect.fetchone(
        conn,
        f"""
        SELECT
            g.provider, g.scope_kind, g.scope_key, g.is_mutable,
            g.active_revision_id, g.published_revision_id,
            rev.content, rev.format, rev.created_by, rev.created_at,
            rev.status, rev.revision_id
        FROM {dialect.qualify('provider_guidance')} g
        JOIN {dialect.qualify('guidance_revisions')} rev ON rev.revision_id = g.active_revision_id
        WHERE g.provider = {dialect.placeholder(1)}
          AND g.scope_kind = {dialect.placeholder(2)}
          AND g.scope_key = {dialect.placeholder(3)}
        """,
        (provider, scope_kind, scope_key),
    )
    return None if row is None else _guidance_row_to_track(row)


def _runtime_provider_guidance(
    conn,
    *,
    dialect: StoreDialect,
    provider: str,
    scope_kind: str,
    scope_key: str,
) -> ProviderGuidanceTrackRecord | None:
    row = dialect.fetchone(
        conn,
        f"""
        SELECT
            g.provider, g.scope_kind, g.scope_key, g.is_mutable,
            g.active_revision_id, g.published_revision_id,
            rev.content, rev.format, rev.created_by, rev.created_at,
            rev.status, rev.revision_id
        FROM {dialect.qualify('provider_guidance')} g
        JOIN {dialect.qualify('guidance_revisions')} rev ON rev.revision_id = g.published_revision_id
        WHERE g.provider = {dialect.placeholder(1)}
          AND g.scope_kind = {dialect.placeholder(2)}
          AND g.scope_key = {dialect.placeholder(3)}
          AND g.published_revision_id != ''
        """,
        (provider, scope_kind, scope_key),
    )
    return None if row is None else _guidance_row_to_track(row)


def resolve_provider_guidance(
    conn,
    *,
    dialect: StoreDialect,
    provider: str,
    instance_key: str = "",
) -> ProviderGuidanceTrackRecord | None:
    if instance_key:
        match = _runtime_provider_guidance(
            conn,
            dialect=dialect,
            provider=provider,
            scope_kind="instance",
            scope_key=instance_key,
        )
        if match is not None:
            return match
    return _runtime_provider_guidance(
        conn,
        dialect=dialect,
        provider=provider,
        scope_kind="system",
        scope_key="",
    )


def list_provider_guidance_revisions(
    conn,
    *,
    dialect: StoreDialect,
    provider: str,
    scope_kind: str = "system",
    scope_key: str = "",
) -> list[ProviderGuidanceRevisionRecord]:
    rows = dialect.fetchall(
        conn,
        f"""
        SELECT revision_id, content, format, created_by, created_at, status
        FROM {dialect.qualify('guidance_revisions')}
        WHERE provider = {dialect.placeholder(1)}
          AND scope_kind = {dialect.placeholder(2)}
          AND scope_key = {dialect.placeholder(3)}
        ORDER BY created_at DESC, revision_id DESC
        """,
        (provider, scope_kind, scope_key),
    )
    return records(ProviderGuidanceRevisionRecord, rows)


def list_provider_guidance_approvals(
    conn,
    *,
    dialect: StoreDialect,
    provider: str,
    scope_kind: str = "system",
    scope_key: str = "",
) -> list[LifecycleApprovalRecord]:
    rows = dialect.fetchall(
        conn,
        f"""
        SELECT record_id, revision_id, action, actor, note, created_at
        FROM {dialect.qualify('guidance_approvals')}
        WHERE provider = {dialect.placeholder(1)}
          AND scope_kind = {dialect.placeholder(2)}
          AND scope_key = {dialect.placeholder(3)}
        ORDER BY created_at DESC, record_id DESC
        """,
        (provider, scope_kind, scope_key),
    )
    return records(LifecycleApprovalRecord, rows)


def get_latest_provider_guidance_approval_action(
    conn,
    *,
    dialect: StoreDialect,
    provider: str,
    revision_id: str,
    scope_kind: str = "system",
    scope_key: str = "",
) -> str:
    row = dialect.fetchone(
        conn,
        f"""
        SELECT action
        FROM {dialect.qualify('guidance_approvals')}
        WHERE provider = {dialect.placeholder(1)}
          AND scope_kind = {dialect.placeholder(2)}
          AND scope_key = {dialect.placeholder(3)}
          AND revision_id = {dialect.placeholder(4)}
        ORDER BY created_at DESC, record_id DESC
        LIMIT 1
        """,
        (provider, scope_kind, scope_key, revision_id),
    )
    return str(row["action"]) if row is not None else ""


def append_provider_guidance_approval(
    conn,
    *,
    dialect: StoreDialect,
    provider: str,
    revision_id: str,
    action: str,
    actor: str,
    note: str = "",
    scope_kind: str = "system",
    scope_key: str = "",
) -> LifecycleApprovalRecord:
    now = utcnow_iso()
    record_id = f"{provider}|{scope_kind}|{scope_key}|{revision_id}|{action}|{now}"
    dialect.execute(
        conn,
        f"""
        INSERT INTO {dialect.qualify('guidance_approvals')} (
            record_id, provider, scope_kind, scope_key, revision_id, action, actor, note, created_at
        ) VALUES (
            {dialect.placeholder(1)}, {dialect.placeholder(2)}, {dialect.placeholder(3)},
            {dialect.placeholder(4)}, {dialect.placeholder(5)}, {dialect.placeholder(6)},
            {dialect.placeholder(7)}, {dialect.placeholder(8)}, {dialect.placeholder(9)}
        )
        """,
        (record_id, provider, scope_kind, scope_key, revision_id, action, actor, note, now),
    )
    return record(LifecycleApprovalRecord, {
        "record_id": record_id,
        "revision_id": revision_id,
        "action": action,
        "actor": actor,
        "note": note,
        "created_at": now,
    })


def set_provider_guidance_revision_status(
    conn,
    *,
    dialect: StoreDialect,
    provider: str,
    revision_id: str,
    status: str,
    scope_kind: str = "system",
    scope_key: str = "",
) -> None:
    dialect.execute(
        conn,
        f"""
        UPDATE {dialect.qualify('guidance_revisions')}
        SET status = {dialect.placeholder(1)}
        WHERE provider = {dialect.placeholder(2)}
          AND scope_kind = {dialect.placeholder(3)}
          AND scope_key = {dialect.placeholder(4)}
          AND revision_id = {dialect.placeholder(5)}
        """,
        (status, provider, scope_kind, scope_key, revision_id),
    )


def set_published_provider_guidance_revision(
    conn,
    *,
    dialect: StoreDialect,
    provider: str,
    revision_id: str,
    scope_kind: str = "system",
    scope_key: str = "",
) -> None:
    dialect.execute(
        conn,
        f"""
        UPDATE {dialect.qualify('provider_guidance')}
        SET published_revision_id = {dialect.placeholder(1)}, updated_at = {dialect.placeholder(2)}
        WHERE provider = {dialect.placeholder(3)}
          AND scope_kind = {dialect.placeholder(4)}
          AND scope_key = {dialect.placeholder(5)}
        """,
        (revision_id, utcnow_iso(), provider, scope_kind, scope_key),
    )


def clear_published_provider_guidance_revision(
    conn,
    *,
    dialect: StoreDialect,
    provider: str,
    scope_kind: str = "system",
    scope_key: str = "",
) -> None:
    dialect.execute(
        conn,
        f"""
        UPDATE {dialect.qualify('provider_guidance')}
        SET published_revision_id = '', updated_at = {dialect.placeholder(1)}
        WHERE provider = {dialect.placeholder(2)}
          AND scope_kind = {dialect.placeholder(3)}
          AND scope_key = {dialect.placeholder(4)}
        """,
        (utcnow_iso(), provider, scope_kind, scope_key),
    )


def apply_provider_guidance_lifecycle_transition(
    conn,
    *,
    dialect: StoreDialect,
    provider: str,
    revision_id: str,
    set_status: str | None = None,
    published_pointer: Literal["unchanged", "set_active", "clear"] = "unchanged",
    approval_action: str | None = None,
    actor: str = "",
    note: str = "",
    scope_kind: str = "system",
    scope_key: str = "",
) -> LifecycleApprovalRecord | None:
    result: LifecycleApprovalRecord | None = None
    now = utcnow_iso()
    record_id = (
        f"{provider}|{scope_kind}|{scope_key}|{revision_id}|{approval_action}|{now}"
        if approval_action else ""
    )
    if set_status is not None:
        set_provider_guidance_revision_status(
            conn,
            dialect=dialect,
            provider=provider,
            revision_id=revision_id,
            status=set_status,
            scope_kind=scope_kind,
            scope_key=scope_key,
        )
    if published_pointer == "set_active":
        set_published_provider_guidance_revision(
            conn,
            dialect=dialect,
            provider=provider,
            revision_id=revision_id,
            scope_kind=scope_kind,
            scope_key=scope_key,
        )
    elif published_pointer == "clear":
        clear_published_provider_guidance_revision(
            conn,
            dialect=dialect,
            provider=provider,
            scope_kind=scope_kind,
            scope_key=scope_key,
        )
    if approval_action is not None:
        dialect.execute(
            conn,
            f"""
            INSERT INTO {dialect.qualify('guidance_approvals')} (
                record_id, provider, scope_kind, scope_key, revision_id, action, actor, note, created_at
            ) VALUES (
                {dialect.placeholder(1)}, {dialect.placeholder(2)}, {dialect.placeholder(3)},
                {dialect.placeholder(4)}, {dialect.placeholder(5)}, {dialect.placeholder(6)},
                {dialect.placeholder(7)}, {dialect.placeholder(8)}, {dialect.placeholder(9)}
            )
            """,
            (record_id, provider, scope_kind, scope_key, revision_id, approval_action, actor, note, now),
        )
        result = record(LifecycleApprovalRecord, {
            "record_id": record_id,
            "revision_id": revision_id,
            "action": approval_action,
            "actor": actor,
            "note": note,
            "created_at": now,
        })
    return result
