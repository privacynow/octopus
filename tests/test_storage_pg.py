"""Tests for Postgres-backed session store (Phase 12). Require Postgres harness."""

import pytest

from app.storage import default_session
from app import storage_pg


def _provider_state_factory():
    return {}


def test_session_exists_false_when_empty(postgres_truncated):
    from app.db.postgres import get_connection
    with get_connection(postgres_truncated) as conn:
        assert storage_pg.session_exists(conn, 12345) is False


def test_save_and_load_session_roundtrip(postgres_truncated):
    from app.db.postgres import get_connection
    chat_id = 999
    session = default_session(
        "claude", _provider_state_factory(), "on", "Engineer", ("debugging",)
    )
    session["active_skills"] = ["debugging", "testing"]
    session["project_id"] = "myproj"
    with get_connection(postgres_truncated) as conn:
        storage_pg.save_session(conn, chat_id, session)
        loaded = storage_pg.load_session(
            conn, chat_id, "claude", _provider_state_factory, "on", "", ()
        )
    assert loaded["active_skills"] == ["debugging", "testing"]
    assert loaded["project_id"] == "myproj"
    assert loaded["provider"] == "claude"


def test_save_session_then_exists(postgres_truncated):
    from app.db.postgres import get_connection
    with get_connection(postgres_truncated) as conn:
        assert storage_pg.session_exists(conn, 888) is False
        storage_pg.save_session(
            conn, 888, default_session("codex", _provider_state_factory(), "off")
        )
        assert storage_pg.session_exists(conn, 888) is True


def test_delete_session(postgres_truncated):
    from app.db.postgres import get_connection
    with get_connection(postgres_truncated) as conn:
        storage_pg.save_session(
            conn, 777, default_session("claude", _provider_state_factory(), "off")
        )
        assert storage_pg.session_exists(conn, 777) is True
        storage_pg.delete_session(conn, 777)
        assert storage_pg.session_exists(conn, 777) is False


def test_list_sessions_empty(postgres_truncated):
    from app.db.postgres import get_connection
    with get_connection(postgres_truncated) as conn:
        assert storage_pg.list_sessions(conn) == []


def test_list_sessions_after_save(postgres_truncated):
    from app.db.postgres import get_connection
    with get_connection(postgres_truncated) as conn:
        storage_pg.save_session(
            conn, 111, default_session("claude", _provider_state_factory(), "on")
        )
        storage_pg.save_session(
            conn, 222, default_session("codex", _provider_state_factory(), "off")
        )
        listed = storage_pg.list_sessions(conn)
    assert len(listed) == 2
    chat_ids = {s["chat_id"] for s in listed}
    assert chat_ids == {111, 222}
