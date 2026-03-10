"""Handler integration tests for credential and setup flows."""

import asyncio
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.providers.base import RunResult
from app.skills import derive_encryption_key, load_user_credentials, save_user_credential
from app.storage import default_session, ensure_data_dirs, save_session
import app.telegram_handlers as _th
from tests.support.assertions import Checks
from tests.support.handler_support import (
    FakeCallbackQuery,
    FakeChat,
    FakeContext,
    FakeMessage,
    FakeProvider,
    FakeUpdate,
    FakeUser,
    get_callback_data_values,
    has_markup_removal,
    last_reply,
    last_run_context,
    load_session_disk,
    make_config,
    make_skill,
    send_command,
    send_text,
    setup_globals,
    test_data_dir,
)

checks = Checks()
run_test = checks.add_test

MARKER_ALPHA = "SKILL_ALPHA_e7f3"
MARKER_BETA = "SKILL_BETA_a2c9"


async def test_credential_capture():
    with test_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        prov.run_results = [RunResult(text="Used github token")]
        setup_globals(cfg, prov)

        original_validate = _th.validate_credential

        async def fake_validate(req, value):
            return (True, "")

        _th.validate_credential = fake_validate
        try:
            chat = FakeChat(12345)
            user = FakeUser(42)

            msg1 = await send_command(_th.cmd_skills, chat, user, "/skills add github-integration", ["add", "github-integration"])
            session = load_session_disk(data_dir, 12345, prov)
            checks.check_not_in("skill NOT active before creds", "github-integration", session.get("active_skills", []))
            checks.check_true("awaiting_skill_setup set", session.get("awaiting_skill_setup") is not None)
            setup = session["awaiting_skill_setup"]
            checks.check("setup user_id", setup["user_id"], 42)
            checks.check("setup skill", setup["skill"], "github-integration")
            checks.check_true("remaining has GITHUB_TOKEN", any(r["key"] == "GITHUB_TOKEN" for r in setup["remaining"]))
            checks.check_true("remaining has validate spec", setup["remaining"][0].get("validate") is not None)
            checks.check_in("mentions setup needed", "needs setup", " ".join(r.get("text", "") for r in msg1.replies).lower())

            secret_msg = FakeMessage(chat=chat, text="ghp_fake_token_12345")
            await _th.handle_message(FakeUpdate(message=secret_msg, user=user, chat=chat), FakeContext())
            checks.check_true("message deleted (secret)", secret_msg.deleted)

            session = load_session_disk(data_dir, 12345, prov)
            checks.check("awaiting_skill_setup cleared", session.get("awaiting_skill_setup"), None)
            checks.check_in("skill activated after creds", "github-integration", session.get("active_skills", []))

            key = derive_encryption_key(cfg.telegram_token)
            creds = load_user_credentials(data_dir, 42, key)
            checks.check_true("credential saved", "github-integration" in creds)
            checks.check("credential value", creds["github-integration"].get("GITHUB_TOKEN"), "ghp_fake_token_12345")
            checks.check_in("ready reply", "ready", " ".join(r.get("text", "") for r in secret_msg.replies).lower())

            msg3 = FakeMessage(chat=chat, text="list my repos")
            await _th.handle_message(FakeUpdate(message=msg3, user=user, chat=chat), FakeContext())
            checks.check("run called after creds satisfied", len(prov.run_calls), 1)
            ctx = prov.run_calls[0]["context"]
            checks.check_true("credential_env has GITHUB_TOKEN", "GITHUB_TOKEN" in ctx.credential_env)
            checks.check("credential_env value", ctx.credential_env["GITHUB_TOKEN"], "ghp_fake_token_12345")
        finally:
            _th.validate_credential = original_validate


run_test("credential capture", test_credential_capture())


async def test_credential_validation_failure():
    with test_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        session = default_session("claude", prov.new_provider_state(), "off")
        session["active_skills"] = ["github-integration"]
        session["awaiting_skill_setup"] = {
            "user_id": 42,
            "skill": "github-integration",
            "remaining": [{
                "key": "GITHUB_TOKEN",
                "prompt": "Paste your token",
                "help_url": None,
                "validate": {
                    "method": "GET",
                    "url": "https://api.github.com/user",
                    "header": "Authorization: Bearer ${GITHUB_TOKEN}",
                    "expect_status": 200,
                },
            }],
        }
        save_session(data_dir, 12345, session)

        original_validate = _th.validate_credential

        async def fake_validate_fail(req, value):
            return (False, "Expected status 200, got 401")

        _th.validate_credential = fake_validate_fail
        try:
            chat = FakeChat(12345)
            user = FakeUser(42)
            msg = FakeMessage(chat=chat, text="bad_token_value")
            await _th.handle_message(FakeUpdate(message=msg, user=user, chat=chat), FakeContext())

            checks.check_true("message deleted on failure", msg.deleted)
            reply_texts = " ".join(r.get("text", "") for r in msg.replies)
            checks.check_in("error mentions validation failed", "validation failed", reply_texts.lower())
            checks.check_in("error mentions 401", "401", reply_texts)

            session = load_session_disk(data_dir, 12345, prov)
            setup = session.get("awaiting_skill_setup")
            checks.check_true("setup state preserved", setup is not None)
            checks.check("remaining count unchanged", len(setup["remaining"]), 1)

            key = derive_encryption_key(cfg.telegram_token)
            creds = load_user_credentials(data_dir, 42, key)
            checks.check_false("no credential saved", creds.get("github-integration", {}).get("GITHUB_TOKEN"))
        finally:
            _th.validate_credential = original_validate


run_test("credential validation failure", test_credential_validation_failure())


async def test_doctor_credential_check():
    with test_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        prov._health_errors = []
        setup_globals(cfg, prov)

        session = default_session("claude", prov.new_provider_state(), "off")
        session["active_skills"] = ["github-integration"]
        save_session(data_dir, 12345, session)

        chat = FakeChat(12345)
        msg = FakeMessage(chat=chat, text="/doctor")
        user = FakeUser(42)
        await _th.cmd_doctor(FakeUpdate(message=msg, user=user, chat=chat), FakeContext())
        checks.check_in("reports missing credential", "GITHUB_TOKEN", " ".join(r.get("text", "") for r in msg.replies))


run_test("/doctor credential checks", test_doctor_credential_check())


async def test_multi_credential():
    with test_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        session = default_session("claude", prov.new_provider_state(), "off")
        session["active_skills"] = ["my-skill"]
        session["awaiting_skill_setup"] = {
            "user_id": 42,
            "skill": "my-skill",
            "remaining": [
                {"key": "API_KEY", "prompt": "Enter API key", "help_url": None, "validate": None},
                {"key": "SECRET", "prompt": "Enter secret", "help_url": None, "validate": None},
            ],
        }
        save_session(data_dir, 12345, session)

        chat = FakeChat(12345)
        user = FakeUser(42)

        msg1 = FakeMessage(chat=chat, text="my-api-key-123")
        await _th.handle_message(FakeUpdate(message=msg1, user=user, chat=chat), FakeContext())
        checks.check_true("msg1 deleted", msg1.deleted)

        session = load_session_disk(data_dir, 12345, prov)
        setup = session.get("awaiting_skill_setup")
        checks.check_true("still in setup", setup is not None)
        checks.check("1 remaining", len(setup["remaining"]), 1)
        checks.check("remaining is SECRET", setup["remaining"][0]["key"], "SECRET")
        checks.check_in("prompts for secret", "secret", " ".join(r.get("text", "") for r in msg1.replies).lower())

        msg2 = FakeMessage(chat=chat, text="super-secret-value")
        await _th.handle_message(FakeUpdate(message=msg2, user=user, chat=chat), FakeContext())
        checks.check_true("msg2 deleted", msg2.deleted)

        session = load_session_disk(data_dir, 12345, prov)
        checks.check("setup cleared", session.get("awaiting_skill_setup"), None)

        key = derive_encryption_key(cfg.telegram_token)
        creds = load_user_credentials(data_dir, 42, key)
        checks.check("API_KEY saved", creds.get("my-skill", {}).get("API_KEY"), "my-api-key-123")
        checks.check("SECRET saved", creds.get("my-skill", {}).get("SECRET"), "super-secret-value")


run_test("multi-credential capture", test_multi_credential())


async def test_credential_env_in_context():
    with test_data_dir() as data_dir:
        cfg = make_config(data_dir, default_skills=("github-integration",))
        prov = FakeProvider("claude")
        prov.run_results = [RunResult(text="used token")]
        setup_globals(cfg, prov)

        key = derive_encryption_key(cfg.telegram_token)
        save_user_credential(data_dir, 42, "github-integration", "GITHUB_TOKEN", "ghp_real_token", key)

        chat = FakeChat(12345)
        user = FakeUser(42)
        await _th.handle_message(FakeUpdate(message=FakeMessage(chat=chat, text="list repos"), user=user, chat=chat), FakeContext())

        checks.check("run called", len(prov.run_calls), 1)
        ctx = prov.run_calls[0]["context"]
        checks.check("credential_env has GITHUB_TOKEN", ctx.credential_env.get("GITHUB_TOKEN"), "ghp_real_token")
        checks.check_true("system_prompt has skill instructions", len(ctx.system_prompt) > 0)


run_test("credential env in context", test_credential_env_in_context())


async def test_missing_creds_block_execution():
    with test_data_dir() as data_dir:
        cfg = make_config(data_dir, default_skills=("github-integration",))
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        chat = FakeChat(12345)
        msg = FakeMessage(chat=chat, text="list repos")
        user = FakeUser(42)
        await _th.handle_message(FakeUpdate(message=msg, user=user, chat=chat), FakeContext())

        checks.check("run NOT called", len(prov.run_calls), 0)
        session = load_session_disk(data_dir, 12345, prov)
        checks.check_true("awaiting_skill_setup set", session.get("awaiting_skill_setup") is not None)
        checks.check_in("prompts for setup", "needs setup", " ".join(r.get("text", "") for r in msg.replies).lower())


run_test("missing creds block execution", test_missing_creds_block_execution())


async def test_skills_add_defers_activation():
    with test_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        chat = FakeChat(12345)
        msg = FakeMessage(chat=chat, text="/skills add github-integration")
        user = FakeUser(42)
        await _th.cmd_skills(FakeUpdate(message=msg, user=user, chat=chat), FakeContext(args=["add", "github-integration"]))

        session = load_session_disk(data_dir, 12345, prov)
        checks.check_not_in("skill not in active_skills yet", "github-integration", session.get("active_skills", []))
        checks.check_true("setup started", session.get("awaiting_skill_setup") is not None)
        checks.check("setup skill name", session["awaiting_skill_setup"]["skill"], "github-integration")
        checks.check_in("mentions setup needed", "needs setup", " ".join(r.get("text", "") for r in msg.replies).lower())


run_test("/skills add defers activation", test_skills_add_defers_activation())


async def test_credential_completion_activates():
    with test_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        session = default_session("claude", prov.new_provider_state(), "off")
        session["active_skills"] = []
        session["awaiting_skill_setup"] = {
            "user_id": 42,
            "skill": "github-integration",
            "remaining": [{"key": "GITHUB_TOKEN", "prompt": "Paste token", "help_url": None, "validate": None}],
        }
        save_session(data_dir, 12345, session)

        chat = FakeChat(12345)
        user = FakeUser(42)
        await _th.handle_message(FakeUpdate(message=FakeMessage(chat=chat, text="ghp_my_token"), user=user, chat=chat), FakeContext())

        session = load_session_disk(data_dir, 12345, prov)
        checks.check_in("skill activated after creds", "github-integration", session.get("active_skills", []))
        checks.check("setup cleared", session.get("awaiting_skill_setup"), None)


run_test("credential completion activates", test_credential_completion_activates())


async def test_skills_add_no_creds():
    from app.skills import load_catalog, get_skill_requirements

    with test_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        no_cred_skill = next((s for s in load_catalog() if not get_skill_requirements(s)), None)
        if not no_cred_skill:
            return

        chat = FakeChat(12345)
        msg = FakeMessage(chat=chat, text=f"/skills add {no_cred_skill}")
        user = FakeUser(42)
        await _th.cmd_skills(FakeUpdate(message=msg, user=user, chat=chat), FakeContext(args=["add", no_cred_skill]))

        session = load_session_disk(data_dir, 12345, prov)
        checks.check_in("skill activated immediately", no_cred_skill, session.get("active_skills", []))
        checks.check("no setup needed", session.get("awaiting_skill_setup"), None)
        checks.check_in("says activated", "activated", " ".join(r.get("text", "") for r in msg.replies).lower())


run_test("/skills add no creds", test_skills_add_no_creds())


async def test_skills_remove_cancels_setup():
    with test_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        session = default_session("claude", prov.new_provider_state(), "off")
        session["active_skills"] = ["github-integration"]
        session["awaiting_skill_setup"] = {
            "user_id": 42,
            "skill": "github-integration",
            "started_at": time.time(),
            "remaining": [{"key": "GITHUB_TOKEN", "prompt": "Paste token", "help_url": None, "validate": None}],
        }
        save_session(data_dir, 12345, session)

        chat = FakeChat(12345)
        user = FakeUser(42)
        await _th.cmd_skills(
            FakeUpdate(message=FakeMessage(chat=chat, text="/skills remove github-integration"), user=user, chat=chat),
            FakeContext(args=["remove", "github-integration"]),
        )
        session = load_session_disk(data_dir, 12345, prov)
        checks.check_not_in("skill removed", "github-integration", session.get("active_skills", []))
        checks.check("setup cancelled", session.get("awaiting_skill_setup"), None)


run_test("/skills remove cancels setup", test_skills_remove_cancels_setup())


async def test_skills_clear_cancels_setup():
    with test_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        session = default_session("claude", prov.new_provider_state(), "off")
        session["active_skills"] = ["github-integration"]
        session["awaiting_skill_setup"] = {
            "user_id": 42,
            "skill": "github-integration",
            "started_at": time.time(),
            "remaining": [{"key": "GITHUB_TOKEN", "prompt": "Paste token", "help_url": None, "validate": None}],
        }
        save_session(data_dir, 12345, session)

        chat = FakeChat(12345)
        user = FakeUser(42)
        await _th.cmd_skills(FakeUpdate(message=FakeMessage(chat=chat, text="/skills clear"), user=user, chat=chat), FakeContext(args=["clear"]))
        session = load_session_disk(data_dir, 12345, prov)
        checks.check("skills empty", session.get("active_skills"), [])
        checks.check("setup cancelled", session.get("awaiting_skill_setup"), None)


run_test("/skills clear cancels setup", test_skills_clear_cancels_setup())


async def test_cross_user_credential_isolation():
    with test_data_dir() as data_dir:
        cfg = make_config(data_dir, approval_mode="on", default_skills=("github-integration",))
        prov = FakeProvider("claude")
        prov.preflight_results = [RunResult(text="Plan: use github")]
        prov.run_results = [RunResult(text="Done with github")]
        setup_globals(cfg, prov)

        original_validate = _th.validate_credential

        async def fake_validate(req, value):
            return (True, "")

        _th.validate_credential = fake_validate
        try:
            key = derive_encryption_key(cfg.telegram_token)
            save_user_credential(data_dir, 100, "github-integration", "GITHUB_TOKEN", "ghp_alice_token", key)
            save_user_credential(data_dir, 200, "github-integration", "GITHUB_TOKEN", "ghp_bob_token", key)

            chat = FakeChat(12345)
            alice = FakeUser(uid=100, username="alice")
            bob = FakeUser(uid=200, username="bob")

            await _th.handle_message(FakeUpdate(message=FakeMessage(chat=chat, text="list my repos"), user=alice, chat=chat), FakeContext())
            checks.check("preflight called", len(prov.preflight_calls), 1)

            session = load_session_disk(data_dir, 12345, prov)
            checks.check("pending has alice's uid", session["pending_request"]["request_user_id"], 100)

            cb_msg = FakeMessage(chat=chat)
            query = FakeCallbackQuery("approval_approve", message=cb_msg)
            update = FakeUpdate(user=bob, chat=chat, callback_query=query)
            update.effective_message = cb_msg
            await _th.handle_callback(update, FakeContext())

            checks.check("run called", len(prov.run_calls), 1)
            ctx = prov.run_calls[0]["context"]
            checks.check("credential_env has GITHUB_TOKEN", ctx.credential_env.get("GITHUB_TOKEN"), "ghp_alice_token")
            checks.check("NOT bob's token", ctx.credential_env.get("GITHUB_TOKEN") != "ghp_bob_token", True)
        finally:
            _th.validate_credential = original_validate


run_test("cross-user credential isolation", test_cross_user_credential_isolation())


async def test_group_chat_setup_isolation():
    with test_data_dir() as data_dir:
        cfg = make_config(data_dir, default_skills=("github-integration",))
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        original_validate = _th.validate_credential

        async def fake_validate(req, value):
            return (True, "")

        _th.validate_credential = fake_validate
        try:
            chat = FakeChat(12345)
            alice = FakeUser(uid=100, username="alice")
            bob = FakeUser(uid=200, username="bob")

            await _th.cmd_skills(
                FakeUpdate(message=FakeMessage(chat=chat, text="/skills add github-integration"), user=alice, chat=chat),
                FakeContext(args=["add", "github-integration"]),
            )
            session = load_session_disk(data_dir, 12345, prov)
            checks.check_true("alice setup started", session.get("awaiting_skill_setup") is not None)
            checks.check("setup is alice's", session["awaiting_skill_setup"]["user_id"], 100)

            await _th.cmd_skills(
                FakeUpdate(message=FakeMessage(chat=chat, text="/skills add github-integration"), user=bob, chat=chat),
                FakeContext(args=["add", "github-integration"]),
            )
            session = load_session_disk(data_dir, 12345, prov)
            checks.check("setup still alice's after bob's attempt", session["awaiting_skill_setup"]["user_id"], 100)

            await _th.cmd_skills(
                FakeUpdate(message=FakeMessage(chat=chat, text="/skills setup github-integration"), user=bob, chat=chat),
                FakeContext(args=["setup", "github-integration"]),
            )
            session = load_session_disk(data_dir, 12345, prov)
            checks.check("setup still alice's after bob's setup attempt", session["awaiting_skill_setup"]["user_id"], 100)

            bob_secret = FakeMessage(chat=chat, text="ghp_bob_secret_token")
            await _th.handle_message(FakeUpdate(message=bob_secret, user=bob, chat=chat), FakeContext())
            checks.check_false("bob's msg not deleted", bob_secret.deleted)

            session = load_session_disk(data_dir, 12345, prov)
            checks.check_true("alice setup still intact", session.get("awaiting_skill_setup") is not None)
            checks.check("still alice's setup", session["awaiting_skill_setup"]["user_id"], 100)

            alice_secret = FakeMessage(chat=chat, text="ghp_alice_real_token")
            await _th.handle_message(FakeUpdate(message=alice_secret, user=alice, chat=chat), FakeContext())
            checks.check_true("alice's msg deleted (secret)", alice_secret.deleted)

            session = load_session_disk(data_dir, 12345, prov)
            checks.check("setup cleared after alice's cred", session.get("awaiting_skill_setup"), None)

            key = derive_encryption_key(cfg.telegram_token)
            alice_creds = load_user_credentials(data_dir, 100, key)
            bob_creds = load_user_credentials(data_dir, 200, key)
            checks.check("alice has GITHUB_TOKEN", alice_creds.get("github-integration", {}).get("GITHUB_TOKEN"), "ghp_alice_real_token")
            checks.check_false("bob has no credential", bob_creds.get("github-integration", {}).get("GITHUB_TOKEN"))
        finally:
            _th.validate_credential = original_validate


run_test("group chat setup isolation", test_group_chat_setup_isolation())


async def test_group_check_cred_satisfaction_no_overwrite():
    with test_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        chat = FakeChat(12345)
        bob = FakeUser(uid=200, username="bob")

        session = default_session("claude", prov.new_provider_state(), "off")
        session["active_skills"] = ["github-integration"]
        session["awaiting_skill_setup"] = {
            "user_id": 100,
            "skill": "github-integration",
            "started_at": time.time(),
            "remaining": [{"key": "GITHUB_TOKEN", "prompt": "Paste token", "help_url": None, "validate": None}],
        }
        save_session(data_dir, 12345, session)

        msg = FakeMessage(chat=chat, text="list repos please")
        await _th.handle_message(FakeUpdate(message=msg, user=bob, chat=chat), FakeContext())

        checks.check("run NOT called", len(prov.run_calls), 0)
        session = load_session_disk(data_dir, 12345, prov)
        setup = session.get("awaiting_skill_setup")
        checks.check_true("setup still exists", setup is not None)
        checks.check("setup still alice's user_id", setup["user_id"], 100)
        checks.check_in("bob told to wait", "wait", " ".join(r.get("text", "") for r in msg.replies).lower())


run_test("group check_cred_satisfaction no overwrite", test_group_check_cred_satisfaction_no_overwrite())


async def test_cross_user_skills_remove_blocked():
    with test_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        session = default_session("claude", prov.new_provider_state(), "off")
        session["active_skills"] = ["github-integration"]
        session["awaiting_skill_setup"] = {
            "user_id": 100,
            "skill": "github-integration",
            "started_at": time.time(),
            "remaining": [{"key": "GITHUB_TOKEN", "prompt": "Paste token", "help_url": None, "validate": None}],
        }
        save_session(data_dir, 12345, session)

        chat = FakeChat(12345)
        bob = FakeUser(uid=200, username="bob")
        msg = FakeMessage(chat=chat, text="/skills remove github-integration")
        await _th.cmd_skills(FakeUpdate(message=msg, user=bob, chat=chat), FakeContext(args=["remove", "github-integration"]))

        session = load_session_disk(data_dir, 12345, prov)
        checks.check_in("skill still active", "github-integration", session.get("active_skills", []))
        checks.check_true("setup preserved", session.get("awaiting_skill_setup") is not None)
        checks.check("setup still alice's", session["awaiting_skill_setup"]["user_id"], 100)
        checks.check_in("bob told to wait", "wait", " ".join(r.get("text", "") for r in msg.replies).lower())

        alice_msg = FakeMessage(chat=chat, text="ghp_alice_real_token")
        await _th.handle_message(FakeUpdate(message=alice_msg, user=FakeUser(uid=100, username="alice"), chat=chat), FakeContext())
        checks.check_true("alice secret deleted", alice_msg.deleted)
        session = load_session_disk(data_dir, 12345, prov)
        checks.check("setup cleared after alice cred", session.get("awaiting_skill_setup"), None)
        checks.check("skill list unchanged after alice cred", session.get("active_skills"), ["github-integration"])


run_test("cross-user /skills remove blocked", test_cross_user_skills_remove_blocked())


async def test_cross_user_skills_clear_blocked():
    with test_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        session = default_session("claude", prov.new_provider_state(), "off")
        session["active_skills"] = ["github-integration", "testing"]
        session["awaiting_skill_setup"] = {
            "user_id": 100,
            "skill": "github-integration",
            "started_at": time.time(),
            "remaining": [{"key": "GITHUB_TOKEN", "prompt": "Paste token", "help_url": None, "validate": None}],
        }
        save_session(data_dir, 12345, session)

        chat = FakeChat(12345)
        bob = FakeUser(uid=200, username="bob")
        msg = FakeMessage(chat=chat, text="/skills clear")
        await _th.cmd_skills(FakeUpdate(message=msg, user=bob, chat=chat), FakeContext(args=["clear"]))

        session = load_session_disk(data_dir, 12345, prov)
        checks.check("skills unchanged", session.get("active_skills"), ["github-integration", "testing"])
        checks.check_true("setup preserved", session.get("awaiting_skill_setup") is not None)
        checks.check("setup still alice's", session["awaiting_skill_setup"]["user_id"], 100)
        checks.check_in("bob told to wait", "wait", " ".join(r.get("text", "") for r in msg.replies).lower())

        alice_msg = FakeMessage(chat=chat, text="ghp_alice_real_token")
        await _th.handle_message(FakeUpdate(message=alice_msg, user=FakeUser(uid=100, username="alice"), chat=chat), FakeContext())
        checks.check_true("alice secret deleted", alice_msg.deleted)
        session = load_session_disk(data_dir, 12345, prov)
        checks.check("setup cleared after alice cred", session.get("awaiting_skill_setup"), None)
        checks.check("skills still unchanged after alice cred", session.get("active_skills"), ["github-integration", "testing"])


run_test("cross-user /skills clear blocked", test_cross_user_skills_clear_blocked())


async def test_cross_user_new_blocked():
    with test_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        session = default_session("claude", prov.new_provider_state(), "off")
        session["active_skills"] = ["github-integration"]
        session["provider_state"]["started"] = True
        session["awaiting_skill_setup"] = {
            "user_id": 100,
            "skill": "github-integration",
            "started_at": time.time(),
            "remaining": [{"key": "GITHUB_TOKEN", "prompt": "Paste token", "help_url": None, "validate": None}],
        }
        save_session(data_dir, 12345, session)

        chat = FakeChat(12345)
        bob = FakeUser(uid=200, username="bob")
        msg = FakeMessage(chat=chat, text="/new")
        await _th.cmd_new(FakeUpdate(message=msg, user=bob, chat=chat), FakeContext())

        session = load_session_disk(data_dir, 12345, prov)
        checks.check_true("setup preserved across /new", session.get("awaiting_skill_setup") is not None)
        checks.check("setup still alice's", session["awaiting_skill_setup"]["user_id"], 100)
        checks.check_true("provider state not reset", session["provider_state"].get("started"))
        checks.check_in("bob told to wait", "wait", " ".join(r.get("text", "") for r in msg.replies).lower())

        alice_msg = FakeMessage(chat=chat, text="ghp_alice_real_token")
        await _th.handle_message(FakeUpdate(message=alice_msg, user=FakeUser(uid=100, username="alice"), chat=chat), FakeContext())
        checks.check_true("alice secret deleted", alice_msg.deleted)
        session = load_session_disk(data_dir, 12345, prov)
        checks.check("setup cleared after alice cred", session.get("awaiting_skill_setup"), None)
        checks.check_true("provider state still not reset after alice cred", session["provider_state"].get("started"))
        checks.check("skills still active after alice cred", session.get("active_skills"), ["github-integration"])


run_test("cross-user /new blocked", test_cross_user_new_blocked())


async def test_expired_foreign_setup_allows_recovery():
    with test_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        chat = FakeChat(12345)
        bob = FakeUser(uid=200, username="bob")

        session = default_session("claude", prov.new_provider_state(), "off")
        session["active_skills"] = ["github-integration"]
        session["awaiting_skill_setup"] = {
            "user_id": 100,
            "skill": "github-integration",
            "started_at": 0,
            "remaining": [{"key": "GITHUB_TOKEN", "prompt": "Paste token", "help_url": None, "validate": None}],
        }
        save_session(data_dir, 12345, session)

        msg = FakeMessage(chat=chat, text="/new")
        await _th.cmd_new(FakeUpdate(message=msg, user=bob, chat=chat), FakeContext())
        session = load_session_disk(data_dir, 12345, prov)
        checks.check("stale setup cleared", session.get("awaiting_skill_setup"), None)
        checks.check_in("fresh conversation", "fresh", " ".join(r.get("text", "") for r in msg.replies).lower())

        session["awaiting_skill_setup"] = {
            "user_id": 100,
            "skill": "github-integration",
            "started_at": 0,
            "remaining": [{"key": "GITHUB_TOKEN", "prompt": "Paste token", "help_url": None, "validate": None}],
        }
        session["active_skills"] = ["github-integration"]
        save_session(data_dir, 12345, session)
        msg2 = FakeMessage(chat=chat, text="/skills clear")
        await _th.cmd_skills(FakeUpdate(message=msg2, user=bob, chat=chat), FakeContext(args=["clear"]))
        session = load_session_disk(data_dir, 12345, prov)
        checks.check("skills cleared", session.get("active_skills"), [])
        checks.check("expired setup cleared", session.get("awaiting_skill_setup"), None)

        session["awaiting_skill_setup"] = {
            "user_id": 100,
            "skill": "github-integration",
            "started_at": 0,
            "remaining": [{"key": "GITHUB_TOKEN", "prompt": "Paste token", "help_url": None, "validate": None}],
        }
        save_session(data_dir, 12345, session)
        await _th.cmd_skills(
            FakeUpdate(message=FakeMessage(chat=chat, text="/skills setup github-integration"), user=bob, chat=chat),
            FakeContext(args=["setup", "github-integration"]),
        )
        session = load_session_disk(data_dir, 12345, prov)
        checks.check_true("bob's setup started after expiry", session.get("awaiting_skill_setup") is not None)
        checks.check("setup is now bob's", session["awaiting_skill_setup"]["user_id"], 200)


run_test("expired foreign setup allows recovery", test_expired_foreign_setup_allows_recovery())


async def test_expired_setup_persisted_on_noop_remove():
    with test_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        session = default_session("claude", prov.new_provider_state(), "off")
        session["active_skills"] = []
        session["awaiting_skill_setup"] = {
            "user_id": 100,
            "skill": "github-integration",
            "started_at": 0,
            "remaining": [{"key": "GITHUB_TOKEN", "prompt": "Paste token", "help_url": None, "validate": None}],
        }
        save_session(data_dir, 12345, session)

        chat = FakeChat(12345)
        bob = FakeUser(uid=200, username="bob")
        await _th.cmd_skills(
            FakeUpdate(message=FakeMessage(chat=chat, text="/skills remove github-integration"), user=bob, chat=chat),
            FakeContext(args=["remove", "github-integration"]),
        )
        session = load_session_disk(data_dir, 12345, prov)
        checks.check("expired setup cleared on disk", session.get("awaiting_skill_setup"), None)


run_test("expired setup persisted on noop remove", test_expired_setup_persisted_on_noop_remove())


async def test_handler_credential_activation_and_capture():
    import app.skills as skills_mod

    orig = skills_mod.CUSTOM_DIR
    try:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            ensure_data_dirs(data_dir)
            custom_dir = Path(tmp) / "custom"
            custom_dir.mkdir()
            skills_mod.CUSTOM_DIR = custom_dir
            make_skill(custom_dir, "alpha", body=MARKER_ALPHA, requires=[{"key": "ALPHA_TOKEN"}])

            cfg = make_config(data_dir)
            prov = FakeProvider("claude")
            setup_globals(cfg, prov)

            original_validate = _th.validate_credential
            _th.validate_credential = lambda req, val: asyncio.coroutine(lambda: (True, ""))()
            try:
                chat = FakeChat(1001)
                alice = FakeUser(uid=100, username="alice")
                await send_command(_th.cmd_skills, chat, alice, "/skills add alpha", ["add", "alpha"])
                session = load_session_disk(data_dir, 1001, prov)
                checks.check_not_in("not active before creds", "alpha", session.get("active_skills", []))
                checks.check_true("setup started", session.get("awaiting_skill_setup") is not None)

                secret_msg = FakeMessage(chat=chat, text="my-secret-token")
                await _th.handle_message(FakeUpdate(message=secret_msg, user=alice, chat=chat), FakeContext())
                checks.check_true("secret message deleted", secret_msg.deleted)

                session = load_session_disk(data_dir, 1001, prov)
                checks.check("setup cleared", session.get("awaiting_skill_setup"), None)
                checks.check_in("skill activated", "alpha", session.get("active_skills", []))

                key = derive_encryption_key(cfg.telegram_token)
                creds = load_user_credentials(data_dir, 100, key)
                checks.check("credential saved", creds.get("alpha", {}).get("ALPHA_TOKEN"), "my-secret-token")
            finally:
                _th.validate_credential = original_validate
    finally:
        skills_mod.CUSTOM_DIR = orig


run_test("handler: credential activation and capture", test_handler_credential_activation_and_capture())


async def test_handler_provider_context_has_skill_and_creds():
    import app.skills as skills_mod

    orig = skills_mod.CUSTOM_DIR
    try:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            ensure_data_dirs(data_dir)
            custom_dir = Path(tmp) / "custom"
            custom_dir.mkdir()
            skills_mod.CUSTOM_DIR = custom_dir
            make_skill(custom_dir, "alpha", body=MARKER_ALPHA, requires=[{"key": "ALPHA_TOKEN"}])

            cfg = make_config(data_dir)
            prov = FakeProvider("claude")
            setup_globals(cfg, prov)
            chat = FakeChat(1001)
            alice = FakeUser(uid=100, username="alice")

            key = derive_encryption_key(cfg.telegram_token)
            save_user_credential(data_dir, 100, "alpha", "ALPHA_TOKEN", "tok-123", key)
            session = default_session(prov.name, prov.new_provider_state(), "off")
            session["active_skills"] = ["alpha"]
            save_session(data_dir, 1001, session)

            prov.run_results = [RunResult(text="done")]
            await send_text(chat, alice, "do something")
            ctx = last_run_context(prov)
            checks.check_in("marker in system_prompt", MARKER_ALPHA, ctx.system_prompt)
            checks.check("cred in env", ctx.credential_env.get("ALPHA_TOKEN"), "tok-123")
    finally:
        skills_mod.CUSTOM_DIR = orig


run_test("handler: provider context has skill instructions and creds", test_handler_provider_context_has_skill_and_creds())


async def test_handler_second_skill_changes_prompt():
    import app.skills as skills_mod

    orig = skills_mod.CUSTOM_DIR
    try:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            ensure_data_dirs(data_dir)
            custom_dir = Path(tmp) / "custom"
            custom_dir.mkdir()
            skills_mod.CUSTOM_DIR = custom_dir
            make_skill(custom_dir, "alpha", body=MARKER_ALPHA, requires=[{"key": "ALPHA_TOKEN"}])
            make_skill(custom_dir, "beta", body=MARKER_BETA)

            cfg = make_config(data_dir)
            prov = FakeProvider("claude")
            setup_globals(cfg, prov)
            chat = FakeChat(1001)
            alice = FakeUser(uid=100, username="alice")

            key = derive_encryption_key(cfg.telegram_token)
            save_user_credential(data_dir, 100, "alpha", "ALPHA_TOKEN", "tok-123", key)
            session = default_session(prov.name, prov.new_provider_state(), "off")
            session["active_skills"] = ["alpha"]
            save_session(data_dir, 1001, session)

            await send_command(_th.cmd_skills, chat, alice, "/skills add beta", ["add", "beta"])
            session = load_session_disk(data_dir, 1001, prov)
            checks.check_in("alpha still active", "alpha", session.get("active_skills", []))
            checks.check_in("beta now active", "beta", session.get("active_skills", []))

            prov.run_results = [RunResult(text="done")]
            await send_text(chat, alice, "go")
            ctx = last_run_context(prov)
            checks.check_in("alpha marker in prompt", MARKER_ALPHA, ctx.system_prompt)
            checks.check_in("beta marker in prompt", MARKER_BETA, ctx.system_prompt)
            checks.check("alpha cred still in env", ctx.credential_env.get("ALPHA_TOKEN"), "tok-123")
    finally:
        skills_mod.CUSTOM_DIR = orig


run_test("handler: second skill changes prompt composition", test_handler_second_skill_changes_prompt())


async def test_handler_skills_remove_drops_cred_env():
    import app.skills as skills_mod

    orig = skills_mod.CUSTOM_DIR
    try:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            ensure_data_dirs(data_dir)
            custom_dir = Path(tmp) / "custom"
            custom_dir.mkdir()
            skills_mod.CUSTOM_DIR = custom_dir
            make_skill(custom_dir, "alpha", body=MARKER_ALPHA, requires=[{"key": "ALPHA_TOKEN"}])
            make_skill(custom_dir, "beta", body=MARKER_BETA)

            cfg = make_config(data_dir)
            prov = FakeProvider("claude")
            setup_globals(cfg, prov)
            chat = FakeChat(1001)
            alice = FakeUser(uid=100, username="alice")

            key = derive_encryption_key(cfg.telegram_token)
            save_user_credential(data_dir, 100, "alpha", "ALPHA_TOKEN", "tok-123", key)
            session = default_session(prov.name, prov.new_provider_state(), "off")
            session["active_skills"] = ["alpha", "beta"]
            save_session(data_dir, 1001, session)

            await send_command(_th.cmd_skills, chat, alice, "/skills remove alpha", ["remove", "alpha"])
            session = load_session_disk(data_dir, 1001, prov)
            checks.check_not_in("alpha removed", "alpha", session.get("active_skills", []))
            checks.check_in("beta preserved", "beta", session.get("active_skills", []))

            prov.run_results = [RunResult(text="done")]
            await send_text(chat, alice, "go")
            ctx = last_run_context(prov)
            checks.check_not_in("alpha marker gone", MARKER_ALPHA, ctx.system_prompt)
            checks.check_in("beta marker present", MARKER_BETA, ctx.system_prompt)
            checks.check("alpha cred gone", ctx.credential_env.get("ALPHA_TOKEN"), None)
    finally:
        skills_mod.CUSTOM_DIR = orig


run_test("handler: /skills remove drops cred env", test_handler_skills_remove_drops_cred_env())


async def test_handler_skills_clear_preserves_credentials():
    import app.skills as skills_mod

    orig = skills_mod.CUSTOM_DIR
    try:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            ensure_data_dirs(data_dir)
            custom_dir = Path(tmp) / "custom"
            custom_dir.mkdir()
            skills_mod.CUSTOM_DIR = custom_dir
            make_skill(custom_dir, "alpha", body=MARKER_ALPHA, requires=[{"key": "ALPHA_TOKEN"}])

            cfg = make_config(data_dir)
            prov = FakeProvider("claude")
            setup_globals(cfg, prov)
            chat = FakeChat(1001)
            alice = FakeUser(uid=100, username="alice")

            key = derive_encryption_key(cfg.telegram_token)
            save_user_credential(data_dir, 100, "alpha", "ALPHA_TOKEN", "tok-123", key)
            session = default_session(prov.name, prov.new_provider_state(), "off")
            session["active_skills"] = ["alpha"]
            save_session(data_dir, 1001, session)

            msg = await send_command(_th.cmd_skills, chat, alice, "/skills clear", ["clear"])
            checks.check_in("reply confirms clear", "removed", last_reply(msg).lower())
            session = load_session_disk(data_dir, 1001, prov)
            checks.check("active_skills empty", session.get("active_skills"), [])
            creds = load_user_credentials(data_dir, 100, key)
            checks.check("credential survives clear", creds.get("alpha", {}).get("ALPHA_TOKEN"), "tok-123")
    finally:
        skills_mod.CUSTOM_DIR = orig


run_test("handler: /skills clear preserves credentials", test_handler_skills_clear_preserves_credentials())


async def test_handler_new_resets_state_not_credentials():
    import app.skills as skills_mod

    orig = skills_mod.CUSTOM_DIR
    try:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            ensure_data_dirs(data_dir)
            custom_dir = Path(tmp) / "custom"
            custom_dir.mkdir()
            skills_mod.CUSTOM_DIR = custom_dir
            make_skill(custom_dir, "alpha", body=MARKER_ALPHA, requires=[{"key": "ALPHA_TOKEN"}])

            cfg = make_config(data_dir)
            prov = FakeProvider("claude")
            setup_globals(cfg, prov)
            chat = FakeChat(1001)
            alice = FakeUser(uid=100, username="alice")

            key = derive_encryption_key(cfg.telegram_token)
            save_user_credential(data_dir, 100, "alpha", "ALPHA_TOKEN", "tok-123", key)
            session = default_session(prov.name, prov.new_provider_state(), "off")
            session["active_skills"] = ["alpha"]
            session["role"] = "senior engineer"
            save_session(data_dir, 1001, session)

            await send_command(_th.cmd_new, chat, alice, "/new")
            session = load_session_disk(data_dir, 1001, prov)
            checks.check("skills reset", session.get("active_skills"), [])
            checks.check("role reset", session.get("role"), "")
            checks.check("setup cleared", session.get("awaiting_skill_setup"), None)
            creds = load_user_credentials(data_dir, 100, key)
            checks.check("credential survives /new", creds.get("alpha", {}).get("ALPHA_TOKEN"), "tok-123")
    finally:
        skills_mod.CUSTOM_DIR = orig


run_test("handler: /new resets state not credentials", test_handler_new_resets_state_not_credentials())


async def test_regression_readd_after_new_skips_setup():
    import app.skills as skills_mod

    orig = skills_mod.CUSTOM_DIR
    try:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            ensure_data_dirs(data_dir)
            custom_dir = Path(tmp) / "custom"
            custom_dir.mkdir()
            skills_mod.CUSTOM_DIR = custom_dir
            make_skill(custom_dir, "alpha", body=MARKER_ALPHA, requires=[{"key": "ALPHA_TOKEN"}])

            cfg = make_config(data_dir)
            prov = FakeProvider("claude")
            setup_globals(cfg, prov)
            chat = FakeChat(1001)
            alice = FakeUser(uid=100, username="alice")

            key = derive_encryption_key(cfg.telegram_token)
            save_user_credential(data_dir, 100, "alpha", "ALPHA_TOKEN", "tok-123", key)
            save_session(data_dir, 1001, default_session(prov.name, prov.new_provider_state(), "off"))

            await send_command(_th.cmd_skills, chat, alice, "/skills add alpha", ["add", "alpha"])
            session = load_session_disk(data_dir, 1001, prov)
            checks.check_in("activates immediately", "alpha", session.get("active_skills", []))
            checks.check("no setup needed", session.get("awaiting_skill_setup"), None)
    finally:
        skills_mod.CUSTOM_DIR = orig


run_test("regression: re-add after /new skips setup", test_regression_readd_after_new_skips_setup())


async def test_smoke_credentialed_skill_flow():
    import app.skills as skills_mod

    orig = skills_mod.CUSTOM_DIR
    try:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            ensure_data_dirs(data_dir)
            custom_dir = Path(tmp) / "custom"
            custom_dir.mkdir()
            skills_mod.CUSTOM_DIR = custom_dir
            make_skill(custom_dir, "alpha", body=MARKER_ALPHA, requires=[{"key": "ALPHA_TOKEN"}])

            cfg = make_config(data_dir)
            prov = FakeProvider("claude")
            setup_globals(cfg, prov)

            original_validate = _th.validate_credential
            _th.validate_credential = lambda req, val: asyncio.coroutine(lambda: (True, ""))()
            try:
                chat = FakeChat(1001)
                alice = FakeUser(uid=100, username="alice")

                await send_command(_th.cmd_skills, chat, alice, "/skills add alpha", ["add", "alpha"])
                secret_msg = FakeMessage(chat=chat, text="my-secret")
                await _th.handle_message(FakeUpdate(message=secret_msg, user=alice, chat=chat), FakeContext())
                checks.check_true("smoke: secret deleted", secret_msg.deleted)

                prov.run_results = [RunResult(text="done")]
                await send_text(chat, alice, "go")
                ctx = last_run_context(prov)
                checks.check_in("smoke: marker in prompt", MARKER_ALPHA, ctx.system_prompt)
                checks.check("smoke: cred in env", ctx.credential_env.get("ALPHA_TOKEN"), "my-secret")
            finally:
                _th.validate_credential = original_validate
    finally:
        skills_mod.CUSTOM_DIR = orig


run_test("smoke: credentialed skill flow", test_smoke_credentialed_skill_flow())


async def test_cancel_setup():
    with test_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        session = default_session(prov.name, prov.new_provider_state(), "off")
        session["awaiting_skill_setup"] = {
            "user_id": 42,
            "skill": "test-skill",
            "started_at": time.time(),
            "remaining": [{"key": "TOKEN", "prompt": "Enter token"}],
        }
        save_session(data_dir, 12345, session)

        chat = FakeChat(12345)
        user = FakeUser(42)
        msg = FakeMessage(chat=chat, text="/cancel")
        await _th.cmd_cancel(FakeUpdate(message=msg, user=user, chat=chat), FakeContext())
        checks.check_in("cancel setup reply", "Credential setup cancelled", msg.replies[0]["text"])
        session = load_session_disk(data_dir, 12345, prov)
        checks.check("setup cleared", session.get("awaiting_skill_setup"), None)


run_test("/cancel clears own setup", test_cancel_setup())


async def test_cancel_nothing():
    with test_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        chat = FakeChat(12345)
        user = FakeUser(42)
        msg = FakeMessage(chat=chat, text="/cancel")
        await _th.cmd_cancel(FakeUpdate(message=msg, user=user, chat=chat), FakeContext())
        checks.check_in("cancel nothing reply", "Nothing to cancel", msg.replies[0]["text"])


run_test("/cancel nothing", test_cancel_nothing())


async def test_cancel_admin_foreign_setup():
    with test_data_dir() as data_dir:
        cfg = make_config(data_dir, admin_user_ids=frozenset({99}))
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        session = default_session(prov.name, prov.new_provider_state(), "off")
        session["awaiting_skill_setup"] = {
            "user_id": 42,
            "skill": "test-skill",
            "started_at": time.time(),
            "remaining": [{"key": "TOKEN", "prompt": "Enter token"}],
        }
        save_session(data_dir, 12345, session)

        chat = FakeChat(12345)
        admin = FakeUser(99, "admin")
        msg = FakeMessage(chat=chat, text="/cancel")
        await _th.cmd_cancel(FakeUpdate(message=msg, user=admin, chat=chat), FakeContext())
        checks.check_in("admin cancel reply", "Credential setup cancelled", msg.replies[0]["text"])


run_test("/cancel admin override", test_cancel_admin_foreign_setup())


async def test_friendly_validation_errors():
    from app.skills import _friendly_validation_error

    msg401 = _friendly_validation_error(401, 200)
    checks.check_in("401 says rejected", "rejected", msg401.lower())
    checks.check_in("401 has code", "401", msg401)
    checks.check_in("500 says unavailable", "unavailable", _friendly_validation_error(500, 200).lower())
    checks.check_in("404 says not found", "not found", _friendly_validation_error(404, 200).lower())


run_test("friendly validation errors", test_friendly_validation_errors())


async def test_credential_prompt_html_link():
    req = {"key": "TOKEN", "prompt": "Enter your token", "help_url": "https://example.com/guide"}
    result = _th._format_credential_prompt(req)
    checks.check_in("has href", 'href="https://example.com/guide"', result)
    checks.check_in("has link text", "setup guide", result)
    result2 = _th._format_credential_prompt({"key": "TOKEN", "prompt": "Enter your token", "help_url": None})
    checks.check_not_in("no href", "href", result2)


run_test("credential prompt clickable URL", test_credential_prompt_html_link())


async def test_delete_user_credentials():
    from app.skills import delete_user_credentials

    with test_data_dir() as data_dir:
        key = derive_encryption_key("1234567890:AABBCCDDEEFFaabbccddeeff_01234567")
        save_user_credential(data_dir, 42, "skill-a", "TOKEN_A", "value-a", key)
        save_user_credential(data_dir, 42, "skill-b", "TOKEN_B", "value-b", key)

        removed = delete_user_credentials(data_dir, 42, key, "skill-a")
        checks.check("removed one", removed, ["skill-a"])
        creds = load_user_credentials(data_dir, 42, key)
        checks.check_true("skill-b remains", "skill-b" in creds)
        checks.check_false("skill-a gone", "skill-a" in creds)

        removed2 = delete_user_credentials(data_dir, 42, key)
        checks.check("removed all", removed2, ["skill-b"])
        checks.check("nothing to remove", delete_user_credentials(data_dir, 42, key), [])


run_test("delete_user_credentials", test_delete_user_credentials())


async def test_foreign_setup_message_info():
    msg = _th._foreign_setup_message({"user_id": 42, "started_at": time.time() - 120})
    checks.check_in("has user id", "42", msg)
    checks.check_in("has time", "min ago", msg)
    checks.check_in("has admin hint", "/cancel", msg)


run_test("foreign setup message info", test_foreign_setup_message_info())


async def test_clear_credentials_confirm_flow():
    """Clear credentials shows confirmation, then clears on confirm."""
    import app.skills as skills_mod

    orig_custom_dir = skills_mod.CUSTOM_DIR
    try:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            ensure_data_dirs(data_dir)
            custom_dir = Path(tmp) / "custom-skills"
            skills_mod.CUSTOM_DIR = custom_dir

            skill_dir = custom_dir / "cred-test"
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "skill.md").write_text("---\nname: cred-test\ndisplay_name: Cred Test\ndescription: Test\n---\n\nTest instructions.\n")
            (skill_dir / "requires.yaml").write_text("credentials:\n  - key: API_TOKEN\n    prompt: Enter token\n")

            cfg = make_config(data_dir)
            prov = FakeProvider("claude")
            setup_globals(cfg, prov)

            chat = FakeChat(12345)
            user = FakeUser(42)
            key = derive_encryption_key(cfg.telegram_token)
            save_user_credential(data_dir, 42, "cred-test", "API_TOKEN", "old-value", key)

            session = default_session(prov.name, prov.new_provider_state(), "off")
            session["awaiting_skill_setup"] = {
                "user_id": 42,
                "skill": "cred-test",
                "started_at": time.time(),
                "remaining": [{"key": "API_TOKEN", "prompt": "Enter token"}],
            }
            save_session(data_dir, 12345, session)

            # Step 1: Command shows confirmation
            msg = await send_command(_th.cmd_clear_credentials, chat, user, "/clear_credentials cred-test", args=["cred-test"])
            reply = msg.replies[-1]
            checks.check_in("confirmation mentions skill", "cred-test", reply["text"])
            checks.check("has buttons", "reply_markup" in reply, True)
            cb_values = get_callback_data_values(reply)
            checks.check_true("confirm button data", any("clear_cred_confirm" in v for v in cb_values))
            checks.check_true("cancel button data", any("clear_cred_cancel" in v for v in cb_values))

            # Step 2: Confirm via callback (data includes user_id)
            cb_msg = FakeMessage(chat=chat)
            query = FakeCallbackQuery("clear_cred_confirm:42:cred-test", message=cb_msg)
            update = FakeUpdate(user=user, chat=chat, callback_query=query)
            await _th.handle_clear_cred_callback(update, FakeContext())

            checks.check("confirm: single answer", len(query.answers), 1)
            checks.check_false("confirm: not an alert", query.answer_show_alert)
            checks.check_true("confirm: buttons removed", has_markup_removal(cb_msg))
            session = load_session_disk(data_dir, 12345, prov)
            checks.check("setup cleared", session.get("awaiting_skill_setup"), None)
            creds = load_user_credentials(data_dir, 42, key)
            checks.check("credentials removed", "cred-test" in creds, False)
            checks.check_in("reply confirms cleared", "cleared", cb_msg.replies[-1]["edit_text"].lower())
    finally:
        skills_mod.CUSTOM_DIR = orig_custom_dir


run_test("clear_credentials confirm flow", test_clear_credentials_confirm_flow())


async def test_clear_credentials_cancel():
    """Cancel button aborts credential clearing."""
    import app.skills as skills_mod

    orig_custom_dir = skills_mod.CUSTOM_DIR
    try:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            ensure_data_dirs(data_dir)
            custom_dir = Path(tmp) / "custom-skills"
            skills_mod.CUSTOM_DIR = custom_dir

            skill_dir = custom_dir / "cred-test"
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "skill.md").write_text("---\nname: cred-test\ndisplay_name: Cred Test\ndescription: Test\n---\n\nTest instructions.\n")
            (skill_dir / "requires.yaml").write_text("credentials:\n  - key: API_TOKEN\n    prompt: Enter token\n")

            cfg = make_config(data_dir)
            prov = FakeProvider("claude")
            setup_globals(cfg, prov)

            chat = FakeChat(12345)
            user = FakeUser(42)
            key = derive_encryption_key(cfg.telegram_token)
            save_user_credential(data_dir, 42, "cred-test", "API_TOKEN", "old-value", key)

            # Step 1: Command shows confirmation
            msg = await send_command(_th.cmd_clear_credentials, chat, user, "/clear_credentials cred-test", args=["cred-test"])
            checks.check("has buttons", "reply_markup" in msg.replies[-1], True)

            # Step 2: Cancel via callback (data includes user_id)
            cb_msg = FakeMessage(chat=chat)
            query = FakeCallbackQuery("clear_cred_cancel:42", message=cb_msg)
            update = FakeUpdate(user=user, chat=chat, callback_query=query)
            await _th.handle_clear_cred_callback(update, FakeContext())

            checks.check("cancel: single answer", len(query.answers), 1)
            checks.check_false("cancel: not an alert", query.answer_show_alert)
            checks.check_true("cancel: buttons removed", has_markup_removal(cb_msg))
            checks.check_in("reply says cancelled", "cancelled", cb_msg.replies[-1]["edit_text"].lower())
            # Credentials should still exist
            creds = load_user_credentials(data_dir, 42, key)
            checks.check("credentials preserved", "cred-test" in creds, True)
    finally:
        skills_mod.CUSTOM_DIR = orig_custom_dir


run_test("clear_credentials cancel", test_clear_credentials_cancel())


async def test_clear_credentials_all_confirm():
    """Clear all credentials with confirmation."""
    import app.skills as skills_mod

    orig_custom_dir = skills_mod.CUSTOM_DIR
    try:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            ensure_data_dirs(data_dir)
            custom_dir = Path(tmp) / "custom-skills"
            skills_mod.CUSTOM_DIR = custom_dir

            for sname in ("skill-a", "skill-b"):
                sd = custom_dir / sname
                sd.mkdir(parents=True, exist_ok=True)
                (sd / "skill.md").write_text(f"---\nname: {sname}\ndisplay_name: {sname}\ndescription: Test\n---\n\nInstructions.\n")
                (sd / "requires.yaml").write_text(f"credentials:\n  - key: TOKEN_{sname.upper().replace('-','_')}\n    prompt: Enter token\n")

            cfg = make_config(data_dir)
            prov = FakeProvider("claude")
            setup_globals(cfg, prov)

            chat = FakeChat(12345)
            user = FakeUser(42)
            key = derive_encryption_key(cfg.telegram_token)
            save_user_credential(data_dir, 42, "skill-a", "TOKEN_SKILL_A", "val-a", key)
            save_user_credential(data_dir, 42, "skill-b", "TOKEN_SKILL_B", "val-b", key)

            # No args → clear all
            msg = await send_command(_th.cmd_clear_credentials, chat, user, "/clear_credentials")
            reply = msg.replies[-1]
            checks.check_in("lists skill-a", "skill-a", reply["text"])
            checks.check_in("lists skill-b", "skill-b", reply["text"])
            checks.check("has buttons", "reply_markup" in reply, True)

            # Verify clear-all button data
            cb_values = get_callback_data_values(reply)
            checks.check_true("confirm_all button", any("clear_cred_confirm_all" in v for v in cb_values))

            # Confirm (data includes user_id)
            cb_msg = FakeMessage(chat=chat)
            query = FakeCallbackQuery("clear_cred_confirm_all:42", message=cb_msg)
            update = FakeUpdate(user=user, chat=chat, callback_query=query)
            await _th.handle_clear_cred_callback(update, FakeContext())

            checks.check_true("confirm_all: buttons removed", has_markup_removal(cb_msg))
            creds = load_user_credentials(data_dir, 42, key)
            checks.check("all credentials removed", len(creds), 0)
    finally:
        skills_mod.CUSTOM_DIR = orig_custom_dir


run_test("clear_credentials all confirm", test_clear_credentials_all_confirm())


async def test_clear_credentials_no_stored():
    """Clear credentials with nothing stored shows informative message."""
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp) / "data"
        ensure_data_dirs(data_dir)
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        chat = FakeChat(12345)
        user = FakeUser(42)

        # Specific skill
        msg = await send_command(_th.cmd_clear_credentials, chat, user, "/clear_credentials foo", args=["foo"])
        checks.check_in("no creds message", "no stored credentials", msg.replies[-1]["text"].lower())

        # All
        msg2 = await send_command(_th.cmd_clear_credentials, chat, user, "/clear_credentials")
        checks.check_in("no creds all message", "no stored credentials", msg2.replies[-1]["text"].lower())


run_test("clear_credentials no stored", test_clear_credentials_no_stored())


async def test_clear_credentials_cross_user_rejected():
    """In a group chat, Bob cannot tap Alice's clear-credentials button."""
    import app.skills as skills_mod

    orig_custom_dir = skills_mod.CUSTOM_DIR
    try:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            ensure_data_dirs(data_dir)
            custom_dir = Path(tmp) / "custom-skills"
            skills_mod.CUSTOM_DIR = custom_dir

            skill_dir = custom_dir / "cred-test"
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "skill.md").write_text("---\nname: cred-test\ndisplay_name: Cred Test\ndescription: Test\n---\n\nTest instructions.\n")
            (skill_dir / "requires.yaml").write_text("credentials:\n  - key: API_TOKEN\n    prompt: Enter token\n")

            cfg = make_config(data_dir)
            prov = FakeProvider("claude")
            setup_globals(cfg, prov)

            chat = FakeChat(12345)
            alice = FakeUser(42)
            bob = FakeUser(99)
            key = derive_encryption_key(cfg.telegram_token)
            save_user_credential(data_dir, 42, "cred-test", "API_TOKEN", "alice-token", key)
            save_user_credential(data_dir, 99, "cred-test", "API_TOKEN", "bob-token", key)

            # Alice initiates clear — button encodes alice's user_id (42)
            msg = await send_command(_th.cmd_clear_credentials, chat, alice, "/clear_credentials cred-test", args=["cred-test"])
            checks.check("has buttons", "reply_markup" in msg.replies[-1], True)

            # Bob clicks Alice's confirm button — should be rejected
            cb_msg = FakeMessage(chat=chat)
            query = FakeCallbackQuery("clear_cred_confirm:42:cred-test", message=cb_msg)
            update = FakeUpdate(user=bob, chat=chat, callback_query=query)
            await _th.handle_clear_cred_callback(update, FakeContext())

            # Both credentials should still exist
            alice_creds = load_user_credentials(data_dir, 42, key)
            bob_creds = load_user_credentials(data_dir, 99, key)
            checks.check("alice creds preserved", "cred-test" in alice_creds, True)
            checks.check("bob creds preserved", "cred-test" in bob_creds, True)
            # No edit_text reply (only query.answer with alert)
            checks.check("no edit made", len(cb_msg.replies), 0)
            # Callback should have shown an alert to the wrong user
            checks.check("single answer", len(query.answers), 1)
            checks.check_true("answer is alert", query.answer_show_alert)
            checks.check_in("alert mentions other user", "another user", query.answer_text.lower())
    finally:
        skills_mod.CUSTOM_DIR = orig_custom_dir


run_test("clear_credentials cross-user rejected", test_clear_credentials_cross_user_rejected())


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


if __name__ == "__main__":
    checks.run_async_and_exit()
