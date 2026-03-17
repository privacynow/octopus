"""SQLite implementation of the runtime content store."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import sqlite3
from pathlib import Path

from app.content_models import (
    ProviderGuidanceRevisionRecord,
    ProviderGuidanceTrackRecord,
    RuntimeSkillSummary,
    RuntimeSkillTrackRecord,
    SkillFileRecord,
    SkillRevisionRecord,
    skill_precedence,
)
from app.content_store_base import AbstractContentStore

_CREATE_SQL = """\
CREATE TABLE IF NOT EXISTS skill_namespaces (
    skill_id TEXT PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    archived INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS skill_tracks (
    track_id TEXT PRIMARY KEY,
    skill_id TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    source_uri TEXT NOT NULL DEFAULT '',
    owner_actor TEXT NOT NULL DEFAULT '',
    visibility TEXT NOT NULL DEFAULT 'shared',
    is_mutable INTEGER NOT NULL DEFAULT 0,
    active_revision_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(skill_id, source_kind, source_uri, owner_actor),
    FOREIGN KEY(skill_id) REFERENCES skill_namespaces(skill_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS skill_revisions (
    revision_id TEXT PRIMARY KEY,
    track_id TEXT NOT NULL,
    version_label TEXT NOT NULL DEFAULT '',
    digest TEXT NOT NULL,
    instruction_body TEXT NOT NULL DEFAULT '',
    requirements_json TEXT NOT NULL DEFAULT '[]',
    provider_config_json TEXT NOT NULL DEFAULT '{}',
    changelog TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    FOREIGN KEY(track_id) REFERENCES skill_tracks(track_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS skill_files (
    revision_id TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    content_text TEXT NOT NULL DEFAULT '',
    content_type TEXT NOT NULL DEFAULT 'text/plain',
    executable INTEGER NOT NULL DEFAULT 0,
    digest TEXT NOT NULL,
    PRIMARY KEY(revision_id, relative_path),
    FOREIGN KEY(revision_id) REFERENCES skill_revisions(revision_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS provider_guidance_tracks (
    guidance_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    scope_kind TEXT NOT NULL DEFAULT 'system',
    scope_key TEXT NOT NULL DEFAULT '',
    is_mutable INTEGER NOT NULL DEFAULT 0,
    active_revision_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(provider, scope_kind, scope_key)
);
CREATE TABLE IF NOT EXISTS provider_guidance_revisions (
    revision_id TEXT PRIMARY KEY,
    guidance_id TEXT NOT NULL,
    digest TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    format TEXT NOT NULL DEFAULT 'markdown',
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    FOREIGN KEY(guidance_id) REFERENCES provider_guidance_tracks(guidance_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_skill_tracks_skill_id ON skill_tracks(skill_id);
CREATE INDEX IF NOT EXISTS idx_skill_revisions_track_id ON skill_revisions(track_id);
CREATE INDEX IF NOT EXISTS idx_guidance_tracks_lookup ON provider_guidance_tracks(provider, scope_kind, scope_key);
"""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value) -> str:
    return json.dumps(value, sort_keys=True)


def _parse_json(raw: str, default):
    try:
        return json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


class SQLiteContentStore(AbstractContentStore):
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def _db(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path), isolation_level="DEFERRED")
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(_CREATE_SQL)
        conn.commit()
        self._conn = conn
        return conn

    def _skill_id(self, slug: str) -> str:
        return f"skill:{slug}"

    def _track_id(self, record: RuntimeSkillTrackRecord) -> str:
        return "|".join(
            (
                record.slug,
                record.source_kind,
                record.source_uri,
                record.owner_actor,
            )
        )

    def _guidance_id(self, record: ProviderGuidanceTrackRecord) -> str:
        return "|".join((record.provider, record.scope_kind, record.scope_key))

    def replace_skill_track(self, record: RuntimeSkillTrackRecord) -> None:
        conn = self._db()
        now = _utcnow()
        skill_id = self._skill_id(record.slug)
        track_id = self._track_id(record)
        revision_id = f"{track_id}|{record.revision.digest}"
        conn.execute(
            """
            INSERT INTO skill_namespaces (skill_id, slug, display_name, description, archived, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(skill_id) DO UPDATE SET
                display_name = excluded.display_name,
                description = excluded.description,
                archived = excluded.archived,
                updated_at = excluded.updated_at
            """,
            (
                skill_id,
                record.slug,
                record.display_name,
                record.description,
                1 if record.archived else 0,
                now,
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO skill_tracks (
                track_id, skill_id, source_kind, source_uri, owner_actor, visibility,
                is_mutable, active_revision_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(track_id) DO UPDATE SET
                visibility = excluded.visibility,
                is_mutable = excluded.is_mutable,
                updated_at = excluded.updated_at
            """,
            (
                track_id,
                skill_id,
                record.source_kind,
                record.source_uri,
                record.owner_actor,
                record.visibility,
                1 if record.is_mutable else 0,
                revision_id,
                now,
                now,
            ),
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO skill_revisions (
                revision_id, track_id, version_label, digest, instruction_body,
                requirements_json, provider_config_json, changelog, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                revision_id,
                track_id,
                record.revision.version_label,
                record.revision.digest,
                record.revision.instruction_body,
                _json(record.revision.requirements),
                _json(record.revision.provider_config),
                record.revision.changelog,
                record.revision.created_by,
                record.revision.created_at or now,
            ),
        )
        conn.execute("DELETE FROM skill_files WHERE revision_id = ?", (revision_id,))
        for file_record in record.revision.files:
            conn.execute(
                """
                INSERT INTO skill_files (
                    revision_id, relative_path, content_text, content_type, executable, digest
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    revision_id,
                    file_record.relative_path,
                    file_record.content_text,
                    file_record.content_type,
                    1 if file_record.executable else 0,
                    file_record.digest,
                ),
            )
        conn.execute(
            "UPDATE skill_tracks SET active_revision_id = ?, updated_at = ? WHERE track_id = ?",
            (revision_id, now, track_id),
        )
        conn.commit()

    def delete_skill_track(
        self,
        slug: str,
        *,
        source_kind: str,
        source_uri: str = "",
        owner_actor: str = "",
    ) -> bool:
        conn = self._db()
        track_id = "|".join((slug, source_kind, source_uri, owner_actor))
        before = conn.total_changes
        conn.execute("DELETE FROM skill_tracks WHERE track_id = ?", (track_id,))
        conn.execute(
            """
            DELETE FROM skill_namespaces
            WHERE slug = ?
              AND NOT EXISTS (
                    SELECT 1
                    FROM skill_tracks tr
                    WHERE tr.skill_id = skill_namespaces.skill_id
              )
            """,
            (slug,),
        )
        conn.commit()
        return conn.total_changes > before

    def _rows_for_slug(self, slug: str) -> list[sqlite3.Row]:
        conn = self._db()
        return conn.execute(
            """
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
                rev.revision_id,
                rev.version_label,
                rev.digest,
                rev.instruction_body,
                rev.requirements_json,
                rev.provider_config_json,
                rev.changelog,
                rev.created_by,
                rev.created_at
            FROM skill_namespaces ns
            JOIN skill_tracks tr ON tr.skill_id = ns.skill_id
            JOIN skill_revisions rev ON rev.revision_id = tr.active_revision_id
            WHERE ns.slug = ?
            ORDER BY tr.source_kind ASC, tr.updated_at DESC
            """,
            (slug,),
        ).fetchall()

    def _files_for_revision(self, revision_id: str) -> tuple[SkillFileRecord, ...]:
        rows = self._db().execute(
            """
            SELECT relative_path, content_text, content_type, executable
            FROM skill_files
            WHERE revision_id = ?
            ORDER BY relative_path ASC
            """,
            (revision_id,),
        ).fetchall()
        return tuple(
            SkillFileRecord(
                relative_path=row["relative_path"],
                content_text=row["content_text"],
                content_type=row["content_type"],
                executable=bool(row["executable"]),
            )
            for row in rows
        )

    def _record_from_row(self, row: sqlite3.Row) -> RuntimeSkillTrackRecord:
        revision = SkillRevisionRecord(
            instruction_body=row["instruction_body"],
            requirements=_parse_json(row["requirements_json"], []),
            provider_config=_parse_json(row["provider_config_json"], {}),
            files=self._files_for_revision(row["revision_id"]),
            version_label=row["version_label"],
            changelog=row["changelog"],
            created_by=row["created_by"],
            created_at=row["created_at"],
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
        )

    def list_skill_tracks(self, slug: str) -> list[RuntimeSkillTrackRecord]:
        rows = self._rows_for_slug(slug)
        records = [self._record_from_row(row) for row in rows]
        return sorted(records, key=lambda item: skill_precedence(item.source_kind), reverse=True)

    def resolve_skill(self, slug: str) -> RuntimeSkillTrackRecord | None:
        tracks = self.list_skill_tracks(slug)
        return tracks[0] if tracks else None

    def list_skill_summaries(self) -> list[RuntimeSkillSummary]:
        rows = self._db().execute("SELECT slug FROM skill_namespaces ORDER BY lower(slug)").fetchall()
        summaries: list[RuntimeSkillSummary] = []
        for row in rows:
            record = self.resolve_skill(row["slug"])
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
                )
            )
        return summaries

    def replace_provider_guidance(self, record: ProviderGuidanceTrackRecord) -> None:
        conn = self._db()
        now = _utcnow()
        guidance_id = self._guidance_id(record)
        revision_id = f"{guidance_id}|{record.revision.digest}"
        conn.execute(
            """
            INSERT INTO provider_guidance_tracks (
                guidance_id, provider, scope_kind, scope_key, is_mutable, active_revision_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(guidance_id) DO UPDATE SET
                is_mutable = excluded.is_mutable,
                updated_at = excluded.updated_at
            """,
            (
                guidance_id,
                record.provider,
                record.scope_kind,
                record.scope_key,
                1 if record.is_mutable else 0,
                revision_id,
                now,
                now,
            ),
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO provider_guidance_revisions (
                revision_id, guidance_id, digest, content, format, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                revision_id,
                guidance_id,
                record.revision.digest,
                record.revision.content,
                record.revision.format,
                record.revision.created_by,
                record.revision.created_at or now,
            ),
        )
        conn.execute(
            "UPDATE provider_guidance_tracks SET active_revision_id = ?, updated_at = ? WHERE guidance_id = ?",
            (revision_id, now, guidance_id),
        )
        conn.commit()

    def get_provider_guidance(
        self,
        provider: str,
        *,
        scope_kind: str = "system",
        scope_key: str = "",
    ) -> ProviderGuidanceTrackRecord | None:
        row = self._db().execute(
            """
            SELECT
                tr.provider,
                tr.scope_kind,
                tr.scope_key,
                tr.is_mutable,
                rev.content,
                rev.format,
                rev.created_by,
                rev.created_at
            FROM provider_guidance_tracks tr
            JOIN provider_guidance_revisions rev ON rev.revision_id = tr.active_revision_id
            WHERE tr.provider = ? AND tr.scope_kind = ? AND tr.scope_key = ?
            """,
            (provider, scope_kind, scope_key),
        ).fetchone()
        if row is None:
            return None
        return ProviderGuidanceTrackRecord(
            provider=row["provider"],
            scope_kind=row["scope_kind"],
            scope_key=row["scope_key"],
            is_mutable=bool(row["is_mutable"]),
            revision=ProviderGuidanceRevisionRecord(
                content=row["content"],
                format=row["format"],
                created_by=row["created_by"],
                created_at=row["created_at"],
            ),
        )

    def resolve_provider_guidance(
        self,
        provider: str,
        *,
        instance_key: str = "",
    ) -> ProviderGuidanceTrackRecord | None:
        if instance_key:
            match = self.get_provider_guidance(
                provider,
                scope_kind="instance",
                scope_key=instance_key,
            )
            if match is not None:
                return match
        return self.get_provider_guidance(provider, scope_kind="system", scope_key="")

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
