"""Guards for the committed orchestration inventory."""

from pathlib import Path


def _inventory_text() -> str:
    repo_root = Path(__file__).resolve().parents[1]
    return (repo_root / "docs" / "orchestration_inventory.md").read_text()


def test_orchestration_inventory_lists_required_concerns_and_files() -> None:
    text = _inventory_text()

    required_fragments = (
        "Lifecycle",
        "Pending Approval / Retry",
        "Transport Recovery",
        "Credential / Setup Progression",
        "Delegation Progression",
        "Request Execution / Preflight",
        "app/workflows/runtime_skills/setup.py",
        "app/skill_lifecycle_service.py",
        "app/credential_flow.py",
        "app/agents/orchestration.py",
        "app/agents/delegation.py",
        "app/runtime/dispatch.py",
    )

    for fragment in required_fragments:
        assert fragment in text


def test_orchestration_inventory_uses_only_declared_classifications() -> None:
    text = _inventory_text()

    assert "Classification: `explicit machine required`" in text
    assert "Classification: `misplaced orchestration that must move`" in text
    assert text.count("Classification: `procedural workflow acceptable`") == 0
    assert "TBD" not in text
    assert "TODO" not in text
    assert "unclassified" not in text.lower()
