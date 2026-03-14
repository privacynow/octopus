"""Contract tests for operator scripts (Milestone E Bucket A).

Assert script content and output contracts so operator-path changes
don't remove or weaken provider vs full-doctor distinction.
"""

from pathlib import Path


def test_provider_status_reminds_full_doctor():
    """provider_status.sh must remind operator to run full app doctor on success."""
    repo = Path(__file__).resolve().parent.parent
    script = repo / "scripts" / "provider_status.sh"
    assert script.exists()
    text = script.read_text()
    assert "full app health" in text or "app.main --doctor" in text, (
        "provider_status.sh must tell operator how to run full app health (provider-only is not full health)"
    )
    assert "no DB" in text or "no DB/Telegram" in text, (
        "provider_status.sh must state it does not check DB (and optionally Telegram)"
    )


def test_provider_status_requires_env_bot():
    """provider_status.sh (or its sourced lib) must tell operator to create .env.bot when missing."""
    repo = Path(__file__).resolve().parent.parent
    script = repo / "scripts" / "provider_status.sh"
    lib_env = repo / "scripts" / "lib_env.sh"
    script_text = script.read_text()
    assert ".env.bot" in script_text
    # Message may live in script or in sourced lib_env.sh
    script_has_message = "Create .env.bot" in script_text or "create .env.bot" in script_text.lower()
    lib_has_message = (
        lib_env.read_text().count("Create .env.bot") >= 1 or "create .env.bot" in lib_env.read_text().lower()
    )
    assert script_has_message or lib_has_message, (
        "provider_status.sh or scripts/lib_env.sh must tell operator to create .env.bot when missing"
    )
