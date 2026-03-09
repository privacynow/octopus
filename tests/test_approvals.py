"""Tests for approvals.py — preflight prompt, pending request, denials."""

import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))

from app.approvals import (
    build_preflight_prompt,
    clear_pending_request,
    format_denials_html,
    serialize_pending_request,
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

# -- serialize_pending_request --
print("\n=== serialize_pending_request ===")
pending = serialize_pending_request("do thing", ["/tmp/img.png"], [{"path": "/tmp/img.png", "is_image": True}])
check("prompt", pending["prompt"], "do thing")
check("image_paths", pending["image_paths"], ["/tmp/img.png"])
check("attachments", len(pending["attachments"]), 1)

# -- clear_pending_request --
print("\n=== clear_pending_request ===")
session = {"pending_request": {"prompt": "x"}, "other": "data"}
cleared = clear_pending_request(session)
check("cleared", cleared["pending_request"], None)
check("other preserved", cleared["other"], "data")

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
