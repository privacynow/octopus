"""Postgres-backed session store (Phase 12). Same contract as storage.py, different backend."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Callable

from app.storage import default_session

_SCHEMA_TABLE = "bot_runtime.sessions"


def session_exists(conn, chat_id: int) -> bool:
    """Check whether a session exists for the given chat_id."""
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
    """Load session dict for chat_id; merge into default_session. Same merge logic as storage.load_session."""
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
    saved = raw if isinstance(raw, dict) else json.loads(raw)
    try:
        for key in (
            "active_skills",
            "role",
            "pending_approval",
            "pending_retry",
            "awaiting_skill_setup",
            "compact_mode",
            "project_id",
            "file_policy",
            "model_profile",
            "created_at",
            "updated_at",
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
    except (json.JSONDecodeError, KeyError, TypeError):
        pass
    return session


def _upsert(conn, chat_id: int, session: dict[str, Any]) -> None:
    """Insert or replace a session row from a session dict."""
    has_pending = (
        session.get("pending_approval") is not None
        or session.get("pending_retry") is not None
    )
    has_setup = session.get("awaiting_skill_setup") is not None
    data_json = json.dumps(session, sort_keys=True)
    created_at = session.get("created_at", "") or datetime.now(timezone.utc).isoformat()
    updated_at = session.get("updated_at", "") or datetime.now(timezone.utc).isoformat()
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
                created_at = EXCLUDED.created_at,
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
    """Persist session dict."""
    session["updated_at"] = datetime.now(timezone.utc).isoformat()
    _upsert(conn, chat_id, session)


def delete_session(conn, chat_id: int) -> None:
    """Delete a session (for tests or admin cleanup)."""
    with conn.cursor() as cur:
        cur.execute(f"DELETE FROM {_SCHEMA_TABLE} WHERE chat_id = %s", (chat_id,))
    conn.commit()


def list_sessions(conn) -> list[dict[str, Any]]:
    """Return summary info for all stored sessions, ordered by updated_at desc."""
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
