from pathlib import Path
import re


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

FORBIDDEN_TELEGRAM_SINGLETON_HELPERS = (
    "install_channel_state(",
    "get_channel_state(",
    "peek_channel_state(",
    "reset_channel_state(",
    "get_cancellation_registry(",
    "reset_cancellation_registry(",
)


def test_deleted_legacy_module_references_are_gone_from_app_code() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    app_root = repo_root / "app"
    python_files = sorted(path for path in app_root.rglob("*.py") if "__pycache__" not in path.parts)
    for path in python_files:
        text = path.read_text()
        for forbidden in FORBIDDEN_APP_REFERENCES:
            assert forbidden not in text, f"{forbidden} still referenced in {path}"


def test_deleted_telegram_singleton_helpers_are_gone_from_app_code() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    app_root = repo_root / "app"
    python_files = sorted(path for path in app_root.rglob("*.py") if "__pycache__" not in path.parts)
    for path in python_files:
        text = path.read_text()
        for forbidden in FORBIDDEN_TELEGRAM_SINGLETON_HELPERS:
            assert forbidden not in text, f"{forbidden} still referenced in {path}"


def test_deleted_telegram_singleton_helpers_are_gone_from_test_code() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    tests_root = repo_root / "tests"
    gate_path = Path(__file__).resolve()
    python_files = sorted(
        path for path in tests_root.rglob("*.py") if "__pycache__" not in path.parts and path != gate_path
    )
    for path in python_files:
        text = path.read_text()
        for forbidden in FORBIDDEN_TELEGRAM_SINGLETON_HELPERS:
            assert forbidden not in text, f"{forbidden} still referenced in {path}"


def test_deleted_legacy_module_references_are_gone_from_test_code() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    tests_root = repo_root / "tests"
    gate_path = Path(__file__).resolve()
    python_files = sorted(
        path for path in tests_root.rglob("*.py") if "__pycache__" not in path.parts and path != gate_path
    )
    for path in python_files:
        text = path.read_text()
        for forbidden in FORBIDDEN_APP_REFERENCES:
            assert forbidden not in text, f"{forbidden} still referenced in {path}"


def test_live_channel_contracts_do_not_reintroduce_surface_vocabulary() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    app_root = repo_root / "app"
    allowed_paths = {
        app_root / "registry_service" / "store.py",
    }
    forbidden_tokens = (
        "origin_surface",
        "surface_input",
        "surface_action",
        "surface_capabilities",
        "surface_binding_id",
        "ExecutionSurfaceContext",
        "SurfaceBinding",
        "SurfaceEvent",
        "RuntimeSurfaceContext",
        "get_runtime_surface_context",
    )
    for path in sorted(app_root.rglob("*.py")):
        if "__pycache__" in path.parts or path in allowed_paths:
            continue
        text = path.read_text()
        for token in forbidden_tokens:
            assert token not in text, f"{token} still referenced in {path}"


def test_legacy_registry_column_tokens_are_limited_to_migration_owners() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    allowed_paths = {
        repo_root / "app" / "registry_service" / "store.py",
        repo_root / "app" / "db" / "migrations" / "postgres" / "0004_registry.sql",
        repo_root / "app" / "db" / "migrations" / "postgres" / "0010_rename_registry_channel_columns.sql",
        repo_root / "tests" / "test_registry_service.py",
        repo_root / "tests" / "test_db_postgres.py",
        Path(__file__).resolve(),
    }
    candidate_paths = sorted(
        path
        for path in repo_root.rglob("*")
        if path.is_file()
        and path.suffix in {".py", ".sql"}
        and "__pycache__" not in path.parts
    )
    forbidden_tokens = ("origin_surface", "surface_capabilities_json")
    for path in candidate_paths:
        if path in allowed_paths:
            continue
        text = path.read_text()
        for token in forbidden_tokens:
            assert token not in text, f"{token} still referenced in {path}"


def test_legacy_delivery_kind_tokens_are_limited_to_migration_owners() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    allowed_paths = {
        repo_root / "app" / "registry_service" / "store.py",
        repo_root / "app" / "db" / "migrations" / "postgres" / "0009_rename_delivery_kinds.sql",
        repo_root / "tests" / "test_agents.py",
        repo_root / "tests" / "test_db_postgres.py",
        repo_root / "tests" / "test_registry_service.py",
        Path(__file__).resolve(),
    }
    candidate_paths = sorted(
        path
        for path in repo_root.rglob("*")
        if path.is_file()
        and path.suffix in {".py", ".sql"}
        and "__pycache__" not in path.parts
    )
    forbidden_tokens = ("surface_input", "surface_action")
    for path in candidate_paths:
        if path in allowed_paths:
            continue
        text = path.read_text()
        for token in forbidden_tokens:
            assert token not in text, f"{token} still referenced in {path}"


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


def test_telegram_session_io_module_has_no_ingress_import() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    session_io_path = repo_root / "app" / "channels" / "telegram" / "session_io.py"
    text = session_io_path.read_text()
    assert "app.channels.telegram.ingress" not in text, (
        f"telegram ingress import still referenced in {session_io_path}"
    )


def test_telegram_progress_module_has_no_ingress_import() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    progress_path = repo_root / "app" / "channels" / "telegram" / "progress.py"
    text = progress_path.read_text()
    assert "app.channels.telegram.ingress" not in text, (
        f"telegram ingress import still referenced in {progress_path}"
    )


def test_telegram_delegation_channel_module_has_no_ingress_import() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    delegation_path = repo_root / "app" / "channels" / "telegram" / "delegation_channel.py"
    text = delegation_path.read_text()
    assert "app.channels.telegram.ingress" not in text, (
        f"telegram ingress import still referenced in {delegation_path}"
    )


def test_telegram_execution_module_has_no_ingress_import() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    execution_path = repo_root / "app" / "channels" / "telegram" / "execution.py"
    text = execution_path.read_text()
    assert "app.channels.telegram.ingress" not in text, (
        f"telegram ingress import still referenced in {execution_path}"
    )


def test_telegram_execution_module_does_not_own_workflow_context_or_error_formatting() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    execution_path = repo_root / "app" / "channels" / "telegram" / "execution.py"
    text = execution_path.read_text()
    forbidden = (
        "def execution_channel_context(",
        "async def format_provider_error(",
        "async def execute_request(",
        "async def request_approval(",
        "def check_prompt_size_cross_chat(",
        "async def approve_pending(",
        "async def reject_pending(",
        "async def retry_skip_pending(",
        "async def retry_allow_pending(",
    )
    for token in forbidden:
        assert token not in text, f"{token} still referenced in {execution_path}"


def test_telegram_worker_module_has_no_ingress_import() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    worker_path = repo_root / "app" / "channels" / "telegram" / "worker.py"
    text = worker_path.read_text()
    assert "app.channels.telegram.ingress" not in text, (
        f"telegram ingress import still referenced in {worker_path}"
    )


def test_telegram_shared_mode_dispatch_module_has_no_ingress_import() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    shared_mode_dispatch_path = repo_root / "app" / "channels" / "telegram" / "shared_mode_dispatch.py"
    text = shared_mode_dispatch_path.read_text()
    assert "app.channels.telegram.ingress" not in text, (
        f"telegram ingress import still referenced in {shared_mode_dispatch_path}"
    )


def test_telegram_shared_mode_dispatch_does_not_define_duplicated_inline_dispatch_helpers() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    shared_mode_dispatch_path = repo_root / "app" / "channels" / "telegram" / "shared_mode_dispatch.py"
    text = shared_mode_dispatch_path.read_text()
    forbidden = (
        "def _shared_skills_inline_handler(",
        "def _shared_inline_command_handler(",
    )
    for token in forbidden:
        assert token not in text, f"{token} still referenced in {shared_mode_dispatch_path}"


def test_h1_extracted_telegram_modules_have_no_ingress_back_imports() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    telegram_root = repo_root / "app" / "channels" / "telegram"
    extracted_modules = (
        "session_io.py",
        "progress.py",
        "delegation_channel.py",
        "execution.py",
        "worker.py",
        "shared_mode_dispatch.py",
    )
    for filename in extracted_modules:
        path = telegram_root / filename
        text = path.read_text()
        assert "app.channels.telegram.ingress" not in text, (
            f"telegram ingress import still referenced in {path}"
        )


def test_extracted_telegram_modules_import_only_shared_types_and_routing_targets() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    telegram_root = repo_root / "app" / "channels" / "telegram"
    allowed_imports = {
        "session_io.py": {"state"},
        "progress.py": {"state"},
        "delegation_channel.py": {"presenters", "session_io", "state"},
        "execution.py": {"presenters", "conversation", "pending", "runtime_skills", "session_io", "state"},
        "worker.py": {"presenters", "conversation", "execution", "pending", "runtime_skills", "session_io", "state"},
        "shared_mode_dispatch.py": {
            "presenters",
            "conversation",
            "delegation_channel",
            "normalization",
            "runtime_skills",
            "session_io",
            "state",
        },
    }
    sibling_import_pattern = re.compile(
        r"^\s*from app\.channels\.telegram(?:\.(?P<submodule>[a-z_]+)|\s+import\s+(?P<pkgmodule>[a-z_]+))",
        re.MULTILINE,
    )

    for filename, allowed in allowed_imports.items():
        path = telegram_root / filename
        text = path.read_text()
        imports = {
            match.group("submodule") or match.group("pkgmodule")
            for match in sibling_import_pattern.finditer(text)
        }
        imports.discard(None)
        unexpected = imports - allowed
        assert not unexpected, f"{path} has unexpected sibling imports: {sorted(unexpected)}"


def test_no_channel_module_constructs_execution_channel_context() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    channels_root = repo_root / "app" / "channels"
    for path in sorted(channels_root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        text = path.read_text()
        assert "ExecutionChannelContext(" not in text, (
            f"workflow execution context still constructed in channel code at {path}"
        )


def test_ingress_no_longer_defines_session_io_helpers() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    ingress_path = repo_root / "app" / "channels" / "telegram" / "ingress.py"
    text = ingress_path.read_text()
    forbidden_defs = (
        "def _conversation_key(",
        "def _actor_key(",
        "def _event_key(",
        "def _telegram_chat_id(",
        "def _load(",
        "def _save(",
    )
    for token in forbidden_defs:
        assert token not in text, f"{token} still defined in {ingress_path}"


def test_ingress_no_longer_defines_progress_helpers() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    ingress_path = repo_root / "app" / "channels" / "telegram" / "ingress.py"
    text = ingress_path.read_text()
    forbidden_defs = (
        "class TelegramProgress:",
        "def _progress_timeline_callback(",
        "def keep_typing(",
        "def _heartbeat(",
    )
    for token in forbidden_defs:
        assert token not in text, f"{token} still defined in {ingress_path}"


def test_ingress_no_longer_defines_delegation_channel_helpers() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    ingress_path = repo_root / "app" / "channels" / "telegram" / "ingress.py"
    text = ingress_path.read_text()
    forbidden_defs = (
        "def _delegation_keyboard(",
        "class _DelegationCallbackEditableHandle:",
        "class _DelegationCallbackSurface:",
        "def _parse_delegation_callback(",
        "async def _publish_delegation_proposed_event(",
        "async def _propose_delegation_plan(",
        "async def _handle_delegation_approve(",
        "async def _handle_delegation_cancel(",
    )
    for token in forbidden_defs:
        assert token not in text, f"{token} still defined in {ingress_path}"


def test_ingress_no_longer_defines_execution_helpers() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    ingress_path = repo_root / "app" / "channels" / "telegram" / "ingress.py"
    text = ingress_path.read_text()
    forbidden_defs = (
        "def _conversation_runtime(",
        "def _runtime_skill_runtime(",
        "def _pending_runtime(",
        "def _dispatch_runtime(",
        "def _execution_surface_context(",
        "def _execution_runtime(",
        "def _delegation_runtime(",
        "def _check_prompt_size_cross_chat(",
        "def _resolve_project(",
        "def _resolve_context(",
        "def _allowed_roots(",
        "def _edit_or_reply_text(",
        "def _send_compact_reply(",
        "async def _show_foreign_setup(",
        "async def _show_setup_prompt(",
        "async def _send_retry_prompt(",
        "async def _send_approval_prompt(",
        "async def _format_provider_error(",
        "def _run_result_was_interrupted(",
    )
    for token in forbidden_defs:
        assert token not in text, f"{token} still defined in {ingress_path}"


def test_ingress_no_longer_defines_worker_helpers() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    ingress_path = repo_root / "app" / "channels" / "telegram" / "ingress.py"
    text = ingress_path.read_text()
    forbidden_defs = (
        "async def _poll_cancel_requested(",
        "async def _run_with_cancel_watch(",
        "def _action_target_message_id(",
        "def _build_action_surface(",
        "async def _execute_worker_action(",
        "async def worker_dispatch(",
        "def _maybe_fire_webhook(",
    )
    for token in forbidden_defs:
        assert token not in text, f"{token} still defined in {ingress_path}"


def test_ingress_no_longer_defines_shared_mode_dispatch_helpers() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    ingress_path = repo_root / "app" / "channels" / "telegram" / "ingress.py"
    text = ingress_path.read_text()
    forbidden_defs = (
        "def _callback_message_id(",
        "def _build_action_envelope(",
        "def _worker_owned_command_action(",
        "def _worker_owned_callback_action(",
        "def _shared_inline_command_handler(",
        "def _action_requires_public_guard(",
        "async def _enqueue_shared_action(",
        "def _shared_action_envelope(",
        "def _record_shared_action(",
        "async def _shared_cancel_command(",
        "async def _shared_command_dispatch(",
        "async def _shared_callback_dispatch(",
    )
    for token in forbidden_defs:
        assert token not in text, f"{token} still defined in {ingress_path}"


def test_ingress_no_longer_contains_inline_skills_or_guidance_command_routing() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    ingress_path = repo_root / "app" / "channels" / "telegram" / "ingress.py"
    text = ingress_path.read_text()
    forbidden_tokens = (
        "skills_show(",
        "skills_list(",
        "skills_add(",
        "skills_remove(",
        "skills_setup(",
        "skills_clear(",
        "skills_create(",
        "skills_search(",
        "skills_info(",
        "skills_install(",
        "skills_uninstall(",
        "skills_updates(",
        "skills_diff(",
        "skills_update(",
        "skills_edit(",
        "skills_history(",
        "skills_submit(",
        "skills_approve(",
        "skills_reject(",
        "skills_publish(",
        "skills_archive(",
        "guidance_preview(",
        "guidance_history(",
        "guidance_edit(",
        "guidance_submit(",
        "guidance_approve(",
        "guidance_reject(",
        "guidance_publish(",
        "guidance_archive(",
        "guidance_usage_message(",
        "guidance_admin_only_message(",
    )
    for token in forbidden_tokens:
        assert token not in text, f"{token} still referenced in {ingress_path}"


def test_telegram_runtime_owner_modules_do_not_define_singletons() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    state_path = repo_root / "app" / "channels" / "telegram" / "state.py"
    cancellation_path = repo_root / "app" / "channels" / "telegram" / "cancellation.py"
    ingress_path = repo_root / "app" / "channels" / "telegram" / "ingress.py"
    state_text = state_path.read_text()
    cancellation_text = cancellation_path.read_text()
    ingress_text = ingress_path.read_text()

    assert "_CURRENT_STATE" not in state_text, f"singleton runtime still referenced in {state_path}"
    assert "_REGISTRY" not in cancellation_text, f"singleton cancel registry still referenced in {cancellation_path}"
    assert "CHAT_LOCKS =" not in ingress_text, f"ingress global lock registry still referenced in {ingress_path}"
    assert "_pending_work_items" not in ingress_text, f"ingress pending-item global still referenced in {ingress_path}"
    assert "_current_update_id" not in ingress_text, f"ingress update-id contextvar global still referenced in {ingress_path}"


def test_deleted_telegram_routing_path_is_gone() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    deleted_path = repo_root / "app" / "channels" / "telegram" / "routing.py"
    assert not deleted_path.exists(), f"legacy telegram routing path still exists at {deleted_path}"


def test_telegram_delegation_surface_path_is_gone() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    deleted_path = repo_root / "app" / "channels" / "telegram" / "delegation_surface.py"
    assert not deleted_path.exists(), f"incorrect telegram delegation surface path still exists at {deleted_path}"


def test_only_telegram_bootstrap_imports_the_live_ingress_owner_from_app_code() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    app_root = repo_root / "app"
    bootstrap_path = app_root / "channels" / "telegram" / "bootstrap.py"
    ingress_path = app_root / "channels" / "telegram" / "ingress.py"
    python_files = sorted(path for path in app_root.rglob("*.py") if "__pycache__" not in path.parts)
    forbidden_tokens = (
        "app.channels.telegram.ingress",
        "from app.channels.telegram import ingress",
    )
    for path in python_files:
        if path in {bootstrap_path, ingress_path}:
            continue
        text = path.read_text()
        for token in forbidden_tokens:
            assert token not in text, f"{token} still referenced in {path}"


def test_telegram_bootstrap_owns_application_construction_and_handler_registration() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    bootstrap_path = repo_root / "app" / "channels" / "telegram" / "bootstrap.py"
    text = bootstrap_path.read_text()
    required = (
        "def build_application(",
        "Application.builder().token(",
        "app.add_handler(",
        "def build_bootstrap(",
        "from app.channels.telegram import ingress",
        "from app.channels.telegram import shared_mode_dispatch as telegram_shared_mode_dispatch",
        "from app.channels.telegram import worker as telegram_worker",
        "shared_command_handler = telegram_shared_mode_dispatch.build_shared_command_handler(",
        "shared_callback_handler = telegram_shared_mode_dispatch.build_shared_callback_handler(",
        "def _execution_runtime(runtime: TelegramRuntime):",
        "execution_runtime=execution_runtime",
        "worker_dispatch=functools.partial(",
    )
    for token in required:
        assert token in text, f"{token} missing from {bootstrap_path}"


def test_telegram_ingress_does_not_build_ptb_applications_or_register_handlers() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    ingress_path = repo_root / "app" / "channels" / "telegram" / "ingress.py"
    text = ingress_path.read_text()
    forbidden = (
        "def build_application(",
        "Application.builder(",
        "app.add_handler(",
        "def build_bootstrap(",
    )
    for token in forbidden:
        assert token not in text, f"{token} still referenced in {ingress_path}"


def test_runtime_dispatch_has_no_channel_imports() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    dispatch_path = repo_root / "app" / "runtime" / "dispatch.py"
    text = dispatch_path.read_text()
    assert "app.channels" not in text, (
        f"channel import still referenced in {dispatch_path}"
    )


def test_runtime_composition_has_no_channel_imports() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    composition_path = repo_root / "app" / "runtime" / "composition.py"
    text = composition_path.read_text()
    assert "app.channels" not in text, (
        f"channel import still referenced in {composition_path}"
    )


def test_runtime_dispatch_has_no_telegram_rendering_or_workflow_branches() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    dispatch_path = repo_root / "app" / "runtime" / "dispatch.py"
    text = dispatch_path.read_text()
    forbidden = (
        "from telegram",
        "import telegram",
        "InlineKeyboardButton",
        "InlineKeyboardMarkup",
        "ParseMode",
        "app.approvals",
        "app.credential_flow",
        "app.provider_guidance_service",
        "app.storage",
        "app.summarize",
        "app.work_queue",
        "PendingApproval",
        "PendingRetry",
        "RequestExecutionOutcome",
    )
    for token in forbidden:
        assert token not in text, f"{token} still referenced in {dispatch_path}"


def test_execution_finalization_workflow_has_no_channel_imports() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    finalization_path = repo_root / "app" / "workflows" / "execution" / "finalization.py"
    text = finalization_path.read_text()
    assert "app.channels" not in text, f"channel import still referenced in {finalization_path}"


def test_worker_dispatch_no_longer_contains_inline_execution_workflow_logic() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    worker_path = repo_root / "app" / "channels" / "telegram" / "worker.py"
    text = worker_path.read_text()
    forbidden = (
        "session.approval_mode",
        "load_session(runtime, runtime_chat).approval_mode",
        "finalize_resumed_delegation(",
        "record_usage(",
        "publish_timeline_event(",
        "routed_task_result(",
        'source == "registry"',
    )
    for token in forbidden:
        assert token not in text, f"{token} still referenced in {worker_path}"


def test_worker_dispatch_documents_completion_ownership() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    worker_path = repo_root / "app" / "channels" / "telegram" / "worker.py"
    text = worker_path.read_text()
    assert "Completion ownership:" in text, f"completion ownership note missing from {worker_path}"


def test_telegram_reply_markup_builders_live_only_in_presenters() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    telegram_root = repo_root / "app" / "channels" / "telegram"
    forbidden = ("InlineKeyboardButton", "InlineKeyboardMarkup")
    for path in sorted(telegram_root.glob("*.py")):
        if path.name == "presenters.py":
            continue
        text = path.read_text()
        for token in forbidden:
            assert token not in text, f"{token} still referenced in {path}"


def test_telegram_ingress_line_count_stays_below_hard_cap() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    ingress_path = repo_root / "app" / "channels" / "telegram" / "ingress.py"
    line_count = sum(1 for _ in ingress_path.open())
    assert line_count <= 1500, f"{ingress_path} regressed to {line_count} lines"


def test_telegram_shared_mode_dispatch_line_count_stays_below_hard_cap() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    shared_mode_dispatch_path = repo_root / "app" / "channels" / "telegram" / "shared_mode_dispatch.py"
    line_count = sum(1 for _ in shared_mode_dispatch_path.open())
    assert line_count <= 450, f"{shared_mode_dispatch_path} regressed to {line_count} lines"


def test_telegram_guidance_channel_has_no_inline_html_formatting() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    guidance_path = repo_root / "app" / "channels" / "telegram" / "guidance.py"
    text = guidance_path.read_text()
    forbidden = (
        "html.escape(",
        "ParseMode.HTML",
        "<b>",
        "<pre>",
        "<code>",
    )
    for token in forbidden:
        assert token not in text, f"{token} still referenced in {guidance_path}"


def test_telegram_runtime_skills_channel_has_no_inline_html_or_credential_formatting() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    runtime_skills_path = repo_root / "app" / "channels" / "telegram" / "runtime_skills.py"
    text = runtime_skills_path.read_text()
    forbidden = (
        "html.escape(",
        "ParseMode.HTML",
        "from app.credential_flow",
        "format_credential_prompt(",
        "<b>",
        "<pre>",
        "<code>",
    )
    for token in forbidden:
        assert token not in text, f"{token} still referenced in {runtime_skills_path}"


def test_telegram_conversation_channel_has_no_inline_html_or_legacy_formatting_helpers() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    conversation_path = repo_root / "app" / "channels" / "telegram" / "conversation.py"
    text = conversation_path.read_text()
    forbidden = (
        "html.escape(",
        "ParseMode.HTML",
        "from app.credential_flow",
        "<b>",
        "<pre>",
        "<code>",
    )
    for token in forbidden:
        assert token not in text, f"{token} still referenced in {conversation_path}"


def test_telegram_pending_channel_has_no_inline_html_formatting() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    pending_path = repo_root / "app" / "channels" / "telegram" / "pending.py"
    text = pending_path.read_text()
    forbidden = (
        "ParseMode.HTML",
        "html.escape(",
        "<b>",
        "<pre>",
        "<code>",
    )
    for token in forbidden:
        assert token not in text, f"{token} still referenced in {pending_path}"


def test_test_suite_does_not_call_private_telegram_ingress_helpers() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    tests_root = repo_root / "tests"
    gate_path = Path(__file__).resolve()
    allowed_private_calls = {
        (tests_root / "test_invariants.py", "global_error_handler"),
    }
    private_call_pattern = re.compile(r"\b(?:th|_th|ingress)\._([A-Za-z0-9_]+)")
    python_files = sorted(
        path for path in tests_root.rglob("*.py") if "__pycache__" not in path.parts and path != gate_path
    )
    for path in python_files:
        text = path.read_text()
        for match in private_call_pattern.finditer(text):
            helper_name = match.group(1)
            if (path, helper_name) in allowed_private_calls:
                continue
            assert False, f"private ingress helper {helper_name} still referenced in {path}"


def test_test_suite_does_not_stub_validate_credential_via_module_assignment() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    tests_root = repo_root / "tests"
    gate_path = Path(__file__).resolve()
    python_files = sorted(
        path for path in tests_root.rglob("*.py") if "__pycache__" not in path.parts and path != gate_path
    )
    for path in python_files:
        for line_no, line in enumerate(path.read_text().splitlines(), start=1):
            assert ".validate_credential =" not in line, (
                f"module-level validate_credential assignment still referenced in {path}:{line_no}"
            )
            assert not ("setattr(" in line and "validate_credential" in line), (
                f"validate_credential monkeypatch still referenced in {path}:{line_no}"
            )


def test_test_suite_does_not_override_telegram_ingress_module_attributes() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    tests_root = repo_root / "tests"
    gate_path = Path(__file__).resolve()
    python_files = sorted(
        path for path in tests_root.rglob("*.py") if "__pycache__" not in path.parts and path != gate_path
    )
    for path in python_files:
        for line_no, line in enumerate(path.read_text().splitlines(), start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            assert not re.search(r"\b(?:monkeypatch\.setattr|setattr)\((?:th|_th|ingress),", line), (
                f"telegram ingress module monkeypatch still referenced in {path}:{line_no}"
            )
            assert not re.search(r"\b(?:th|_th|ingress)\.[A-Za-z_][A-Za-z0-9_]*\s*=", line), (
                f"telegram ingress module attribute override still referenced in {path}:{line_no}"
            )


def test_telegram_ingress_request_and_compact_rendering_is_presenter_owned() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    ingress_path = repo_root / "app" / "channels" / "telegram" / "ingress.py"
    text = ingress_path.read_text()
    forbidden = (
        "from app.credential_flow import",
        "format_credential_prompt(",
        "md_to_telegram_html(",
        "split_html(",
        "<blockquote expandable>",
        "I'd like to delegate the following to specialist bots:",
        "[Cannot send:",
        "Usage: /raw [N]",
        "No stored responses found.",
        "I'm ready. Send me a message or type /help to see what I can do.",
    )
    for token in forbidden:
        assert token not in text, f"{token} still referenced in {ingress_path}"


def test_telegram_ingress_does_not_duplicate_command_normalization_for_start_or_help() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    ingress_path = repo_root / "app" / "channels" / "telegram" / "ingress.py"
    text = ingress_path.read_text()
    assert "@_command_handler(show_not_allowed_message=True)\nasync def cmd_start(" in text
    assert "@_command_handler(show_not_allowed_message=True)\nasync def cmd_help(" in text
    assert text.count("event = telegram_normalization.normalize_command(update, context)") == 1


def test_telegram_ingress_help_and_admin_rendering_is_presenter_owned() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    ingress_path = repo_root / "app" / "channels" / "telegram" / "ingress.py"
    text = ingress_path.read_text()
    forbidden = (
        "_help_command_lines(",
        "_build_main_help(",
        "HELP_SKILLS =",
        "HELP_APPROVAL =",
        "HELP_CREDENTIALS =",
        "_HELP_TOPICS =",
        "_discover_usage(",
        "_format_discovery_results(",
        "Usage: /skills [list|add|remove|setup|create|edit|history|submit|approve|reject|publish|archive|clear|search|info|install|uninstall|updates|update|diff]",
        "Usage: /guidance [preview|edit|history|submit|approve|reject|publish|archive] <provider> [body]",
        "Usage: /admin sessions [conversation_key]",
        "This command requires admin access.",
        "<b>Access overrides</b>",
        "<b>Agent Bot</b>",
        "Unknown help topic. Try:",
        "Agent discovery is unavailable in standalone mode.",
    )
    for token in forbidden:
        assert token not in text, f"{token} still referenced in {ingress_path}"


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
        "app.channels.telegram.routing",
        "_th._config",
        "_th._provider",
        "_th._bot_instance",
        "_th._LIVE_CANCEL",
        "_th._cfg(",
        "_th._prov(",
        "install_channel_state(",
        "get_channel_state(",
        "reset_channel_state(",
        "get_cancellation_registry(",
        "reset_cancellation_registry(",
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


def test_workflows_package_root_has_no_transitional_reexports() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    workflows_init = repo_root / "app" / "workflows" / "__init__.py"
    text = workflows_init.read_text()
    assert "temporary" not in text.lower(), f"temporary language still present in {workflows_init}"
    assert "import " not in text, f"transitional re-export still present in {workflows_init}"


def test_recovery_transport_contract_owner_exists_under_concern_package() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    owner_path = repo_root / "app" / "workflows" / "recovery" / "transport_contract.py"
    assert owner_path.exists(), f"recovery transport contract owner missing at {owner_path}"


def test_stale_transport_era_test_files_are_gone() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    stale_paths = (
        repo_root / "tests" / "test_transports_factory.py",
        repo_root / "tests" / "test_transports_telegram.py",
    )
    for stale_path in stale_paths:
        assert not stale_path.exists(), f"stale transport-era test file still exists at {stale_path}"


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


def _non_registry_orchestration_paths() -> list[Path]:
    repo_root = Path(__file__).resolve().parents[1]
    app_root = repo_root / "app"
    excluded_files = {
        app_root / "main.py",
        app_root / "agents" / "bridge.py",
        app_root / "agents" / "registry_runtime.py",
        app_root / "agents" / "registry_control_processor.py",
    }
    excluded_dirs = {
        app_root / "channels" / "registry",
        app_root / "registry_service",
        app_root / "db" / "migrations",
    }
    paths: list[Path] = []
    for path in sorted(app_root.rglob("*.py")):
        if "__pycache__" in path.parts or path in excluded_files:
            continue
        if any(excluded_dir in path.parents for excluded_dir in excluded_dirs):
            continue
        paths.append(path)
    return paths


def test_non_registry_orchestration_has_no_registry_runtime_or_factory_tokens() -> None:
    forbidden = (
        "registry_runtime",
        "registry_client_factory",
    )
    for path in _non_registry_orchestration_paths():
        text = path.read_text()
        for token in forbidden:
            assert token not in text, f"{token} still referenced in {path}"


def test_non_registry_orchestration_has_no_registry_connection_helpers() -> None:
    forbidden = (
        "registry_connection_client",
        "resolve_registry_connection",
    )
    for path in _non_registry_orchestration_paths():
        text = path.read_text()
        for token in forbidden:
            assert token not in text, f"{token} still referenced in {path}"


def test_non_registry_orchestration_has_no_registry_runtime_presence_branch() -> None:
    pattern = re.compile(r"if\s+.*registry_runtime.*is\s+not\s+None")
    for path in _non_registry_orchestration_paths():
        text = path.read_text()
        assert pattern.search(text) is None, (
            f"registry_runtime presence branch still referenced in {path}"
        )


def test_removed_registry_fanout_helpers_do_not_reappear() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    gate_path = Path(__file__).resolve()
    candidate_paths = sorted(
        path
        for path in repo_root.rglob("*.py")
        if "__pycache__" not in path.parts and path != gate_path
    )
    forbidden = (
        "bind_conversation_to_registries",
        "publish_timeline_to_registries",
    )
    for path in candidate_paths:
        text = path.read_text()
        for token in forbidden:
            assert token not in text, f"{token} still referenced in {path}"
