"""Tests for /admin sessions handler."""

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import app.telegram_handlers as th
from app.storage import default_session, ensure_data_dirs, save_session
from tests.support.assertions import Checks
from tests.support.handler_support import (
    FakeChat,
    FakeContext,
    FakeMessage,
    FakeProvider,
    FakeUpdate,
    FakeUser,
    last_reply,
    make_config,
    make_skill,
    send_command,
    setup_globals,
)

checks = Checks()
_tests: list[tuple[str, object]] = []


def run_test(name, coro):
    _tests.append((name, coro))


async def test_admin_requires_admin():
    """Non-admin users get rejected."""
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(
            data_dir,
            admin_user_ids=frozenset({99}),
            admin_usernames=frozenset(),
            admin_users_explicit=True,
        )
        setup_globals(cfg, FakeProvider())

        chat = FakeChat()
        user = FakeUser(42, "regular")
        msg = await send_command(th.cmd_admin, chat, user, "/admin sessions", args=["sessions"])
        checks.check("non-admin rejected", "Admin access" in last_reply(msg), True)


run_test("non-admin rejected", test_admin_requires_admin())


async def test_admin_sessions_summary():
    """Admin gets session summary."""
    import app.skills as skills_mod
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(
            data_dir,
            admin_user_ids=frozenset({42}),
            admin_usernames=frozenset(),
            admin_users_explicit=True,
        )
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        # Create a resolvable custom skill
        tmp_custom = Path(tmp) / "custom"
        tmp_custom.mkdir()
        orig_custom = skills_mod.CUSTOM_DIR
        skills_mod.CUSTOM_DIR = tmp_custom
        try:
            make_skill(tmp_custom, "code-review", body="Review code.")

            # Create sessions
            s1 = default_session("claude", {"session_id": "a", "started": False}, "on")
            s1["active_skills"] = ["code-review"]
            save_session(data_dir, 111, s1)

            s2 = default_session("claude", {"session_id": "b", "started": False}, "off")
            s2["pending_request"] = {"prompt": "test", "created_at": 0}
            save_session(data_dir, 222, s2)

            chat = FakeChat()
            user = FakeUser(42, "admin")
            msg = await send_command(th.cmd_admin, chat, user, "/admin sessions", args=["sessions"])
            reply = last_reply(msg)
            checks.check("shows total", "Sessions: 2" in reply, True)
            checks.check("shows pending", "Pending approval: 1" in reply, True)
            checks.check("shows skills", "code-review" in reply, True)
        finally:
            skills_mod.CUSTOM_DIR = orig_custom


run_test("sessions summary", test_admin_sessions_summary())


async def test_admin_sessions_detail():
    """Admin gets detail view for a specific chat."""
    import app.skills as skills_mod
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(
            data_dir,
            admin_user_ids=frozenset({42}),
            admin_usernames=frozenset(),
            admin_users_explicit=True,
        )
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        # Create resolvable custom skills
        tmp_custom = Path(tmp) / "custom"
        tmp_custom.mkdir()
        orig_custom = skills_mod.CUSTOM_DIR
        skills_mod.CUSTOM_DIR = tmp_custom
        try:
            make_skill(tmp_custom, "code-review", body="Review code.")
            make_skill(tmp_custom, "deploy", body="Deploy code.")

            s = default_session("claude", {"session_id": "a", "started": False}, "on")
            s["active_skills"] = ["code-review", "deploy"]
            save_session(data_dir, 555, s)

            chat = FakeChat()
            user = FakeUser(42, "admin")
            msg = await send_command(
                th.cmd_admin, chat, user, "/admin sessions 555", args=["sessions", "555"])
            reply = last_reply(msg)
            checks.check("shows chat id", "Session 555" in reply, True)
            checks.check("shows provider", "claude" in reply, True)
            checks.check("shows skills count", "Skills (2)" in reply, True)
            checks.check("shows approval mode", "Approval: on" in reply, True)
        finally:
            skills_mod.CUSTOM_DIR = orig_custom


run_test("sessions detail", test_admin_sessions_detail())


async def test_admin_sessions_detail_not_found():
    """Detail view for non-existent chat."""
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(
            data_dir,
            admin_user_ids=frozenset({42}),
            admin_usernames=frozenset(),
            admin_users_explicit=True,
        )
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        # Need at least one session so we pass the "no sessions" check
        s = default_session("claude", {"session_id": "a", "started": False}, "on")
        save_session(data_dir, 111, s)

        chat = FakeChat()
        user = FakeUser(42, "admin")
        msg = await send_command(
            th.cmd_admin, chat, user, "/admin sessions 999", args=["sessions", "999"])
        checks.check("not found", "No session found" in last_reply(msg), True)


run_test("detail not found", test_admin_sessions_detail_not_found())


async def test_admin_no_sessions():
    """Empty sessions directory."""
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(
            data_dir,
            admin_user_ids=frozenset({42}),
            admin_usernames=frozenset(),
            admin_users_explicit=True,
        )
        setup_globals(cfg, FakeProvider())

        chat = FakeChat()
        user = FakeUser(42, "admin")
        msg = await send_command(th.cmd_admin, chat, user, "/admin sessions", args=["sessions"])
        checks.check("no sessions", "No sessions found" in last_reply(msg), True)


run_test("no sessions", test_admin_no_sessions())


async def test_admin_usage():
    """No subcommand shows usage."""
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(
            data_dir,
            admin_user_ids=frozenset({42}),
            admin_usernames=frozenset(),
            admin_users_explicit=True,
        )
        setup_globals(cfg, FakeProvider())

        chat = FakeChat()
        user = FakeUser(42, "admin")
        msg = await send_command(th.cmd_admin, chat, user, "/admin", args=[])
        checks.check("usage shown", "Usage" in last_reply(msg), True)


run_test("usage", test_admin_usage())


async def test_admin_not_allowed():
    """Disallowed user gets nothing."""
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(
            data_dir,
            allow_open=False,
            allowed_user_ids=frozenset({99}),
            admin_user_ids=frozenset({99}),
            admin_users_explicit=True,
        )
        setup_globals(cfg, FakeProvider())

        chat = FakeChat()
        user = FakeUser(42, "stranger")
        msg = await send_command(th.cmd_admin, chat, user, "/admin sessions", args=["sessions"])
        checks.check("no reply for disallowed", len(msg.replies), 0)


run_test("disallowed user", test_admin_not_allowed())


# Run all tests
for name, coro in _tests:
    print(f"\n--- {name} ---")
    asyncio.get_event_loop().run_until_complete(coro)

print(f"\n{'='*40}")
print(f"  {checks.passed} passed, {checks.failed} failed")
print(f"{'='*40}")
sys.exit(1 if checks.failed else 0)
