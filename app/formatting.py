"""Markdown-to-Telegram HTML conversion, text splitting, and trimming."""

import html
import re

SEND_DIRECTIVE_RE = re.compile(r"(?m)^SEND_(FILE|IMAGE):\s*(?P<path>.+?)\s*$")


def trim_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


def md_to_telegram_html(text: str) -> str:
    """Convert common GitHub-flavored markdown into Telegram-safe HTML."""
    blocks: list[str] = []

    def stash_fenced(m: re.Match) -> str:
        lang = m.group(1) or ""
        code = html.escape(m.group(2))
        if lang:
            blocks.append(
                f'<pre><code class="language-{html.escape(lang)}">'
                f"{code}</code></pre>"
            )
        else:
            blocks.append(f"<pre>{code}</pre>")
        return f"\x00BLOCK{len(blocks) - 1}\x00"

    def stash_inline(m: re.Match) -> str:
        code = html.escape(m.group(1))
        blocks.append(f"<code>{code}</code>")
        return f"\x00BLOCK{len(blocks) - 1}\x00"

    text = re.sub(r"```(\w*)\n(.*?)```", stash_fenced, text, flags=re.DOTALL)

    # Convert markdown tables to aligned <pre> blocks (after code fences are
    # stashed so tables inside fences are left alone).
    def stash_table(m: re.Match) -> str:
        raw = m.group(0)
        rows = [line.strip().strip("|").split("|") for line in raw.splitlines()]
        rows = [[cell.strip() for cell in row] for row in rows]
        # Drop the separator row (second row, all dashes/colons)
        if len(rows) >= 2 and all(
            re.fullmatch(r":?-+:?", cell) for cell in rows[1] if cell
        ):
            rows = rows[:1] + rows[2:]
        if not rows:
            return raw
        ncols = max(len(r) for r in rows)
        rows = [r + [""] * (ncols - len(r)) for r in rows]
        widths = [max(len(r[c]) for r in rows) for c in range(ncols)]
        lines = []
        for r in rows:
            cells = [r[c].ljust(widths[c]) for c in range(ncols)]
            lines.append("  ".join(cells).rstrip())
        blocks.append(f"<pre>{html.escape(chr(10).join(lines))}</pre>")
        return f"\x00BLOCK{len(blocks) - 1}\x00"

    table_re = re.compile(
        r"(?m)"
        r"^[^\n]*\|[^\n]*\n"         # header row (must contain |)
        r"[|\s:-]*---[|\s:.-]*\n"     # separator row (must contain ---)
        r"(?:[^\n]*\|[^\n]*\n?)*"     # data rows (must contain |)
    )
    text = table_re.sub(stash_table, text)

    text = re.sub(r"`([^`\n]+)`", stash_inline, text)
    text = html.escape(text)
    text = re.sub(r"^#{1,6}\s+(.+)$", r"<b>\1</b>", text, flags=re.MULTILINE)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__(.+?)__", r"<b>\1</b>", text)
    text = re.sub(r"\*(.+?)\*", r"<i>\1</i>", text)
    text = re.sub(r"(?<!\w)_(.+?)_(?!\w)", r"<i>\1</i>", text)
    text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)

    for i, block in enumerate(blocks):
        placeholder = f"\x00BLOCK{i}\x00"
        text = text.replace(placeholder, block)
        text = text.replace(html.escape(placeholder), block)
    return text


def _track_open_tags(html_text: str) -> list[tuple[str, str]]:
    """Return the stack of unclosed HTML tags as (tag_name, full_open_tag) tuples.

    full_open_tag includes attributes, e.g. '<a href="https://example.com">'.
    """
    open_tag_re = re.compile(r"<(\w+)(?:\s[^>]*)?>")
    close_tag_re = re.compile(r"</(\w+)>")
    stack: list[tuple[str, str]] = []
    pos = 0
    while pos < len(html_text):
        open_m = open_tag_re.search(html_text, pos)
        close_m = close_tag_re.search(html_text, pos)
        if not open_m and not close_m:
            break
        open_start = open_m.start() if open_m else len(html_text)
        close_start = close_m.start() if close_m else len(html_text)
        if open_start <= close_start and open_m:
            stack.append((open_m.group(1), open_m.group(0)))
            pos = open_m.end()
        elif close_m:
            tag = close_m.group(1)
            for i in range(len(stack) - 1, -1, -1):
                if stack[i][0] == tag:
                    stack.pop(i)
                    break
            pos = close_m.end()
        else:
            break
    return stack


def _strip_tags(text: str) -> str:
    """Remove all HTML tags, returning plain text."""
    return re.sub(r"<[^>]*>", "", text)


def _validate_chunk(chunk: str) -> bool:
    """Return True if the chunk has balanced HTML tags."""
    return len(_track_open_tags(chunk)) == 0


def split_html(text: str, limit: int = 4096) -> list[str]:
    """Split HTML text into chunks that each have balanced tags.

    Closes any open tags at the end of each chunk and reopens them
    (with original attributes) at the start of the next chunk.
    Every emitted chunk is guaranteed to be <= limit characters.

    If the tag-balancing pass produces invalid chunks, falls back to
    stripping all HTML and splitting as plain text.
    """
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    remainder = text
    # Tags to reopen at next chunk start: list of (tag_name, full_open_tag)
    carry_open: list[tuple[str, str]] = []
    while remainder:
        # Build prefix (reopened tags) and estimate suffix (closing tags)
        prefix = "".join(full_tag for _, full_tag in carry_open)
        # Worst-case suffix: close all carried tags + any new ones in this chunk.
        # We reserve space for at least the carried tags' closing.
        suffix_reserve = sum(len(f"</{name}>") for name, _ in carry_open)
        budget = limit - len(prefix) - suffix_reserve
        if budget < 1:
            # Degenerate case: tags themselves exceed limit; skip balancing
            budget = limit
            prefix = ""
            suffix_reserve = 0
            carry_open = []

        if len(prefix) + len(remainder) + suffix_reserve <= limit:
            # Everything fits — close any remaining open tags
            full = prefix + remainder
            open_tags = _track_open_tags(full)
            suffix = "".join(f"</{name}>" for name, _ in reversed(open_tags))
            chunks.append(full + suffix)
            break

        # Find a cut point within budget
        cut = remainder.rfind("\n", 0, budget)
        if cut < budget // 2:
            cut = budget
        chunk_body = remainder[:cut]
        full_chunk = prefix + chunk_body

        # Close any tags left open in this chunk
        open_tags = _track_open_tags(full_chunk)
        suffix = "".join(f"</{name}>" for name, _ in reversed(open_tags))

        # If suffix makes us exceed limit, pull back the cut point
        while len(full_chunk) + len(suffix) > limit and cut > 1:
            cut -= 1
            chunk_body = remainder[:cut]
            full_chunk = prefix + chunk_body
            open_tags = _track_open_tags(full_chunk)
            suffix = "".join(f"</{name}>" for name, _ in reversed(open_tags))

        # Guard: ensure we always make progress to avoid infinite loops
        if cut < 1:
            cut = max(1, budget)
            chunk_body = remainder[:cut]
            full_chunk = prefix + chunk_body
            open_tags = _track_open_tags(full_chunk)
            suffix = "".join(f"</{name}>" for name, _ in reversed(open_tags))

        chunks.append(full_chunk + suffix)
        carry_open = open_tags
        remainder = remainder[cut:].lstrip("\n")

    # Post-split validation: if any chunk has unbalanced tags, fall back to
    # plain text splitting to avoid sending malformed HTML to Telegram.
    if any(not _validate_chunk(c) for c in chunks):
        plain = _strip_tags(text)
        chunks = []
        while plain:
            cut = plain.rfind("\n", 0, limit)
            if cut < limit // 2:
                cut = limit
            chunks.append(plain[:cut])
            plain = plain[cut:].lstrip("\n")

    return chunks


def extract_send_directives(text: str) -> tuple[str, list[tuple[str, str]]]:
    directives: list[tuple[str, str]] = []
    cleaned: list[str] = []
    for line in text.splitlines():
        m = SEND_DIRECTIVE_RE.match(line.strip())
        if m:
            directives.append((m.group(1), m.group("path").strip()))
        else:
            cleaned.append(line)
    return "\n".join(cleaned).strip(), directives
