from pathlib import Path


FORBIDDEN_APP_REFERENCES = (
    "app.transports.",
    "from app.transports",
    "import app.transports",
    "app.request_runtime",
    "from app.request_runtime",
    "import app.request_runtime",
    "app.telegram_handlers",
    "app.skill_commands",
    "app.telegram_runtime_skill_surface",
    "app.telegram_conversation_surface",
    "app.telegram_pending_request_surface",
    "from app.transport import",
    "import app.transport",
    "app.runtime_skill_catalog_use_cases",
    "app.runtime_skill_activation_use_cases",
    "app.runtime_skill_import_use_cases",
    "app.runtime_skill_setup_use_cases",
    "app.credential_management_use_cases",
    "app.conversation_control_use_cases",
    "app.conversation_settings_use_cases",
    "app.pending_request_use_cases",
    "app.recovery_use_cases",
    "app.provider_guidance_use_cases",
    "app.skill_lifecycle_service",
    "app.agents.orchestration",
    "app.workflows.pending_request",
    "from app.workflows.pending_request",
    "import app.workflows.pending_request",
    "app.workflows.transport_recovery",
    "from app.workflows.transport_recovery",
    "import app.workflows.transport_recovery",
    "app.workflows.results",
    "from app.workflows.results",
    "import app.workflows.results",
    "app.transport_contract",
    "from app.transport_contract",
    "import app.transport_contract",
)


def test_deleted_legacy_module_references_are_gone_from_app_code() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    app_root = repo_root / "app"
    python_files = sorted(path for path in app_root.rglob("*.py") if "__pycache__" not in path.parts)
    for path in python_files:
        text = path.read_text()
        for forbidden in FORBIDDEN_APP_REFERENCES:
            assert forbidden not in text, f"{forbidden} still referenced in {path}"


def test_access_module_has_no_channel_imports() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    access_path = repo_root / "app" / "access.py"
    text = access_path.read_text()
    assert "app.channels" not in text, f"channel import still referenced in {access_path}"


def test_telegram_conversation_module_has_no_ingress_import() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    conversation_path = repo_root / "app" / "channels" / "telegram" / "conversation.py"
    text = conversation_path.read_text()
    assert "app.channels.telegram.ingress" not in text, (
        f"telegram ingress import still referenced in {conversation_path}"
    )


def test_telegram_runtime_skills_module_has_no_ingress_import() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    runtime_skills_path = repo_root / "app" / "channels" / "telegram" / "runtime_skills.py"
    text = runtime_skills_path.read_text()
    assert "app.channels.telegram.ingress" not in text, (
        f"telegram ingress import still referenced in {runtime_skills_path}"
    )


def test_telegram_pending_module_has_no_ingress_import() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    pending_path = repo_root / "app" / "channels" / "telegram" / "pending.py"
    text = pending_path.read_text()
    assert "app.channels.telegram.ingress" not in text, (
        f"telegram ingress import still referenced in {pending_path}"
    )


def test_runtime_dispatch_has_no_channel_imports() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    dispatch_path = repo_root / "app" / "runtime" / "dispatch.py"
    text = dispatch_path.read_text()
    assert "app.channels" not in text, (
        f"channel import still referenced in {dispatch_path}"
    )


def test_agents_delivery_has_no_channel_imports() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    delivery_path = repo_root / "app" / "agents" / "delivery.py"
    text = delivery_path.read_text()
    assert "app.channels" not in text, (
        f"channel import still referenced in {delivery_path}"
    )


def test_agents_delegation_has_no_channel_imports() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    delegation_path = repo_root / "app" / "agents" / "delegation.py"
    text = delegation_path.read_text()
    assert "app.channels" not in text, (
        f"channel import still referenced in {delegation_path}"
    )


def test_handler_support_does_not_mutate_legacy_ingress_globals() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    handler_support_path = repo_root / "tests" / "support" / "handler_support.py"
    text = handler_support_path.read_text()
    forbidden = (
        "_th._config",
        "_th._provider",
        "_th._bot_instance",
        "_th._LIVE_CANCEL",
        "_th._cfg(",
        "_th._prov(",
    )
    for token in forbidden:
        assert token not in text, f"{token} still referenced in {handler_support_path}"


def test_deleted_skill_lifecycle_service_path_is_gone() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    deleted_path = repo_root / "app" / "skill_lifecycle_service.py"
    assert not deleted_path.exists(), f"legacy setup owner still exists at {deleted_path}"


def test_runtime_skill_setup_is_the_only_app_owner_of_awaiting_skill_setup_writes() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    app_root = repo_root / "app"
    allowed = {app_root / "workflows" / "runtime_skills" / "setup.py"}
    hits: list[Path] = []
    for path in sorted(app_root.rglob("*.py")):
        if path.name == "session_state.py":
            continue
        text = path.read_text()
        if "session.awaiting_skill_setup =" in text:
            hits.append(path)
    assert hits == sorted(allowed), f"unexpected awaiting_skill_setup write owners: {hits}"


def test_deleted_agents_orchestration_path_is_gone() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    deleted_path = repo_root / "app" / "agents" / "orchestration.py"
    assert not deleted_path.exists(), f"legacy delegation owner still exists at {deleted_path}"


def test_deleted_pending_and_recovery_root_paths_are_gone() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    deleted_paths = (
        repo_root / "app" / "workflows" / "pending_request.py",
        repo_root / "app" / "workflows" / "transport_recovery.py",
        repo_root / "app" / "workflows" / "results.py",
        repo_root / "app" / "transport_contract.py",
    )
    for deleted_path in deleted_paths:
        assert not deleted_path.exists(), f"legacy machine path still exists at {deleted_path}"


def test_agents_do_not_edit_delegation_status_strings_directly() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    agent_paths = (
        repo_root / "app" / "agents" / "delegation.py",
        repo_root / "app" / "agents" / "delivery.py",
    )
    forbidden = (
        "task.status =",
        "delegation.status =",
        "PendingDelegation(",
        "DelegatedTask(",
    )
    for path in agent_paths:
        text = path.read_text()
        for token in forbidden:
            assert token not in text, f"{token} still referenced in {path}"
