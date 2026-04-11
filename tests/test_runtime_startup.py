import pytest

from app.runtime.startup import initialize_runtime_startup, validate_provider_runtime_requirements
from tests.support.config_support import make_config
from tests.support.handler_support import FakeProvider


def test_validate_provider_runtime_requirements_rejects_unsupported_codex_sandbox(monkeypatch) -> None:
    cfg = make_config(provider_name="codex", approval_mode="on")
    monkeypatch.setattr(
        "app.runtime.startup.codex_sandbox_support_error",
        lambda config, approval_mode: (
            "Approval mode 'on' requires Codex sandboxing, but this host cannot provide it: nope"
        ),
    )

    with pytest.raises(SystemExit):
        validate_provider_runtime_requirements(cfg)


def test_initialize_runtime_startup_allows_approval_off_without_sandbox(monkeypatch) -> None:
    cfg = make_config(provider_name="codex", approval_mode="off")
    provider = FakeProvider("codex")

    monkeypatch.setattr("app.runtime.startup.initialize_runtime_health_startup", lambda config: None)
    monkeypatch.setattr("app.runtime.startup.run_database_startup_checks", lambda config: None)
    monkeypatch.setattr("app.runtime.startup.validate_provider_auth", lambda config, provider: None)
    monkeypatch.setattr("app.runtime.startup.validate_required_runtime_profile", lambda config: None)
    monkeypatch.setattr("app.runtime.startup.log_runtime_profile", lambda config, provider: None)
    monkeypatch.setattr(
        "app.runtime.startup.codex_sandbox_support_error",
        lambda config, approval_mode: None if approval_mode == "off" else "unexpected",
    )

    initialize_runtime_startup(cfg, provider)
