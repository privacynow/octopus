"""Edge case tests: callback interactions (double-click, cross-user, after reset)."""

import app.telegram_handlers as th
from app.providers.base import RunResult
from tests.support.handler_support import (
    FakeChat,
    FakeUser,
    fresh_env,
    last_reply,
    load_session_disk,
    send_callback,
    send_command,
    send_text,
)


async def test_approval_double_click():
    """Clicking Approve twice should not execute twice."""
    with fresh_env(config_overrides={"approval_mode": "on"}) as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")
        prov.preflight_results = [RunResult(text="plan: read stuff")]
        prov.run_results = [
            RunResult(text="done", provider_state_updates={"started": True}),
            RunResult(text="done again", provider_state_updates={"started": True}),
        ]

        # Send message — triggers preflight
        await send_text(chat, user, "hello world")
        assert len(prov.preflight_calls) == 1

        # First approve
        query1, _ = await send_callback(th.handle_callback, chat, user, "approval_approve")
        assert len(prov.run_calls) == 1

        # Second approve — pending should be gone
        query2, _ = await send_callback(th.handle_callback, chat, user, "approval_approve")
        # Should NOT have made a second run call
        assert len(prov.run_calls) == 1
        # Second click should get an answer (stale/no pending)
        assert query2.answered


async def test_approval_after_session_reset():
    """Approve callback after /new should not execute stale request."""
    with fresh_env(config_overrides={"approval_mode": "on"}) as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")
        prov.preflight_results = [RunResult(text="plan: read stuff")]

        # Send message — creates pending request
        await send_text(chat, user, "hello")
        assert len(prov.preflight_calls) == 1

        # Reset session
        await send_command(th.cmd_new, chat, user, "/new")

        # Try to approve the old pending — should be gone
        query, _ = await send_callback(th.handle_callback, chat, user, "approval_approve")
        assert len(prov.run_calls) == 0  # No execution
        assert query.answered


async def test_cross_user_can_approve_in_shared_chat():
    """Any allowed user in the chat can approve a pending request."""
    with fresh_env(config_overrides={"approval_mode": "on"}) as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")
        other_user = FakeUser(uid=99, username="otheruser")
        prov.preflight_results = [RunResult(text="plan: read stuff")]
        prov.run_results = [RunResult(text="done", provider_state_updates={"started": True})]

        # User sends message
        await send_text(chat, user, "hello")

        # Other user approves — allowed in shared chat
        query, _ = await send_callback(th.handle_callback, chat, other_user, "approval_approve")
        assert len(prov.run_calls) == 1  # Execution happened
        # Pending should be cleared
        session = load_session_disk(data_dir, 1001, prov)
        assert session.get("pending_approval") is None and session.get("pending_retry") is None


async def test_retry_callback_without_pending():
    """Retry callback when no pending request should be harmless."""
    with fresh_env() as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")

        query, _ = await send_callback(th.handle_callback, chat, user, "retry_approve:/tmp/dir")
        assert query.answered
        assert len(prov.run_calls) == 0
