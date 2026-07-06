"""Shared security validation for Claude CLI configuration input."""

from __future__ import annotations

ALLOWED_CLAUDE_EFFORTS = frozenset(
    {
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
    }
)


def _allowed_effort_text() -> str:
    return ", ".join(sorted(ALLOWED_CLAUDE_EFFORTS))


def validate_claude_effort(value: str) -> str:
    effort = value.strip()
    if not effort:
        return ""
    if effort not in ALLOWED_CLAUDE_EFFORTS:
        raise ValueError(
            f"CLAUDE_EFFORT must be one of {_allowed_effort_text()}, got '{value}'"
        )
    return effort
