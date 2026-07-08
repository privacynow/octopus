"""Unified bot runtime support contracts and provider dispatch plumbing."""

from __future__ import annotations

import asyncio
import html
import json
import logging
import re
import signal
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Awaitable
from typing import Callable
from typing import MutableMapping
from typing import MutableSet
from typing import Protocol
from typing import runtime_checkable
from uuid import uuid4

from octopus_sdk.agent_directory import AgentDirectoryPort
from octopus_sdk.agent_awareness import AgentAwarenessPort
from octopus_sdk.authorization import AuthorizationPort, TrustTierResolverPort
from octopus_sdk.config import BotConfigBase
from octopus_sdk.conversation_projection import ConversationProjectionPort
from octopus_sdk.deferred_notifications import DeferredNotificationPort
from octopus_sdk.execution_context import ResolvedExecutionContext
from octopus_sdk.formatting import TextFormattingPort, summarize_text
from octopus_sdk.health_publication import HealthPublicationPort
from octopus_sdk.identity import event_id_for_conversation_key, resolve_event_conversation_ref
from octopus_sdk.inbound_types import InboundAction
from octopus_sdk.inbound_types import InboundAttachment
from octopus_sdk.inbound_types import InboundCallback
from octopus_sdk.inbound_types import InboundCommand
from octopus_sdk.inbound_types import InboundEnvelope, InboundMessage, InboundUser, deserialize_inbound, serialize_inbound
from octopus_sdk.messages import MessageTemplatePort
from octopus_sdk.protocols.auto_design import ProtocolAutoDesignModelRequestRecord, ProtocolAutoDesignModelResponseRecord
from octopus_sdk.providers import CredentialEnvRecord, PreflightContext, ProgressSink, Provider, ProviderStateRecord, RunContext
from octopus_sdk.registry_participant import RegistryParticipantImplementation
from octopus_sdk.registry_inspection import RegistryInspectionPort
from octopus_sdk.runtime.skills import (
    SkillInspectionPort,
)
from octopus_sdk.registry.models import (
    DiscoveredAgentRef,
    ExecutionStateRecord,
    RoutedTaskResult,
    RoutedTaskUpdate,
    extract_leading_requested_skills,
    extract_target_selector_message,
)
from octopus_sdk.sessions import SessionState
from octopus_sdk.transport import InboundSubmissionResult
from octopus_sdk.transport import EditableHandle
from octopus_sdk.transport import DelegationContinuationRequest
from octopus_sdk.transport import DelegationContinuationResult
from octopus_sdk.transport import TransportDescriptor
from octopus_sdk.transport import TransportEgress
from octopus_sdk.transport import TransportImplementation
from octopus_sdk.webhooks import CompletionWebhookPort
from octopus_sdk.work_queue import LeaveClaimed, PendingRecovery, TransportStateCorruption, WorkItemRecord, WorkQueuePort, WorkerHeartbeat
from octopus_sdk.task_routing import TaskRoutingPort
from octopus_sdk.workflows.conversation import ConversationControlPort, ConversationSettingsPort
from octopus_sdk.workflows.credentials import CredentialManagementPort
from octopus_sdk.workflows.pending import PendingRequestPort
from octopus_sdk.workflows.provider_guidance import (
    ProviderGuidanceManagementPort as WorkflowProviderGuidanceManagementPort,
    ProviderGuidancePort as WorkflowProviderGuidancePort,
)
from octopus_sdk.workflows.recovery import RecoveryPort
from octopus_sdk.workflows.skills import (
    RuntimeSkillActivationPort as WorkflowRuntimeSkillActivationPort,
    RuntimeSkillApprovalPort,
    RuntimeSkillAuthoringPort,
    RuntimeSkillCatalogPort,
    RuntimeSkillImportPort,
    RuntimeSkillSetupPort as WorkflowRuntimeSkillSetupPort,
)

_HTML_TAG_RE = re.compile(r"<[^>]+>")
log = logging.getLogger(__name__)


@runtime_checkable
class ProviderGuidancePort(Protocol):
    def system_prompt(
        self,
        role: str,
        active_skills: list[str],
        *,
        provider_name: str = "",
        instance_key: str = "",
        guidance_override: str = "",
        available_agents: list[DiscoveredAgentRef] | None = None,
    ) -> str: ...

    def published_guidance_text(
        self,
        provider_name: str,
        *,
        instance_key: str = "",
    ) -> str: ...

    def draft_guidance_text(
        self,
        provider_name: str,
        *,
        scope_kind: str = "system",
        scope_key: str = "",
    ) -> str: ...

    def provider_config(
        self,
        provider_name: str,
        active_skills: list[str],
        credential_env: CredentialEnvRecord | None = None,
    ): ...

    def check_prompt_size_cross_chat(
        self,
        data_dir: Path,
        skill_name: str,
        provider_name: str,
        provider_state_factory,
        approval_mode: str,
    ) -> list[str]: ...

    def prompt_weight(
        self,
        role: str,
        active_skills: list[str],
        available_agents: list[DiscoveredAgentRef] | None = None,
    ) -> int: ...

    def active_skill_tools_summary(self, provider_name: str, active_skills: list[str]) -> str: ...

    def estimate_prompt_size(
        self,
        role: str,
        current_skills: list[str],
        new_skill: str,
    ) -> tuple[int, bool]: ...

    def build_run_context(
        self,
        role: str,
        active_skills: list[str],
        extra_dirs: list[str],
        *,
        provider_name: str,
        credential_env: CredentialEnvRecord | None = None,
        working_dir: str = "",
        file_policy: str = "",
        effective_model: str = "",
        guidance_override: str = "",
        available_agents: list[DiscoveredAgentRef] | None = None,
    ) -> RunContext: ...

    def build_preflight_context(
        self,
        role: str,
        active_skills: list[str],
        extra_dirs: list[str],
        *,
        provider_name: str,
        working_dir: str = "",
        file_policy: str = "",
        effective_model: str = "",
        guidance_override: str = "",
    ) -> PreflightContext: ...

    def apply_compact_mode(
        self,
        system_prompt: str,
        compact: bool,
    ) -> str: ...

    def stage_codex_scripts(
        self,
        data_dir: Path,
        conversation_key: str,
        active_skills: list[str],
    ) -> Path | None: ...

    def cleanup_codex_scripts(
        self,
        data_dir: Path,
        conversation_key: str,
    ) -> None: ...


@runtime_checkable
class SkillActivationPort(Protocol):
    def normalize(self, session: SessionState) -> list[str]: ...
    def list_active(self, session: SessionState) -> list[str]: ...
    def activate(self, session: SessionState, skill_name: str) -> bool: ...
    def deactivate(self, session: SessionState, skill_name: str) -> bool: ...
    def clear(self, session: SessionState) -> None: ...


@runtime_checkable
class SessionRuntimePort(Protocol):
    def load(
        self,
        conversation_key: str,
        *,
        provider_name: str,
        provider_state_factory,
        approval_mode: str,
        default_role: str = "",
        default_skills: tuple[str, ...] = (),
    ) -> SessionState: ...

    def save(
        self,
        conversation_key: str,
        session: SessionState,
    ) -> None: ...

    def list_incomplete_sessions(self) -> list[str]: ...

    def recover_after_crash(
        self,
        conversation_key: str,
        *,
        provider_name: str,
        provider_state_factory,
        approval_mode: str,
        default_role: str = "",
        default_skills: tuple[str, ...] = (),
    ) -> SessionState | None: ...

    def resolve_context(
        self,
        session: SessionState,
        *,
        config: BotConfigBase,
        provider_name: str,
        trust_tier: str = "trusted",
    ) -> ResolvedExecutionContext: ...


@runtime_checkable
class ArtifactStorePort(Protocol):
    def upload_dir(
        self,
        conversation_key: str,
    ) -> Path: ...

    def save_raw(
        self,
        conversation_key: str,
        prompt: str,
        raw_text: str,
        *,
        kind: str = "request",
    ) -> int: ...


@runtime_checkable
class ExecutionFaultStatePort(Protocol):
    def load(self) -> ExecutionStateRecord: ...

    def clear(self) -> ExecutionStateRecord: ...

    def record_provider_failure(
        self,
        *,
        provider_name: str,
        error_text: str,
        returncode: int,
    ) -> ExecutionStateRecord | None: ...


@runtime_checkable
class RuntimeCapabilityExchangePort(Protocol):
    async def exchange_runtime_capability(
        self,
        *,
        authority_ref: str,
        capability_ref: str,
    ) -> str: ...


@runtime_checkable
class AutoDesignPlannerPort(Protocol):
    async def design_auto_protocol(
        self,
        request: ProtocolAutoDesignModelRequestRecord,
        *,
        progress: ProgressSink,
        cancel: asyncio.Event | None = None,
    ) -> ProtocolAutoDesignModelResponseRecord: ...


@runtime_checkable
class ControlPlanePort(Protocol):
    conversation_projection: ConversationProjectionPort
    task_routing: TaskRoutingPort
    agent_directory: AgentDirectoryPort
    registry_inspection: RegistryInspectionPort
    health_publication: HealthPublicationPort


@dataclass(frozen=True)
class ExecutionServices:
    guidance: ProviderGuidancePort
    skill_activation: SkillActivationPort
    runtime_skill_setup: WorkflowRuntimeSkillSetupPort
    sessions: SessionRuntimePort
    artifacts: ArtifactStorePort
    skill_inspection: SkillInspectionPort | None = None
    execution_faults: ExecutionFaultStatePort | None = None
    agent_directory: AgentDirectoryPort | None = None
    conversation_projection: ConversationProjectionPort | None = None
    agent_awareness: AgentAwarenessPort | None = None
    runtime_capabilities: RuntimeCapabilityExchangePort | None = None


@dataclass(frozen=True)
class RuntimeSkillWorkflows:
    catalog: RuntimeSkillCatalogPort
    activation: WorkflowRuntimeSkillActivationPort
    imports: RuntimeSkillImportPort
    setup: WorkflowRuntimeSkillSetupPort
    authoring: RuntimeSkillAuthoringPort
    approval: RuntimeSkillApprovalPort


@dataclass(frozen=True)
class CredentialWorkflows:
    management: CredentialManagementPort


@dataclass(frozen=True)
class ConversationWorkflows:
    control: ConversationControlPort
    settings: ConversationSettingsPort


@dataclass(frozen=True)
class PendingWorkflows:
    requests: PendingRequestPort


@dataclass(frozen=True)
class RecoveryWorkflows:
    replay: RecoveryPort


@dataclass(frozen=True)
class ProviderGuidanceWorkflows:
    preview: WorkflowProviderGuidancePort
    management: WorkflowProviderGuidanceManagementPort


@dataclass(frozen=True)
class WorkflowComposition:
    runtime_skills: RuntimeSkillWorkflows
    credentials: CredentialWorkflows
    conversation: ConversationWorkflows
    pending: PendingWorkflows
    recovery: RecoveryWorkflows
    provider_guidance: ProviderGuidanceWorkflows
    messages: MessageTemplatePort
    config: BotConfigBase
    sessions: SessionRuntimePort
    deferred_notifications: DeferredNotificationPort
    supported_admin_operations: tuple[str, ...] = ()
    text_formatting: TextFormattingPort | None = None
    completion_webhook: CompletionWebhookPort | None = None
    trust_tier_resolver: TrustTierResolverPort | None = None
    test_only: bool = False


@runtime_checkable
class BotServicesPort(Protocol):
    control_plane: ControlPlanePort
    registry: RegistryParticipantImplementation
    workflows: WorkflowComposition
    authorization: AuthorizationPort
    work_queue: WorkQueuePort


class ProviderProgress:
    """Transport-neutral progress message updater."""

    def __init__(
        self,
        status_message: EditableHandle,
        config: BotConfigBase,
        *,
        timeline_callback: Callable[[str, bool], Awaitable[None]] | None = None,
    ) -> None:
        self._status_message = status_message
        self._timeline_callback = timeline_callback
        self._interval = config.stream_update_interval_seconds
        self._last_text = ""
        self._last_update = 0.0
        self._content_delivered = False
        self.content_started: asyncio.Event | None = None

    async def update(self, html_text: str, *, force: bool = False) -> None:
        now = asyncio.get_running_loop().time()
        if not html_text or html_text == self._last_text:
            return
        if (
            not force
            and self._last_update
            and now - self._last_update < self._interval
        ):
            return
        content_started = self.content_started
        if (
            not force
            and not self._content_delivered
            and content_started is not None
            and content_started.is_set()
        ):
            force = True
        try:
            await self._status_message.edit_text(
                html_text,
                parse_mode="HTML",
            )
        except Exception:
            return
        self._last_text = html_text
        self._last_update = now
        if content_started is not None and content_started.is_set():
            self._content_delivered = True
        if self._timeline_callback is not None:
            try:
                await self._timeline_callback(html_text, force=force)
            except Exception:
                return


@dataclass
class BotRuntime:
    """SDK-owned runtime composition and durable admission entrypoint."""

    config: BotConfigBase
    transport: TransportImplementation
    registry: RegistryParticipantImplementation
    provider: Provider
    sessions: SessionRuntimePort
    workflows: WorkflowComposition
    authorization: AuthorizationPort
    work_queue: WorkQueuePort
    control_plane: ControlPlanePort | None = None
    execution_services: ExecutionServices | None = None
    boot_id: str = ""
    allow_test_mode: bool = False
    cancellations: MutableMapping[str, asyncio.Event] = field(default_factory=dict)
    execution_inflight: MutableSet[str] = field(default_factory=set)
    auto_design_planner: AutoDesignPlannerPort | None = None

    async def submit(
        self,
        envelope: InboundEnvelope,
        *,
        worker_id: str | None = None,
    ) -> InboundSubmissionResult:
        payload = serialize_inbound(envelope.event, transport=envelope.transport)
        if envelope.kind == "message":
            status, item_id = self.work_queue.record_and_admit_message(
                self.config.data_dir,
                envelope.event_id,
                envelope.conversation_key,
                envelope.actor_key,
                envelope.kind,
                payload=payload,
            )
            return InboundSubmissionResult(status=status, item_id=item_id)

        is_new, item_id = self.work_queue.record_and_enqueue(
            self.config.data_dir,
            envelope.event_id,
            envelope.conversation_key,
            envelope.actor_key,
            envelope.kind,
            payload=payload,
            worker_id=worker_id,
        )
        return InboundSubmissionResult(
            status="queued" if is_new else "duplicate",
            item_id=item_id,
        )

    async def admit_message(self, envelope: InboundEnvelope) -> InboundSubmissionResult:
        return await self.submit(envelope)

    async def enqueue(
        self,
        envelope: InboundEnvelope,
        *,
        worker_id: str | None = None,
    ) -> InboundSubmissionResult:
        return await self.submit(envelope, worker_id=worker_id)

    async def record(self, envelope: InboundEnvelope) -> bool:
        payload = serialize_inbound(envelope.event, transport=envelope.transport)
        return self.work_queue.record_update(
            self.config.data_dir,
            envelope.event_id,
            envelope.conversation_key,
            envelope.actor_key,
            envelope.kind,
            payload=payload,
        )

    async def continue_delegation(
        self,
        request: DelegationContinuationRequest,
    ) -> DelegationContinuationResult:
        from octopus_sdk.workflows.delegation import (
            apply_routed_result,
            build_resume_prompt,
            delegation_ready_to_resume,
        )
        from octopus_sdk.workflows.execution_finalization import (
            FinalizationContext,
            finalize_execution,
        )

        session = self._load_session(request.parent_conversation_key)
        pending = session.pending_delegation
        was_ready_to_resume = delegation_ready_to_resume(pending)
        applied = apply_routed_result(
            pending,
            routed_task_id=request.routed_task_id,
            authority_ref=request.authority_ref,
            result=request.result,
        )
        updated_pending = applied.pending
        matched = applied.matched
        ready_to_resume = applied.ready_to_resume
        resume_prompt = applied.resume_prompt
        completion_message = applied.completion_message
        newly_ready = applied.matched and applied.ready_to_resume and not was_ready_to_resume

        if not matched and pending is not None:
            matching_task = next(
                (
                    task
                    for task in pending.tasks
                    if task.routed_task_id == request.routed_task_id
                    and (
                        not request.authority_ref
                        or not task.authority_ref
                        or task.authority_ref == request.authority_ref
                    )
                ),
                None,
            )
            if matching_task is not None and delegation_ready_to_resume(pending):
                matched = True
                updated_pending = pending
                ready_to_resume = True
                resume_prompt = build_resume_prompt(pending)
                completion_message = ""
                newly_ready = False

        if not matched:
            return DelegationContinuationResult(status="not_matched", matched=False, resumed=False)

        session.pending_delegation = updated_pending
        self.sessions.save(request.parent_conversation_key, session)

        if updated_pending is None or not ready_to_resume:
            return DelegationContinuationResult(status="updated", matched=True, resumed=False)

        actor_key = str(updated_pending.actor_key or "")
        actor_user = InboundUser(id=actor_key or "internal:delegation")
        descriptor = self._descriptor_for_ref(request.parent_transport_ref)
        resume_transport = (
            descriptor.transport_type
            if descriptor is not None
            else str(request.parent_transport_ref or "").split(":", 1)[0] or "registry"
        )
        event = InboundMessage(
            user=actor_user,
            conversation_key=request.parent_conversation_key,
            text=resume_prompt,
            attachments=(),
            source=resume_transport,
            transport=resume_transport,
            conversation_ref=request.parent_transport_ref,
            external_conversation_ref=(
                request.parent_external_conversation_ref or request.parent_transport_ref
            ),
            authority_ref=request.authority_ref,
            authorized_actor_key=actor_key,
            skip_approval=True,
            admission_class="internal",
        )
        item = WorkItemRecord(
            id=f"delegation:{request.routed_task_id}",
            conversation_key=request.parent_conversation_key,
            actor_key=actor_key,
            kind="message",
        )
        egress, conversation_ref = self._build_worker_egress(event, item)
        title = summarize_text(updated_pending.title or resume_prompt) or "Delegation follow-up"
        await egress.bind(title=title, config=self.config)
        if newly_ready and completion_message:
            await egress.send_text(completion_message)
        trust_tier = self._trust_tier_for_event(
            conversation_ref,
            actor_key=actor_key,
            user=actor_user,
        )
        outcome = await self._execute_message_request(
            event=event,
            item=item,
            egress=egress,
            conversation_ref=conversation_ref,
            trust_tier=trust_tier,
            cancel_event=None,
            skip_approval=True,
            prompt=resume_prompt,
            image_paths=[],
            attachments=[],
        )
        await finalize_execution(
            outcome,
            context=FinalizationContext(
                config=self.config,
                item_id=item.id,
                conversation_key=request.parent_conversation_key,
                runtime_chat=request.parent_conversation_key,
                conversation_ref=updated_pending.conversation_ref,
                chat_id=event.chat_id if isinstance(event.chat_id, int) else 0,
                skip_approval=True,
                load_session=self._load_session,
                save_session=self.sessions.save,
                record_usage=self.work_queue.record_usage,
                completion_webhook_sender=self.workflows.completion_webhook,
                registry_inspection=self.control_plane.registry_inspection if self.control_plane is not None else None,
                working_dir_resolver=self._resolved_working_dir,
            ),
        )
        return DelegationContinuationResult(status="continued", matched=True, resumed=True)

    async def dispatch_claimed_item(
        self,
        kind: str,
        event: InboundMessage | InboundCommand | InboundCallback | InboundAction,
        item: WorkItemRecord,
    ) -> None:
        await self._dispatch_claimed_item(kind, event, item)

    async def run(self) -> None:
        if self.workflows.test_only and not self.allow_test_mode:
            raise RuntimeError(
                "BotRuntime refuses to start with a test-only workflow composition. "
                "Use WorkflowComposer.build() with durable implementations, or set "
                "allow_test_mode=True explicitly for SDK verification only."
            )
        stop_event = asyncio.Event()
        worker_task: asyncio.Task[None] | None = None
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop_event.set)
            except NotImplementedError:
                continue

        try:
            await self.transport.start(runtime=self, stop_event=stop_event)
            if self._runs_worker():
                self.work_queue.recover_after_crash(
                    self.config.data_dir,
                    lease_ttl_seconds=self.config.claim_lease_ttl_seconds,
                )
                worker_task = asyncio.create_task(
                    self._run_worker_loop(stop_event),
                    name="bot-runtime-worker",
                )
            await stop_event.wait()
        finally:
            stop_event.set()
            worker_failure: BaseException | None = None
            if worker_task is not None:
                try:
                    await asyncio.wait_for(worker_task, timeout=5.0)
                except asyncio.TimeoutError:
                    worker_task.cancel()
                    results = await asyncio.gather(worker_task, return_exceptions=True)
                    if results and isinstance(results[0], BaseException) and not isinstance(results[0], asyncio.CancelledError):
                        worker_failure = results[0]
                except BaseException as exc:
                    worker_failure = exc
            transport_failure: BaseException | None = None
            try:
                await self.transport.stop()
            except BaseException as exc:
                transport_failure = exc
            if worker_failure is not None:
                raise worker_failure
            if transport_failure is not None:
                raise transport_failure

    def _runs_worker(self) -> bool:
        return self.config.process_role in {"all", "worker"}

    def _worker_poll_interval(self) -> float:
        return 0.5 if self.config.runtime_mode == "shared" else 1.0

    def _worker_id(self) -> str:
        return self.boot_id or self.config.instance

    def _load_session(self, conversation_key: str) -> SessionState:
        session = self.sessions.load(
            conversation_key,
            provider_name=self.provider.name,
            provider_state_factory=self.provider.new_provider_state,
            approval_mode=self.config.approval_mode,
            default_role=self.config.role,
            default_skills=self.config.default_skills,
        )
        return session

    def _require_execution_services(self) -> ExecutionServices:
        if self.execution_services is None:
            raise RuntimeError("BotRuntime requires execution_services for worker dispatch")
        return self.execution_services

    def _execution_runtime(self):
        from octopus_sdk.execution import ExecutionRuntime
        from octopus_sdk.work_queue import LeaveClaimed

        services = self._require_execution_services()
        execution_services = ExecutionServices(
            guidance=services.guidance,
            skill_activation=services.skill_activation,
            runtime_skill_setup=self.workflows.runtime_skills.setup,
            sessions=self.sessions,
            artifacts=services.artifacts,
            skill_inspection=services.skill_inspection,
            execution_faults=services.execution_faults,
            agent_directory=services.agent_directory,
            conversation_projection=services.conversation_projection,
            agent_awareness=services.agent_awareness,
        )
        return ExecutionRuntime(
            dispatch=ProviderDispatchRuntime(
                config=self.config,
                provider=self.provider,
                boot_id=self.boot_id,
                cancellations=self.cancellations,
                execution_inflight=self.execution_inflight,
            ),
            services=execution_services,
            interrupted_exc=LeaveClaimed,
        )

    def _descriptor_for_ref(self, conversation_ref: str) -> TransportDescriptor | None:
        try:
            return self.transport.descriptor_for_ref(conversation_ref)
        except Exception:
            return None

    def _trust_tier_for_event(
        self,
        conversation_ref: str,
        *,
        actor_key: str,
        user: InboundUser | None,
    ) -> str:
        descriptor = self._descriptor_for_ref(conversation_ref)
        if descriptor is not None and descriptor.trust_tier == "trusted":
            return descriptor.trust_tier
        resolver = self.workflows.trust_tier_resolver
        if resolver is not None:
            return resolver(
                conversation_ref,
                user,
                config=self.config,
                dispatcher=self.transport if hasattr(self.transport, "descriptor_for_ref") else None,
            )
        return self.authorization.trust_tier(self.config, user)

    def _target_agent_id_for_authority(self, authority_ref: str) -> str:
        if not authority_ref:
            return ""
        try:
            current = self.registry.health.current_local_agent_ids().get(authority_ref, "")
            if current:
                return current
        except Exception:
            pass
        try:
            return self.registry.health.live_local_agent_ids().get(authority_ref, "")
        except Exception:
            return ""

    def _local_agent_ids(self) -> tuple[str, ...]:
        agent_ids: list[str] = []
        try:
            current = self.registry.health.current_local_agent_ids()
        except Exception:
            current = {}
        try:
            live = self.registry.health.live_local_agent_ids()
        except Exception:
            live = {}
        for value in tuple(current.values()) + tuple(live.values()):
            agent_id = str(value or "")
            if agent_id and agent_id not in agent_ids:
                agent_ids.append(agent_id)
        return tuple(agent_ids)

    async def _flush_deferred_notifications(
        self,
        *,
        actor_key: str,
        egress: TransportEgress,
    ) -> None:
        store = self.workflows.deferred_notifications
        if not actor_key:
            return
        store.expire_stale(self.config.data_dir)
        for target_agent_id in self._local_agent_ids():
            notifications = store.flush(
                self.config.data_dir,
                target_agent_id=target_agent_id,
                actor_key=actor_key,
            )
            for notification in notifications:
                text = str(notification.content or "").strip()
                if text:
                    await egress.send_text(text)

    async def _noop_timeline_callback(self, html_text: str, *, force: bool = False) -> None:
        del html_text, force

    async def _routed_task_timeline_callback(
        self,
        routed_task_id: str,
        authority_ref: str,
        html_text: str,
        *,
        force: bool = False,
    ) -> None:
        del force
        if self.control_plane is None or not routed_task_id or not authority_ref:
            return
        summary = summarize_text(html.unescape(_HTML_TAG_RE.sub(" ", html_text or "")), limit=200)
        if not summary:
            return
        await self.control_plane.task_routing.update_routed_task_status(
            update=RoutedTaskUpdate(
                routed_task_id=routed_task_id,
                status="running",
                transition_id=uuid4().hex,
                summary=summary,
            ),
            authority_ref=authority_ref,
        )

    async def _report_interrupted_routed_task_recovery(
        self,
        *,
        routed_task_id: str,
        authority_ref: str,
        event: InboundMessage,
        item: WorkItemRecord,
    ) -> None:
        if self.control_plane is None or not routed_task_id or not authority_ref:
            return
        summary = "Work was interrupted; retry this stage to continue."
        full_text = (
            "This routed task was interrupted after the worker restarted before "
            "the provider result was durably reported. The runtime recovered the "
            "stuck task and marked the stage as blocked so an operator can retry "
            "the same stage without hunting through logs. Check any partial local "
            "files if needed, then use Retry to continue from this stage."
        )
        await self.control_plane.task_routing.report_routed_task_result(
            routed_task_id=routed_task_id,
            authority_ref=authority_ref,
            result=RoutedTaskResult(
                routed_task_id=routed_task_id,
                status="interrupted",
                transition_id=uuid4().hex,
                summary=summary,
                full_text=full_text,
                artifacts=[],
                follow_up_questions=(),
                provider=self.provider.name,
                working_dir=str(event.working_dir_hint or ""),
            ),
        )

    def _auto_design_context(self, event: InboundMessage) -> dict[str, object]:
        if not str(getattr(event, "routed_task_id", "") or "").strip():
            return {}
        try:
            context = json.loads(str(getattr(event, "context_text", "") or "{}"))
        except Exception:
            return {}
        if not isinstance(context, dict):
            return {}
        if str(context.get("task_source_kind") or context.get("source_kind") or "") != "auto_design":
            return {}
        auto_design = context.get("auto_design", {})
        return auto_design if isinstance(auto_design, dict) else {}

    async def _dispatch_auto_design_routed_task(
        self,
        event: InboundMessage,
        item: WorkItemRecord,
        *,
        cancel_event: asyncio.Event | None,
    ) -> bool:
        auto_design = self._auto_design_context(event)
        if not auto_design:
            return False
        routed_task_id = str(getattr(event, "routed_task_id", "") or "")
        authority_ref = str(getattr(event, "authority_ref", "") or "")
        if self.control_plane is None or not routed_task_id or not authority_ref:
            raise RuntimeError("Auto Protocol planner task requires registry task routing.")

        async def update_status(summary: str, *, progress: int | None = None, force: bool = False) -> None:
            del force
            await self.control_plane.task_routing.update_routed_task_status(
                update=RoutedTaskUpdate(
                    routed_task_id=routed_task_id,
                    status="running",
                    transition_id=uuid4().hex,
                    summary=summarize_text(summary, limit=220) or "Auto Protocol planner is running.",
                    progress=progress,
                ),
                authority_ref=authority_ref,
            )

        class _TaskProgress:
            def __init__(self) -> None:
                self._last_update = 0.0
                self._progress = 1

            async def update(self, html_text: str, *, force: bool = False) -> None:
                now = asyncio.get_running_loop().time()
                if not force and self._last_update and now - self._last_update < 10.0:
                    return
                self._last_update = now
                self._progress = min(95, self._progress + 3)
                text = html.unescape(_HTML_TAG_RE.sub(" ", html_text or ""))
                await update_status(
                    text or "Auto Protocol planner is running.",
                    progress=self._progress,
                )

        await update_status("Auto Protocol planner started.", progress=1)
        try:
            if self.auto_design_planner is None:
                raise RuntimeError("Auto Protocol planner execution is not configured for this runtime.")
            request_payload = auto_design.get("request", {})
            request = ProtocolAutoDesignModelRequestRecord.model_validate(request_payload)
            response = await self.auto_design_planner.design_auto_protocol(
                request,
                progress=_TaskProgress(),
                cancel=cancel_event,
            )
            await self.control_plane.task_routing.report_routed_task_result(
                routed_task_id=routed_task_id,
                authority_ref=authority_ref,
                result=RoutedTaskResult(
                    routed_task_id=routed_task_id,
                    status="completed",
                    transition_id=uuid4().hex,
                    summary="Auto Protocol planner completed.",
                    full_text=response.model_dump_json(),
                    artifacts=[],
                    follow_up_questions=(),
                    provider=self.provider.name,
                    working_dir=str(getattr(self.config, "working_dir", "") or ""),
                ),
            )
            return True
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self.control_plane.task_routing.report_routed_task_result(
                routed_task_id=routed_task_id,
                authority_ref=authority_ref,
                result=RoutedTaskResult(
                    routed_task_id=routed_task_id,
                    status="failed",
                    transition_id=uuid4().hex,
                    summary="Auto Protocol planner failed.",
                    full_text=str(exc),
                    artifacts=[],
                    follow_up_questions=(),
                    provider=self.provider.name,
                    working_dir=str(getattr(self.config, "working_dir", "") or ""),
                ),
            )
            return True

    def _build_transport_identity(
        self,
        *,
        event: InboundMessage | InboundAction,
        conversation_ref: str,
        actor_key: str,
    ):
        from octopus_sdk.execution import ExecutionChannelMetadata, build_transport_identity_from_metadata

        authority_ref = str(getattr(event, "authority_ref", "") or "")
        routed_task_id = str(getattr(event, "routed_task_id", "") or "")
        stage_contract = getattr(event, "protocol_stage_contract", {}) or {}
        timeout_seconds = 0
        if isinstance(stage_contract, dict):
            try:
                timeout_seconds = max(0, int(stage_contract.get("timeout_seconds") or 0))
            except (TypeError, ValueError):
                timeout_seconds = 0
        return build_transport_identity_from_metadata(
            ExecutionChannelMetadata(
                conversation_key=str(getattr(event, "conversation_key", "") or ""),
                origin_channel=str(getattr(event, "source", "") or self.transport.descriptor.transport_type),
                actor=actor_key,
                descriptor=self._descriptor_for_ref(conversation_ref),
                message_conversation_ref=conversation_ref,
                routed_task_id=routed_task_id,
                authority_ref=authority_ref,
                external_conversation_ref=str(getattr(event, "external_conversation_ref", "") or ""),
                target_agent_id=self._target_agent_id_for_authority(authority_ref),
                runtime_capability_ref=str(getattr(event, "runtime_capability_ref", "") or ""),
                requested_skills=tuple(
                    str(skill).strip().lower()
                    for skill in getattr(event, "requested_skills", ())
                    if str(skill).strip()
                ),
                execution_timeout_seconds=timeout_seconds,
            ),
            conversation_callback_factory=lambda _conversation_ref, _routed_task_id: self._noop_timeline_callback,
            routed_task_callback_factory=lambda task_id, auth_ref: (
                lambda html_text, force=False: self._routed_task_timeline_callback(
                    task_id,
                    auth_ref,
                    html_text,
                    force=force,
                )
            ),
        )

    def _build_worker_prompt(
        self,
        text: str,
        attachments: list[InboundAttachment],
    ) -> tuple[str, list[str]]:
        prompt = text.strip() or "Inspect the attached files or images and help with them."
        image_paths: list[str] = []
        if not attachments:
            return prompt, image_paths
        lines = []
        for attachment in attachments:
            kind = "image" if attachment.is_image else "file"
            lines.append(f"- {attachment.path} ({kind}, original name: {attachment.original_name})")
            if attachment.is_image:
                image_paths.append(str(attachment.path))
        return f"{prompt}\n\nAttached local files:\n" + "\n".join(lines), image_paths

    def _target_message_id(self, event: InboundAction) -> int | None:
        raw = event.params.get("message_id")
        if isinstance(raw, int) and raw > 0:
            return raw
        if isinstance(raw, str) and raw.isdigit():
            return int(raw)
        return None

    def _build_worker_egress(
        self,
        event: InboundMessage | InboundAction,
        item: WorkItemRecord,
    ) -> tuple[TransportEgress, str]:
        conversation_ref = resolve_event_conversation_ref(config=self.config, event=event)
        kwargs: dict[str, object] = {
            "conversation_key": item.conversation_key,
            "source": str(getattr(event, "source", "") or self.transport.descriptor.transport_type),
            "authority_ref": str(getattr(event, "authority_ref", "") or ""),
            "routed_task_id": str(getattr(event, "routed_task_id", "") or ""),
            "external_id": str(
                getattr(event, "external_conversation_ref", "")
                or getattr(event, "conversation_key", "")
                or item.conversation_key
            ),
        }
        kwargs.update(self.transport.worker_egress_kwargs(conversation_ref=conversation_ref))
        if isinstance(event, InboundAction):
            target_message_id = self._target_message_id(event)
            if target_message_id is not None:
                kwargs["target_message_id"] = target_message_id
        return (
            self.transport.build_egress(
                conversation_ref=conversation_ref,
                config=self.config,
                **kwargs,
            ),
            conversation_ref,
        )

    def _admit_claimed_message(
        self,
        event: InboundMessage,
        item: WorkItemRecord,
        *,
        conversation_ref: str,
    ) -> tuple[bool, str]:
        if str(getattr(event, "admission_class", "external") or "external") == "internal":
            return True, "internal"
        actor_key = item.actor_key or str(getattr(event.user, "id", "") or "")
        trust_tier = self._trust_tier_for_event(
            conversation_ref,
            actor_key=actor_key,
            user=event.user,
        )
        descriptor = self._descriptor_for_ref(conversation_ref)
        if descriptor is not None and descriptor.trust_tier == "trusted":
            return True, trust_tier
        override = self.work_queue.get_user_access(self.config.data_dir, actor_key)
        if not self.authorization.is_allowed(self.config, event.user, override=override):
            self.work_queue.fail_work_item(self.config.data_dir, item.id, error="not_allowed")
            return False, trust_tier
        return True, trust_tier

    async def _execute_message_request(
        self,
        *,
        event: InboundMessage,
        item: WorkItemRecord,
        egress: TransportEgress,
        conversation_ref: str,
        trust_tier: str,
        cancel_event: asyncio.Event | None,
        skip_approval: bool = False,
        prompt: str | None = None,
        image_paths: list[str] | None = None,
        attachments: list[InboundAttachment] | None = None,
    ):
        from octopus_sdk.execution import dispatch_message_request, load_approval_mode

        execution_runtime = self._execution_runtime()
        worker_prompt, worker_images = self._build_worker_prompt(
            event.text,
            list(attachments if attachments is not None else event.attachments),
        )
        approval_mode = load_approval_mode(item.conversation_key, runtime=execution_runtime)
        return await dispatch_message_request(
            self._build_transport_identity(
                event=event,
                conversation_ref=conversation_ref,
                actor_key=item.actor_key or str(getattr(event.user, "id", "") or ""),
            ),
            prompt if prompt is not None else worker_prompt,
            image_paths if image_paths is not None else worker_images,
            list(attachments if attachments is not None else event.attachments),
            egress,
            approval_mode=approval_mode,
            routed_task_id=str(getattr(event, "routed_task_id", "") or ""),
            skip_approval=skip_approval or bool(getattr(event, "skip_approval", False)),
            trust_tier=trust_tier,
            cancel_event=cancel_event,
            runtime=execution_runtime,
        )

    def _resolved_working_dir(self, conversation_key: int | str) -> str:
        session = self._load_session(str(conversation_key))
        resolved = self.sessions.resolve_context(
            session,
            config=self.config,
            provider_name=self.provider.name,
            trust_tier="trusted",
        )
        return str(resolved.working_dir or "")

    def _save_session_if_mutated(self, conversation_key: str, session: SessionState, *, mutated: bool) -> None:
        if mutated:
            self.sessions.save(conversation_key, session)

    def _policy_for_actor(self, user: InboundUser | None, *, actor_key: str) -> str:
        override = self.work_queue.get_user_access(self.config.data_dir, actor_key)
        return self.authorization.access_policy(self.config, user, override=override)

    async def _dispatch_pending_action(
        self,
        event: InboundAction,
        item: WorkItemRecord,
        *,
        egress: TransportEgress,
        conversation_ref: str,
        cancel_event: asyncio.Event | None,
    ) -> bool:
        action = event.action
        if action not in {"approve_pending", "reject_pending", "retry_skip", "retry_allow", "recovery_replay", "recovery_discard"}:
            return False

        session = self._load_session(item.conversation_key)
        callback_token = str(event.params.get("callback_token") or "")

        def _matches(pending) -> bool:
            if not callback_token or pending is None:
                return True
            expected = str(getattr(pending, "callback_token", "") or "")
            return expected == callback_token

        if action == "approve_pending":
            if not _matches(session.pending_approval or session.pending_retry):
                await egress.send_text("This approval request is no longer valid.")
                return True
            outcome = self.workflows.pending.requests.approve(
                session,
                cfg=self.config,
                provider_name=self.provider.name,
            )
            self._save_session_if_mutated(item.conversation_key, session, mutated=outcome.mutated)
            if outcome.execution_plan is None:
                await egress.send_text(outcome.message)
                return True
            replay_event = InboundMessage(
                user=event.user,
                conversation_key=item.conversation_key,
                text=outcome.execution_plan.prompt,
                source=str(getattr(event, "source", "") or self.transport.descriptor.transport_type),
                attachments=tuple(),
                conversation_ref=conversation_ref,
                admission_class="internal",
            )
            await self._execute_message_request(
                event=replay_event,
                item=item,
                egress=egress,
                conversation_ref=conversation_ref,
                trust_tier=outcome.execution_plan.trust_tier,
                cancel_event=cancel_event,
                skip_approval=True,
                prompt=outcome.execution_plan.prompt,
                image_paths=list(outcome.execution_plan.image_paths),
                attachments=[],
            )
            return True

        if action == "reject_pending":
            if not _matches(session.pending_approval or session.pending_retry):
                await egress.send_text("This approval request is no longer valid.")
                return True
            outcome = self.workflows.pending.requests.reject(session)
            self._save_session_if_mutated(item.conversation_key, session, mutated=outcome.mutated)
            await egress.send_text(outcome.message)
            return True

        if action == "retry_skip":
            if not _matches(session.pending_retry):
                await egress.send_text("This approval request is no longer valid.")
                return True
            outcome = self.workflows.pending.requests.retry_skip(session)
            self._save_session_if_mutated(item.conversation_key, session, mutated=outcome.mutated)
            await egress.send_text(outcome.message)
            return True

        if action == "retry_allow":
            if not _matches(session.pending_retry):
                await egress.send_text("This approval request is no longer valid.")
                return True
            outcome = self.workflows.pending.requests.retry_allow(
                session,
                cfg=self.config,
                provider_name=self.provider.name,
            )
            self._save_session_if_mutated(item.conversation_key, session, mutated=outcome.mutated)
            if outcome.execution_plan is None:
                await egress.send_text(outcome.message)
                return True
            replay_event = InboundMessage(
                user=event.user,
                conversation_key=item.conversation_key,
                text=outcome.execution_plan.prompt,
                source=str(getattr(event, "source", "") or self.transport.descriptor.transport_type),
                attachments=tuple(),
                conversation_ref=conversation_ref,
                admission_class="internal",
            )
            await self._execute_message_request(
                event=replay_event,
                item=item,
                egress=egress,
                conversation_ref=conversation_ref,
                trust_tier=outcome.execution_plan.trust_tier,
                cancel_event=cancel_event,
                skip_approval=True,
                prompt=outcome.execution_plan.prompt,
                image_paths=list(outcome.execution_plan.image_paths),
                attachments=[],
            )
            return True

        if action == "recovery_replay":
            self.work_queue.complete_work_item(self.config.data_dir, item.id)

        recovery_event_id = event_id_for_conversation_key(
            item.conversation_key,
            str(event.params.get("recovery_id") or item.event_id),
        )

        outcome = self.workflows.recovery.replay.prepare_action(
            data_dir=self.config.data_dir,
            conversation_key=item.conversation_key,
            event_id=recovery_event_id,
            action=action,
            worker_id=self._worker_id(),
            ignore_claimed_item_id=item.id,
            config=self.config,
            dispatcher=self.transport,
        )
        if outcome.toast_message:
            await egress.answer_action(outcome.toast_message, show_alert=outcome.show_alert)
        if outcome.edit_message:
            await egress.send_text(outcome.edit_message)
        if outcome.replay_plan is None:
            return True
        replay_event = outcome.replay_plan.event
        replay_ref = resolve_event_conversation_ref(config=self.config, event=replay_event)
        prompt, image_paths = self._build_worker_prompt(
            replay_event.text,
            list(replay_event.attachments),
        )
        try:
            # Recovery replay resumes an already accepted request. It should run
            # directly instead of re-entering the approval gate.
            await self._execute_message_request(
                event=replay_event,
                item=item,
                egress=egress,
                conversation_ref=replay_ref,
                trust_tier=outcome.replay_plan.trust_tier,
                cancel_event=cancel_event,
                skip_approval=True,
            )
            self.workflows.recovery.replay.complete_replay(
                data_dir=self.config.data_dir,
                item_id=outcome.replay_plan.item_id,
            )
        except LeaveClaimed:
            raise
        except Exception:
            self.workflows.recovery.replay.fail_replay(
                data_dir=self.config.data_dir,
                item_id=outcome.replay_plan.item_id,
            )
            await egress.send_text("Recovery replay failed.")
        return True

    async def _dispatch_conversation_action(
        self,
        event: InboundAction,
        item: WorkItemRecord,
        *,
        egress: TransportEgress,
        conversation_ref: str,
    ) -> bool:
        action = event.action
        if action not in {
            "session_new",
            "cancel_conversation",
            "set_approval_mode",
            "set_compact_mode",
            "set_role",
            "set_model_profile",
            "set_project",
            "set_file_policy",
        }:
            return False

        actor_key = item.actor_key or str(getattr(event.user, "id", "") or "")
        policy = self._policy_for_actor(event.user, actor_key=actor_key)
        is_public = policy == "public"
        is_admin = self.authorization.is_admin(self.config, event.user)
        session = self._load_session(item.conversation_key)

        if action == "session_new":
            outcome = self.workflows.conversation.control.reset_session(
                session,
                actor_key=actor_key,
                provider_name=self.provider.name,
                provider_state_factory=self.provider.new_provider_state,
                approval_mode_default=self.config.approval_mode,
                default_role=self.config.role,
                default_skills=self.config.default_skills,
                projects=self.config.projects,
                conversation_key=item.conversation_key,
            )
            if outcome.replacement_session is not None:
                self.sessions.save(item.conversation_key, outcome.replacement_session)
            if outcome.cleanup_scripts:
                self._require_execution_services().guidance.cleanup_codex_scripts(
                    self.config.data_dir,
                    item.conversation_key,
                )
            await egress.send_text(outcome.message or "Started a fresh session.")
            return True

        if action == "cancel_conversation":
            outcome = self.workflows.conversation.control.cancel_conversation(
                session,
                data_dir=self.config.data_dir,
                conversation_key=item.conversation_key,
                actor_key=actor_key,
                live_cancel_event=self.cancellations.get(item.conversation_key),
                cancel_request_event_id=item.event_id,
                allow_override=is_admin,
            )
            self._save_session_if_mutated(item.conversation_key, session, mutated=outcome.mutated)
            await egress.send_text(outcome.message)
            return True

        if action == "set_approval_mode":
            outcome = self.workflows.conversation.settings.set_approval_mode(
                session,
                str(event.params.get("value", "")).lower(),
            )
            self._save_session_if_mutated(item.conversation_key, session, mutated=outcome.mutated)
            await egress.send_text(outcome.message)
            return True

        if action == "set_compact_mode":
            outcome = self.workflows.conversation.settings.set_compact_mode(
                session,
                bool(event.params.get("value", False)),
            )
            self._save_session_if_mutated(item.conversation_key, session, mutated=outcome.mutated)
            await egress.send_text(outcome.message)
            return True

        if action == "set_role":
            if is_public:
                await egress.send_text("Role changes are not available for public users.")
                return True
            outcome = self.workflows.conversation.settings.set_role(
                session,
                str(event.params.get("value", "")),
                default_role=self.config.role,
            )
            self._save_session_if_mutated(item.conversation_key, session, mutated=outcome.mutated)
            await egress.send_text(outcome.message)
            return True

        if action == "set_model_profile":
            outcome = self.workflows.conversation.settings.set_model_profile(
                session,
                str(event.params.get("profile", "")),
                cfg=self.config,
                provider_name=self.provider.name,
                trust_tier=self._trust_tier_for_event(
                    conversation_ref,
                    actor_key=actor_key,
                    user=event.user,
                ),
            )
            self._save_session_if_mutated(item.conversation_key, session, mutated=outcome.mutated)
            await egress.send_text(outcome.message)
            return True

        if action == "set_project":
            if is_public:
                await egress.send_text("Project selection is not available for public users.")
                return True
            if not self.config.projects:
                await egress.send_text("No projects are configured for this bot.")
                return True
            outcome = self.workflows.conversation.settings.set_project(
                session,
                str(event.params.get("value", "")),
                cfg=self.config,
                provider_state_factory=self.provider.new_provider_state,
                conversation_key=item.conversation_key,
            )
            self._save_session_if_mutated(item.conversation_key, session, mutated=outcome.mutated)
            await egress.send_text(outcome.message)
            return True

        if is_public:
            await egress.send_text("File policy changes are not available for public users.")
            return True
        outcome = self.workflows.conversation.settings.set_file_policy(
            session,
            str(event.params.get("value", "")),
            cfg=self.config,
            provider_name=self.provider.name,
            trust_tier=self._trust_tier_for_event(
                conversation_ref,
                actor_key=actor_key,
                user=event.user,
            ),
            provider_state_factory=self.provider.new_provider_state,
            conversation_key=item.conversation_key,
        )
        self._save_session_if_mutated(item.conversation_key, session, mutated=outcome.mutated)
        await egress.send_text(outcome.message)
        return True

    async def _dispatch_skill_action(
        self,
        event: InboundAction,
        item: WorkItemRecord,
        *,
        egress: TransportEgress,
    ) -> bool:
        action = event.action
        if action not in {"skills_add", "skills_remove", "skills_setup", "skills_clear"}:
            return False

        actor_key = item.actor_key or str(getattr(event.user, "id", "") or "")
        if self._policy_for_actor(event.user, actor_key=actor_key) == "public":
            await egress.send_text("Skill management is not available for public users.")
            return True

        session = self._load_session(item.conversation_key)
        skill_name = str(event.params.get("name", "") or "")

        if action == "skills_add":
            if not self.workflows.runtime_skills.catalog.has_skill(skill_name):
                await egress.send_text(f"Unknown skill: {skill_name}")
                return True
            outcome = self.workflows.runtime_skills.activation.begin_activate(
                session,
                actor_key=actor_key,
                skill_name=skill_name,
            )
            self._save_session_if_mutated(item.conversation_key, session, mutated=outcome.mutated)
            if outcome.status == "foreign_setup" and outcome.foreign_setup is not None:
                await egress.show_foreign_setup(outcome.foreign_setup)
                return True
            if outcome.status == "needs_setup" and outcome.first_requirement is not None:
                await egress.show_setup_prompt(skill_name, outcome.first_requirement)
                return True
            if outcome.status == "needs_confirmation":
                await egress.send_text(
                    "Activating this skill requires confirmation because it would increase prompt size. "
                    "Use the explicit confirmation flow in the interactive transport."
                )
                return True
            if outcome.status == "not_published":
                await egress.send_text(f"Skill {skill_name} is not published.")
                return True
            await egress.send_text(
                f"Skill {skill_name} activated." if outcome.status == "activated" else f"Skill {skill_name} is already active."
            )
            return True

        if action == "skills_remove":
            outcome = self.workflows.runtime_skills.activation.deactivate(
                session,
                actor_key=actor_key,
                skill_name=skill_name,
            )
            self._save_session_if_mutated(item.conversation_key, session, mutated=outcome.mutated)
            if outcome.status == "foreign_setup" and outcome.foreign_setup is not None:
                await egress.show_foreign_setup(outcome.foreign_setup)
                return True
            await egress.send_text(
                f"Skill {skill_name} deactivated." if outcome.status == "removed" else f"Skill {skill_name} is not active."
            )
            return True

        if action == "skills_setup":
            if not self.workflows.runtime_skills.catalog.has_skill(skill_name):
                await egress.send_text(f"Unknown skill: {skill_name}")
                return True
            outcome = self.workflows.runtime_skills.activation.begin_setup(
                session,
                actor_key=actor_key,
                skill_name=skill_name,
            )
            self._save_session_if_mutated(item.conversation_key, session, mutated=outcome.mutated)
            if outcome.status == "foreign_setup" and outcome.foreign_setup is not None:
                await egress.show_foreign_setup(outcome.foreign_setup)
                return True
            if outcome.first_requirement is not None:
                await egress.show_setup_prompt(skill_name, outcome.first_requirement)
                return True
            await egress.send_text(f"Skill {skill_name} is already configured.")
            return True

        outcome = self.workflows.runtime_skills.activation.clear(
            session,
            actor_key=actor_key,
        )
        self._save_session_if_mutated(item.conversation_key, session, mutated=outcome.mutated)
        if outcome.status == "foreign_setup" and outcome.foreign_setup is not None:
            await egress.show_foreign_setup(outcome.foreign_setup)
            return True
        await egress.send_text("Cleared active conversation skills.")
        return True

    async def _dispatch_delegation_action(
        self,
        event: InboundAction,
        item: WorkItemRecord,
        *,
        egress: TransportEgress,
        conversation_ref: str,
    ) -> bool:
        if event.action not in {"delegation_approve", "delegation_cancel"}:
            return False
        from octopus_sdk.workflows.delegation import (
            approve_participant_delegation,
            cancel_participant_delegation,
        )
        target_key = item.conversation_key
        if event.params.get("target_conversation_key"):
            target_key = str(event.params["target_conversation_key"])
        if event.action == "delegation_approve":
            outcome = await approve_participant_delegation(self._participant_delegation_runtime(), target_key)
        else:
            outcome = await cancel_participant_delegation(self._participant_delegation_runtime(), target_key)
        await egress.send_text(outcome.message or "Delegation updated.")
        return True

    def _participant_delegation_runtime(self):
        from octopus_sdk.workflows.delegation import ParticipantDelegationRuntime

        return ParticipantDelegationRuntime(
            config=self.config,
            provider_name=self.provider.name,
            provider_state_factory=self.provider.new_provider_state,
            coordination=self.registry.coordination,
            sessions=self.sessions,
        )

    async def _dispatch_direct_assignment_message(
        self,
        event: InboundMessage,
        item: WorkItemRecord,
        *,
        egress: TransportEgress,
        conversation_ref: str,
    ) -> bool:
        from octopus_sdk.workflows.delegation import submit_participant_direct_assignment

        direct_assignment = extract_target_selector_message(event.text)
        if direct_assignment is None:
            return False

        selector, instructions = direct_assignment
        requested_skills: tuple[str, ...] = ()
        effective_instructions = instructions
        if selector.kind != "skill":
            requested_skills, stripped_instructions = extract_leading_requested_skills(instructions)
            if requested_skills and stripped_instructions:
                effective_instructions = stripped_instructions
        parent_event_id = ""
        if conversation_ref.startswith("registry:"):
            parent_event_id = str(item.event_id or "").strip()
            if parent_event_id.startswith("reg:"):
                parent_event_id = parent_event_id.split(":", 1)[1]
        title = summarize_text(effective_instructions) or "Direct assignment"
        result = await submit_participant_direct_assignment(
            self._participant_delegation_runtime(),
            item.conversation_key,
            conversation_ref=conversation_ref,
            selector=selector,
            title=title,
            instructions=effective_instructions,
            parent_event_id=parent_event_id,
            message_text=event.text,
            origin_channel=str(getattr(event, "transport", "") or getattr(event, "source", "") or "registry"),
            external_ref=(
                str(getattr(event, "external_conversation_ref", "") or "")
                or conversation_ref
                or item.conversation_key
            ),
            authorized_actor_key=(
                str(getattr(event, "authorized_actor_key", "") or "")
                or item.actor_key
                or str(getattr(event.user, "id", "") or "")
            ),
            requested_skills=requested_skills,
        )
        task_ref = result.routed_tasks[0] if result.routed_tasks else None
        target_label = (
            f"@{selector.value}"
            if selector.kind == "agent"
            else f"@{selector.kind}:{selector.value}"
        )
        if task_ref is None:
            await egress.send_text(f"Task sent to {target_label}.")
        else:
            await egress.send_text(
                f"Task sent to {target_label}. Routed task id: {task_ref.routed_task_id}"
            )
        return True

    def _effective_message_text(self, event: InboundMessage) -> str:
        text = str(event.text or "").strip()
        sections = []
        context_text = str(getattr(event, "context_text", "") or "").strip()
        constraints_text = str(getattr(event, "constraints_text", "") or "").strip()
        if context_text:
            sections.append(f"Context:\n{context_text}")
        if constraints_text:
            sections.append(f"Constraints:\n{constraints_text}")
        if not sections:
            return text
        if not text:
            return "\n\n".join(sections)
        return text + "\n\n" + "\n\n".join(sections)

    def _activate_requested_routing_skills(
        self,
        session: SessionState,
        *,
        requested_skills: tuple[str, ...],
    ) -> bool:
        if not requested_skills:
            return False
        activation = self._require_execution_services().skill_activation
        catalog = self.workflows.runtime_skills.catalog
        mutated = False
        for skill_name in requested_skills:
            detail = catalog.get_skill(skill_name)
            if detail is None or not detail.can_activate:
                continue
            mutated = activation.activate(session, skill_name) or mutated
        return mutated

    async def _dispatch_claimed_message(
        self,
        event: InboundMessage,
        item: WorkItemRecord,
        *,
        cancel_event: asyncio.Event | None,
    ) -> None:
        from octopus_sdk.execution import load_approval_mode
        from octopus_sdk.workflows.delegation import expire_stale_delegations
        from octopus_sdk.workflows.execution_finalization import FinalizationContext, finalize_execution

        egress, conversation_ref = self._build_worker_egress(event, item)
        allowed, trust_tier = self._admit_claimed_message(
            event,
            item,
            conversation_ref=conversation_ref,
        )
        if not allowed:
            return

        title = str(getattr(event, "title_text", "") or "").strip() or summarize_text(event.text) or "Conversation"
        routed_task_id = str(getattr(event, "routed_task_id", "") or "")
        authority_ref = str(getattr(event, "authority_ref", "") or "")

        if routed_task_id and await self._dispatch_auto_design_routed_task(
            event,
            item,
            cancel_event=cancel_event,
        ):
            return

        if item.dispatch_mode == "recovery":
            if routed_task_id:
                await self._report_interrupted_routed_task_recovery(
                    routed_task_id=routed_task_id,
                    authority_ref=authority_ref,
                    event=event,
                    item=item,
                )
                return
            transport_identity = self._build_transport_identity(
                event=event,
                conversation_ref=conversation_ref,
                actor_key=str(getattr(event.user, "id", "") or ""),
            )
            from octopus_sdk.event_sink import build_event_sink_for_context

            event_sink = build_event_sink_for_context(
                transport_identity,
                self.control_plane.conversation_projection if self.control_plane is not None else None,
                self.config,
            )
            recovery_outcome = await self.workflows.recovery.replay.dispatch_worker_recovery(
                data_dir=self.config.data_dir,
                item_id=item.id,
                original_text=event.text or "",
                recovery_id=item.event_id,
                bind_egress=(
                    (lambda: egress.bind(title=title, config=self.config))
                    if not routed_task_id
                    else (lambda: asyncio.sleep(0))
                ),
                send_notice=(
                    (
                        lambda notice: egress.send_recovery_notice(
                            preview=notice.preview,
                            prompt=notice.prompt,
                            run_again_label=notice.run_again_label,
                            skip_label=notice.skip_label,
                            recovery_id=notice.recovery_id,
                        )
                    )
                    if not routed_task_id
                    else (lambda notice: asyncio.sleep(0))
                ),
                publish_notice=(
                    (
                        lambda notice: event_sink.on_approval_requested(
                            f"{notice.preview}\n\n{notice.prompt}".strip(),
                            request_kind="recovery",
                            actor_key=str(getattr(event.user, "id", "") or ""),
                            trust_tier=trust_tier,
                            request_id=f"recovery:{item.conversation_key}:{item.event_id}",
                            recovery_id=notice.recovery_id,
                        )
                    )
                    if not routed_task_id
                    else (lambda notice: asyncio.sleep(0))
                ),
            )
            if recovery_outcome.status == "pending_recovery":
                raise PendingRecovery(item.id)
            raise RuntimeError(f"Unexpected recovery outcome: {recovery_outcome.status}")

        if not routed_task_id:
            await egress.bind(title=title, config=self.config)
            await self._flush_deferred_notifications(
                actor_key=item.actor_key,
                egress=egress,
            )

        session = self._load_session(item.conversation_key)
        if not routed_task_id:
            if await self._dispatch_direct_assignment_message(
                event,
                item,
                egress=egress,
                conversation_ref=conversation_ref,
            ):
                return
        skill_mutated = self._activate_requested_routing_skills(
            session,
            requested_skills=tuple(
                str(skill).strip()
                for skill in getattr(event, "requested_skills", ())
                if str(skill).strip()
            ),
        )
        self._save_session_if_mutated(item.conversation_key, session, mutated=skill_mutated)
        expiration = expire_stale_delegations(
            session.pending_delegation,
            timeout_seconds=self.config.delegation_timeout_seconds,
        )
        if expiration.expired:
            session.pending_delegation = expiration.pending
            self.sessions.save(item.conversation_key, session)

        execution_event = replace(event, text=self._effective_message_text(event))
        outcome = await self._execute_message_request(
            event=execution_event,
            item=item,
            egress=egress,
            conversation_ref=conversation_ref,
            trust_tier=trust_tier,
            cancel_event=cancel_event,
        )
        if routed_task_id and outcome is None:
            from octopus_sdk.execution import interactive_followup_unavailable

            outcome = interactive_followup_unavailable()

        await finalize_execution(
            outcome,
            context=FinalizationContext(
                config=self.config,
                item_id=item.id,
                conversation_key=item.conversation_key,
                runtime_chat=item.conversation_key,
                conversation_ref=conversation_ref,
                chat_id=event.chat_id if isinstance(event.chat_id, int) else 0,
                routed_task_id=routed_task_id,
                authority_ref=authority_ref,
                skip_approval=bool(getattr(event, "skip_approval", False)),
                load_session=self._load_session,
                save_session=self.sessions.save,
                task_routing=self.control_plane.task_routing if self.control_plane is not None else None,
                record_usage=self.work_queue.record_usage,
                completion_webhook_sender=self.workflows.completion_webhook,
                deferred_notifications=self.workflows.deferred_notifications,
                deferred_target_agent_id=self._target_agent_id_for_authority(authority_ref),
                deferred_actor_key=str(getattr(event, "authorized_actor_key", "") or ""),
                deferred_title=title,
                protocol_stage_contract=dict(getattr(event, "protocol_stage_contract", {}) or {}),
                working_dir_hint=str(getattr(event, "working_dir_hint", "") or ""),
                registry_inspection=self.control_plane.registry_inspection if self.control_plane is not None else None,
                working_dir_resolver=self._resolved_working_dir,
            ),
        )

    async def _dispatch_claimed_action(
        self,
        event: InboundAction,
        item: WorkItemRecord,
        *,
        cancel_event: asyncio.Event | None,
    ) -> None:
        egress, conversation_ref = self._build_worker_egress(event, item)
        await egress.answer_action()
        if await self._dispatch_conversation_action(event, item, egress=egress, conversation_ref=conversation_ref):
            return
        if await self._dispatch_pending_action(event, item, egress=egress, conversation_ref=conversation_ref, cancel_event=cancel_event):
            return
        if await self._dispatch_skill_action(event, item, egress=egress):
            return
        if await self._dispatch_delegation_action(event, item, egress=egress, conversation_ref=conversation_ref):
            return

    async def _notify_orphaned_interaction(
        self,
        event: InboundCommand | InboundCallback,
        item: WorkItemRecord,
    ) -> None:
        try:
            conversation_ref = resolve_event_conversation_ref(config=self.config, event=event)
            kwargs: dict[str, object] = {
                "conversation_key": item.conversation_key,
                "source": str(getattr(event, "source", "") or self.transport.descriptor.transport_type),
            }
            kwargs.update(self.transport.worker_egress_kwargs(conversation_ref=conversation_ref))
            egress = self.transport.build_egress(
                conversation_ref=conversation_ref,
                config=self.config,
                **kwargs,
            )
        except Exception:
            return
        detail = f"/{event.command}" if isinstance(event, InboundCommand) else "a button action"
        message = self.workflows.messages.recovery_orphaned_command(detail)
        await egress.send_text(message)

    async def _notify_direct_message_dispatch_failure(
        self,
        event: InboundMessage | InboundCommand | InboundCallback | InboundAction,
        item: WorkItemRecord,
    ) -> None:
        if not isinstance(event, InboundMessage):
            return
        if str(getattr(event, "routed_task_id", "") or "").strip():
            return
        if str(getattr(event, "admission_class", "external") or "external") == "internal":
            return
        try:
            egress, _conversation_ref = self._build_worker_egress(event, item)
            await egress.send_text(self.workflows.messages.recovery_error_try_again())
        except Exception:
            log.debug(
                "Could not notify user about dispatch failure for work item %s",
                item.id,
                exc_info=True,
            )

    async def _dispatch_claimed_item(
        self,
        kind: str,
        event: InboundMessage | InboundCommand | InboundCallback | InboundAction,
        item: WorkItemRecord,
    ) -> None:
        async with self.transport.claimed_item_context(event=event, item=item):
            if isinstance(event, InboundMessage):
                await self._run_with_cancel_watch(
                    item,
                    lambda cancel_event: self._dispatch_claimed_message(
                        event,
                        item,
                        cancel_event=cancel_event,
                    ),
                )
                return
            if isinstance(event, InboundAction):
                await self._run_with_cancel_watch(
                    item,
                    lambda cancel_event: self._dispatch_claimed_action(
                        event,
                        item,
                        cancel_event=cancel_event,
                    ),
                )
                return
            if isinstance(event, (InboundCommand, InboundCallback)):
                await self._notify_orphaned_interaction(event, item)
                return
            raise RuntimeError(f"Unsupported claimed item kind: {kind}")

    async def _run_with_cancel_watch(
        self,
        item: WorkItemRecord,
        runner: Callable[[asyncio.Event | None], Awaitable[None]],
    ) -> None:
        cancel_event = asyncio.Event()

        async def _poll_cancel_requested() -> None:
            interval = self._worker_poll_interval()
            while not cancel_event.is_set():
                if self.work_queue.is_cancel_requested(self.config.data_dir, item.id):
                    cancel_event.set()
                    return
                await asyncio.sleep(interval)

        watcher = asyncio.create_task(
            _poll_cancel_requested(),
            name=f"cancel-watch:{item.id}",
        )
        try:
            await runner(cancel_event)
        finally:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)

    async def _run_worker_loop(self, stop_event: asyncio.Event) -> None:
        poll_interval = self._worker_poll_interval()
        started_at = time.time()
        items_processed_total = 0
        stale_recoveries_seen = 0
        current_item_id = ""
        current_conversation_key = ""
        current_kind = ""
        last_error = ""
        last_heartbeat = 0.0
        last_sweep = 0.0
        last_usage_purge = float("-inf")
        graceful_shutdown = False
        heartbeat_enabled = self.config.runtime_mode == "shared"
        worker_id = self._worker_id()

        def _publish_heartbeat(*, force: bool = False) -> None:
            nonlocal last_heartbeat
            if not heartbeat_enabled:
                return
            now_mono = time.monotonic()
            if not force and last_heartbeat and (now_mono - last_heartbeat) < 30.0:
                return
            self.work_queue.upsert_worker_heartbeat(
                self.config.data_dir,
                WorkerHeartbeat(
                    worker_id=worker_id,
                    process_role=self.config.process_role,
                    started_at=time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(started_at)),
                    last_seen_at=time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
                    current_item_id=current_item_id,
                    current_conversation_key=current_conversation_key,
                    current_kind=current_kind,
                    items_processed=items_processed_total,
                    stale_recoveries_seen=stale_recoveries_seen,
                    last_error=last_error,
                ),
            )
            last_heartbeat = now_mono

        try:
            _publish_heartbeat(force=True)
            while not stop_event.is_set():
                processed = 0
                try:
                    _publish_heartbeat()
                    now_mono = time.monotonic()
                    if now_mono - last_sweep >= self.config.claim_sweep_interval_seconds:
                        recovered = self.work_queue.recover_stale_claims(
                            self.config.data_dir,
                            lease_ttl_seconds=self.config.claim_lease_ttl_seconds,
                        )
                        if recovered:
                            stale_recoveries_seen += recovered
                            _publish_heartbeat(force=True)
                        if now_mono - last_usage_purge >= 3600.0:
                            self.work_queue.purge_old_usage(
                                self.config.data_dir,
                                older_than_seconds=168 * 3600,
                            )
                            last_usage_purge = now_mono
                        last_sweep = now_mono

                    for _ in range(10):
                        item = self.work_queue.claim_next_any(
                            self.config.data_dir,
                            worker_id,
                        )
                        if item is None:
                            break

                        item_id = item.id
                        current_item_id = item_id
                        current_conversation_key = item.conversation_key
                        current_kind = item.kind or "unknown"
                        last_error = ""
                        _publish_heartbeat(force=True)

                        try:
                            event = deserialize_inbound(item.kind or "unknown", item.payload or "{}")
                        except Exception:
                            self.work_queue.fail_work_item(
                                self.config.data_dir,
                                item_id,
                                error="deserialize_error",
                            )
                            try:
                                await self.transport.notify_deserialize_failure(item, runtime=self)
                            except Exception:
                                pass
                            current_item_id = ""
                            current_conversation_key = ""
                            current_kind = ""
                            items_processed_total += 1
                            processed += 1
                            _publish_heartbeat(force=True)
                            continue

                        try:
                            await self._dispatch_claimed_item(
                                item.kind or "unknown",
                                event,
                                item,
                            )
                            self.work_queue.complete_work_item(self.config.data_dir, item_id)
                        except PendingRecovery:
                            pass
                        except LeaveClaimed:
                            pass
                        except TransportStateCorruption:
                            last_error = "transport_state_corruption"
                            _publish_heartbeat(force=True)
                            raise
                        except Exception:
                            last_error = "dispatch_exception"
                            log.exception(
                                "Dispatch failed for work item %s kind=%s conversation=%s event=%s",
                                item_id,
                                current_kind,
                                current_conversation_key,
                                item.event_id,
                            )
                            await self._notify_direct_message_dispatch_failure(event, item)
                            self.work_queue.fail_work_item(
                                self.config.data_dir,
                                item_id,
                                error=last_error,
                            )
                        current_item_id = ""
                        current_conversation_key = ""
                        current_kind = ""
                        items_processed_total += 1
                        processed += 1
                        _publish_heartbeat(force=True)
                except TransportStateCorruption:
                    last_error = "transport_state_corruption"
                    _publish_heartbeat(force=True)
                    raise
                except Exception:
                    last_error = "dispatch_exception"
                    _publish_heartbeat(force=True)

                if processed:
                    continue

                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=poll_interval)
                    break
                except asyncio.TimeoutError:
                    pass
            graceful_shutdown = True
        finally:
            if heartbeat_enabled and graceful_shutdown:
                try:
                    self.work_queue.clear_worker_heartbeat(
                        self.config.data_dir,
                        worker_id,
                    )
                except Exception:
                    pass


@dataclass(frozen=True)
class ProviderDispatchRuntime:
    """Explicit runtime-owned provider dispatch collaborators."""

    config: BotConfigBase
    provider: Provider
    boot_id: str
    cancellations: MutableMapping[int | str, asyncio.Event]
    execution_inflight: MutableSet[int | str]

    async def send_status(self, message: TransportEgress, label: str) -> EditableHandle:
        return await message.send_status(label)

    def build_progress(
        self,
        status_message: EditableHandle,
        *,
        timeline_callback: Callable[[str, bool], Awaitable[None]] | None = None,
    ) -> ProviderProgress:
        return ProviderProgress(
            status_message,
            self.config,
            timeline_callback=timeline_callback,
        )

    def typing_target(self, message: TransportEgress) -> TransportEgress:
        return message.typing_target()

    async def keep_typing(self, message: TransportEgress) -> None:
        try:
            while True:
                await message.send_action("typing")
                await asyncio.sleep(self.config.typing_interval_seconds)
        except asyncio.CancelledError:
            return None

    async def heartbeat(
        self,
        progress: ProviderProgress,
        content_started: asyncio.Event,
    ) -> None:
        first = 5.0
        subsequent = 10.0
        try:
            start = asyncio.get_running_loop().time()
            await asyncio.sleep(first)
            while not content_started.is_set():
                last = getattr(progress, "_last_update", 0.0)
                since_last = asyncio.get_running_loop().time() - last if last else first
                if since_last < subsequent:
                    await asyncio.sleep(subsequent - since_last)
                    continue
                elapsed = int(asyncio.get_running_loop().time() - start)
                await progress.update(f"Still working… {elapsed}s", force=True)
                await asyncio.sleep(subsequent)
        except asyncio.CancelledError:
            return None

    async def format_provider_error(self, raw_text: str, returncode: int) -> str:
        text = str(raw_text or "").strip()
        if not text:
            return f"Provider exited with code {returncode} (no output)."
        path_re = re.compile(
            r"(?<![\w.-])(?:/Users|/home|/app|/tmp|/var|/srv|/opt|/etc)(?:/[^\s'\":]+)+"
        )
        secret_re = re.compile(
            r"(?i)\b("
            r"api[_-]?key|token|secret|password|passwd|authorization|credential"
            r")(\s*[:=]\s*)([^\s,;]+)"
        )
        runtime_token_re = re.compile(r"oct-rt-[A-Za-z0-9_-]+")
        text = secret_re.sub(r"\1\2<redacted>", text)
        text = runtime_token_re.sub("<runtime-token>", text)
        text = path_re.sub("<path>", text)
        limit = 1500
        if len(text) > limit:
            return text[: limit - 1].rstrip() + "…"
        return text

    def run_result_was_interrupted(self, returncode: int) -> bool:
        return returncode < 0


@dataclass(frozen=True)
class ProviderDispatchOutcome:
    progress: ProviderProgress
    result: object


async def _run_provider_call(
    chat_id: int | str,
    *,
    message,
    label: str,
    cancel_event: asyncio.Event | None,
    runtime: ProviderDispatchRuntime,
    timeline_callback: Callable[[str, bool], Awaitable[None]] | None,
    invoke: Callable[[ProviderProgress, asyncio.Event], Awaitable[object]],
) -> ProviderDispatchOutcome:
    status_msg = await runtime.send_status(message, label)
    progress = runtime.build_progress(
        status_msg,
        timeline_callback=timeline_callback,
    )
    content_started = asyncio.Event()
    progress.content_started = content_started
    typing_task = asyncio.create_task(runtime.keep_typing(runtime.typing_target(message)))
    heartbeat_task = asyncio.create_task(runtime.heartbeat(progress, content_started))

    local_cancel_event = cancel_event or asyncio.Event()
    runtime.cancellations[chat_id] = local_cancel_event
    try:
        result = await invoke(progress, local_cancel_event)
    finally:
        runtime.cancellations.pop(chat_id, None)
        heartbeat_task.cancel()
        typing_task.cancel()
        await asyncio.gather(heartbeat_task, typing_task, return_exceptions=True)

    return ProviderDispatchOutcome(progress=progress, result=result)


async def run_provider_request(
    chat_id: int | str,
    *,
    prompt: str,
    image_paths: list[str],
    message,
    provider_state: ProviderStateRecord,
    context,
    cancel_event: asyncio.Event | None = None,
    label: str,
    runtime: ProviderDispatchRuntime,
    timeline_callback: Callable[[str, bool], Awaitable[None]] | None = None,
) -> ProviderDispatchOutcome:
    return await _run_provider_call(
        chat_id,
        message=message,
        label=label,
        cancel_event=cancel_event,
        runtime=runtime,
        timeline_callback=timeline_callback,
        invoke=lambda progress, local_cancel_event: runtime.provider.run(
            provider_state,
            prompt,
            image_paths,
            progress,
            context=context,
            cancel=local_cancel_event,
        ),
    )


async def run_provider_preflight(
    chat_id: int | str,
    *,
    prompt: str,
    image_paths: list[str],
    message,
    context,
    cancel_event: asyncio.Event | None = None,
    label: str,
    runtime: ProviderDispatchRuntime,
    timeline_callback: Callable[[str, bool], Awaitable[None]] | None = None,
) -> ProviderDispatchOutcome:
    return await _run_provider_call(
        chat_id,
        message=message,
        label=label,
        cancel_event=cancel_event,
        runtime=runtime,
        timeline_callback=timeline_callback,
        invoke=lambda progress, local_cancel_event: runtime.provider.run_preflight(
            prompt,
            image_paths,
            progress,
            context=context,
            cancel=local_cancel_event,
        ),
    )
