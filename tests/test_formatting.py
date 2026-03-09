"""Tests for formatting.py — markdown converter, text splitting, send directives."""

import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))

from app.formatting import extract_send_directives, md_to_telegram_html, split_html, trim_text
from tests.support.assertions import Checks

checks = Checks()
check = checks.check
check_contains = checks.check_contains


# -- trim_text --
print("\n=== trim_text ===")
check("short", trim_text("hello", 10), "hello")
check("exact", trim_text("hello", 5), "hello")
check("truncate", trim_text("hello world", 8), "hello...")

# -- md_to_telegram_html --
print("\n=== md_to_telegram_html ===")
check("bold", md_to_telegram_html("**bold**"), "<b>bold</b>")
check("italic", md_to_telegram_html("*italic*"), "<i>italic</i>")
check("bold+italic", md_to_telegram_html("**bold** and *italic*"), "<b>bold</b> and <i>italic</i>")
check("header", md_to_telegram_html("# Header"), "<b>Header</b>")
check("h3", md_to_telegram_html("### Sub"), "<b>Sub</b>")
check("inline code", md_to_telegram_html("use `foo()` here"), "use <code>foo()</code> here")
check("strike", md_to_telegram_html("~~removed~~"), "<s>removed</s>")
check("link", md_to_telegram_html("[click](https://x.com)"), '<a href="https://x.com">click</a>')
check("html escape", md_to_telegram_html("a < b & c > d"), "a &lt; b &amp; c &gt; d")
check("underscore bold", md_to_telegram_html("__bold__"), "<b>bold</b>")

cb = md_to_telegram_html("```python\nprint('hi')\n```")
check_contains("fenced code block", cb, "<pre>", "language-python", "print", "</code></pre>")

cb_nolang = md_to_telegram_html("```\nplain code\n```")
check_contains("fenced no lang", cb_nolang, "<pre>", "plain code", "</pre>")
check("fenced no lang omits language class", "language-" in cb_nolang, False)

mixed = md_to_telegram_html("**bold with `code` inside**")
check_contains("bold+code", mixed, "<b>", "<code>code</code>")

dangerous = md_to_telegram_html("`<script>alert(1)</script>`")
check_contains("code html escape", dangerous, "<code>&lt;script&gt;")

multi = md_to_telegram_html("# Title\n\nSome **bold** text\n\n```\ncode\n```\n\nEnd.")
check_contains("multi-line", multi, "<b>Title</b>", "<b>bold</b>", "<pre>", "code", "End.")

check("plain text", md_to_telegram_html("hello world"), "hello world")

result = md_to_telegram_html("some_variable_name")
check("underscore in word", result, "some_variable_name")

# -- split_html --
print("\n=== split_html ===")
check("short", split_html("hi", 10), ["hi"])
check("exact", split_html("x" * 4096, 4096), ["x" * 4096])
chunks = split_html("line1\nline2\nline3", 10)
check("splits needed", len(chunks) > 1, True)

# Balanced HTML: a <pre> block that spans across chunks
long_code = "<pre>" + "x" * 100 + "</pre>"
chunks_pre = split_html(long_code, 60)
check("pre split: multiple chunks", len(chunks_pre) > 1, True)
# Every chunk must have balanced <pre> tags
for i, chunk in enumerate(chunks_pre):
    opens = chunk.count("<pre>")
    closes = chunk.count("</pre>")
    check(f"pre chunk {i} balanced", opens, closes)

# Nested tags: <b> inside <pre>
nested = "<pre><b>" + "y" * 100 + "</b></pre>"
chunks_nested = split_html(nested, 60)
check("nested split: multiple chunks", len(chunks_nested) > 1, True)
for i, chunk in enumerate(chunks_nested):
    for tag in ["pre", "b"]:
        opens = chunk.count(f"<{tag}>")
        closes = chunk.count(f"</{tag}>")
        check(f"nested chunk {i} <{tag}> balanced", opens, closes)

# Continuation: second chunk reopens tags from first
check("continuation reopens <pre>", chunks_pre[1].startswith("<pre>"), True)

# Already-closed tags should not be re-closed
closed_html = "<b>bold</b>\n" * 20
chunks_closed = split_html(closed_html, 50)
for i, chunk in enumerate(chunks_closed):
    opens = chunk.count("<b>")
    closes = chunk.count("</b>")
    check(f"closed chunk {i} balanced", opens, closes)

# Real-world: md_to_telegram_html output with a long code block
long_md = "# Title\n\n```python\n" + "print('hello')\n" * 300 + "```\n\nDone."
long_html = md_to_telegram_html(long_md)
real_chunks = split_html(long_html, 4096)
check("real-world: splits needed", len(real_chunks) > 1, True)
for i, chunk in enumerate(real_chunks):
    for tag in ["pre", "code"]:
        opens = chunk.count(f"<{tag}")  # <code or <code class=...>
        closes = chunk.count(f"</{tag}>")
        check(f"real chunk {i} <{tag}> balanced", opens, closes)

# STRICT SIZE LIMIT: every chunk must be <= limit, including closing tags
for i, chunk in enumerate(real_chunks):
    check(f"real chunk {i} within 4096", len(chunk) <= 4096, True)

# Test with a tighter limit to stress the suffix reservation
tight_chunks = split_html(long_html, 200)
check("tight split: many chunks", len(tight_chunks) > 5, True)
for i, chunk in enumerate(tight_chunks):
    check(f"tight chunk {i} within 200", len(chunk) <= 200, True)
    for tag in ["pre", "code"]:
        opens = chunk.count(f"<{tag}")
        closes = chunk.count(f"</{tag}>")
        check(f"tight chunk {i} <{tag}> balanced", opens, closes)

# ATTRIBUTE PRESERVATION: links should keep their href across chunks
long_link = '<a href="https://example.com/very/long/path">' + "click " * 500 + "</a>"
link_chunks = split_html(long_link, 200)
check("link split: multiple chunks", len(link_chunks) > 1, True)
for i, chunk in enumerate(link_chunks):
    if "<a " in chunk or "<a>" in chunk:
        # Every <a> tag must have the href attribute
        check(f"link chunk {i} has href", 'href="https://example.com/very/long/path"' in chunk, True)
    check(f"link chunk {i} within 200", len(chunk) <= 200, True)
    opens = chunk.count("<a ")  # opening tags with attributes
    if opens == 0:
        opens = chunk.count("<a>")  # should not happen — would mean lost attributes
    closes = chunk.count("</a>")
    check(f"link chunk {i} <a> balanced", opens, closes)

# Nested link in pre: attributes preserved on both
nested_attr = '<pre><code class="language-python">' + "x" * 300 + "</code></pre>"
na_chunks = split_html(nested_attr, 150)
check("nested attr: multiple chunks", len(na_chunks) > 1, True)
for i, chunk in enumerate(na_chunks):
    if '<code' in chunk:
        check(f"nested attr chunk {i} has class", 'class="language-python"' in chunk, True)
    check(f"nested attr chunk {i} within 150", len(chunk) <= 150, True)

# -- extract_send_directives --
print("\n=== extract_send_directives ===")
text, dirs = extract_send_directives("hello\nSEND_FILE: /tmp/foo.txt\nbye")
check("directive extracted", dirs, [("FILE", "/tmp/foo.txt")])
check("text cleaned", text, "hello\nbye")

text2, dirs2 = extract_send_directives("no directives here")
check("no directives", dirs2, [])
check("text unchanged", text2, "no directives here")

text3, dirs3 = extract_send_directives("SEND_IMAGE: /tmp/img.png")
check("image directive", dirs3, [("IMAGE", "/tmp/img.png")])

# -- markdown tables --
print("\n=== markdown tables ===")

simple_table = """\
| Name | Age |
|------|-----|
| Alice | 30 |
| Bob | 25 |"""
result = md_to_telegram_html(simple_table)
check_contains("simple table is pre", result, "<pre>")
check_contains("simple table has alice", result, "Alice")
check_contains("simple table has bob", result, "Bob")
check("simple table no pipes", "|" not in result.replace("</pre>", "").replace("<pre>", ""), True)
# Columns should be aligned (padded)
check_contains("simple table aligned", result, "Name ", "Age")

# Ragged table (inconsistent column counts)
ragged = """\
| A | B | C |
|---|---|---|
| 1 | 2 |
| x | y | z |"""
result2 = md_to_telegram_html(ragged)
check_contains("ragged table is pre", result2, "<pre>")
check_contains("ragged table has data", result2, "x", "y", "z")

# Table inside code fence should NOT be converted
fenced_table = """\
```
| Name | Age |
|------|-----|
| Alice | 30 |
```"""
result3 = md_to_telegram_html(fenced_table)
check_contains("fenced table has pipes", result3, "|")
# Should be in a code fence pre, not a table pre
check("fenced table not double-converted", result3.count("<pre>"), 1)

# No separator row = not a table
not_a_table = "| just | some | pipes |"
result4 = md_to_telegram_html(not_a_table)
check_contains("no separator not converted", result4, "|")

# Table with surrounding text
mixed = """\
Here is a table:

| Col1 | Col2 |
|------|------|
| a    | b    |

And some more text."""
result5 = md_to_telegram_html(mixed)
check_contains("mixed has surrounding text", result5, "Here is a table:", "And some more text.")
check_contains("mixed has table content", result5, "<pre>")

# Special chars in table cells are escaped
special = """\
| Key | Value |
|-----|-------|
| <script> | x&y |"""
result6 = md_to_telegram_html(special)
check_contains("special chars escaped", result6, "&lt;script&gt;", "x&amp;y")

# -- split_html plaintext fallback --
print("\n=== split_html plaintext fallback ===")
# Deliberately broken HTML that would produce unbalanced chunks
broken = "<b>unclosed " + "x" * 200
chunks_broken = split_html(broken, 50)
check("broken html splits", len(chunks_broken) > 1, True)
for i, c in enumerate(chunks_broken):
    check(f"broken chunk {i} within limit", len(c) <= 50, True)
# All chunks should be plain text (tags stripped) since balancing would fail
has_tags = any("<b>" in c or "</b>" in c for c in chunks_broken)
# Either properly balanced OR stripped — both are acceptable outcomes
all_balanced = all(c.count("<b>") == c.count("</b>") for c in chunks_broken)
check("broken html either balanced or stripped", has_tags is False or all_balanced, True)

checks.run_and_exit()
