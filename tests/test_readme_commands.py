"""Contract tests: README commands section matches the simplified user-facing contract.

The README intentionally documents a practical subset for first-time users
(Most Useful Commands). Tests enforce that contract: the section exists, uses
the allowed title, includes the simplified command set, and must NOT list
removed/non-top-level commands (/retry, /clear).
"""

import re
from pathlib import Path


# Section title: shipped README uses "Most Useful Commands"; allow "Commands" as fallback.
_COMMANDS_SECTION_RE = re.compile(
    r"## (?:Most Useful Commands|Commands)\s+(.*?)(?=\n## |\Z)",
    re.DOTALL,
)


def _get_commands_section(readme_path: Path) -> str | None:
    """Extract the user-facing commands section. Returns None if not found."""
    text = readme_path.read_text()
    m = _COMMANDS_SECTION_RE.search(text)
    return m.group(1) if m else None


# Simplified set the README is required to document (product contract).
_REQUIRED_COMMANDS = [
    "/start",
    "/help",
    "/approval",
    "/approve",
    "/reject",
    "/cancel",
    "/send <path>",
    "/skills",
    "/skills list",
    "/skills add <name>",
    "/skills setup <name>",
    "/settings",
    "/session",
    "/doctor",
]

# Must NOT appear as top-level commands (retry is via buttons; clear is /new).
_FORBIDDEN_AS_COMMANDS = ["/retry", "/clear"]


def test_readme_has_user_facing_commands_section():
    """README must contain a user-facing commands section (Most Useful Commands or Commands)."""
    repo = Path(__file__).resolve().parent.parent
    readme = repo / "README.md"
    assert readme.exists()
    section = _get_commands_section(readme)
    assert section is not None, (
        "README should have a user-facing commands section titled "
        '"## Most Useful Commands" or "## Commands"'
    )


def test_readme_commands_section_does_not_list_retry_or_clear():
    """README must not document /retry or /clear as top-level commands."""
    repo = Path(__file__).resolve().parent.parent
    readme = repo / "README.md"
    section = _get_commands_section(readme)
    assert section is not None
    for forbidden in _FORBIDDEN_AS_COMMANDS:
        assert f"| `{forbidden}`" not in section, (
            f"README must not list {forbidden} (no such top-level command)"
        )


def test_readme_commands_section_includes_simplified_set():
    """README commands section must include the simplified practical command set."""
    repo = Path(__file__).resolve().parent.parent
    readme = repo / "README.md"
    section = _get_commands_section(readme)
    assert section is not None
    # Core identifiers that must appear (table may use | `/cmd` | or similar)
    required_parts = [
        "/start", "/help", "approval", "/approve", "/reject", "/cancel",
        "/send", "/skills", "skills list", "skills add", "skills setup",
        "/settings", "/session", "/doctor",
    ]
    for part in required_parts:
        assert part in section, (
            f"README commands section must include {part!r} (simplified contract)"
        )


def test_readme_commands_section_includes_settings():
    """README commands section must include /settings (Bucket B discoverability)."""
    repo = Path(__file__).resolve().parent.parent
    readme = repo / "README.md"
    section = _get_commands_section(readme)
    assert section is not None
    assert "/settings" in section


def test_readme_commands_section_includes_session():
    """README commands section must include /session (Bucket B discoverability)."""
    repo = Path(__file__).resolve().parent.parent
    readme = repo / "README.md"
    section = _get_commands_section(readme)
    assert section is not None
    assert "/session" in section


def test_readme_commands_section_includes_doctor():
    """README commands section must include /doctor for health check discoverability."""
    repo = Path(__file__).resolve().parent.parent
    readme = repo / "README.md"
    section = _get_commands_section(readme)
    assert section is not None
    assert "/doctor" in section
