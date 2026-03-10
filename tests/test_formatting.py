"""Tests for formatting.py — markdown converter, text splitting, send directives."""

from app.formatting import extract_send_directives, md_to_telegram_html, split_html, trim_text


# -- trim_text --

def test_trim_text_short():
    assert trim_text("hello", 10) == "hello"

def test_trim_text_exact():
    assert trim_text("hello", 5) == "hello"

def test_trim_text_truncate():
    assert trim_text("hello world", 8) == "hello..."


# -- md_to_telegram_html --

def test_md_bold():
    assert md_to_telegram_html("**bold**") == "<b>bold</b>"

def test_md_italic():
    assert md_to_telegram_html("*italic*") == "<i>italic</i>"

def test_md_bold_and_italic():
    assert md_to_telegram_html("**bold** and *italic*") == "<b>bold</b> and <i>italic</i>"

def test_md_header():
    assert md_to_telegram_html("# Header") == "<b>Header</b>"

def test_md_h3():
    assert md_to_telegram_html("### Sub") == "<b>Sub</b>"

def test_md_inline_code():
    assert md_to_telegram_html("use `foo()` here") == "use <code>foo()</code> here"

def test_md_strike():
    assert md_to_telegram_html("~~removed~~") == "<s>removed</s>"

def test_md_link():
    assert md_to_telegram_html("[click](https://x.com)") == '<a href="https://x.com">click</a>'

def test_md_html_escape():
    assert md_to_telegram_html("a < b & c > d") == "a &lt; b &amp; c &gt; d"

def test_md_underscore_bold():
    assert md_to_telegram_html("__bold__") == "<b>bold</b>"

def test_md_fenced_code_block():
    cb = md_to_telegram_html("```python\nprint('hi')\n```")
    assert "<pre>" in cb
    assert "language-python" in cb
    assert "print" in cb
    assert "</code></pre>" in cb

def test_md_fenced_no_lang():
    cb_nolang = md_to_telegram_html("```\nplain code\n```")
    assert "<pre>" in cb_nolang
    assert "plain code" in cb_nolang
    assert "</pre>" in cb_nolang
    assert ("language-" in cb_nolang) == False

def test_md_bold_with_code():
    mixed = md_to_telegram_html("**bold with `code` inside**")
    assert "<b>" in mixed
    assert "<code>code</code>" in mixed

def test_md_code_html_escape():
    dangerous = md_to_telegram_html("`<script>alert(1)</script>`")
    assert "<code>&lt;script&gt;" in dangerous

def test_md_multi_line():
    multi = md_to_telegram_html("# Title\n\nSome **bold** text\n\n```\ncode\n```\n\nEnd.")
    assert "<b>Title</b>" in multi
    assert "<b>bold</b>" in multi
    assert "<pre>" in multi
    assert "code" in multi
    assert "End." in multi

def test_md_plain_text():
    assert md_to_telegram_html("hello world") == "hello world"

def test_md_underscore_in_word():
    result = md_to_telegram_html("some_variable_name")
    assert result == "some_variable_name"


# -- split_html --

def test_split_html_short():
    assert split_html("hi", 10) == ["hi"]

def test_split_html_exact():
    assert split_html("x" * 4096, 4096) == ["x" * 4096]

def test_split_html_splits_needed():
    chunks = split_html("line1\nline2\nline3", 10)
    assert len(chunks) > 1

def test_split_html_pre_balanced():
    """Balanced HTML: a <pre> block that spans across chunks."""
    long_code = "<pre>" + "x" * 100 + "</pre>"
    chunks_pre = split_html(long_code, 60)
    assert len(chunks_pre) > 1
    # Every chunk must have balanced <pre> tags
    for i, chunk in enumerate(chunks_pre):
        opens = chunk.count("<pre>")
        closes = chunk.count("</pre>")
        assert opens == closes

def test_split_html_nested_balanced():
    """Nested tags: <b> inside <pre>."""
    nested = "<pre><b>" + "y" * 100 + "</b></pre>"
    chunks_nested = split_html(nested, 60)
    assert len(chunks_nested) > 1
    for i, chunk in enumerate(chunks_nested):
        for tag in ["pre", "b"]:
            opens = chunk.count(f"<{tag}>")
            closes = chunk.count(f"</{tag}>")
            assert opens == closes

def test_split_html_continuation_reopens_pre():
    """Continuation: second chunk reopens tags from first."""
    long_code = "<pre>" + "x" * 100 + "</pre>"
    chunks_pre = split_html(long_code, 60)
    assert chunks_pre[1].startswith("<pre>")

def test_split_html_already_closed_tags():
    """Already-closed tags should not be re-closed."""
    closed_html = "<b>bold</b>\n" * 20
    chunks_closed = split_html(closed_html, 50)
    for i, chunk in enumerate(chunks_closed):
        opens = chunk.count("<b>")
        closes = chunk.count("</b>")
        assert opens == closes

def test_split_html_real_world():
    """Real-world: md_to_telegram_html output with a long code block."""
    long_md = "# Title\n\n```python\n" + "print('hello')\n" * 300 + "```\n\nDone."
    long_html = md_to_telegram_html(long_md)
    real_chunks = split_html(long_html, 4096)
    assert len(real_chunks) > 1
    for i, chunk in enumerate(real_chunks):
        for tag in ["pre", "code"]:
            opens = chunk.count(f"<{tag}")  # <code or <code class=...>
            closes = chunk.count(f"</{tag}>")
            assert opens == closes

def test_split_html_strict_size_limit():
    """STRICT SIZE LIMIT: every chunk must be <= limit, including closing tags."""
    long_md = "# Title\n\n```python\n" + "print('hello')\n" * 300 + "```\n\nDone."
    long_html = md_to_telegram_html(long_md)
    real_chunks = split_html(long_html, 4096)
    for i, chunk in enumerate(real_chunks):
        assert len(chunk) <= 4096

def test_split_html_tight_limit():
    """Test with a tighter limit to stress the suffix reservation."""
    long_md = "# Title\n\n```python\n" + "print('hello')\n" * 300 + "```\n\nDone."
    long_html = md_to_telegram_html(long_md)
    tight_chunks = split_html(long_html, 200)
    assert len(tight_chunks) > 5
    for i, chunk in enumerate(tight_chunks):
        assert len(chunk) <= 200
        for tag in ["pre", "code"]:
            opens = chunk.count(f"<{tag}")
            closes = chunk.count(f"</{tag}>")
            assert opens == closes

def test_split_html_attribute_preservation():
    """ATTRIBUTE PRESERVATION: links should keep their href across chunks."""
    long_link = '<a href="https://example.com/very/long/path">' + "click " * 500 + "</a>"
    link_chunks = split_html(long_link, 200)
    assert len(link_chunks) > 1
    for i, chunk in enumerate(link_chunks):
        if "<a " in chunk or "<a>" in chunk:
            # Every <a> tag must have the href attribute
            assert 'href="https://example.com/very/long/path"' in chunk
        assert len(chunk) <= 200
        opens = chunk.count("<a ")  # opening tags with attributes
        if opens == 0:
            opens = chunk.count("<a>")  # should not happen — would mean lost attributes
        closes = chunk.count("</a>")
        assert opens == closes

def test_split_html_nested_attr():
    """Nested link in pre: attributes preserved on both."""
    nested_attr = '<pre><code class="language-python">' + "x" * 300 + "</code></pre>"
    na_chunks = split_html(nested_attr, 150)
    assert len(na_chunks) > 1
    for i, chunk in enumerate(na_chunks):
        if '<code' in chunk:
            assert 'class="language-python"' in chunk
        assert len(chunk) <= 150


# -- extract_send_directives --

def test_extract_send_directives_file():
    text, dirs = extract_send_directives("hello\nSEND_FILE: /tmp/foo.txt\nbye")
    assert dirs == [("FILE", "/tmp/foo.txt")]
    assert text == "hello\nbye"

def test_extract_send_directives_none():
    text2, dirs2 = extract_send_directives("no directives here")
    assert dirs2 == []
    assert text2 == "no directives here"

def test_extract_send_directives_image():
    text3, dirs3 = extract_send_directives("SEND_IMAGE: /tmp/img.png")
    assert dirs3 == [("IMAGE", "/tmp/img.png")]


# -- markdown tables --

def test_simple_table():
    simple_table = """\
| Name | Age |
|------|-----|
| Alice | 30 |
| Bob | 25 |"""
    result = md_to_telegram_html(simple_table)
    assert "<pre>" in result
    assert "Alice" in result
    assert "Bob" in result
    assert "|" not in result.replace("</pre>", "").replace("<pre>", "")
    # Columns should be aligned (padded)
    assert "Name " in result
    assert "Age" in result

def test_ragged_table():
    """Ragged table (inconsistent column counts)."""
    ragged = """\
| A | B | C |
|---|---|---|
| 1 | 2 |
| x | y | z |"""
    result2 = md_to_telegram_html(ragged)
    assert "<pre>" in result2
    assert "x" in result2
    assert "y" in result2
    assert "z" in result2

def test_fenced_table_not_converted():
    """Table inside code fence should NOT be converted."""
    fenced_table = """\
```
| Name | Age |
|------|-----|
| Alice | 30 |
```"""
    result3 = md_to_telegram_html(fenced_table)
    assert "|" in result3
    # Should be in a code fence pre, not a table pre
    assert result3.count("<pre>") == 1

def test_no_separator_not_table():
    """No separator row = not a table."""
    not_a_table = "| just | some | pipes |"
    result4 = md_to_telegram_html(not_a_table)
    assert "|" in result4

def test_table_with_surrounding_text():
    mixed = """\
Here is a table:

| Col1 | Col2 |
|------|------|
| a    | b    |

And some more text."""
    result5 = md_to_telegram_html(mixed)
    assert "Here is a table:" in result5
    assert "And some more text." in result5
    assert "<pre>" in result5

def test_table_special_chars_escaped():
    special = """\
| Key | Value |
|-----|-------|
| <script> | x&y |"""
    result6 = md_to_telegram_html(special)
    assert "&lt;script&gt;" in result6
    assert "x&amp;y" in result6


# -- split_html plaintext fallback --

def test_split_html_plaintext_fallback():
    """Deliberately broken HTML that would produce unbalanced chunks."""
    broken = "<b>unclosed " + "x" * 200
    chunks_broken = split_html(broken, 50)
    assert len(chunks_broken) > 1
    for i, c in enumerate(chunks_broken):
        assert len(c) <= 50
    # All chunks should be plain text (tags stripped) since balancing would fail
    has_tags = any("<b>" in c or "</b>" in c for c in chunks_broken)
    # Either properly balanced OR stripped — both are acceptable outcomes
    all_balanced = all(c.count("<b>") == c.count("</b>") for c in chunks_broken)
    assert has_tags is False or all_balanced
