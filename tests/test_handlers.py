"""Core handler integration tests: happy-path routing, session lifecycle, /help, /start, /doctor, /project."""

import re
import tempfile
from pathlib import Path

from app.providers.base import RunContext, RunResult
from app.storage import default_session, save_session
from tests.support.handler_support import (
    FakeCallbackQuery,
    FakeChat,
    FakeContext,
    FakeMessage,
    FakeProvider,
    FakeUpdate,
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


async def test_happy_path():
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        prov.run_results = [RunResult(text="Hello world", provider_state_updates={"started": True})]
        setup_globals(cfg, prov)

        chat = FakeChat(12345)
        user = FakeUser(42)
        msg = FakeMessage(chat=chat, text="hi there")

        import app.telegram_handlers as th

        await th.handle_message(FakeUpdate(message=msg, user=user, chat=chat), FakeContext())

        assert len(prov.run_calls) == 1
        assert "hi there" in prov.run_calls[0]["prompt"]

        ctx = prov.run_calls[0]["context"]
        assert isinstance(ctx, RunContext)
        assert any("uploads" in d for d in ctx.extra_dirs)
        assert ctx.skip_permissions is False

        session = load_session_disk(data_dir, 12345, prov)
        assert session["provider_state"]["started"] == True
        assert len(msg.replies) >= 2
        assert "Hello world" in " ".join(r.get("text", r.get("edit_text", "")) for r in msg.replies)


async def test_cmd_new():
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        session = default_session("claude", {"session_id": "old-sess", "started": True}, "on")
        session["active_skills"] = ["github-integration"]
        save_session(data_dir, 12345, session)

        scripts_dir = data_dir / "scripts" / "12345" / "some-skill"
        scripts_dir.mkdir(parents=True)
        (scripts_dir / "helper.sh").write_text("#!/bin/bash\necho hi")

        chat = FakeChat(12345)
        user = FakeUser(42)
        msg = FakeMessage(chat=chat, text="/new")

        import app.telegram_handlers as th

        await th.cmd_new(FakeUpdate(message=msg, user=user, chat=chat), FakeContext())

        new_session = load_session_disk(data_dir, 12345, prov)
        assert not new_session["provider_state"].get("started")
        assert new_session["approval_mode"] == "off"
        assert not (data_dir / "scripts" / "12345").exists()
        assert "Fresh" in " ".join(r.get("text", "") for r in msg.replies)


async def test_provider_timeout():
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        prov.run_results = [RunResult(text="partial output", timed_out=True)]
        setup_globals(cfg, prov)

        chat = FakeChat(12345)
        user = FakeUser(42)
        msg = FakeMessage(chat=chat, text="long running task")

        import app.telegram_handlers as th

        await th.handle_message(FakeUpdate(message=msg, user=user, chat=chat), FakeContext())

        assert len(prov.run_calls) == 1
        reply_texts = " ".join(r.get("text", "") for r in msg.replies)
        assert "partial output" not in reply_texts
        assert sum(1 for r in msg.replies if "text" in r) == 1
        session = load_session_disk(data_dir, 12345, prov)
        assert session.get("pending_approval") is None and session.get("pending_retry") is None


async def test_provider_error_returncode():
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        prov.run_results = [RunResult(text="Error: segfault in subprocess", returncode=1)]
        setup_globals(cfg, prov)

        chat = FakeChat(12345)
        user = FakeUser(42)
        msg = FakeMessage(chat=chat, text="crash me")

        import app.telegram_handlers as th

        await th.handle_message(FakeUpdate(message=msg, user=user, chat=chat), FakeContext())

        assert len(prov.run_calls) == 1
        reply_texts = " ".join(r.get("text", "") for r in msg.replies)
        assert "segfault" not in reply_texts
        assert sum(1 for r in msg.replies if "text" in r) == 1
        session = load_session_disk(data_dir, 12345, prov)
        assert session.get("pending_approval") is None and session.get("pending_retry") is None


async def test_cmd_role():
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir, role="default engineer")
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        import app.telegram_handlers as th

        chat = FakeChat(12345)
        user = FakeUser(42)

        msg1 = FakeMessage(chat=chat, text="/role")
        await th.cmd_role(FakeUpdate(message=msg1, user=user, chat=chat), FakeContext(args=[]))
        assert "default engineer" in " ".join(r.get("text", "") for r in msg1.replies)

        msg2 = FakeMessage(chat=chat, text="/role security auditor")
        await th.cmd_role(FakeUpdate(message=msg2, user=user, chat=chat), FakeContext(args=["security", "auditor"]))
        session = load_session_disk(data_dir, 12345, prov)
        assert session.get("role") == "security auditor"

        msg3 = FakeMessage(chat=chat, text="/role clear")
        await th.cmd_role(FakeUpdate(message=msg3, user=user, chat=chat), FakeContext(args=["clear"]))
        session = load_session_disk(data_dir, 12345, prov)
        assert session.get("role") == "default engineer"
        assert "default" in " ".join(r.get("text", "") for r in msg3.replies).lower()


async def test_role_in_provider_context():
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir, role="Kubernetes expert")
        prov = FakeProvider("claude")
        prov.run_results = [RunResult(text="ok")]
        setup_globals(cfg, prov)

        import app.telegram_handlers as th

        chat = FakeChat(12345)
        user = FakeUser(42)
        await th.handle_message(
            FakeUpdate(message=FakeMessage(chat=chat, text="deploy my app"), user=user, chat=chat),
            FakeContext(),
        )

        assert len(prov.run_calls) == 1
        assert "Kubernetes expert" in prov.run_calls[0]["context"].system_prompt


async def test_new_preserves_default_skills():
    from app.skills import save_user_credential, derive_encryption_key

    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir, default_skills=("github-integration",))
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        key = derive_encryption_key(cfg.telegram_token)
        save_user_credential(data_dir, 42, "github-integration", "GITHUB_TOKEN", "ghp_test", key)

        session = default_session("claude", prov.new_provider_state(), "off")
        session["active_skills"] = ["github-integration", "extra-skill"]
        save_session(data_dir, 12345, session)

        import app.telegram_handlers as th

        chat = FakeChat(12345)
        user = FakeUser(42)
        await th.cmd_new(FakeUpdate(message=FakeMessage(chat=chat, text="/new"), user=user, chat=chat), FakeContext())
        session = load_session_disk(data_dir, 12345, prov)
        assert "github-integration" in session.get("active_skills", [])
        assert "extra-skill" not in session.get("active_skills", [])


async def test_help_topics():
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        import app.telegram_handlers as th

        chat = FakeChat(12345)
        user = FakeUser(42)

        msg1 = FakeMessage(chat=chat, text="/help skills")
        await th.cmd_help(FakeUpdate(message=msg1, user=user, chat=chat), FakeContext(args=["skills"]))
        assert "/skills add" in msg1.replies[0]["text"]

        msg2 = FakeMessage(chat=chat, text="/help approval")
        await th.cmd_help(FakeUpdate(message=msg2, user=user, chat=chat), FakeContext(args=["approval"]))
        assert "Approval Mode" in msg2.replies[0]["text"]

        msg3 = FakeMessage(chat=chat, text="/help credentials")
        await th.cmd_help(FakeUpdate(message=msg3, user=user, chat=chat), FakeContext(args=["credentials"]))
        assert "/clear_credentials" in msg3.replies[0]["text"]

        msg4 = FakeMessage(chat=chat, text="/help")
        await th.cmd_help(FakeUpdate(message=msg4, user=user, chat=chat), FakeContext(args=[]))
        assert "/skills" in msg4.replies[0]["text"]
        assert "CLI Bridge" not in msg4.replies[0]["text"]
        assert "/settings" in msg4.replies[0]["text"]


async def test_help_and_start_include_settings():
    """/help and /start must expose /settings, /project, /session for discoverability (Bucket B)."""
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)
        import app.telegram_handlers as th
        chat = FakeChat(12345)
        user = FakeUser(42)
        help_msg = FakeMessage(chat=chat, text="/help")
        await th.cmd_help(FakeUpdate(message=help_msg, user=user, chat=chat), FakeContext(args=[]))
        help_text = help_msg.replies[0]["text"]
        assert "/settings" in help_text
        assert "/project" in help_text
        assert "/session" in help_text
        assert "/retry" not in help_text
        assert not re.search(r"(?:^|\n)/clear\s", help_text), "must not advertise /clear (use /new); /clear_credentials is fine"
        start_msg = FakeMessage(chat=chat, text="/start")
        await th.cmd_start(FakeUpdate(message=start_msg, user=user, chat=chat), FakeContext(args=[]))
        start_text = start_msg.replies[0]["text"]
        assert "/settings" in start_text
        assert "/project" in start_text
        assert "/session" in start_text
        assert "/retry" not in start_text
        assert not re.search(r"(?:^|\n)/clear\s", start_text), "must not advertise /clear (use /new)"


async def test_help_and_start_public_user_excludes_project_and_policy():
    """Bucket B follow-up: public users must not see /project or /policy in /start or /help."""
    with fresh_data_dir() as data_dir:
        cfg = make_config(
            data_dir,
            allow_open=True,
            allowed_user_ids=frozenset({1, 2, 3}),
        )
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)
        import app.telegram_handlers as th
        chat = FakeChat(12345)
        user = FakeUser(999)
        help_msg = FakeMessage(chat=chat, text="/help")
        await th.cmd_help(FakeUpdate(message=help_msg, user=user, chat=chat), FakeContext(args=[]))
        help_text = help_msg.replies[0]["text"]
        assert "/project" not in help_text
        assert "/policy" not in help_text
        assert "/settings" in help_text
        assert "/session" in help_text
        start_msg = FakeMessage(chat=chat, text="/start")
        await th.cmd_start(FakeUpdate(message=start_msg, user=user, chat=chat), FakeContext(args=[]))
        start_text = start_msg.replies[0]["text"]
        assert "/project" not in start_text
        assert "/policy" not in start_text
        assert "/settings" in start_text
        assert "/session" in start_text


async def test_help_and_start_non_admin_excludes_admin_sessions():
    """Bucket B follow-up: non-admin trusted users must not see /admin sessions in /start or /help."""
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir, admin_user_ids=frozenset(), admin_usernames=frozenset())
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)
        import app.telegram_handlers as th
        chat = FakeChat(12345)
        user = FakeUser(42)
        help_msg = FakeMessage(chat=chat, text="/help")
        await th.cmd_help(FakeUpdate(message=help_msg, user=user, chat=chat), FakeContext(args=[]))
        help_text = help_msg.replies[0]["text"]
        assert "/admin sessions" not in help_text
        start_msg = FakeMessage(chat=chat, text="/start")
        await th.cmd_start(FakeUpdate(message=start_msg, user=user, chat=chat), FakeContext(args=[]))
        start_text = start_msg.replies[0]["text"]
        assert "/admin sessions" not in start_text


async def test_help_and_start_admin_sees_admin_sessions_and_trusted_commands():
    """Bucket B follow-up: admin users see /admin sessions and full trusted command set."""
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir, admin_user_ids=frozenset({42}), admin_usernames=frozenset())
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)
        import app.telegram_handlers as th
        chat = FakeChat(12345)
        user = FakeUser(42)
        help_msg = FakeMessage(chat=chat, text="/help")
        await th.cmd_help(FakeUpdate(message=help_msg, user=user, chat=chat), FakeContext(args=[]))
        help_text = help_msg.replies[0]["text"]
        assert "/admin sessions" in help_text
        assert "/project" in help_text
        assert "/settings" in help_text
        assert "/session" in help_text
        start_msg = FakeMessage(chat=chat, text="/start")
        await th.cmd_start(FakeUpdate(message=start_msg, user=user, chat=chat), FakeContext(args=[]))
        start_text = start_msg.replies[0]["text"]
        assert "/admin sessions" in start_text
        assert "/project" in start_text


def test_bucket_b_command_registration_parity():
    """Bucket B: key user-facing commands (start, help, settings, project, session) must be registered."""
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        import app.telegram_handlers as th
        from telegram.ext import CommandHandler

        app = th.build_application(cfg, prov)
        registered = set()
        for group_handlers in app.handlers.values():
            for h in group_handlers:
                if isinstance(h, CommandHandler):
                    commands = getattr(h, "commands", None) or (
                        (getattr(h, "command", None),) if getattr(h, "command", None) else ()
                    )
                    registered.update(commands)
        required = {"start", "help", "settings", "project", "session"}
        missing = required - registered
        assert not missing, f"Bucket B main commands must be registered; missing: {missing}"


async def test_first_run_welcome():
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir, approval_mode="on")
        prov = FakeProvider("claude")
        prov.preflight_results = [RunResult(text="plan: read files")]
        setup_globals(cfg, prov)

        import app.telegram_handlers as th

        chat = FakeChat(12345)
        user = FakeUser(42)
        msg = FakeMessage(chat=chat, text="hello")
        await th.handle_message(FakeUpdate(message=msg, user=user, chat=chat), FakeContext())
        sent = " ".join(m.get("text", "") for m in chat.sent_messages)
        assert "ready" in sent.lower()
        assert "Approval mode is on" in sent


async def test_first_run_welcome_compact_mode():
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir, compact_mode=True)
        prov = FakeProvider("claude")
        prov.run_results = [RunResult(text="hi")]
        setup_globals(cfg, prov)

        import app.telegram_handlers as th

        chat = FakeChat(12345)
        user = FakeUser(42)
        msg = FakeMessage(chat=chat, text="hello")
        await th.handle_message(FakeUpdate(message=msg, user=user, chat=chat), FakeContext())
        sent = " ".join(m.get("text", "") for m in chat.sent_messages)
        assert "Compact mode is on" in sent
        assert "/compact off" in sent


async def test_first_run_welcome_no_compact():
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir, compact_mode=False)
        prov = FakeProvider("claude")
        prov.run_results = [RunResult(text="hi")]
        setup_globals(cfg, prov)

        import app.telegram_handlers as th

        chat = FakeChat(12345)
        user = FakeUser(42)
        msg = FakeMessage(chat=chat, text="hello")
        await th.handle_message(FakeUpdate(message=msg, user=user, chat=chat), FakeContext())
        sent = " ".join(m.get("text", "") for m in chat.sent_messages)
        assert "Compact mode" not in sent


async def test_start_deep_link():
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        import app.telegram_handlers as th

        chat = FakeChat(12345)
        user = FakeUser(42)
        msg = FakeMessage(chat=chat, text="/start foo")
        await th.cmd_start(FakeUpdate(message=msg, user=user, chat=chat), FakeContext(args=["foo"]))
        assert "Unknown help topic" not in msg.replies[0]["text"]
        assert "Agent Bot" in msg.replies[0]["text"]


async def test_doctor_admin_warning():
    with fresh_data_dir() as data_dir:
        cfg = make_config(
            data_dir,
            allowed_user_ids=frozenset({1, 2, 3}),
            admin_user_ids=frozenset({1, 2, 3}),
        )
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        session = default_session("claude", prov.new_provider_state(), "off")
        save_session(data_dir, 1, session)

        import app.telegram_handlers as th

        chat = FakeChat(1)
        user = FakeUser(1)
        msg = await send_command(th.cmd_doctor, chat, user, "/doctor")
        reply = last_reply(msg)
        assert "BOT_ADMIN_USERS" in reply


async def test_doctor_no_warning_explicit_admin():
    with fresh_data_dir() as data_dir:
        cfg = make_config(
            data_dir,
            allowed_user_ids=frozenset({1, 2, 3}),
            admin_user_ids=frozenset({1}),
            admin_users_explicit=True,
        )
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        session = default_session("claude", prov.new_provider_state(), "off")
        save_session(data_dir, 1, session)

        import app.telegram_handlers as th

        chat = FakeChat(1)
        user = FakeUser(1)
        msg = await send_command(th.cmd_doctor, chat, user, "/doctor")
        reply = last_reply(msg)
        assert "BOT_ADMIN_USERS" not in reply


async def test_prompt_size_warning_before_activation():
    import app.skills as skills_mod

    with fresh_data_dir() as data_dir:
        orig_custom_dir = skills_mod.CUSTOM_DIR
        try:
            custom_dir = data_dir / "custom-skills"
            skills_mod.CUSTOM_DIR = custom_dir

            d = custom_dir / "big-skill"
            d.mkdir(parents=True)
            (d / "skill.md").write_text(
                "---\nname: big-skill\ndisplay_name: Big\n"
                "description: test\n---\n\n" + "x" * 9000 + "\n"
            )

            cfg = make_config(data_dir)
            prov = FakeProvider("claude")
            prov.run_results = [RunResult(text="ok")]
            setup_globals(cfg, prov)

            session = default_session("claude", prov.new_provider_state(), "off")
            save_session(data_dir, 1, session)

            import app.telegram_handlers as th
            chat = FakeChat(1)
            user = FakeUser(42)
            msg = await send_command(
                th.cmd_skills, chat, user, "/skills add big-skill",
                args=["add", "big-skill"])

            reply = last_reply(msg)
            assert "prompt context" in reply
            assert "8,000" in reply
            assert "Continue" in reply

            session = load_session_disk(data_dir, 1, prov)
            assert "big-skill" not in session.get("active_skills", [])
        finally:
            skills_mod.CUSTOM_DIR = orig_custom_dir


async def test_prompt_size_no_warning_small_skill():
    import app.skills as skills_mod

    with fresh_data_dir() as data_dir:
        orig_custom_dir = skills_mod.CUSTOM_DIR
        try:
            custom_dir = data_dir / "custom-skills"
            skills_mod.CUSTOM_DIR = custom_dir

            d = custom_dir / "tiny-skill"
            d.mkdir(parents=True)
            (d / "skill.md").write_text(
                "---\nname: tiny-skill\ndisplay_name: Tiny\n"
                "description: test\n---\n\nSmall instructions.\n"
            )

            cfg = make_config(data_dir)
            prov = FakeProvider("claude")
            prov.run_results = [RunResult(text="ok")]
            setup_globals(cfg, prov)

            session = default_session("claude", prov.new_provider_state(), "off")
            save_session(data_dir, 1, session)

            import app.telegram_handlers as th
            chat = FakeChat(1)
            user = FakeUser(42)
            msg = await send_command(
                th.cmd_skills, chat, user, "/skills add tiny-skill",
                args=["add", "tiny-skill"])

            reply = last_reply(msg)
            assert "activated" in reply
            assert "prompt context" not in reply

            session = load_session_disk(data_dir, 1, prov)
            assert "tiny-skill" in session.get("active_skills", [])
        finally:
            skills_mod.CUSTOM_DIR = orig_custom_dir


async def test_doctor_stale_session_warnings():
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir, working_dir=data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        session1 = default_session("claude", prov.new_provider_state(), "off")
        session1["pending_approval"] = {"prompt": "do something", "created_at": 0}
        save_session(data_dir, 100, session1)

        session2 = default_session("claude", prov.new_provider_state(), "off")
        session2["awaiting_skill_setup"] = {"user_id": 42, "skill": "test", "started_at": 0}
        save_session(data_dir, 200, session2)

        session3 = default_session("claude", prov.new_provider_state(), "off")
        save_session(data_dir, 300, session3)

        import app.telegram_handlers as th
        chat = FakeChat(1)
        user = FakeUser(42)
        msg = await send_command(th.cmd_doctor, chat, user, "/doctor")
        reply = last_reply(msg)
        assert "pending approval" in reply
        assert "credential setup" in reply


async def test_doctor_no_warning_explicit_admin_equal_to_allowed():
    """If BOT_ADMIN_USERS is explicitly set to same as BOT_ALLOWED_USERS,
    /doctor should NOT warn (operator made a deliberate choice)."""
    with fresh_data_dir() as data_dir:
        cfg = make_config(
            data_dir,
            allowed_user_ids=frozenset({1, 2, 3}),
            admin_user_ids=frozenset({1, 2, 3}),
            admin_users_explicit=True,
        )
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        session = default_session("claude", prov.new_provider_state(), "off")
        save_session(data_dir, 1, session)

        import app.telegram_handlers as th
        chat = FakeChat(1)
        user = FakeUser(1)
        msg = await send_command(th.cmd_doctor, chat, user, "/doctor")
        reply = last_reply(msg)
        assert "BOT_ADMIN_USERS" not in reply


async def test_doctor_no_stale_warning_for_fresh_sessions():
    import time as _time
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        session1 = default_session("claude", prov.new_provider_state(), "off")
        session1["pending_approval"] = {"prompt": "do something", "created_at": _time.time()}
        save_session(data_dir, 100, session1)

        session2 = default_session("claude", prov.new_provider_state(), "off")
        session2["awaiting_skill_setup"] = {"user_id": 42, "skill": "test", "started_at": _time.time()}
        save_session(data_dir, 200, session2)

        import app.telegram_handlers as th
        chat = FakeChat(1)
        user = FakeUser(42)
        msg = await send_command(th.cmd_doctor, chat, user, "/doctor")
        reply = last_reply(msg)
        assert "stale pending" not in reply
        assert "stale credential" not in reply


async def test_doctor_missing_data_dir():
    """collect_doctor_report should not crash when data_dir doesn't exist yet.

    Reproduces: operator runs --doctor before first bot startup, data_dir
    doesn't exist.  Previously crashed in scan_stale_sessions -> SQLite open.
    """
    import tempfile
    from app.doctor import collect_doctor_report

    with tempfile.TemporaryDirectory() as tmp:
        missing_dir = Path(tmp) / "not-yet-created"
        # Verify it really doesn't exist -- no stale leftovers possible
        assert not missing_dir.exists()

        cfg = make_config(missing_dir)
        prov = FakeProvider("claude")

        report = await collect_doctor_report(cfg, prov)
        assert report is not None
        assert isinstance(report.errors, list)
        assert isinstance(report.warnings, list)
        # Stale session scan should have been skipped entirely
        stale_msgs = [w for w in report.warnings if "stale" in w.lower()]
        assert len(stale_msgs) == 0


async def test_doctor_corrupt_session_db():
    """collect_doctor_report should report corrupt DB, not crash.

    Reproduces: operator's sessions.db gets corrupted (disk error, partial
    write, manual edit).  Previously raised DatabaseError: file is not a
    database, crashing the health command instead of reporting the problem.
    """
    import tempfile
    from app.doctor import collect_doctor_report
    from app.storage import close_db

    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        # Create a corrupt sessions.db -- junk bytes, not a valid SQLite file
        db_path = data_dir / "sessions.db"
        db_path.write_bytes(b"this is not a valid sqlite database file at all")

        cfg = make_config(data_dir)
        prov = FakeProvider("claude")

        try:
            report = await collect_doctor_report(cfg, prov)
            assert report is not None
            # Should have caught the corruption and reported it as an error
            corruption_errors = [e for e in report.errors if "corrupt" in e.lower() or "database" in e.lower()]
            assert len(corruption_errors) >= 1
            # Should NOT have stale session warnings (scan couldn't run)
            stale_msgs = [w for w in report.warnings if "stale" in w.lower()]
            assert len(stale_msgs) == 0
        finally:
            close_db(data_dir)


async def test_cmd_doctor_corrupt_db_telegram():
    """/doctor via Telegram should reply with an error, not crash, on corrupt DB.

    This exercises the real user-facing path: user sends /doctor in chat,
    cmd_doctor calls _load() which hits SQLite, DB is corrupt.  Previously
    the handler raised DatabaseError unhandled and the user saw nothing.
    """
    import tempfile
    from app.storage import close_db

    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        # Bootstrap a real DB first so the config/dirs are valid
        from app.storage import ensure_data_dirs
        ensure_data_dirs(data_dir)
        close_db(data_dir)

        # Now corrupt the DB file
        db_path = data_dir / "sessions.db"
        db_path.write_bytes(b"this is not a valid sqlite database file at all")

        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        import app.telegram_handlers as th
        chat = FakeChat(1)
        user = FakeUser(42)

        try:
            msg = await send_command(th.cmd_doctor, chat, user, "/doctor")
            reply = last_reply(msg)
            # Handler should reply (not crash silently)
            assert len(reply) > 0
            # Reply should mention the DB problem
            assert "corrupt" in reply.lower() or "database" in reply.lower()
        finally:
            close_db(data_dir)


async def test_doctor_schema_mismatch_cli():
    """collect_doctor_report should report a newer session DB schema, not crash.

    Reproduces: operator downgrades the bot, sessions.db has schema_version=99.
    storage._db() raises RuntimeError which was not caught by the stale session
    scan handler (only sqlite3 exceptions were caught).
    """
    import tempfile
    from app.doctor import collect_doctor_report
    from app.storage import close_db, ensure_data_dirs, _db

    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        # Bump schema version beyond what the code supports
        conn = _db(data_dir)
        conn.execute("UPDATE meta SET value='99' WHERE key='schema_version'")
        conn.commit()
        close_db(data_dir)

        cfg = make_config(data_dir)
        prov = FakeProvider("claude")

        report = await collect_doctor_report(cfg, prov)
        assert report is not None
        schema_errors = [e for e in report.errors if "schema" in e.lower() or "newer" in e.lower()]
        assert len(schema_errors) >= 1


async def test_doctor_schema_mismatch_telegram():
    """/doctor via Telegram should reply with schema error, not crash.

    Same scenario as CLI but through the real handler path: cmd_doctor calls
    _load() which hits _db() which raises RuntimeError for schema mismatch.
    """
    import tempfile
    from app.storage import close_db, ensure_data_dirs, _db

    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        conn = _db(data_dir)
        conn.execute("UPDATE meta SET value='99' WHERE key='schema_version'")
        conn.commit()
        close_db(data_dir)

        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        import app.telegram_handlers as th
        chat = FakeChat(1)
        user = FakeUser(42)

        msg = await send_command(th.cmd_doctor, chat, user, "/doctor")
        reply = last_reply(msg)
        assert len(reply) > 0
        assert "schema" in reply.lower() or "newer" in reply.lower()


async def test_send_file_directive():
    """Provider response with SEND_FILE: directive delivers the file to chat."""
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir, working_dir=data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        # Create a file within the allowed working_dir
        test_file = data_dir / "output.txt"
        test_file.write_text("file contents here")

        prov.run_results = [RunResult(text=f"Here is the file\nSEND_FILE: {test_file}")]

        chat = FakeChat(12345)
        user = FakeUser(42)
        msg = await send_text(chat, user, "generate a file")

        # Should have a reply_document entry
        doc_replies = [r for r in msg.replies if r.get("document")]
        assert len(doc_replies) >= 1


async def test_send_image_directive():
    """Provider response with SEND_IMAGE: directive delivers the image to chat."""
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir, working_dir=data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        # Create a fake image file within the allowed working_dir
        test_img = data_dir / "chart.png"
        test_img.write_bytes(b"\x89PNG fake image data")

        prov.run_results = [RunResult(text=f"Here is the chart\nSEND_IMAGE: {test_img}")]

        chat = FakeChat(12345)
        user = FakeUser(42)
        msg = await send_text(chat, user, "make a chart")

        # Should have a reply_photo entry
        photo_replies = [r for r in msg.replies if r.get("photo")]
        assert len(photo_replies) >= 1


# ---------------------------------------------------------------------------
# /project command tests
# ---------------------------------------------------------------------------

async def test_project_list_no_projects():
    """When no projects are configured, /project list says so."""
    import app.telegram_handlers as th
    with fresh_env() as (data_dir, cfg, prov):
        chat = FakeChat(1)
        user = FakeUser(1)
        msg = await send_command(th.cmd_project, chat, user, "/project", args=["list"])
        reply = last_reply(msg)
        assert "No projects configured" in reply


async def test_project_list_shows_projects():
    """When projects are configured, /project list shows them."""
    import app.telegram_handlers as th
    with tempfile.TemporaryDirectory() as proj_dir:
        with fresh_env(config_overrides={
            "projects": (("myapp", proj_dir, ()),),
        }) as (data_dir, cfg, prov):
            chat = FakeChat(1)
            user = FakeUser(1)
            msg = await send_command(th.cmd_project, chat, user, "/project", args=["list"])
            reply = last_reply(msg)
            assert "myapp" in reply
            assert proj_dir in reply


async def test_project_use_switches_project():
    """'/project use <name>' binds the chat to a project and resets provider state."""
    import app.telegram_handlers as th
    with tempfile.TemporaryDirectory() as proj_dir:
        with fresh_env(config_overrides={
            "projects": (("frontend", proj_dir, ()),),
        }) as (data_dir, cfg, prov):
            chat = FakeChat(2001)
            user = FakeUser(1)

            # First send a message to create session state
            prov.run_results = [RunResult(text="ok")]
            await send_text(chat, user, "hello")

            # Now switch project
            msg = await send_command(th.cmd_project, chat, user, "/project", args=["use", "frontend"])
            reply = last_reply(msg)
            assert "Switched to project" in reply
            assert "frontend" in reply
            assert "Provider session reset" in reply

            # Verify session has project_id set and provider state reset
            session = load_session_disk(data_dir, 2001, prov)
            assert session["project_id"] == "frontend"
            # Provider state should be fresh
            assert session["provider_state"].get("started") is not True


async def test_project_use_unknown_project():
    """'/project use <unknown>' returns error."""
    import app.telegram_handlers as th
    with fresh_env(config_overrides={
        "projects": (("myapp", "/tmp", ()),),
    }) as (data_dir, cfg, prov):
        chat = FakeChat(1)
        user = FakeUser(1)
        msg = await send_command(th.cmd_project, chat, user, "/project", args=["use", "nonexistent"])
        reply = last_reply(msg)
        assert "Unknown project" in reply


async def test_project_clear_resets_to_default():
    """'/project clear' removes the project binding and resets provider state."""
    import app.telegram_handlers as th
    with tempfile.TemporaryDirectory() as proj_dir:
        with fresh_env(config_overrides={
            "projects": (("myapp", proj_dir, ()),),
        }) as (data_dir, cfg, prov):
            chat = FakeChat(3001)
            user = FakeUser(1)

            # Bind to project first
            prov.run_results = [RunResult(text="ok")]
            await send_text(chat, user, "hello")
            await send_command(th.cmd_project, chat, user, "/project", args=["use", "myapp"])

            # Clear
            msg = await send_command(th.cmd_project, chat, user, "/project", args=["clear"])
            reply = last_reply(msg)
            assert "Project cleared" in reply

            session = load_session_disk(data_dir, 3001, prov)
            assert session.get("project_id", "") == ""


async def test_project_show_current():
    """'/project' with no args shows the current project."""
    import app.telegram_handlers as th
    with tempfile.TemporaryDirectory() as proj_dir:
        with fresh_env(config_overrides={
            "projects": (("backend", proj_dir, ()),),
        }) as (data_dir, cfg, prov):
            chat = FakeChat(4001)
            user = FakeUser(1)

            # No project active
            msg = await send_command(th.cmd_project, chat, user, "/project")
            reply = last_reply(msg)
            assert "No project" in reply

            # Bind and check
            await send_command(th.cmd_project, chat, user, "/project", args=["use", "backend"])
            msg = await send_command(th.cmd_project, chat, user, "/project")
            reply = last_reply(msg)
            assert "backend" in reply


async def test_project_switch_invalidates_pending():
    """Switching projects clears pending approval requests."""
    import app.telegram_handlers as th
    with tempfile.TemporaryDirectory() as proj_dir:
        with fresh_env(config_overrides={
            "projects": (("proj1", proj_dir, ()),),
        }) as (data_dir, cfg, prov):
            chat = FakeChat(5001)
            user = FakeUser(1)

            # Create a session with a pending request
            session = default_session("claude", prov.new_provider_state(), "on")
            session["pending_approval"] = {"prompt": "do something", "created_at": 0}
            save_session(data_dir, 5001, session)

            # Switch project
            await send_command(th.cmd_project, chat, user, "/project", args=["use", "proj1"])

            # Pending should be cleared
            session = load_session_disk(data_dir, 5001, prov)
            assert session.get("pending_approval") is None and session.get("pending_retry") is None


async def test_session_shows_project():
    """/session shows the active project when one is bound."""
    import app.telegram_handlers as th
    with tempfile.TemporaryDirectory() as proj_dir:
        with fresh_env(config_overrides={
            "projects": (("webapp", proj_dir, ()),),
        }) as (data_dir, cfg, prov):
            chat = FakeChat(6001)
            user = FakeUser(1)

            # Bind to project
            await send_command(th.cmd_project, chat, user, "/project", args=["use", "webapp"])

            # Check /session output
            msg = await send_command(th.cmd_session, chat, user, "/session")
            reply = last_reply(msg)
            assert "webapp" in reply
            assert proj_dir in reply


async def test_context_hash_changes_with_project():
    """Context hash should differ when project_id changes."""
    from app.execution_context import ResolvedExecutionContext
    _d = dict(role="role", active_skills=["skill"], skill_digests={}, provider_config_digest="", execution_config_digest="", base_extra_dirs=[], working_dir="", file_policy="", provider_name="")
    hash1 = ResolvedExecutionContext(**_d, project_id="").context_hash
    hash2 = ResolvedExecutionContext(**_d, project_id="myproject").context_hash
    assert hash1 != hash2


# ---------------------------------------------------------------------------
# /policy — file policy (6.3)
# ---------------------------------------------------------------------------

async def test_policy_default_is_edit():
    """/policy with no args shows current policy; default is edit."""
    import app.telegram_handlers as th
    with fresh_env() as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")
        msg = await send_command(th.cmd_policy, chat, user, "/policy")
        reply = last_reply(msg)
        assert "edit" in reply


async def test_policy_set_inspect():
    """/policy inspect switches to read-only mode and resets provider state."""
    import app.telegram_handlers as th
    with fresh_env() as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")

        # Send a message to create session with provider state
        await send_text(chat, user, "hello")
        session = load_session_disk(data_dir, 1001, prov)
        assert session.get("file_policy", "") != "inspect"

        # Set inspect
        msg = await send_command(th.cmd_policy, chat, user, "/policy", args=["inspect"])
        reply = last_reply(msg)
        assert "inspect" in reply
        assert "reset" in reply.lower()

        # Verify persisted
        session = load_session_disk(data_dir, 1001, prov)
        assert session.get("file_policy") == "inspect"


async def test_policy_set_edit():
    """/policy edit switches back to edit mode."""
    import app.telegram_handlers as th
    with fresh_env() as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")

        # Set inspect first
        await send_command(th.cmd_policy, chat, user, "/policy", args=["inspect"])
        # Switch to edit
        msg = await send_command(th.cmd_policy, chat, user, "/policy", args=["edit"])
        reply = last_reply(msg)
        assert "edit" in reply

        session = load_session_disk(data_dir, 1001, prov)
        assert session.get("file_policy") == "edit"


async def test_policy_same_value_noop():
    """/policy edit when already edit shows already-set message, no reset."""
    import app.telegram_handlers as th
    with fresh_env() as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")
        msg = await send_command(th.cmd_policy, chat, user, "/policy", args=["edit"])
        # Default is edit, so should say "already"
        reply = last_reply(msg)
        assert "already" in reply.lower()


async def test_policy_invalid_arg():
    """/policy with bad argument shows usage hint."""
    import app.telegram_handlers as th
    with fresh_env() as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")
        msg = await send_command(th.cmd_policy, chat, user, "/policy", args=["delete"])
        reply = last_reply(msg)
        assert "inspect" in reply and "edit" in reply  # usage hint


async def test_policy_shown_in_session():
    """/session output includes file policy."""
    import app.telegram_handlers as th
    with fresh_env() as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")

        # Set inspect
        await send_command(th.cmd_policy, chat, user, "/policy", args=["inspect"])
        msg = await send_command(th.cmd_session, chat, user, "/session")
        reply = last_reply(msg)
        assert "inspect" in reply
        assert "File policy" in reply


async def test_policy_inspect_passed_to_provider():
    """When file_policy=inspect, provider run() receives it in context."""
    import app.telegram_handlers as th
    with fresh_env() as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")

        # Set inspect
        await send_command(th.cmd_policy, chat, user, "/policy", args=["inspect"])
        # Send a message
        await send_text(chat, user, "analyze the code")

        assert len(prov.run_calls) == 1
        ctx = prov.run_calls[0]["context"]
        assert ctx.file_policy == "inspect"


async def test_policy_edit_passed_to_provider():
    """When file_policy=edit (default), provider run() gets empty or 'edit'."""
    import app.telegram_handlers as th
    with fresh_env() as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")

        await send_text(chat, user, "write code")

        assert len(prov.run_calls) == 1
        ctx = prov.run_calls[0]["context"]
        # Default: empty string (no file_policy set in session)
        assert ctx.file_policy == ""


async def test_context_hash_changes_with_file_policy():
    """Context hash should differ when file_policy changes."""
    from app.execution_context import ResolvedExecutionContext
    _d = dict(role="role", active_skills=["skill"], skill_digests={}, provider_config_digest="", execution_config_digest="", base_extra_dirs=[], project_id="", working_dir="", provider_name="")
    hash1 = ResolvedExecutionContext(**_d, file_policy="").context_hash
    hash2 = ResolvedExecutionContext(**_d, file_policy="inspect").context_hash
    assert hash1 != hash2


async def test_context_hash_changes_with_working_dir():
    """Context hash should differ when working_dir changes."""
    from app.execution_context import ResolvedExecutionContext
    _d = dict(role="role", active_skills=["skill"], skill_digests={}, provider_config_digest="", execution_config_digest="", base_extra_dirs=[], project_id="", file_policy="", provider_name="")
    hash1 = ResolvedExecutionContext(**_d, working_dir="").context_hash
    hash2 = ResolvedExecutionContext(**_d, working_dir="/opt/frontend").context_hash
    assert hash1 != hash2
    hash3 = ResolvedExecutionContext(**_d, working_dir="/opt/backend").context_hash
    assert hash2 != hash3


# ===========================================================================
# /model command + settings inline keyboard
# ===========================================================================

_PROFILES = {"fast": "claude-haiku-4-5-20251001", "balanced": "claude-sonnet-4-6", "best": "claude-opus-4-6"}

async def test_model_command_shows_profiles():
    """/model with no args shows current profile and inline buttons."""
    import app.telegram_handlers as th
    with fresh_env(config_overrides={
        "model_profiles": _PROFILES, "default_model_profile": "balanced",
    }) as (data_dir, cfg, prov):
        chat = FakeChat(1)
        user = FakeUser(42)
        msg = await send_command(th.cmd_model, chat, user, "/model")
        reply = msg.replies[-1]
        assert "balanced" in reply.get("text", "")
        # Should have inline keyboard buttons
        markup = reply.get("reply_markup")
        assert markup is not None


async def test_model_command_switches_profile():
    """/model fast should switch the session model profile."""
    import app.telegram_handlers as th
    with fresh_env(config_overrides={
        "model_profiles": _PROFILES, "default_model_profile": "balanced",
    }) as (data_dir, cfg, prov):
        chat = FakeChat(1)
        user = FakeUser(42)
        msg = await send_command(th.cmd_model, chat, user, "/model", args=["fast"])
        reply = last_reply(msg)
        assert "fast" in reply.lower()
        session = load_session_disk(data_dir, 1, prov)
        assert session.get("model_profile") == "fast"


async def test_model_command_no_profiles_configured():
    """/model should say no profiles if none configured."""
    import app.telegram_handlers as th
    with fresh_env() as (data_dir, cfg, prov):
        chat = FakeChat(1)
        user = FakeUser(42)
        msg = await send_command(th.cmd_model, chat, user, "/model")
        reply = last_reply(msg)
        assert "no model profiles" in reply.lower()


async def test_settings_callback_model():
    """Inline button setting_model:fast should switch model profile."""
    import app.telegram_handlers as th
    from tests.support.handler_support import send_callback
    with fresh_env(config_overrides={
        "model_profiles": _PROFILES, "default_model_profile": "balanced",
    }) as (data_dir, cfg, prov):
        chat = FakeChat(1)
        user = FakeUser(42)
        query, _ = await send_callback(th.handle_settings_callback, chat, user, "setting_model:fast")
        session = load_session_disk(data_dir, 1, prov)
        assert session.get("model_profile") == "fast"


async def test_settings_callback_approval():
    """Inline button setting_approval:off should change approval mode."""
    import app.telegram_handlers as th
    from tests.support.handler_support import send_callback
    with fresh_env(config_overrides={"approval_mode": "on"}) as (data_dir, cfg, prov):
        chat = FakeChat(1)
        user = FakeUser(42)
        query, _ = await send_callback(th.handle_settings_callback, chat, user, "setting_approval:off")
        session = load_session_disk(data_dir, 1, prov)
        assert session.get("approval_mode") == "off"


async def test_settings_callback_compact():
    """Inline button setting_compact:on should enable compact mode."""
    import app.telegram_handlers as th
    from tests.support.handler_support import send_callback
    with fresh_env() as (data_dir, cfg, prov):
        chat = FakeChat(1)
        user = FakeUser(42)
        query, _ = await send_callback(th.handle_settings_callback, chat, user, "setting_compact:on")
        session = load_session_disk(data_dir, 1, prov)
        assert session.get("compact_mode") is True


async def test_settings_callback_policy():
    """Inline button setting_policy:inspect should change file policy."""
    import app.telegram_handlers as th
    from tests.support.handler_support import send_callback
    with fresh_env() as (data_dir, cfg, prov):
        chat = FakeChat(1)
        user = FakeUser(42)
        query, _ = await send_callback(th.handle_settings_callback, chat, user, "setting_policy:inspect")
        session = load_session_disk(data_dir, 1, prov)
        assert session.get("file_policy") == "inspect"


async def test_compact_change_does_not_reset_provider_state():
    """Changing compact mode via callback must not reset provider_state."""
    import app.telegram_handlers as th
    from tests.support.handler_support import send_callback
    with fresh_env() as (data_dir, cfg, prov):
        chat = FakeChat(1)
        user = FakeUser(42)
        prov.run_results = [RunResult(text="ok", provider_state_updates={"started": True})]
        await send_text(chat, user, "hi")
        session_before = load_session_disk(data_dir, 1, prov)
        assert session_before["provider_state"].get("started") is True
        await send_callback(th.handle_settings_callback, chat, user, "setting_compact:on")
        session_after = load_session_disk(data_dir, 1, prov)
        assert session_after["provider_state"].get("started") is True
        assert session_after.get("compact_mode") is True


async def test_settings_command_shows_current_values():
    """/settings shows current project, model, policy, compact, approval and inline controls."""
    import app.telegram_handlers as th
    from tests.support.handler_support import get_callback_data_values
    with tempfile.TemporaryDirectory() as proj_dir:
        with fresh_env(config_overrides={
            "projects": (("myapp", proj_dir, ()),),
            "model_profiles": {"fast": "claude-3-5-haiku", "balanced": "claude-sonnet-4-6"},
            "default_model_profile": "balanced",
        }) as (data_dir, cfg, prov):
            chat = FakeChat(1)
            user = FakeUser(42)
            msg = await send_command(th.cmd_settings, chat, user, "/settings")
            reply = msg.replies[-1]
            text = reply.get("text", "")
            assert "Chat settings" in text
            assert "Project" in text
            assert "Model profile" in text
            assert "File policy" in text
            assert "Compact mode" in text
            assert "Approval mode" in text
            cbs = get_callback_data_values(reply)
            assert any(cb.startswith("setting_project:") for cb in cbs)
            assert any(cb.startswith("setting_model:") for cb in cbs)
            assert "setting_policy:inspect" in cbs
            assert "setting_policy:edit" in cbs
            assert "setting_compact:on" in cbs
            assert "setting_compact:off" in cbs
            assert "setting_approval:on" in cbs
            assert "setting_approval:off" in cbs


async def test_project_default_shows_inline_keyboard():
    """/project with no args shows inline project selection when projects configured."""
    import app.telegram_handlers as th
    from tests.support.handler_support import get_callback_data_values
    with tempfile.TemporaryDirectory() as proj_dir:
        with fresh_env(config_overrides={
            "projects": (("backend", proj_dir, ()), ("frontend", proj_dir, ()),),
        }) as (data_dir, cfg, prov):
            chat = FakeChat(1)
            user = FakeUser(42)
            msg = await send_command(th.cmd_project, chat, user, "/project")
            reply = msg.replies[-1]
            cbs = get_callback_data_values(reply)
            assert "setting_project:backend" in cbs
            assert "setting_project:frontend" in cbs
            # Clear button only when a project is active
            await send_command(th.cmd_project, chat, user, "/project", args=["use", "backend"])
            msg2 = await send_command(th.cmd_project, chat, user, "/project")
            cbs2 = get_callback_data_values(msg2.replies[-1])
            assert "setting_project:clear" in cbs2


async def test_settings_callback_project_use():
    """setting_project:<name> callback switches project and resets provider state."""
    import app.telegram_handlers as th
    from tests.support.handler_support import send_callback
    with tempfile.TemporaryDirectory() as proj_dir:
        with fresh_env(config_overrides={
            "projects": (("myproj", proj_dir, ()),),
        }) as (data_dir, cfg, prov):
            chat = FakeChat(1)
            user = FakeUser(42)
            prov.run_results = [RunResult(text="ok")]
            await send_text(chat, user, "hi")
            query, cb_msg = await send_callback(th.handle_settings_callback, chat, user, "setting_project:myproj")
            session = load_session_disk(data_dir, 1, prov)
            assert session["project_id"] == "myproj"
            assert session["provider_state"].get("started") is not True
            edit = cb_msg.replies[-1].get("edit_text", "")
            assert "Switched to project" in edit
            assert "myproj" in edit


async def test_settings_callback_project_clear():
    """setting_project:clear callback clears project and resets provider state."""
    import app.telegram_handlers as th
    from tests.support.handler_support import send_callback
    with tempfile.TemporaryDirectory() as proj_dir:
        with fresh_env(config_overrides={
            "projects": (("p1", proj_dir, ()),),
        }) as (data_dir, cfg, prov):
            chat = FakeChat(1)
            user = FakeUser(42)
            await send_command(th.cmd_project, chat, user, "/project", args=["use", "p1"])
            query, cb_msg = await send_callback(th.handle_settings_callback, chat, user, "setting_project:clear")
            session = load_session_disk(data_dir, 1, prov)
            assert session.get("project_id", "") == ""
            edit = cb_msg.replies[-1].get("edit_text", "")
            assert "Project cleared" in edit


async def test_public_settings_shows_managed_and_no_project_policy_buttons():
    """Bucket D: public user /settings shows managed message and no project/policy buttons."""
    import app.telegram_handlers as th
    from app.user_messages import trust_settings_managed_public
    from tests.support.handler_support import get_callback_data_values

    with fresh_data_dir() as data_dir:
        cfg = make_config(
            data_dir,
            allow_open=True,
            allowed_user_ids=frozenset({1, 2, 3}),
            model_profiles={"fast": "claude-fast", "balanced": "claude-balanced"},
            public_model_profiles=frozenset({"fast"}),
            projects=(("proj1", "/tmp/proj1", ()),),
        )
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)
        chat = FakeChat(12345)
        user = FakeUser(999)
        msg = await send_command(th.cmd_settings, chat, user, "/settings")
        text = msg.replies[0]["text"]
        assert trust_settings_managed_public() in text
        cbs = get_callback_data_values(msg.replies[0])
        assert not any(cb.startswith("setting_project:") for cb in cbs)
        assert "setting_policy:inspect" not in cbs
        assert "setting_policy:edit" not in cbs
        assert any(cb.startswith("setting_model:") for cb in cbs)


async def test_public_settings_model_text_and_button_agree_when_default_restricted():
    """Bucket D follow-up: public /settings shows same profile in text and as selected button.

    When default_model_profile is restricted (e.g. balanced) and public only has fast,
    the screen must show Model profile: fast and the fast button must be checked.
    """
    import app.telegram_handlers as th
    from tests.support.handler_support import get_callback_data_values

    with fresh_data_dir() as data_dir:
        cfg = make_config(
            data_dir,
            allow_open=True,
            allowed_user_ids=frozenset({1, 2, 3}),
            model_profiles={"fast": "m1", "balanced": "m2"},
            default_model_profile="balanced",
            public_model_profiles=frozenset({"fast"}),
        )
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)
        chat = FakeChat(12345)
        user = FakeUser(999)
        msg = await send_command(th.cmd_settings, chat, user, "/settings")
        reply = msg.replies[0]
        text = reply["text"]
        assert "Model profile:" in text
        assert "fast" in text
        cbs = get_callback_data_values(reply)
        assert "setting_model:fast" in cbs
        assert not any(cb.startswith("setting_model:") and cb != "setting_model:fast" for cb in cbs)
        markup = reply.get("reply_markup")
        assert markup is not None
        checkmark = "\u2705"
        for row in markup.inline_keyboard:
            for btn in row:
                if getattr(btn, "callback_data", None) == "setting_model:fast":
                    assert btn.text.startswith(checkmark), "fast button must be selected (checkmark)"
                    return
        assert False, "setting_model:fast button not found"


async def test_public_session_shows_resolved_and_managed_message():
    """Bucket D: public user /session shows resolved context and operator-managed message."""
    import app.telegram_handlers as th
    from app.user_messages import trust_settings_managed_public

    with fresh_data_dir() as data_dir:
        cfg = make_config(
            data_dir,
            allow_open=True,
            allowed_user_ids=frozenset({1, 2, 3}),
            model_profiles={"fast": "claude-fast"},
            public_model_profiles=frozenset({"fast"}),
        )
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)
        chat = FakeChat(12345)
        user = FakeUser(999)
        msg = await send_command(th.cmd_session, chat, user, "/session")
        text = msg.replies[0]["text"]
        assert trust_settings_managed_public() in text
        assert "inspect" in text
        assert "Working dir" in text or "Provider" in text


async def test_public_model_shows_only_public_profiles():
    """Bucket D: public user /model shows only public_model_profiles in buttons."""
    import app.telegram_handlers as th
    from tests.support.handler_support import get_callback_data_values

    with fresh_data_dir() as data_dir:
        cfg = make_config(
            data_dir,
            allow_open=True,
            allowed_user_ids=frozenset({1, 2, 3}),
            model_profiles={"fast": "m1", "balanced": "m2", "best": "m3"},
            default_model_profile="balanced",
            public_model_profiles=frozenset({"fast"}),
        )
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)
        chat = FakeChat(12345)
        user = FakeUser(999)
        msg = await send_command(th.cmd_model, chat, user, "/model")
        cbs = get_callback_data_values(msg.replies[0])
        model_buttons = [c for c in cbs if c.startswith("setting_model:")]
        assert len(model_buttons) == 1
        assert "setting_model:fast" in model_buttons


async def test_settings_callback_policy_denial_public():
    """Bucket D: public user clicking policy button gets trust_file_policy_public (command/callback parity)."""
    import app.telegram_handlers as th
    from app.user_messages import trust_file_policy_public

    with fresh_data_dir() as data_dir:
        cfg = make_config(
            data_dir,
            allow_open=True,
            allowed_user_ids=frozenset({1, 2, 3}),
        )
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)
        chat = FakeChat(12345)
        user = FakeUser(999)
        await send_command(th.cmd_settings, chat, user, "/settings")
        cb_msg = FakeMessage(chat=chat)
        query = FakeCallbackQuery("setting_policy:edit", message=cb_msg)
        update = FakeUpdate(user=user, chat=chat, callback_query=query)
        await th.handle_settings_callback(update, FakeContext())
        edit_text = cb_msg.replies[-1].get("edit_text", "")
        assert edit_text == trust_file_policy_public()


async def test_settings_callback_project_denial_public():
    """Bucket D: public user clicking project button gets trust_project_public (command/callback parity)."""
    import app.telegram_handlers as th
    from app.user_messages import trust_project_public

    with fresh_data_dir() as data_dir:
        cfg = make_config(
            data_dir,
            allow_open=True,
            allowed_user_ids=frozenset({1, 2, 3}),
            projects=(("aproj", "/tmp/a", ()),),
        )
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)
        chat = FakeChat(12345)
        user = FakeUser(999)
        await send_command(th.cmd_settings, chat, user, "/settings")
        cb_msg = FakeMessage(chat=chat)
        query = FakeCallbackQuery("setting_project:aproj", message=cb_msg)
        update = FakeUpdate(user=user, chat=chat, callback_query=query)
        await th.handle_settings_callback(update, FakeContext())
        edit_text = cb_msg.replies[-1].get("edit_text", "")
        assert edit_text == trust_project_public()


async def test_settings_callback_project_clears_pending():
    """Project change via callback clears pending approval/retry."""
    import app.telegram_handlers as th
    from tests.support.handler_support import send_callback
    with tempfile.TemporaryDirectory() as proj_dir:
        with fresh_env(config_overrides={
            "projects": (("proj1", proj_dir, ()),),
        }) as (data_dir, cfg, prov):
            chat = FakeChat(1)
            user = FakeUser(42)
            session = default_session("claude", prov.new_provider_state(), "on")
            session["pending_approval"] = {"prompt": "do it", "created_at": 0}
            save_session(data_dir, 1, session)
            await send_callback(th.handle_settings_callback, chat, user, "setting_project:proj1")
            session = load_session_disk(data_dir, 1, prov)
            assert session.get("pending_approval") is None and session.get("pending_retry") is None


async def test_session_shows_model_profile():
    """/session should display the model profile and effective model."""
    import app.telegram_handlers as th
    with fresh_env(config_overrides={
        "model_profiles": _PROFILES, "default_model_profile": "balanced",
    }) as (data_dir, cfg, prov):
        chat = FakeChat(1)
        user = FakeUser(42)
        msg = await send_command(th.cmd_session, chat, user, "/session")
        reply = last_reply(msg)
        assert "balanced" in reply
        assert "claude-sonnet-4-6" in reply


async def test_session_shows_prompt_weight():
    """/session should display prompt weight estimate."""
    import app.telegram_handlers as th
    with fresh_env() as (data_dir, cfg, prov):
        chat = FakeChat(1)
        user = FakeUser(42)
        msg = await send_command(th.cmd_session, chat, user, "/session")
        reply = last_reply(msg)
        assert "Prompt weight" in reply


# -- Handler edge cases (from test_edge_sessions.py, test_edge_providers.py) --


async def test_empty_message_ignored():
    """Empty text message should not trigger provider."""
    with fresh_env() as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")

        await send_text(chat, user, "")
        assert len(prov.run_calls) == 0


async def test_session_codex_shows_thread():
    """/session with codex provider shows thread info."""
    import app.telegram_handlers as th
    with fresh_env(provider_name="codex") as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")

        msg = await send_command(th.cmd_session, chat, user, "/session")
        reply = last_reply(msg)
        assert "Thread" in reply


async def test_message_after_new_gets_fresh_session():
    """/new then message should use fresh provider_state, not stale."""
    import app.telegram_handlers as th
    with fresh_env() as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")

        prov.run_results = [
            RunResult(text="first response", provider_state_updates={"started": True}),
        ]
        await send_text(chat, user, "first message")
        session1 = load_session_disk(data_dir, 1001, prov)
        assert session1["provider_state"]["started"] is True

        # Reset
        await send_command(th.cmd_new, chat, user, "/new")
        session2 = load_session_disk(data_dir, 1001, prov)
        assert session2["provider_state"]["started"] is False

        # Send another message
        prov.run_results = [
            RunResult(text="second response", provider_state_updates={"started": True}),
        ]
        await send_text(chat, user, "second message")
        assert len(prov.run_calls) == 2
        second_call = prov.run_calls[1]
        assert second_call["provider_state"]["started"] is False


async def test_provider_empty_response():
    """Provider returning empty text should not crash."""
    with fresh_env() as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")
        prov.run_results = [RunResult(text="")]

        await send_text(chat, user, "hello")
        assert len(prov.run_calls) == 1
