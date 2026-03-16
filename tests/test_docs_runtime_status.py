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
    assert "Phase 20" in preamble
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
    assert "./scripts/app/guided_start.sh" in deployment
    assert "./scripts/db/dev_up_postgres.sh" in deployment
    assert "Phase 12 runtime (shipped today)" not in deployment


def test_status_current_snapshot_matches_current_phase_and_runtime():
    """STATUS Current Snapshot must reflect Phase 20 + Local Runtime, not the old Phase 15 baseline."""
    repo = Path(__file__).resolve().parent.parent
    text = (repo / "docs" / "status.md").read_text()
    snapshot = _section(text, "Current Snapshot")
    assert "Phases 1-15 are sealed as shipped." in snapshot
    assert "Phase 20 is the shipped product baseline." in snapshot
    assert "Phases 16-19 remain on the roadmap and are deferred beyond Phase 20." in snapshot
    assert "Local Runtime" in snapshot
    assert "SQLite is the default backend" in snapshot
    assert "Postgres is a supported alternate backend" in snapshot
    assert "./scripts/app/guided_start.sh" in snapshot
    assert "Phase 12 is complete: the **shipped runtime today** uses Postgres" not in snapshot
    assert "M10 is complete" in snapshot


def test_status_historical_focus_intro_mentions_phase_20():
    """Historical Execution Focus intro should point readers at the current Phase 20 roadmap state."""
    repo = Path(__file__).resolve().parent.parent
    text = (repo / "docs" / "status.md").read_text()
    historical = _section(text, "Historical Execution Focus")
    assert "Phase 20 is complete" in historical
    assert "Phases 16-19 remain\ndeferred beyond it" in historical or "Phases 16-19 remain deferred beyond it" in historical
    assert "Phase 15 is in progress" not in historical
