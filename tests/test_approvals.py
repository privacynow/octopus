"""Tests for approvals.py — preflight prompt and denial formatting."""

from app.approvals import build_preflight_prompt, format_denials_html


def test_preflight_prompt_has_sections():
    prompt = build_preflight_prompt("list files in /tmp", "claude")
    assert "## Tool use" in prompt
    assert "## Planned actions" in prompt
    assert "## Approval advice" in prompt


def test_preflight_prompt_includes_user_request():
    prompt = build_preflight_prompt("list files in /tmp", "claude")
    assert "list files in /tmp" in prompt


def test_preflight_prompt_includes_provider():
    prompt = build_preflight_prompt("list files in /tmp", "claude")
    assert "claude" in prompt


def test_preflight_prompt_codex_provider():
    prompt = build_preflight_prompt("hello", "codex")
    assert "codex" in prompt


def test_denial_html_contains_tool_info():
    html = format_denials_html([{"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}}])
    assert "<b>Bash</b>" in html
    assert "rm -rf" in html


def test_denial_html_empty():
    assert format_denials_html([]) == ""
