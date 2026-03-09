"""Tests for approvals.py — preflight prompt and denial formatting."""

import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))

from app.approvals import (
    build_preflight_prompt,
    format_denials_html,
)
from tests.support.assertions import Checks

checks = Checks()
check = checks.check
check_contains = checks.check_contains


# -- build_preflight_prompt --
print("\n=== build_preflight_prompt ===")
prompt = build_preflight_prompt("list files in /tmp", "claude")
check_contains("has sections", prompt, "## Tool use", "## Planned actions", "## Approval advice")
check_contains("has user request", prompt, "list files in /tmp")
check_contains("has provider name", prompt, "claude")

prompt2 = build_preflight_prompt("hello", "codex")
check_contains("codex provider", prompt2, "codex")

# -- format_denials_html --
print("\n=== format_denials_html ===")
html = format_denials_html([{"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}}])
check_contains("denial html", html, "<b>Bash</b>", "rm -rf")

empty = format_denials_html([])
check("empty denials", empty, "")

# -- Summary --
print(f"\n{'='*40}")
print(f"  {checks.passed} passed, {checks.failed} failed")
print(f"{'='*40}")
sys.exit(1 if checks.failed else 0)
