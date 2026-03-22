import importlib
from pathlib import Path


EXPECTED_MODULES = (
    "app.channels",
    "app.channels.telegram",
    "app.channels.telegram.bootstrap",
    "app.channels.telegram.conversation",
    "app.channels.telegram.ingress",
    "app.channels.telegram.normalization",
    "app.channels.telegram.pending",
    "app.channels.telegram.presenters",
    "app.channels.telegram.runtime_skills",
    "app.channels.registry",
    "app.channels.registry.ingress",
    "app.channels.registry.http",
    "app.channels.registry.presenters",
    "app.channels.registry.ws",
    "app.ports",
    "app.runtime",
    "app.runtime.dispatch",
    "app.runtime.inbound_types",
    "app.runtime.session_runtime",
    "app.runtime.work_admission",
    "app.workflows",
    "app.workflows.runtime_skills",
    "app.workflows.runtime_skills.activation",
    "app.workflows.runtime_skills.catalog",
    "app.workflows.runtime_skills.contracts",
    "app.workflows.runtime_skills.importing",
    "app.workflows.runtime_skills.setup",
    "app.workflows.credentials",
    "app.workflows.credentials.contracts",
    "app.workflows.credentials.management",
    "app.workflows.conversation",
    "app.workflows.conversation.control",
    "app.workflows.conversation.contracts",
    "app.workflows.conversation.settings",
    "app.workflows.execution",
    "app.workflows.execution.contracts",
    "app.workflows.execution.requests",
    "app.workflows.pending",
    "app.workflows.pending.contracts",
    "app.workflows.pending.machine",
    "app.workflows.pending.requests",
    "app.workflows.recovery",
    "app.workflows.recovery.contracts",
    "app.workflows.recovery.machine",
    "app.workflows.recovery.replay",
    "app.workflows.recovery.results",
    "app.workflows.recovery.transport_contract",
    "app.workflows.provider_guidance",
    "app.workflows.provider_guidance.contracts",
    "app.workflows.provider_guidance.preview",
)

REMOVED_TOP_LEVEL_PORT_MODULES = (
    "app/inbound_use_case_factory.py",
    "app/credential_management_port.py",
    "app/conversation_control_port.py",
    "app/conversation_settings_port.py",
    "app/pending_request_port.py",
    "app/provider_guidance_port.py",
    "app/recovery_port.py",
    "app/runtime_skill_activation_port.py",
    "app/runtime_skill_catalog_port.py",
    "app/runtime_skill_import_port.py",
    "app/runtime_skill_setup_port.py",
    "app/conversation_control_use_cases.py",
    "app/conversation_settings_use_cases.py",
    "app/credential_management_use_cases.py",
    "app/pending_request_use_cases.py",
    "app/provider_guidance_use_cases.py",
    "app/recovery_use_cases.py",
    "app/runtime_skill_activation_use_cases.py",
    "app/runtime_skill_catalog_use_cases.py",
    "app/runtime_skill_import_use_cases.py",
    "app/runtime_skill_setup_use_cases.py",
    "app/registry_service/app.py",
    "app/registry_service/runtime_surface.py",
    "app/request_runtime.py",
    "app/telegram_handlers.py",
    "app/skill_commands.py",
    "app/telegram_runtime_skill_surface.py",
    "app/telegram_conversation_surface.py",
    "app/telegram_pending_request_surface.py",
    "app/channels/telegram/routing.py",
    "app/transport.py",
    "app/transport_contract.py",
    "app/transports/admission.py",
    "app/transports/__init__.py",
    "app/transports/types.py",
    "app/workflows/pending_request.py",
    "app/workflows/transport_recovery.py",
    "app/workflows/results.py",
)


def test_channel_architecture_skeleton_modules_exist() -> None:
    for module_name in EXPECTED_MODULES:
        module = importlib.import_module(module_name)
        assert module.__doc__


def test_top_level_workflow_port_modules_are_deleted() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    for rel_path in REMOVED_TOP_LEVEL_PORT_MODULES:
        assert not (repo_root / rel_path).exists(), rel_path
