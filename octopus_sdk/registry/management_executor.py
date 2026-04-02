"""Bot-side execution of registry management requests."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from octopus_sdk.bot_runtime import ExecutionFaultStatePort, WorkflowComposition
from octopus_sdk.config import BotConfigBase
from octopus_sdk.providers import ProviderStateRecord
from octopus_sdk.sessions import SessionState
from octopus_sdk.workflows.conversation import SettingMutationOutcome
from octopus_sdk.registry.management import (
    ActivateConversationSkillRequest,
    ActivateConversationSkillResult,
    ArchiveCatalogSkillRequest,
    ArchiveCatalogSkillResult,
    ArchiveProviderGuidanceRequest,
    ArchiveProviderGuidanceResult,
    ApproveCatalogSkillRequest,
    ApproveCatalogSkillResult,
    ApproveProviderGuidanceRequest,
    ApproveProviderGuidanceResult,
    CatalogSkillDetailRequest,
    CatalogSkillDetailResult,
    CatalogSkillLifecycleDetailRequest,
    CatalogSkillLifecycleDetailResult,
    ClearConversationSkillsRequest,
    ClearConversationSkillsResult,
    ConversationSettingsStateRecord,
    ConversationSettingsStateRequest,
    ConversationSettingsStateResult,
    ConversationSkillSetupPromptRecord,
    ConversationSkillStateRequest,
    ConversationSkillStateResult,
    DeactivateConversationSkillRequest,
    DeactivateConversationSkillResult,
    DiffCatalogSkillRequest,
    DiffCatalogSkillResult,
    EditCatalogSkillDraftRequest,
    EditCatalogSkillDraftResult,
    EditProviderGuidanceDraftRequest,
    EditProviderGuidanceDraftResult,
    InstallCatalogSkillRequest,
    InstallCatalogSkillResult,
    ListCatalogSkillsRequest,
    ListCatalogSkillsResult,
    ManagementRequest,
    ManagementResult,
    ResetConversationRequest,
    ResetConversationResult,
    PreviewProviderGuidanceRequest,
    PreviewProviderGuidanceResult,
    ProviderGuidanceDetailRequest,
    ProviderGuidanceDetailResult,
    PublishCatalogSkillRequest,
    PublishCatalogSkillResult,
    PublishProviderGuidanceRequest,
    PublishProviderGuidanceResult,
    RejectCatalogSkillRequest,
    RejectCatalogSkillResult,
    RejectProviderGuidanceRequest,
    RejectProviderGuidanceResult,
    ResetExecutionFaultRequest,
    ResetExecutionFaultResult,
    SetConversationSettingRequest,
    SetConversationSettingResult,
    SearchCatalogSkillsRequest,
    SearchCatalogSkillsResult,
    SubmitConversationSkillCredentialRequest,
    SubmitConversationSkillCredentialResult,
    SubmitCatalogSkillRequest,
    SubmitCatalogSkillResult,
    SubmitProviderGuidanceRequest,
    SubmitProviderGuidanceResult,
    UninstallCatalogSkillRequest,
    UninstallCatalogSkillResult,
    UpdateCatalogSkillRequest,
    UpdateCatalogSkillResult,
    conversation_skill_listing_record,
    conversation_skill_mutation_outcome_record,
    conversation_skill_setup_advance_outcome_record,
    conversation_reset_outcome_record,
    conversation_setting_mutation_record,
    provider_guidance_lifecycle_detail_record,
    provider_guidance_lifecycle_mutation_record,
    provider_guidance_preview_record,
    runtime_skill_catalog_item_record,
    runtime_skill_detail_record,
    runtime_skill_lifecycle_detail_record,
    runtime_skill_lifecycle_mutation_record,
    runtime_skill_mutation_outcome_record,
    runtime_skill_search_results_record,
    skill_requirement_record,
)
from octopus_sdk.workflows.skills import PromptWarningContext


ProviderStateFactory = Callable[[str], ProviderStateRecord]


@dataclass(frozen=True)
class ManagementExecutionContext:
    config: BotConfigBase
    workflows: WorkflowComposition
    provider_state_factory: ProviderStateFactory
    execution_faults: ExecutionFaultStatePort | None = None


def _warning_context(context: ManagementExecutionContext) -> PromptWarningContext | None:
    registry_url = str(context.config.registry_url or "").strip()
    if not registry_url:
        return None
    return PromptWarningContext(
        data_dir=context.config.data_dir,
        provider_name=context.config.provider_name,
        provider_state_factory=context.provider_state_factory,
        approval_mode=context.config.approval_mode,
    )


def _session_for_request(
    context: ManagementExecutionContext,
    *,
    conversation_key: str,
):
    sessions = context.workflows.sessions
    if sessions is None:
        raise RuntimeError("Workflow composition does not provide a session runtime.")
    return sessions.load(
        conversation_key,
        provider_name=context.config.provider_name,
        provider_state_factory=context.provider_state_factory,
        approval_mode=context.config.approval_mode,
        default_role=context.config.role,
        default_skills=context.config.default_skills,
    )


def _save_session(
    context: ManagementExecutionContext,
    *,
    conversation_key: str,
    session: SessionState,
) -> None:
    sessions = context.workflows.sessions
    if sessions is None:
        raise RuntimeError("Workflow composition does not provide a session runtime.")
    sessions.save(conversation_key, session)


def _conversation_skill_state_result(
    context: ManagementExecutionContext,
    request: ConversationSkillStateRequest,
) -> ConversationSkillStateResult:
    sessions = context.workflows.sessions
    if sessions is None:
        raise RuntimeError("Workflow composition does not provide a session runtime.")
    session = _session_for_request(context, conversation_key=request.conversation_key)
    resolved = sessions.resolve_context(
        session,
        config=context.config,
        provider_name=context.config.provider_name,
        trust_tier="trusted",
    )
    listing = context.workflows.runtime_skills.activation.list_conversation_skills(
        list(resolved.active_skills)
    )
    return ConversationSkillStateResult(
        conversation_id=request.conversation_id,
        conversation_key=request.conversation_key,
        listing=conversation_skill_listing_record(listing),
        pending_setup=(
            ConversationSkillSetupPromptRecord(
                skill_name=str(session.awaiting_skill_setup.skill or ""),
                actor_key=str(session.awaiting_skill_setup.actor_key or ""),
                requirement=(
                    skill_requirement_record(session.awaiting_skill_setup.remaining[0])
                    if session.awaiting_skill_setup.remaining
                    else None
                ),
            )
            if session.awaiting_skill_setup is not None and session.awaiting_skill_setup.remaining
            else None
        ),
    )


def _conversation_settings_state(
    context: ManagementExecutionContext,
    *,
    conversation_id: str,
    conversation_key: str,
    session: SessionState | None = None,
) -> ConversationSettingsStateRecord:
    sessions = context.workflows.sessions
    if sessions is None:
        raise RuntimeError("Workflow composition does not provide a session runtime.")
    current_session = session or _session_for_request(context, conversation_key=conversation_key)
    resolved = sessions.resolve_context(
        current_session,
        config=context.config,
        provider_name=context.config.provider_name,
        trust_tier="trusted",
    )
    model_state = context.workflows.conversation.settings.model_profile_state(
        current_session,
        context.config,
        "trusted",
        resolved.effective_model or context.config.model,
    )
    return ConversationSettingsStateRecord(
        conversation_id=conversation_id,
        conversation_key=conversation_key,
        role=str(current_session.role or ""),
        default_role=str(context.config.role or ""),
        approval_mode=str(current_session.approval_mode or context.config.approval_mode),
        approval_mode_explicit=bool(current_session.approval_mode_explicit),
        compact_mode=current_session.compact_mode,
        effective_compact_mode=bool(
            context.config.compact_mode if current_session.compact_mode is None else current_session.compact_mode
        ),
        model_profile=str(current_session.model_profile or ""),
        current_profile=str(model_state.current_profile or ""),
        effective_model=str(resolved.effective_model or context.config.model or ""),
        available_model_profiles=list(model_state.available_profiles),
        file_policy=str(current_session.file_policy or ""),
        effective_file_policy=str(resolved.file_policy or "edit"),
        project_id=str(current_session.project_id or ""),
        available_projects=[str(project.name) for project in context.config.projects],
    )


def _compact_mode_value(value: str) -> bool | None:
    normalized = str(value or "").strip().lower()
    if normalized in {"on", "true", "1"}:
        return True
    if normalized in {"off", "false", "0"}:
        return False
    return None


async def execute_management_request(
    request: ManagementRequest,
    *,
    context: ManagementExecutionContext,
) -> ManagementResult:
    payload = request.payload
    try:
        if isinstance(payload, ListCatalogSkillsRequest):
            result = context.workflows.runtime_skills.catalog.list_skills(payload.query)
            return ManagementResult(
                request_id=request.request_id,
                agent_id=request.agent_id,
                success=True,
                payload=ListCatalogSkillsResult(
                    items=tuple(runtime_skill_catalog_item_record(item) for item in result)
                ),
            )
        if isinstance(payload, SearchCatalogSkillsRequest):
            result = context.workflows.runtime_skills.imports.search(
                payload.query,
                registry_url=context.config.registry_url,
            )
            return ManagementResult(
                request_id=request.request_id,
                agent_id=request.agent_id,
                success=True,
                payload=SearchCatalogSkillsResult(
                    results=runtime_skill_search_results_record(result)
                ),
            )
        if isinstance(payload, CatalogSkillDetailRequest):
            detail = context.workflows.runtime_skills.catalog.get_skill(payload.skill_name)
            return ManagementResult(
                request_id=request.request_id,
                agent_id=request.agent_id,
                success=True,
                payload=CatalogSkillDetailResult(
                    detail=runtime_skill_detail_record(detail) if detail is not None else None
                ),
            )
        if isinstance(payload, CatalogSkillLifecycleDetailRequest):
            detail = context.workflows.runtime_skills.authoring.detail(payload.skill_name)
            return ManagementResult(
                request_id=request.request_id,
                agent_id=request.agent_id,
                success=True,
                payload=CatalogSkillLifecycleDetailResult(
                    detail=(
                        runtime_skill_lifecycle_detail_record(detail)
                        if detail is not None
                        else None
                    )
                ),
            )
        if isinstance(payload, EditCatalogSkillDraftRequest):
            authoring = context.workflows.runtime_skills.authoring
            if authoring.detail(payload.skill_name) is None:
                authoring.create_draft(payload.skill_name, owner_actor=payload.actor_key)
            mutation = authoring.edit_draft(
                payload.skill_name,
                actor_key=payload.actor_key,
                body=payload.body,
                description=payload.description or None,
                changelog=payload.changelog,
            )
            return ManagementResult(
                request_id=request.request_id,
                agent_id=request.agent_id,
                success=True,
                payload=EditCatalogSkillDraftResult(
                    result=runtime_skill_lifecycle_mutation_record(mutation)
                ),
            )
        if isinstance(payload, SubmitCatalogSkillRequest):
            mutation = context.workflows.runtime_skills.authoring.submit(
                payload.skill_name,
                actor_key=payload.actor_key,
                note=payload.note,
            )
            return ManagementResult(
                request_id=request.request_id,
                agent_id=request.agent_id,
                success=True,
                payload=SubmitCatalogSkillResult(
                    result=runtime_skill_lifecycle_mutation_record(mutation)
                ),
            )
        if isinstance(payload, ApproveCatalogSkillRequest):
            mutation = context.workflows.runtime_skills.approval.approve(
                payload.skill_name,
                actor_key=payload.actor_key,
                note=payload.note,
            )
            return ManagementResult(
                request_id=request.request_id,
                agent_id=request.agent_id,
                success=True,
                payload=ApproveCatalogSkillResult(
                    result=runtime_skill_lifecycle_mutation_record(mutation)
                ),
            )
        if isinstance(payload, RejectCatalogSkillRequest):
            mutation = context.workflows.runtime_skills.approval.reject(
                payload.skill_name,
                actor_key=payload.actor_key,
                note=payload.note,
            )
            return ManagementResult(
                request_id=request.request_id,
                agent_id=request.agent_id,
                success=True,
                payload=RejectCatalogSkillResult(
                    result=runtime_skill_lifecycle_mutation_record(mutation)
                ),
            )
        if isinstance(payload, PublishCatalogSkillRequest):
            mutation = context.workflows.runtime_skills.authoring.publish(
                payload.skill_name,
                actor_key=payload.actor_key,
                note=payload.note,
            )
            return ManagementResult(
                request_id=request.request_id,
                agent_id=request.agent_id,
                success=True,
                payload=PublishCatalogSkillResult(
                    result=runtime_skill_lifecycle_mutation_record(mutation)
                ),
            )
        if isinstance(payload, ArchiveCatalogSkillRequest):
            mutation = context.workflows.runtime_skills.authoring.archive(
                payload.skill_name,
                actor_key=payload.actor_key,
                note=payload.note,
            )
            return ManagementResult(
                request_id=request.request_id,
                agent_id=request.agent_id,
                success=True,
                payload=ArchiveCatalogSkillResult(
                    result=runtime_skill_lifecycle_mutation_record(mutation)
                ),
            )
        if isinstance(payload, InstallCatalogSkillRequest):
            registry_url = str(context.config.registry_url or "").strip()
            if not registry_url:
                return ManagementResult(
                    request_id=request.request_id,
                    agent_id=request.agent_id,
                    success=False,
                    error_code="request_failed",
                    error_detail="No skill registry configured.",
                )
            outcome = context.workflows.runtime_skills.imports.install_from_registry(
                payload.skill_name,
                registry_url,
                warning_context=_warning_context(context),
            )
            return ManagementResult(
                request_id=request.request_id,
                agent_id=request.agent_id,
                success=True,
                payload=InstallCatalogSkillResult(
                    result=runtime_skill_mutation_outcome_record(outcome)
                ),
            )
        if isinstance(payload, UninstallCatalogSkillRequest):
            outcome = context.workflows.runtime_skills.imports.uninstall(
                payload.skill_name,
                default_skills=context.config.default_skills,
            )
            return ManagementResult(
                request_id=request.request_id,
                agent_id=request.agent_id,
                success=True,
                payload=UninstallCatalogSkillResult(
                    result=runtime_skill_mutation_outcome_record(outcome)
                ),
            )
        if isinstance(payload, UpdateCatalogSkillRequest):
            outcome = context.workflows.runtime_skills.imports.update(
                payload.skill_name,
                warning_context=_warning_context(context),
            )
            return ManagementResult(
                request_id=request.request_id,
                agent_id=request.agent_id,
                success=True,
                payload=UpdateCatalogSkillResult(
                    result=runtime_skill_mutation_outcome_record(outcome)
                ),
            )
        if isinstance(payload, DiffCatalogSkillRequest):
            outcome = context.workflows.runtime_skills.imports.diff(payload.skill_name)
            return ManagementResult(
                request_id=request.request_id,
                agent_id=request.agent_id,
                success=True,
                payload=DiffCatalogSkillResult(
                    result=runtime_skill_mutation_outcome_record(outcome)
                ),
            )
        if isinstance(payload, ConversationSkillStateRequest):
            return ManagementResult(
                request_id=request.request_id,
                agent_id=request.agent_id,
                success=True,
                payload=_conversation_skill_state_result(context, payload),
            )
        if isinstance(payload, ActivateConversationSkillRequest):
            session = _session_for_request(context, conversation_key=payload.conversation_key)
            outcome = context.workflows.runtime_skills.activation.begin_activate(
                session,
                actor_key=payload.actor_key,
                skill_name=payload.skill_name,
                confirm=payload.confirm,
            )
            if outcome.mutated:
                _save_session(context, conversation_key=payload.conversation_key, session=session)
            return ManagementResult(
                request_id=request.request_id,
                agent_id=request.agent_id,
                success=True,
                payload=ActivateConversationSkillResult(
                    result=conversation_skill_mutation_outcome_record(outcome)
                ),
            )
        if isinstance(payload, DeactivateConversationSkillRequest):
            session = _session_for_request(context, conversation_key=payload.conversation_key)
            outcome = context.workflows.runtime_skills.activation.deactivate(
                session,
                actor_key=payload.actor_key,
                skill_name=payload.skill_name,
            )
            if outcome.mutated:
                _save_session(context, conversation_key=payload.conversation_key, session=session)
            return ManagementResult(
                request_id=request.request_id,
                agent_id=request.agent_id,
                success=True,
                payload=DeactivateConversationSkillResult(
                    result=conversation_skill_mutation_outcome_record(outcome)
                ),
            )
        if isinstance(payload, ClearConversationSkillsRequest):
            session = _session_for_request(context, conversation_key=payload.conversation_key)
            outcome = context.workflows.runtime_skills.activation.clear(
                session,
                actor_key=payload.actor_key,
            )
            if outcome.mutated:
                _save_session(context, conversation_key=payload.conversation_key, session=session)
            return ManagementResult(
                request_id=request.request_id,
                agent_id=request.agent_id,
                success=True,
                payload=ClearConversationSkillsResult(
                    result=conversation_skill_mutation_outcome_record(outcome)
                ),
            )
        if isinstance(payload, SubmitConversationSkillCredentialRequest):
            session = _session_for_request(context, conversation_key=payload.conversation_key)
            outcome = await context.workflows.runtime_skills.setup.submit_credential_value(
                session,
                actor_key=payload.actor_key,
                raw_value=payload.value,
            )
            if outcome.mutated:
                _save_session(context, conversation_key=payload.conversation_key, session=session)
            return ManagementResult(
                request_id=request.request_id,
                agent_id=request.agent_id,
                success=True,
                payload=SubmitConversationSkillCredentialResult(
                    result=conversation_skill_setup_advance_outcome_record(outcome)
                ),
            )
        if isinstance(payload, ConversationSettingsStateRequest):
            return ManagementResult(
                request_id=request.request_id,
                agent_id=request.agent_id,
                success=True,
                payload=ConversationSettingsStateResult(
                    state=_conversation_settings_state(
                        context,
                        conversation_id=payload.conversation_id,
                        conversation_key=payload.conversation_key,
                    ),
                ),
            )
        if isinstance(payload, SetConversationSettingRequest):
            session = _session_for_request(context, conversation_key=payload.conversation_key)
            settings = context.workflows.conversation.settings
            if payload.setting == "approval_mode":
                outcome = settings.set_approval_mode(session, str(payload.value or "").strip())
            elif payload.setting == "compact_mode":
                compact_mode = _compact_mode_value(payload.value)
                if compact_mode is None:
                    outcome = SettingMutationOutcome(
                        status="invalid",
                        message="Compact mode must be on or off.",
                    )
                else:
                    outcome = settings.set_compact_mode(session, compact_mode)
            elif payload.setting == "role":
                outcome = settings.set_role(
                    session,
                    str(payload.value or "").strip(),
                    default_role=context.config.role,
                )
            elif payload.setting == "model_profile":
                requested_value = str(payload.value or "").strip()
                if requested_value == "inherit":
                    requested_value = ""
                outcome = settings.set_model_profile(
                    session,
                    requested_value,
                    cfg=context.config,
                    provider_name=context.config.provider_name,
                    trust_tier="trusted",
                )
            elif payload.setting == "project":
                outcome = settings.set_project(
                    session,
                    str(payload.value or "").strip(),
                    cfg=context.config,
                    provider_state_factory=context.provider_state_factory,
                    conversation_key=payload.conversation_key,
                )
            elif payload.setting == "file_policy":
                requested_value = str(payload.value or "").strip()
                if requested_value == "inherit":
                    requested_value = ""
                outcome = settings.set_file_policy(
                    session,
                    requested_value,
                    cfg=context.config,
                    provider_name=context.config.provider_name,
                    trust_tier="trusted",
                    provider_state_factory=context.provider_state_factory,
                    conversation_key=payload.conversation_key,
                )
            else:
                outcome = SettingMutationOutcome(
                    status="invalid",
                    message=f"Unsupported setting: {payload.setting}",
                )
            if outcome.mutated:
                _save_session(context, conversation_key=payload.conversation_key, session=session)
            return ManagementResult(
                request_id=request.request_id,
                agent_id=request.agent_id,
                success=True,
                payload=SetConversationSettingResult(
                    result=conversation_setting_mutation_record(payload.setting, outcome),
                    state=_conversation_settings_state(
                        context,
                        conversation_id=payload.conversation_id,
                        conversation_key=payload.conversation_key,
                        session=session,
                    ),
                ),
            )
        if isinstance(payload, ResetConversationRequest):
            session = _session_for_request(context, conversation_key=payload.conversation_key)
            outcome = context.workflows.conversation.control.reset_session(
                session,
                actor_key=payload.actor_key,
                provider_name=context.config.provider_name,
                provider_state_factory=context.provider_state_factory,
                approval_mode_default=context.config.approval_mode,
                default_role=context.config.role,
                default_skills=context.config.default_skills,
                conversation_key=payload.conversation_key,
            )
            next_session = outcome.replacement_session or session
            if outcome.replacement_session is not None:
                _save_session(context, conversation_key=payload.conversation_key, session=outcome.replacement_session)
            return ManagementResult(
                request_id=request.request_id,
                agent_id=request.agent_id,
                success=True,
                payload=ResetConversationResult(
                    result=conversation_reset_outcome_record(outcome),
                    state=_conversation_settings_state(
                        context,
                        conversation_id=payload.conversation_id,
                        conversation_key=payload.conversation_key,
                        session=next_session,
                    ),
                ),
            )
        if isinstance(payload, ResetExecutionFaultRequest):
            if context.execution_faults is None:
                return ManagementResult(
                    request_id=request.request_id,
                    agent_id=request.agent_id,
                    success=False,
                    error_code="capability_not_available",
                    error_detail="Execution reset is not available on this bot.",
                )
            return ManagementResult(
                request_id=request.request_id,
                agent_id=request.agent_id,
                success=True,
                payload=ResetExecutionFaultResult(
                    state=context.execution_faults.clear(),
                ),
            )
        if isinstance(payload, PreviewProviderGuidanceRequest):
            preview = context.workflows.provider_guidance.preview.preview(
                payload.provider_name,
                role=payload.role,
                active_skills=list(payload.active_skills),
                compact_mode=payload.compact_mode,
            )
            return ManagementResult(
                request_id=request.request_id,
                agent_id=request.agent_id,
                success=True,
                payload=PreviewProviderGuidanceResult(
                    preview=provider_guidance_preview_record(preview)
                ),
            )
        if isinstance(payload, ProviderGuidanceDetailRequest):
            detail = context.workflows.provider_guidance.management.detail(
                payload.provider_name,
                scope_kind=payload.scope_kind,
                scope_key=payload.scope_key,
            )
            return ManagementResult(
                request_id=request.request_id,
                agent_id=request.agent_id,
                success=True,
                payload=ProviderGuidanceDetailResult(
                    detail=(
                        provider_guidance_lifecycle_detail_record(detail)
                        if detail is not None
                        else None
                    )
                ),
            )
        if isinstance(payload, EditProviderGuidanceDraftRequest):
            mutation = context.workflows.provider_guidance.management.edit_draft(
                payload.provider_name,
                actor_key=payload.actor_key,
                body=payload.body,
                scope_kind=payload.scope_kind,
                scope_key=payload.scope_key,
            )
            return ManagementResult(
                request_id=request.request_id,
                agent_id=request.agent_id,
                success=True,
                payload=EditProviderGuidanceDraftResult(
                    result=provider_guidance_lifecycle_mutation_record(mutation)
                ),
            )
        if isinstance(payload, SubmitProviderGuidanceRequest):
            mutation = context.workflows.provider_guidance.management.submit(
                payload.provider_name,
                actor_key=payload.actor_key,
                note=payload.note,
                scope_kind=payload.scope_kind,
                scope_key=payload.scope_key,
            )
            return ManagementResult(
                request_id=request.request_id,
                agent_id=request.agent_id,
                success=True,
                payload=SubmitProviderGuidanceResult(
                    result=provider_guidance_lifecycle_mutation_record(mutation)
                ),
            )
        if isinstance(payload, ApproveProviderGuidanceRequest):
            mutation = context.workflows.provider_guidance.management.approve(
                payload.provider_name,
                actor_key=payload.actor_key,
                note=payload.note,
                scope_kind=payload.scope_kind,
                scope_key=payload.scope_key,
            )
            return ManagementResult(
                request_id=request.request_id,
                agent_id=request.agent_id,
                success=True,
                payload=ApproveProviderGuidanceResult(
                    result=provider_guidance_lifecycle_mutation_record(mutation)
                ),
            )
        if isinstance(payload, RejectProviderGuidanceRequest):
            mutation = context.workflows.provider_guidance.management.reject(
                payload.provider_name,
                actor_key=payload.actor_key,
                note=payload.note,
                scope_kind=payload.scope_kind,
                scope_key=payload.scope_key,
            )
            return ManagementResult(
                request_id=request.request_id,
                agent_id=request.agent_id,
                success=True,
                payload=RejectProviderGuidanceResult(
                    result=provider_guidance_lifecycle_mutation_record(mutation)
                ),
            )
        if isinstance(payload, PublishProviderGuidanceRequest):
            mutation = context.workflows.provider_guidance.management.publish(
                payload.provider_name,
                actor_key=payload.actor_key,
                note=payload.note,
                scope_kind=payload.scope_kind,
                scope_key=payload.scope_key,
            )
            return ManagementResult(
                request_id=request.request_id,
                agent_id=request.agent_id,
                success=True,
                payload=PublishProviderGuidanceResult(
                    result=provider_guidance_lifecycle_mutation_record(mutation)
                ),
            )
        if isinstance(payload, ArchiveProviderGuidanceRequest):
            mutation = context.workflows.provider_guidance.management.archive(
                payload.provider_name,
                actor_key=payload.actor_key,
                note=payload.note,
                scope_kind=payload.scope_kind,
                scope_key=payload.scope_key,
            )
            return ManagementResult(
                request_id=request.request_id,
                agent_id=request.agent_id,
                success=True,
                payload=ArchiveProviderGuidanceResult(
                    result=provider_guidance_lifecycle_mutation_record(mutation)
                ),
            )
        return ManagementResult(
            request_id=request.request_id,
            agent_id=request.agent_id,
            success=False,
            error_code="request_invalid",
            error_detail=f"Unsupported management operation: {request.operation}",
        )
    except Exception as exc:
        return ManagementResult(
            request_id=request.request_id,
            agent_id=request.agent_id,
            success=False,
            error_code="request_failed",
            error_detail=str(exc),
        )
