from app.conversation_control_use_cases import get_conversation_control_use_cases
from app.conversation_settings_use_cases import get_conversation_settings_use_cases
from app.credential_management_use_cases import get_credential_management_use_cases
from app.pending_request_use_cases import get_pending_request_use_cases
from app.provider_guidance_use_cases import get_provider_guidance_use_cases
from app.recovery_use_cases import get_recovery_use_cases
from app.runtime import composition
from app.runtime_skill_activation_use_cases import get_runtime_skill_activation_use_cases
from app.runtime_skill_catalog_use_cases import get_runtime_skill_catalog_use_cases
from app.runtime_skill_import_use_cases import get_runtime_skill_import_use_cases
from app.runtime_skill_setup_use_cases import get_runtime_skill_setup_use_cases


def test_workflow_composition_groups_current_workflow_singletons() -> None:
    flows = composition.workflows()
    assert flows is composition.workflows()
    assert flows.runtime_skills.catalog is get_runtime_skill_catalog_use_cases()
    assert flows.runtime_skills.activation is get_runtime_skill_activation_use_cases()
    assert flows.runtime_skills.imports is get_runtime_skill_import_use_cases()
    assert flows.runtime_skills.setup is get_runtime_skill_setup_use_cases()
    assert flows.credentials.management is get_credential_management_use_cases()
    assert flows.conversation.control is get_conversation_control_use_cases()
    assert flows.conversation.settings is get_conversation_settings_use_cases()
    assert flows.pending.requests is get_pending_request_use_cases()
    assert flows.recovery.replay is get_recovery_use_cases()
    assert flows.provider_guidance.preview is get_provider_guidance_use_cases()
