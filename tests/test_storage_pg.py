"""Tests for Postgres-backed session store (Phase 12). Require Postgres harness."""

import threading

from octopus_sdk.registry.models import RoutedTaskResult
from octopus_sdk.providers import ProviderStateRecord
from app import storage_postgres
from octopus_sdk.identity import telegram_conversation_key
from octopus_sdk.sessions import default_session


def _provider_state_factory(conversation_key: str):
    del conversation_key
    return ProviderStateRecord()


def _delegation_session() -> dict:
    session = default_session("claude", _provider_state_factory("tg:test"), "on")
    session["pending_delegation"] = {
        "conversation_ref": "telegram:agent:12345",
        "title": "Delegation plan",
        "resume_instruction": "Resume when all child tasks complete.",
        "status": "submitted",
        "created_at": 1.0,
        "tasks": [
            {
                "routed_task_id": "task-1",
                "authority_ref": "registry:prod",
                "title": "Task one",
                "target_agent_id": "agent-1",
                "instructions": "Do task one.",
                "status": "submitted",
            },
            {
                "routed_task_id": "task-2",
                "authority_ref": "registry:prod",
                "title": "Task two",
                "target_agent_id": "agent-2",
                "instructions": "Do task two.",
                "status": "submitted",
            },
        ],
    }
    return session


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


def test_apply_delegation_result_atomically_merges_concurrent_updates(postgres_truncated):
    from app.db.postgres import get_connection

    conversation_key = telegram_conversation_key(5150)
    with get_connection(postgres_truncated) as conn:
        storage_postgres.save_session(conn, conversation_key, _delegation_session())

    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def _apply(task_id: str, summary: str) -> None:
        try:
            barrier.wait()
            with get_connection(postgres_truncated) as conn:
                outcome = storage_postgres.apply_delegation_result_atomically(
                    conn,
                    conversation_key,
                    routed_task_id=task_id,
                    authority_ref="registry:prod",
                    result=RoutedTaskResult(
                        routed_task_id=task_id,
                        status="completed",
                        transition_id=f"{task_id}-complete",
                        summary=summary,
                    ),
                )
                assert outcome.matched is True
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    first = threading.Thread(target=_apply, args=("task-1", "first done"))
    second = threading.Thread(target=_apply, args=("task-2", "second done"))
    first.start()
    second.start()
    first.join()
    second.join()

    assert errors == []
    with get_connection(postgres_truncated) as conn:
        loaded = storage_postgres.load_session(
            conn, conversation_key, "claude", _provider_state_factory, "on"
        )
    pending = loaded["pending_delegation"]
    assert pending is not None
    assert pending["status"] == "completed"
    assert {task["routed_task_id"]: task["status"] for task in pending["tasks"]} == {
        "task-1": "completed",
        "task-2": "completed",
    }
    assert {task["routed_task_id"]: task["summary"] for task in pending["tasks"]} == {
        "task-1": "first done",
        "task-2": "second done",
    }


def test_apply_delegation_result_atomically_does_not_touch_other_conversations(postgres_truncated):
    from app.db.postgres import get_connection

    first_key = telegram_conversation_key(7001)
    second_key = telegram_conversation_key(7002)
    with get_connection(postgres_truncated) as conn:
        storage_postgres.save_session(conn, first_key, _delegation_session())
        storage_postgres.save_session(conn, second_key, _delegation_session())

    with get_connection(postgres_truncated) as conn:
        storage_postgres.apply_delegation_result_atomically(
            conn,
            first_key,
            routed_task_id="task-1",
            authority_ref="registry:prod",
            result=RoutedTaskResult(
                routed_task_id="task-1",
                status="completed",
                transition_id="task-1-complete",
                summary="updated",
            ),
        )

    with get_connection(postgres_truncated) as conn:
        changed = storage_postgres.load_session(
            conn, first_key, "claude", _provider_state_factory, "on"
        )
        unchanged = storage_postgres.load_session(
            conn, second_key, "claude", _provider_state_factory, "on"
        )
    assert changed["pending_delegation"]["tasks"][0]["summary"] == "updated"
    assert unchanged["pending_delegation"]["tasks"][0].get("summary", "") == ""


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


def test_load_session_corrupt_provider_state_falls_back(postgres_truncated):
    """If stored provider_state is not a mapping, load_session must fall back to defaults."""
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
        loaded = storage_postgres.load_session(
            conn, conversation_key, "claude", lambda _ck="": ProviderStateRecord({"session_id": "new"}), "on"
        )
    assert isinstance(loaded["provider_state"], dict)
    assert loaded["provider_state"]["session_id"] == "new"
    assert loaded["created_at"] == session["created_at"], "row was not read — test is blind"


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


def test_load_session_non_object_json_falls_back_to_defaults(postgres_truncated):
    """If stored JSON decodes to a non-object, load_session must fall back to defaults."""
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
        loaded = storage_postgres.load_session(
            conn, conversation_key, "claude", _provider_state_factory, "on"
        )
    assert isinstance(loaded["provider_state"], dict)
    assert loaded["provider"] == "claude"
