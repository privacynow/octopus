"""Tests for /export handler."""

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import app.telegram_handlers as th
from app.storage import ensure_data_dirs
from app.summarize import save_raw
from tests.support.assertions import Checks
from tests.support.handler_support import (
    FakeChat,
    FakeContext,
    FakeMessage,
    FakeProvider,
    FakeUpdate,
    FakeUser,
    last_reply,
    make_config,
    send_command,
    setup_globals,
)

checks = Checks()
_tests: list[tuple[str, object]] = []


def run_test(name, coro):
    _tests.append((name, coro))


async def test_export_no_history():
    """No history returns message."""
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(data_dir)
        setup_globals(cfg, FakeProvider())

        chat = FakeChat(12345)
        user = FakeUser(42)
        msg = await send_command(th.cmd_export, chat, user, "/export")
        checks.check("no history msg", "No conversation history" in last_reply(msg), True)


run_test("no history", test_export_no_history())


def _export_text(msg) -> str:
    """Extract exported text from the document reply."""
    reply = msg.replies[-1]
    doc = reply["document"]
    doc.seek(0)
    return doc.read().decode("utf-8")


async def test_export_with_history():
    """Export sends document with correct body content."""
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        save_raw(data_dir, 12345, "hello there", "Hello! How can I help?")
        save_raw(data_dir, 12345, "what is 2+2", "The answer is 4.")

        chat = FakeChat(12345)
        user = FakeUser(42)
        msg = await send_command(th.cmd_export, chat, user, "/export")

        checks.check("has document reply", len(msg.replies) > 0, True)
        reply = msg.replies[-1]
        checks.check("is document", "document" in reply, True)

        text = _export_text(msg)
        # Scope note
        checks.check("scope note present", "only successful" in text, True)
        checks.check("scope note mentions denied", "Denied" in text, True)
        # Session metadata header
        checks.check("header has chat id", "Chat ID: 12345" in text, True)
        checks.check("header has provider", "Provider: claude" in text, True)
        # Conversation body
        checks.check("full prompt in body", "User: hello there" in text, True)
        checks.check("response in body", "Assistant: Hello! How can I help?" in text, True)
        checks.check("second prompt", "User: what is 2+2" in text, True)
        checks.check("second response", "Assistant: The answer is 4." in text, True)


run_test("with history", test_export_with_history())


async def test_export_approval_label():
    """Approval-kind entries show [approval] label in export."""
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(data_dir)
        setup_globals(cfg, FakeProvider("claude"))

        save_raw(data_dir, 12345, "deploy to prod", "here is the plan", kind="approval")
        save_raw(data_dir, 12345, "deploy to prod", "deployed successfully")

        chat = FakeChat(12345)
        user = FakeUser(42)
        msg = await send_command(th.cmd_export, chat, user, "/export")

        text = _export_text(msg)
        checks.check("approval label present", "[approval]" in text, True)
        checks.check("request turn has no label", text.count("[approval]") == 1, True)


run_test("approval label", test_export_approval_label())




async def test_export_not_allowed():
    """Disallowed user gets no response."""
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(
            data_dir,
            allow_open=False,
            allowed_user_ids=frozenset({99}),
        )
        setup_globals(cfg, FakeProvider())

        chat = FakeChat(12345)
        user = FakeUser(42, "stranger")
        msg = await send_command(th.cmd_export, chat, user, "/export")
        checks.check("no reply", len(msg.replies), 0)


run_test("not allowed", test_export_not_allowed())


# Run all tests
for name, coro in _tests:
    print(f"\n--- {name} ---")
    asyncio.get_event_loop().run_until_complete(coro)

print(f"\n{'='*40}")
print(f"  {checks.passed} passed, {checks.failed} failed")
print(f"{'='*40}")
sys.exit(1 if checks.failed else 0)
