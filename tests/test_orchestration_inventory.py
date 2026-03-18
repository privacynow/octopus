"""Guards for the committed orchestration inventory."""

from pathlib import Path


def _inventory_text() -> str:
    repo_root = Path(__file__).resolve().parents[1]
    return (repo_root / "docs" / "orchestration_inventory.md").read_text()


def test_orchestration_inventory_lists_required_concerns_and_files() -> None:
    text = _inventory_text()

    required_fragments = (
        "Channel Entry Boundaries",
        "app/channels/telegram/bootstrap.py",
        "app/channels/telegram/ingress.py",
        "Lifecycle",
        "Pending Approval / Retry",
        "Transport Recovery",
        "Credential / Setup Progression",
        "Delegation Progression",
        "Request Execution / Preflight",
        "app/workflows/runtime_skills/setup.py",
        "app/credential_flow.py",
        "app/workflows/delegation/machine.py",
        "app/workflows/delegation/coordination.py",
        "app/workflows/delegation/contracts.py",
        "app/agents/delegation.py",
        "app/runtime/dispatch.py",
        "app/workflows/execution/requests.py",
    )

    for fragment in required_fragments:
        assert fragment in text


def test_orchestration_inventory_uses_only_declared_classifications() -> None:
    text = _inventory_text()

    assert "Classification: `explicit machine required`" in text
    assert "Classification: `procedural workflow acceptable`" in text
    assert "Classification: `misplaced orchestration that must move`" not in text
    assert "TBD" not in text
    assert "TODO" not in text
    assert "unclassified" not in text.lower()


def test_orchestration_inventory_names_only_live_owners() -> None:
    text = _inventory_text()
    forbidden_fragments = (
        "app/channels/telegram/routing.py",
        "app/agents/orchestration.py",
        "app/skill_lifecycle_service.py",
        "app/workflows/pending_request.py",
        "app/workflows/transport_recovery.py",
    )
    for fragment in forbidden_fragments:
        assert fragment not in text
