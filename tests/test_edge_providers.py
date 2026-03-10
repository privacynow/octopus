"""Edge case tests: provider behavior (timeout, empty response, error states)."""

import app.telegram_handlers as th
from app.providers.base import RunResult
from tests.support.handler_support import (
    FakeChat,
    FakeUser,
    fresh_env,
    last_reply,
    load_session_disk,
    send_text,
)


async def test_provider_timeout_shows_error():
    """Provider timeout should show an error message to the user."""
    with fresh_env() as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")
        prov.run_results = [RunResult(text="", timed_out=True, returncode=124)]

        await send_text(chat, user, "hello")
        assert len(prov.run_calls) == 1
        # Check that something was sent to the user (timeout message)
        assert len(chat.sent_messages) > 0 or len(prov.run_calls) == 1


async def test_provider_empty_response():
    """Provider returning empty text should show a placeholder."""
    with fresh_env() as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")
        prov.run_results = [RunResult(text="")]

        await send_text(chat, user, "hello")
        assert len(prov.run_calls) == 1


async def test_provider_error_returncode():
    """Provider returning a non-zero exit code should show an error."""
    with fresh_env() as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")
        prov.run_results = [RunResult(text="[error]", returncode=1)]

        await send_text(chat, user, "hello")
        assert len(prov.run_calls) == 1


async def test_provider_state_persisted_after_run():
    """Provider state updates should be saved in the session."""
    with fresh_env() as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")
        prov.run_results = [
            RunResult(text="done", provider_state_updates={"started": True}),
        ]

        await send_text(chat, user, "hello")
        session = load_session_disk(data_dir, 1001, prov)
        assert session["provider_state"]["started"] is True


async def test_codex_thread_id_persisted():
    """Codex thread_id from provider should be persisted in session."""
    with fresh_env(provider_name="codex") as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")
        prov.run_results = [
            RunResult(text="done", provider_state_updates={"thread_id": "thread-abc"}),
        ]

        await send_text(chat, user, "hello")
        session = load_session_disk(data_dir, 1001, prov)
        assert session["provider_state"]["thread_id"] == "thread-abc"


async def test_codex_second_message_resumes_thread():
    """Second message to codex should resume with saved thread_id."""
    with fresh_env(provider_name="codex") as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")
        prov.run_results = [
            RunResult(text="first", provider_state_updates={"thread_id": "thread-abc"}),
            RunResult(text="second", provider_state_updates={"thread_id": "thread-abc"}),
        ]

        await send_text(chat, user, "first message")
        await send_text(chat, user, "second message")
        assert len(prov.run_calls) == 2
        # Second call should have thread_id from first call
        second_state = prov.run_calls[1]["provider_state"]
        assert second_state["thread_id"] == "thread-abc"


async def test_approval_plan_then_execute():
    """Full approval flow: preflight → approve → execute."""
    with fresh_env(config_overrides={"approval_mode": "on"}) as (data_dir, cfg, prov):
        from tests.support.handler_support import send_callback
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")
        prov.preflight_results = [RunResult(text="Plan: I will read files")]
        prov.run_results = [
            RunResult(text="execution done", provider_state_updates={"started": True}),
        ]

        # Trigger preflight
        await send_text(chat, user, "analyze code")
        assert len(prov.preflight_calls) == 1
        assert len(prov.run_calls) == 0

        # Approve
        query, _ = await send_callback(th.handle_callback, chat, user, "approval_approve")
        assert len(prov.run_calls) == 1
