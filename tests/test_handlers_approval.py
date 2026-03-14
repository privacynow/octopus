"""Handler integration tests for approval and pending-request flows."""

import time

from app.providers.base import PreflightContext, RunResult
from app.storage import default_session, save_session
from tests.support.handler_support import (
    FakeCallbackQuery,
    FakeChat,
    FakeContext,
    FakeMessage,
    FakeProvider,
    FakeUpdate,
    FakeUser,
    fresh_data_dir,
    fresh_env,
    get_callback_data_values,
    has_markup_removal,
    last_reply,
    load_session_disk,
    make_config,
    send_callback,
    send_command,
    send_text,
    setup_globals,
)


async def test_approval_flow():
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir, approval_mode="on")
        prov = FakeProvider("claude")
        prov.preflight_results = [RunResult(text="Plan: read files")]
        prov.run_results = [RunResult(text="Done reading")]
        setup_globals(cfg, prov)

        chat = FakeChat(12345)
        msg = FakeMessage(chat=chat, text="read my files")
        user = FakeUser(42)
        update = FakeUpdate(message=msg, user=user, chat=chat)

        import app.telegram_handlers as th

        await th.handle_message(update, FakeContext())

        assert len(prov.preflight_calls) == 1
        assert len(prov.run_calls) == 0

        pf_ctx = prov.preflight_calls[0]["context"]
        assert isinstance(pf_ctx, PreflightContext)
        assert any("uploads" in d for d in pf_ctx.extra_dirs)
        assert len(prov.preflight_calls[0]["prompt"]) > 0

        preflight_texts = " ".join(r.get("text", "") for r in msg.replies)
        assert "Approval plan" in preflight_texts
        chat_msgs = " ".join(m.get("text", "") for m in chat.sent_messages)
        assert "Approve this plan?" in chat_msgs

        # Verify approval buttons have correct callback_data
        approval_msg = chat.sent_messages[-1]
        cb_values = get_callback_data_values(approval_msg)
        assert "approval_approve" in cb_values
        assert "approval_reject" in cb_values

        session = load_session_disk(data_dir, 12345, prov)
        assert session.get("pending_approval") is not None

        cb_msg = FakeMessage(chat=chat)
        query = FakeCallbackQuery("approval_approve", message=cb_msg)
        cb_update = FakeUpdate(user=user, chat=chat, callback_query=query)
        cb_update.effective_message = cb_msg

        await th.handle_callback(cb_update, FakeContext())

        assert len(query.answers) == 1
        assert not query.answer_show_alert
        assert has_markup_removal(cb_msg)
        assert len(prov.run_calls) == 1
        approved_ctx = prov.run_calls[0]["context"]
        assert approved_ctx.skip_permissions is True
        session = load_session_disk(data_dir, 12345, prov)
        assert session.get("pending_approval") is None and session.get("pending_retry") is None


async def test_approval_wording():
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir, approval_mode="on")
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        import app.telegram_handlers as th

        chat = FakeChat(12345)
        user = FakeUser(42)

        status_msg = FakeMessage(chat=chat, text="/approval status")
        status_update = FakeUpdate(message=status_msg, user=user, chat=chat)
        await th.cmd_approval(status_update, FakeContext(["status"]))

        status_texts = " ".join(r.get("text", "") for r in status_msg.replies)
        assert "approval mode" in status_texts.lower() and "on" in status_texts
        assert "instance default" in status_texts

        set_msg = FakeMessage(chat=chat, text="/approval off")
        set_update = FakeUpdate(message=set_msg, user=user, chat=chat)
        await th.cmd_approval(set_update, FakeContext(["off"]))

        set_texts = " ".join(r.get("text", "") for r in set_msg.replies)
        assert "Approval mode set to off for this chat." in set_texts

        session_msg = FakeMessage(chat=chat, text="/session")
        session_update = FakeUpdate(message=session_msg, user=user, chat=chat)
        await th.cmd_session(session_update, FakeContext())

        session_texts = " ".join(r.get("text", "") for r in session_msg.replies)
        assert "Approval mode" in session_texts
        assert "chat override" in session_texts


async def test_denial_retry_flow():
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        prov.run_results = [
            RunResult(
                text="partial",
                denials=[{"tool_name": "Write", "tool_input": {"file_path": "/opt/app/config.yaml"}}],
            ),
            RunResult(text="Success after retry"),
        ]
        setup_globals(cfg, prov)

        chat = FakeChat(12345)
        msg = FakeMessage(chat=chat, text="edit config")
        user = FakeUser(42)
        update = FakeUpdate(message=msg, user=user, chat=chat)

        import app.telegram_handlers as th

        await th.handle_message(update, FakeContext())

        assert len(prov.run_calls) == 1
        reply_texts = " ".join(r.get("text", "") for r in msg.replies)
        assert "partial" in reply_texts
        chat_msgs = " ".join(m.get("text", "") for m in chat.sent_messages)
        assert "Permission needed" in chat_msgs
        assert "Grant access" in chat_msgs and ("retry" in chat_msgs or "again" in chat_msgs)

        # Verify retry buttons have correct callback_data
        retry_msg = chat.sent_messages[-1]
        retry_cbs = get_callback_data_values(retry_msg)
        assert "retry_allow" in retry_cbs
        assert "retry_skip" in retry_cbs

        session = load_session_disk(data_dir, 12345, prov)
        assert session.get("pending_retry") is not None
        assert session["pending_retry"].get("denials") is not None

        cb_msg = FakeMessage(chat=chat)
        query = FakeCallbackQuery("retry_allow", message=cb_msg)
        cb_update = FakeUpdate(user=user, chat=chat, callback_query=query)
        cb_update.effective_message = cb_msg

        await th.handle_callback(cb_update, FakeContext())

        assert has_markup_removal(cb_msg)
        assert len(prov.run_calls) == 2

        retry_ctx = prov.run_calls[1]["context"]
        assert len(retry_ctx.extra_dirs) >= 2
        extra_dirs_str = " ".join(retry_ctx.extra_dirs)
        assert "/opt/app" in extra_dirs_str
        assert retry_ctx.skip_permissions is True

        session = load_session_disk(data_dir, 12345, prov)
        assert session.get("pending_approval") is None and session.get("pending_retry") is None


async def test_retry_skip():
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        session = default_session("claude", prov.new_provider_state(), "off")
        session["pending_retry"] = {
            "request_user_id": 42,
            "prompt": "test",
            "image_paths": [],
            "context_hash": "somehash",
            "denials": [{"tool_name": "X"}],
        }
        save_session(data_dir, 12345, session)

        chat = FakeChat(12345)
        cb_msg = FakeMessage(chat=chat)
        query = FakeCallbackQuery("retry_skip", message=cb_msg)
        user = FakeUser(42)
        cb_update = FakeUpdate(user=user, chat=chat, callback_query=query)
        cb_update.effective_message = cb_msg

        import app.telegram_handlers as th

        await th.handle_callback(cb_update, FakeContext())

        assert has_markup_removal(cb_msg)
        session = load_session_disk(data_dir, 12345, prov)
        assert session.get("pending_approval") is None and session.get("pending_retry") is None
        assert len(prov.run_calls) == 0

        edit_texts = [r.get("edit_text", "") for r in cb_msg.replies if r.get("edit_text")]
        from app.user_messages import retry_skip_confirmation
        assert any(retry_skip_confirmation() in t for t in edit_texts)


async def test_retry_allow_no_pending():
    """retry_allow when no pending_retry shows centralized no-retry wording."""
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        session = default_session("claude", prov.new_provider_state(), "off")
        assert session.get("pending_retry") is None
        save_session(data_dir, 12345, session)

        chat = FakeChat(12345)
        cb_msg = FakeMessage(chat=chat)
        query = FakeCallbackQuery("retry_allow", message=cb_msg)
        user = FakeUser(42)
        cb_update = FakeUpdate(user=user, chat=chat, callback_query=query)
        cb_update.effective_message = cb_msg

        import app.telegram_handlers as th

        await th.handle_callback(cb_update, FakeContext())

        edit_texts = [r.get("edit_text", "") for r in cb_msg.replies if r.get("edit_text")]
        from app.user_messages import retry_nothing_pending
        assert any(retry_nothing_pending() in t for t in edit_texts)


async def test_stale_context_hash():
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        session = default_session("claude", prov.new_provider_state(), "off")
        session["pending_retry"] = {
            "request_user_id": 42,
            "prompt": "test",
            "image_paths": [],
            "context_hash": "definitely_stale_hash",
            "denials": [{"tool_name": "X"}],
        }
        save_session(data_dir, 12345, session)

        chat = FakeChat(12345)
        cb_msg = FakeMessage(chat=chat)
        query = FakeCallbackQuery("retry_allow", message=cb_msg)
        user = FakeUser(42)
        cb_update = FakeUpdate(user=user, chat=chat, callback_query=query)
        cb_update.effective_message = cb_msg

        import app.telegram_handlers as th

        await th.handle_callback(cb_update, FakeContext())

        assert len(prov.run_calls) == 0
        assert has_markup_removal(cb_msg)

        session = load_session_disk(data_dir, 12345, prov)
        assert session.get("pending_approval") is None and session.get("pending_retry") is None

        reply_texts = " ".join(r.get("edit_text", r.get("text", "")) for r in cb_msg.replies)
        assert "changed" in reply_texts and "request" in reply_texts
        assert "context" in reply_texts


async def test_cross_user_approval():
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir, approval_mode="on")
        prov = FakeProvider("claude")
        prov.preflight_results = [RunResult(text="Plan: do something")]
        prov.run_results = [RunResult(text="Done")]
        setup_globals(cfg, prov)

        import app.telegram_handlers as th

        chat = FakeChat(12345)
        alice = FakeUser(uid=100, username="alice")
        bob = FakeUser(uid=200, username="bob")

        msg_alice = FakeMessage(chat=chat, text="deploy to production")
        update_alice = FakeUpdate(message=msg_alice, user=alice, chat=chat)
        await th.handle_message(update_alice, FakeContext())

        assert len(prov.preflight_calls) == 1

        session = load_session_disk(data_dir, 12345, prov)
        pending = session.get("pending_approval")
        assert pending is not None
        assert pending["request_user_id"] == 100

        cb_msg = FakeMessage(chat=chat)
        query = FakeCallbackQuery("approval_approve", message=cb_msg)
        cb_update = FakeUpdate(user=bob, chat=chat, callback_query=query)
        cb_update.effective_message = cb_msg
        await th.handle_callback(cb_update, FakeContext())

        assert len(prov.run_calls) == 1

        session = load_session_disk(data_dir, 12345, prov)
        assert session.get("pending_approval") is None and session.get("pending_retry") is None


async def test_approval_preflight_timeout():
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir, approval_mode="on")
        prov = FakeProvider("claude")
        prov.preflight_results = [RunResult(text="", timed_out=True)]
        setup_globals(cfg, prov)

        chat = FakeChat(12345)
        msg = FakeMessage(chat=chat, text="do something")
        user = FakeUser(42)
        update = FakeUpdate(message=msg, user=user, chat=chat)

        import app.telegram_handlers as th

        await th.handle_message(update, FakeContext())

        assert len(prov.preflight_calls) == 1
        assert len(prov.run_calls) == 0

        session = load_session_disk(data_dir, 12345, prov)
        assert session.get("pending_approval") is None and session.get("pending_retry") is None

        chat_msgs = " ".join(m.get("text", "") for m in chat.sent_messages)
        assert "Approve" not in chat_msgs


async def test_approval_preflight_error():
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir, approval_mode="on")
        prov = FakeProvider("claude")
        prov.preflight_results = [RunResult(text="Preflight error", returncode=1)]
        setup_globals(cfg, prov)

        chat = FakeChat(12345)
        msg = FakeMessage(chat=chat, text="do something")
        user = FakeUser(42)
        update = FakeUpdate(message=msg, user=user, chat=chat)

        import app.telegram_handlers as th

        await th.handle_message(update, FakeContext())

        assert len(prov.preflight_calls) == 1
        assert len(prov.run_calls) == 0

        session = load_session_disk(data_dir, 12345, prov)
        assert session.get("pending_approval") is None and session.get("pending_retry") is None


async def test_duplicate_pending_blocked():
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir, approval_mode="on")
        prov = FakeProvider("claude")
        prov.preflight_results = [RunResult(text="Plan 1"), RunResult(text="Plan 2")]
        setup_globals(cfg, prov)

        import app.telegram_handlers as th

        chat = FakeChat(12345)
        user = FakeUser(42)

        msg1 = FakeMessage(chat=chat, text="first request")
        update1 = FakeUpdate(message=msg1, user=user, chat=chat)
        await th.handle_message(update1, FakeContext())

        assert len(prov.preflight_calls) == 1

        msg2 = FakeMessage(chat=chat, text="second request")
        update2 = FakeUpdate(message=msg2, user=user, chat=chat)
        await th.handle_message(update2, FakeContext())

        session = load_session_disk(data_dir, 12345, prov)
        assert (session.get("pending_approval") or session.get("pending_retry")) is not None


async def test_denial_preserves_request_user_id():
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        prov.run_results = [
            RunResult(
                text="partial",
                denials=[{"tool_name": "Read", "tool_input": {"file_path": "/etc/secrets"}}],
            )
        ]
        setup_globals(cfg, prov)

        import app.telegram_handlers as th

        chat = FakeChat(12345)
        alice = FakeUser(uid=100, username="alice")
        msg = FakeMessage(chat=chat, text="read secrets")
        update = FakeUpdate(message=msg, user=alice, chat=chat)

        await th.handle_message(update, FakeContext())

        session = load_session_disk(data_dir, 12345, prov)
        pending = session.get("pending_retry")
        assert pending is not None
        assert pending["request_user_id"] == 100
        assert len(pending.get("denials", [])) > 0


async def test_cancel_pending():
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        import app.telegram_handlers as th

        chat = FakeChat(12345)
        user = FakeUser(42)

        session = default_session(prov.name, prov.new_provider_state(), "off")
        session["pending_approval"] = {
            "request_user_id": 42,
            "prompt": "test",
            "image_paths": [],
            "attachment_dicts": [],
            "context_hash": "abc",
            "created_at": time.time(),
        }
        save_session(data_dir, 12345, session)

        msg = FakeMessage(chat=chat, text="/cancel")
        update = FakeUpdate(message=msg, user=user, chat=chat)
        await th.cmd_cancel(update, FakeContext())

        reply = msg.replies[0]["text"]
        from app.user_messages import cancel_pending_request
        assert reply == cancel_pending_request()

        session = load_session_disk(data_dir, 12345, prov)
        assert session.get("pending_approval") is None and session.get("pending_retry") is None


async def test_cancel_nothing_to_cancel():
    """Bucket C: /cancel with no pending shows centralized nothing_to_cancel message."""
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        import app.telegram_handlers as th
        from app.user_messages import nothing_to_cancel

        chat = FakeChat(12345)
        user = FakeUser(42)
        session = default_session(prov.name, prov.new_provider_state(), "off")
        assert not session.get("pending_approval") and not session.get("pending_retry")
        save_session(data_dir, 12345, session)

        msg = FakeMessage(chat=chat, text="/cancel")
        await th.cmd_cancel(FakeUpdate(message=msg, user=user, chat=chat), FakeContext())

        assert len(msg.replies) == 1
        assert msg.replies[0]["text"] == nothing_to_cancel()


async def test_stale_pending_ttl():
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir, timeout_seconds=300)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        import app.telegram_handlers as th

        chat = FakeChat(12345)
        user = FakeUser(42)

        session = default_session(prov.name, prov.new_provider_state(), "on")
        session["pending_approval"] = {
            "request_user_id": 42,
            "prompt": "old request",
            "image_paths": [],
            "attachment_dicts": [],
            "context_hash": "",
            "created_at": time.time() - 7200,
        }
        save_session(data_dir, 12345, session)

        msg = FakeMessage(chat=chat, text="")
        await th.approve_pending(12345, msg)

        reply = " ".join(r.get("text", "") for r in msg.replies)
        assert "expired" in reply.lower()
        assert len(prov.run_calls) == 0


async def test_approval_with_project_active():
    """Approval flow must succeed when a project is active.

    Regression test: the stored context_hash (from request_approval) must match
    what _current_context_hash computes at approval time. Both must include
    working_dir from the project.
    """
    import tempfile
    with fresh_data_dir() as data_dir:
        project_dir = tempfile.mkdtemp()
        cfg = make_config(
            data_dir, approval_mode="on",
            projects=(("frontend", project_dir, ()),),
        )
        prov = FakeProvider("claude")
        prov.preflight_results = [RunResult(text="Plan: review frontend")]
        prov.run_results = [RunResult(text="Done")]
        setup_globals(cfg, prov)

        import app.telegram_handlers as th

        chat = FakeChat(12345)
        user = FakeUser(42)

        # Bind project
        await th.cmd_project(
            FakeUpdate(message=FakeMessage(chat=chat, text="/project use frontend"), user=user, chat=chat),
            FakeContext(["use", "frontend"]),
        )
        session = load_session_disk(data_dir, 12345, prov)
        assert session.get("project_id") == "frontend"

        # Send message — triggers preflight
        msg = FakeMessage(chat=chat, text="review the code")
        await th.handle_message(FakeUpdate(message=msg, user=user, chat=chat), FakeContext())
        assert len(prov.preflight_calls) == 1
        assert len(prov.run_calls) == 0

        session = load_session_disk(data_dir, 12345, prov)
        assert session.get("pending_approval") is not None

        # Approve — this must NOT say "Context changed"
        cb_msg = FakeMessage(chat=chat)
        query = FakeCallbackQuery("approval_approve", message=cb_msg)
        cb_update = FakeUpdate(user=user, chat=chat, callback_query=query)
        cb_update.effective_message = cb_msg
        await th.handle_callback(cb_update, FakeContext())

        assert len(prov.run_calls) == 1, (
            "Approval should have executed the request, not rejected it as stale"
        )
        reply_texts = " ".join(
            r.get("edit_text", r.get("text", "")) for r in cb_msg.replies
        )
        assert "Context changed" not in reply_texts

        session = load_session_disk(data_dir, 12345, prov)
        assert session.get("pending_approval") is None and session.get("pending_retry") is None


async def test_retry_with_project_active():
    """Denial retry flow must succeed when a project is active.

    Same hash consistency check as approval: the context_hash stored when
    denials are recorded must match _current_context_hash at retry time.
    """
    import tempfile
    with fresh_data_dir() as data_dir:
        project_dir = tempfile.mkdtemp()
        cfg = make_config(
            data_dir,
            projects=(("backend", project_dir, ()),),
        )
        prov = FakeProvider("claude")
        prov.run_results = [
            RunResult(
                text="partial",
                denials=[{"tool_name": "Write", "tool_input": {"file_path": "/opt/app/config.yaml"}}],
            ),
            RunResult(text="Success after retry"),
        ]
        setup_globals(cfg, prov)

        import app.telegram_handlers as th

        chat = FakeChat(12345)
        user = FakeUser(42)

        # Bind project
        await th.cmd_project(
            FakeUpdate(message=FakeMessage(chat=chat, text="/project use backend"), user=user, chat=chat),
            FakeContext(["use", "backend"]),
        )

        # Send message — gets denied
        msg = FakeMessage(chat=chat, text="edit config")
        await th.handle_message(FakeUpdate(message=msg, user=user, chat=chat), FakeContext())
        assert len(prov.run_calls) == 1

        session = load_session_disk(data_dir, 12345, prov)
        assert session.get("pending_retry") is not None

        # Retry — must NOT say "Context changed"
        cb_msg = FakeMessage(chat=chat)
        query = FakeCallbackQuery("retry_allow", message=cb_msg)
        cb_update = FakeUpdate(user=user, chat=chat, callback_query=query)
        cb_update.effective_message = cb_msg
        await th.handle_callback(cb_update, FakeContext())

        assert len(prov.run_calls) == 2, (
            "Retry should have executed, not rejected as stale"
        )
        reply_texts = " ".join(
            r.get("edit_text", r.get("text", "")) for r in cb_msg.replies
        )
        assert "Context changed" not in reply_texts


# -- Approval edge cases (from test_edge_callbacks.py, test_edge_sessions.py) --


async def test_approval_after_session_reset():
    """Approve callback after /new should not execute stale request."""
    import app.telegram_handlers as th

    with fresh_env(config_overrides={"approval_mode": "on"}) as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")
        prov.preflight_results = [RunResult(text="plan: read stuff")]

        await send_text(chat, user, "hello")
        assert len(prov.preflight_calls) == 1

        # Reset session
        await send_command(th.cmd_new, chat, user, "/new")

        # Try to approve the old pending — should be gone
        query, _ = await send_callback(th.handle_callback, chat, user, "approval_approve")
        assert len(prov.run_calls) == 0
        assert query.answered


async def test_retry_callback_without_pending():
    """Retry callback when no pending request should be harmless."""
    with fresh_env() as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")

        import app.telegram_handlers as th
        query, _ = await send_callback(th.handle_callback, chat, user, "retry_approve:/tmp/dir")
        assert query.answered
        assert len(prov.run_calls) == 0


async def test_role_change_invalidates_pending_approval():
    """Changing role while approval is pending must invalidate it."""
    import app.telegram_handlers as th

    with fresh_env(config_overrides={"approval_mode": "on"}) as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")
        prov.preflight_results = [RunResult(text="plan: do something")]
        prov.run_results = [RunResult(text="done")]

        await send_text(chat, user, "hello")
        session = load_session_disk(data_dir, 1001, prov)
        assert session.get("pending_approval") is not None

        # Change role -- must invalidate pending
        await send_command(th.cmd_role, chat, user, "/role", args=["Python", "expert"])
        session = load_session_disk(data_dir, 1001, prov)
        assert session.get("role") == "Python expert"

        # Approve should fail -- context changed
        query, _ = await send_callback(th.handle_callback, chat, user, "approval_approve")
        assert len(prov.run_calls) == 0, "Stale approval must not execute"
