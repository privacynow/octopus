"""Telegram-channel presentation helpers."""

from __future__ import annotations


def extract_summary(text: str, max_lines: int = 4) -> tuple[str, str]:
    lines = [line for line in (text or "").splitlines() if line.strip()]
    if not lines:
        return ("", "")
    summary_lines = lines[:max_lines]
    summary = "\n".join(summary_lines)
    detail = "\n".join(lines[max_lines:]).strip()
    return (summary, detail)
