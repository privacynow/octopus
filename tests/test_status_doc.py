"""Guards for the final architecture-remediation status document."""

from pathlib import Path


def _status_text() -> str:
    repo_root = Path(__file__).resolve().parents[1]
    return (repo_root / "status.md").read_text()


def test_status_doc_records_final_phase7_state_and_live_owners() -> None:
    text = _status_text()

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
        "1615 passed, 23 skipped",
    )

    for fragment in required_fragments:
        assert fragment in text


def test_status_doc_includes_all_phase7_acceptance_gate_fragments() -> None:
    text = _status_text()

    required_fragments = (
        "Telegram channel runtime state is explicit and instance-owned",
        "Telegram bootstrap owns PTB application construction and route",
        "Telegram-heavy tests exercise the Telegram boundary through explicit",
        "`status.md` and `docs/orchestration_inventory.md` reflect the actual",
    )

    for fragment in required_fragments:
        assert fragment in text


def test_status_doc_has_no_stale_placeholders_or_reopened_state() -> None:
    text = _status_text()

    forbidden_fragments = (
        "The remediation track is reopened and not complete.",
        "complete in current worktree",
        "Worktree now in progress",
        "Acceptance remains blocked",
    )

    for fragment in forbidden_fragments:
        assert fragment not in text
