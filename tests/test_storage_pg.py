"""Tests for Postgres-backed session store (Phase 12). Require Postgres harness."""

import pytest

from octopus_sdk.deferred_notifications import DeferredNotification
from octopus_sdk.providers import ProviderStateRecord
from app import storage_postgres
from octopus_sdk.identity import telegram_conversation_key
from octopus_sdk.sessions import default_session


def _provider_state_factory(conversation_key: str):
    del conversation_key
    return ProviderStateRecord()


def test_session_exists_false_when_empty(postgres_truncated):
    from app.db.postgres import get_connection

    with get_connection(postgres_truncated) as conn:
        assert storage_postgres.session_exists(conn, telegram_conversation_key(12345)) is False


def test_save_and_load_session_roundtrip(postgres_truncated):
    from app.db.postgres import get_connection

    conversation_key = telegram_conversation_key(999)
    session = default_session(
        "claude", _provider_state_factory("tg:test"), "on", "Engineer", ("debugging",)
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
            default_session("codex", _provider_state_factory("tg:test"), "off"),
        )
        assert storage_postgres.session_exists(conn, conversation_key) is True


def test_postgres_deferred_notifications_flush_and_expire(postgres_truncated):
    from app.db.postgres import get_connection

    with get_connection(postgres_truncated) as conn:
        storage_postgres.enqueue_deferred_notification(
            conn,
            DeferredNotification(
                notification_id="notif-live",
                target_agent_id="agent-1",
                actor_key="telegram:42",
                content="live",
                created_at="2026-03-28T00:00:00+00:00",
                expires_at="2026-03-29T00:00:00+00:00",
            ),
        )
        storage_postgres.enqueue_deferred_notification(
            conn,
            DeferredNotification(
                notification_id="notif-stale",
                target_agent_id="agent-1",
                actor_key="telegram:42",
                content="stale",
                created_at="2026-03-28T00:00:00+00:00",
                expires_at="2026-03-28T00:00:01+00:00",
            ),
        )
        assert storage_postgres.expire_stale_deferred_notifications(
            conn,
            now="2026-03-28T00:00:02+00:00",
        ) == 1
        delivered = storage_postgres.flush_deferred_notifications(
            conn,
            target_agent_id="agent-1",
            actor_key="telegram:42",
            now="2026-03-28T12:00:00+00:00",
        )
        assert [item.notification_id for item in delivered] == ["notif-live"]
        assert storage_postgres.flush_deferred_notifications(
            conn,
            target_agent_id="agent-1",
            actor_key="telegram:42",
        ) == []


def test_delete_session(postgres_truncated):
    from app.db.postgres import get_connection

    conversation_key = telegram_conversation_key(777)
    with get_connection(postgres_truncated) as conn:
        storage_postgres.save_session(
            conn,
            conversation_key,
            default_session("claude", _provider_state_factory("tg:test"), "off"),
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
            default_session("claude", _provider_state_factory("tg:test"), "on"),
        )
        storage_postgres.save_session(
            conn,
            telegram_conversation_key(222),
            default_session("codex", _provider_state_factory("tg:test"), "off"),
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
    session = default_session("claude", _provider_state_factory("tg:test"), "on")
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


def test_load_session_corrupt_provider_state_raises(postgres_truncated):
    """If stored provider_state is not a mapping, load_session must fail explicitly."""
    from app.db.postgres import get_connection

    conversation_key = telegram_conversation_key(60002)
    session = default_session("claude", _provider_state_factory("tg:test"), "on")
    with get_connection(postgres_truncated) as conn:
        storage_postgres.save_session(conn, conversation_key, session)
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE bot_runtime.sessions SET data = data || %s::jsonb WHERE conversation_key = %s",
                ('{"provider_state": [1, 2, 3]}', conversation_key),
            )
        conn.commit()
        with pytest.raises(RuntimeError, match="not valid current schema data"):
            storage_postgres.load_session(
                conn,
                conversation_key,
                "claude",
                lambda _ck="": ProviderStateRecord({"session_id": "new"}),
                "on",
            )
    assert session["created_at"], "row was not written — test is blind"


def test_falsy_created_at_normalized_on_save(postgres_truncated):
    """If created_at is falsy, save must normalize it to a real timestamp."""
    from app.db.postgres import get_connection

    conversation_key = telegram_conversation_key(60003)
    session = default_session("claude", _provider_state_factory("tg:test"), "on")
    session["created_at"] = ""
    with get_connection(postgres_truncated) as conn:
        storage_postgres.save_session(conn, conversation_key, session)
        loaded = storage_postgres.load_session(
            conn, conversation_key, "claude", _provider_state_factory, "on"
        )
    assert loaded["created_at"] != "", "falsy created_at was not normalized on save"
    assert len(loaded["created_at"]) > 10, "created_at should be an ISO timestamp"


def test_load_session_non_object_json_raises(postgres_truncated):
    """If stored JSON decodes to a non-object, load_session must fail explicitly."""
    from app.db.postgres import get_connection

    conversation_key = telegram_conversation_key(60004)
    session = default_session("claude", _provider_state_factory("tg:test"), "on")
    with get_connection(postgres_truncated) as conn:
        storage_postgres.save_session(conn, conversation_key, session)
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE bot_runtime.sessions SET data = '[]'::jsonb WHERE conversation_key = %s",
                (conversation_key,),
            )
        conn.commit()
        with pytest.raises(RuntimeError, match="not an object"):
            storage_postgres.load_session(
                conn, conversation_key, "claude", _provider_state_factory, "on"
            )
