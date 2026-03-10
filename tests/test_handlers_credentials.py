"""Handler integration tests for credential and setup flows."""

import asyncio
import tempfile
import time
from pathlib import Path

from app.providers.base import RunResult
from app.skills import derive_encryption_key, load_user_credentials, save_user_credential
from app.storage import default_session, ensure_data_dirs, save_session
import app.telegram_handlers as _th
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
    fresh_data_dir,
)

MARKER_ALPHA = "SKILL_ALPHA_e7f3"
MARKER_BETA = "SKILL_BETA_a2c9"


async def test_credential_capture():
    with fresh_data_dir() as data_dir:
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
            assert "github-integration" not in session.get("active_skills", [])
            assert session.get("awaiting_skill_setup") is not None
            setup = session["awaiting_skill_setup"]
            assert setup["user_id"] == 42
            assert setup["skill"] == "github-integration"
            assert any(r["key"] == "GITHUB_TOKEN" for r in setup["remaining"])
            assert setup["remaining"][0].get("validate") is not None
            assert "needs setup" in " ".join(r.get("text", "") for r in msg1.replies).lower()

            secret_msg = FakeMessage(chat=chat, text="ghp_fake_token_12345")
            await _th.handle_message(FakeUpdate(message=secret_msg, user=user, chat=chat), FakeContext())
            assert secret_msg.deleted

            session = load_session_disk(data_dir, 12345, prov)
            assert session.get("awaiting_skill_setup") is None
            assert "github-integration" in session.get("active_skills", [])

            key = derive_encryption_key(cfg.telegram_token)
            creds = load_user_credentials(data_dir, 42, key)
            assert "github-integration" in creds
            assert creds["github-integration"].get("GITHUB_TOKEN") == "ghp_fake_token_12345"
            assert "ready" in " ".join(r.get("text", "") for r in secret_msg.replies).lower()

            msg3 = FakeMessage(chat=chat, text="list my repos")
            await _th.handle_message(FakeUpdate(message=msg3, user=user, chat=chat), FakeContext())
            assert len(prov.run_calls) == 1
            ctx = prov.run_calls[0]["context"]
            assert "GITHUB_TOKEN" in ctx.credential_env
            assert ctx.credential_env["GITHUB_TOKEN"] == "ghp_fake_token_12345"
        finally:
            _th.validate_credential = original_validate


async def test_credential_validation_failure():
    with fresh_data_dir() as data_dir:
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

            assert msg.deleted
            reply_texts = " ".join(r.get("text", "") for r in msg.replies)
            assert "validation failed" in reply_texts.lower()
            assert "401" in reply_texts

            session = load_session_disk(data_dir, 12345, prov)
            setup = session.get("awaiting_skill_setup")
            assert setup is not None
            assert len(setup["remaining"]) == 1

            key = derive_encryption_key(cfg.telegram_token)
            creds = load_user_credentials(data_dir, 42, key)
            assert not creds.get("github-integration", {}).get("GITHUB_TOKEN")
        finally:
            _th.validate_credential = original_validate


async def test_doctor_credential_check():
    with fresh_data_dir() as data_dir:
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
        assert "GITHUB_TOKEN" in " ".join(r.get("text", "") for r in msg.replies)


async def test_multi_credential():
    with fresh_data_dir() as data_dir:
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
        assert msg1.deleted

        session = load_session_disk(data_dir, 12345, prov)
        setup = session.get("awaiting_skill_setup")
        assert setup is not None
        assert len(setup["remaining"]) == 1
        assert setup["remaining"][0]["key"] == "SECRET"
        assert "secret" in " ".join(r.get("text", "") for r in msg1.replies).lower()

        msg2 = FakeMessage(chat=chat, text="super-secret-value")
        await _th.handle_message(FakeUpdate(message=msg2, user=user, chat=chat), FakeContext())
        assert msg2.deleted

        session = load_session_disk(data_dir, 12345, prov)
        assert session.get("awaiting_skill_setup") is None

        key = derive_encryption_key(cfg.telegram_token)
        creds = load_user_credentials(data_dir, 42, key)
        assert creds.get("my-skill", {}).get("API_KEY") == "my-api-key-123"
        assert creds.get("my-skill", {}).get("SECRET") == "super-secret-value"


async def test_credential_env_in_context():
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir, default_skills=("github-integration",))
        prov = FakeProvider("claude")
        prov.run_results = [RunResult(text="used token")]
        setup_globals(cfg, prov)

        key = derive_encryption_key(cfg.telegram_token)
        save_user_credential(data_dir, 42, "github-integration", "GITHUB_TOKEN", "ghp_real_token", key)

        chat = FakeChat(12345)
        user = FakeUser(42)
        await _th.handle_message(FakeUpdate(message=FakeMessage(chat=chat, text="list repos"), user=user, chat=chat), FakeContext())

        assert len(prov.run_calls) == 1
        ctx = prov.run_calls[0]["context"]
        assert ctx.credential_env.get("GITHUB_TOKEN") == "ghp_real_token"
        assert len(ctx.system_prompt) > 0


async def test_missing_creds_block_execution():
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir, default_skills=("github-integration",))
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        chat = FakeChat(12345)
        msg = FakeMessage(chat=chat, text="list repos")
        user = FakeUser(42)
        await _th.handle_message(FakeUpdate(message=msg, user=user, chat=chat), FakeContext())

        assert len(prov.run_calls) == 0
        session = load_session_disk(data_dir, 12345, prov)
        assert session.get("awaiting_skill_setup") is not None
        assert "needs setup" in " ".join(r.get("text", "") for r in msg.replies).lower()


async def test_skills_add_defers_activation():
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        chat = FakeChat(12345)
        msg = FakeMessage(chat=chat, text="/skills add github-integration")
        user = FakeUser(42)
        await _th.cmd_skills(FakeUpdate(message=msg, user=user, chat=chat), FakeContext(args=["add", "github-integration"]))

        session = load_session_disk(data_dir, 12345, prov)
        assert "github-integration" not in session.get("active_skills", [])
        assert session.get("awaiting_skill_setup") is not None
        assert session["awaiting_skill_setup"]["skill"] == "github-integration"
        assert "needs setup" in " ".join(r.get("text", "") for r in msg.replies).lower()


async def test_credential_completion_activates():
    with fresh_data_dir() as data_dir:
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
        assert "github-integration" in session.get("active_skills", [])
        assert session.get("awaiting_skill_setup") is None


async def test_skills_add_no_creds():
    from app.skills import load_catalog, get_skill_requirements

    with fresh_data_dir() as data_dir:
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
        assert no_cred_skill in session.get("active_skills", [])
        assert session.get("awaiting_skill_setup") is None
        assert "activated" in " ".join(r.get("text", "") for r in msg.replies).lower()


async def test_skills_remove_cancels_setup():
    with fresh_data_dir() as data_dir:
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
        assert "github-integration" not in session.get("active_skills", [])
        assert session.get("awaiting_skill_setup") is None


async def test_skills_clear_cancels_setup():
    with fresh_data_dir() as data_dir:
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
        assert session.get("active_skills") == []
        assert session.get("awaiting_skill_setup") is None


async def test_cross_user_credential_isolation():
    with fresh_data_dir() as data_dir:
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
            assert len(prov.preflight_calls) == 1

            session = load_session_disk(data_dir, 12345, prov)
            assert session["pending_request"]["request_user_id"] == 100

            cb_msg = FakeMessage(chat=chat)
            query = FakeCallbackQuery("approval_approve", message=cb_msg)
            update = FakeUpdate(user=bob, chat=chat, callback_query=query)
            update.effective_message = cb_msg
            await _th.handle_callback(update, FakeContext())

            assert len(prov.run_calls) == 1
            ctx = prov.run_calls[0]["context"]
            assert ctx.credential_env.get("GITHUB_TOKEN") == "ghp_alice_token"
            assert ctx.credential_env.get("GITHUB_TOKEN") != "ghp_bob_token"
        finally:
            _th.validate_credential = original_validate


async def test_group_chat_setup_isolation():
    with fresh_data_dir() as data_dir:
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
            assert session.get("awaiting_skill_setup") is not None
            assert session["awaiting_skill_setup"]["user_id"] == 100

            await _th.cmd_skills(
                FakeUpdate(message=FakeMessage(chat=chat, text="/skills add github-integration"), user=bob, chat=chat),
                FakeContext(args=["add", "github-integration"]),
            )
            session = load_session_disk(data_dir, 12345, prov)
            assert session["awaiting_skill_setup"]["user_id"] == 100

            await _th.cmd_skills(
                FakeUpdate(message=FakeMessage(chat=chat, text="/skills setup github-integration"), user=bob, chat=chat),
                FakeContext(args=["setup", "github-integration"]),
            )
            session = load_session_disk(data_dir, 12345, prov)
            assert session["awaiting_skill_setup"]["user_id"] == 100

            bob_secret = FakeMessage(chat=chat, text="ghp_bob_secret_token")
            await _th.handle_message(FakeUpdate(message=bob_secret, user=bob, chat=chat), FakeContext())
            assert not bob_secret.deleted

            session = load_session_disk(data_dir, 12345, prov)
            assert session.get("awaiting_skill_setup") is not None
            assert session["awaiting_skill_setup"]["user_id"] == 100

            alice_secret = FakeMessage(chat=chat, text="ghp_alice_real_token")
            await _th.handle_message(FakeUpdate(message=alice_secret, user=alice, chat=chat), FakeContext())
            assert alice_secret.deleted

            session = load_session_disk(data_dir, 12345, prov)
            assert session.get("awaiting_skill_setup") is None

            key = derive_encryption_key(cfg.telegram_token)
            alice_creds = load_user_credentials(data_dir, 100, key)
            bob_creds = load_user_credentials(data_dir, 200, key)
            assert alice_creds.get("github-integration", {}).get("GITHUB_TOKEN") == "ghp_alice_real_token"
            assert not bob_creds.get("github-integration", {}).get("GITHUB_TOKEN")
        finally:
            _th.validate_credential = original_validate


async def test_group_check_cred_satisfaction_no_overwrite():
    with fresh_data_dir() as data_dir:
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

        assert len(prov.run_calls) == 0
        session = load_session_disk(data_dir, 12345, prov)
        setup = session.get("awaiting_skill_setup")
        assert setup is not None
        assert setup["user_id"] == 100
        assert "wait" in " ".join(r.get("text", "") for r in msg.replies).lower()


async def test_cross_user_skills_remove_blocked():
    with fresh_data_dir() as data_dir:
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
        assert "github-integration" in session.get("active_skills", [])
        assert session.get("awaiting_skill_setup") is not None
        assert session["awaiting_skill_setup"]["user_id"] == 100
        assert "wait" in " ".join(r.get("text", "") for r in msg.replies).lower()

        alice_msg = FakeMessage(chat=chat, text="ghp_alice_real_token")
        await _th.handle_message(FakeUpdate(message=alice_msg, user=FakeUser(uid=100, username="alice"), chat=chat), FakeContext())
        assert alice_msg.deleted
        session = load_session_disk(data_dir, 12345, prov)
        assert session.get("awaiting_skill_setup") is None
        assert session.get("active_skills") == ["github-integration"]


async def test_cross_user_skills_clear_blocked():
    with fresh_data_dir() as data_dir:
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
        assert session.get("active_skills") == ["github-integration", "testing"]
        assert session.get("awaiting_skill_setup") is not None
        assert session["awaiting_skill_setup"]["user_id"] == 100
        assert "wait" in " ".join(r.get("text", "") for r in msg.replies).lower()

        alice_msg = FakeMessage(chat=chat, text="ghp_alice_real_token")
        await _th.handle_message(FakeUpdate(message=alice_msg, user=FakeUser(uid=100, username="alice"), chat=chat), FakeContext())
        assert alice_msg.deleted
        session = load_session_disk(data_dir, 12345, prov)
        assert session.get("awaiting_skill_setup") is None
        assert session.get("active_skills") == ["github-integration", "testing"]


async def test_cross_user_new_blocked():
    with fresh_data_dir() as data_dir:
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
        assert session.get("awaiting_skill_setup") is not None
        assert session["awaiting_skill_setup"]["user_id"] == 100
        assert session["provider_state"].get("started")
        assert "wait" in " ".join(r.get("text", "") for r in msg.replies).lower()

        alice_msg = FakeMessage(chat=chat, text="ghp_alice_real_token")
        await _th.handle_message(FakeUpdate(message=alice_msg, user=FakeUser(uid=100, username="alice"), chat=chat), FakeContext())
        assert alice_msg.deleted
        session = load_session_disk(data_dir, 12345, prov)
        assert session.get("awaiting_skill_setup") is None
        assert session["provider_state"].get("started")
        assert session.get("active_skills") == ["github-integration"]


async def test_expired_foreign_setup_allows_recovery():
    with fresh_data_dir() as data_dir:
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
        assert session.get("awaiting_skill_setup") is None
        assert "fresh" in " ".join(r.get("text", "") for r in msg.replies).lower()

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
        assert session.get("active_skills") == []
        assert session.get("awaiting_skill_setup") is None

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
        assert session.get("awaiting_skill_setup") is not None
        assert session["awaiting_skill_setup"]["user_id"] == 200


async def test_expired_setup_persisted_on_noop_remove():
    with fresh_data_dir() as data_dir:
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
        assert session.get("awaiting_skill_setup") is None


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
                assert "alpha" not in session.get("active_skills", [])
                assert session.get("awaiting_skill_setup") is not None

                secret_msg = FakeMessage(chat=chat, text="my-secret-token")
                await _th.handle_message(FakeUpdate(message=secret_msg, user=alice, chat=chat), FakeContext())
                assert secret_msg.deleted

                session = load_session_disk(data_dir, 1001, prov)
                assert session.get("awaiting_skill_setup") is None
                assert "alpha" in session.get("active_skills", [])

                key = derive_encryption_key(cfg.telegram_token)
                creds = load_user_credentials(data_dir, 100, key)
                assert creds.get("alpha", {}).get("ALPHA_TOKEN") == "my-secret-token"
            finally:
                _th.validate_credential = original_validate
    finally:
        skills_mod.CUSTOM_DIR = orig


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
            assert MARKER_ALPHA in ctx.system_prompt
            assert ctx.credential_env.get("ALPHA_TOKEN") == "tok-123"
    finally:
        skills_mod.CUSTOM_DIR = orig


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
            assert "alpha" in session.get("active_skills", [])
            assert "beta" in session.get("active_skills", [])

            prov.run_results = [RunResult(text="done")]
            await send_text(chat, alice, "go")
            ctx = last_run_context(prov)
            assert MARKER_ALPHA in ctx.system_prompt
            assert MARKER_BETA in ctx.system_prompt
            assert ctx.credential_env.get("ALPHA_TOKEN") == "tok-123"
    finally:
        skills_mod.CUSTOM_DIR = orig


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
            assert "alpha" not in session.get("active_skills", [])
            assert "beta" in session.get("active_skills", [])

            prov.run_results = [RunResult(text="done")]
            await send_text(chat, alice, "go")
            ctx = last_run_context(prov)
            assert MARKER_ALPHA not in ctx.system_prompt
            assert MARKER_BETA in ctx.system_prompt
            assert ctx.credential_env.get("ALPHA_TOKEN") is None
    finally:
        skills_mod.CUSTOM_DIR = orig


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
            assert "removed" in last_reply(msg).lower()
            session = load_session_disk(data_dir, 1001, prov)
            assert session.get("active_skills") == []
            creds = load_user_credentials(data_dir, 100, key)
            assert creds.get("alpha", {}).get("ALPHA_TOKEN") == "tok-123"
    finally:
        skills_mod.CUSTOM_DIR = orig


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
            assert session.get("active_skills") == []
            assert session.get("role") == ""
            assert session.get("awaiting_skill_setup") is None
            creds = load_user_credentials(data_dir, 100, key)
            assert creds.get("alpha", {}).get("ALPHA_TOKEN") == "tok-123"
    finally:
        skills_mod.CUSTOM_DIR = orig


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
            assert "alpha" in session.get("active_skills", [])
            assert session.get("awaiting_skill_setup") is None
    finally:
        skills_mod.CUSTOM_DIR = orig


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
                assert secret_msg.deleted

                prov.run_results = [RunResult(text="done")]
                await send_text(chat, alice, "go")
                ctx = last_run_context(prov)
                assert MARKER_ALPHA in ctx.system_prompt
                assert ctx.credential_env.get("ALPHA_TOKEN") == "my-secret"
            finally:
                _th.validate_credential = original_validate
    finally:
        skills_mod.CUSTOM_DIR = orig


async def test_cancel_setup():
    with fresh_data_dir() as data_dir:
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
        assert "Credential setup cancelled" in msg.replies[0]["text"]
        session = load_session_disk(data_dir, 12345, prov)
        assert session.get("awaiting_skill_setup") is None


async def test_cancel_nothing():
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        chat = FakeChat(12345)
        user = FakeUser(42)
        msg = FakeMessage(chat=chat, text="/cancel")
        await _th.cmd_cancel(FakeUpdate(message=msg, user=user, chat=chat), FakeContext())
        assert "Nothing to cancel" in msg.replies[0]["text"]


async def test_cancel_admin_foreign_setup():
    with fresh_data_dir() as data_dir:
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
        assert "Credential setup cancelled" in msg.replies[0]["text"]


async def test_friendly_validation_errors():
    from app.skills import _friendly_validation_error

    msg401 = _friendly_validation_error(401, 200)
    assert "rejected" in msg401.lower()
    assert "401" in msg401
    assert "unavailable" in _friendly_validation_error(500, 200).lower()
    assert "not found" in _friendly_validation_error(404, 200).lower()


async def test_credential_prompt_html_link():
    req = {"key": "TOKEN", "prompt": "Enter your token", "help_url": "https://example.com/guide"}
    result = _th._format_credential_prompt(req)
    assert 'href="https://example.com/guide"' in result
    assert "setup guide" in result
    result2 = _th._format_credential_prompt({"key": "TOKEN", "prompt": "Enter your token", "help_url": None})
    assert "href" not in result2


async def test_delete_user_credentials():
    from app.skills import delete_user_credentials

    with fresh_data_dir() as data_dir:
        key = derive_encryption_key("1234567890:AABBCCDDEEFFaabbccddeeff_01234567")
        save_user_credential(data_dir, 42, "skill-a", "TOKEN_A", "value-a", key)
        save_user_credential(data_dir, 42, "skill-b", "TOKEN_B", "value-b", key)

        removed = delete_user_credentials(data_dir, 42, key, "skill-a")
        assert removed == ["skill-a"]
        creds = load_user_credentials(data_dir, 42, key)
        assert "skill-b" in creds
        assert "skill-a" not in creds

        removed2 = delete_user_credentials(data_dir, 42, key)
        assert removed2 == ["skill-b"]
        assert delete_user_credentials(data_dir, 42, key) == []


async def test_foreign_setup_message_info():
    msg = _th._foreign_setup_message({"user_id": 42, "started_at": time.time() - 120})
    assert "42" in msg
    assert "min ago" in msg
    assert "/cancel" in msg


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
            assert "cred-test" in reply["text"]
            assert "reply_markup" in reply
            cb_values = get_callback_data_values(reply)
            assert any("clear_cred_confirm" in v for v in cb_values)
            assert any("clear_cred_cancel" in v for v in cb_values)

            # Step 2: Confirm via callback (data includes user_id)
            cb_msg = FakeMessage(chat=chat)
            query = FakeCallbackQuery("clear_cred_confirm:42:cred-test", message=cb_msg)
            update = FakeUpdate(user=user, chat=chat, callback_query=query)
            await _th.handle_clear_cred_callback(update, FakeContext())

            assert len(query.answers) == 1
            assert not query.answer_show_alert
            assert has_markup_removal(cb_msg)
            session = load_session_disk(data_dir, 12345, prov)
            assert session.get("awaiting_skill_setup") is None
            creds = load_user_credentials(data_dir, 42, key)
            assert ("cred-test" in creds) == False
            assert "cleared" in cb_msg.replies[-1]["edit_text"].lower()
    finally:
        skills_mod.CUSTOM_DIR = orig_custom_dir


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
            assert "reply_markup" in msg.replies[-1]

            # Step 2: Cancel via callback (data includes user_id)
            cb_msg = FakeMessage(chat=chat)
            query = FakeCallbackQuery("clear_cred_cancel:42", message=cb_msg)
            update = FakeUpdate(user=user, chat=chat, callback_query=query)
            await _th.handle_clear_cred_callback(update, FakeContext())

            assert len(query.answers) == 1
            assert not query.answer_show_alert
            assert has_markup_removal(cb_msg)
            assert "cancelled" in cb_msg.replies[-1]["edit_text"].lower()
            # Credentials should still exist
            creds = load_user_credentials(data_dir, 42, key)
            assert ("cred-test" in creds) == True
    finally:
        skills_mod.CUSTOM_DIR = orig_custom_dir


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

            # No args -> clear all
            msg = await send_command(_th.cmd_clear_credentials, chat, user, "/clear_credentials")
            reply = msg.replies[-1]
            assert "skill-a" in reply["text"]
            assert "skill-b" in reply["text"]
            assert "reply_markup" in reply

            # Verify clear-all button data
            cb_values = get_callback_data_values(reply)
            assert any("clear_cred_confirm_all" in v for v in cb_values)

            # Confirm (data includes user_id)
            cb_msg = FakeMessage(chat=chat)
            query = FakeCallbackQuery("clear_cred_confirm_all:42", message=cb_msg)
            update = FakeUpdate(user=user, chat=chat, callback_query=query)
            await _th.handle_clear_cred_callback(update, FakeContext())

            assert has_markup_removal(cb_msg)
            creds = load_user_credentials(data_dir, 42, key)
            assert len(creds) == 0
    finally:
        skills_mod.CUSTOM_DIR = orig_custom_dir


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
        assert "no stored credentials" in msg.replies[-1]["text"].lower()

        # All
        msg2 = await send_command(_th.cmd_clear_credentials, chat, user, "/clear_credentials")
        assert "no stored credentials" in msg2.replies[-1]["text"].lower()


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

            # Alice initiates clear -- button encodes alice's user_id (42)
            msg = await send_command(_th.cmd_clear_credentials, chat, alice, "/clear_credentials cred-test", args=["cred-test"])
            assert "reply_markup" in msg.replies[-1]

            # Bob clicks Alice's confirm button -- should be rejected
            cb_msg = FakeMessage(chat=chat)
            query = FakeCallbackQuery("clear_cred_confirm:42:cred-test", message=cb_msg)
            update = FakeUpdate(user=bob, chat=chat, callback_query=query)
            await _th.handle_clear_cred_callback(update, FakeContext())

            # Both credentials should still exist
            alice_creds = load_user_credentials(data_dir, 42, key)
            bob_creds = load_user_credentials(data_dir, 99, key)
            assert ("cred-test" in alice_creds) == True
            assert ("cred-test" in bob_creds) == True
            # No edit_text reply (only query.answer with alert)
            assert len(cb_msg.replies) == 0
            # Callback should have shown an alert to the wrong user
            assert len(query.answers) == 1
            assert query.answer_show_alert
            assert "another user" in query.answer_text.lower()
    finally:
        skills_mod.CUSTOM_DIR = orig_custom_dir


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
    assert ok == False
    assert "expect_status" in detail.lower()

    req2 = SkillRequirement(
        key="API_KEY",
        prompt="Enter key",
        help_url=None,
        validate={"method": "GET", "url": "https://example.com/health", "expect_status": None},
    )
    ok2, detail2 = await validate_credential(req2, "some-key")
    assert ok2 == False
    assert "invalid" in detail2.lower()
