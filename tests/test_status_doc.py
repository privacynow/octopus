"""Guards for the architecture-remediation status document."""

from pathlib import Path
import re


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
        "## Historical Phase 7 Closure Status",
    )

    for fragment in required_fragments:
        assert fragment in text


def test_status_doc_records_live_phase8_state_and_owners_in_authoritative_section() -> None:
    text = _status_text()
    authoritative = text.rsplit("## Current Authoritative Status", 1)[1]

    required_fragments = (
        "app/channels/telegram/bootstrap.py",
        "app/channels/telegram/ingress.py",
        "app/channels/telegram/session_io.py",
        "app/channels/telegram/worker.py",
        "docs/orchestration_inventory.md",
        "docs/machine_conventions.md",
        "936c502",
        "274c6e4",
        "7804cf4",
        "07af844",
        "837b4ed",
        "a686565",
        "829e9e7",
        "b56473d",
        "0a2a3ef",
        "6c58cae",
        "5a07330",
        "99939f0",
        "dbf9176",
        "584d700",
        "6e7595e",
        "a03a7b8",
        "app/workflows/execution/finalization.py",
    )

    for fragment in required_fragments:
        assert fragment in authoritative

    assert "Architecture remediation is complete." in authoritative
    assert "Feature work may resume." in authoritative
    assert re.search(r"Result: `\d+ passed, 23 skipped`", authoritative)


def test_status_doc_includes_all_phase8_acceptance_gate_fragments() -> None:
    text = _status_text()
    authoritative = text.rsplit("## Current Authoritative Status", 1)[1]

    required_fragments = (
        "Telegram channel runtime state is explicit and instance-owned",
        "Telegram bootstrap owns PTB application construction and route",
        "Telegram-heavy tests exercise the Telegram boundary through explicit",
        "`status.md` and `docs/orchestration_inventory.md` reflect the actual",
        "`ingress.py` is ≤ 1500 lines",
        "No Telegram channel file except `presenters.py` creates",
        "No test file monkeypatches module-level ingress functions for stubbing.",
        "`worker.py` contains no inline workflow logic",
        "`app/workflows/execution/finalization.py` exists and has no",
        "`surface_binding_id` is deleted and blocked by the live vocabulary gate.",
        "Postgres migration `0009_rename_delivery_kinds.sql` exists and renames",
        "Postgres migration `0010_rename_registry_channel_columns.sql` exists and",
        "live app code retains no registry `surface_*` schema/runtime vocabulary",
        "runtime registry delivery handling no longer carries legacy",
    )

    for fragment in required_fragments:
        assert fragment in authoritative


def test_status_doc_historical_and_live_closure_sections_are_both_present() -> None:
    text = _status_text()

    required_fragments = (
        "Historical pre-closure execution notes are preserved below as an audit log",
        "## Historical Phase 7 Closure Status",
        "Phase 7 closure correction is complete.",
        "## Current Authoritative Status",
        "The historical log above is preserved intentionally, including intermediate",
        "42 passed",
        "62 passed",
        "273 passed",
        "64 passed",
        "80 passed",
        "121 passed, 4 skipped",
    )

    for fragment in required_fragments:
        assert fragment in text


def test_status_doc_lede_points_to_live_phase8_closure_and_marks_phase7_as_historical() -> None:
    text = _status_text()

    required_fragments = (
        "The live accepted state is recorded in the final",
        "`## Historical Phase 7 Closure Status` (preserved Phase 7 baseline)",
        "`## Current Authoritative Status` (live post-audit closure state)",
        "The initial Phase 8 closure at",
        "Feature work may resume.",
        "final cap-restore complete:",
    )

    for fragment in required_fragments:
        assert fragment in text
