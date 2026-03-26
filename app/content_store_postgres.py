"""Postgres implementation of the runtime content store."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
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
from app.content_store_base import AbstractContentStore
from app.db.postgres import get_connection
from psycopg.rows import dict_row

_SCHEMA = "bot_content"
_SCHEMA_VERSION = 2

_INIT_V1_SQL = f"""\
CREATE SCHEMA IF NOT EXISTS {_SCHEMA};
CREATE TABLE IF NOT EXISTS {_SCHEMA}.skill_namespaces (
    skill_id TEXT PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    archived BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS {_SCHEMA}.skill_tracks (
    track_id TEXT PRIMARY KEY,
    skill_id TEXT NOT NULL REFERENCES {_SCHEMA}.skill_namespaces(skill_id) ON DELETE CASCADE,
    source_kind TEXT NOT NULL,
    source_uri TEXT NOT NULL DEFAULT '',
    owner_actor TEXT NOT NULL DEFAULT '',
    visibility TEXT NOT NULL DEFAULT 'shared',
    is_mutable BOOLEAN NOT NULL DEFAULT FALSE,
    active_revision_id TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    UNIQUE(skill_id, source_kind, source_uri, owner_actor)
);
CREATE TABLE IF NOT EXISTS {_SCHEMA}.skill_revisions (
    revision_id TEXT PRIMARY KEY,
    track_id TEXT NOT NULL REFERENCES {_SCHEMA}.skill_tracks(track_id) ON DELETE CASCADE,
    version_label TEXT NOT NULL DEFAULT '',
    digest TEXT NOT NULL,
    instruction_body TEXT NOT NULL DEFAULT '',
    requirements_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    provider_config_json JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    changelog TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS {_SCHEMA}.skill_files (
    revision_id TEXT NOT NULL REFERENCES {_SCHEMA}.skill_revisions(revision_id) ON DELETE CASCADE,
    relative_path TEXT NOT NULL,
    content_text TEXT NOT NULL DEFAULT '',
    content_type TEXT NOT NULL DEFAULT 'text/plain',
    executable BOOLEAN NOT NULL DEFAULT FALSE,
    digest TEXT NOT NULL,
    PRIMARY KEY(revision_id, relative_path)
);
CREATE TABLE IF NOT EXISTS {_SCHEMA}.provider_guidance_tracks (
    guidance_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    scope_kind TEXT NOT NULL DEFAULT 'system',
    scope_key TEXT NOT NULL DEFAULT '',
    is_mutable BOOLEAN NOT NULL DEFAULT FALSE,
    active_revision_id TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    UNIQUE(provider, scope_kind, scope_key)
);
CREATE TABLE IF NOT EXISTS {_SCHEMA}.provider_guidance_revisions (
    revision_id TEXT PRIMARY KEY,
    guidance_id TEXT NOT NULL REFERENCES {_SCHEMA}.provider_guidance_tracks(guidance_id) ON DELETE CASCADE,
    digest TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    format TEXT NOT NULL DEFAULT 'markdown',
    created_by TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL
);
"""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_json(raw, default):
    if raw is None:
        return default
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


class PostgresContentStore(AbstractContentStore):
    def __init__(
        self,
        database_url: str,
        *,
        pool_min: int = 1,
        pool_max: int = 10,
        connect_timeout: int = 10,
    ) -> None:
        self._database_url = database_url
        self._pool_min = pool_min
        self._pool_max = pool_max
        self._connect_timeout = connect_timeout
        self._schema_ready = False

    @contextmanager
    def _connect(self):
        with get_connection(
            self._database_url,
            min_size=self._pool_min,
            max_size=self._pool_max,
            connect_timeout=self._connect_timeout,
        ) as conn:
            self._ensure_schema(conn)
            yield conn

    def _ensure_schema(self, conn) -> None:
        if self._schema_ready:
            return
        with conn.cursor() as cur:
            cur.execute(_INIT_V1_SQL)
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {_SCHEMA}.schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            cur.execute(f"SELECT COALESCE(MAX(version), 0) AS version FROM {_SCHEMA}.schema_migrations")
            row = cur.fetchone()
            version = int(row[0] if row else 0)
            if version == 0:
                cur.execute(
                    f"INSERT INTO {_SCHEMA}.schema_migrations(version) VALUES (1) ON CONFLICT (version) DO NOTHING"
                )
                version = 1
            if version < 2:
                self._migrate_v2(cur)
                cur.execute(
                    f"INSERT INTO {_SCHEMA}.schema_migrations(version) VALUES (2) ON CONFLICT (version) DO NOTHING"
                )
        conn.commit()
        self._schema_ready = True

    def _migrate_v2(self, cur) -> None:
        cur.execute(
            f"ALTER TABLE {_SCHEMA}.skill_tracks ADD COLUMN IF NOT EXISTS published_revision_id TEXT NOT NULL DEFAULT ''"
        )
        cur.execute(
            f"ALTER TABLE {_SCHEMA}.skill_revisions ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'published'"
        )
        cur.execute(
            f"ALTER TABLE {_SCHEMA}.provider_guidance_tracks ADD COLUMN IF NOT EXISTS published_revision_id TEXT NOT NULL DEFAULT ''"
        )
        cur.execute(
            f"ALTER TABLE {_SCHEMA}.provider_guidance_revisions ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'published'"
        )
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {_SCHEMA}.skill_approval_records (
                record_id TEXT PRIMARY KEY,
                track_id TEXT NOT NULL REFERENCES {_SCHEMA}.skill_tracks(track_id) ON DELETE CASCADE,
                revision_id TEXT NOT NULL REFERENCES {_SCHEMA}.skill_revisions(revision_id) ON DELETE CASCADE,
                action TEXT NOT NULL,
                actor TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMPTZ NOT NULL
            )
            """
        )
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {_SCHEMA}.provider_guidance_approval_records (
                record_id TEXT PRIMARY KEY,
                guidance_id TEXT NOT NULL REFERENCES {_SCHEMA}.provider_guidance_tracks(guidance_id) ON DELETE CASCADE,
                revision_id TEXT NOT NULL REFERENCES {_SCHEMA}.provider_guidance_revisions(revision_id) ON DELETE CASCADE,
                action TEXT NOT NULL,
                actor TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMPTZ NOT NULL
            )
            """
        )
        cur.execute(
            f"CREATE INDEX IF NOT EXISTS idx_skill_approval_records_track_id ON {_SCHEMA}.skill_approval_records(track_id, created_at DESC)"
        )
        cur.execute(
            f"CREATE INDEX IF NOT EXISTS idx_guidance_approval_records_guidance_id ON {_SCHEMA}.provider_guidance_approval_records(guidance_id, created_at DESC)"
        )
        cur.execute(
            f"UPDATE {_SCHEMA}.skill_tracks SET published_revision_id = active_revision_id WHERE published_revision_id = ''"
        )
        cur.execute(
            f"UPDATE {_SCHEMA}.skill_revisions SET status = 'published' WHERE status = ''"
        )
        cur.execute(
            f"UPDATE {_SCHEMA}.provider_guidance_tracks SET published_revision_id = active_revision_id WHERE published_revision_id = ''"
        )
        cur.execute(
            f"UPDATE {_SCHEMA}.provider_guidance_revisions SET status = 'published' WHERE status = ''"
        )

    def _skill_id(self, slug: str) -> str:
        return f"skill:{slug}"

    def _track_id(self, record: RuntimeSkillTrackRecord) -> str:
        return "|".join((record.slug, record.source_kind, record.source_uri, record.owner_actor))

    def _guidance_id(self, record: ProviderGuidanceTrackRecord) -> str:
        return "|".join((record.provider, record.scope_kind, record.scope_key))

    def _skill_revision_id(self, record: RuntimeSkillTrackRecord) -> str:
        return record.revision.revision_id or f"{self._track_id(record)}|{record.revision.digest}"

    def _guidance_revision_id(self, record: ProviderGuidanceTrackRecord) -> str:
        return record.revision.revision_id or f"{self._guidance_id(record)}|{record.revision.digest}"

    def _upsert_skill_track(
        self,
        record: RuntimeSkillTrackRecord,
        *,
        status: str,
        publish: bool,
    ) -> None:
        now = _utcnow()
        skill_id = self._skill_id(record.slug)
        track_id = self._track_id(record)
        revision_id = self._skill_revision_id(record)
        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    f"SELECT published_revision_id FROM {_SCHEMA}.skill_tracks WHERE track_id = %s",
                    (track_id,),
                )
                existing = cur.fetchone()
                published_revision_id = revision_id if publish else (existing["published_revision_id"] if existing else "")
                cur.execute(
                    f"""
                    INSERT INTO {_SCHEMA}.skill_namespaces (
                        skill_id, slug, display_name, description, archived, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s::timestamptz, %s::timestamptz)
                    ON CONFLICT(skill_id) DO UPDATE SET
                        display_name = EXCLUDED.display_name,
                        description = EXCLUDED.description,
                        archived = EXCLUDED.archived,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (
                        skill_id,
                        record.slug,
                        record.display_name,
                        record.description,
                        record.archived,
                        now,
                        now,
                    ),
                )
                cur.execute(
                    f"""
                    INSERT INTO {_SCHEMA}.skill_tracks (
                        track_id, skill_id, source_kind, source_uri, owner_actor, visibility,
                        is_mutable, active_revision_id, published_revision_id, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::timestamptz, %s::timestamptz)
                    ON CONFLICT(track_id) DO UPDATE SET
                        visibility = EXCLUDED.visibility,
                        is_mutable = EXCLUDED.is_mutable,
                        active_revision_id = EXCLUDED.active_revision_id,
                        published_revision_id = EXCLUDED.published_revision_id,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (
                        track_id,
                        skill_id,
                        record.source_kind,
                        record.source_uri,
                        record.owner_actor,
                        record.visibility,
                        record.is_mutable,
                        revision_id,
                        published_revision_id,
                        now,
                        now,
                    ),
                )
                cur.execute(
                    f"""
                    INSERT INTO {_SCHEMA}.skill_revisions (
                        revision_id, track_id, version_label, digest, instruction_body,
                        requirements_json, provider_config_json, changelog, created_by, created_at, status
                    ) VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s::timestamptz, %s)
                    ON CONFLICT(revision_id) DO UPDATE SET
                        version_label = EXCLUDED.version_label,
                        instruction_body = EXCLUDED.instruction_body,
                        requirements_json = EXCLUDED.requirements_json,
                        provider_config_json = EXCLUDED.provider_config_json,
                        changelog = EXCLUDED.changelog,
                        created_by = EXCLUDED.created_by,
                        status = EXCLUDED.status
                    """,
                    (
                        revision_id,
                        track_id,
                        record.revision.version_label,
                        record.revision.digest,
                        record.revision.instruction_body,
                        json.dumps(record.revision.requirements, sort_keys=True),
                        json.dumps(record.revision.provider_config, sort_keys=True),
                        record.revision.changelog,
                        record.revision.created_by,
                        record.revision.created_at or now,
                        status,
                    ),
                )
                cur.execute(f"DELETE FROM {_SCHEMA}.skill_files WHERE revision_id = %s", (revision_id,))
                for file_record in record.revision.files:
                    cur.execute(
                        f"""
                        INSERT INTO {_SCHEMA}.skill_files (
                            revision_id, relative_path, content_text, content_type, executable, digest
                        ) VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            revision_id,
                            file_record.relative_path,
                            file_record.content_text,
                            file_record.content_type,
                            file_record.executable,
                            file_record.digest,
                        ),
                    )
            conn.commit()

    def replace_skill_track(self, record: RuntimeSkillTrackRecord) -> None:
        self._upsert_skill_track(record, status="published", publish=True)

    def upsert_skill_draft(self, record: RuntimeSkillTrackRecord) -> None:
        self._upsert_skill_track(record, status="draft", publish=False)

    def delete_skill_track(
        self,
        slug: str,
        *,
        source_kind: str,
        source_uri: str = "",
        owner_actor: str = "",
    ) -> bool:
        track_id = "|".join((slug, source_kind, source_uri, owner_actor))
        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    f"DELETE FROM {_SCHEMA}.skill_tracks WHERE track_id = %s",
                    (track_id,),
                )
                deleted = cur.rowcount > 0
                cur.execute(
                    f"""
                    DELETE FROM {_SCHEMA}.skill_namespaces ns
                    WHERE ns.slug = %s
                      AND NOT EXISTS (
                            SELECT 1
                            FROM {_SCHEMA}.skill_tracks tr
                            WHERE tr.skill_id = ns.skill_id
                      )
                    """,
                    (slug,),
                )
            conn.commit()
        return deleted

    def _rows_for_slug(self, slug: str, *, runtime_only: bool):
        revision_ref = (
            "CASE WHEN tr.published_revision_id != '' THEN tr.published_revision_id ELSE tr.active_revision_id END"
            if runtime_only else
            "tr.active_revision_id"
        )
        extra_where = "AND tr.published_revision_id != ''" if runtime_only else ""
        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    f"""
                    SELECT
                        ns.slug,
                        ns.display_name,
                        ns.description,
                        ns.archived,
                        tr.track_id,
                        tr.source_kind,
                        tr.source_uri,
                        tr.owner_actor,
                        tr.visibility,
                        tr.is_mutable,
                        tr.active_revision_id,
                        tr.published_revision_id,
                        rev.revision_id,
                        rev.version_label,
                        rev.digest,
                        rev.instruction_body,
                        rev.requirements_json,
                        rev.provider_config_json,
                        rev.changelog,
                        rev.created_by,
                        rev.created_at,
                        rev.status
                    FROM {_SCHEMA}.skill_namespaces ns
                    JOIN {_SCHEMA}.skill_tracks tr ON tr.skill_id = ns.skill_id
                    JOIN {_SCHEMA}.skill_revisions rev ON rev.revision_id = {revision_ref}
                    WHERE ns.slug = %s
                    {extra_where}
                    ORDER BY tr.source_kind ASC, tr.updated_at DESC
                    """,
                    (slug,),
                )
                return cur.fetchall()

    def _files_for_revision(self, revision_id: str) -> tuple[SkillFileRecord, ...]:
        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    f"""
                    SELECT relative_path, content_text, content_type, executable
                    FROM {_SCHEMA}.skill_files
                    WHERE revision_id = %s
                    ORDER BY relative_path ASC
                    """,
                    (revision_id,),
                )
                rows = cur.fetchall()
        return tuple(
            SkillFileRecord(
                relative_path=row["relative_path"],
                content_text=row["content_text"],
                content_type=row["content_type"],
                executable=bool(row["executable"]),
            )
            for row in rows
        )

    def _record_from_row(self, row) -> RuntimeSkillTrackRecord:
        revision = SkillRevisionRecord(
            instruction_body=row["instruction_body"],
            requirements=_parse_json(row["requirements_json"], []),
            provider_config=_parse_json(row["provider_config_json"], {}),
            files=self._files_for_revision(row["revision_id"]),
            version_label=row["version_label"],
            changelog=row["changelog"],
            created_by=row["created_by"],
            created_at=str(row["created_at"]),
            revision_id=row["revision_id"],
            status=row["status"],
        )
        return RuntimeSkillTrackRecord(
            slug=row["slug"],
            display_name=row["display_name"],
            description=row["description"],
            source_kind=row["source_kind"],
            revision=revision,
            source_uri=row["source_uri"],
            owner_actor=row["owner_actor"],
            visibility=row["visibility"],
            is_mutable=bool(row["is_mutable"]),
            archived=bool(row["archived"]),
            active_revision_id=row["active_revision_id"],
            published_revision_id=row["published_revision_id"],
        )

    def list_skill_tracks(self, slug: str) -> list[RuntimeSkillTrackRecord]:
        records = [self._record_from_row(row) for row in self._rows_for_slug(slug, runtime_only=False)]
        return sorted(records, key=lambda item: skill_precedence(item.source_kind), reverse=True)

    def resolve_skill(self, slug: str) -> RuntimeSkillTrackRecord | None:
        tracks = self.list_skill_tracks(slug)
        return tracks[0] if tracks else None

    def resolve_runtime_skill(self, slug: str) -> RuntimeSkillTrackRecord | None:
        records = [self._record_from_row(row) for row in self._rows_for_slug(slug, runtime_only=True)]
        records = sorted(records, key=lambda item: skill_precedence(item.source_kind), reverse=True)
        return records[0] if records else None

    def _summaries(self, *, runtime_only: bool) -> list[RuntimeSkillSummary]:
        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(f"SELECT slug FROM {_SCHEMA}.skill_namespaces ORDER BY lower(slug)")
                rows = cur.fetchall()
        summaries: list[RuntimeSkillSummary] = []
        resolver = self.resolve_runtime_skill if runtime_only else self.resolve_skill
        for row in rows:
            record = resolver(row["slug"])
            if record is None:
                continue
            summaries.append(
                RuntimeSkillSummary(
                    slug=record.slug,
                    display_name=record.display_name,
                    description=record.description,
                    source_kind=record.source_kind,
                    source_uri=record.source_uri,
                    visibility=record.visibility,
                    is_mutable=record.is_mutable,
                    digest=record.revision.digest,
                    status=record.revision.status,
                    runtime_available=bool(record.published_revision_id) or not record.is_mutable,
                    has_unpublished_changes=bool(record.published_revision_id)
                    and record.published_revision_id != record.active_revision_id,
                )
            )
        return summaries

    def list_skill_summaries(self) -> list[RuntimeSkillSummary]:
        return self._summaries(runtime_only=False)

    def list_runtime_skill_summaries(self) -> list[RuntimeSkillSummary]:
        return self._summaries(runtime_only=True)

    def _custom_track_row(self, slug: str):
        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    f"""
                    SELECT tr.track_id, tr.active_revision_id, tr.published_revision_id
                    FROM {_SCHEMA}.skill_tracks tr
                    JOIN {_SCHEMA}.skill_namespaces ns ON ns.skill_id = tr.skill_id
                    WHERE ns.slug = %s AND tr.source_kind = 'custom'
                    ORDER BY tr.updated_at DESC
                    LIMIT 1
                    """,
                    (slug,),
                )
                return cur.fetchone()

    def list_skill_revisions(self, slug: str) -> list[SkillRevisionRecord]:
        track = self._custom_track_row(slug)
        if track is None:
            return []
        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    f"""
                    SELECT revision_id, version_label, instruction_body, requirements_json, provider_config_json,
                           changelog, created_by, created_at, status
                    FROM {_SCHEMA}.skill_revisions
                    WHERE track_id = %s
                    ORDER BY created_at DESC, revision_id DESC
                    """,
                    (track["track_id"],),
                )
                rows = cur.fetchall()
        return [
            SkillRevisionRecord(
                instruction_body=row["instruction_body"],
                requirements=_parse_json(row["requirements_json"], []),
                provider_config=_parse_json(row["provider_config_json"], {}),
                files=self._files_for_revision(row["revision_id"]),
                version_label=row["version_label"],
                changelog=row["changelog"],
                created_by=row["created_by"],
                created_at=str(row["created_at"]),
                revision_id=row["revision_id"],
                status=row["status"],
            )
            for row in rows
        ]

    def list_skill_approvals(self, slug: str) -> list[LifecycleApprovalRecord]:
        track = self._custom_track_row(slug)
        if track is None:
            return []
        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    f"""
                    SELECT record_id, revision_id, action, actor, note, created_at
                    FROM {_SCHEMA}.skill_approval_records
                    WHERE track_id = %s
                    ORDER BY created_at DESC, record_id DESC
                    """,
                    (track["track_id"],),
                )
                rows = cur.fetchall()
        return [
            LifecycleApprovalRecord(
                record_id=row["record_id"],
                revision_id=row["revision_id"],
                action=row["action"],
                actor=row["actor"],
                note=row["note"],
                created_at=str(row["created_at"]),
            )
            for row in rows
        ]

    def get_latest_skill_approval_action(self, slug: str, revision_id: str) -> str:
        track = self._custom_track_row(slug)
        if track is None:
            return ""
        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    f"""
                    SELECT action
                    FROM {_SCHEMA}.skill_approval_records
                    WHERE track_id = %s AND revision_id = %s
                    ORDER BY created_at DESC, record_id DESC
                    LIMIT 1
                    """,
                    (track["track_id"], revision_id),
                )
                row = cur.fetchone()
        return str(row["action"]) if row is not None else ""

    def append_skill_approval(
        self,
        slug: str,
        revision_id: str,
        *,
        action: str,
        actor: str,
        note: str = "",
    ) -> LifecycleApprovalRecord:
        track = self._custom_track_row(slug)
        if track is None:
            raise KeyError(f"Unknown custom skill: {slug}")
        now = _utcnow()
        record_id = f"{track['track_id']}|{revision_id}|{action}|{now}"
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO {_SCHEMA}.skill_approval_records (
                        record_id, track_id, revision_id, action, actor, note, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s::timestamptz)
                    """,
                    (record_id, track["track_id"], revision_id, action, actor, note, now),
                )
            conn.commit()
        return LifecycleApprovalRecord(
            record_id=record_id,
            revision_id=revision_id,
            action=action,
            actor=actor,
            note=note,
            created_at=now,
        )

    def set_skill_revision_status(self, slug: str, revision_id: str, status: str) -> None:
        track = self._custom_track_row(slug)
        if track is None:
            raise KeyError(f"Unknown custom skill: {slug}")
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE {_SCHEMA}.skill_revisions SET status = %s WHERE track_id = %s AND revision_id = %s",
                    (status, track["track_id"], revision_id),
                )
            conn.commit()

    def set_published_skill_revision(self, slug: str, revision_id: str) -> None:
        track = self._custom_track_row(slug)
        if track is None:
            raise KeyError(f"Unknown custom skill: {slug}")
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    UPDATE {_SCHEMA}.skill_tracks
                    SET published_revision_id = %s, updated_at = %s::timestamptz
                    WHERE track_id = %s
                    """,
                    (revision_id, _utcnow(), track["track_id"]),
                )
            conn.commit()

    def clear_published_skill_revision(self, slug: str) -> None:
        track = self._custom_track_row(slug)
        if track is None:
            raise KeyError(f"Unknown custom skill: {slug}")
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    UPDATE {_SCHEMA}.skill_tracks
                    SET published_revision_id = '', updated_at = %s::timestamptz
                    WHERE track_id = %s
                    """,
                    (_utcnow(), track["track_id"]),
                )
            conn.commit()

    def apply_skill_lifecycle_transition(
        self,
        slug: str,
        revision_id: str,
        *,
        set_status: str | None = None,
        published_pointer: Literal["unchanged", "set_active", "clear"] = "unchanged",
        approval_action: str | None = None,
        actor: str = "",
        note: str = "",
    ) -> LifecycleApprovalRecord | None:
        track = self._custom_track_row(slug)
        if track is None:
            raise KeyError(f"Unknown custom skill: {slug}")
        now = _utcnow()
        record_id = (
            f"{track['track_id']}|{revision_id}|{approval_action}|{now}"
            if approval_action is not None else
            ""
        )
        record: LifecycleApprovalRecord | None = None
        with self._connect() as conn:
            try:
                with conn.cursor() as cur:
                    if set_status is not None:
                        cur.execute(
                            f"UPDATE {_SCHEMA}.skill_revisions SET status = %s WHERE track_id = %s AND revision_id = %s",
                            (set_status, track["track_id"], revision_id),
                        )
                    if published_pointer == "set_active":
                        cur.execute(
                            f"""
                            UPDATE {_SCHEMA}.skill_tracks
                            SET published_revision_id = %s, updated_at = %s::timestamptz
                            WHERE track_id = %s
                            """,
                            (revision_id, now, track["track_id"]),
                        )
                    elif published_pointer == "clear":
                        cur.execute(
                            f"""
                            UPDATE {_SCHEMA}.skill_tracks
                            SET published_revision_id = '', updated_at = %s::timestamptz
                            WHERE track_id = %s
                            """,
                            (now, track["track_id"]),
                        )
                    if approval_action is not None:
                        cur.execute(
                            f"""
                            INSERT INTO {_SCHEMA}.skill_approval_records (
                                record_id, track_id, revision_id, action, actor, note, created_at
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s::timestamptz)
                            """,
                            (record_id, track["track_id"], revision_id, approval_action, actor, note, now),
                        )
                        record = LifecycleApprovalRecord(
                            record_id=record_id,
                            revision_id=revision_id,
                            action=approval_action,
                            actor=actor,
                            note=note,
                            created_at=now,
                        )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return record

    def _upsert_provider_guidance(
        self,
        record: ProviderGuidanceTrackRecord,
        *,
        status: str,
        publish: bool,
    ) -> None:
        now = _utcnow()
        guidance_id = self._guidance_id(record)
        revision_id = self._guidance_revision_id(record)
        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    f"SELECT published_revision_id FROM {_SCHEMA}.provider_guidance_tracks WHERE guidance_id = %s",
                    (guidance_id,),
                )
                existing = cur.fetchone()
                published_revision_id = revision_id if publish else (existing["published_revision_id"] if existing else "")
                cur.execute(
                    f"""
                    INSERT INTO {_SCHEMA}.provider_guidance_tracks (
                        guidance_id, provider, scope_kind, scope_key, is_mutable,
                        active_revision_id, published_revision_id, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::timestamptz, %s::timestamptz)
                    ON CONFLICT(guidance_id) DO UPDATE SET
                        is_mutable = EXCLUDED.is_mutable,
                        active_revision_id = EXCLUDED.active_revision_id,
                        published_revision_id = EXCLUDED.published_revision_id,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (
                        guidance_id,
                        record.provider,
                        record.scope_kind,
                        record.scope_key,
                        record.is_mutable,
                        revision_id,
                        published_revision_id,
                        now,
                        now,
                    ),
                )
                cur.execute(
                    f"""
                    INSERT INTO {_SCHEMA}.provider_guidance_revisions (
                        revision_id, guidance_id, digest, content, format, created_by, created_at, status
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s::timestamptz, %s)
                    ON CONFLICT(revision_id) DO UPDATE SET
                        content = EXCLUDED.content,
                        format = EXCLUDED.format,
                        created_by = EXCLUDED.created_by,
                        status = EXCLUDED.status
                    """,
                    (
                        revision_id,
                        guidance_id,
                        record.revision.digest,
                        record.revision.content,
                        record.revision.format,
                        record.revision.created_by,
                        record.revision.created_at or now,
                        status,
                    ),
                )
            conn.commit()

    def replace_provider_guidance(self, record: ProviderGuidanceTrackRecord) -> None:
        self._upsert_provider_guidance(record, status="published", publish=True)

    def upsert_provider_guidance_draft(self, record: ProviderGuidanceTrackRecord) -> None:
        self._upsert_provider_guidance(record, status="draft", publish=False)

    def get_provider_guidance(
        self,
        provider: str,
        *,
        scope_kind: str = "system",
        scope_key: str = "",
    ) -> ProviderGuidanceTrackRecord | None:
        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    f"""
                    SELECT
                        tr.provider,
                        tr.scope_kind,
                        tr.scope_key,
                        tr.is_mutable,
                        tr.active_revision_id,
                        tr.published_revision_id,
                        rev.content,
                        rev.format,
                        rev.created_by,
                        rev.created_at,
                        rev.status,
                        rev.revision_id
                    FROM {_SCHEMA}.provider_guidance_tracks tr
                    JOIN {_SCHEMA}.provider_guidance_revisions rev ON rev.revision_id = tr.active_revision_id
                    WHERE tr.provider = %s AND tr.scope_kind = %s AND tr.scope_key = %s
                    """,
                    (provider, scope_kind, scope_key),
                )
                row = cur.fetchone()
        if row is None:
            return None
        return ProviderGuidanceTrackRecord(
            provider=row["provider"],
            scope_kind=row["scope_kind"],
            scope_key=row["scope_key"],
            is_mutable=bool(row["is_mutable"]),
            active_revision_id=row["active_revision_id"],
            published_revision_id=row["published_revision_id"],
            revision=ProviderGuidanceRevisionRecord(
                content=row["content"],
                format=row["format"],
                created_by=row["created_by"],
                created_at=str(row["created_at"]),
                revision_id=row["revision_id"],
                status=row["status"],
            ),
        )

    def _runtime_provider_guidance(
        self,
        provider: str,
        *,
        scope_kind: str,
        scope_key: str,
    ) -> ProviderGuidanceTrackRecord | None:
        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    f"""
                    SELECT
                        tr.provider,
                        tr.scope_kind,
                        tr.scope_key,
                        tr.is_mutable,
                        tr.active_revision_id,
                        tr.published_revision_id,
                        rev.content,
                        rev.format,
                        rev.created_by,
                        rev.created_at,
                        rev.status,
                        rev.revision_id
                    FROM {_SCHEMA}.provider_guidance_tracks tr
                    JOIN {_SCHEMA}.provider_guidance_revisions rev ON rev.revision_id = tr.published_revision_id
                    WHERE tr.provider = %s AND tr.scope_kind = %s AND tr.scope_key = %s AND tr.published_revision_id != ''
                    """,
                    (provider, scope_kind, scope_key),
                )
                row = cur.fetchone()
        if row is None:
            return None
        return ProviderGuidanceTrackRecord(
            provider=row["provider"],
            scope_kind=row["scope_kind"],
            scope_key=row["scope_key"],
            is_mutable=bool(row["is_mutable"]),
            active_revision_id=row["active_revision_id"],
            published_revision_id=row["published_revision_id"],
            revision=ProviderGuidanceRevisionRecord(
                content=row["content"],
                format=row["format"],
                created_by=row["created_by"],
                created_at=str(row["created_at"]),
                revision_id=row["revision_id"],
                status=row["status"],
            ),
        )

    def resolve_provider_guidance(
        self,
        provider: str,
        *,
        instance_key: str = "",
    ) -> ProviderGuidanceTrackRecord | None:
        if instance_key:
            match = self._runtime_provider_guidance(
                provider,
                scope_kind="instance",
                scope_key=instance_key,
            )
            if match is not None:
                return match
        return self._runtime_provider_guidance(provider, scope_kind="system", scope_key="")

    def _guidance_track_row(
        self,
        provider: str,
        *,
        scope_kind: str,
        scope_key: str,
    ):
        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    f"""
                    SELECT guidance_id, active_revision_id, published_revision_id
                    FROM {_SCHEMA}.provider_guidance_tracks
                    WHERE provider = %s AND scope_kind = %s AND scope_key = %s
                    """,
                    (provider, scope_kind, scope_key),
                )
                return cur.fetchone()

    def list_provider_guidance_revisions(
        self,
        provider: str,
        *,
        scope_kind: str = "system",
        scope_key: str = "",
    ) -> list[ProviderGuidanceRevisionRecord]:
        track = self._guidance_track_row(provider, scope_kind=scope_kind, scope_key=scope_key)
        if track is None:
            return []
        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    f"""
                    SELECT revision_id, content, format, created_by, created_at, status
                    FROM {_SCHEMA}.provider_guidance_revisions
                    WHERE guidance_id = %s
                    ORDER BY created_at DESC, revision_id DESC
                    """,
                    (track["guidance_id"],),
                )
                rows = cur.fetchall()
        return [
            ProviderGuidanceRevisionRecord(
                content=row["content"],
                format=row["format"],
                created_by=row["created_by"],
                created_at=str(row["created_at"]),
                revision_id=row["revision_id"],
                status=row["status"],
            )
            for row in rows
        ]

    def list_provider_guidance_approvals(
        self,
        provider: str,
        *,
        scope_kind: str = "system",
        scope_key: str = "",
    ) -> list[LifecycleApprovalRecord]:
        track = self._guidance_track_row(provider, scope_kind=scope_kind, scope_key=scope_key)
        if track is None:
            return []
        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    f"""
                    SELECT record_id, revision_id, action, actor, note, created_at
                    FROM {_SCHEMA}.provider_guidance_approval_records
                    WHERE guidance_id = %s
                    ORDER BY created_at DESC, record_id DESC
                    """,
                    (track["guidance_id"],),
                )
                rows = cur.fetchall()
        return [
            LifecycleApprovalRecord(
                record_id=row["record_id"],
                revision_id=row["revision_id"],
                action=row["action"],
                actor=row["actor"],
                note=row["note"],
                created_at=str(row["created_at"]),
            )
            for row in rows
        ]

    def get_latest_provider_guidance_approval_action(
        self,
        provider: str,
        revision_id: str,
        *,
        scope_kind: str = "system",
        scope_key: str = "",
    ) -> str:
        track = self._guidance_track_row(provider, scope_kind=scope_kind, scope_key=scope_key)
        if track is None:
            return ""
        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    f"""
                    SELECT action
                    FROM {_SCHEMA}.provider_guidance_approval_records
                    WHERE guidance_id = %s AND revision_id = %s
                    ORDER BY created_at DESC, record_id DESC
                    LIMIT 1
                    """,
                    (track["guidance_id"], revision_id),
                )
                row = cur.fetchone()
        return str(row["action"]) if row is not None else ""

    def append_provider_guidance_approval(
        self,
        provider: str,
        revision_id: str,
        *,
        action: str,
        actor: str,
        note: str = "",
        scope_kind: str = "system",
        scope_key: str = "",
    ) -> LifecycleApprovalRecord:
        track = self._guidance_track_row(provider, scope_kind=scope_kind, scope_key=scope_key)
        if track is None:
            raise KeyError(f"Unknown provider guidance: {provider}/{scope_kind}/{scope_key}")
        now = _utcnow()
        record_id = f"{track['guidance_id']}|{revision_id}|{action}|{now}"
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO {_SCHEMA}.provider_guidance_approval_records (
                        record_id, guidance_id, revision_id, action, actor, note, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s::timestamptz)
                    """,
                    (record_id, track["guidance_id"], revision_id, action, actor, note, now),
                )
            conn.commit()
        return LifecycleApprovalRecord(
            record_id=record_id,
            revision_id=revision_id,
            action=action,
            actor=actor,
            note=note,
            created_at=now,
        )

    def set_provider_guidance_revision_status(
        self,
        provider: str,
        revision_id: str,
        status: str,
        *,
        scope_kind: str = "system",
        scope_key: str = "",
    ) -> None:
        track = self._guidance_track_row(provider, scope_kind=scope_kind, scope_key=scope_key)
        if track is None:
            raise KeyError(f"Unknown provider guidance: {provider}/{scope_kind}/{scope_key}")
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    UPDATE {_SCHEMA}.provider_guidance_revisions
                    SET status = %s
                    WHERE guidance_id = %s AND revision_id = %s
                    """,
                    (status, track["guidance_id"], revision_id),
                )
            conn.commit()

    def set_published_provider_guidance_revision(
        self,
        provider: str,
        revision_id: str,
        *,
        scope_kind: str = "system",
        scope_key: str = "",
    ) -> None:
        track = self._guidance_track_row(provider, scope_kind=scope_kind, scope_key=scope_key)
        if track is None:
            raise KeyError(f"Unknown provider guidance: {provider}/{scope_kind}/{scope_key}")
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    UPDATE {_SCHEMA}.provider_guidance_tracks
                    SET published_revision_id = %s, updated_at = %s::timestamptz
                    WHERE guidance_id = %s
                    """,
                    (revision_id, _utcnow(), track["guidance_id"]),
                )
            conn.commit()

    def clear_published_provider_guidance_revision(
        self,
        provider: str,
        *,
        scope_kind: str = "system",
        scope_key: str = "",
    ) -> None:
        track = self._guidance_track_row(provider, scope_kind=scope_kind, scope_key=scope_key)
        if track is None:
            raise KeyError(f"Unknown provider guidance: {provider}/{scope_kind}/{scope_key}")
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    UPDATE {_SCHEMA}.provider_guidance_tracks
                    SET published_revision_id = '', updated_at = %s::timestamptz
                    WHERE guidance_id = %s
                    """,
                    (_utcnow(), track["guidance_id"]),
                )
            conn.commit()

    def apply_provider_guidance_lifecycle_transition(
        self,
        provider: str,
        revision_id: str,
        *,
        set_status: str | None = None,
        published_pointer: Literal["unchanged", "set_active", "clear"] = "unchanged",
        approval_action: str | None = None,
        actor: str = "",
        note: str = "",
        scope_kind: str = "system",
        scope_key: str = "",
    ) -> LifecycleApprovalRecord | None:
        track = self._guidance_track_row(provider, scope_kind=scope_kind, scope_key=scope_key)
        if track is None:
            raise KeyError(f"Unknown provider guidance: {provider}/{scope_kind}/{scope_key}")
        now = _utcnow()
        record_id = (
            f"{track['guidance_id']}|{revision_id}|{approval_action}|{now}"
            if approval_action is not None else
            ""
        )
        record: LifecycleApprovalRecord | None = None
        with self._connect() as conn:
            try:
                with conn.cursor() as cur:
                    if set_status is not None:
                        cur.execute(
                            f"""
                            UPDATE {_SCHEMA}.provider_guidance_revisions
                            SET status = %s
                            WHERE guidance_id = %s AND revision_id = %s
                            """,
                            (set_status, track["guidance_id"], revision_id),
                        )
                    if published_pointer == "set_active":
                        cur.execute(
                            f"""
                            UPDATE {_SCHEMA}.provider_guidance_tracks
                            SET published_revision_id = %s, updated_at = %s::timestamptz
                            WHERE guidance_id = %s
                            """,
                            (revision_id, now, track["guidance_id"]),
                        )
                    elif published_pointer == "clear":
                        cur.execute(
                            f"""
                            UPDATE {_SCHEMA}.provider_guidance_tracks
                            SET published_revision_id = '', updated_at = %s::timestamptz
                            WHERE guidance_id = %s
                            """,
                            (now, track["guidance_id"]),
                        )
                    if approval_action is not None:
                        cur.execute(
                            f"""
                            INSERT INTO {_SCHEMA}.provider_guidance_approval_records (
                                record_id, guidance_id, revision_id, action, actor, note, created_at
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s::timestamptz)
                            """,
                            (record_id, track["guidance_id"], revision_id, approval_action, actor, note, now),
                        )
                        record = LifecycleApprovalRecord(
                            record_id=record_id,
                            revision_id=revision_id,
                            action=approval_action,
                            actor=actor,
                            note=note,
                            created_at=now,
                        )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return record
