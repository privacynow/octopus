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
    "app.channels.registry.ui",
    "app.ports",
    "app.runtime",
    "app.runtime.inbound_types",
    "app.workflows",
    "app.workflows.runtime_skills",
    "app.workflows.runtime_skills.contracts",
    "app.workflows.credentials",
    "app.workflows.credentials.contracts",
    "app.workflows.conversation",
    "app.workflows.conversation.contracts",
    "app.workflows.pending",
    "app.workflows.pending.contracts",
    "app.workflows.recovery",
    "app.workflows.recovery.contracts",
    "app.workflows.provider_guidance",
    "app.workflows.provider_guidance.contracts",
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
    "app/registry_service/app.py",
    "app/registry_service/runtime_surface.py",
    "app/telegram_handlers.py",
    "app/skill_commands.py",
    "app/telegram_runtime_skill_surface.py",
    "app/telegram_conversation_surface.py",
    "app/telegram_pending_request_surface.py",
    "app/transport.py",
)


def test_channel_architecture_skeleton_modules_exist() -> None:
    for module_name in EXPECTED_MODULES:
        module = importlib.import_module(module_name)
        assert module.__doc__


def test_top_level_workflow_port_modules_are_deleted() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    for rel_path in REMOVED_TOP_LEVEL_PORT_MODULES:
        assert not (repo_root / rel_path).exists(), rel_path
