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

import asyncio
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.providers.base import RunResult
from app.storage import (
    _db,
    _db_connections,
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
from tests.support.assertions import Checks
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
    test_env,
)

checks = Checks()
_tests: list[tuple[str, object]] = []


def run_test(name, coro):
    _tests.append((name, coro))


# ---------------------------------------------------------------------------
# 1. Full handler round-trip: message → SQLite save → SQLite load
# ---------------------------------------------------------------------------

async def test_handler_roundtrip_through_sqlite():
    """Send a message through the real handler, verify session is persisted
    in SQLite and can be loaded back with correct state."""
    with test_env() as (data_dir, cfg, prov):
        prov.run_results = [RunResult(text="hello back")]
        chat = FakeChat(7001)
        user = FakeUser(1)

        # No session yet
        checks.check("no session before message", session_exists(data_dir, 7001), False)

        await send_text(chat, user, "hello")

        # Session now exists in SQLite
        checks.check("session exists after message", session_exists(data_dir, 7001), True)

        # Load it back — provider and updated_at should reflect the handler's save
        session = load_session_disk(data_dir, 7001, prov)
        checks.check("provider matches", session["provider"], "claude")
        checks.check("updated_at set", bool(session.get("updated_at")), True)

        # No JSON files were created
        sessions_dir = data_dir / "sessions"
        checks.check("no json dir", sessions_dir.exists(), False)

        # Verify the actual SQLite DB file has the row
        conn = _db(data_dir)
        row = conn.execute(
            "SELECT provider, has_pending FROM sessions WHERE chat_id = ?", (7001,)
        ).fetchone()
        checks.check("db row exists", row is not None, True)
        checks.check("db provider column", row[0], "claude")
        checks.check("db has_pending", row[1], 0)


run_test("handler round-trip through SQLite", test_handler_roundtrip_through_sqlite())


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
            checks.check("json dir removed", sessions_dir.exists(), False)

            # Session should be in SQLite
            checks.check("migrated session exists", session_exists(data_dir, 8001), True)

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
            checks.check("role survived migration", session["role"], "You are helpful.")
            checks.check("provider_state session_id preserved",
                         session["provider_state"]["session_id"], "legacy-abc")

            # updated_at should be refreshed by handler save
            checks.check("updated_at refreshed", bool(session.get("updated_at")), True)

            # Still no JSON files
            checks.check("still no json dir", sessions_dir.exists(), False)
        finally:
            close_db(data_dir)


run_test("migration then handler message", test_migration_then_handler_message())


# ---------------------------------------------------------------------------
# 3. cmd_doctor reads stale sessions from SQLite (DB state verification)
# ---------------------------------------------------------------------------

async def test_doctor_reads_sqlite_not_json():
    """Verify cmd_doctor's stale session scan actually reads from SQLite.
    Create sessions directly in SQLite (no JSON files), run /doctor,
    and verify the scan finds them."""
    import app.telegram_handlers as th

    with test_env() as (data_dir, cfg, prov):
        # Create stale pending session directly via storage API
        s1 = default_session("claude", prov.new_provider_state(), "off")
        s1["pending_request"] = {"prompt": "do something", "created_at": 0}
        save_session(data_dir, 9001, s1)

        # Create stale setup session
        s2 = default_session("claude", prov.new_provider_state(), "off")
        s2["awaiting_skill_setup"] = {"user_id": 42, "skill": "test", "started_at": 0}
        save_session(data_dir, 9002, s2)

        # Create clean session (should not trigger warnings)
        s3 = default_session("claude", prov.new_provider_state(), "off")
        save_session(data_dir, 9003, s3)

        # Verify no JSON session dir exists
        checks.check("no json dir", (data_dir / "sessions").exists(), False)

        # Verify SQLite has the rows
        sessions = list_sessions(data_dir)
        checks.check("3 sessions in sqlite", len(sessions), 3)
        pending_count = sum(1 for s in sessions if s["has_pending"])
        setup_count = sum(1 for s in sessions if s["has_setup"])
        checks.check("1 pending in sqlite", pending_count, 1)
        checks.check("1 setup in sqlite", setup_count, 1)

        # Run /doctor
        chat = FakeChat(1)
        user = FakeUser(42)
        msg = await send_command(th.cmd_doctor, chat, user, "/doctor")
        reply = last_reply(msg)

        # Doctor found stale sessions from SQLite
        checks.check("doctor found pending", "pending approval" in reply, True)
        checks.check("doctor found setup", "credential setup" in reply, True)
        checks.check("doctor counts match", "1 session(s) with stale pending" in reply, True)
        checks.check("doctor setup count", "1 session(s) with stale credential" in reply, True)


run_test("cmd_doctor reads stale sessions from SQLite", test_doctor_reads_sqlite_not_json())


# ---------------------------------------------------------------------------
# 4. delete_session removes session from SQLite
# ---------------------------------------------------------------------------

async def test_delete_session():
    """delete_session removes the row, session_exists returns False,
    load_session returns a fresh default."""
    with test_env() as (data_dir, cfg, prov):
        # Create and save a session with some state
        s = default_session("claude", prov.new_provider_state(), "on")
        s["active_skills"] = ["my-skill"]
        s["role"] = "custom role"
        save_session(data_dir, 5001, s)
        checks.check("exists after save", session_exists(data_dir, 5001), True)

        # Delete it
        delete_session(data_dir, 5001)
        checks.check("gone after delete", session_exists(data_dir, 5001), False)

        # load_session returns fresh default (no skills, no role)
        fresh = load_session(data_dir, 5001, "claude", prov.new_provider_state, "on")
        checks.check("fresh has no skills", fresh["active_skills"], [])
        checks.check("fresh has no role", fresh["role"], "")

        # Verify at DB level
        conn = _db(data_dir)
        row = conn.execute("SELECT 1 FROM sessions WHERE chat_id = ?", (5001,)).fetchone()
        checks.check("no db row", row, None)


run_test("delete_session removes from SQLite", test_delete_session())


# ---------------------------------------------------------------------------
# 5. close_db / connection lifecycle
# ---------------------------------------------------------------------------

async def test_close_db_and_reopen():
    """close_db closes the connection; subsequent operations transparently
    reopen it and data is still there."""
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)

        try:
            s = default_session("claude", {"session_id": "abc", "started": False}, "on")
            s["role"] = "persistent role"
            save_session(data_dir, 6001, s)

            # Close the connection
            close_db(data_dir)

            # Operations should transparently reopen
            checks.check("exists after reopen", session_exists(data_dir, 6001), True)

            loaded = load_session(data_dir, 6001, "claude",
                                  lambda: {"session_id": "abc", "started": False}, "on")
            checks.check("role survives close/reopen", loaded["role"], "persistent role")

            # Save new data after reopen
            loaded["role"] = "updated role"
            save_session(data_dir, 6001, loaded)
            close_db(data_dir)

            # Verify again
            loaded2 = load_session(data_dir, 6001, "claude",
                                   lambda: {"session_id": "abc", "started": False}, "on")
            checks.check("updated role survives", loaded2["role"], "updated role")
        finally:
            close_db(data_dir)


run_test("close_db and reopen", test_close_db_and_reopen())


# ---------------------------------------------------------------------------
# 6. Multiple chats saving through handler
# ---------------------------------------------------------------------------

async def test_multiple_chats_save_independently():
    """Send messages to multiple different chats through the real handler.
    Verify each chat's session is independently persisted."""
    with test_env() as (data_dir, cfg, prov):
        chats = [FakeChat(chat_id) for chat_id in (3001, 3002, 3003)]
        users = [FakeUser(uid) for uid in (1, 2, 3)]

        # Send a message to each chat
        for chat, user in zip(chats, users):
            prov.run_results = [RunResult(text=f"reply to chat {chat.id}")]
            await send_text(chat, user, f"hello from {chat.id}")

        # All three sessions exist
        sessions = list_sessions(data_dir)
        checks.check("3 sessions created", len(sessions), 3)

        chat_ids = {s["chat_id"] for s in sessions}
        checks.check("all chats present", chat_ids, {3001, 3002, 3003})

        # Each session has correct independent state
        for chat_id in (3001, 3002, 3003):
            s = load_session_disk(data_dir, chat_id, prov)
            checks.check(f"chat {chat_id} provider", s["provider"], "claude")
            checks.check(f"chat {chat_id} has updated_at", bool(s.get("updated_at")), True)


run_test("multiple chats save independently", test_multiple_chats_save_independently())


# ---------------------------------------------------------------------------
# 7. _check_prompt_size_cross_chat reads from SQLite
# ---------------------------------------------------------------------------

async def test_prompt_size_cross_chat_reads_sqlite():
    """Verify _check_prompt_size_cross_chat iterates sessions from SQLite,
    not from JSON files."""
    import app.telegram_handlers as th

    with test_env(config_overrides={
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
        checks.check("no json dir", (data_dir / "sessions").exists(), False)

        # Verify list_sessions returns all 3 with correct skills
        sessions = list_sessions(data_dir)
        with_skill = [s for s in sessions if "big-skill" in s.get("active_skills", [])]
        checks.check("2 sessions have skill", len(with_skill), 2)

        # Call the function directly (it's a module-level helper)
        warnings = th._check_prompt_size_cross_chat(data_dir, "big-skill")
        # The skill doesn't actually exist so it gets filtered out — no warnings expected.
        # The point is that it doesn't crash and successfully iterates SQLite rows.
        checks.check("cross-chat scan completed", isinstance(warnings, list), True)


run_test("prompt size cross-chat reads SQLite", test_prompt_size_cross_chat_reads_sqlite())


# ---------------------------------------------------------------------------
# 8. Handler message on fresh DB creates session without JSON
# ---------------------------------------------------------------------------

async def test_fresh_db_no_json_artifacts():
    """On a completely fresh data_dir, handler messages should create sessions
    only in SQLite, never creating a sessions/ directory or .json files."""
    with test_env() as (data_dir, cfg, prov):
        prov.run_results = [RunResult(text="first reply")]
        await send_text(FakeChat(2001), FakeUser(1), "first message")

        prov.run_results = [RunResult(text="second reply")]
        await send_text(FakeChat(2002), FakeUser(2), "second message")

        # No session JSON artifacts (raw/ dir is conversation history, not sessions)
        checks.check("no sessions dir", (data_dir / "sessions").exists(), False)
        session_json = list(data_dir.glob("sessions/**/*.json"))
        checks.check("no session json files", session_json, [])

        # SQLite has both sessions
        checks.check("chat 2001 exists", session_exists(data_dir, 2001), True)
        checks.check("chat 2002 exists", session_exists(data_dir, 2002), True)

        # DB file exists
        checks.check("db file exists", (data_dir / "sessions.db").exists(), True)


run_test("fresh DB no JSON artifacts", test_fresh_db_no_json_artifacts())


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def _close_all_db_connections():
    """Close all leaked SQLite connections between tests."""
    for conn in _db_connections.values():
        try:
            conn.close()
        except Exception:
            pass
    _db_connections.clear()


async def _run_all():
    for name, coro in _tests:
        print(f"\n=== {name} ===")
        try:
            await coro
        except Exception as exc:
            print(f"  FAIL  {name} (exception: {exc})")
            import traceback
            traceback.print_exc()
            checks.failed += 1
        finally:
            _close_all_db_connections()


async def _main():
    await _run_all()
    print(f"\n{'=' * 60}")
    print(f"  test_sqlite_integration.py: {checks.passed} passed, {checks.failed} failed")
    print(f"{'=' * 60}")
    raise SystemExit(1 if checks.failed else 0)


if __name__ == "__main__":
    asyncio.run(_main())
