"""Tests for Postgres-backed session store (Phase 12). Require Postgres harness."""

import pytest

from app.session_defaults import default_session
from app import storage_postgres


def _provider_state_factory():
    return {}


def test_session_exists_false_when_empty(postgres_truncated):
    from app.db.postgres import get_connection
    with get_connection(postgres_truncated) as conn:
        assert storage_postgres.session_exists(conn, 12345) is False


def test_save_and_load_session_roundtrip(postgres_truncated):
    from app.db.postgres import get_connection
    chat_id = 999
    session = default_session(
        "claude", _provider_state_factory(), "on", "Engineer", ("debugging",)
    )
    session["active_skills"] = ["debugging", "testing"]
    session["project_id"] = "myproj"
    with get_connection(postgres_truncated) as conn:
        storage_postgres.save_session(conn, chat_id, session)
        loaded = storage_postgres.load_session(
            conn, chat_id, "claude", _provider_state_factory, "on", "", ()
        )
    assert loaded["active_skills"] == ["debugging", "testing"]
    assert loaded["project_id"] == "myproj"
    assert loaded["provider"] == "claude"


def test_save_session_then_exists(postgres_truncated):
    from app.db.postgres import get_connection
    with get_connection(postgres_truncated) as conn:
        assert storage_postgres.session_exists(conn, 888) is False
        storage_postgres.save_session(
            conn, 888, default_session("codex", _provider_state_factory(), "off")
        )
        assert storage_postgres.session_exists(conn, 888) is True


def test_delete_session(postgres_truncated):
    from app.db.postgres import get_connection
    with get_connection(postgres_truncated) as conn:
        storage_postgres.save_session(
            conn, 777, default_session("claude", _provider_state_factory(), "off")
        )
        assert storage_postgres.session_exists(conn, 777) is True
        storage_postgres.delete_session(conn, 777)
        assert storage_postgres.session_exists(conn, 777) is False


def test_list_sessions_empty(postgres_truncated):
    from app.db.postgres import get_connection
    with get_connection(postgres_truncated) as conn:
        assert storage_postgres.list_sessions(conn) == []


def test_list_sessions_after_save(postgres_truncated):
    from app.db.postgres import get_connection
    with get_connection(postgres_truncated) as conn:
        storage_postgres.save_session(
            conn, 111, default_session("claude", _provider_state_factory(), "on")
        )
        storage_postgres.save_session(
            conn, 222, default_session("codex", _provider_state_factory(), "off")
        )
        listed = storage_postgres.list_sessions(conn)
    assert len(listed) == 2
    chat_ids = {s["chat_id"] for s in listed}
    assert chat_ids == {111, 222}


# -- Contract: created_at preserved on re-save --

def test_created_at_preserved_on_resave(postgres_truncated):
    """created_at must not change on subsequent saves (write-once contract)."""
    from app.db.postgres import get_connection
    chat_id = 60001
    session = default_session("claude", _provider_state_factory(), "on")
    original_created = session["created_at"]
    with get_connection(postgres_truncated) as conn:
        storage_postgres.save_session(conn, chat_id, session)
        loaded = storage_postgres.load_session(
            conn, chat_id, "claude", _provider_state_factory, "on"
        )
        loaded["role"] = "test-role"
        storage_postgres.save_session(conn, chat_id, loaded)
        reloaded = storage_postgres.load_session(
            conn, chat_id, "claude", _provider_state_factory, "on"
        )
    assert reloaded["created_at"] == original_created


# -- Contract: corrupt provider_state falls back to defaults --

def test_load_session_corrupt_provider_state_falls_back(postgres_truncated):
    """If stored provider_state is not a mapping, load_session must fall back to
    defaults instead of raising TypeError."""
    import json
    from app.db.postgres import get_connection
    chat_id = 60002
    session = default_session("claude", _provider_state_factory(), "on")
    with get_connection(postgres_truncated) as conn:
        storage_postgres.save_session(conn, chat_id, session)
        # Corrupt provider_state in the stored JSON
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE bot_runtime.sessions SET data = data || %s::jsonb WHERE chat_id = %s",
                ('{"provider_state": [1, 2, 3]}', chat_id),
            )
        conn.commit()
        loaded = storage_postgres.load_session(
            conn, chat_id, "claude", lambda: {"session_id": "new"}, "on"
        )
    assert isinstance(loaded["provider_state"], dict)
    assert loaded["provider_state"]["session_id"] == "new"
    # Prove the row was actually found — created_at was loaded from stored data
    assert loaded["created_at"] == session["created_at"], "row was not read — test is blind"


def test_falsy_created_at_normalized_on_save(postgres_truncated):
    """If created_at is falsy (empty string), save must normalize it to a
    real timestamp so it round-trips as a non-empty value."""
    from app.db.postgres import get_connection
    chat_id = 60003
    session = default_session("claude", _provider_state_factory(), "on")
    session["created_at"] = ""  # force falsy
    with get_connection(postgres_truncated) as conn:
        storage_postgres.save_session(conn, chat_id, session)
        loaded = storage_postgres.load_session(
            conn, chat_id, "claude", _provider_state_factory, "on"
        )
    assert loaded["created_at"] != "", "falsy created_at was not normalized on save"
    assert len(loaded["created_at"]) > 10, "created_at should be an ISO timestamp"


def test_load_session_non_object_json_falls_back_to_defaults(postgres_truncated):
    """If stored JSON decodes to a non-object (e.g. a list), load_session must
    fall back to defaults instead of raising AttributeError."""
    from app.db.postgres import get_connection
    chat_id = 60004
    session = default_session("claude", _provider_state_factory(), "on")
    with get_connection(postgres_truncated) as conn:
        storage_postgres.save_session(conn, chat_id, session)
        # Overwrite stored data with a valid-JSON non-object
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE bot_runtime.sessions SET data = '[]'::jsonb WHERE chat_id = %s",
                (chat_id,),
            )
        conn.commit()
        loaded = storage_postgres.load_session(
            conn, chat_id, "claude", _provider_state_factory, "on"
        )
    assert isinstance(loaded["provider_state"], dict)
    assert loaded["provider"] == "claude"
