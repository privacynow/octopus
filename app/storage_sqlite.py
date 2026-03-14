"""SQLite-backed session store implementation. Used by runtime_backend when BOT_DATABASE_URL is unset."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Callable

from app.session_defaults import default_session

_SCHEMA_VERSION = 1

_CREATE_SQL = """\
CREATE TABLE IF NOT EXISTS sessions (
    chat_id     INTEGER PRIMARY KEY,
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


class SQLiteSessionStore:
    """Session store backed by SQLite. One instance per backend; owns its connection cache."""

    def __init__(self) -> None:
        self._connections: dict[Path, sqlite3.Connection] = {}

    def _db(self, data_dir: Path) -> sqlite3.Connection:
        if data_dir in self._connections:
            return self._connections[data_dir]
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
            self._migrate_json_files(data_dir, conn)
        except Exception:
            conn.close()
            raise
        self._connections[data_dir] = conn
        return conn

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
                chat_id = int(sf.stem)
            except (json.JSONDecodeError, OSError, ValueError):
                try:
                    sf.unlink()
                except OSError:
                    pass
                continue
            self._upsert(conn, chat_id, data)
            sf.unlink()
        conn.commit()
        try:
            sessions_dir.rmdir()
        except OSError:
            pass

    def _upsert(self, conn: sqlite3.Connection, chat_id: int, session: dict[str, Any]) -> None:
        has_pending = (
            session.get("pending_approval") is not None
            or session.get("pending_retry") is not None
        )
        conn.execute(
            """INSERT OR REPLACE INTO sessions
               (chat_id, provider, data, has_pending, has_setup,
                project_id, file_policy, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                chat_id,
                session.get("provider", ""),
                json.dumps(session, sort_keys=True),
                1 if has_pending else 0,
                1 if session.get("awaiting_skill_setup") is not None else 0,
                session.get("project_id"),
                session.get("file_policy"),
                session.get("created_at", ""),
                session.get("updated_at", ""),
            ),
        )

    def session_exists(self, data_dir: Path, chat_id: int) -> bool:
        conn = self._db(data_dir)
        row = conn.execute(
            "SELECT 1 FROM sessions WHERE chat_id = ?", (chat_id,)
        ).fetchone()
        return row is not None

    def load_session(
        self,
        data_dir: Path,
        chat_id: int,
        provider_name: str,
        provider_state_factory: Callable[[], dict[str, Any]],
        approval_mode: str,
        role: str = "",
        default_skills: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        session = default_session(
            provider_name, provider_state_factory(), approval_mode, role, default_skills
        )
        conn = self._db(data_dir)
        row = conn.execute(
            "SELECT data FROM sessions WHERE chat_id = ?", (chat_id,)
        ).fetchone()
        if row is not None:
            try:
                saved = json.loads(row[0])
                for key in (
                    "active_skills", "role", "pending_approval", "pending_retry",
                    "awaiting_skill_setup", "compact_mode", "project_id", "file_policy",
                    "model_profile", "created_at", "updated_at",
                ):
                    if key in saved:
                        session[key] = saved[key]
                if saved.get("approval_mode_explicit"):
                    session["approval_mode"] = saved["approval_mode"]
                    session["approval_mode_explicit"] = True
                if saved.get("provider") == provider_name:
                    fresh_state = provider_state_factory()
                    fresh_state.update(saved.get("provider_state", {}))
                    session["provider_state"] = fresh_state
            except (json.JSONDecodeError, KeyError):
                pass
        return session

    def save_session(self, data_dir: Path, chat_id: int, session: dict[str, Any]) -> None:
        from datetime import datetime, timezone
        session["updated_at"] = datetime.now(timezone.utc).isoformat()
        conn = self._db(data_dir)
        self._upsert(conn, chat_id, session)
        conn.commit()

    def delete_session(self, data_dir: Path, chat_id: int) -> None:
        conn = self._db(data_dir)
        conn.execute("DELETE FROM sessions WHERE chat_id = ?", (chat_id,))
        conn.commit()

    def list_sessions(self, data_dir: Path) -> list[dict[str, Any]]:
        conn = self._db(data_dir)
        rows = conn.execute(
            """SELECT chat_id, provider, data, has_pending, has_setup,
                      created_at, updated_at
               FROM sessions ORDER BY updated_at DESC"""
        ).fetchall()
        results: list[dict[str, Any]] = []
        for chat_id, provider, data_json, has_pending, has_setup, created_at, updated_at in rows:
            try:
                data = json.loads(data_json)
            except json.JSONDecodeError:
                data = {}
            results.append({
                "chat_id": chat_id,
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
        conn = self._connections.pop(data_dir, None)
        if conn:
            conn.close()

    def close_all_db(self) -> None:
        for data_dir in list(self._connections.keys()):
            self.close_db(data_dir)

    def _reset_db(self, data_dir: Path) -> None:
        """Tests only: close and delete the database."""
        self.close_db(data_dir)
        db_path = data_dir / "sessions.db"
        if db_path.exists():
            db_path.unlink()
