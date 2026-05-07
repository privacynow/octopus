"""SDK-owned Octopus awareness records and rendering for bot runtimes."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import Field

from octopus_sdk.protocols.models import (
    ProtocolArtifactRecord,
    ProtocolArtifactRuntimeInstanceRecord,
    ProtocolDefinitionRecord,
    ProtocolRunDetailRecord,
    ProtocolRunRecord,
    ProtocolStageExecutionRecord,
)
from octopus_sdk.registry.models import RegistryRecordModel


def _compact(value: object, *, limit: int = 180) -> str:
    text = " ".join(str(value or "").strip().split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "..."


def _short_id(value: object, *, length: int = 8) -> str:
    text = str(value or "").strip()
    return text[:length] if len(text) > length else text


class AgentToolCapabilityRecord(RegistryRecordModel):
    name: str = ""
    available: bool = False
    path: str = ""
    detail: str = ""


class AgentWorkspaceAwarenessRecord(RegistryRecordModel):
    name: str = ""
    root_dir: str = ""
    file_policy: str = ""
    active: bool = False


class AgentProtocolSummaryRecord(RegistryRecordModel):
    protocol_id: str = ""
    slug: str = ""
    display_name: str = ""
    description: str = ""
    lifecycle_state: str = ""
    current_version_id: str = ""


class AgentStageOutcomeSummaryRecord(RegistryRecordModel):
    stage_key: str = ""
    status: str = ""
    decision: str = ""
    decision_summary: str = ""
    attempt: int = 1
    loop_iteration: int = 1


class AgentArtifactOutcomeSummaryRecord(RegistryRecordModel):
    artifact_key: str = ""
    workspace_path: str = ""
    exists: bool = False
    verification_state: str = ""
    state: str = ""
    size_bytes: int = 0


class AgentRuntimeOutcomeSummaryRecord(RegistryRecordModel):
    artifact_key: str = ""
    status: str = ""
    ui_url: str = ""
    api_url: str = ""
    health_url: str = ""
    failure_code: str = ""
    failure_detail: str = ""


class AgentRunSummaryRecord(RegistryRecordModel):
    protocol_run_id: str = ""
    protocol_id: str = ""
    protocol_label: str = ""
    status: str = ""
    current_stage_key: str = ""
    problem_statement: str = ""
    origin_channel: str = ""
    workspace_ref: str = ""
    updated_at: str = ""
    completed_at: str = ""
    artifacts: list[AgentArtifactOutcomeSummaryRecord] = Field(default_factory=list)
    stages: list[AgentStageOutcomeSummaryRecord] = Field(default_factory=list)
    runtimes: list[AgentRuntimeOutcomeSummaryRecord] = Field(default_factory=list)


class AgentAwarenessRequestRecord(RegistryRecordModel):
    origin_channel: str = ""
    conversation_key: str = ""
    user_prompt: str = ""
    agent_slug: str = ""
    agent_display_name: str = ""
    provider_name: str = ""
    model: str = ""
    working_dir: str = ""
    workspace_ref: str = ""
    file_policy: str = ""
    active_skills: list[str] = Field(default_factory=list)
    available_skills: list[str] = Field(default_factory=list)
    workspaces: list[AgentWorkspaceAwarenessRecord] = Field(default_factory=list)
    tool_capabilities: list[AgentToolCapabilityRecord] = Field(default_factory=list)
    recent_run_detail_limit: int = Field(default=2, ge=0, le=5)


class AgentAwarenessRecord(RegistryRecordModel):
    source: str = "sdk"
    origin_channel: str = ""
    agent_slug: str = ""
    agent_display_name: str = ""
    provider_name: str = ""
    model: str = ""
    working_dir: str = ""
    workspace_ref: str = ""
    file_policy: str = ""
    active_skills: list[str] = Field(default_factory=list)
    available_skills: list[str] = Field(default_factory=list)
    workspaces: list[AgentWorkspaceAwarenessRecord] = Field(default_factory=list)
    tool_capabilities: list[AgentToolCapabilityRecord] = Field(default_factory=list)
    protocols: list[AgentProtocolSummaryRecord] = Field(default_factory=list)
    recent_runs: list[AgentRunSummaryRecord] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def to_prompt_block(self) -> str:
        lines: list[str] = [
            "## Octopus Agent Awareness",
            "",
            "This is SDK-backed operational context supplied by Octopus before the model invocation. "
            "Treat it as current state, but do not claim facts beyond it; ask for a protocol or run reference when ambiguous.",
        ]

        identity_parts = []
        if self.agent_display_name or self.agent_slug:
            identity_parts.append(self.agent_display_name or self.agent_slug)
        if self.agent_slug and self.agent_slug != self.agent_display_name:
            identity_parts.append(f"slug {self.agent_slug}")
        if self.provider_name:
            identity_parts.append(f"provider {self.provider_name}")
        if self.model:
            identity_parts.append(f"model {self.model}")
        if identity_parts:
            lines.extend(["", "Agent: " + "; ".join(identity_parts) + "."])

        if self.working_dir or self.workspace_ref or self.file_policy:
            workspace_bits = []
            if self.workspace_ref:
                workspace_bits.append(f"workspace ref {self.workspace_ref}")
            if self.working_dir:
                workspace_bits.append(f"working directory {self.working_dir}")
            if self.file_policy:
                workspace_bits.append(f"file policy {self.file_policy}")
            lines.append("Execution context: " + "; ".join(workspace_bits) + ".")

        available_tools = [item for item in self.tool_capabilities if item.available]
        if available_tools:
            tool_labels = []
            for item in available_tools[:14]:
                detail = f" ({item.detail})" if item.detail else ""
                tool_labels.append(f"{item.name}{detail}")
            lines.extend(["", "Container/tool capabilities: " + ", ".join(tool_labels) + "."])
            if any(item.name == "sudo" and item.available for item in available_tools):
                lines.append(
                    "The bot container is high-trust: sudo is available inside the container for installing packages, "
                    "but this is not host-root access unless the operator mounted host paths or Docker privileges."
                )

        if self.workspaces:
            lines.extend(["", "Configured workspaces:"])
            for workspace in self.workspaces[:6]:
                active = "active" if workspace.active else "available"
                policy = f", {workspace.file_policy}" if workspace.file_policy else ""
                lines.append(f"- {workspace.name or 'workspace'}: {workspace.root_dir}{policy} ({active})")

        if self.protocols:
            lines.extend(
                [
                    "",
                    "Launchable protocols:",
                    "These are Octopus protocols the user can run. Do not confuse them with skills.",
                ]
            )
            for protocol in self.protocols[:10]:
                label = protocol.display_name or protocol.slug or protocol.protocol_id
                token = protocol.slug or protocol.protocol_id
                description = f" - {_compact(protocol.description, limit=120)}" if protocol.description else ""
                lines.append(f"- {label} (`{token}`): {protocol.lifecycle_state or 'available'}{description}")
        else:
            lines.extend(
                [
                    "",
                    "Launchable protocols: none visible in the current Octopus awareness snapshot.",
                ]
            )

        if self.available_skills or self.active_skills:
            available = ", ".join(self.available_skills[:16]) or "none"
            active = ", ".join(self.active_skills[:16]) or "none"
            lines.extend(
                [
                    "",
                    "Skills are reusable instructions/capabilities, not runnable protocols.",
                    f"Skills: available on this bot: {available}. Active in this conversation: {active}.",
                ]
            )

        if self.recent_runs:
            lines.extend(["", "Recent protocol runs:"])
            for run in self.recent_runs[:6]:
                label = run.protocol_label or run.protocol_id or "protocol"
                run_ref = _short_id(run.protocol_run_id)
                objective = f" - {_compact(run.problem_statement, limit=120)}" if run.problem_statement else ""
                stage = f", stage {run.current_stage_key}" if run.current_stage_key else ""
                lines.append(f"- {label} run `{run_ref}`: {run.status or 'unknown'}{stage}{objective}")
                if run.artifacts:
                    artifact_labels = []
                    for artifact in run.artifacts[:4]:
                        path = artifact.workspace_path or artifact.artifact_key
                        state = artifact.verification_state or ("available" if artifact.exists else "declared")
                        artifact_labels.append(f"{artifact.artifact_key or path} ({state})")
                    lines.append(f"  Artifacts: {', '.join(artifact_labels)}.")
                if run.stages:
                    stage_labels = []
                    for stage in run.stages[:4]:
                        decision = f", {stage.decision}" if stage.decision else ""
                        summary = f" - {_compact(stage.decision_summary, limit=80)}" if stage.decision_summary else ""
                        stage_labels.append(
                            f"{stage.stage_key} ({stage.status}{decision}, attempt {stage.attempt}){summary}"
                        )
                    lines.append(f"  Stage outcomes: {'; '.join(stage_labels)}.")
                if run.runtimes:
                    runtime_labels = [
                        f"{runtime.artifact_key} ({runtime.status})"
                        for runtime in run.runtimes[:3]
                    ]
                    lines.append(f"  Runtimes: {', '.join(runtime_labels)}.")

        lines.extend(["", "Available Octopus actions through SDK-backed surfaces:"])
        lines.append("- list protocols and recent runs; inspect run status, stages, artifacts, runtime health, logs, and exports")
        lines.append("- start published protocols; improve existing protocols or runs through Auto Protocol; start/stop runnable artifacts")
        lines.append("- archive/delete runs and runtime instances when the current surface and permissions allow it")
        if self.origin_channel == "telegram":
            lines.append(
                "Telegram shortcuts exist for these actions: `/protocol list`, `/protocol recent`, "
                "`/protocol start`, `/protocol improve`, `/protocol improve-run`, `/protocol status`, and `/protocol artifacts`. "
                "Use them as shortcuts, not as the only source of understanding."
            )

        if self.warnings:
            lines.extend(["", "Awareness warnings:"])
            for warning in self.warnings[:4]:
                lines.append(f"- {_compact(warning, limit=180)}")

        return "\n".join(lines).strip()


@runtime_checkable
class ProtocolAwarenessSourcePort(Protocol):
    async def list_launchable(self, *, cursor: int = 0, limit: int = 100) -> list[ProtocolDefinitionRecord]: ...

    async def list_runs(
        self,
        *,
        cursor: int = 0,
        limit: int = 25,
        status: str = "",
        protocol_id: str = "",
        entry_agent_id: str = "",
        root_conversation_id: str = "",
        origin_channel: str = "",
    ) -> list[ProtocolRunRecord]: ...

    async def get_run_status(self, run_id: str) -> ProtocolRunDetailRecord: ...


@runtime_checkable
class AgentAwarenessPort(Protocol):
    async def build_awareness(self, request: AgentAwarenessRequestRecord) -> AgentAwarenessRecord: ...


def _protocol_summary(protocol: ProtocolDefinitionRecord) -> AgentProtocolSummaryRecord:
    return AgentProtocolSummaryRecord(
        protocol_id=protocol.protocol_id,
        slug=protocol.slug,
        display_name=protocol.display_name,
        description=protocol.description,
        lifecycle_state=protocol.lifecycle_state,
        current_version_id=protocol.current_version_id,
    )


def _stage_summary(stage: ProtocolStageExecutionRecord) -> AgentStageOutcomeSummaryRecord:
    return AgentStageOutcomeSummaryRecord(
        stage_key=stage.stage_key,
        status=stage.status,
        decision=stage.decision,
        decision_summary=_compact(stage.decision_summary, limit=180),
        attempt=stage.attempt,
        loop_iteration=stage.loop_iteration,
    )


def _artifact_summary(artifact: ProtocolArtifactRecord) -> AgentArtifactOutcomeSummaryRecord:
    return AgentArtifactOutcomeSummaryRecord(
        artifact_key=artifact.artifact_key,
        workspace_path=artifact.workspace_path or artifact.location,
        exists=artifact.exists,
        verification_state=artifact.verification_state,
        state=artifact.state,
        size_bytes=artifact.size_bytes,
    )


def _runtime_summary(runtime: ProtocolArtifactRuntimeInstanceRecord) -> AgentRuntimeOutcomeSummaryRecord:
    return AgentRuntimeOutcomeSummaryRecord(
        artifact_key=runtime.artifact_key,
        status=str(runtime.status or ""),
        ui_url=runtime.ui_url,
        api_url=runtime.api_url,
        health_url=runtime.health_url,
        failure_code=runtime.failure_code,
        failure_detail=_compact(runtime.failure_detail, limit=180),
    )


def _run_summary(run: ProtocolRunRecord) -> AgentRunSummaryRecord:
    return AgentRunSummaryRecord(
        protocol_run_id=run.protocol_run_id,
        protocol_id=run.protocol_id,
        protocol_label=run.protocol_id,
        status=run.status,
        current_stage_key=run.current_stage_key,
        problem_statement=_compact(run.problem_statement, limit=220),
        origin_channel=run.origin_channel,
        workspace_ref=run.workspace_ref,
        updated_at=run.updated_at,
        completed_at=run.completed_at,
    )


def _run_detail_summary(detail: ProtocolRunDetailRecord) -> AgentRunSummaryRecord:
    run = detail.run
    protocol_label = (
        detail.definition.display_name
        or detail.definition.slug
        or run.protocol_id
    )
    stages = [_stage_summary(item) for item in (detail.stage_executions or [])[:4]]
    verified = [
        item for item in (detail.artifacts or [])
        if item.exists or item.verification_state in {"available", "verified"}
    ]
    artifacts = [_artifact_summary(item) for item in (verified or detail.artifacts or [])[:5]]
    runtimes = [_runtime_summary(item) for item in (detail.runtime_instances or [])[:4]]
    return AgentRunSummaryRecord(
        protocol_run_id=run.protocol_run_id,
        protocol_id=run.protocol_id,
        protocol_label=protocol_label,
        status=run.status,
        current_stage_key=run.current_stage_key,
        problem_statement=_compact(run.problem_statement, limit=220),
        origin_channel=run.origin_channel,
        workspace_ref=run.workspace_ref,
        updated_at=run.updated_at,
        completed_at=run.completed_at,
        artifacts=artifacts,
        stages=stages,
        runtimes=runtimes,
    )


class ProtocolAgentAwarenessService:
    """Builds agent awareness from SDK protocol ports.

    Registry is one authority implementation of these ports. Future bot
    runtimes can provide another implementation without changing the awareness
    contract or provider prompt rendering.
    """

    def __init__(self, source: ProtocolAwarenessSourcePort | None = None) -> None:
        self._source = source

    async def build_awareness(self, request: AgentAwarenessRequestRecord) -> AgentAwarenessRecord:
        warnings: list[str] = []
        protocols: list[AgentProtocolSummaryRecord] = []
        recent_runs: list[AgentRunSummaryRecord] = []

        if self._source is None:
            warnings.append("No protocol authority is connected for SDK awareness.")
        else:
            try:
                protocols = [
                    _protocol_summary(item)
                    for item in await self._source.list_launchable(cursor=0, limit=10)
                ]
            except Exception as exc:  # pragma: no cover - exact transport errors are implementation-specific
                warnings.append(f"Protocol catalog unavailable: {exc}")

            try:
                runs = await self._source.list_runs(cursor=0, limit=6)
                detail_budget = request.recent_run_detail_limit
                for index, run in enumerate(runs):
                    if index < detail_budget and run.protocol_run_id:
                        try:
                            recent_runs.append(_run_detail_summary(await self._source.get_run_status(run.protocol_run_id)))
                            continue
                        except Exception as exc:  # pragma: no cover - exact transport errors are implementation-specific
                            warnings.append(f"Run detail unavailable for {_short_id(run.protocol_run_id)}: {exc}")
                    recent_runs.append(_run_summary(run))
            except Exception as exc:  # pragma: no cover - exact transport errors are implementation-specific
                warnings.append(f"Recent runs unavailable: {exc}")

        return AgentAwarenessRecord(
            source="sdk",
            origin_channel=request.origin_channel,
            agent_slug=request.agent_slug,
            agent_display_name=request.agent_display_name,
            provider_name=request.provider_name,
            model=request.model,
            working_dir=request.working_dir,
            workspace_ref=request.workspace_ref,
            file_policy=request.file_policy,
            active_skills=list(request.active_skills),
            available_skills=list(request.available_skills),
            workspaces=list(request.workspaces),
            tool_capabilities=list(request.tool_capabilities),
            protocols=protocols,
            recent_runs=recent_runs,
            warnings=warnings,
        )
