from pathlib import Path
import re


FORBIDDEN_APP_REFERENCES = (
    "app.session_defaults",
    "app.session_defaults",
    "import app.session_defaults",
    "app.transports.",
    "app.transports",
    "import app.transports",
    "app.request_runtime",
    "app.request_runtime",
    "import app.request_runtime",
    "app.telegram_handlers",
    "app.skill_commands",
    "app.telegram_runtime_skill_surface",
    "app.telegram_conversation_surface",
    "app.telegram_pending_request_surface",
    "app.transport import",
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
    "app.workflows.pending_request",
    "import app.workflows.pending_request",
    "app.workflows.transport_recovery",
    "app.workflows.transport_recovery",
    "import app.workflows.transport_recovery",
    "app.workflows.results",
    "app.workflows.results",
    "import app.workflows.results",
    "app.transport_contract",
    "app.transport_contract",
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

FORBIDDEN_RELOCATED_PROVIDER_DISPATCH_KWARGS = (
    "progress_factory=",
    "send_status=",
    "typing_target=",
    "keep_typing=",
    "heartbeat=",
    "format_provider_error=",
    "run_result_was_interrupted=",
)

FORBIDDEN_OLD_WORLD_TEST_TOKENS = (
    "DelegationRuntime",
    "build_noop_control_plane_services",
    "_DynamicWorkQueue",
    "_default_registry_participant",
)


def test_deleted_legacy_module_references_are_gone__app_code() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    app_root = repo_root / "app"
    python_files = sorted(path for path in app_root.rglob("*.py") if "__pycache__" not in path.parts)
    for path in python_files:
        text = path.read_text()
        for forbidden in FORBIDDEN_APP_REFERENCES:
            assert forbidden not in text, f"{forbidden} still referenced in {path}"


def test_deleted_telegram_singleton_helpers_are_gone__app_code() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    app_root = repo_root / "app"
    python_files = sorted(path for path in app_root.rglob("*.py") if "__pycache__" not in path.parts)
    for path in python_files:
        text = path.read_text()
        for forbidden in FORBIDDEN_TELEGRAM_SINGLETON_HELPERS:
            assert forbidden not in text, f"{forbidden} still referenced in {path}"


def test_deleted_telegram_singleton_helpers_are_gone__test_code() -> None:
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


def test_deleted_legacy_module_references_are_gone__test_code() -> None:
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


def test_relocated_provider_dispatch_callback_kwargs_are_gone__app_and_sdk_code() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    gate_path = Path(__file__).resolve()
    python_files = sorted(
        path
        for root in (repo_root / "app", repo_root / "octopus_sdk")
        for path in root.rglob("*.py")
        if "__pycache__" not in path.parts and path != gate_path
    )
    for path in python_files:
        text = path.read_text()
        for forbidden in FORBIDDEN_RELOCATED_PROVIDER_DISPATCH_KWARGS:
            assert forbidden not in text, f"{forbidden} still referenced in {path}"


def test_tests_do_not_guard_old_world_callback_or_fallback_paths() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    tests_root = repo_root / "tests"
    gate_path = Path(__file__).resolve()
    python_files = sorted(
        path for path in tests_root.rglob("*.py") if "__pycache__" not in path.parts and path != gate_path
    )
    for path in python_files:
        text = path.read_text()
        for forbidden in FORBIDDEN_RELOCATED_PROVIDER_DISPATCH_KWARGS + FORBIDDEN_OLD_WORLD_TEST_TOKENS:
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


_DELETED_TELEGRAM_CHANNEL_FILES = (
    "cancellation.py",
    "conversation.py",
    "delegation_channel.py",
    "execution.py",
    "guidance.py",
    "inbound_context.py",
    "ingress.py",
    "normalization.py",
    "pending.py",
    "presenters.py",
    "progress.py",
    "runtime_skills.py",
    "session_io.py",
    "shared_mode_dispatch.py",
    "worker.py",
)


_REHOMED_TELEGRAM_MODULES = {
    "ingress": "app/runtime/telegram_ingress.py",
    "execution": "app/runtime/telegram_execution.py",
    "worker": "app/runtime/telegram_worker.py",
    "shared_dispatch": "app/runtime/telegram_shared_dispatch.py",
    "normalization": "app/runtime/telegram_normalization.py",
    "session_io": "app/runtime/telegram_session_io.py",
    "progress": "app/runtime/telegram_progress.py",
    "presenters": "app/presentation/telegram.py",
    "conversation": "app/workflows/conversation/telegram.py",
    "pending": "app/workflows/pending/telegram.py",
    "runtime_skills": "app/workflows/runtime_skills/telegram.py",
    "delegation": "app/workflows/delegation/telegram.py",
}


def test_deleted_telegram_channel_modules_are_gone() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    telegram_root = repo_root / "app" / "channels" / "telegram"
    for filename in _DELETED_TELEGRAM_CHANNEL_FILES:
        path = telegram_root / filename
        assert not path.exists(), f"deleted telegram module survived at {path}"


def test_rehomed_telegram_owner_modules_exist() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    for relative in _REHOMED_TELEGRAM_MODULES.values():
        path = repo_root / relative
        assert path.exists(), f"rehomed telegram owner missing at {path}"


def test_tests_do_not_import_deleted_telegram_modules() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    tests_root = repo_root / "tests"
    gate_path = Path(__file__).resolve()
    deleted_names = tuple(path.removesuffix(".py") for path in _DELETED_TELEGRAM_CHANNEL_FILES)
    dotted_pattern = re.compile(
        r"app\.channels\.telegram\.(?P<name>%s)\b" % "|".join(map(re.escape, deleted_names))
    )
    from_import_pattern = re.compile(
        r"from\s+app\.channels\.telegram\s+import\s+(?P<name>%s)\b"
        % "|".join(map(re.escape, deleted_names))
    )
    for path in sorted(tests_root.rglob("*.py")):
        if "__pycache__" in path.parts or path == gate_path:
            continue
        text = path.read_text()
        assert dotted_pattern.search(text) is None, (
            f"deleted telegram module import still referenced in {path}"
        )
        assert from_import_pattern.search(text) is None, (
            f"deleted telegram from-import still referenced in {path}"
        )


def test_rehomed_telegram_modules_do_not_back_import_deleted_channel_modules() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    forbidden = tuple(
        f"app.channels.telegram.{path.removesuffix('.py')}"
        for path in _DELETED_TELEGRAM_CHANNEL_FILES
    )
    for relative in _REHOMED_TELEGRAM_MODULES.values():
        path = repo_root / relative
        text = path.read_text()
        for token in forbidden:
            assert token not in text, f"{token} still referenced in {path}"


def test_rehomed_telegram_modules_only_depend_on_telegram_state_from_transport_dir() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    allowed = {
        "from app.channels.telegram.state import TelegramRuntime",
        "from app.channels.telegram.state import TelegramCancellationRegistry, TelegramRuntime",
    }
    for relative in _REHOMED_TELEGRAM_MODULES.values():
        path = repo_root / relative
        imports = {
            line.strip()
            for line in path.read_text().splitlines()
            if "app.channels.telegram" in line
        }
        unexpected = imports - allowed
        assert not unexpected, f"{path} has unexpected channel imports: {sorted(unexpected)}"


def test_telegram_transport_directory_stays_collapsed() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    telegram_root = repo_root / "app" / "channels" / "telegram"
    python_files = sorted(path for path in telegram_root.glob("*.py"))
    assert [path.name for path in python_files] == [
        "__init__.py",
        "bootstrap.py",
        "channel.py",
        "egress.py",
        "state.py",
    ]
    assert sum(1 for path in python_files for _ in path.open()) <= 1500


def test_telegram_execution_callback_builder_scaffolding_is_gone() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    gate_path = Path(__file__).resolve()
    python_files = sorted(
        path
        for path in repo_root.rglob("*.py")
        if "__pycache__" not in path.parts
        and path != gate_path
    )
    forbidden = (
        "TelegramExecutionCollaborators",
        "bind_execution_collaborators(",
        "build_conversation_progress_callback",
        "build_routed_task_progress_callback",
    )
    for path in python_files:
        text = path.read_text()
        for token in forbidden:
            assert token not in text, f"{token} still referenced in {path}"


def test_no_channel_module_constructs_transport_identity_outside_approved_sites() -> None:
    """Channel modules may construct TransportIdentity for event sink wiring.
    Only registry delivery transport is allowed in channel code."""
    repo_root = Path(__file__).resolve().parents[1]
    channels_root = repo_root / "app" / "channels"
    approved = {"delivery_transport.py"}
    for path in sorted(channels_root.rglob("*.py")):
        if "__pycache__" in path.parts or path.name in approved:
            continue
        text = path.read_text()
        assert "TransportIdentity(" not in text, (
            f"TransportIdentity constructed in non-approved channel code at {path}"
        )


def test_ingress_no_longer_defines_session_io_helpers() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    ingress_path = repo_root / "app" / "runtime" / "telegram_ingress.py"
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
    ingress_path = repo_root / "app" / "runtime" / "telegram_ingress.py"
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
    ingress_path = repo_root / "app" / "runtime" / "telegram_ingress.py"
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
    ingress_path = repo_root / "app" / "runtime" / "telegram_ingress.py"
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
    ingress_path = repo_root / "app" / "runtime" / "telegram_ingress.py"
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
    ingress_path = repo_root / "app" / "runtime" / "telegram_ingress.py"
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
    ingress_path = repo_root / "app" / "runtime" / "telegram_ingress.py"
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
    ingress_path = repo_root / "app" / "runtime" / "telegram_ingress.py"
    state_text = state_path.read_text()
    ingress_text = ingress_path.read_text()

    assert "_CURRENT_STATE" not in state_text, f"singleton runtime still referenced in {state_path}"
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


def test_only_telegram_bootstrap_imports_the_live_ingress_owner__app_code() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    app_root = repo_root / "app"
    bootstrap_path = app_root / "channels" / "telegram" / "bootstrap.py"
    python_files = sorted(path for path in app_root.rglob("*.py") if "__pycache__" not in path.parts)
    forbidden_tokens = ("app.runtime.telegram_ingress",)
    for path in python_files:
        if path == bootstrap_path:
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
        "from app.runtime import telegram_ingress as ingress",
        "from app.runtime import telegram_shared_dispatch as telegram_shared_mode_dispatch",
        "from app.runtime import telegram_worker",
        "shared_command_handler = telegram_shared_mode_dispatch.build_shared_command_handler(",
        "shared_callback_handler = telegram_shared_mode_dispatch.build_shared_callback_handler(",
        "def _execution_runtime(runtime: TelegramRuntime):",
        "execution_runtime=execution_runtime",
        "class TelegramWorkerProcessor(WorkerDispatchPort):",
        "worker_processor=TelegramWorkerProcessor(",
    )
    for token in required:
        assert token in text, f"{token} missing {bootstrap_path}"


def test_telegram_ingress_does_not_build_ptb_applications_or_register_handlers() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    ingress_path = repo_root / "app" / "runtime" / "telegram_ingress.py"
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
    dispatch_path = repo_root / "octopus_sdk" / "bot_runtime.py"
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
    dispatch_path = repo_root / "octopus_sdk" / "bot_runtime.py"
    text = dispatch_path.read_text()
    forbidden = (
        "telegram",
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
    worker_path = repo_root / "app" / "runtime" / "telegram_worker.py"
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


def test_worker_dispatch_does_not_import_registry_bridge_timeline_helpers() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    worker_path = repo_root / "app" / "runtime" / "telegram_worker.py"
    text = worker_path.read_text()
    import_block_match = re.search(
        r"app\.agents\.bridge import \((?P<body>[\s\S]*?)\n\)",
        text,
    )
    if import_block_match is None:
        return
    import_block = import_block_match.group("body")
    forbidden_tokens = (
        "publish_timeline_event",
        "_publish_timeline_event",
        "bind_conversation",
        "_bind_conversation",
    )
    for token in forbidden_tokens:
        assert token not in import_block, f"{token} still imported bridge in {worker_path}"


def test_runtime_boundaries_accept_only_canonical_identity_and_provenance_shapes() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    inbound_types_path = repo_root / "octopus_sdk" / "inbound_types.py"
    session_state_path = repo_root / "octopus_sdk" / "sessions.py"
    coordination_path = repo_root / "octopus_sdk" / "workflows" / "delegation.py"
    presenters_path = repo_root / "app" / "presentation" / "telegram.py"
    worker_path = repo_root / "app" / "runtime" / "telegram_worker.py"

    inbound_text = inbound_types_path.read_text()
    assert '"user_id" in data' not in inbound_text
    assert '"chat_id" in data' not in inbound_text
    assert '"registry_id"' not in inbound_text
    assert "telegram_actor_key(" not in inbound_text
    assert "telegram_conversation_key(" not in inbound_text
    assert "registry_authority_ref(" not in inbound_text

    session_text = session_state_path.read_text()
    assert "registry_authority_ref(" not in session_text

    coordination_text = coordination_path.read_text()
    assert "registry_authority_ref(" not in coordination_text

    presenters_text = presenters_path.read_text()
    assert 'agent.get("registry_id"' not in presenters_text

    worker_text = worker_path.read_text()
    assert "_resolve_registry_authority_ref" not in worker_text
    assert "parse_registry_ref(" not in worker_text


def test_registry_owned_paths_do_not_invent_default_registry_or_first_registry_selection() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    delivery_path = repo_root / "app" / "channels" / "registry" / "delivery_transport.py"
    registry_egress_path = repo_root / "app" / "channels" / "registry" / "egress.py"
    runtime_path = repo_root / "app" / "runtime" / "registry_participant.py"
    state_path = repo_root / "app" / "agents" / "state.py"

    delivery_text = delivery_path.read_text()
    assert 'or "default"' not in delivery_text

    registry_egress_text = registry_egress_path.read_text()
    assert 'else "default"' not in registry_egress_text

    runtime_text = runtime_path.read_text()
    assert "config.agent_registries[0]" not in runtime_text
    assert 'else "default"' not in runtime_text

    state_text = state_path.read_text()
    assert 'registry_id: str = "default"' not in state_text


def test_dead_registry_runtime_api_is_deleted() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    registry_runtime_path = repo_root / "app" / "agents" / "registry_runtime.py"
    assert not registry_runtime_path.exists(), f"dead registry runtime survived at {registry_runtime_path}"

    for path in repo_root.joinpath("app").rglob("*.py"):
        text = path.read_text()
        assert "runtime_for_registry(" not in text, f"runtime_for_registry survived in {path}"
        assert "resolve_target_registry_id(" not in text, (
            f"resolve_target_registry_id survived in {path}"
        )


def test_shared_delivery_and_admission_do_not_branch_on_raw_telegram_surface_names() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    delivery_path = repo_root / "app" / "channels" / "registry" / "delivery_transport.py"
    work_admission_path = repo_root / "app" / "runtime" / "work_admission.py"

    delivery_text = delivery_path.read_text()
    assert 'channel_name == "telegram"' not in delivery_text

    work_admission_text = work_admission_path.read_text()
    assert 'channel_type != "telegram"' not in work_admission_text
    assert 'channel_type == "telegram"' not in work_admission_text


def test_telegram_ingress_submission_flows_do_not_reach_into_work_admission_helpers() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    for relative in (
        ("app", "runtime", "telegram_ingress.py"),
        ("app", "runtime", "telegram_shared_dispatch.py"),
    ):
        path = repo_root.joinpath(*relative)
        text = path.read_text()
        forbidden = (
            "admit_fresh_message(",
            "enqueue_inbound_envelope(",
            "record_inbound_envelope(",
        )
        for token in forbidden:
            assert token not in text, f"{token} still referenced in {path}"


def test_runtime_startup_and_builders_do_not_branch_on_config_registry_agent_ids_for_live_enrollment() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    candidate_paths = (
        repo_root / "app" / "main.py",
        repo_root / "app" / "runtime" / "startup.py",
        repo_root / "app" / "runtime" / "services.py",
    )
    for path in candidate_paths:
        assert "config.registry_agent_ids" not in path.read_text()


def test_telegram_discover_command_stays_on_registry_participant_surface() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    ingress_path = repo_root / "app" / "runtime" / "telegram_ingress.py"
    text = ingress_path.read_text()
    assert "services.control_plane.agent_directory.search_agents" not in text


def test_worker_dispatch_documents_completion_ownership() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    worker_path = repo_root / "app" / "runtime" / "telegram_worker.py"
    text = worker_path.read_text()
    assert "Completion ownership:" in text, f"completion ownership note missing {worker_path}"


def test_telegram_reply_markup_builders_live_only_in_presenters() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    candidate_paths = (
        *sorted((repo_root / "app" / "channels" / "telegram").glob("*.py")),
        *sorted((repo_root / "app" / "runtime").glob("telegram_*.py")),
        repo_root / "app" / "workflows" / "conversation" / "telegram.py",
        repo_root / "app" / "workflows" / "pending" / "telegram.py",
        repo_root / "app" / "workflows" / "runtime_skills" / "telegram.py",
        repo_root / "app" / "workflows" / "delegation" / "telegram.py",
    )
    forbidden = ("InlineKeyboardButton", "InlineKeyboardMarkup")
    for path in candidate_paths:
        if path == repo_root / "app" / "presentation" / "telegram.py":
            continue
        text = path.read_text()
        for token in forbidden:
            assert token not in text, f"{token} still referenced in {path}"


def test_telegram_guidance_dispatch_has_no_inline_html_formatting() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    guidance_path = repo_root / "app" / "runtime" / "telegram_shared_dispatch.py"
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
    runtime_skills_path = repo_root / "app" / "workflows" / "runtime_skills" / "telegram.py"
    text = runtime_skills_path.read_text()
    forbidden = (
        "html.escape(",
        "ParseMode.HTML",
        "app.credential_flow",
        "format_credential_prompt(",
        "<b>",
        "<pre>",
        "<code>",
    )
    for token in forbidden:
        assert token not in text, f"{token} still referenced in {runtime_skills_path}"


def test_telegram_conversation_channel_has_no_inline_html_or_legacy_formatting_helpers() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    conversation_path = repo_root / "app" / "workflows" / "conversation" / "telegram.py"
    text = conversation_path.read_text()
    forbidden = (
        "html.escape(",
        "ParseMode.HTML",
        "app.credential_flow",
        "<b>",
        "<pre>",
        "<code>",
    )
    for token in forbidden:
        assert token not in text, f"{token} still referenced in {conversation_path}"


def test_telegram_pending_channel_has_no_inline_html_formatting() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    pending_path = repo_root / "app" / "workflows" / "pending" / "telegram.py"
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
    ingress_path = repo_root / "app" / "runtime" / "telegram_ingress.py"
    text = ingress_path.read_text()
    forbidden = (
        "app.credential_flow import",
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
    ingress_path = repo_root / "app" / "runtime" / "telegram_ingress.py"
    text = ingress_path.read_text()
    assert "@_command_handler(show_not_allowed_message=True)\nasync def cmd_start(" in text
    assert "@_command_handler(show_not_allowed_message=True)\nasync def cmd_help(" in text
    assert text.count("event = telegram_normalization.normalize_command(update, context)") == 1


def test_telegram_ingress_help_and_admin_rendering_is_presenter_owned() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    ingress_path = repo_root / "app" / "runtime" / "telegram_ingress.py"
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
    assert not delivery_path.exists(), f"legacy delivery owner still exists at {delivery_path}"


def test_agents_delegation_has_no_channel_imports() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    delegation_path = repo_root / "app" / "agents" / "delegation.py"
    assert not delegation_path.exists(), f"legacy delegation owner still exists at {delegation_path}"


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


def test_recovery_transport_contract_owner_lives_in_sdk() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    owner_path = repo_root / "octopus_sdk" / "work_queue.py"
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
    delegation_path = repo_root / "app" / "agents" / "delegation.py"
    assert not delegation_path.exists(), f"legacy delegation owner still exists at {delegation_path}"
    agent_paths = (repo_root / "app" / "channels" / "registry" / "delivery_transport.py",)
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


def test_legacy_bridge_and_delivery_modules_are_deleted() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    bridge_path = repo_root / "app" / "agents" / "bridge.py"
    delivery_path = repo_root / "app" / "agents" / "delivery.py"
    assert not bridge_path.exists(), f"legacy bridge owner still exists at {bridge_path}"
    assert not delivery_path.exists(), f"legacy delivery owner still exists at {delivery_path}"


def test_selected_telegram_and_workflow_modules_no_longer_import_bridge_helpers() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    guarded_paths = (
        repo_root / "app" / "runtime" / "telegram_execution.py",
        repo_root / "app" / "runtime" / "telegram_normalization.py",
        repo_root / "app" / "runtime" / "telegram_worker.py",
        repo_root / "app" / "workflows" / "delegation" / "telegram.py",
        repo_root / "app" / "workflows" / "execution" / "finalization.py",
        repo_root / "app" / "workflows" / "recovery" / "replay.py",
    )
    for path in guarded_paths:
        text = path.read_text()
        assert "app.agents.bridge" not in text, (
            f"bridge helper import still referenced in {path}"
        )


def _non_registry_orchestration_paths() -> list[Path]:
    repo_root = Path(__file__).resolve().parents[1]
    app_root = repo_root / "app"
    excluded_files = {
        app_root / "main.py",
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


def test_removed_bridge_http_helpers_do_not_reappear() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    gate_path = Path(__file__).resolve()
    candidate_paths = sorted(
        path
        for path in repo_root.rglob("*.py")
        if "__pycache__" not in path.parts and path != gate_path
    )
    forbidden = (
        "_bind_conversation(",
        "_publish_timeline_event(",
    )
    for path in candidate_paths:
        text = path.read_text()
        for token in forbidden:
            assert token not in text, f"{token} still referenced in {path}"


def test_generic_health_and_discover_paths_do_not_reference_registry_scope() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    candidate_paths = (
        repo_root / "octopus_sdk" / "health_publication.py",
        repo_root / "app" / "control_plane" / "adapters" / "health_publication.py",
        repo_root / "app" / "runtime" / "telegram_ingress.py",
    )
    for path in candidate_paths:
        text = path.read_text()
        assert "registry_scope" not in text, f"registry_scope still referenced in {path}"


def test_octopus_sdk_never_imports_app_modules() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    sdk_root = repo_root / "octopus_sdk"
    python_files = sorted(path for path in sdk_root.rglob("*.py") if "__pycache__" not in path.parts)
    pattern = re.compile(r"^\s*(|import)\s+app(\.|$)", re.MULTILINE)
    for path in python_files:
        text = path.read_text()
        assert pattern.search(text) is None, f"octopus_sdk imports app code in {path}"


def test_runtime_composition_does_not_reach_into_telegram_transport_internals() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    services_path = repo_root / "app" / "runtime" / "services.py"
    text = services_path.read_text()
    forbidden = (
        "telegram_transport.application",
        "telegram_transport.runtime",
        "telegram_transport.worker_dispatch",
        "telegram_transport.worker_deserialize_failure_notifier",
        "telegram_transport._start_worker_task",
        "telegram_transport._stop_worker_task",
    )
    for token in forbidden:
        assert token not in text, f"{token} still referenced in runtime composition"


def test_runtime_startup_does_not_use_deleted_noop_bot_services_builder() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    candidate_paths = (
        repo_root / "app" / "main.py",
        repo_root / "app" / "runtime" / "startup.py",
        repo_root / "app" / "runtime" / "services.py",
        repo_root / "app" / "channels" / "telegram" / "channel.py",
        repo_root / "app" / "channels" / "telegram" / "bootstrap.py",
        repo_root / "app" / "channels" / "telegram" / "state.py",
        repo_root / "app" / "channels" / "telegram" / "egress.py",
    )
    for path in candidate_paths:
        text = path.read_text()
        assert "build_noop_bot_services" not in text, f"deleted noop builder still referenced in {path}"


def test_main_entrypoint_uses_startup_and_builder_seams_only() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    main_path = repo_root / "app" / "main.py"
    text = main_path.read_text()

    assert "initialize_runtime_startup(" in text
    assert "build_runtime(" in text
    forbidden = (
        "ensure_data_dirs(",
        "init_content_store_for_config(",
        "init_credential_store_for_config(",
        "recover_stale_claims(",
        "purge_old(",
        "ControlPlaneBus(",
        "TransportDispatcher(",
        "register_registry_channels(",
        "build_registry_delivery_transport(",
        "TelegramTransport(",
        "build_worker_bundle(",
    )
    for token in forbidden:
        assert token not in text, f"{token} still referenced in thin entrypoint {main_path}"


def test_entrypoint_and_runtime_builder_stay_thin() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    main_path = repo_root / "app" / "main.py"
    services_path = repo_root / "app" / "runtime" / "services.py"

    assert sum(1 for _ in main_path.open()) <= 100, f"{main_path} exceeded thin-entrypoint target"
    assert sum(1 for _ in services_path.open()) <= 120, f"{services_path} exceeded thin-composition target"


def test_runtime_builder_does_not_inline_low_level_service_or_transport_wiring() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    services_path = repo_root / "app" / "runtime" / "services.py"
    text = services_path.read_text()
    forbidden = (
        "BusConversationProjection(",
        "BusTaskRouting(",
        "BusAgentDirectory(",
        "BusHealthPublication(",
        "TelegramTransport(",
        "build_bootstrap(",
        "build_worker_bundle(",
        "register_registry_channels(",
        "build_registry_delivery_transport(",
    )
    for token in forbidden:
        assert token not in text, f"{token} still referenced in thin runtime builder {services_path}"


def test_registry_delivery_transport_is_the_only_live_owner_of_agent_runtime_lifecycle() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    app_root = repo_root / "app"
    allowed = {
        app_root / "runtime" / "registry_participant.py",
        app_root / "channels" / "registry" / "delivery_transport.py",
    }
    for path in sorted(app_root.rglob("*.py")):
        if path in allowed or "__pycache__" in path.parts:
            continue
        text = path.read_text()
        assert "AgentRuntime" not in text, f"live AgentRuntime ownership leaked into {path}"


def test_registry_delivery_helpers_are_confined_to_registry_delivery_path() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    app_root = repo_root / "app"
    allowed = {
        app_root / "channels" / "registry" / "delivery_transport.py",
    }
    forbidden = (
        "app.agents.bridge",
        "app.agents.delivery",
        "handle_registry_delivery(",
        "build_registry_delivery_runtime(",
        "admit_registry_delivery(",
        "build_registry_message_envelope(",
        "build_registry_action_envelope(",
    )
    for path in sorted(app_root.rglob("*.py")):
        if path in allowed or "__pycache__" in path.parts:
            continue
        text = path.read_text()
        for token in forbidden:
            assert token not in text, f"{token} still leaked outside registry delivery path in {path}"


def test_test_suite_does_not_patch_deleted_main_runtime_setup_hooks() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    tests_root = repo_root / "tests"
    gate_path = Path(__file__).resolve()
    forbidden = (
        'patch("app.main.ensure_data_dirs"',
        'patch("app.main.init_content_store_for_config"',
        'patch("app.main.init_credential_store_for_config"',
        'patch("app.main.recover_stale_claims"',
        'patch("app.main.purge_old"',
    )
    for path in sorted(
        candidate for candidate in tests_root.rglob("*.py") if "__pycache__" not in candidate.parts and candidate != gate_path
    ):
        text = path.read_text()
        for token in forbidden:
            assert token not in text, f"{token} still referenced in {path}"
