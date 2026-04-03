"""Postgres-backed session store. Conn-based API for tests; PostgresSessionStore for runtime_backend."""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from octopus_sdk.deferred_notifications import DeferredNotification
from octopus_sdk.sessions import default_session, session_from_dict, session_to_dict
from octopus_sdk.time_utils import utc_now_iso

_SCHEMA_TABLE = "bot_runtime.sessions"
_DEFERRED_NOTIFICATIONS_TABLE = "bot_runtime.deferred_notifications"


# ---------------------------------------------------------------------------
# Conn-based API (used by tests and by PostgresSessionStore)
# ---------------------------------------------------------------------------

def session_exists(conn, conversation_key: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT 1 FROM {_SCHEMA_TABLE} WHERE conversation_key = %s",
            (conversation_key,),
        )
        return cur.fetchone() is not None


def load_session(
    conn,
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
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT data FROM {_SCHEMA_TABLE} WHERE conversation_key = %s",
            (conversation_key,),
        )
        row = cur.fetchone()
    if row is None:
        return session
    raw = row[0]
    try:
        saved = raw if isinstance(raw, dict) else json.loads(raw)
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


def _upsert(conn, conversation_key: str, session: dict[str, Any]) -> None:
    stored_session = dict(session)
    has_setup = session.get("awaiting_skill_setup") is not None
    # Normalize timestamps before serializing so JSON data and column agree
    if not stored_session.get("created_at"):
        stored_session["created_at"] = utc_now_iso()
    if not stored_session.get("updated_at"):
        stored_session["updated_at"] = utc_now_iso()
    stored_session = session_to_dict(session_from_dict(stored_session))
    has_pending = (
        stored_session.get("pending_approval") is not None
        or stored_session.get("pending_retry") is not None
    )
    has_setup = stored_session.get("awaiting_skill_setup") is not None
    created_at = stored_session["created_at"]
    updated_at = stored_session["updated_at"]
    data_json = json.dumps(stored_session, sort_keys=True)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {_SCHEMA_TABLE}
            (conversation_key, provider, data, has_pending, has_setup, project_id, file_policy, created_at, updated_at)
            VALUES (%s, %s, %s::jsonb, %s, %s, %s, %s, %s::timestamptz, %s::timestamptz)
            ON CONFLICT (conversation_key) DO UPDATE SET
                provider = EXCLUDED.provider,
                data = EXCLUDED.data,
                has_pending = EXCLUDED.has_pending,
                has_setup = EXCLUDED.has_setup,
                project_id = EXCLUDED.project_id,
                file_policy = EXCLUDED.file_policy,
                updated_at = EXCLUDED.updated_at
            """,
            (
                conversation_key,
                stored_session.get("provider", ""),
                data_json,
                has_pending,
                has_setup,
                stored_session.get("project_id"),
                stored_session.get("file_policy"),
                created_at,
                updated_at,
            ),
        )


def save_session(conn, conversation_key: str, session: dict[str, Any]) -> None:
    session["updated_at"] = utc_now_iso()
    _upsert(conn, conversation_key, session)
    conn.commit()


def delete_session(conn, conversation_key: str) -> None:
    with conn.cursor() as cur:
        cur.execute(f"DELETE FROM {_SCHEMA_TABLE} WHERE conversation_key = %s", (conversation_key,))
    conn.commit()


def list_sessions(conn) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT conversation_key, provider, data, has_pending, has_setup, created_at, updated_at
            FROM {_SCHEMA_TABLE}
            ORDER BY updated_at DESC
            """
        )
        rows = cur.fetchall()
    results: list[dict[str, Any]] = []
    for row in rows:
        conversation_key, provider, data, has_pending, has_setup, created_at, updated_at = (
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
            "conversation_key": conversation_key,
            "provider": provider,
            "active_skills": data_dict.get("active_skills", []),
            "has_pending": bool(has_pending),
            "has_setup": bool(has_setup),
            "approval_mode": data_dict.get("approval_mode", "off"),
            "updated_at": updated_at.isoformat() if hasattr(updated_at, "isoformat") else updated_at,
            "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else created_at,
        })
    return results


def enqueue_deferred_notification(conn, notification: DeferredNotification) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {_DEFERRED_NOTIFICATIONS_TABLE} (
                notification_id,
                target_agent_id,
                actor_key,
                content,
                priority,
                created_at,
                expires_at
            )
            VALUES (%s, %s, %s, %s, %s, %s::timestamptz, %s::timestamptz)
            ON CONFLICT (notification_id) DO UPDATE SET
                target_agent_id = EXCLUDED.target_agent_id,
                actor_key = EXCLUDED.actor_key,
                content = EXCLUDED.content,
                priority = EXCLUDED.priority,
                created_at = EXCLUDED.created_at,
                expires_at = EXCLUDED.expires_at
            """,
            (
                notification.notification_id,
                notification.target_agent_id,
                notification.actor_key,
                notification.content,
                notification.priority,
                notification.created_at,
                notification.expires_at,
            ),
        )
    conn.commit()


def flush_deferred_notifications(
    conn,
    *,
    target_agent_id: str,
    actor_key: str,
    now: str | None = None,
) -> list[DeferredNotification]:
    current = now or utc_now_iso()
    with conn.cursor() as cur:
        cur.execute(
            f"DELETE FROM {_DEFERRED_NOTIFICATIONS_TABLE} WHERE expires_at <= %s::timestamptz",
            (current,),
        )
        cur.execute(
            f"""
            SELECT notification_id, target_agent_id, actor_key, content, priority, created_at, expires_at
            FROM {_DEFERRED_NOTIFICATIONS_TABLE}
            WHERE target_agent_id = %s AND actor_key = %s
            ORDER BY created_at ASC
            """,
            (target_agent_id, actor_key),
        )
        rows = cur.fetchall()
        if rows:
            cur.executemany(
                f"DELETE FROM {_DEFERRED_NOTIFICATIONS_TABLE} WHERE notification_id = %s",
                [(str(row[0]),) for row in rows],
            )
    conn.commit()
    return [
        DeferredNotification(
            notification_id=str(row[0]),
            target_agent_id=str(row[1]),
            actor_key=str(row[2]),
            content=str(row[3]),
            priority=str(row[4]),
            created_at=row[5].isoformat() if hasattr(row[5], "isoformat") else str(row[5]),
            expires_at=row[6].isoformat() if hasattr(row[6], "isoformat") else str(row[6]),
        )
        for row in rows
    ]


def expire_stale_deferred_notifications(conn, *, now: str | None = None) -> int:
    current = now or utc_now_iso()
    with conn.cursor() as cur:
        cur.execute(
            f"DELETE FROM {_DEFERRED_NOTIFICATIONS_TABLE} WHERE expires_at <= %s::timestamptz",
            (current,),
        )
        deleted = int(cur.rowcount or 0)
    conn.commit()
    return deleted


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

    def session_exists(self, data_dir: Path, conversation_key: str) -> bool:
        with self._conn() as conn:
            return session_exists(conn, conversation_key)

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
        with self._conn() as conn:
            return load_session(
                conn, conversation_key, provider_name, provider_state_factory,
                approval_mode, role, default_skills,
            )

    def save_session(self, data_dir: Path, conversation_key: str, session: dict[str, Any]) -> None:
        with self._conn() as conn:
            save_session(conn, conversation_key, session)

    def delete_session(self, data_dir: Path, conversation_key: str) -> None:
        with self._conn() as conn:
            delete_session(conn, conversation_key)

    def list_sessions(self, data_dir: Path) -> list[dict[str, Any]]:
        with self._conn() as conn:
            return list_sessions(conn)

    def close_db(self, data_dir: Path) -> None:
        pass  # Pool managed by get_connection

    def close_all_db(self) -> None:
        pass

    def debug_connection(self, data_dir: Path):
        del data_dir
        from app.db.postgres import PostgresDebugConnection

        return PostgresDebugConnection(self._database_url, search_path="bot_runtime")

    def reset_db_for_test(self, data_dir: Path) -> None:
        pass  # Tests use conn-based API and truncate; no per-dir reset

    def enqueue_deferred_notification(
        self,
        data_dir: Path,
        notification: DeferredNotification,
    ) -> None:
        del data_dir
        with self._conn() as conn:
            enqueue_deferred_notification(conn, notification)

    def flush_deferred_notifications(
        self,
        data_dir: Path,
        *,
        target_agent_id: str,
        actor_key: str,
        now: str | None = None,
    ) -> list[DeferredNotification]:
        del data_dir
        with self._conn() as conn:
            return flush_deferred_notifications(
                conn,
                target_agent_id=target_agent_id,
                actor_key=actor_key,
                now=now,
            )

    def expire_stale_deferred_notifications(
        self,
        data_dir: Path,
        *,
        now: str | None = None,
    ) -> int:
        del data_dir
        with self._conn() as conn:
            return expire_stale_deferred_notifications(conn, now=now)
