"""Core handler integration tests: happy-path routing, session lifecycle, /help, /start, /doctor."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.providers.base import RunContext, RunResult
from app.storage import default_session, save_session
from tests.support.assertions import Checks
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
    setup_globals,
    test_data_dir,
)

checks = Checks()
_tests: list[tuple[str, object]] = []


def run_test(name, coro):
    _tests.append((name, coro))


async def test_happy_path():
    with test_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        prov.run_results = [RunResult(text="Hello world", provider_state_updates={"started": True})]
        setup_globals(cfg, prov)

        chat = FakeChat(12345)
        user = FakeUser(42)
        msg = FakeMessage(chat=chat, text="hi there")

        import app.telegram_handlers as th

        await th.handle_message(FakeUpdate(message=msg, user=user, chat=chat), FakeContext())

        checks.check("provider.run called once", len(prov.run_calls), 1)
        checks.check_in("prompt has user text", "hi there", prov.run_calls[0]["prompt"])

        ctx = prov.run_calls[0]["context"]
        checks.check_true("context is RunContext", isinstance(ctx, RunContext))
        checks.check_true("extra_dirs has upload dir", any("uploads" in d for d in ctx.extra_dirs))
        checks.check_true("normal run does not skip permissions", ctx.skip_permissions is False)

        session = load_session_disk(data_dir, 12345, prov)
        checks.check("provider_state.started", session["provider_state"]["started"], True)
        checks.check_true("got replies", len(msg.replies) >= 2)
        checks.check_in("reply contains response", "Hello world", " ".join(r.get("text", r.get("edit_text", "")) for r in msg.replies))


run_test("happy path", test_happy_path())


async def test_cmd_new():
    with test_data_dir() as data_dir:
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
        checks.check_false("started is False", new_session["provider_state"].get("started"))
        checks.check("approval_mode uses config default", new_session["approval_mode"], "off")
        checks.check_false("scripts dir removed", (data_dir / "scripts" / "12345").exists())
        checks.check_in("fresh reply", "Fresh", " ".join(r.get("text", "") for r in msg.replies))


run_test("/new resets session", test_cmd_new())


async def test_provider_timeout():
    with test_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        prov.run_results = [RunResult(text="partial output", timed_out=True)]
        setup_globals(cfg, prov)

        chat = FakeChat(12345)
        user = FakeUser(42)
        msg = FakeMessage(chat=chat, text="long running task")

        import app.telegram_handlers as th

        await th.handle_message(FakeUpdate(message=msg, user=user, chat=chat), FakeContext())

        checks.check("run called", len(prov.run_calls), 1)
        reply_texts = " ".join(r.get("text", "") for r in msg.replies)
        checks.check_not_in("no formatted reply of partial text", "partial output", reply_texts)
        checks.check("only status msg reply (no formatted reply)", sum(1 for r in msg.replies if "text" in r), 1)
        session = load_session_disk(data_dir, 12345, prov)
        checks.check("no pending on timeout", session.get("pending_request"), None)


run_test("provider timeout", test_provider_timeout())


async def test_provider_error_returncode():
    with test_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        prov.run_results = [RunResult(text="Error: segfault in subprocess", returncode=1)]
        setup_globals(cfg, prov)

        chat = FakeChat(12345)
        user = FakeUser(42)
        msg = FakeMessage(chat=chat, text="crash me")

        import app.telegram_handlers as th

        await th.handle_message(FakeUpdate(message=msg, user=user, chat=chat), FakeContext())

        checks.check("run called", len(prov.run_calls), 1)
        reply_texts = " ".join(r.get("text", "") for r in msg.replies)
        checks.check_not_in("no formatted reply of error text", "segfault", reply_texts)
        checks.check("only status msg reply (no formatted reply)", sum(1 for r in msg.replies if "text" in r), 1)
        session = load_session_disk(data_dir, 12345, prov)
        checks.check("no pending on error", session.get("pending_request"), None)


run_test("provider error returncode", test_provider_error_returncode())


async def test_cmd_role():
    with test_data_dir() as data_dir:
        cfg = make_config(data_dir, role="default engineer")
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        import app.telegram_handlers as th

        chat = FakeChat(12345)
        user = FakeUser(42)

        msg1 = FakeMessage(chat=chat, text="/role")
        await th.cmd_role(FakeUpdate(message=msg1, user=user, chat=chat), FakeContext(args=[]))
        checks.check_in("shows default role", "default engineer", " ".join(r.get("text", "") for r in msg1.replies))

        msg2 = FakeMessage(chat=chat, text="/role security auditor")
        await th.cmd_role(FakeUpdate(message=msg2, user=user, chat=chat), FakeContext(args=["security", "auditor"]))
        session = load_session_disk(data_dir, 12345, prov)
        checks.check("role updated", session.get("role"), "security auditor")

        msg3 = FakeMessage(chat=chat, text="/role clear")
        await th.cmd_role(FakeUpdate(message=msg3, user=user, chat=chat), FakeContext(args=["clear"]))
        session = load_session_disk(data_dir, 12345, prov)
        checks.check("role reset to default", session.get("role"), "default engineer")
        checks.check_in("says reset", "default", " ".join(r.get("text", "") for r in msg3.replies).lower())


run_test("/role command", test_cmd_role())


async def test_role_in_provider_context():
    with test_data_dir() as data_dir:
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

        checks.check("run called", len(prov.run_calls), 1)
        checks.check_in("system_prompt has role", "Kubernetes expert", prov.run_calls[0]["context"].system_prompt)


run_test("role in provider context", test_role_in_provider_context())


async def test_new_preserves_default_skills():
    from app.skills import save_user_credential, derive_encryption_key

    with test_data_dir() as data_dir:
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
        checks.check_in("default skill preserved", "github-integration", session.get("active_skills", []))
        checks.check_not_in("extra skill removed", "extra-skill", session.get("active_skills", []))


run_test("/new preserves default_skills", test_new_preserves_default_skills())


async def test_help_topics():
    with test_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        import app.telegram_handlers as th

        chat = FakeChat(12345)
        user = FakeUser(42)

        msg1 = FakeMessage(chat=chat, text="/help skills")
        await th.cmd_help(FakeUpdate(message=msg1, user=user, chat=chat), FakeContext(args=["skills"]))
        checks.check_in("help skills has add", "/skills add", msg1.replies[0]["text"])

        msg2 = FakeMessage(chat=chat, text="/help approval")
        await th.cmd_help(FakeUpdate(message=msg2, user=user, chat=chat), FakeContext(args=["approval"]))
        checks.check_in("help approval has mode", "Approval Mode", msg2.replies[0]["text"])

        msg3 = FakeMessage(chat=chat, text="/help credentials")
        await th.cmd_help(FakeUpdate(message=msg3, user=user, chat=chat), FakeContext(args=["credentials"]))
        checks.check_in("help credentials has clear", "/clear_credentials", msg3.replies[0]["text"])

        msg4 = FakeMessage(chat=chat, text="/help")
        await th.cmd_help(FakeUpdate(message=msg4, user=user, chat=chat), FakeContext(args=[]))
        checks.check_in("main help has commands", "/skills", msg4.replies[0]["text"])
        checks.check_not_in("main help no CLI Bridge", "CLI Bridge", msg4.replies[0]["text"])


run_test("/help tiered", test_help_topics())


async def test_first_run_welcome():
    with test_data_dir() as data_dir:
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
        checks.check_in("welcome has ready", "ready", sent.lower())
        checks.check_in("welcome mentions approval", "Approval mode is on", sent)


run_test("first-run welcome", test_first_run_welcome())


async def test_start_deep_link():
    with test_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        import app.telegram_handlers as th

        chat = FakeChat(12345)
        user = FakeUser(42)
        msg = FakeMessage(chat=chat, text="/start foo")
        await th.cmd_start(FakeUpdate(message=msg, user=user, chat=chat), FakeContext(args=["foo"]))
        checks.check_not_in("/start payload not unknown topic", "Unknown help topic", msg.replies[0]["text"])
        checks.check_in("/start payload shows main help", "Agent Bot", msg.replies[0]["text"])


run_test("/start deep-link payload", test_start_deep_link())

async def test_doctor_admin_warning():
    with test_data_dir() as data_dir:
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
        checks.check_in("doctor warns about admin fallback", "BOT_ADMIN_USERS", reply)


run_test("/doctor admin fallback warning", test_doctor_admin_warning())


async def test_doctor_no_warning_explicit_admin():
    with test_data_dir() as data_dir:
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
        checks.check_not_in("no admin warning with explicit admins", "BOT_ADMIN_USERS", reply)


run_test("/doctor no warning with explicit admin", test_doctor_no_warning_explicit_admin())


async def test_prompt_size_warning_before_activation():
    import app.skills as skills_mod

    with test_data_dir() as data_dir:
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
            checks.check_in("warns about prompt size", "prompt context", reply)
            checks.check_in("shows threshold", "8,000", reply)
            checks.check_in("asks to continue", "Continue", reply)

            session = load_session_disk(data_dir, 1, prov)
            checks.check_not_in("skill not activated", "big-skill",
                                session.get("active_skills", []))
        finally:
            skills_mod.CUSTOM_DIR = orig_custom_dir


run_test("prompt size warning before activation", test_prompt_size_warning_before_activation())


async def test_prompt_size_no_warning_small_skill():
    import app.skills as skills_mod

    with test_data_dir() as data_dir:
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
            checks.check_in("activated without warning", "activated", reply)
            checks.check_not_in("no threshold warning", "prompt context", reply)

            session = load_session_disk(data_dir, 1, prov)
            checks.check_in("skill is active", "tiny-skill",
                             session.get("active_skills", []))
        finally:
            skills_mod.CUSTOM_DIR = orig_custom_dir


run_test("no warning for small skill", test_prompt_size_no_warning_small_skill())


async def test_doctor_stale_session_warnings():
    with test_data_dir() as data_dir:
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
        checks.check_in("warns about pending", "pending approval", reply)
        checks.check_in("warns about setup", "credential setup", reply)


run_test("/doctor stale session warnings", test_doctor_stale_session_warnings())


async def test_doctor_no_warning_explicit_admin_equal_to_allowed():
    """If BOT_ADMIN_USERS is explicitly set to same as BOT_ALLOWED_USERS,
    /doctor should NOT warn (operator made a deliberate choice)."""
    with test_data_dir() as data_dir:
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
        checks.check_not_in("no false positive for explicit equal admin",
                            "BOT_ADMIN_USERS", reply)


run_test("/doctor no false positive for explicit admin", test_doctor_no_warning_explicit_admin_equal_to_allowed())


async def test_doctor_no_stale_warning_for_fresh_sessions():
    import time as _time
    with test_data_dir() as data_dir:
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
        checks.check_not_in("no stale pending warning for fresh", "stale pending", reply)
        checks.check_not_in("no stale setup warning for fresh", "stale credential", reply)


run_test("/doctor no stale warning for fresh sessions", test_doctor_no_stale_warning_for_fresh_sessions())


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


async def _main():
    await _run_all()
    print(f"\n{'=' * 40}")
    print(f"  {checks.passed} passed, {checks.failed} failed")
    print(f"{'=' * 40}")
    raise SystemExit(1 if checks.failed else 0)


if __name__ == "__main__":
    asyncio.run(_main())
