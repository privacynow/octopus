"""Session CRUD (SQLite-backed), upload paths, directory management."""

import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}

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


# ---------------------------------------------------------------------------
# Database lifecycle
# ---------------------------------------------------------------------------

_db_connections: dict[Path, sqlite3.Connection] = {}

# Phase 12: when set, session CRUD delegates to storage_pg
_pg_url: str = ""
_pg_pool_min: int = 1
_pg_pool_max: int = 10
_pg_connect_timeout: int = 10


def set_postgres_backend(
    database_url: str,
    *,
    pool_min: int = 1,
    pool_max: int = 10,
    connect_timeout: int = 10,
) -> None:
    """Use Postgres for session store. Call at startup when BOT_DATABASE_URL is set."""
    global _pg_url, _pg_pool_min, _pg_pool_max, _pg_connect_timeout
    _pg_url = database_url
    _pg_pool_min = pool_min
    _pg_pool_max = pool_max
    _pg_connect_timeout = connect_timeout


def _pg_conn():
    """Yield a Postgres connection when backend is Postgres. Otherwise None."""
    if not _pg_url:
        return None
    from app.db.postgres import get_connection
    return get_connection(
        _pg_url,
        min_size=_pg_pool_min,
        max_size=_pg_pool_max,
        connect_timeout=_pg_connect_timeout,
    )


def _db(data_dir: Path) -> sqlite3.Connection:
    """Return (or create) a WAL-mode SQLite connection for this data_dir."""
    if data_dir in _db_connections:
        return _db_connections[data_dir]
    db_path = data_dir / "sessions.db"
    conn = sqlite3.connect(str(db_path), isolation_level="DEFERRED")
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(_CREATE_SQL)
        # Schema version guard
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
        _migrate_json_files(data_dir, conn)
    except Exception:
        conn.close()
        raise
    _db_connections[data_dir] = conn
    return conn


def close_db(data_dir: Path) -> None:
    """Close the database connection for a data_dir (for clean shutdown)."""
    conn = _db_connections.pop(data_dir, None)
    if conn:
        conn.close()


def close_all_db() -> None:
    """Close all cached session DB connections (for test isolation)."""
    for data_dir in list(_db_connections.keys()):
        close_db(data_dir)


def _reset_db(data_dir: Path) -> None:
    """Close and delete the database (for tests only)."""
    close_db(data_dir)
    db_path = data_dir / "sessions.db"
    if db_path.exists():
        db_path.unlink()


def _migrate_json_files(data_dir: Path, conn: sqlite3.Connection) -> None:
    """One-time migration: import sessions/*.json into SQLite, then remove."""
    sessions_dir = data_dir / "sessions"
    if not sessions_dir.is_dir():
        return
    json_files = list(sessions_dir.glob("*.json"))
    if not json_files:
        # Empty dir — clean up
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
            # Corrupt or unparseable — remove and skip
            try:
                sf.unlink()
            except OSError:
                pass
            continue
        _upsert(conn, chat_id, data)
        sf.unlink()
    conn.commit()
    # Remove the now-empty sessions dir
    try:
        sessions_dir.rmdir()
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _upsert(conn: sqlite3.Connection, chat_id: int, session: dict[str, Any]) -> None:
    """Insert or replace a session row from a session dict."""
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


# ---------------------------------------------------------------------------
# Public directory / path helpers (unchanged)
# ---------------------------------------------------------------------------

def ensure_data_dirs(data_dir: Path, *, database_url: str = "") -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "uploads").mkdir(parents=True, exist_ok=True)
    (data_dir / "credentials").mkdir(parents=True, exist_ok=True)
    # When database_url is set, session/transport use Postgres; skip SQLite init
    if database_url:
        return
    _db(data_dir)
    from app.work_queue import _transport_db
    _transport_db(data_dir)


def sanitize_filename(name: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return safe or "attachment"


def is_image_path(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTENSIONS


def chat_upload_dir(data_dir: Path, chat_id: int) -> Path:
    d = data_dir / "uploads" / str(chat_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def build_upload_path(data_dir: Path, chat_id: int, original_name: str) -> Path:
    return (
        chat_upload_dir(data_dir, chat_id)
        / f"{uuid.uuid4().hex}_{sanitize_filename(original_name)}"
    )


def resolve_allowed_path(raw_path: str, allowed_roots: list[Path]) -> Path | None:
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        if allowed_roots:
            candidate = allowed_roots[0] / candidate
        else:
            return None
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError:
        return None
    for root in allowed_roots:
        try:
            resolved.relative_to(root.resolve())
            return resolved
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Session CRUD
# ---------------------------------------------------------------------------

def session_exists(data_dir: Path, chat_id: int) -> bool:
    """Check whether a session exists for the given chat_id."""
    if _pg_url:
        from app import storage_pg
        with _pg_conn() as conn:
            return storage_pg.session_exists(conn, chat_id)
    conn = _db(data_dir)
    row = conn.execute(
        "SELECT 1 FROM sessions WHERE chat_id = ?", (chat_id,)
    ).fetchone()
    return row is not None



def default_session(
    provider_name: str,
    provider_state: dict[str, Any],
    approval_mode: str,
    role: str = "",
    default_skills: tuple[str, ...] = (),
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "provider": provider_name,
        "provider_state": provider_state,
        "approval_mode": approval_mode,
        "active_skills": list(default_skills),
        "role": role,
        "pending_approval": None,
        "pending_retry": None,
        "awaiting_skill_setup": None,
        "created_at": now,
        "updated_at": now,
    }


def load_session(
    data_dir: Path,
    chat_id: int,
    provider_name: str,
    provider_state_factory: Callable[[], dict[str, Any]],
    approval_mode: str,
    role: str = "",
    default_skills: tuple[str, ...] = (),
) -> dict[str, Any]:
    if _pg_url:
        from app import storage_pg
        with _pg_conn() as conn:
            return storage_pg.load_session(
                conn, chat_id, provider_name, provider_state_factory,
                approval_mode, role, default_skills,
            )
    session = default_session(provider_name, provider_state_factory(), approval_mode, role, default_skills)
    conn = _db(data_dir)
    row = conn.execute(
        "SELECT data FROM sessions WHERE chat_id = ?", (chat_id,)
    ).fetchone()
    if row is not None:
        try:
            saved = json.loads(row[0])
            for key in ("active_skills", "role", "pending_approval", "pending_retry", "awaiting_skill_setup", "compact_mode", "project_id", "file_policy", "model_profile", "created_at", "updated_at"):
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


def save_session(data_dir: Path, chat_id: int, session: dict[str, Any]) -> None:
    if _pg_url:
        from app import storage_pg
        with _pg_conn() as conn:
            storage_pg.save_session(conn, chat_id, session)
        return
    session["updated_at"] = datetime.now(timezone.utc).isoformat()
    conn = _db(data_dir)
    _upsert(conn, chat_id, session)
    conn.commit()


def delete_session(data_dir: Path, chat_id: int) -> None:
    """Delete a session (for tests or admin cleanup)."""
    if _pg_url:
        from app import storage_pg
        with _pg_conn() as conn:
            storage_pg.delete_session(conn, chat_id)
        return
    conn = _db(data_dir)
    conn.execute("DELETE FROM sessions WHERE chat_id = ?", (chat_id,))
    conn.commit()


def list_sessions(data_dir: Path) -> list[dict[str, Any]]:
    """Return summary info for all stored sessions, ordered by updated_at desc."""
    if _pg_url:
        from app import storage_pg
        with _pg_conn() as conn:
            return storage_pg.list_sessions(conn)
    conn = _db(data_dir)
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
