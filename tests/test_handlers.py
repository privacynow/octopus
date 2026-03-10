"""Core handler integration tests: happy-path routing, session lifecycle, /help, /start, /doctor."""

from pathlib import Path

from app.providers.base import RunContext, RunResult
from app.storage import default_session, save_session
from tests.support.handler_support import (
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
        assert session.get("pending_request") == None


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
        assert session.get("pending_request") == None


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
        session1["pending_request"] = {"prompt": "do something", "created_at": 0}
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
        session1["pending_request"] = {"prompt": "do something", "created_at": _time.time()}
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
