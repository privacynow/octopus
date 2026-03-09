"""Core handler integration tests that don't belong to approval/output/store/credential suites."""

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.providers.base import RunContext, RunResult
from app.skills import get_provider_config_digest
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
    load_session_disk,
    make_config,
    send_command,
    setup_globals,
)

checks = Checks()
_tests: list[tuple[str, object]] = []


def run_test(name, coro):
    _tests.append((name, coro))


async def test_happy_path():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
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
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
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
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
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
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
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


async def test_rich_role_verbatim():
    from app.skills import build_system_prompt

    prompt1 = build_system_prompt("senior Python engineer", [])
    checks.check_in("short role wrapped", "You are a senior Python engineer", prompt1)

    rich = "You are a senior architect.\nYou specialize in distributed systems."
    prompt2 = build_system_prompt(rich, [])
    checks.check_in("rich role verbatim", "You are a senior architect.", prompt2)
    checks.check_not_in("no double wrap", "You are a You are", prompt2)

    prompt3 = build_system_prompt("You are an expert in Kubernetes.", [])
    checks.check_not_in("no double wrap for 'You are'", "You are a You are", prompt3)
    checks.check_in("starts with You are", "You are an expert", prompt3)

    prompt4 = build_system_prompt("Act as a security auditor.", [])
    checks.check_not_in("no wrap for 'Act as'", "You are a Act as", prompt4)
    checks.check_in("starts with Act as", "Act as a security auditor", prompt4)

    prompt5 = build_system_prompt("you are an expert in kubernetes.", [])
    checks.check_not_in("no double wrap lowercase", "You are a you are", prompt5)
    checks.check_in("lowercase verbatim", "you are an expert in kubernetes", prompt5)

    prompt6 = build_system_prompt("you're a helpful coding assistant.", [])
    checks.check_not_in("no wrap for you're", "You are a you're", prompt6)
    checks.check_in("you're verbatim", "you're a helpful coding assistant", prompt6)


run_test("rich role verbatim", test_rich_role_verbatim())


async def test_provider_scoped_digest():
    digest_claude = get_provider_config_digest(["github-integration"], provider_name="claude")
    digest_codex = get_provider_config_digest(["github-integration"], provider_name="codex")
    digest_all = get_provider_config_digest(["github-integration"])

    checks.check("claude != codex digest", digest_claude != digest_codex, True)
    checks.check("unscoped != claude", digest_all != digest_claude, True)
    checks.check("unscoped != codex", digest_all != digest_codex, True)


run_test("provider-scoped digest", test_provider_scoped_digest())


async def test_mcp_args_is_list():
    from app.skills import load_provider_yaml

    raw = load_provider_yaml("github-integration", "claude")
    mcp = raw.get("mcp_servers", {}).get("github", {})
    checks.check_true("args is a list", isinstance(mcp.get("args"), list))
    checks.check("args has 2 elements", len(mcp.get("args", [])), 2)
    checks.check_in("args contains -y", "-y", mcp["args"])

    raw2 = load_provider_yaml("linear-integration", "claude")
    mcp2 = raw2.get("mcp_servers", {}).get("linear", {})
    checks.check_true("linear args is a list", isinstance(mcp2.get("args"), list))


run_test("MCP args is list", test_mcp_args_is_list())


async def test_malformed_skill_resilience():
    import app.skills as skills_mod
    from app.skills import _skill_dir, get_skill_instructions, get_skill_requirements, load_catalog

    orig_custom_dir = skills_mod.CUSTOM_DIR
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_dir = Path(tmpdir) / "custom-skills"
            skills_mod.CUSTOM_DIR = custom_dir
            malformed_dir = custom_dir / "malformed-test-skill"
            malformed_dir.mkdir(parents=True, exist_ok=True)
            (malformed_dir / "skill.md").write_text(
                "---\nname: malformed-test-skill\ndescription: [invalid yaml\n---\n\nBody text here.\n"
            )

            catalog = load_catalog()
            checks.check_true("load_catalog did not crash", isinstance(catalog, dict))
            checks.check_not_in("malformed skill not in catalog", "malformed-test-skill", catalog)
            checks.check("_skill_dir returns None for malformed", _skill_dir("malformed-test-skill"), None)
            checks.check("instructions empty for malformed", get_skill_instructions("malformed-test-skill"), "")
            checks.check("requirements empty for malformed", get_skill_requirements("malformed-test-skill"), [])
    finally:
        skills_mod.CUSTOM_DIR = orig_custom_dir


run_test("malformed skill resilience", test_malformed_skill_resilience())


async def test_malformed_provider_yaml_resilience():
    import app.skills as skills_mod
    from app.skills import build_provider_config, load_provider_yaml

    orig_custom_dir = skills_mod.CUSTOM_DIR
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_dir = Path(tmpdir) / "custom-skills"
            skills_mod.CUSTOM_DIR = custom_dir
            skill_dir = custom_dir / "yaml-test-skill"
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "skill.md").write_text(
                "---\nname: yaml-test-skill\ndisplay_name: YAML Test\ndescription: Test skill\n---\n\nTest.\n"
            )
            (skill_dir / "claude.yaml").write_text("mcp_servers:\n  test:\n    command: echo\n    args: [unclosed\n")

            checks.check("malformed yaml returns empty dict", load_provider_yaml("yaml-test-skill", "claude"), {})
            checks.check("build_provider_config returns dict", isinstance(build_provider_config("claude", ["yaml-test-skill"], {}), dict), True)
    finally:
        skills_mod.CUSTOM_DIR = orig_custom_dir


run_test("malformed provider yaml resilience", test_malformed_provider_yaml_resilience())


async def test_malformed_requires_yaml_resilience():
    from app.skills import _parse_requires_yaml

    checks.check("malformed requires.yaml returns empty", _parse_requires_yaml("credentials:\n  - key: [unclosed\n"), [])
    checks.check("non-dict requires.yaml returns empty", _parse_requires_yaml("just_a_string"), [])
    checks.check("empty requires.yaml returns empty", _parse_requires_yaml(""), [])


run_test("malformed requires.yaml resilience", test_malformed_requires_yaml_resilience())


async def test_bot_skills_validation():
    from app.config import validate_config

    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        errors = validate_config(make_config(data_dir, default_skills=("nonexistent-skill-xyz",), provider_name="claude"))
        checks.check_true("reports unknown skill", len([e for e in errors if "nonexistent-skill-xyz" in e]) > 0)

        errors2 = validate_config(make_config(data_dir, default_skills=("github-integration",), provider_name="claude"))
        checks.check("valid skill no error", len([e for e in errors2 if "BOT_SKILLS" in e and "github-integration" in e]), 0)

        errors3 = validate_config(make_config(data_dir, default_skills=(), provider_name="claude"))
        checks.check("no skills no error", len([e for e in errors3 if "BOT_SKILLS" in e]), 0)


run_test("BOT_SKILLS validation", test_bot_skills_validation())


async def test_cmd_role():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
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
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
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

    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
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


async def test_catalog_uses_directory_name():
    import app.skills as skills_mod
    from app.skills import _skill_dir, get_skill_instructions, load_catalog

    orig_custom_dir = skills_mod.CUSTOM_DIR
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_dir = Path(tmpdir) / "custom-skills"
            skills_mod.CUSTOM_DIR = custom_dir
            skill_dir = custom_dir / "my-actual-dir"
            skill_dir.mkdir(parents=True)
            (skill_dir / "skill.md").write_text(
                "---\nname: fancy-meta-name\ndisplay_name: Fancy Skill\ndescription: A test skill\n---\n\nDo fancy things.\n"
            )

            catalog = load_catalog()
            checks.check_in("dir name in catalog", "my-actual-dir", catalog)
            checks.check_not_in("frontmatter name NOT in catalog", "fancy-meta-name", catalog)
            checks.check_true("_skill_dir finds dir name", _skill_dir("my-actual-dir") is not None)
            checks.check("_skill_dir misses frontmatter name", _skill_dir("fancy-meta-name"), None)
            checks.check_in("instructions loaded", "fancy things", get_skill_instructions("my-actual-dir"))
            checks.check("no instructions by frontmatter name", get_skill_instructions("fancy-meta-name"), "")
    finally:
        skills_mod.CUSTOM_DIR = orig_custom_dir


run_test("catalog uses directory name", test_catalog_uses_directory_name())


async def test_bad_validate_spec_no_crash():
    from app.skills import SkillRequirement, validate_credential

    req = SkillRequirement(
        key="API_KEY",
        prompt="Enter key",
        help_url=None,
        validate={
            "method": "GET",
            "url": "https://example.com/health",
            "header": "Authorization: Bearer ${API_KEY}",
            "expect_status": "twohundred",
        },
    )
    ok, detail = await validate_credential(req, "some-key-value")
    checks.check("returns not-ok", ok, False)
    checks.check_in("mentions invalid expect_status", "expect_status", detail.lower())

    req2 = SkillRequirement(
        key="API_KEY",
        prompt="Enter key",
        help_url=None,
        validate={"method": "GET", "url": "https://example.com/health", "expect_status": None},
    )
    ok2, detail2 = await validate_credential(req2, "some-key")
    checks.check("none expect_status returns not-ok", ok2, False)
    checks.check_in("mentions invalid", "invalid", detail2.lower())


run_test("bad validate spec no crash", test_bad_validate_spec_no_crash())


async def test_help_topics():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
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
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
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
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
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
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        # Multiple allowed users, no explicit admin set (admin == allowed)
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
        from tests.support.handler_support import send_command, last_reply

        chat = FakeChat(1)
        user = FakeUser(1)
        msg = await send_command(th.cmd_doctor, chat, user, "/doctor")
        reply = last_reply(msg)
        checks.check_in("doctor warns about admin fallback", "BOT_ADMIN_USERS", reply)


run_test("/doctor admin fallback warning", test_doctor_admin_warning())


async def test_doctor_no_warning_explicit_admin():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        # Explicit admin subset
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
        from tests.support.handler_support import send_command, last_reply

        chat = FakeChat(1)
        user = FakeUser(1)
        msg = await send_command(th.cmd_doctor, chat, user, "/doctor")
        reply = last_reply(msg)
        checks.check_not_in("no admin warning with explicit admins", "BOT_ADMIN_USERS", reply)


run_test("/doctor no warning with explicit admin", test_doctor_no_warning_explicit_admin())


async def test_prompt_size_warning_before_activation():
    import app.skills as skills_mod
    from tests.support.handler_support import FakeContext

    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)

        orig_custom_dir = skills_mod.CUSTOM_DIR
        try:
            custom_dir = data_dir / "custom-skills"
            skills_mod.CUSTOM_DIR = custom_dir

            # Create a skill with huge instructions
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

            # Skill should NOT be activated yet
            session = load_session_disk(data_dir, 1, prov)
            checks.check_not_in("skill not activated", "big-skill",
                                session.get("active_skills", []))
        finally:
            skills_mod.CUSTOM_DIR = orig_custom_dir


run_test("prompt size warning before activation", test_prompt_size_warning_before_activation())


async def test_prompt_size_no_warning_small_skill():
    import app.skills as skills_mod

    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)

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
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        # Create a session with a pending request
        session1 = default_session("claude", prov.new_provider_state(), "off")
        session1["pending_request"] = {"prompt": "do something", "created_at": 0}  # epoch = very old
        save_session(data_dir, 100, session1)

        # Create a session with stale credential setup
        session2 = default_session("claude", prov.new_provider_state(), "off")
        session2["awaiting_skill_setup"] = {"user_id": 42, "skill": "test", "started_at": 0}  # epoch = very old
        save_session(data_dir, 200, session2)

        # Create a clean session
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
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
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
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        # Create sessions with fresh timestamps (just now)
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
# inserted before _run_all
