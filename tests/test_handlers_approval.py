"""Handler integration tests for approval and pending-request flows."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.providers.base import PreflightContext, RunResult
from app.storage import default_session, save_session
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
    load_session_disk,
    make_config,
    setup_globals,
    test_data_dir,
)

checks = Checks()
run_test = checks.add_test


async def test_approval_flow():
    with test_data_dir() as data_dir:
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

        checks.check("preflight called", len(prov.preflight_calls), 1)
        checks.check("run NOT called yet", len(prov.run_calls), 0)

        pf_ctx = prov.preflight_calls[0]["context"]
        checks.check_true("preflight context is PreflightContext", isinstance(pf_ctx, PreflightContext))
        checks.check_true(
            "preflight context has upload dir",
            any("uploads" in d for d in pf_ctx.extra_dirs),
        )
        checks.check_true("preflight prompt is non-empty", len(prov.preflight_calls[0]["prompt"]) > 0)

        preflight_texts = " ".join(r.get("text", "") for r in msg.replies)
        checks.check_in("preflight plan label", "Preflight approval plan", preflight_texts)
        chat_msgs = " ".join(m.get("text", "") for m in chat.sent_messages)
        checks.check_in("preflight approval prompt", "Approve this preflight plan?", chat_msgs)

        # Verify approval buttons have correct callback_data
        approval_msg = chat.sent_messages[-1]
        cb_values = get_callback_data_values(approval_msg)
        checks.check_in("approve button present", "approval_approve", cb_values)
        checks.check_in("reject button present", "approval_reject", cb_values)

        session = load_session_disk(data_dir, 12345, prov)
        checks.check_true("pending_request saved", session.get("pending_request") is not None)

        cb_msg = FakeMessage(chat=chat)
        query = FakeCallbackQuery("approval_approve", message=cb_msg)
        cb_update = FakeUpdate(user=user, chat=chat, callback_query=query)
        cb_update.effective_message = cb_msg

        await th.handle_callback(cb_update, FakeContext())

        checks.check("approve: single answer", len(query.answers), 1)
        checks.check_false("approve: not an alert", query.answer_show_alert)
        checks.check_true("approve: buttons removed", has_markup_removal(cb_msg))
        checks.check("run called after approval", len(prov.run_calls), 1)
        approved_ctx = prov.run_calls[0]["context"]
        checks.check_true("approved run skips permissions", approved_ctx.skip_permissions is True)
        session = load_session_disk(data_dir, 12345, prov)
        checks.check("pending_request cleared", session.get("pending_request"), None)


run_test("approval flow", test_approval_flow())


async def test_approval_wording():
    with test_data_dir() as data_dir:
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
        checks.check_in("status says preflight", "Preflight approval mode is on", status_texts)
        checks.check_in("status shows instance default", "instance default", status_texts)

        set_msg = FakeMessage(chat=chat, text="/approval off")
        set_update = FakeUpdate(message=set_msg, user=user, chat=chat)
        await th.cmd_approval(set_update, FakeContext(["off"]))

        set_texts = " ".join(r.get("text", "") for r in set_msg.replies)
        checks.check_in(
            "set says preflight",
            "Preflight approval mode set to off for this chat.",
            set_texts,
        )

        session_msg = FakeMessage(chat=chat, text="/session")
        session_update = FakeUpdate(message=session_msg, user=user, chat=chat)
        await th.cmd_session(session_update, FakeContext())

        session_texts = " ".join(r.get("text", "") for r in session_msg.replies)
        checks.check_in("session says preflight", "Preflight approval mode", session_texts)
        checks.check_in("session shows chat override", "chat override", session_texts)


run_test("approval wording", test_approval_wording())


async def test_denial_retry_flow():
    with test_data_dir() as data_dir:
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

        checks.check("run called once (first attempt)", len(prov.run_calls), 1)
        reply_texts = " ".join(r.get("text", "") for r in msg.replies)
        checks.check_in("partial reply still sent", "partial", reply_texts)
        chat_msgs = " ".join(m.get("text", "") for m in chat.sent_messages)
        checks.check_in("runtime permission label", "Permission needed", chat_msgs)
        checks.check_in("retry prompt", "Grant access and retry from the beginning", chat_msgs)

        # Verify retry buttons have correct callback_data
        retry_msg = chat.sent_messages[-1]
        retry_cbs = get_callback_data_values(retry_msg)
        checks.check_in("retry_allow button", "retry_allow", retry_cbs)
        checks.check_in("retry_skip button", "retry_skip", retry_cbs)

        session = load_session_disk(data_dir, 12345, prov)
        checks.check_true("pending_request saved", session.get("pending_request") is not None)
        checks.check_true("pending has denials", session["pending_request"].get("denials") is not None)

        cb_msg = FakeMessage(chat=chat)
        query = FakeCallbackQuery("retry_allow", message=cb_msg)
        cb_update = FakeUpdate(user=user, chat=chat, callback_query=query)
        cb_update.effective_message = cb_msg

        await th.handle_callback(cb_update, FakeContext())

        checks.check_true("retry: buttons removed", has_markup_removal(cb_msg))
        checks.check("run called twice (after retry)", len(prov.run_calls), 2)

        retry_ctx = prov.run_calls[1]["context"]
        checks.check_true("retry has extra_dirs", len(retry_ctx.extra_dirs) >= 2)
        extra_dirs_str = " ".join(retry_ctx.extra_dirs)
        checks.check_in("denial dir /opt/app in extra_dirs", "/opt/app", extra_dirs_str)
        checks.check_true("retry skips permissions", retry_ctx.skip_permissions is True)

        session = load_session_disk(data_dir, 12345, prov)
        checks.check("pending_request cleared after retry", session.get("pending_request"), None)


run_test("denial/retry flow", test_denial_retry_flow())


async def test_retry_skip():
    with test_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        session = default_session("claude", prov.new_provider_state(), "off")
        session["pending_request"] = {
            "request_user_id": 42,
            "prompt": "test",
            "image_paths": [],
            "attachment_dicts": [],
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

        checks.check_true("skip: buttons removed", has_markup_removal(cb_msg))
        session = load_session_disk(data_dir, 12345, prov)
        checks.check("pending cleared", session.get("pending_request"), None)
        checks.check("run not called", len(prov.run_calls), 0)


run_test("retry skip", test_retry_skip())


async def test_stale_context_hash():
    with test_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        session = default_session("claude", prov.new_provider_state(), "off")
        session["pending_request"] = {
            "request_user_id": 42,
            "prompt": "test",
            "image_paths": [],
            "attachment_dicts": [],
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

        checks.check("run NOT called (stale hash)", len(prov.run_calls), 0)
        checks.check_true("stale: buttons removed", has_markup_removal(cb_msg))

        session = load_session_disk(data_dir, 12345, prov)
        checks.check("pending_request cleared", session.get("pending_request"), None)

        reply_texts = " ".join(r.get("edit_text", r.get("text", "")) for r in cb_msg.replies)
        checks.check_in("context changed message", "Context changed", reply_texts)


run_test("stale context hash", test_stale_context_hash())


async def test_cross_user_approval():
    with test_data_dir() as data_dir:
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

        checks.check("preflight called", len(prov.preflight_calls), 1)

        session = load_session_disk(data_dir, 12345, prov)
        pending = session.get("pending_request")
        checks.check_true("pending exists", pending is not None)
        checks.check("pending has alice's user_id", pending["request_user_id"], 100)

        cb_msg = FakeMessage(chat=chat)
        query = FakeCallbackQuery("approval_approve", message=cb_msg)
        cb_update = FakeUpdate(user=bob, chat=chat, callback_query=query)
        cb_update.effective_message = cb_msg
        await th.handle_callback(cb_update, FakeContext())

        checks.check("run called after bob approves", len(prov.run_calls), 1)

        session = load_session_disk(data_dir, 12345, prov)
        checks.check("pending cleared after approval", session.get("pending_request"), None)


run_test("cross-user approval", test_cross_user_approval())


async def test_approval_preflight_timeout():
    with test_data_dir() as data_dir:
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

        checks.check("preflight called", len(prov.preflight_calls), 1)
        checks.check("run NOT called", len(prov.run_calls), 0)

        session = load_session_disk(data_dir, 12345, prov)
        checks.check("no pending_request on timeout", session.get("pending_request"), None)

        chat_msgs = " ".join(m.get("text", "") for m in chat.sent_messages)
        checks.check_not_in("no approval prompt on timeout", "Approve", chat_msgs)


run_test("approval preflight timeout", test_approval_preflight_timeout())


async def test_approval_preflight_error():
    with test_data_dir() as data_dir:
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

        checks.check("preflight called", len(prov.preflight_calls), 1)
        checks.check("run NOT called", len(prov.run_calls), 0)

        session = load_session_disk(data_dir, 12345, prov)
        checks.check("no pending_request on error", session.get("pending_request"), None)


run_test("approval preflight error", test_approval_preflight_error())


async def test_duplicate_pending_blocked():
    with test_data_dir() as data_dir:
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

        checks.check("first preflight called", len(prov.preflight_calls), 1)

        msg2 = FakeMessage(chat=chat, text="second request")
        update2 = FakeUpdate(message=msg2, user=user, chat=chat)
        await th.handle_message(update2, FakeContext())

        session = load_session_disk(data_dir, 12345, prov)
        checks.check_true("pending_request still exists", session.get("pending_request") is not None)


run_test("duplicate pending blocked", test_duplicate_pending_blocked())


async def test_denial_preserves_request_user_id():
    with test_data_dir() as data_dir:
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
        pending = session.get("pending_request")
        checks.check_true("pending exists", pending is not None)
        checks.check("request_user_id is alice", pending["request_user_id"], 100)
        checks.check_true("denials preserved", len(pending.get("denials", [])) > 0)


run_test("denial preserves request_user_id", test_denial_preserves_request_user_id())


async def test_cancel_pending():
    with test_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        import app.telegram_handlers as th

        chat = FakeChat(12345)
        user = FakeUser(42)

        session = default_session(prov.name, prov.new_provider_state(), "off")
        session["pending_request"] = {
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
        checks.check_in("cancel pending reply", "Pending request cancelled", reply)

        session = load_session_disk(data_dir, 12345, prov)
        checks.check("pending cleared", session.get("pending_request"), None)


run_test("/cancel clears pending", test_cancel_pending())


async def test_stale_pending_ttl():
    with test_data_dir() as data_dir:
        cfg = make_config(data_dir, timeout_seconds=300)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        import app.telegram_handlers as th

        chat = FakeChat(12345)
        user = FakeUser(42)

        session = default_session(prov.name, prov.new_provider_state(), "on")
        session["pending_request"] = {
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
        checks.check_in("expired msg", "expired", reply.lower())
        checks.check("provider not called", len(prov.run_calls), 0)


run_test("stale pending TTL", test_stale_pending_ttl())


if __name__ == "__main__":
    checks.run_async_and_exit()
