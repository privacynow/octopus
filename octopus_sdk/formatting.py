"""Shared text helpers and formatting ports for runtime flows."""

from __future__ import annotations

import re
from typing import Protocol


class TextFormattingPort(Protocol):
    def summarize_text(self, text: str, limit: int = 240) -> str: ...

SEND_DIRECTIVE_RE = re.compile(r"(?m)^SEND_(FILE|IMAGE):\s*(?P<path>.+?)\s*$")


def trim_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


def summarize_text(text: str, limit: int = 240) -> str:
    clean = " ".join(text.strip().split())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1] + "…"


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
