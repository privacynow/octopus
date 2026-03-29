"""SDK-owned workflow contracts for the full operator experience.

This package re-exports workflow contracts lazily so importing one workflow
submodule does not force eager initialization of all sibling modules.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

_EXPORTS = {
    "LifecycleDecision": "octopus_sdk.workflows.lifecycle_machine",
    "LifecycleEffects": "octopus_sdk.workflows.lifecycle_machine",
    "LifecycleSnapshot": "octopus_sdk.workflows.lifecycle_machine",
    "PublishedPointer": "octopus_sdk.workflows.lifecycle_machine",
    "build_lifecycle_snapshot": "octopus_sdk.workflows.lifecycle_machine",
    "decide_lifecycle_action": "octopus_sdk.workflows.lifecycle_machine",
    "DelegationApprovalPreparation": "octopus_sdk.workflows.delegation",
    "DelegationTargetPreview": "octopus_sdk.workflows.delegation",
    "DelegationUpdateOutcome": "octopus_sdk.workflows.delegation",
    "ConversationCancelOutcome": "octopus_sdk.workflows.conversation",
    "ConversationControlPort": "octopus_sdk.workflows.conversation",
    "ConversationResetOutcome": "octopus_sdk.workflows.conversation",
    "ConversationSettingsPort": "octopus_sdk.workflows.conversation",
    "ModelProfileState": "octopus_sdk.workflows.conversation",
    "ProviderStateFactory": "octopus_sdk.workflows.conversation",
    "SettingMutationOutcome": "octopus_sdk.workflows.conversation",
    "CredentialClearOutcome": "octopus_sdk.workflows.credentials",
    "CredentialManagementPort": "octopus_sdk.workflows.credentials",
    "PendingExecutionPlan": "octopus_sdk.workflows.pending",
    "PendingRequestOutcome": "octopus_sdk.workflows.pending",
    "PendingRequestPort": "octopus_sdk.workflows.pending",
    "ProviderGuidanceLifecycleApproval": "octopus_sdk.workflows.provider_guidance",
    "ProviderGuidanceLifecycleDetail": "octopus_sdk.workflows.provider_guidance",
    "ProviderGuidanceLifecycleMutation": "octopus_sdk.workflows.provider_guidance",
    "ProviderGuidanceLifecycleRevision": "octopus_sdk.workflows.provider_guidance",
    "ProviderGuidanceManagementPort": "octopus_sdk.workflows.provider_guidance",
    "ProviderGuidancePort": "octopus_sdk.workflows.provider_guidance",
    "ProviderGuidancePreview": "octopus_sdk.workflows.provider_guidance",
    "RecoveryActionOutcome": "octopus_sdk.workflows.recovery",
    "RecoveryPort": "octopus_sdk.workflows.recovery",
    "RecoveryReplayPlan": "octopus_sdk.workflows.recovery",
    "WorkerRecoveryNotice": "octopus_sdk.workflows.recovery",
    "WorkerRecoveryOutcome": "octopus_sdk.workflows.recovery",
    "ConversationSkillItem": "octopus_sdk.workflows.skills",
    "ConversationSkillListing": "octopus_sdk.workflows.skills",
    "ConversationSkillMutationOutcome": "octopus_sdk.workflows.skills",
    "PromptWarningContext": "octopus_sdk.workflows.skills",
    "RegistryRuntimeSkillSearchHit": "octopus_sdk.workflows.skills",
    "RuntimeSkillActivationPort": "octopus_sdk.workflows.skills",
    "RuntimeSkillApprovalPort": "octopus_sdk.workflows.skills",
    "RuntimeSkillAuthoringPort": "octopus_sdk.workflows.skills",
    "RuntimeSkillCatalogItem": "octopus_sdk.workflows.skills",
    "RuntimeSkillCatalogPort": "octopus_sdk.workflows.skills",
    "RuntimeSkillCredentialClearOutcome": "octopus_sdk.workflows.skills",
    "RuntimeSkillCredentialSatisfactionOutcome": "octopus_sdk.workflows.skills",
    "RuntimeSkillDetail": "octopus_sdk.workflows.skills",
    "RuntimeSkillDraftRecord": "octopus_sdk.workflows.skills",
    "RuntimeSkillImportPort": "octopus_sdk.workflows.skills",
    "RuntimeSkillLifecycleApproval": "octopus_sdk.workflows.skills",
    "RuntimeSkillLifecycleDetail": "octopus_sdk.workflows.skills",
    "RuntimeSkillLifecycleMutation": "octopus_sdk.workflows.skills",
    "RuntimeSkillLifecycleRevision": "octopus_sdk.workflows.skills",
    "RuntimeSkillMutationOutcome": "octopus_sdk.workflows.skills",
    "RuntimeSkillSearchResults": "octopus_sdk.workflows.skills",
    "RuntimeSkillSetupAdvanceOutcome": "octopus_sdk.workflows.skills",
    "RuntimeSkillSetupCancellationOutcome": "octopus_sdk.workflows.skills",
    "RuntimeSkillSetupPort": "octopus_sdk.workflows.skills",
    "RuntimeSkillSetupState": "octopus_sdk.workflows.skills",
    "RuntimeSkillUpdateStatusItem": "octopus_sdk.workflows.skills",
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(name)
    module = import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value


if TYPE_CHECKING:
    from octopus_sdk.workflows.conversation import (
        ConversationCancelOutcome,
        ConversationControlPort,
        ConversationResetOutcome,
        ConversationSettingsPort,
        ModelProfileState,
        ProviderStateFactory,
        SettingMutationOutcome,
    )
    from octopus_sdk.workflows.credentials import (
        CredentialClearOutcome,
        CredentialManagementPort,
    )
    from octopus_sdk.workflows.delegation import (
        DelegationApprovalPreparation,
        DelegationTargetPreview,
        DelegationUpdateOutcome,
    )
    from octopus_sdk.workflows.lifecycle_machine import (
        LifecycleDecision,
        LifecycleEffects,
        LifecycleSnapshot,
        PublishedPointer,
        build_lifecycle_snapshot,
        decide_lifecycle_action,
    )
    from octopus_sdk.workflows.pending import (
        PendingExecutionPlan,
        PendingRequestOutcome,
        PendingRequestPort,
    )
    from octopus_sdk.workflows.provider_guidance import (
        ProviderGuidanceLifecycleApproval,
        ProviderGuidanceLifecycleDetail,
        ProviderGuidanceLifecycleMutation,
        ProviderGuidanceLifecycleRevision,
        ProviderGuidanceManagementPort,
        ProviderGuidancePort,
        ProviderGuidancePreview,
    )
    from octopus_sdk.workflows.recovery import (
        RecoveryActionOutcome,
        RecoveryPort,
        RecoveryReplayPlan,
        WorkerRecoveryNotice,
        WorkerRecoveryOutcome,
    )
    from octopus_sdk.workflows.skills import (
        ConversationSkillItem,
        ConversationSkillListing,
        ConversationSkillMutationOutcome,
        PromptWarningContext,
        RegistryRuntimeSkillSearchHit,
        RuntimeSkillActivationPort,
        RuntimeSkillApprovalPort,
        RuntimeSkillAuthoringPort,
        RuntimeSkillCatalogItem,
        RuntimeSkillCatalogPort,
        RuntimeSkillCredentialClearOutcome,
        RuntimeSkillCredentialSatisfactionOutcome,
        RuntimeSkillDetail,
        RuntimeSkillDraftRecord,
        RuntimeSkillImportPort,
        RuntimeSkillLifecycleApproval,
        RuntimeSkillLifecycleDetail,
        RuntimeSkillLifecycleMutation,
        RuntimeSkillLifecycleRevision,
        RuntimeSkillMutationOutcome,
        RuntimeSkillSearchResults,
        RuntimeSkillSetupAdvanceOutcome,
        RuntimeSkillSetupCancellationOutcome,
        RuntimeSkillSetupPort,
        RuntimeSkillSetupState,
        RuntimeSkillUpdateStatusItem,
    )
