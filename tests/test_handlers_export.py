"""Tests for /export handler."""

import app.telegram_handlers as th
from app.summarize import save_raw
from tests.support.handler_support import (
    FakeChat,
    FakeProvider,
    FakeUser,
    last_reply,
    make_config,
    send_command,
    setup_globals,
    fresh_data_dir,
)


async def test_export_no_history():
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        setup_globals(cfg, FakeProvider())

        chat = FakeChat(12345)
        user = FakeUser(42)
        msg = await send_command(th.cmd_export, chat, user, "/export")
        assert "No conversation history" in last_reply(msg)


def _export_text(msg) -> str:
    reply = msg.replies[-1]
    doc = reply["document"]
    doc.seek(0)
    return doc.read().decode("utf-8")


async def test_export_with_history():
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        save_raw(data_dir, 12345, "hello there", "Hello! How can I help?")
        save_raw(data_dir, 12345, "what is 2+2", "The answer is 4.")

        chat = FakeChat(12345)
        user = FakeUser(42)
        msg = await send_command(th.cmd_export, chat, user, "/export")

        assert len(msg.replies) > 0
        assert "document" in msg.replies[-1]

        text = _export_text(msg)
        assert "only successful" in text
        assert "Denied" in text
        assert "Chat ID: 12345" in text
        assert "Provider: claude" in text
        assert "User: hello there" in text
        assert "Assistant: Hello! How can I help?" in text
        assert "User: what is 2+2" in text
        assert "Assistant: The answer is 4." in text


async def test_export_approval_label():
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        setup_globals(cfg, FakeProvider("claude"))

        save_raw(data_dir, 12345, "deploy to prod", "here is the plan", kind="approval")
        save_raw(data_dir, 12345, "deploy to prod", "deployed successfully")

        chat = FakeChat(12345)
        user = FakeUser(42)
        msg = await send_command(th.cmd_export, chat, user, "/export")

        text = _export_text(msg)
        assert "[approval]" in text
        assert text.count("[approval]") == 1


async def test_export_not_allowed():
    with fresh_data_dir() as data_dir:
        cfg = make_config(
            data_dir,
            allow_open=False,
            allowed_user_ids=frozenset({99}),
        )
        setup_globals(cfg, FakeProvider())

        chat = FakeChat(12345)
        user = FakeUser(42, "stranger")
        msg = await send_command(th.cmd_export, chat, user, "/export")
        assert len(msg.replies) == 0
