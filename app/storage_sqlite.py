"""SQLite-backed session store implementation. Used by runtime_backend when BOT_DATABASE_URL is unset."""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Callable

from octopus_sdk.registry.models import RoutedTaskResult
from octopus_sdk.identity import telegram_conversation_key
from octopus_sdk.sessions import default_session, session_from_dict, session_to_dict
from app.workflows.delegation.contracts import DelegationUpdateOutcome
from app.workflows.delegation.coordination import apply_routed_result

_SCHEMA_VERSION = 2

_CREATE_SQL = """\
CREATE TABLE IF NOT EXISTS sessions (
    conversation_key TEXT PRIMARY KEY,
    provider    TEXT    NOT NULL DEFAULT '',
    data        TEXT    NOT NULL DEFAULT '{}',
    has_pending INTEGER NOT NULL DEFAULT 0,
    has_setup   INTEGER NOT NULL DEFAULT 0,
    project_id  TEXT,
    file_policy TEXT,
    created_at  TEXT    NOT NULL DEFAULT '',
    updated_at  TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_sessions_updated ON sessions (updated_at);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _execute_sql_script(conn: sqlite3.Connection, script: str) -> None:
    buffer = ""
    for line in script.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            statement = buffer.strip()
            if statement:
                conn.execute(statement)
            buffer = ""
    statement = buffer.strip()
    if statement:
        conn.execute(statement)


def _run_migration_step(
    conn: sqlite3.Connection,
    version: int,
    migration: Callable[[sqlite3.Connection], None],
) -> None:
    conn.execute("BEGIN IMMEDIATE")
    try:
        migration(conn)
        conn.execute(
            "UPDATE meta SET value = ? WHERE key = 'schema_version'",
            (str(version),),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


class SQLiteSessionStore:
    """Session store backed by SQLite. One instance per backend; owns its connection cache."""

    def __init__(self) -> None:
        self._connections: dict[tuple[Path, int], sqlite3.Connection] = {}

    def _connection_key(self, data_dir: Path) -> tuple[Path, int]:
        return data_dir, threading.get_ident()

    def _db(self, data_dir: Path) -> sqlite3.Connection:
        key = self._connection_key(data_dir)
        if key in self._connections:
            return self._connections[key]
        db_path = data_dir / "sessions.db"
        conn = sqlite3.connect(str(db_path), isolation_level="DEFERRED")
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.executescript(_CREATE_SQL)
            row = conn.execute(
                "SELECT value FROM meta WHERE key='schema_version'"
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO meta (key, value) VALUES ('schema_version', ?)",
                    (str(_SCHEMA_VERSION),),
                )
                conn.commit()
            else:
                stored = int(row[0])
                if stored > _SCHEMA_VERSION:
                    raise RuntimeError(
                        f"Session DB schema version {stored} is newer than supported "
                        f"version {_SCHEMA_VERSION}. Upgrade the bot."
                    )
                if stored < _SCHEMA_VERSION:
                    self._run_migrations(conn, stored)
            self._migrate_json_files(data_dir, conn)
        except Exception:
            conn.close()
            raise
        self._connections[key] = conn
        return conn

    def _run_migrations(self, conn: sqlite3.Connection, stored_version: int) -> None:
        version = stored_version
        if version < 2:
            _run_migration_step(conn, 2, self._migrate_v1_to_v2)
            version = 2
        return None

    def _migrate_v1_to_v2(self, conn: sqlite3.Connection) -> None:
        _execute_sql_script(
            conn,
            """
            CREATE TABLE sessions_v2 (
                conversation_key TEXT PRIMARY KEY,
                provider    TEXT    NOT NULL DEFAULT '',
                data        TEXT    NOT NULL DEFAULT '{}',
                has_pending INTEGER NOT NULL DEFAULT 0,
                has_setup   INTEGER NOT NULL DEFAULT 0,
                project_id  TEXT,
                file_policy TEXT,
                created_at  TEXT    NOT NULL DEFAULT '',
                updated_at  TEXT    NOT NULL DEFAULT ''
            );
            INSERT INTO sessions_v2 (
                conversation_key, provider, data, has_pending, has_setup,
                project_id, file_policy, created_at, updated_at
            )
            SELECT
                'tg:' || CAST(chat_id AS TEXT),
                provider, data, has_pending, has_setup,
                project_id, file_policy, created_at, updated_at
            FROM sessions;
            DROP TABLE sessions;
            ALTER TABLE sessions_v2 RENAME TO sessions;
            CREATE INDEX IF NOT EXISTS idx_sessions_updated ON sessions (updated_at);
            """,
        )

    def _migrate_json_files(self, data_dir: Path, conn: sqlite3.Connection) -> None:
        sessions_dir = data_dir / "sessions"
        if not sessions_dir.is_dir():
            return
        json_files = list(sessions_dir.glob("*.json"))
        if not json_files:
            try:
                sessions_dir.rmdir()
            except OSError:
                pass
            return
        for sf in json_files:
            try:
                data = json.loads(sf.read_text())
                conversation_key = sf.stem if ":" in sf.stem else telegram_conversation_key(sf.stem)
            except (json.JSONDecodeError, OSError):
                try:
                    sf.unlink()
                except OSError:
                    pass
                continue
            self._upsert(conn, conversation_key, data)
            sf.unlink()
        conn.commit()
        try:
            sessions_dir.rmdir()
        except OSError:
            pass

    def _upsert(self, conn: sqlite3.Connection, conversation_key: str, session: dict[str, Any]) -> None:
        from datetime import datetime, timezone
        has_pending = (
            session.get("pending_approval") is not None
            or session.get("pending_retry") is not None
        )
        # Normalize timestamps before serializing so JSON data and column agree
        if not session.get("created_at"):
            session["created_at"] = datetime.now(timezone.utc).isoformat()
        if not session.get("updated_at"):
            session["updated_at"] = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """INSERT OR REPLACE INTO sessions
               (conversation_key, provider, data, has_pending, has_setup,
                project_id, file_policy, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                conversation_key,
                session.get("provider", ""),
                json.dumps(session, sort_keys=True),
                1 if has_pending else 0,
                1 if session.get("awaiting_skill_setup") is not None else 0,
                session.get("project_id"),
                session.get("file_policy"),
                session["created_at"],
                session["updated_at"],
            ),
        )

    def session_exists(self, data_dir: Path, conversation_key: str) -> bool:
        conn = self._db(data_dir)
        row = conn.execute(
            "SELECT 1 FROM sessions WHERE conversation_key = ?", (conversation_key,)
        ).fetchone()
        return row is not None

    def load_session(
        self,
        data_dir: Path,
        conversation_key: str,
        provider_name: str,
        provider_state_factory: Callable[[str], dict[str, Any]],
        approval_mode: str,
        role: str = "",
        default_skills: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        session = default_session(
            provider_name, provider_state_factory(conversation_key), approval_mode, role, default_skills
        )
        conn = self._db(data_dir)
        row = conn.execute(
            "SELECT data FROM sessions WHERE conversation_key = ?", (conversation_key,)
        ).fetchone()
        if row is not None:
            try:
                saved = json.loads(row[0])
                for key in (
                    "active_skills", "role", "pending_approval", "pending_retry",
                    "awaiting_skill_setup", "pending_delegation",
                    "compact_mode", "project_id", "file_policy",
                    "model_profile", "created_at", "updated_at",
                ):
                    if key in saved:
                        session[key] = saved[key]
                if saved.get("approval_mode_explicit"):
                    session["approval_mode"] = saved["approval_mode"]
                    session["approval_mode_explicit"] = True
                if saved.get("provider") == provider_name:
                    fresh_state = provider_state_factory(conversation_key)
                    fresh_state.update(saved.get("provider_state", {}))
                    session["provider_state"] = fresh_state
            except (json.JSONDecodeError, KeyError, TypeError, AttributeError):
                pass
        return session

    def save_session(self, data_dir: Path, conversation_key: str, session: dict[str, Any]) -> None:
        from datetime import datetime, timezone
        session["updated_at"] = datetime.now(timezone.utc).isoformat()
        conn = self._db(data_dir)
        self._upsert(conn, conversation_key, session)
        conn.commit()

    def apply_delegation_result_atomically(
        self,
        data_dir: Path,
        conversation_key: str,
        *,
        routed_task_id: str,
        authority_ref: str,
        result: RoutedTaskResult,
    ) -> DelegationUpdateOutcome:
        conn = self._db(data_dir)
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT data FROM sessions WHERE conversation_key = ?",
                (conversation_key,),
            ).fetchone()
            raw: dict[str, Any] = {}
            if row is not None:
                try:
                    decoded = json.loads(row[0])
                    if isinstance(decoded, dict):
                        raw = decoded
                except json.JSONDecodeError:
                    raw = {}
            session = session_from_dict(raw)
            applied = apply_routed_result(
                session.pending_delegation,
                routed_task_id=routed_task_id,
                authority_ref=authority_ref,
                result=result,
            )
            if applied.matched:
                session.pending_delegation = applied.pending
                self._upsert(conn, conversation_key, session_to_dict(session))
            conn.commit()
            return applied
        except Exception:
            conn.rollback()
            raise

    def delete_session(self, data_dir: Path, conversation_key: str) -> None:
        conn = self._db(data_dir)
        conn.execute("DELETE FROM sessions WHERE conversation_key = ?", (conversation_key,))
        conn.commit()

    def list_sessions(self, data_dir: Path) -> list[dict[str, Any]]:
        conn = self._db(data_dir)
        rows = conn.execute(
            """SELECT conversation_key, provider, data, has_pending, has_setup,
                      created_at, updated_at
               FROM sessions ORDER BY updated_at DESC"""
        ).fetchall()
        results: list[dict[str, Any]] = []
        for conversation_key, provider, data_json, has_pending, has_setup, created_at, updated_at in rows:
            try:
                data = json.loads(data_json)
            except json.JSONDecodeError:
                data = {}
            results.append({
                "conversation_key": conversation_key,
                "provider": provider,
                "active_skills": data.get("active_skills", []),
                "has_pending": bool(has_pending),
                "has_setup": bool(has_setup),
                "approval_mode": data.get("approval_mode", "off"),
                "updated_at": updated_at,
                "created_at": created_at,
            })
        return results

    def close_db(self, data_dir: Path) -> None:
        keys = [key for key in self._connections if key[0] == data_dir]
        for key in keys:
            conn = self._connections.pop(key, None)
            if conn:
                conn.close()

    def close_all_db(self) -> None:
        for data_dir in list(self._connections.keys()):
            self.close_db(data_dir)

    def debug_connection(self, data_dir: Path) -> sqlite3.Connection:
        """Return the SQLite session connection for tests/diagnostics."""
        return self._db(data_dir)

    def reset_db_for_test(self, data_dir: Path) -> None:
        """Tests only: close and delete the database."""
        self.close_db(data_dir)
        db_path = data_dir / "sessions.db"
        if db_path.exists():
            db_path.unlink()
