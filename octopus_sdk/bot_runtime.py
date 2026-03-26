"""Unified bot runtime support contracts and provider dispatch plumbing."""

from __future__ import annotations

import asyncio
import re
import signal
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable
from typing import Callable
from typing import MutableMapping
from typing import Protocol
from typing import runtime_checkable

from octopus_sdk.agent_directory import AgentDirectoryPort
from octopus_sdk.authorization import AuthorizationPort
from octopus_sdk.config import BotConfigBase
from octopus_sdk.conversation_projection import ConversationProjectionPort
from octopus_sdk.execution_context import ResolvedExecutionContext
from octopus_sdk.health_publication import HealthPublicationPort
from octopus_sdk.providers import CredentialEnvRecord, PreflightContext, Provider, ProviderStateRecord, RunContext
from octopus_sdk.registry_participant import RegistryParticipantImplementation
from octopus_sdk.registry.models import DiscoveredAgentRef
from octopus_sdk.sessions import SessionState
from octopus_sdk.inbound_types import InboundEnvelope, serialize_inbound
from octopus_sdk.transport import InboundSubmissionResult
from octopus_sdk.transport import EditableHandle
from octopus_sdk.transport import TransportEgress
from octopus_sdk.transport import TransportImplementation
from octopus_sdk.work_queue import WorkQueuePort
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


@runtime_checkable
class ProviderGuidancePort(Protocol):
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


@runtime_checkable
class SkillActivationPort(Protocol):
    def normalize(self, session: SessionState) -> list[str]: ...


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
class ControlPlanePort(Protocol):
    conversation_projection: ConversationProjectionPort
    task_routing: TaskRoutingPort
    agent_directory: AgentDirectoryPort
    health_publication: HealthPublicationPort


@runtime_checkable
class RuntimeLifecyclePort(Protocol):
    async def startup(self, stop_event: asyncio.Event) -> None: ...

    async def shutdown(self) -> None: ...


@dataclass(frozen=True)
class ExecutionServices:
    guidance: ProviderGuidancePort
    skill_activation: SkillActivationPort
    runtime_skill_setup: WorkflowRuntimeSkillSetupPort
    sessions: SessionRuntimePort
    artifacts: ArtifactStorePort
    agent_directory: AgentDirectoryPort | None = None
    conversation_projection: ConversationProjectionPort | None = None


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
    lifecycle: RuntimeLifecyclePort | None = None

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

    async def run(self) -> None:
        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop_event.set)
            except NotImplementedError:
                continue

        try:
            if self.lifecycle is not None:
                await self.lifecycle.startup(stop_event)
            await self.transport.start(runtime=self, stop_event=stop_event)
            await stop_event.wait()
        finally:
            stop_event.set()
            await self.transport.stop()
            if self.lifecycle is not None:
                await self.lifecycle.shutdown()


@dataclass(frozen=True)
class ProviderDispatchRuntime:
    """Explicit runtime-owned provider dispatch collaborators."""

    config: BotConfigBase
    provider: Provider
    boot_id: str
    cancellations: MutableMapping[int | str, asyncio.Event]

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
        text = secret_re.sub(r"\1\2<redacted>", text)
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
