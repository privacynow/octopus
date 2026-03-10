"""Handler integration tests for Codex-specific session and script behavior."""

from app.providers.base import RunContext, RunResult, compute_context_hash
from app.skills import derive_encryption_key, get_provider_config_digest, save_user_credential
from app.storage import default_session, save_session
from tests.support.handler_support import (
    FakeCallbackQuery,
    FakeChat,
    FakeContext,
    FakeMessage,
    FakeProvider,
    FakeUpdate,
    FakeUser,
    last_run_call,
    load_session_disk,
    make_config,
    setup_globals,
    fresh_data_dir,
)


async def test_codex_context_hash_invalidation():
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir, provider_name="codex")
        prov = FakeProvider("codex")
        prov.run_results = [RunResult(text="ok", provider_state_updates={"thread_id": "new-thread"})]
        setup_globals(cfg, prov)

        session = default_session("codex", {"thread_id": "old-thread", "context_hash": "stale_hash"}, "off")
        save_session(data_dir, 12345, session)

        chat = FakeChat(12345)
        msg = FakeMessage(chat=chat, text="do something")
        user = FakeUser(42)

        import app.telegram_handlers as th

        await th.handle_message(FakeUpdate(message=msg, user=user, chat=chat), FakeContext())

        assert len(prov.run_calls) == 1
        assert prov.run_calls[0]["provider_state"].get("thread_id") is None

        session = load_session_disk(data_dir, 12345, prov)
        assert session["provider_state"].get("context_hash") is not None
        assert session["provider_state"]["context_hash"] != "stale_hash"
        assert session["provider_state"]["thread_id"] == "new-thread"


async def test_codex_script_staging():
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir, provider_name="codex", default_skills=("github-integration",))
        prov = FakeProvider("codex")
        prov.run_results = [RunResult(text="ok")]
        setup_globals(cfg, prov)

        key = derive_encryption_key(cfg.telegram_token)
        save_user_credential(data_dir, 42, "github-integration", "GITHUB_TOKEN", "ghp_test", key)

        chat = FakeChat(12345)
        msg = FakeMessage(chat=chat, text="use github")
        user = FakeUser(42)

        import app.telegram_handlers as th

        await th.handle_message(FakeUpdate(message=msg, user=user, chat=chat), FakeContext())

        assert len(prov.run_calls) == 1
        ctx = prov.run_calls[0]["context"]
        assert isinstance(ctx, RunContext)

        scripts_dir = data_dir / "scripts" / "12345"
        assert scripts_dir.exists()
        assert (scripts_dir / "github-integration" / "gh-helper.sh").is_file()
        assert any(str(scripts_dir) in d for d in ctx.extra_dirs)
        assert any("uploads" in d for d in ctx.extra_dirs)
        assert "GITHUB_TOKEN" in ctx.credential_env


async def test_codex_retry_clears_thread():
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir, provider_name="codex")
        prov = FakeProvider("codex")
        prov.run_results = [RunResult(text="ok")]
        setup_globals(cfg, prov)

        current_hash = compute_context_hash("", [], {}, get_provider_config_digest([]), [])
        session = default_session("codex", {"thread_id": "thread-xyz", "context_hash": current_hash}, "off")
        session["pending_retry"] = {
            "request_user_id": 42,
            "prompt": "test",
            "image_paths": [],
            "context_hash": current_hash,
            "denials": [{"tool_name": "Write", "tool_input": {"file_path": "/tmp/x.txt"}}],
        }
        save_session(data_dir, 12345, session)

        chat = FakeChat(12345)
        cb_msg = FakeMessage(chat=chat)
        query = FakeCallbackQuery("retry_allow", message=cb_msg)
        user = FakeUser(42)

        import app.telegram_handlers as th

        update = FakeUpdate(user=user, chat=chat, callback_query=query)
        update.effective_message = cb_msg
        await th.handle_callback(update, FakeContext())

        assert len(prov.run_calls) == 1
        assert prov.run_calls[0]["provider_state"].get("thread_id") is None


async def test_codex_failed_resume_clears_thread():
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir, provider_name="codex")
        prov = FakeProvider("codex")
        setup_globals(cfg, prov)

        current_hash = compute_context_hash("", [], {}, get_provider_config_digest([]), [])
        session = default_session("codex", {"thread_id": "thread-abc", "context_hash": current_hash}, "off")
        save_session(data_dir, 12345, session)
        prov.run_results = [RunResult(text="[Codex error: thread not found]", returncode=1)]

        chat = FakeChat(12345)
        user = FakeUser(42)

        import app.telegram_handlers as th

        await th.handle_message(
            FakeUpdate(message=FakeMessage(chat=chat, text="continue working"), user=user, chat=chat),
            FakeContext(),
        )

        session = load_session_disk(data_dir, 12345, prov)
        assert session["provider_state"].get("thread_id") is None


async def test_codex_timed_out_resume_preserves_thread():
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir, provider_name="codex")
        prov = FakeProvider("codex")
        setup_globals(cfg, prov)

        current_hash = compute_context_hash("", [], {}, get_provider_config_digest([]), [])
        session = default_session("codex", {"thread_id": "thread-abc", "context_hash": current_hash}, "off")
        save_session(data_dir, 12345, session)
        prov.run_results = [RunResult(text="", timed_out=True, returncode=124)]

        chat = FakeChat(12345)
        user = FakeUser(42)

        import app.telegram_handlers as th

        await th.handle_message(
            FakeUpdate(message=FakeMessage(chat=chat, text="continue working"), user=user, chat=chat),
            FakeContext(),
        )

        session = load_session_disk(data_dir, 12345, prov)
        assert session["provider_state"].get("thread_id") == "thread-abc"


async def test_codex_new_exec_failure_preserves_no_thread():
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir, provider_name="codex")
        prov = FakeProvider("codex")
        setup_globals(cfg, prov)

        session = default_session("codex", {"thread_id": None}, "off")
        save_session(data_dir, 12345, session)
        prov.run_results = [RunResult(text="[Codex error: model overloaded]", returncode=1)]

        chat = FakeChat(12345)
        user = FakeUser(42)

        import app.telegram_handlers as th

        await th.handle_message(
            FakeUpdate(message=FakeMessage(chat=chat, text="do something"), user=user, chat=chat),
            FakeContext(),
        )

        session = load_session_disk(data_dir, 12345, prov)
        assert session["provider_state"].get("thread_id") is None


async def test_codex_boot_id_clears_stale_thread():
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir, provider_name="codex")
        prov = FakeProvider("codex")
        setup_globals(cfg, prov, boot_id="old-boot")
        session = default_session(
            "codex",
            {"thread_id": "old-thread", "boot_id": "old-boot", "context_hash": "abc"},
            "off",
        )
        save_session(data_dir, 12345, session)

        setup_globals(cfg, prov, boot_id="new-boot")
        prov.run_results = [RunResult(text="done")]

        chat = FakeChat(12345)
        user = FakeUser(42)

        import app.telegram_handlers as th

        await th.handle_message(
            FakeUpdate(message=FakeMessage(chat=chat, text="hello"), user=user, chat=chat),
            FakeContext(),
        )

        call = last_run_call(prov)
        assert call["provider_state"].get("thread_id") is None
        session = load_session_disk(data_dir, 12345, prov)
        assert session["provider_state"].get("boot_id") == "new-boot"


async def test_codex_same_boot_preserves_thread():
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir, provider_name="codex")
        prov = FakeProvider("codex")
        setup_globals(cfg, prov, boot_id="same-boot")

        session = default_session("codex", {"thread_id": "my-thread", "boot_id": "same-boot"}, "off")
        save_session(data_dir, 12345, session)
        prov.run_results = [RunResult(text="done", provider_state_updates={"thread_id": "my-thread"})]

        chat = FakeChat(12345)
        user = FakeUser(42)

        import app.telegram_handlers as th

        await th.handle_message(
            FakeUpdate(message=FakeMessage(chat=chat, text="hello"), user=user, chat=chat),
            FakeContext(),
        )

        call = last_run_call(prov)
        assert call["provider_state"].get("thread_id") == "my-thread"


async def test_scripts_dir_in_run_context():
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir, provider_name="codex", default_skills=("github-integration",))
        prov = FakeProvider("codex")
        prov.run_results = [RunResult(text="ok")]
        setup_globals(cfg, prov)

        key = derive_encryption_key(cfg.telegram_token)
        save_user_credential(data_dir, 42, "github-integration", "GITHUB_TOKEN", "ghp_test", key)

        chat = FakeChat(12345)
        user = FakeUser(42)

        import app.telegram_handlers as th

        await th.handle_message(
            FakeUpdate(message=FakeMessage(chat=chat, text="use github"), user=user, chat=chat),
            FakeContext(),
        )

        assert len(prov.run_calls) == 1
        ctx = prov.run_calls[0]["context"]
        scripts_path = data_dir / "scripts" / "12345"
        assert scripts_path.exists()
        assert any(str(scripts_path) in d for d in ctx.extra_dirs)
        assert any("uploads" in d for d in ctx.extra_dirs)


async def test_script_staging_removes_stale():
    from app.skills import stage_codex_scripts

    with fresh_data_dir() as data_dir:

        result = stage_codex_scripts(data_dir, 99999, ["github-integration"])
        assert result is not None
        staged_dir = result / "github-integration"
        assert (staged_dir / "gh-helper.sh").is_file()

        stale_file = staged_dir / "old-script.sh"
        stale_file.write_text("#!/bin/bash\necho stale")

        result2 = stage_codex_scripts(data_dir, 99999, ["github-integration"])
        staged_dir2 = result2 / "github-integration"
        assert (staged_dir2 / "gh-helper.sh").is_file()
        assert not (staged_dir2 / "old-script.sh").exists()


async def test_context_hash_role_sensitivity():
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir, provider_name="codex")
        prov = FakeProvider("codex")
        prov.run_results = [
            RunResult(text="ok1", provider_state_updates={"thread_id": "thread-1"}),
            RunResult(text="ok2", provider_state_updates={"thread_id": "thread-2"}),
        ]
        setup_globals(cfg, prov)

        import app.telegram_handlers as th

        chat = FakeChat(12345)
        user = FakeUser(42)

        await th.handle_message(FakeUpdate(message=FakeMessage(chat=chat, text="hello"), user=user, chat=chat), FakeContext())
        assert len(prov.run_calls) == 1

        session = load_session_disk(data_dir, 12345, prov)
        hash1 = session["provider_state"].get("context_hash")
        assert hash1 is not None

        await th.cmd_role(
            FakeUpdate(message=FakeMessage(chat=chat, text="/role security expert"), user=user, chat=chat),
            FakeContext(args=["security", "expert"]),
        )

        await th.handle_message(
            FakeUpdate(message=FakeMessage(chat=chat, text="check security"), user=user, chat=chat),
            FakeContext(),
        )

        assert len(prov.run_calls) == 2
        assert prov.run_calls[1]["provider_state"].get("thread_id") is None

        session = load_session_disk(data_dir, 12345, prov)
        hash2 = session["provider_state"].get("context_hash")
        assert hash1 != hash2
