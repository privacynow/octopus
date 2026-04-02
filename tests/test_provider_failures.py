from pathlib import Path

from app.execution_faults import LocalExecutionFaultState
from app.provider_failures import classify_provider_failure


def test_classify_provider_failure_marks_login_errors_irrecoverable() -> None:
    result = classify_provider_failure(
        "claude",
        "Not logged in · Please run /login",
        returncode=1,
    )

    assert result.is_irrecoverable is True
    assert result.fault_kind == "provider_auth"
    assert result.fault_code == "authentication_required"


def test_classify_provider_failure_marks_session_busy_transient() -> None:
    result = classify_provider_failure(
        "claude",
        "Session ID 123 is already in use.",
        returncode=1,
    )

    assert result.is_irrecoverable is False
    assert result.fault_kind == "concurrency"
    assert result.fault_code == "session_busy"


def test_local_execution_fault_state_only_latches_irrecoverable_errors(tmp_path: Path) -> None:
    faults = LocalExecutionFaultState(tmp_path)

    busy = faults.record_provider_failure(
        provider_name="claude",
        error_text="Session ID 123 is already in use.",
        returncode=1,
    )
    auth = faults.record_provider_failure(
        provider_name="claude",
        error_text="Not logged in · Please run /login",
        returncode=1,
    )

    assert busy is None
    assert auth is not None
    assert auth.state == "faulted"
    assert auth.fault_kind == "provider_auth"
