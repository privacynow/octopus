"""Postgres-backed session store. Conn-based API for tests; PostgresSessionStore for runtime_backend."""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from app.session_defaults import default_session

_SCHEMA_TABLE = "bot_runtime.sessions"


# ---------------------------------------------------------------------------
# Conn-based API (used by tests and by PostgresSessionStore)
# ---------------------------------------------------------------------------

def session_exists(conn, chat_id: int) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT 1 FROM {_SCHEMA_TABLE} WHERE chat_id = %s",
            (chat_id,),
        )
        return cur.fetchone() is not None


def load_session(
    conn,
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
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT data FROM {_SCHEMA_TABLE} WHERE chat_id = %s",
            (chat_id,),
        )
        row = cur.fetchone()
    if row is None:
        return session
    raw = row[0]
    try:
        saved = raw if isinstance(raw, dict) else json.loads(raw)
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
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError):
        pass
    return session


def _upsert(conn, chat_id: int, session: dict[str, Any]) -> None:
    has_pending = (
        session.get("pending_approval") is not None
        or session.get("pending_retry") is not None
    )
    has_setup = session.get("awaiting_skill_setup") is not None
    # Normalize timestamps before serializing so JSON data and column agree
    if not session.get("created_at"):
        session["created_at"] = datetime.now(timezone.utc).isoformat()
    if not session.get("updated_at"):
        session["updated_at"] = datetime.now(timezone.utc).isoformat()
    created_at = session["created_at"]
    updated_at = session["updated_at"]
    data_json = json.dumps(session, sort_keys=True)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {_SCHEMA_TABLE}
            (chat_id, provider, data, has_pending, has_setup, project_id, file_policy, created_at, updated_at)
            VALUES (%s, %s, %s::jsonb, %s, %s, %s, %s, %s::timestamptz, %s::timestamptz)
            ON CONFLICT (chat_id) DO UPDATE SET
                provider = EXCLUDED.provider,
                data = EXCLUDED.data,
                has_pending = EXCLUDED.has_pending,
                has_setup = EXCLUDED.has_setup,
                project_id = EXCLUDED.project_id,
                file_policy = EXCLUDED.file_policy,
                updated_at = EXCLUDED.updated_at
            """,
            (
                chat_id,
                session.get("provider", ""),
                data_json,
                has_pending,
                has_setup,
                session.get("project_id"),
                session.get("file_policy"),
                created_at,
                updated_at,
            ),
        )
    conn.commit()


def save_session(conn, chat_id: int, session: dict[str, Any]) -> None:
    session["updated_at"] = datetime.now(timezone.utc).isoformat()
    _upsert(conn, chat_id, session)


def delete_session(conn, chat_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute(f"DELETE FROM {_SCHEMA_TABLE} WHERE chat_id = %s", (chat_id,))
    conn.commit()


def list_sessions(conn) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT chat_id, provider, data, has_pending, has_setup, created_at, updated_at
            FROM {_SCHEMA_TABLE}
            ORDER BY updated_at DESC
            """
        )
        rows = cur.fetchall()
    results: list[dict[str, Any]] = []
    for row in rows:
        chat_id, provider, data, has_pending, has_setup, created_at, updated_at = (
            row[0], row[1], row[2], row[3], row[4], row[5], row[6]
        )
        if isinstance(data, dict):
            data_dict = data
        else:
            try:
                data_dict = json.loads(data) if data else {}
            except json.JSONDecodeError:
                data_dict = {}
        results.append({
            "chat_id": chat_id,
            "provider": provider,
            "active_skills": data_dict.get("active_skills", []),
            "has_pending": bool(has_pending),
            "has_setup": bool(has_setup),
            "approval_mode": data_dict.get("approval_mode", "off"),
            "updated_at": updated_at.isoformat() if hasattr(updated_at, "isoformat") else updated_at,
            "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else created_at,
        })
    return results


# ---------------------------------------------------------------------------
# Store wrapper for runtime_backend (data_dir ignored; uses pool)
# ---------------------------------------------------------------------------

class PostgresSessionStore:
    """Session store backed by Postgres. Uses connection pool; data_dir ignored."""

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

    @contextmanager
    def _conn(self):
        from app.db.postgres import get_connection
        with get_connection(
            self._database_url,
            min_size=self._pool_min,
            max_size=self._pool_max,
            connect_timeout=self._connect_timeout,
        ) as conn:
            yield conn

    def session_exists(self, data_dir: Path, chat_id: int) -> bool:
        with self._conn() as conn:
            return session_exists(conn, chat_id)

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
        with self._conn() as conn:
            return load_session(
                conn, chat_id, provider_name, provider_state_factory,
                approval_mode, role, default_skills,
            )

    def save_session(self, data_dir: Path, chat_id: int, session: dict[str, Any]) -> None:
        with self._conn() as conn:
            save_session(conn, chat_id, session)

    def delete_session(self, data_dir: Path, chat_id: int) -> None:
        with self._conn() as conn:
            delete_session(conn, chat_id)

    def list_sessions(self, data_dir: Path) -> list[dict[str, Any]]:
        with self._conn() as conn:
            return list_sessions(conn)

    def close_db(self, data_dir: Path) -> None:
        pass  # Pool managed by get_connection

    def close_all_db(self) -> None:
        pass

    def _reset_db(self, data_dir: Path) -> None:
        pass  # Tests use conn-based API and truncate; no per-dir reset
