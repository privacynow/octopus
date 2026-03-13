"""Contract tests: README Commands section must not document non-existent commands.

Milestone E: the command table is user-facing documentation. It must only list
commands that exist (registered CommandHandlers). /retry and /clear were removed
because they do not exist as top-level commands (retry is via inline buttons;
conversation clear is /new).
"""

import re
from pathlib import Path


def test_readme_commands_section_does_not_list_retry_or_clear():
    """README must not document /retry or /clear as top-level commands."""
    repo = Path(__file__).resolve().parent.parent
    readme = repo / "README.md"
    assert readme.exists()
    text = readme.read_text()
    # Commands section: from "## Commands" to next "## " or end
    match = re.search(r"## Commands\s+(.*?)(?=\n## |\Z)", text, re.DOTALL)
    assert match, "README should have a Commands section"
    commands_section = match.group(1)
    # Must not list /retry or /clear as command rows (| `/retry` or | `/clear`)
    assert "| `/retry`" not in commands_section, (
        "README must not list /retry (no such command; retry is via inline buttons)"
    )
    assert "| `/clear`" not in commands_section, (
        "README must not list /clear (no such command; conversation clear is /new)"
    )


def test_readme_commands_section_includes_settings():
    """README Commands section must include /settings for discoverability."""
    repo = Path(__file__).resolve().parent.parent
    readme = repo / "README.md"
    text = readme.read_text()
    match = re.search(r"## Commands\s+(.*?)(?=\n## |\Z)", text, re.DOTALL)
    assert match
    commands_section = match.group(1)
    assert "| `/settings`" in commands_section or "/settings" in commands_section, (
        "README Commands section must include /settings"
    )
