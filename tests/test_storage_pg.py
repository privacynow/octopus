"""Tests for Postgres-backed session store (Phase 12). Require Postgres harness."""

from app import storage_postgres
from app.identity import telegram_conversation_key
from app.session_defaults import default_session


def _provider_state_factory():
    return {}


def test_session_exists_false_when_empty(postgres_truncated):
    from app.db.postgres import get_connection

    with get_connection(postgres_truncated) as conn:
        assert storage_postgres.session_exists(conn, telegram_conversation_key(12345)) is False


def test_save_and_load_session_roundtrip(postgres_truncated):
    from app.db.postgres import get_connection

    conversation_key = telegram_conversation_key(999)
    session = default_session(
        "claude", _provider_state_factory(), "on", "Engineer", ("debugging",)
    )
    session["active_skills"] = ["debugging", "testing"]
    session["project_id"] = "myproj"
    with get_connection(postgres_truncated) as conn:
        storage_postgres.save_session(conn, conversation_key, session)
        loaded = storage_postgres.load_session(
            conn, conversation_key, "claude", _provider_state_factory, "on", "", ()
        )
    assert loaded["active_skills"] == ["debugging", "testing"]
    assert loaded["project_id"] == "myproj"
    assert loaded["provider"] == "claude"


def test_save_session_then_exists(postgres_truncated):
    from app.db.postgres import get_connection

    conversation_key = telegram_conversation_key(888)
    with get_connection(postgres_truncated) as conn:
        assert storage_postgres.session_exists(conn, conversation_key) is False
        storage_postgres.save_session(
            conn,
            conversation_key,
            default_session("codex", _provider_state_factory(), "off"),
        )
        assert storage_postgres.session_exists(conn, conversation_key) is True


def test_delete_session(postgres_truncated):
    from app.db.postgres import get_connection

    conversation_key = telegram_conversation_key(777)
    with get_connection(postgres_truncated) as conn:
        storage_postgres.save_session(
            conn,
            conversation_key,
            default_session("claude", _provider_state_factory(), "off"),
        )
        assert storage_postgres.session_exists(conn, conversation_key) is True
        storage_postgres.delete_session(conn, conversation_key)
        assert storage_postgres.session_exists(conn, conversation_key) is False


def test_list_sessions_empty(postgres_truncated):
    from app.db.postgres import get_connection

    with get_connection(postgres_truncated) as conn:
        assert storage_postgres.list_sessions(conn) == []


def test_list_sessions_after_save(postgres_truncated):
    from app.db.postgres import get_connection

    with get_connection(postgres_truncated) as conn:
        storage_postgres.save_session(
            conn,
            telegram_conversation_key(111),
            default_session("claude", _provider_state_factory(), "on"),
        )
        storage_postgres.save_session(
            conn,
            telegram_conversation_key(222),
            default_session("codex", _provider_state_factory(), "off"),
        )
        listed = storage_postgres.list_sessions(conn)
    assert len(listed) == 2
    conversation_keys = {s["conversation_key"] for s in listed}
    assert conversation_keys == {
        telegram_conversation_key(111),
        telegram_conversation_key(222),
    }


def test_created_at_preserved_on_resave(postgres_truncated):
    """created_at must not change on subsequent saves (write-once contract)."""
    from app.db.postgres import get_connection

    conversation_key = telegram_conversation_key(60001)
    session = default_session("claude", _provider_state_factory(), "on")
    original_created = session["created_at"]
    with get_connection(postgres_truncated) as conn:
        storage_postgres.save_session(conn, conversation_key, session)
        loaded = storage_postgres.load_session(
            conn, conversation_key, "claude", _provider_state_factory, "on"
        )
        loaded["role"] = "test-role"
        storage_postgres.save_session(conn, conversation_key, loaded)
        reloaded = storage_postgres.load_session(
            conn, conversation_key, "claude", _provider_state_factory, "on"
        )
    assert reloaded["created_at"] == original_created


def test_load_session_corrupt_provider_state_falls_back(postgres_truncated):
    """If stored provider_state is not a mapping, load_session must fall back to defaults."""
    from app.db.postgres import get_connection

    conversation_key = telegram_conversation_key(60002)
    session = default_session("claude", _provider_state_factory(), "on")
    with get_connection(postgres_truncated) as conn:
        storage_postgres.save_session(conn, conversation_key, session)
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE bot_runtime.sessions SET data = data || %s::jsonb WHERE conversation_key = %s",
                ('{"provider_state": [1, 2, 3]}', conversation_key),
            )
        conn.commit()
        loaded = storage_postgres.load_session(
            conn, conversation_key, "claude", lambda: {"session_id": "new"}, "on"
        )
    assert isinstance(loaded["provider_state"], dict)
    assert loaded["provider_state"]["session_id"] == "new"
    assert loaded["created_at"] == session["created_at"], "row was not read — test is blind"


def test_falsy_created_at_normalized_on_save(postgres_truncated):
    """If created_at is falsy, save must normalize it to a real timestamp."""
    from app.db.postgres import get_connection

    conversation_key = telegram_conversation_key(60003)
    session = default_session("claude", _provider_state_factory(), "on")
    session["created_at"] = ""
    with get_connection(postgres_truncated) as conn:
        storage_postgres.save_session(conn, conversation_key, session)
        loaded = storage_postgres.load_session(
            conn, conversation_key, "claude", _provider_state_factory, "on"
        )
    assert loaded["created_at"] != "", "falsy created_at was not normalized on save"
    assert len(loaded["created_at"]) > 10, "created_at should be an ISO timestamp"


def test_load_session_non_object_json_falls_back_to_defaults(postgres_truncated):
    """If stored JSON decodes to a non-object, load_session must fall back to defaults."""
    from app.db.postgres import get_connection

    conversation_key = telegram_conversation_key(60004)
    session = default_session("claude", _provider_state_factory(), "on")
    with get_connection(postgres_truncated) as conn:
        storage_postgres.save_session(conn, conversation_key, session)
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE bot_runtime.sessions SET data = '[]'::jsonb WHERE conversation_key = %s",
                (conversation_key,),
            )
        conn.commit()
        loaded = storage_postgres.load_session(
            conn, conversation_key, "claude", _provider_state_factory, "on"
        )
    assert isinstance(loaded["provider_state"], dict)
    assert loaded["provider"] == "claude"
