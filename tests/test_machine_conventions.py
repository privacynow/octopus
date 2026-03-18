"""Guards for the committed machine-standard document."""

from pathlib import Path


def _conventions_text() -> str:
    repo_root = Path(__file__).resolve().parents[1]
    return (repo_root / "docs" / "machine_conventions.md").read_text()


def test_machine_conventions_define_functional_decision_machine_standard() -> None:
    text = _conventions_text()

    required_fragments = (
        "functional",
        "decision-machine",
        "app/workflows/lifecycle_machine.py",
        "snapshot",
        "action",
        "decision",
        "effects",
        "atomic application at the store or session boundary",
        "python-statemachine",
        "migration-state only",
    )

    lowered = text.lower()
    for fragment in required_fragments:
        assert fragment.lower() in lowered


def test_machine_conventions_forbid_new_machine_style_drift() -> None:
    text = _conventions_text().lower()

    assert "introducing a third explicit machine style" in text
    assert "no new `python-statemachine` machine may be added".lower() in text
    assert "callback-driven mutable machines as a new standard" in text
