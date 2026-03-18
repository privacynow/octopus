"""Channel composition, workflow wiring, and egress construction."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from app.access import trust_tier
from app.config import BotConfig
from app.identity import telegram_conversation_key, telegram_numeric_id
from app.ports.egress import ChannelEgress

if TYPE_CHECKING:
    from app.workflows.conversation.contracts import ConversationControlPort, ConversationSettingsPort
    from app.workflows.credentials.contracts import CredentialManagementPort
    from app.workflows.pending.contracts import PendingRequestPort
    from app.workflows.provider_guidance.contracts import ProviderGuidancePort
    from app.workflows.recovery.contracts import RecoveryPort
    from app.workflows.runtime_skills.contracts import (
        RuntimeSkillActivationPort,
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
    from app.conversation_control_use_cases import get_conversation_control_use_cases
    from app.conversation_settings_use_cases import get_conversation_settings_use_cases
    from app.credential_management_use_cases import get_credential_management_use_cases
    from app.pending_request_use_cases import get_pending_request_use_cases
    from app.provider_guidance_use_cases import get_provider_guidance_use_cases
    from app.recovery_use_cases import get_recovery_use_cases
    from app.runtime_skill_activation_use_cases import get_runtime_skill_activation_use_cases
    from app.runtime_skill_catalog_use_cases import get_runtime_skill_catalog_use_cases
    from app.runtime_skill_import_use_cases import get_runtime_skill_import_use_cases
    from app.runtime_skill_setup_use_cases import get_runtime_skill_setup_use_cases

    return WorkflowComposition(
        runtime_skills=RuntimeSkillWorkflows(
            catalog=get_runtime_skill_catalog_use_cases(),
            activation=get_runtime_skill_activation_use_cases(),
            imports=get_runtime_skill_import_use_cases(),
            setup=get_runtime_skill_setup_use_cases(),
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
        ),
    )


def conversation_channel_name(conversation_ref: str) -> str:
    if conversation_ref.startswith("telegram:"):
        return "telegram"
    return "registry"


def create_channel_egress(
    conversation_ref: str,
    *,
    config: BotConfig,
    bot: Any,
    conversation_key: str = "",
    chat_id: int | None = None,
    target_message_id: int | None = None,
    source: str,
    routed_task_id: str = "",
    output_log: list | None = None,
) -> ChannelEgress:
    if not conversation_key and chat_id is not None:
        conversation_key = telegram_conversation_key(chat_id)
    if not conversation_key:
        conversation_key = conversation_ref
    if conversation_channel_name(conversation_ref) == "telegram":
        if bot is None:
            raise RuntimeError("Telegram channel requires a bot instance")
        numeric_chat_id = telegram_numeric_id(conversation_key)
        if numeric_chat_id is None:
            raise RuntimeError(
                f"Telegram channel requires a Telegram conversation key, got {conversation_key!r}"
            )
        from app.channels.telegram.egress import TelegramChannelEgress

        return TelegramChannelEgress(
            bot,
            numeric_chat_id,
            config=config,
            conversation_ref=conversation_ref,
            mirror_input_event=(source == "telegram"),
            target_message_id=target_message_id,
        )

    from app.channels.registry.egress import RegistryChannelEgress

    return RegistryChannelEgress(
        config,
        conversation_ref=conversation_ref,
        routed_task_id=routed_task_id,
        output_log=output_log,
    )


def trust_tier_for_source(source: str, user: Any, *, config: BotConfig) -> str:
    if source == "registry":
        return "trusted"
    return trust_tier(config, user)
