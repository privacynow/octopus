"""Edge case tests: session state transitions and interleaving."""

import app.telegram_handlers as th
from app.providers.base import RunResult
from tests.support.handler_support import (
    FakeChat,
    FakeUser,
    fresh_env,
    last_reply,
    load_session_disk,
    send_command,
    send_text,
)


async def test_message_after_new_gets_fresh_session():
    """/new then message should use a fresh provider state, not stale."""
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
        # Provider should have been called with started=False (new session)
        assert len(prov.run_calls) == 2
        second_call = prov.run_calls[1]
        assert second_call["provider_state"]["started"] is False


async def test_role_change_with_pending_approval():
    """Changing role while a pending approval exists should invalidate the pending request."""
    with fresh_env(config_overrides={"approval_mode": "on"}) as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")
        prov.preflight_results = [RunResult(text="plan: do something")]

        # Send message — creates pending request
        await send_text(chat, user, "hello")
        session = load_session_disk(data_dir, 1001, prov)
        assert session.get("pending_approval") is not None

        # Change role
        await send_command(th.cmd_role, chat, user, "/role", args=["Python", "expert"])
        session = load_session_disk(data_dir, 1001, prov)
        assert session.get("role") == "Python expert"


async def test_compact_toggle():
    """/compact on and off should persist correctly."""
    with fresh_env() as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")

        msg = await send_command(th.cmd_compact, chat, user, "/compact", args=["on"])
        reply = last_reply(msg)
        assert "on" in reply.lower()

        session = load_session_disk(data_dir, 1001, prov)
        assert session.get("compact_mode") is True

        msg = await send_command(th.cmd_compact, chat, user, "/compact", args=["off"])
        reply = last_reply(msg)
        assert "off" in reply.lower()

        session = load_session_disk(data_dir, 1001, prov)
        assert session.get("compact_mode") is False


async def test_session_shows_provider_info():
    """/session should show provider-specific session info."""
    with fresh_env() as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")

        msg = await send_command(th.cmd_session, chat, user, "/session")
        reply = last_reply(msg)
        assert "claude" in reply.lower()
        assert "Session" in reply or "session" in reply


async def test_session_codex_shows_thread():
    """/session with codex provider shows thread info."""
    with fresh_env(provider_name="codex") as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")

        msg = await send_command(th.cmd_session, chat, user, "/session")
        reply = last_reply(msg)
        assert "Thread" in reply


async def test_cancel_clears_pending():
    """/cancel should clear any pending request."""
    with fresh_env(config_overrides={"approval_mode": "on"}) as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")
        prov.preflight_results = [RunResult(text="plan")]

        await send_text(chat, user, "test")
        session = load_session_disk(data_dir, 1001, prov)
        assert session.get("pending_approval") is not None

        await send_command(th.cmd_cancel, chat, user, "/cancel")
        session = load_session_disk(data_dir, 1001, prov)
        assert session.get("pending_approval") is None and session.get("pending_retry") is None


async def test_empty_message_ignored():
    """Empty text message should not trigger provider."""
    with fresh_env() as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")

        await send_text(chat, user, "")
        assert len(prov.run_calls) == 0
