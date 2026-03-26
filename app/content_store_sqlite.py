"""SQLite implementation of the runtime content store."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import sqlite3
from pathlib import Path
import threading
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

_SCHEMA_VERSION = 2

_CREATE_V1_SQL = """\
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
        self._local = threading.local()

    def _db(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            return conn
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            str(self._db_path),
            isolation_level="DEFERRED",
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        self._ensure_schema(conn)
        self._local.conn = conn
        return conn

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        conn.executescript(_CREATE_V1_SQL)
        conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        row = conn.execute("SELECT value FROM meta WHERE key = 'content_schema_version'").fetchone()
        if row is None:
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('content_schema_version', '1')"
            )
            version = 1
        else:
            try:
                version = int(row["value"])
            except (TypeError, ValueError):
                version = 1
        if version < 2:
            self._migrate_v2(conn)
            version = 2
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('content_schema_version', ?)",
            (str(version),),
        )
        conn.commit()

    def _has_column(self, conn: sqlite3.Connection, table: str, column: str) -> bool:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return any(row["name"] == column for row in rows)

    def _migrate_v2(self, conn: sqlite3.Connection) -> None:
        if not self._has_column(conn, "skill_tracks", "published_revision_id"):
            conn.execute("ALTER TABLE skill_tracks ADD COLUMN published_revision_id TEXT NOT NULL DEFAULT ''")
        if not self._has_column(conn, "skill_revisions", "status"):
            conn.execute("ALTER TABLE skill_revisions ADD COLUMN status TEXT NOT NULL DEFAULT 'published'")
        if not self._has_column(conn, "provider_guidance_tracks", "published_revision_id"):
            conn.execute(
                "ALTER TABLE provider_guidance_tracks ADD COLUMN published_revision_id TEXT NOT NULL DEFAULT ''"
            )
        if not self._has_column(conn, "provider_guidance_revisions", "status"):
            conn.execute(
                "ALTER TABLE provider_guidance_revisions ADD COLUMN status TEXT NOT NULL DEFAULT 'published'"
            )
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS skill_approval_records (
                record_id TEXT PRIMARY KEY,
                track_id TEXT NOT NULL,
                revision_id TEXT NOT NULL,
                action TEXT NOT NULL,
                actor TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY(track_id) REFERENCES skill_tracks(track_id) ON DELETE CASCADE,
                FOREIGN KEY(revision_id) REFERENCES skill_revisions(revision_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS provider_guidance_approval_records (
                record_id TEXT PRIMARY KEY,
                guidance_id TEXT NOT NULL,
                revision_id TEXT NOT NULL,
                action TEXT NOT NULL,
                actor TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY(guidance_id) REFERENCES provider_guidance_tracks(guidance_id) ON DELETE CASCADE,
                FOREIGN KEY(revision_id) REFERENCES provider_guidance_revisions(revision_id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_skill_approval_records_track_id ON skill_approval_records(track_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_guidance_approval_records_guidance_id ON provider_guidance_approval_records(guidance_id, created_at DESC);
            """
        )
        conn.execute(
            "UPDATE skill_tracks SET published_revision_id = active_revision_id WHERE published_revision_id = ''"
        )
        conn.execute("UPDATE skill_revisions SET status = 'published' WHERE status = ''")
        conn.execute(
            "UPDATE provider_guidance_tracks SET published_revision_id = active_revision_id WHERE published_revision_id = ''"
        )
        conn.execute(
            "UPDATE provider_guidance_revisions SET status = 'published' WHERE status = ''"
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
        conn = self._db()
        now = _utcnow()
        skill_id = self._skill_id(record.slug)
        track_id = self._track_id(record)
        revision_id = self._skill_revision_id(record)
        existing = conn.execute(
            "SELECT published_revision_id FROM skill_tracks WHERE track_id = ?",
            (track_id,),
        ).fetchone()
        published_revision_id = revision_id if publish else (existing["published_revision_id"] if existing else "")
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
                is_mutable, active_revision_id, published_revision_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(track_id) DO UPDATE SET
                visibility = excluded.visibility,
                is_mutable = excluded.is_mutable,
                active_revision_id = excluded.active_revision_id,
                published_revision_id = excluded.published_revision_id,
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
                published_revision_id,
                now,
                now,
            ),
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO skill_revisions (
                revision_id, track_id, version_label, digest, instruction_body,
                requirements_json, provider_config_json, changelog, created_by, created_at, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                status,
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

    def _rows_for_slug(self, slug: str, *, runtime_only: bool) -> list[sqlite3.Row]:
        revision_ref = "CASE WHEN tr.published_revision_id != '' THEN tr.published_revision_id ELSE tr.active_revision_id END" if runtime_only else "tr.active_revision_id"
        extra_where = "AND tr.published_revision_id != ''" if runtime_only else ""
        return self._db().execute(
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
            FROM skill_namespaces ns
            JOIN skill_tracks tr ON tr.skill_id = ns.skill_id
            JOIN skill_revisions rev ON rev.revision_id = {revision_ref}
            WHERE ns.slug = ?
            {extra_where}
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
        rows = self._db().execute("SELECT slug FROM skill_namespaces ORDER BY lower(slug)").fetchall()
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

    def _custom_track_row(self, slug: str) -> sqlite3.Row | None:
        return self._db().execute(
            """
            SELECT tr.track_id, tr.active_revision_id, tr.published_revision_id
            FROM skill_tracks tr
            JOIN skill_namespaces ns ON ns.skill_id = tr.skill_id
            WHERE ns.slug = ? AND tr.source_kind = 'custom'
            ORDER BY tr.updated_at DESC
            LIMIT 1
            """,
            (slug,),
        ).fetchone()

    def list_skill_revisions(self, slug: str) -> list[SkillRevisionRecord]:
        track = self._custom_track_row(slug)
        if track is None:
            return []
        rows = self._db().execute(
            """
            SELECT revision_id, version_label, instruction_body, requirements_json, provider_config_json,
                   changelog, created_by, created_at, status
            FROM skill_revisions
            WHERE track_id = ?
            ORDER BY created_at DESC, revision_id DESC
            """,
            (track["track_id"],),
        ).fetchall()
        return [
            SkillRevisionRecord(
                instruction_body=row["instruction_body"],
                requirements=_parse_json(row["requirements_json"], []),
                provider_config=_parse_json(row["provider_config_json"], {}),
                files=self._files_for_revision(row["revision_id"]),
                version_label=row["version_label"],
                changelog=row["changelog"],
                created_by=row["created_by"],
                created_at=row["created_at"],
                revision_id=row["revision_id"],
                status=row["status"],
            )
            for row in rows
        ]

    def list_skill_approvals(self, slug: str) -> list[LifecycleApprovalRecord]:
        track = self._custom_track_row(slug)
        if track is None:
            return []
        rows = self._db().execute(
            """
            SELECT record_id, revision_id, action, actor, note, created_at
            FROM skill_approval_records
            WHERE track_id = ?
            ORDER BY created_at DESC, record_id DESC
            """,
            (track["track_id"],),
        ).fetchall()
        return [
            LifecycleApprovalRecord(
                record_id=row["record_id"],
                revision_id=row["revision_id"],
                action=row["action"],
                actor=row["actor"],
                note=row["note"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def get_latest_skill_approval_action(self, slug: str, revision_id: str) -> str:
        track = self._custom_track_row(slug)
        if track is None:
            return ""
        row = self._db().execute(
            """
            SELECT action
            FROM skill_approval_records
            WHERE track_id = ? AND revision_id = ?
            ORDER BY created_at DESC, record_id DESC
            LIMIT 1
            """,
            (track["track_id"], revision_id),
        ).fetchone()
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
        self._db().execute(
            """
            INSERT INTO skill_approval_records (
                record_id, track_id, revision_id, action, actor, note, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (record_id, track["track_id"], revision_id, action, actor, note, now),
        )
        self._db().commit()
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
        self._db().execute(
            "UPDATE skill_revisions SET status = ? WHERE track_id = ? AND revision_id = ?",
            (status, track["track_id"], revision_id),
        )
        self._db().commit()

    def set_published_skill_revision(self, slug: str, revision_id: str) -> None:
        track = self._custom_track_row(slug)
        if track is None:
            raise KeyError(f"Unknown custom skill: {slug}")
        self._db().execute(
            "UPDATE skill_tracks SET published_revision_id = ?, updated_at = ? WHERE track_id = ?",
            (revision_id, _utcnow(), track["track_id"]),
        )
        self._db().commit()

    def clear_published_skill_revision(self, slug: str) -> None:
        track = self._custom_track_row(slug)
        if track is None:
            raise KeyError(f"Unknown custom skill: {slug}")
        self._db().execute(
            "UPDATE skill_tracks SET published_revision_id = '', updated_at = ? WHERE track_id = ?",
            (_utcnow(), track["track_id"]),
        )
        self._db().commit()

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
        record: LifecycleApprovalRecord | None = None
        now = _utcnow()
        record_id = (
            f"{track['track_id']}|{revision_id}|{approval_action}|{now}"
            if approval_action is not None else
            ""
        )
        conn = self._db()
        with conn:
            if set_status is not None:
                conn.execute(
                    "UPDATE skill_revisions SET status = ? WHERE track_id = ? AND revision_id = ?",
                    (set_status, track["track_id"], revision_id),
                )
            if published_pointer == "set_active":
                conn.execute(
                    "UPDATE skill_tracks SET published_revision_id = ?, updated_at = ? WHERE track_id = ?",
                    (revision_id, now, track["track_id"]),
                )
            elif published_pointer == "clear":
                conn.execute(
                    "UPDATE skill_tracks SET published_revision_id = '', updated_at = ? WHERE track_id = ?",
                    (now, track["track_id"]),
                )
            if approval_action is not None:
                conn.execute(
                    """
                    INSERT INTO skill_approval_records (
                        record_id, track_id, revision_id, action, actor, note, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
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
        return record

    def _upsert_provider_guidance(
        self,
        record: ProviderGuidanceTrackRecord,
        *,
        status: str,
        publish: bool,
    ) -> None:
        conn = self._db()
        now = _utcnow()
        guidance_id = self._guidance_id(record)
        revision_id = self._guidance_revision_id(record)
        existing = conn.execute(
            "SELECT published_revision_id FROM provider_guidance_tracks WHERE guidance_id = ?",
            (guidance_id,),
        ).fetchone()
        published_revision_id = revision_id if publish else (existing["published_revision_id"] if existing else "")
        conn.execute(
            """
            INSERT INTO provider_guidance_tracks (
                guidance_id, provider, scope_kind, scope_key, is_mutable,
                active_revision_id, published_revision_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(guidance_id) DO UPDATE SET
                is_mutable = excluded.is_mutable,
                active_revision_id = excluded.active_revision_id,
                published_revision_id = excluded.published_revision_id,
                updated_at = excluded.updated_at
            """,
            (
                guidance_id,
                record.provider,
                record.scope_kind,
                record.scope_key,
                1 if record.is_mutable else 0,
                revision_id,
                published_revision_id,
                now,
                now,
            ),
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO provider_guidance_revisions (
                revision_id, guidance_id, digest, content, format, created_by, created_at, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
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
        row = self._db().execute(
            """
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
            active_revision_id=row["active_revision_id"],
            published_revision_id=row["published_revision_id"],
            revision=ProviderGuidanceRevisionRecord(
                content=row["content"],
                format=row["format"],
                created_by=row["created_by"],
                created_at=row["created_at"],
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
        row = self._db().execute(
            """
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
            FROM provider_guidance_tracks tr
            JOIN provider_guidance_revisions rev ON rev.revision_id = tr.published_revision_id
            WHERE tr.provider = ? AND tr.scope_kind = ? AND tr.scope_key = ? AND tr.published_revision_id != ''
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
            active_revision_id=row["active_revision_id"],
            published_revision_id=row["published_revision_id"],
            revision=ProviderGuidanceRevisionRecord(
                content=row["content"],
                format=row["format"],
                created_by=row["created_by"],
                created_at=row["created_at"],
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
    ) -> sqlite3.Row | None:
        return self._db().execute(
            """
            SELECT guidance_id, active_revision_id, published_revision_id
            FROM provider_guidance_tracks
            WHERE provider = ? AND scope_kind = ? AND scope_key = ?
            """,
            (provider, scope_kind, scope_key),
        ).fetchone()

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
        rows = self._db().execute(
            """
            SELECT revision_id, content, format, created_by, created_at, status
            FROM provider_guidance_revisions
            WHERE guidance_id = ?
            ORDER BY created_at DESC, revision_id DESC
            """,
            (track["guidance_id"],),
        ).fetchall()
        return [
            ProviderGuidanceRevisionRecord(
                content=row["content"],
                format=row["format"],
                created_by=row["created_by"],
                created_at=row["created_at"],
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
        rows = self._db().execute(
            """
            SELECT record_id, revision_id, action, actor, note, created_at
            FROM provider_guidance_approval_records
            WHERE guidance_id = ?
            ORDER BY created_at DESC, record_id DESC
            """,
            (track["guidance_id"],),
        ).fetchall()
        return [
            LifecycleApprovalRecord(
                record_id=row["record_id"],
                revision_id=row["revision_id"],
                action=row["action"],
                actor=row["actor"],
                note=row["note"],
                created_at=row["created_at"],
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
        row = self._db().execute(
            """
            SELECT action
            FROM provider_guidance_approval_records
            WHERE guidance_id = ? AND revision_id = ?
            ORDER BY created_at DESC, record_id DESC
            LIMIT 1
            """,
            (track["guidance_id"], revision_id),
        ).fetchone()
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
        self._db().execute(
            """
            INSERT INTO provider_guidance_approval_records (
                record_id, guidance_id, revision_id, action, actor, note, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (record_id, track["guidance_id"], revision_id, action, actor, note, now),
        )
        self._db().commit()
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
        self._db().execute(
            "UPDATE provider_guidance_revisions SET status = ? WHERE guidance_id = ? AND revision_id = ?",
            (status, track["guidance_id"], revision_id),
        )
        self._db().commit()

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
        self._db().execute(
            """
            UPDATE provider_guidance_tracks
            SET published_revision_id = ?, updated_at = ?
            WHERE guidance_id = ?
            """,
            (revision_id, _utcnow(), track["guidance_id"]),
        )
        self._db().commit()

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
        self._db().execute(
            """
            UPDATE provider_guidance_tracks
            SET published_revision_id = '', updated_at = ?
            WHERE guidance_id = ?
            """,
            (_utcnow(), track["guidance_id"]),
        )
        self._db().commit()

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
        record: LifecycleApprovalRecord | None = None
        now = _utcnow()
        record_id = (
            f"{track['guidance_id']}|{revision_id}|{approval_action}|{now}"
            if approval_action is not None else
            ""
        )
        conn = self._db()
        with conn:
            if set_status is not None:
                conn.execute(
                    "UPDATE provider_guidance_revisions SET status = ? WHERE guidance_id = ? AND revision_id = ?",
                    (set_status, track["guidance_id"], revision_id),
                )
            if published_pointer == "set_active":
                conn.execute(
                    """
                    UPDATE provider_guidance_tracks
                    SET published_revision_id = ?, updated_at = ?
                    WHERE guidance_id = ?
                    """,
                    (revision_id, now, track["guidance_id"]),
                )
            elif published_pointer == "clear":
                conn.execute(
                    """
                    UPDATE provider_guidance_tracks
                    SET published_revision_id = '', updated_at = ?
                    WHERE guidance_id = ?
                    """,
                    (now, track["guidance_id"]),
                )
            if approval_action is not None:
                conn.execute(
                    """
                    INSERT INTO provider_guidance_approval_records (
                        record_id, guidance_id, revision_id, action, actor, note, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
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
        return record
