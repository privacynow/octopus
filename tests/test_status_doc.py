"""Guards for the architecture-remediation status document."""

from pathlib import Path


def _status_text() -> str:
    repo_root = Path(__file__).resolve().parents[1]
    return (repo_root / "status.md").read_text()


def test_status_doc_preserves_historical_log_entries() -> None:
    text = _status_text()

    required_fragments = (
        "This file tracks execution of the **Reopened Architecture Remediation Track**",
        "00379be",
        "Track A / A3: normalize access boundary",
        "Track F / F6: enforce runtime dispatch ownership",
        "Track B / B2c2a: move ingress request rendering into presenters",
        "## Working Rules",
    )

    for fragment in required_fragments:
        assert fragment in text


def test_status_doc_records_final_phase7_state_and_live_owners_in_authoritative_section() -> None:
    text = _status_text()
    authoritative = text.split("## Current Authoritative Status", 1)[1]

    required_fragments = (
        "Phase 7 closure correction is complete.",
        "app/channels/telegram/bootstrap.py",
        "app/channels/telegram/ingress.py",
        "docs/orchestration_inventory.md",
        "docs/machine_conventions.md",
        "bf86331",
        "4166599",
        "0c01b70",
        "78051ae",
        "1616 passed, 23 skipped",
    )

    for fragment in required_fragments:
        assert fragment in authoritative


def test_status_doc_includes_all_phase7_acceptance_gate_fragments() -> None:
    text = _status_text()
    authoritative = text.split("## Current Authoritative Status", 1)[1]

    required_fragments = (
        "Telegram channel runtime state is explicit and instance-owned",
        "Telegram bootstrap owns PTB application construction and route",
        "Telegram-heavy tests exercise the Telegram boundary through explicit",
        "`status.md` and `docs/orchestration_inventory.md` reflect the actual",
    )

    for fragment in required_fragments:
        assert fragment in authoritative


def test_status_doc_historical_and_authoritative_sections_are_both_present() -> None:
    text = _status_text()

    required_fragments = (
        "Historical pre-closure execution notes are preserved below as an audit log",
        "## Current Authoritative Status",
        "The historical log above is preserved intentionally",
        "42 passed",
    )

    for fragment in required_fragments:
        assert fragment in text


def test_status_doc_lede_marks_phase7_closure_section_as_historical_context() -> None:
    text = _status_text()

    required_fragments = (
        "The live execution state for the reopened track is recorded in `## Current State`",
        "`## Current Authoritative Status` (historical Phase 7 baseline)",
        "The remediation track remains open. Phase 8 is in progress",
    )

    for fragment in required_fragments:
        assert fragment in text
