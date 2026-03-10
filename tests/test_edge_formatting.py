"""Edge case tests: formatting and output edge cases."""

from app.formatting import md_to_telegram_html, split_html, trim_text


def test_deeply_nested_markdown():
    """Deeply nested lists and emphasis should not crash or hang."""
    nested = "- " * 20 + "deep item"
    result = md_to_telegram_html(nested)
    assert "deep item" in result


def test_extremely_long_single_line():
    """Very long single line should be trimmed without crash."""
    long_line = "x" * 50000
    result = trim_text(long_line, 4000)
    assert len(result) <= 4100  # trim_text adds "..." suffix
    assert result.endswith("…") or result.endswith("...")


def test_empty_code_block():
    """Empty code block should render without error."""
    md = "```\n```"
    result = md_to_telegram_html(md)
    assert "<pre>" in result or "<code>" in result or result.strip() == ""


def test_code_block_with_language():
    """Code block with language tag should render."""
    md = "```python\nprint('hello')\n```"
    result = md_to_telegram_html(md)
    assert "print" in result


def test_unicode_emoji_mix():
    """Mixed unicode/emoji content should render cleanly."""
    md = "Status: ✅ Done — 日本語テスト — 🚀 launched"
    result = md_to_telegram_html(md)
    assert "✅" in result
    assert "日本語" in result


def test_html_entities_in_markdown():
    """Markdown containing < > & should be escaped."""
    md = "Compare: `x < 10 && y > 5`"
    result = md_to_telegram_html(md)
    assert "&lt;" in result or "<" not in result.replace("<code>", "").replace("</code>", "")


def test_split_html_single_chunk():
    """Short HTML should come back as a single chunk."""
    short = "<b>hello</b>"
    chunks = split_html(short, limit=4096)
    assert len(chunks) == 1
    assert chunks[0] == short


def test_split_html_preserves_content():
    """Splitting long HTML should preserve all content."""
    lines = [f"Line {i}" for i in range(200)]
    html_text = "<br>".join(lines)
    chunks = split_html(html_text, limit=500)
    assert len(chunks) > 1
    rejoined = "".join(chunks)
    for line in lines[:10]:
        assert line in rejoined


def test_table_with_inconsistent_columns():
    """Markdown table with varying column counts should not crash."""
    md = (
        "| A | B | C |\n"
        "|---|---|\n"
        "| 1 | 2 | 3 | 4 |\n"
        "| 5 |\n"
    )
    result = md_to_telegram_html(md)
    # Should produce some output without crashing
    assert len(result) > 0


def test_trim_text_empty():
    """trim_text on empty string should return empty."""
    assert trim_text("", 100) == ""


def test_trim_text_exact_boundary():
    """trim_text at exact length should not trim."""
    text = "x" * 100
    result = trim_text(text, 100)
    assert result == text
