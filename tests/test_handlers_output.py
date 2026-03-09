"""Handler integration tests for output presentation and raw-response helpers."""

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.providers.base import RunResult
from app.storage import _db_connections, default_session, ensure_data_dirs, save_session
from tests.support.assertions import Checks
from tests.support.handler_support import (
    FakeChat,
    FakeProvider,
    FakeUser,
    last_reply,
    load_session_disk,
    make_config,
    send_command,
    send_text,
    setup_globals,
)

checks = Checks()
_tests: list[tuple[str, object]] = []


def run_test(name, coro):
    _tests.append((name, coro))


async def test_compact_toggle():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(data_dir)
        prov = FakeProvider("codex")
        setup_globals(cfg, prov)

        session = default_session("codex", prov.new_provider_state(), "off")
        save_session(data_dir, 1, session)

        chat = FakeChat(1)
        user = FakeUser(42)

        import app.telegram_handlers as th

        msg1 = await send_command(th.cmd_compact, chat, user, "/compact")
        checks.check("compact default is off", "off" in last_reply(msg1).lower(), True)

        msg2 = await send_command(th.cmd_compact, chat, user, "/compact on", args=["on"])
        checks.check("compact turned on", "on" in last_reply(msg2).lower(), True)
        session = load_session_disk(data_dir, 1, prov)
        checks.check("compact_mode stored true", session.get("compact_mode"), True)

        msg3 = await send_command(th.cmd_compact, chat, user, "/compact off", args=["off"])
        checks.check("compact turned off", "off" in last_reply(msg3).lower(), True)
        session = load_session_disk(data_dir, 1, prov)
        checks.check("compact_mode stored false", session.get("compact_mode"), False)


run_test("/compact toggle", test_compact_toggle())


async def test_raw_retrieves_response():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(data_dir)
        prov = FakeProvider("codex")
        setup_globals(cfg, prov)

        session = default_session("codex", prov.new_provider_state(), "off")
        save_session(data_dir, 1, session)

        chat = FakeChat(1)
        user = FakeUser(42)

        prov.run_results = [RunResult(text="This is the full response text.")]
        await send_text(chat, user, "hello")

        import app.telegram_handlers as th

        msg = await send_command(th.cmd_raw, chat, user, "/raw")
        checks.check("raw has response text", "full response" in last_reply(msg), True)

        msg2 = await send_command(th.cmd_raw, FakeChat(999), user, "/raw")
        checks.check("raw empty chat", "no stored" in last_reply(msg2).lower(), True)


run_test("/raw retrieves response", test_raw_retrieves_response())


async def test_e2e_table_in_provider_response():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(data_dir)
        prov = FakeProvider("codex")
        setup_globals(cfg, prov)

        session = default_session("codex", prov.new_provider_state(), "off")
        save_session(data_dir, 1, session)

        table_response = (
            "Here are the results:\n\n"
            "| Name  | Score |\n"
            "|-------|-------|\n"
            "| Alice | 95    |\n"
            "| Bob   | 87    |\n"
        )
        prov.run_results = [RunResult(text=table_response)]

        chat = FakeChat(1)
        user = FakeUser(42)
        msg = await send_text(chat, user, "show scores")

        all_replies = " ".join(r.get("text", "") for r in msg.replies)
        checks.check("table reply has pre", "<pre>" in all_replies, True)
        checks.check("table reply has alice", "Alice" in all_replies, True)
        checks.check("table reply no pipes", "---|---" not in all_replies, True)


run_test("e2e table in provider response", test_e2e_table_in_provider_response())


async def test_e2e_compact_mode_summarizes():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(data_dir)
        prov = FakeProvider("codex")
        setup_globals(cfg, prov)

        session = default_session("codex", prov.new_provider_state(), "off")
        session["compact_mode"] = True
        save_session(data_dir, 1, session)

        long_response = "Detailed analysis paragraph. " * 40
        prov.run_results = [RunResult(text=long_response)]

        chat = FakeChat(1)
        user = FakeUser(42)

        import app.telegram_handlers as th
        original_summarize = th.summarize

        async def fake_summarize(text, model, timeout=30):
            return "Short summary of the analysis."

        th.summarize = fake_summarize
        try:
            msg = await send_text(chat, user, "analyze this")
        finally:
            th.summarize = original_summarize

        all_replies = " ".join(r.get("text", "") for r in msg.replies)
        checks.check("compact reply has summary", "Short summary" in all_replies, True)
        checks.check("compact reply has footer", "/raw" in all_replies, True)
        checks.check(
            "compact reply not full text",
            "Detailed analysis paragraph. Detailed" not in all_replies,
            True,
        )

        msg2 = await send_command(th.cmd_raw, chat, user, "/raw")
        raw_reply = last_reply(msg2)
        checks.check("raw has original text", "Detailed analysis paragraph" in raw_reply, True)


run_test("e2e compact mode summarizes", test_e2e_compact_mode_summarizes())


async def test_e2e_compact_off_no_summarize():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(data_dir)
        prov = FakeProvider("codex")
        setup_globals(cfg, prov)

        session = default_session("codex", prov.new_provider_state(), "off")
        save_session(data_dir, 1, session)

        long_response = "Full verbose response. " * 50
        prov.run_results = [RunResult(text=long_response)]

        chat = FakeChat(1)
        user = FakeUser(42)
        msg = await send_text(chat, user, "do something")

        all_replies = " ".join(r.get("text", "") for r in msg.replies)
        checks.check("no-compact has full text", "Full verbose response" in all_replies, True)
        checks.check("no-compact no footer", "/raw for full" not in all_replies, True)

        import app.telegram_handlers as th
        msg2 = await send_command(th.cmd_raw, chat, user, "/raw")
        checks.check("raw still works without compact", "Full verbose response" in last_reply(msg2), True)


run_test("e2e compact off no summarize", test_e2e_compact_off_no_summarize())


async def test_e2e_compact_mode_summarize_exception_falls_back():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(data_dir)
        prov = FakeProvider("codex")
        setup_globals(cfg, prov)

        session = default_session("codex", prov.new_provider_state(), "off")
        session["compact_mode"] = True
        save_session(data_dir, 1, session)

        long_response = "Verbose output block. " * 60
        prov.run_results = [RunResult(text=long_response)]

        chat = FakeChat(1)
        user = FakeUser(42)

        import app.telegram_handlers as th
        original_summarize = th.summarize

        async def broken_summarize(text, model, timeout=30):
            raise RuntimeError("boom")

        th.summarize = broken_summarize
        try:
            msg = await send_text(chat, user, "summarize this")
        finally:
            th.summarize = original_summarize

        all_replies = " ".join(r.get("text", "") for r in msg.replies)
        checks.check("fallback keeps full response", "Verbose output block." in all_replies, True)
        checks.check("fallback omits compact footer", "/raw for full response" in all_replies, False)

        import app.telegram_handlers as th2
        msg2 = await send_command(th2.cmd_raw, chat, user, "/raw")
        checks.check("raw retains original after summarize error", "Verbose output block." in last_reply(msg2), True)


run_test(
    "e2e compact summarize exception falls back",
    test_e2e_compact_mode_summarize_exception_falls_back(),
)


def _close_all_db_connections():
    """Close all leaked SQLite connections between tests."""
    for conn in _db_connections.values():
        try:
            conn.close()
        except Exception:
            pass
    _db_connections.clear()


async def _run_all():
    for name, coro in _tests:
        print(f"\n=== {name} ===")
        try:
            await coro
        except Exception as exc:
            print(f"  FAIL  {name} (exception: {exc})")
            import traceback
            traceback.print_exc()
            checks.failed += 1
        finally:
            _close_all_db_connections()


async def _main():
    await _run_all()


if __name__ == "__main__":
    asyncio.run(_main())
    print(f"\n{'='*40}")
    print(f"  {checks.passed} passed, {checks.failed} failed")
    print(f"{'='*40}")
    sys.exit(1 if checks.failed else 0)
