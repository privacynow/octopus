"""Handler integration tests for output presentation and raw-response helpers."""

from app.providers.base import RunResult
from app.storage import default_session, save_session
from app.telegram_handlers import _extract_summary
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


async def test_e2e_compact_mode_uses_blockquote():
    """Compact mode should use expandable blockquote for long responses."""
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("codex")
        setup_globals(cfg, prov)

        session = default_session("codex", prov.new_provider_state(), "off")
        session["compact_mode"] = True
        save_session(data_dir, 1, session)

        long_response = "Summary line one.\n\nDetailed analysis paragraph. " * 30
        prov.run_results = [RunResult(text=long_response)]

        chat = FakeChat(1)
        user = FakeUser(42)

        msg = await send_text(chat, user, "analyze this")

        all_replies = " ".join(r.get("text", "") for r in msg.replies)
        # Should contain expandable blockquote or a "Show full" button
        has_blockquote = "blockquote" in all_replies
        has_expand_button = any(
            r.get("reply_markup") is not None for r in msg.replies
        )
        assert has_blockquote or has_expand_button, (
            f"Expected blockquote or expand button, got: {all_replies[:200]}"
        )

        import app.telegram_handlers as th
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


async def test_e2e_compact_mode_short_response_no_blockquote():
    """Compact mode should not use blockquote for short responses (<800 chars)."""
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("codex")
        setup_globals(cfg, prov)

        session = default_session("codex", prov.new_provider_state(), "off")
        session["compact_mode"] = True
        save_session(data_dir, 1, session)

        short_response = "Quick answer: 42."
        prov.run_results = [RunResult(text=short_response)]

        chat = FakeChat(1)
        user = FakeUser(42)
        msg = await send_text(chat, user, "what is the answer")

        all_replies = " ".join(r.get("text", "") for r in msg.replies)
        assert "42" in all_replies
        assert "blockquote" not in all_replies


# -- _extract_summary unit tests --

def test_extract_summary_splits_at_line_boundary():
    text = "Line one\nLine two\nLine three\nLine four\nLine five\nLine six"
    summary, rest = _extract_summary(text, max_lines=3)
    assert "Line one" in summary
    assert "Line three" in summary
    assert "Line five" in rest


def test_extract_summary_short_text():
    text = "Just one line"
    summary, rest = _extract_summary(text, max_lines=4)
    assert summary == "Just one line"
    assert rest == ""
