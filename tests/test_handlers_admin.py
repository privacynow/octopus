"""Tests for /admin sessions handler."""

import app.telegram_handlers as th
from app.storage import default_session, save_session
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
    fresh_data_dir,
)


async def test_admin_requires_admin():
    """Non-admin users get rejected."""
    with fresh_data_dir() as data_dir:
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
        assert "Admin access" in last_reply(msg)


async def test_admin_sessions_summary():
    """Admin gets session summary."""
    import app.skills as skills_mod
    with fresh_data_dir() as data_dir:
        cfg = make_config(
            data_dir,
            admin_user_ids=frozenset({42}),
            admin_usernames=frozenset(),
            admin_users_explicit=True,
        )
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        # Create a resolvable custom skill
        tmp_custom = data_dir / "custom"
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
            assert "Sessions: 2" in reply
            assert "Pending approval: 1" in reply
            assert "code-review" in reply
        finally:
            skills_mod.CUSTOM_DIR = orig_custom


async def test_admin_sessions_detail():
    """Admin gets detail view for a specific chat."""
    import app.skills as skills_mod
    with fresh_data_dir() as data_dir:
        cfg = make_config(
            data_dir,
            admin_user_ids=frozenset({42}),
            admin_usernames=frozenset(),
            admin_users_explicit=True,
        )
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        # Create resolvable custom skills
        tmp_custom = data_dir / "custom"
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
            assert "Session 555" in reply
            assert "claude" in reply
            assert "Skills (2)" in reply
            assert "Approval: on" in reply
        finally:
            skills_mod.CUSTOM_DIR = orig_custom


async def test_admin_sessions_detail_not_found():
    """Detail view for non-existent chat."""
    with fresh_data_dir() as data_dir:
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
        assert "No session found" in last_reply(msg)


async def test_admin_no_sessions():
    """Empty sessions directory."""
    with fresh_data_dir() as data_dir:
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
        assert "No sessions found" in last_reply(msg)


async def test_admin_usage():
    """No subcommand shows usage."""
    with fresh_data_dir() as data_dir:
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
        assert "Usage" in last_reply(msg)


async def test_admin_not_allowed():
    """Disallowed user gets nothing."""
    with fresh_data_dir() as data_dir:
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
        assert len(msg.replies) == 0
