"""Workflow composition and channel-agnostic runtime helpers."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING

from app.config import BotConfig
if TYPE_CHECKING:
    from app.workflows.conversation.contracts import ConversationControlPort, ConversationSettingsPort
    from app.workflows.credentials.contracts import CredentialManagementPort
    from app.workflows.pending.contracts import PendingRequestPort
    from app.workflows.provider_guidance.contracts import (
        ProviderGuidanceManagementPort,
        ProviderGuidancePort,
    )
    from app.workflows.recovery.contracts import RecoveryPort
    from app.workflows.runtime_skills.contracts import (
        RuntimeSkillActivationPort,
        RuntimeSkillApprovalPort,
        RuntimeSkillAuthoringPort,
        RuntimeSkillCatalogPort,
        RuntimeSkillImportPort,
        RuntimeSkillSetupPort,
    )


@dataclass(frozen=True)
class RuntimeSkillWorkflows:
    catalog: "RuntimeSkillCatalogPort"
    activation: "RuntimeSkillActivationPort"
    imports: "RuntimeSkillImportPort"
    setup: "RuntimeSkillSetupPort"
    authoring: "RuntimeSkillAuthoringPort"
    approval: "RuntimeSkillApprovalPort"


@dataclass(frozen=True)
class CredentialWorkflows:
    management: "CredentialManagementPort"


@dataclass(frozen=True)
class ConversationWorkflows:
    control: "ConversationControlPort"
    settings: "ConversationSettingsPort"


@dataclass(frozen=True)
class PendingWorkflows:
    requests: "PendingRequestPort"


@dataclass(frozen=True)
class RecoveryWorkflows:
    replay: "RecoveryPort"


@dataclass(frozen=True)
class ProviderGuidanceWorkflows:
    preview: "ProviderGuidancePort"
    management: "ProviderGuidanceManagementPort"


@dataclass(frozen=True)
class WorkflowComposition:
    runtime_skills: RuntimeSkillWorkflows
    credentials: CredentialWorkflows
    conversation: ConversationWorkflows
    pending: PendingWorkflows
    recovery: RecoveryWorkflows
    provider_guidance: ProviderGuidanceWorkflows


@lru_cache(maxsize=1)
def workflows() -> WorkflowComposition:
    from app.workflows.conversation.control import get_conversation_control_use_cases
    from app.workflows.conversation.settings import get_conversation_settings_use_cases
    from app.workflows.credentials.management import get_credential_management_use_cases
    from app.workflows.pending.requests import get_pending_request_use_cases
    from app.workflows.provider_guidance.management import get_provider_guidance_management_use_cases
    from app.workflows.provider_guidance.preview import get_provider_guidance_use_cases
    from app.workflows.recovery.replay import get_recovery_use_cases
    from app.workflows.runtime_skills.approval import get_runtime_skill_approval_use_cases
    from app.workflows.runtime_skills.activation import get_runtime_skill_activation_use_cases
    from app.workflows.runtime_skills.authoring import get_runtime_skill_authoring_use_cases
    from app.workflows.runtime_skills.catalog import get_runtime_skill_catalog_use_cases
    from app.workflows.runtime_skills.importing import get_runtime_skill_import_use_cases
    from app.workflows.runtime_skills.setup import get_runtime_skill_setup_use_cases

    return WorkflowComposition(
        runtime_skills=RuntimeSkillWorkflows(
            catalog=get_runtime_skill_catalog_use_cases(),
            activation=get_runtime_skill_activation_use_cases(),
            imports=get_runtime_skill_import_use_cases(),
            setup=get_runtime_skill_setup_use_cases(),
            authoring=get_runtime_skill_authoring_use_cases(),
            approval=get_runtime_skill_approval_use_cases(),
        ),
        credentials=CredentialWorkflows(
            management=get_credential_management_use_cases(),
        ),
        conversation=ConversationWorkflows(
            control=get_conversation_control_use_cases(),
            settings=get_conversation_settings_use_cases(),
        ),
        pending=PendingWorkflows(
            requests=get_pending_request_use_cases(),
        ),
        recovery=RecoveryWorkflows(
            replay=get_recovery_use_cases(),
        ),
        provider_guidance=ProviderGuidanceWorkflows(
            preview=get_provider_guidance_use_cases(),
            management=get_provider_guidance_management_use_cases(),
        ),
    )
