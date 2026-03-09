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


async def test_export_with_history():
    """Export sends document with history."""
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        # Create some ring buffer entries
        save_raw(data_dir, 12345, "hello", "Hello! How can I help?")
        save_raw(data_dir, 12345, "what is 2+2", "The answer is 4.")

        chat = FakeChat(12345)
        user = FakeUser(42)
        msg = await send_command(th.cmd_export, chat, user, "/export")

        # Should have a document reply
        checks.check("has document reply", len(msg.replies) > 0, True)
        reply = msg.replies[-1]
        checks.check("is document", "document" in reply, True)


run_test("with history", test_export_with_history())


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
