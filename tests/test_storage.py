"""Tests for storage.py — session CRUD (SQLite-backed), path resolution, uploads."""

import json
import sqlite3
import tempfile
import threading
from pathlib import Path

import pytest

from octopus_sdk.deferred_notifications import DeferredNotification
from octopus_sdk.registry.models import RoutedTaskResult
from octopus_sdk.identity import telegram_conversation_key
from octopus_sdk.providers import ProviderStateRecord
from tests.support.handler_support import pending_approval_dict
from app.storage_sqlite import SQLiteSessionStore
from app.storage import (
    build_upload_path,
    default_session,
    debug_session_connection,
    ensure_data_dirs,
    is_image_path,
    load_session,
    reset_db_for_test,
    resolve_allowed_path,
    sanitize_filename,
    list_sessions,
    save_session,
    session_exists,
)


def _state(**kwargs) -> ProviderStateRecord:
    return ProviderStateRecord(kwargs)


# -- sanitize_filename --

def test_sanitize_filename_clean():
    assert sanitize_filename("hello.txt") == "hello.txt"


def test_sanitize_filename_spaces():
    assert sanitize_filename("my file (1).doc") == "my_file_1_.doc"


def test_sanitize_filename_empty():
    assert sanitize_filename("...") == "attachment"


# -- is_image_path --

def test_is_image_path_png():
    assert is_image_path(Path("test.png")) is True


def test_is_image_path_jpg():
    assert is_image_path(Path("test.JPG")) is True


def test_is_image_path_txt():
    assert is_image_path(Path("test.txt")) is False


# -- session management --

def test_session_management():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        assert (data_dir / "uploads").is_dir()
        # sessions.db is created on first session use (no longer by ensure_data_dirs)

        # default_session
        s = default_session("claude", _state(session_id="abc", started=False), "on")
        assert s["provider"] == "claude"
        assert s["provider_state"]["session_id"] == "abc"
        assert s["approval_mode"] == "on"
        assert "created_at" in s
        assert "updated_at" in s

        # save + load (first use creates sessions.db)
        save_session(data_dir, telegram_conversation_key(12345), s)
        assert (data_dir / "sessions.db").exists()
        assert session_exists(data_dir, telegram_conversation_key(12345))
        assert not session_exists(data_dir, telegram_conversation_key(99998))

        loaded = load_session(
            data_dir,
            telegram_conversation_key(12345),
            "claude",
            lambda _ck="": _state(session_id="abc", started=False),
            "on",
        )
        assert loaded["provider"] == "claude"
        assert loaded["provider_state"]["session_id"] == "abc"

        # load with new provider_state keys (migration-safe)
        loaded2 = load_session(
            data_dir,
            telegram_conversation_key(12345),
            "claude",
            lambda _ck="": _state(session_id="abc", started=False, new_key="default"),
            "on",
        )
        assert loaded2["provider_state"]["new_key"] == "default"

        # explicit approval mode survives reload, including its source flag
        s["approval_mode"] = "off"
        s["approval_mode_explicit"] = True
        save_session(data_dir, telegram_conversation_key(12345), s)
        loaded3 = load_session(
            data_dir,
            telegram_conversation_key(12345),
            "claude",
            lambda _ck="": _state(session_id="abc", started=False),
            "on",
        )
        assert loaded3["approval_mode"] == "off"
        assert loaded3["approval_mode_explicit"] is True


def test_sqlite_deferred_notifications_flush_and_expire():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        store = SQLiteSessionStore()
        store.enqueue_deferred_notification(
            data_dir,
            DeferredNotification(
                notification_id="notif-live",
                target_agent_id="agent-1",
                actor_key="telegram:42",
                content="live",
                created_at="2026-03-28T00:00:00+00:00",
                expires_at="2026-03-29T00:00:00+00:00",
            ),
        )
        store.enqueue_deferred_notification(
            data_dir,
            DeferredNotification(
                notification_id="notif-stale",
                target_agent_id="agent-1",
                actor_key="telegram:42",
                content="stale",
                created_at="2026-03-28T00:00:00+00:00",
                expires_at="2026-03-28T00:00:01+00:00",
            ),
        )

        assert store.expire_stale_deferred_notifications(
            data_dir,
            now="2026-03-28T00:00:02+00:00",
        ) == 1
        delivered = store.flush_deferred_notifications(
            data_dir,
            target_agent_id="agent-1",
            actor_key="telegram:42",
            now="2026-03-28T12:00:00+00:00",
        )
        assert [item.notification_id for item in delivered] == ["notif-live"]
        assert store.flush_deferred_notifications(
            data_dir,
            target_agent_id="agent-1",
            actor_key="telegram:42",
        ) == []

        # fresh session for new chat
        fresh = load_session(
            data_dir,
            telegram_conversation_key(99999),
            "codex",
            lambda _ck="": _state(thread_id=None),
            "off",
        )
        assert fresh["provider"] == "codex"
        assert fresh["provider_state"]["thread_id"] is None

        reset_db_for_test(data_dir)


def test_session_store_uses_thread_local_sqlite_connections():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        conversation_key = telegram_conversation_key(4242)
        session = default_session("claude", _state(session_id="abc", started=False), "on")
        save_session(data_dir, conversation_key, session)

        loaded__thread: dict[str, object] = {}
        error__thread: list[BaseException] = []

        def _load() -> None:
            try:
                loaded__thread.update(
                    load_session(
                        data_dir,
                        conversation_key,
                        "claude",
                        lambda _ck="": _state(session_id="abc", started=False),
                        "on",
                    )
                )
            except BaseException as exc:  # pragma: no cover - assertion below
                error__thread.append(exc)

        worker = threading.Thread(target=_load)
        worker.start()
        worker.join()

        assert error__thread == []
        assert loaded__thread["provider"] == "claude"
        assert loaded__thread["provider_state"]["session_id"] == "abc"


def _delegation_session(provider_name: str = "claude") -> dict:
    session = default_session(provider_name, _state(session_id="abc", started=False), "on")
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


def test_apply_delegation_result_atomically_merges_concurrent_updates_for_same_conversation():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        conversation_key = telegram_conversation_key(5150)
        initial_store = SQLiteSessionStore()
        initial_store.save_session(data_dir, conversation_key, _delegation_session())
        initial_store.close_all_db()

        barrier = threading.Barrier(2)
        errors: list[BaseException] = []

        def _apply(task_id: str, summary: str) -> None:
            worker_store = SQLiteSessionStore()
            try:
                barrier.wait()
                outcome = worker_store.apply_delegation_result_atomically(
                    data_dir,
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
            finally:
                worker_store.close_all_db()

        first = threading.Thread(target=_apply, args=("task-1", "first done"))
        second = threading.Thread(target=_apply, args=("task-2", "second done"))
        first.start()
        second.start()
        first.join()
        second.join()

        assert errors == []
        verify_store = SQLiteSessionStore()
        loaded = verify_store.load_session(
            data_dir,
            conversation_key,
            "claude",
            lambda _ck="": _state(session_id="abc", started=False),
            "on",
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
        verify_store.close_all_db()


def test_apply_delegation_result_atomically_does_not_touch_other_conversations():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        store = SQLiteSessionStore()
        first_key = telegram_conversation_key(7001)
        second_key = telegram_conversation_key(7002)
        store.save_session(data_dir, first_key, _delegation_session())
        store.save_session(data_dir, second_key, _delegation_session())

        store.apply_delegation_result_atomically(
            data_dir,
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

        changed = store.load_session(
            data_dir,
            first_key,
            "claude",
            lambda _ck="": _state(session_id="abc", started=False),
            "on",
        )
        unchanged = store.load_session(
            data_dir,
            second_key,
            "claude",
            lambda _ck="": _state(session_id="abc", started=False),
            "on",
        )
        assert changed["pending_delegation"]["tasks"][0]["summary"] == "updated"
        assert unchanged["pending_delegation"]["tasks"][0].get("summary", "") == ""
        store.close_all_db()


# -- resolve_allowed_path --

def test_resolve_allowed_path():
    with tempfile.TemporaryDirectory() as tmp:
        test_file = Path(tmp) / "test.txt"
        test_file.write_text("x")
        roots = [Path(tmp)]

        resolved = resolve_allowed_path(str(test_file), roots)
        assert resolved == test_file.resolve()

        resolved2 = resolve_allowed_path("test.txt", roots)
        assert resolved2 == test_file.resolve()

        resolved3 = resolve_allowed_path("/etc/passwd", roots)
        assert resolved3 is None

        resolved4 = resolve_allowed_path("/nonexistent/file", roots)
        assert resolved4 is None


# -- build_upload_path --

def test_build_upload_path():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        path = build_upload_path(data_dir, telegram_conversation_key(42), "photo.jpg")
        assert str(path).startswith(str(data_dir / "uploads" / "42"))
        assert path.name.endswith("_photo.jpg")
        reset_db_for_test(data_dir)


# -- list_sessions --

def test_list_sessions():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)

        # Empty database
        assert list_sessions(data_dir) == []

        # Create two sessions
        s1 = default_session("claude", _state(session_id="a", started=False), "on")
        s1["active_skills"] = ["code-review"]
        save_session(data_dir, telegram_conversation_key(111), s1)

        s2 = default_session("codex", _state(thread_id=None), "off")
        s2["pending_approval"] = pending_approval_dict(prompt="test", created_at=0)
        save_session(data_dir, telegram_conversation_key(222), s2)

        result = list_sessions(data_dir)
        assert len(result) == 2

        # Most recently updated should be first
        assert result[0]["conversation_key"] == telegram_conversation_key(222)
        assert result[1]["conversation_key"] == telegram_conversation_key(111)

        # Check fields
        s222 = result[0]
        assert s222["provider"] == "codex"
        assert s222["has_pending"] is True
        assert s222["has_setup"] is False
        assert s222["approval_mode"] == "off"

        s111 = result[1]
        assert s111["active_skills"] == ["code-review"]
        assert s111["provider"] == "claude"
        assert s111["has_pending"] is False

        reset_db_for_test(data_dir)


# -- JSON file migration --

def test_json_file_migration():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        (data_dir / "uploads").mkdir(parents=True)
        (data_dir / "credentials").mkdir(parents=True)

        # Create legacy JSON session files
        sessions_dir = data_dir / "sessions"
        sessions_dir.mkdir()
        s = default_session("claude", _state(session_id="migrated"), "on")
        s["active_skills"] = ["github-integration"]
        (sessions_dir / "12345.json").write_text(json.dumps(s))

        s2 = default_session("codex", _state(thread_id="t1"), "off")
        (sessions_dir / "67890.json").write_text(json.dumps(s2))

        # Also a corrupt file — should be skipped
        (sessions_dir / "bad.json").write_text("{corrupt")

        ensure_data_dirs(data_dir)
        # First use of session store creates DB and runs JSON migration
        list_sessions(data_dir)

        assert not sessions_dir.exists()
        assert (data_dir / "sessions.db").exists()

        # Verify migrated data
        loaded = load_session(
            data_dir,
            telegram_conversation_key(12345),
            "claude",
            lambda _ck="": _state(session_id="new"),
            "on",
        )
        assert loaded["provider_state"]["session_id"] == "migrated"
        assert loaded["active_skills"] == ["github-integration"]

        loaded2 = load_session(
            data_dir,
            telegram_conversation_key(67890),
            "codex",
            lambda _ck="": _state(thread_id=None),
            "off",
        )
        assert loaded2["provider_state"]["thread_id"] == "t1"

        # Corrupt file was skipped — no session for "bad"
        assert not session_exists(data_dir, telegram_conversation_key(0))

        result = list_sessions(data_dir)
        assert len(result) == 2

        reset_db_for_test(data_dir)


def test_session_migration_rolls_back_when_step_fails(monkeypatch: pytest.MonkeyPatch):
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        db_path = data_dir / "sessions.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            """
            CREATE TABLE sessions (
                chat_id INTEGER PRIMARY KEY,
                provider TEXT NOT NULL DEFAULT '',
                data TEXT NOT NULL DEFAULT '{}',
                has_pending INTEGER NOT NULL DEFAULT 0,
                has_setup INTEGER NOT NULL DEFAULT 0,
                project_id TEXT,
                file_policy TEXT,
                created_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute("INSERT INTO meta (key, value) VALUES ('schema_version', '1')")
        conn.commit()
        conn.close()

        store = SQLiteSessionStore()

        def fail_migration(conn: sqlite3.Connection) -> None:
            conn.execute("CREATE TABLE migration_probe (id INTEGER PRIMARY KEY)")
            raise RuntimeError("boom")

        monkeypatch.setattr(store, "_migrate_v1_to_v2", fail_migration)

        with pytest.raises(RuntimeError, match="boom"):
            store._db(data_dir)

        verify = sqlite3.connect(str(db_path))
        version = verify.execute(
            "SELECT value FROM meta WHERE key='schema_version'"
        ).fetchone()[0]
        tables = {
            row[0]
            for row in verify.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        }
        verify.close()

        assert version == "1"
        assert "migration_probe" not in tables


# -- Session/upload isolation (test_high_risk.py) --


def test_session_provider_mismatch():
    """Switching providers must reset provider_state; same provider preserves it."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir)
        conversation_key = telegram_conversation_key(1001)

        claude_state_factory = lambda _ck="": _state(session_id="new-id", started=False)
        codex_state_factory = lambda _ck="": _state(thread_id=None)

        # Save a Claude session with explicit approval_mode override
        session = default_session("claude", claude_state_factory(), "on")
        session["provider_state"]["started"] = True
        session["provider_state"]["session_id"] = "abc-123"
        session["approval_mode"] = "off"
        session["approval_mode_explicit"] = True
        save_session(data_dir, conversation_key, session)

        # Reload as Codex — provider_state must be reset
        loaded_codex = load_session(data_dir, conversation_key, "codex", codex_state_factory, "on")
        assert loaded_codex["provider_state"].get("started") is None
        assert loaded_codex["provider_state"].get("session_id") is None
        # Approval mode saved session should persist
        assert loaded_codex["approval_mode"] == "off"

        # Same provider reload should preserve state
        loaded_same = load_session(data_dir, conversation_key, "claude", claude_state_factory, "on")
        assert loaded_same["provider_state"]["started"] is True
        assert loaded_same["provider_state"]["session_id"] == "abc-123"
        assert loaded_same["approval_mode"] == "off"


def test_upload_isolation():
    """Per-chat upload dirs are isolated; cross-chat access is denied."""
    from app.storage import chat_upload_dir, resolve_allowed_path

    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir)

        chat_a_dir = chat_upload_dir(data_dir, 111)
        chat_b_dir = chat_upload_dir(data_dir, 222)
        file_a = chat_a_dir / "secret.txt"
        file_a.write_text("chat A secret")
        file_b = chat_b_dir / "secret.txt"
        file_b.write_text("chat B secret")

        roots_a = [Path("/home/test"), chat_a_dir]
        roots_b = [Path("/home/test"), chat_b_dir]

        assert resolve_allowed_path(str(file_a), roots_a) is not None
        assert resolve_allowed_path(str(file_b), roots_a) is None
        assert resolve_allowed_path(str(file_b), roots_b) is not None
        assert resolve_allowed_path(str(file_a), roots_b) is None

        # Neither chat can access the shared uploads root
        shared_uploads = data_dir / "uploads"
        rogue_file = shared_uploads / "rogue.txt"
        rogue_file.write_text("should be inaccessible")
        assert resolve_allowed_path(str(rogue_file), roots_a) is None


def test_upload_isolation_provider_commands():
    """Provider commands must not contain shared uploads path."""
    from app.providers.claude import ClaudeProvider
    from tests.support.config_support import make_config

    p = ClaudeProvider(make_config(provider_name="claude"))
    cmd = p._build_run_cmd({"session_id": "x", "started": False}, "test")
    assert not any("uploads" in a for a in cmd)

    # When caller passes chat-specific dir, only that dir appears
    cmd_with = p._build_run_cmd(
        {"session_id": "x", "started": False}, "test",
        extra_dirs=["/tmp/data/uploads/111"]
    )
    assert "/tmp/data/uploads/111" in cmd_with


# -- Session contract: corruption fallback --

def test_load_session_corrupt_provider_state_falls_back_to_defaults():
    """If stored provider_state is not a mapping (e.g. a list), load_session must
    fall back to defaults instead of raising TypeError."""
    import sqlite3
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        # Save a valid session first
        s = default_session("claude", _state(session_id="abc", started=False), "on")
        save_session(data_dir, telegram_conversation_key(55555), s)
        # Corrupt provider_state to a list in the raw JSON
        db_path = data_dir / "sessions.db"
        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT data FROM sessions WHERE conversation_key = ?",
            (telegram_conversation_key(55555),),
        ).fetchone()
        import json as _json
        data = _json.loads(row[0])
        data["provider_state"] = [1, 2, 3]  # not a mapping
        conn.execute(
            "UPDATE sessions SET data = ? WHERE conversation_key = ?",
            (_json.dumps(data), telegram_conversation_key(55555)),
        )
        conn.commit()
        conn.close()
        # Close cached connection so load_session re-reads the corrupted file
        from app.storage import close_db
        close_db(data_dir)
        # Must not raise — should fall back to fresh provider_state
        loaded = load_session(
            data_dir,
            telegram_conversation_key(55555),
            "claude",
            lambda _ck="": _state(session_id="new", started=False),
            "on",
        )
        assert isinstance(loaded["provider_state"], dict)
        assert loaded["provider_state"]["session_id"] == "new"
        # Prove the row was actually found and partially loaded (not a fresh/empty session)
        assert loaded["created_at"] == s["created_at"], "session row was not read — test is blind"
        reset_db_for_test(data_dir)


def test_created_at_preserved_on_resave():
    """created_at must not change on subsequent saves (write-once contract)."""
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        s = default_session("claude", _state(session_id="abc", started=False), "on")
        original_created = s["created_at"]
        save_session(data_dir, telegram_conversation_key(77777), s)
        # Load, mutate, and re-save
        loaded = load_session(
            data_dir,
            telegram_conversation_key(77777),
            "claude",
            lambda _ck="": _state(session_id="abc", started=False),
            "on",
        )
        loaded["role"] = "test-role"
        save_session(data_dir, telegram_conversation_key(77777), loaded)
        # Reload and verify created_at is unchanged
        reloaded = load_session(
            data_dir,
            telegram_conversation_key(77777),
            "claude",
            lambda _ck="": _state(session_id="abc", started=False),
            "on",
        )
        assert reloaded["created_at"] == original_created
        reset_db_for_test(data_dir)


def test_falsy_created_at_normalized_on_save():
    """If created_at is falsy (empty string), save must normalize it to a
    real timestamp so it round-trips as a non-empty value."""
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        s = default_session("claude", _state(session_id="abc", started=False), "on")
        s["created_at"] = ""  # force falsy
        save_session(data_dir, telegram_conversation_key(88888), s)
        loaded = load_session(
            data_dir,
            telegram_conversation_key(88888),
            "claude",
            lambda _ck="": _state(session_id="abc", started=False),
            "on",
        )
        assert loaded["created_at"] != "", "falsy created_at was not normalized on save"
        assert len(loaded["created_at"]) > 10, "created_at should be an ISO timestamp"
        reset_db_for_test(data_dir)


def test_load_session_non_object_json_falls_back_to_defaults():
    """If stored JSON decodes to a non-object (e.g. a list), load_session must
    fall back to defaults instead of raising AttributeError."""
    import sqlite3
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        s = default_session("claude", _state(session_id="abc", started=False), "on")
        save_session(data_dir, telegram_conversation_key(66666), s)
        # Overwrite stored data with a valid-JSON non-object
        db_path = data_dir / "sessions.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "UPDATE sessions SET data = '[]' WHERE conversation_key = ?",
            (telegram_conversation_key(66666),),
        )
        conn.commit()
        conn.close()
        from app.storage import close_db
        close_db(data_dir)
        loaded = load_session(
            data_dir,
            telegram_conversation_key(66666),
            "claude",
            lambda _ck="": _state(session_id="new", started=False),
            "on",
        )
        assert isinstance(loaded["provider_state"], dict)
        assert loaded["provider"] == "claude"
        reset_db_for_test(data_dir)
