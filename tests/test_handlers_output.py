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
    send_callback,
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


# -- III.4: summary-first prompt injection --


async def test_compact_mode_injects_summary_first_instruction():
    """Compact mode must inject summary-first instruction into the execution context system prompt."""
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("codex")
        setup_globals(cfg, prov)

        session = default_session("codex", prov.new_provider_state(), "off")
        session["compact_mode"] = True
        save_session(data_dir, 1, session)

        prov.run_results = [RunResult(text="Short answer.")]
        chat = FakeChat(1)
        user = FakeUser(42)
        await send_text(chat, user, "explain something")

        assert len(prov.run_calls) == 1
        ctx = prov.run_calls[0]["context"]
        assert "summary first" in ctx.system_prompt.lower()
        assert "2-4 line" in ctx.system_prompt


async def test_compact_off_no_summary_first_instruction():
    """Non-compact mode must NOT inject summary-first instruction."""
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("codex")
        setup_globals(cfg, prov)

        session = default_session("codex", prov.new_provider_state(), "off")
        session["compact_mode"] = False
        save_session(data_dir, 1, session)

        prov.run_results = [RunResult(text="Full answer.")]
        chat = FakeChat(1)
        user = FakeUser(42)
        await send_text(chat, user, "explain something")

        assert len(prov.run_calls) == 1
        ctx = prov.run_calls[0]["context"]
        sp = ctx.system_prompt or ""
        assert "summary first" not in sp.lower()


# -- III.3: expand/collapse callback tests --


def _button_path_response() -> str:
    """Generate a response that forces the expand-button path.

    _send_compact_reply uses blockquote when compact HTML ≤ 4000.
    _extract_summary splits on non-empty lines (default max_lines=4).
    """
    summary = ["Summary one.", "Summary two.", "Summary three.", "Summary four."]
    detail_lines = [f"Detail {i}: " + "Detailed explanation with plenty of content here. " * 5 for i in range(25)]
    return "\n".join(summary + detail_lines)


async def test_compact_long_response_shows_expand_button():
    """Compact mode with long response should show 'Show full answer' button."""
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("codex")
        setup_globals(cfg, prov)

        session = default_session("codex", prov.new_provider_state(), "off")
        session["compact_mode"] = True
        save_session(data_dir, 1, session)

        prov.run_results = [RunResult(text=_button_path_response())]

        chat = FakeChat(1)
        user = FakeUser(42)
        msg = await send_text(chat, user, "analyze this")

        # Must have taken the button path, not blockquote
        expand_markup = None
        for r in msg.replies:
            rm = r.get("reply_markup")
            if rm is not None:
                expand_markup = rm
                break

        assert expand_markup is not None, (
            "Response should be long enough to force button path (not blockquote)"
        )

        button = expand_markup.inline_keyboard[0][0]
        assert button.text == "Show full answer"
        assert button.callback_data.startswith("expand:")

        # The reply text should show "truncated" indicator
        for r in msg.replies:
            if r.get("reply_markup") is not None:
                assert "truncated" in r.get("text", "").lower()


async def test_expand_callback_shows_full_response():
    """Expand callback loads raw text and shows it (new messages for long content)."""
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("codex")
        setup_globals(cfg, prov)

        session = default_session("codex", prov.new_provider_state(), "off")
        session["compact_mode"] = True
        save_session(data_dir, 1, session)

        prov.run_results = [RunResult(text=_button_path_response())]

        chat = FakeChat(1)
        user = FakeUser(42)
        msg = await send_text(chat, user, "analyze this")

        # Get expand callback data
        cb_data = None
        for r in msg.replies:
            rm = r.get("reply_markup")
            if rm is not None:
                cb_data = rm.inline_keyboard[0][0].callback_data
                break
        assert cb_data is not None

        import app.telegram_handlers as th
        # Clear chat.sent_messages so we only see expand-generated messages
        chat.sent_messages.clear()
        query, expanded_msg = await send_callback(th.handle_expand_callback, chat, user, cb_data)

        # Expand callback should answer the query
        assert query.answered
        # Button should be removed (edit_reply_markup with None)
        assert any(r.get("edit_reply_markup") for r in expanded_msg.replies)
        # Full content should be delivered via chat.send_message (long-content path)
        assert len(chat.sent_messages) >= 1, "Expand should send full content via chat messages"
        all_sent = " ".join(m.get("text", "") for m in chat.sent_messages)
        assert "Detail" in all_sent, "Sent messages should contain the response detail"


async def test_expand_collapse_round_trip_with_short_full_text():
    """Expand→Collapse round trip when full text fits in a single message.

    This tests the in-place edit path where expand shows a Collapse button
    and collapse restores the compact view with Show full answer button.
    We write a short raw text directly to the ring buffer to control the
    formatted length independently of the compact-HTML threshold.
    """
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("codex")
        setup_globals(cfg, prov)

        session = default_session("codex", prov.new_provider_state(), "off")
        save_session(data_dir, 1, session)

        # Write a short raw text directly to ring buffer — short enough for
        # in-place edit (≤ 4000 formatted) but with summary+detail structure
        from app.summarize import save_raw
        short_text = "Summary.\n\nLine two.\nLine three.\nLine four.\nLine five.\nDetail: the answer is 42."
        slot = save_raw(cfg.data_dir, 1, "test prompt", short_text)

        import app.telegram_handlers as th

        # Expand: should edit in-place with Collapse button
        expand_data = f"expand:1:{slot}"
        query, msg = await send_callback(th.handle_expand_callback, FakeChat(1), FakeUser(42), expand_data)

        assert query.answered
        collapse_btn = None
        for r in msg.replies:
            rm = r.get("reply_markup")
            if rm is not None:
                for row in rm.inline_keyboard:
                    for btn in row:
                        if btn.text == "Collapse":
                            collapse_btn = btn
        assert collapse_btn is not None, "Short expand should show Collapse button"
        assert collapse_btn.callback_data.startswith("collapse:")

        # Collapse: should restore compact view with Show full answer button
        collapse_data = collapse_btn.callback_data
        query2, msg2 = await send_callback(th.handle_collapse_callback, FakeChat(1), FakeUser(42), collapse_data)

        assert query2.answered
        expand_btn = None
        for r in msg2.replies:
            rm = r.get("reply_markup")
            if rm is not None:
                for row in rm.inline_keyboard:
                    for btn in row:
                        if btn.text == "Show full answer":
                            expand_btn = btn
        assert expand_btn is not None, "Collapse should restore Show full answer button"
        # Collapsed text should show truncation indicator
        collapsed_text = ""
        for r in msg2.replies:
            collapsed_text += r.get("edit_text", "")
        assert "truncated" in collapsed_text.lower()


async def test_collapse_callback_restores_compact_with_expand_button():
    """Collapse callback should restore compact view with Show full answer button."""
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("codex")
        setup_globals(cfg, prov)

        session = default_session("codex", prov.new_provider_state(), "off")
        save_session(data_dir, 1, session)

        # Write raw text directly to ring buffer
        from app.summarize import save_raw
        text = "Summary.\n\nLine two.\nLine three.\nLine four.\nLine five.\nDetail content."
        slot = save_raw(cfg.data_dir, 1, "prompt", text)

        import app.telegram_handlers as th
        collapse_data = f"collapse:1:{slot}"
        query, msg = await send_callback(th.handle_collapse_callback, FakeChat(1), FakeUser(42), collapse_data)

        has_expand_button = False
        has_truncated = False
        for r in msg.replies:
            text = r.get("edit_text", "")
            if "truncated" in text.lower():
                has_truncated = True
            rm = r.get("reply_markup")
            if rm is not None:
                for row in rm.inline_keyboard:
                    for btn in row:
                        if btn.text == "Show full answer":
                            has_expand_button = True
        assert has_expand_button, "Collapsed message should have Show full answer button"
        assert has_truncated, "Collapsed message should show truncation indicator"


async def test_expand_callback_rotated_buffer():
    """Expand callback on rotated buffer entry shows unavailable message."""
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("codex")
        setup_globals(cfg, prov)

        session = default_session("codex", prov.new_provider_state(), "off")
        save_session(data_dir, 1, session)

        # Fire expand callback for a slot that was never written
        import app.telegram_handlers as th
        query, msg = await send_callback(th.handle_expand_callback, chat=FakeChat(1), user=FakeUser(42), data="expand:1:999")

        found_unavailable = False
        for r in msg.replies:
            text = r.get("edit_text", "")
            if "no longer available" in text.lower():
                found_unavailable = True
        assert found_unavailable
