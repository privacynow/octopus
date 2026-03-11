"""Integration tests for SQLite session backend.

Exercises real production code paths end-to-end:
- Message handler → save_session → load_session round-trip through SQLite
- JSON-to-SQLite migration under handler load
- cmd_doctor stale session scan reading from SQLite
- _check_prompt_size_cross_chat reading from SQLite
- close_db / connection lifecycle
- delete_session
- Concurrent chat saves
"""

import json
import sqlite3
import tempfile
from pathlib import Path

from app.providers.base import RunResult
from app.storage import (
    _db,
    _reset_db,
    close_db,
    default_session,
    delete_session,
    ensure_data_dirs,
    list_sessions,
    load_session,
    save_session,
    session_exists,
)
from tests.support.handler_support import (
    FakeChat,
    FakeProvider,
    FakeUser,
    last_reply,
    load_session_disk,
    make_config,
    send_command,
    send_text,
    setup_globals,
    fresh_data_dir,
    fresh_env,
)


# ---------------------------------------------------------------------------
# 1. Full handler round-trip: message → SQLite save → SQLite load
# ---------------------------------------------------------------------------

async def test_handler_roundtrip_through_sqlite():
    """Send a message through the real handler, verify session is persisted
    in SQLite and can be loaded back with correct state."""
    with fresh_env() as (data_dir, cfg, prov):
        prov.run_results = [RunResult(text="hello back")]
        chat = FakeChat(7001)
        user = FakeUser(1)

        # No session yet
        assert session_exists(data_dir, 7001) is False

        await send_text(chat, user, "hello")

        # Session now exists in SQLite
        assert session_exists(data_dir, 7001) is True

        # Load it back — provider and updated_at should reflect the handler's save
        session = load_session_disk(data_dir, 7001, prov)
        assert session["provider"] == "claude"
        assert bool(session.get("updated_at")) is True

        # No JSON files were created
        sessions_dir = data_dir / "sessions"
        assert sessions_dir.exists() is False

        # Verify the actual SQLite DB file has the row
        conn = _db(data_dir)
        row = conn.execute(
            "SELECT provider, has_pending FROM sessions WHERE chat_id = ?", (7001,)
        ).fetchone()
        assert row is not None
        assert row[0] == "claude"
        assert row[1] == 0


# ---------------------------------------------------------------------------
# 2. JSON-to-SQLite migration under handler load
# ---------------------------------------------------------------------------

async def test_migration_then_handler_message():
    """Start with legacy JSON session files, boot the DB (triggering migration),
    then send a handler message. Verify JSON files are gone, session state
    survives in SQLite, and new handler state is merged correctly."""
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        (data_dir / "uploads").mkdir(parents=True)
        (data_dir / "credentials").mkdir(parents=True)

        # Create legacy JSON session file
        sessions_dir = data_dir / "sessions"
        sessions_dir.mkdir()
        legacy = default_session("claude", {"session_id": "legacy-abc", "started": False}, "on")
        legacy["role"] = "You are helpful."
        (sessions_dir / "8001.json").write_text(json.dumps(legacy))

        # Boot DB — triggers migration
        ensure_data_dirs(data_dir)

        try:
            # JSON dir should be gone
            assert sessions_dir.exists() is False

            # Session should be in SQLite
            assert session_exists(data_dir, 8001) is True

            # Now send a message through the handler
            prov = FakeProvider("claude")
            cfg = make_config(data_dir, working_dir=data_dir)
            setup_globals(cfg, prov)
            prov.run_results = [RunResult(text="post-migration response")]

            chat = FakeChat(8001)
            user = FakeUser(1)
            await send_text(chat, user, "after migration")

            # Verify merged state: role from migration, session_id preserved
            session = load_session_disk(data_dir, 8001, prov)
            assert session["role"] == "You are helpful."
            assert session["provider_state"]["session_id"] == "legacy-abc"

            # updated_at should be refreshed by handler save
            assert bool(session.get("updated_at")) is True

            # Still no JSON files
            assert sessions_dir.exists() is False
        finally:
            close_db(data_dir)


# ---------------------------------------------------------------------------
# 3. cmd_doctor reads stale sessions from SQLite (DB state verification)
# ---------------------------------------------------------------------------

async def test_doctor_reads_sqlite_not_json():
    """Verify cmd_doctor's stale session scan actually reads from SQLite.
    Create sessions directly in SQLite (no JSON files), run /doctor,
    and verify the scan finds them."""
    import app.telegram_handlers as th

    with fresh_env() as (data_dir, cfg, prov):
        # Create stale pending session directly via storage API
        s1 = default_session("claude", prov.new_provider_state(), "off")
        s1["pending_approval"] = {"prompt": "do something", "created_at": 0}
        save_session(data_dir, 9001, s1)

        # Create stale setup session
        s2 = default_session("claude", prov.new_provider_state(), "off")
        s2["awaiting_skill_setup"] = {"user_id": 42, "skill": "test", "started_at": 0}
        save_session(data_dir, 9002, s2)

        # Create clean session (should not trigger warnings)
        s3 = default_session("claude", prov.new_provider_state(), "off")
        save_session(data_dir, 9003, s3)

        # Verify no JSON session dir exists
        assert (data_dir / "sessions").exists() is False

        # Verify SQLite has the rows
        sessions = list_sessions(data_dir)
        assert len(sessions) == 3
        pending_count = sum(1 for s in sessions if s["has_pending"])
        setup_count = sum(1 for s in sessions if s["has_setup"])
        assert pending_count == 1
        assert setup_count == 1

        # Run /doctor
        chat = FakeChat(1)
        user = FakeUser(42)
        msg = await send_command(th.cmd_doctor, chat, user, "/doctor")
        reply = last_reply(msg)

        # Doctor found stale sessions from SQLite
        assert "pending approval" in reply
        assert "credential setup" in reply
        assert "1 session(s) with stale pending" in reply
        assert "1 session(s) with stale credential" in reply


# ---------------------------------------------------------------------------
# 4. delete_session removes session from SQLite
# ---------------------------------------------------------------------------

async def test_delete_session():
    """delete_session removes the row, session_exists returns False,
    load_session returns a fresh default."""
    with fresh_env() as (data_dir, cfg, prov):
        # Create and save a session with some state
        s = default_session("claude", prov.new_provider_state(), "on")
        s["active_skills"] = ["my-skill"]
        s["role"] = "custom role"
        save_session(data_dir, 5001, s)
        assert session_exists(data_dir, 5001) is True

        # Delete it
        delete_session(data_dir, 5001)
        assert session_exists(data_dir, 5001) is False

        # load_session returns fresh default (no skills, no role)
        fresh = load_session(data_dir, 5001, "claude", prov.new_provider_state, "on")
        assert fresh["active_skills"] == []
        assert fresh["role"] == ""

        # Verify at DB level
        conn = _db(data_dir)
        row = conn.execute("SELECT 1 FROM sessions WHERE chat_id = ?", (5001,)).fetchone()
        assert row is None


# ---------------------------------------------------------------------------
# 5. close_db / connection lifecycle
# ---------------------------------------------------------------------------

async def test_close_db_and_reopen():
    """close_db closes the connection; subsequent operations transparently
    reopen it and data is still there."""
    with fresh_data_dir() as data_dir:
        s = default_session("claude", {"session_id": "abc", "started": False}, "on")
        s["role"] = "persistent role"
        save_session(data_dir, 6001, s)

        # Close the connection
        close_db(data_dir)

        # Operations should transparently reopen
        assert session_exists(data_dir, 6001) is True

        loaded = load_session(data_dir, 6001, "claude",
                              lambda: {"session_id": "abc", "started": False}, "on")
        assert loaded["role"] == "persistent role"

        # Save new data after reopen
        loaded["role"] = "updated role"
        save_session(data_dir, 6001, loaded)
        close_db(data_dir)

        # Verify again
        loaded2 = load_session(data_dir, 6001, "claude",
                               lambda: {"session_id": "abc", "started": False}, "on")
        assert loaded2["role"] == "updated role"


# ---------------------------------------------------------------------------
# 6. Multiple chats saving through handler
# ---------------------------------------------------------------------------

async def test_multiple_chats_save_independently():
    """Send messages to multiple different chats through the real handler.
    Verify each chat's session is independently persisted."""
    with fresh_env() as (data_dir, cfg, prov):
        chats = [FakeChat(chat_id) for chat_id in (3001, 3002, 3003)]
        users = [FakeUser(uid) for uid in (1, 2, 3)]

        # Send a message to each chat
        for chat, user in zip(chats, users):
            prov.run_results = [RunResult(text=f"reply to chat {chat.id}")]
            await send_text(chat, user, f"hello from {chat.id}")

        # All three sessions exist
        sessions = list_sessions(data_dir)
        assert len(sessions) == 3

        chat_ids = {s["chat_id"] for s in sessions}
        assert chat_ids == {3001, 3002, 3003}

        # Each session has correct independent state
        for chat_id in (3001, 3002, 3003):
            s = load_session_disk(data_dir, chat_id, prov)
            assert s["provider"] == "claude"
            assert bool(s.get("updated_at")) is True


# ---------------------------------------------------------------------------
# 7. _check_prompt_size_cross_chat reads from SQLite
# ---------------------------------------------------------------------------

async def test_prompt_size_cross_chat_reads_sqlite():
    """Verify _check_prompt_size_cross_chat iterates sessions from SQLite,
    not from JSON files."""
    import app.telegram_handlers as th

    with fresh_env(config_overrides={
        "admin_user_ids": frozenset({100}),
        "admin_usernames": frozenset({"admin"}),
        "admin_users_explicit": True,
    }) as (data_dir, cfg, prov):
        # Create two sessions with a skill active, directly in SQLite
        for cid in (4001, 4002):
            s = default_session("claude", prov.new_provider_state(), "off")
            s["active_skills"] = ["big-skill"]
            save_session(data_dir, cid, s)

        # Create a session without the skill
        s3 = default_session("claude", prov.new_provider_state(), "off")
        save_session(data_dir, 4003, s3)

        # No JSON dir
        assert (data_dir / "sessions").exists() is False

        # Verify list_sessions returns all 3 with correct skills
        sessions = list_sessions(data_dir)
        with_skill = [s for s in sessions if "big-skill" in s.get("active_skills", [])]
        assert len(with_skill) == 2

        # Call the function directly (it's a module-level helper)
        warnings = th._check_prompt_size_cross_chat(data_dir, "big-skill")
        # The skill doesn't actually exist so it gets filtered out — no warnings expected.
        # The point is that it doesn't crash and successfully iterates SQLite rows.
        assert isinstance(warnings, list)


# ---------------------------------------------------------------------------
# 8. Handler message on fresh DB creates session without JSON
# ---------------------------------------------------------------------------

async def test_fresh_db_no_json_artifacts():
    """On a completely fresh data_dir, handler messages should create sessions
    only in SQLite, never creating a sessions/ directory or .json files."""
    with fresh_env() as (data_dir, cfg, prov):
        prov.run_results = [RunResult(text="first reply")]
        await send_text(FakeChat(2001), FakeUser(1), "first message")

        prov.run_results = [RunResult(text="second reply")]
        await send_text(FakeChat(2002), FakeUser(2), "second message")

        # No session JSON artifacts (raw/ dir is conversation history, not sessions)
        assert (data_dir / "sessions").exists() is False
        session_json = list(data_dir.glob("sessions/**/*.json"))
        assert session_json == []

        # SQLite has both sessions
        assert session_exists(data_dir, 2001) is True
        assert session_exists(data_dir, 2002) is True

        # DB file exists
        assert (data_dir / "sessions.db").exists() is True


# ---------------------------------------------------------------------------
# 9. _db() does not leak connections on schema/corruption errors
# ---------------------------------------------------------------------------

def _count_open_fds():
    """Portable open fd count for current process. Returns None if unsupported (e.g. Windows)."""
    import os
    pid = os.getpid()
    if os.path.isdir(f"/proc/{pid}/fd"):
        return len(os.listdir(f"/proc/{pid}/fd"))
    if os.path.isdir("/dev/fd"):
        # macOS/BSD: listing /dev/fd can add one fd; delta still detects leaks.
        return len(os.listdir("/dev/fd"))
    return None


async def test_db_no_fd_leak_on_schema_error():
    """Regression: _db() must close the SQLite connection when it raises
    due to schema version mismatch. Previously the connection was opened
    but never cached or closed on error paths, leaking a file descriptor
    per call (fds grew from 4 to 45 after 20 calls)."""
    import pytest

    from app.storage import _db, _db_connections

    if _count_open_fds() is None:
        pytest.skip("Cannot count open fds on this platform (/proc/pid/fd, /dev/fd)")

    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        db_path = data_dir / "sessions.db"

        # Create a valid DB then bump schema_version to force RuntimeError
        conn = sqlite3.connect(str(db_path))
        conn.executescript(
            "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);"
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', '99')"
        )
        conn.commit()
        conn.close()

        fd_count_before = _count_open_fds()

        # Repeatedly trigger the error — should NOT accumulate open fds
        for _ in range(20):
            try:
                _db(data_dir)
            except RuntimeError:
                pass

        fd_count_after = _count_open_fds()

        # The data_dir should never have been cached
        assert data_dir not in _db_connections
        # The actual bug: each failed call leaked an open fd.
        # Allow at most 2 fd variance for unrelated runtime activity.
        assert fd_count_after - fd_count_before <= 2, (
            f"file descriptor leak: started at {fd_count_before}, "
            f"ended at {fd_count_after} after 20 failed _db() calls"
        )
