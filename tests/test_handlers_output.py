"""Handler integration tests for output presentation and raw-response helpers."""

from app.providers.base import RunResult
from app.storage import default_session, save_session
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
    fresh_data_dir,
)


async def test_compact_toggle():
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("codex")
        setup_globals(cfg, prov)

        session = default_session("codex", prov.new_provider_state(), "off")
        save_session(data_dir, 1, session)

        chat = FakeChat(1)
        user = FakeUser(42)

        import app.telegram_handlers as th

        msg1 = await send_command(th.cmd_compact, chat, user, "/compact")
        assert "off" in last_reply(msg1).lower()

        msg2 = await send_command(th.cmd_compact, chat, user, "/compact on", args=["on"])
        assert "on" in last_reply(msg2).lower()
        session = load_session_disk(data_dir, 1, prov)
        assert session.get("compact_mode") == True

        msg3 = await send_command(th.cmd_compact, chat, user, "/compact off", args=["off"])
        assert "off" in last_reply(msg3).lower()
        session = load_session_disk(data_dir, 1, prov)
        assert session.get("compact_mode") == False


async def test_raw_retrieves_response():
    with fresh_data_dir() as data_dir:
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
        assert "full response" in last_reply(msg)

        msg2 = await send_command(th.cmd_raw, FakeChat(999), user, "/raw")
        assert "no stored" in last_reply(msg2).lower()


async def test_e2e_table_in_provider_response():
    with fresh_data_dir() as data_dir:
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
        assert "<pre>" in all_replies
        assert "Alice" in all_replies
        assert "---|---" not in all_replies


async def test_e2e_compact_mode_summarizes():
    with fresh_data_dir() as data_dir:
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
        assert "Short summary" in all_replies
        assert "/raw" in all_replies
        assert "Detailed analysis paragraph. Detailed" not in all_replies

        msg2 = await send_command(th.cmd_raw, chat, user, "/raw")
        raw_reply = last_reply(msg2)
        assert "Detailed analysis paragraph" in raw_reply


async def test_e2e_compact_off_no_summarize():
    with fresh_data_dir() as data_dir:
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
        assert "Full verbose response" in all_replies
        assert "/raw for full" not in all_replies

        import app.telegram_handlers as th
        msg2 = await send_command(th.cmd_raw, chat, user, "/raw")
        assert "Full verbose response" in last_reply(msg2)


async def test_e2e_compact_mode_summarize_exception_falls_back():
    with fresh_data_dir() as data_dir:
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
        assert "Verbose output block." in all_replies
        assert "/raw for full response" not in all_replies

        import app.telegram_handlers as th2
        msg2 = await send_command(th2.cmd_raw, chat, user, "/raw")
        assert "Verbose output block." in last_reply(msg2)
