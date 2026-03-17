"""Composition entry point for current inbound use-case contracts."""

from __future__ import annotations

from app.credential_management_port import CredentialManagementPort
from app.conversation_control_port import ConversationControlPort
from app.conversation_settings_port import ConversationSettingsPort
from app.pending_request_port import PendingRequestPort
from app.provider_guidance_port import ProviderGuidancePort
from app.recovery_port import RecoveryPort
from app.runtime_skill_activation_port import RuntimeSkillActivationPort
from app.runtime_skill_catalog_port import RuntimeSkillCatalogPort
from app.runtime_skill_import_port import RuntimeSkillImportPort
from app.runtime_skill_setup_port import RuntimeSkillSetupPort


def get_runtime_skill_catalog_use_cases() -> RuntimeSkillCatalogPort:
    from app.runtime_skill_catalog_use_cases import get_runtime_skill_catalog_use_cases as _get

    return _get()


def get_runtime_skill_activation_use_cases() -> RuntimeSkillActivationPort:
    from app.runtime_skill_activation_use_cases import get_runtime_skill_activation_use_cases as _get

    return _get()


def get_runtime_skill_import_use_cases() -> RuntimeSkillImportPort:
    from app.runtime_skill_import_use_cases import get_runtime_skill_import_use_cases as _get

    return _get()


def get_runtime_skill_setup_use_cases() -> RuntimeSkillSetupPort:
    from app.runtime_skill_setup_use_cases import get_runtime_skill_setup_use_cases as _get

    return _get()


def get_credential_management_use_cases() -> CredentialManagementPort:
    from app.credential_management_use_cases import get_credential_management_use_cases as _get

    return _get()


def get_conversation_control_use_cases() -> ConversationControlPort:
    from app.conversation_control_use_cases import get_conversation_control_use_cases as _get

    return _get()


def get_conversation_settings_use_cases() -> ConversationSettingsPort:
    from app.conversation_settings_use_cases import get_conversation_settings_use_cases as _get

    return _get()


def get_pending_request_use_cases() -> PendingRequestPort:
    from app.pending_request_use_cases import get_pending_request_use_cases as _get

    return _get()


def get_recovery_use_cases() -> RecoveryPort:
    from app.recovery_use_cases import get_recovery_use_cases as _get

    return _get()


def get_provider_guidance_use_cases() -> ProviderGuidancePort:
    from app.provider_guidance_use_cases import get_provider_guidance_use_cases as _get

    return _get()
