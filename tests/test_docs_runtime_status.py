"""Contract tests for architecture/status summaries.

These docs are user/operator-facing summaries of the current runtime and
roadmap baseline. Keep the authoritative summary sections aligned with the
shipped Local Runtime contract and current roadmap phase.
"""

import re
from pathlib import Path


def _section(text: str, heading: str) -> str:
    match = re.search(rf"## {re.escape(heading)}\s+(.*?)(?=\n## |\Z)", text, re.DOTALL)
    assert match, f"Expected section '{heading}'"
    return match.group(1)


def test_architecture_preamble_states_current_local_runtime_baseline():
    """ARCHITECTURE preamble must summarize the current local-runtime baseline."""
    repo = Path(__file__).resolve().parent.parent
    text = (repo / "docs" / "ARCHITECTURE.md").read_text()
    preamble = text.split("\n---\n", 1)[0]
    assert "Current shipped baseline" in preamble
    assert "Phase 15 Slice 1" in preamble
    assert "Local Runtime" in preamble
    assert "SQLite" in preamble and "BOT_DATABASE_URL" in preamble
    assert "Postgres" in preamble
    assert "Shared Runtime" in preamble


def test_architecture_deployment_section_matches_current_runtime_contract():
    """ARCHITECTURE deployment section must describe SQLite-first Local Runtime."""
    repo = Path(__file__).resolve().parent.parent
    text = (repo / "docs" / "ARCHITECTURE.md").read_text()
    deployment = _section(text, "Deployment and dependencies")
    assert "Current runtime contract" in deployment
    assert "Local Runtime is the supported deployment mode" in deployment
    assert "BOT_DATABASE_URL" in deployment
    assert "./scripts/guided_start.sh" in deployment
    assert "./scripts/dev_up_postgres.sh" in deployment
    assert "Phase 12 runtime (shipped today)" not in deployment


def test_status_current_snapshot_matches_current_phase_and_runtime():
    """STATUS Current Snapshot must reflect Phase 15 + Local Runtime, not old Postgres-first wording."""
    repo = Path(__file__).resolve().parent.parent
    text = (repo / "docs" / "STATUS-commercial-polish.md").read_text()
    snapshot = _section(text, "Current Snapshot")
    assert "Phases 1-14 are sealed as shipped." in snapshot
    assert "Phase 15 is the active roadmap phase" in snapshot
    assert "Local Runtime" in snapshot
    assert "SQLite is the default backend" in snapshot
    assert "Postgres is a supported alternate backend" in snapshot
    assert "./scripts/guided_start.sh" in snapshot
    assert "Phase 12 is complete: the **shipped runtime today** uses Postgres" not in snapshot


def test_status_historical_focus_intro_mentions_phase_15_not_phase_14():
    """Historical Execution Focus intro should point readers at the current roadmap phase."""
    repo = Path(__file__).resolve().parent.parent
    text = (repo / "docs" / "STATUS-commercial-polish.md").read_text()
    historical = _section(text, "Historical Execution Focus")
    assert "Phase 15 is in progress" in historical
    assert "Phase 13 is complete and the next numbered phase is Phase 14" not in historical
