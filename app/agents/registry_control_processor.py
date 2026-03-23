"""Registry-backed control-plane command processor."""

from __future__ import annotations

import json
import uuid
from typing import Any

from app.agents.client import RegistryClientError
from app.agents.registry_capabilities import (
    registry_authority_capabilities,
    registry_id_from_authority_ref,
)
from app.agents.registry_runtime import RegistryRuntime
from app.agents.types import (
    AgentDiscoveryQuery,
    DiscoveredAgentRef,
    RoutedTaskRequest,
    RoutedTaskResult,
    RoutedTaskUpdate,
)
from app.control_plane.models import ControlCommand, ControlReply
from app.control_plane.processor_base import ControlProcessor
from app.control_plane.requests import (
    PublishHealthRequest,
    ReportTaskResultPayload,
    ResolveTargetAuthorityRequest,
    SearchAgentsRequest,
    SubmitRoutedTaskPayload,
    TimelineEventPayload,
    UpdateRoutedTaskStatusPayload,
)
from app.ports.agent_directory import AgentSearchResult, AuthorityResolution
from app.ports.task_routing import TaskResultReport, TaskSubmissionResult


class RegistryControlProcessor(ControlProcessor):
    def __init__(self, registry_runtime: RegistryRuntime) -> None:
        self._runtime = registry_runtime

    def authority_capabilities(self) -> dict[str, set[str]]:
        return registry_authority_capabilities(self._runtime.registries)

    async def process(self, command: ControlCommand) -> ControlReply:
        try:
            registry_id = registry_id_from_authority_ref(command.authority_ref)
        except ValueError as exc:
            return ControlReply(command_id=command.command_id, status="failed", error=str(exc))
        client = self._runtime.client_for_registry(registry_id)
        if client is None:
            return ControlReply(
                command_id=command.command_id,
                status="failed",
                error=f"no registry client for {command.authority_ref}",
            )

        try:
            if command.capability == "conversation_projection":
                return await self._process_conversation_projection(command, client)
            if command.capability == "mirror_retry":
                return await self._process_mirror_retry(command, client)
            if command.capability == "task_routing":
                return await self._process_task_routing(command, client)
            if command.capability == "agent_directory":
                return await self._process_agent_directory(command, client, registry_id)
            if command.capability == "health_publication":
                return await self._process_health_publication(command, client)
            return ControlReply(
                command_id=command.command_id,
                status="failed",
                error=f"unsupported control-plane capability {command.capability!r}",
            )
        except RegistryClientError as exc:
            return ControlReply(
                command_id=command.command_id,
                status="failed",
                error=exc.operator_detail or str(exc),
            )

    async def _process_conversation_projection(self, command: ControlCommand, client) -> ControlReply:
        if command.operation == "create_conversation":
            payload = json.loads(command.payload_json)
            response = await client.create_conversation(
                target_agent_id=payload["target_agent_id"],
                origin_channel=payload["origin_channel"],
                external_conversation_ref=payload["external_conversation_ref"],
                title=payload.get("title", ""),
            )
            return ControlReply(
                command_id=command.command_id,
                status="completed",
                result_json=json.dumps(response),
            )
        if command.operation == "publish_events":
            payload = json.loads(command.payload_json)
            conversation_id = payload["conversation_id"]
            from registry_sdk.events import ConversationEvent as SdkConversationEvent
            events = [SdkConversationEvent.model_validate(e) for e in payload["events"]]
            await client.publish_events(conversation_id, events)
            return ControlReply(command_id=command.command_id, status="completed")
        return ControlReply(
            command_id=command.command_id,
            status="failed",
            error=f"unsupported conversation_projection operation {command.operation!r}",
        )

    async def _process_mirror_retry(self, command: ControlCommand, client) -> ControlReply:
        if command.operation == "create_conversation":
            payload = json.loads(command.payload_json)
            response = await client.create_conversation(
                target_agent_id=payload["target_agent_id"],
                origin_channel=payload["origin_channel"],
                external_conversation_ref=payload["external_conversation_ref"],
                title=payload.get("title", ""),
            )
            return ControlReply(
                command_id=command.command_id,
                status="completed",
                result_json=json.dumps(response),
            )
        if command.operation == "publish_events":
            payload = json.loads(command.payload_json)
            conversation_id = payload["conversation_id"]
            from registry_sdk.events import ConversationEvent as SdkConversationEvent
            events = [SdkConversationEvent.model_validate(e) for e in payload["events"]]
            await client.publish_events(conversation_id, events)
            return ControlReply(command_id=command.command_id, status="completed")
        return ControlReply(
            command_id=command.command_id,
            status="failed",
            error=f"unsupported mirror_retry operation {command.operation!r}",
        )

    async def _process_task_routing(self, command: ControlCommand, client) -> ControlReply:
        if command.operation == "submit_routed_task":
            payload = SubmitRoutedTaskPayload.model_validate_json(command.payload_json)
            request = RoutedTaskRequest(
                routed_task_id=payload.routed_task_id,
                parent_conversation_id=payload.parent_conversation_id,
                origin_agent_id=payload.origin_agent_id,
                target_agent_id=payload.target_agent_id,
                title=payload.title,
                instructions=payload.instructions,
                context=dict(payload.context),
                constraints=dict(payload.constraints),
                requested_capabilities=tuple(payload.requested_capabilities),
                priority=payload.priority,
                created_at=payload.created_at,
            )
            response = await client.submit_routed_task(request)
            return ControlReply(
                command_id=command.command_id,
                status="completed",
                result_json=TaskSubmissionResult(
                    status="accepted",
                    routed_task_id=str(response.get("routed_task_id", payload.routed_task_id)),
                    delivery_id=str(response.get("delivery_id", "")),
                ).model_dump_json(),
            )
        if command.operation == "report_routed_task_result":
            payload = ReportTaskResultPayload.model_validate_json(command.payload_json)
            result = RoutedTaskResult(
                routed_task_id=payload.routed_task_id,
                status=payload.status,
                summary=payload.summary,
                full_text=payload.full_text,
                artifacts=tuple(dict(item) for item in payload.artifacts),
                follow_up_questions=tuple(payload.follow_up_questions),
                completed_at=payload.completed_at,
            )
            response = await client.routed_task_result(payload.routed_task_id, result)
            return ControlReply(
                command_id=command.command_id,
                status="completed",
                result_json=TaskResultReport(
                    status="reported",
                    routed_task_id=str(response.get("routed_task_id", payload.routed_task_id)),
                ).model_dump_json(),
            )
        if command.operation == "update_routed_task_status":
            payload = UpdateRoutedTaskStatusPayload.model_validate_json(command.payload_json)
            update = RoutedTaskUpdate(
                routed_task_id=payload.routed_task_id,
                status=payload.status,
                summary=payload.summary,
                timeline_events=tuple(event.model_dump() for event in payload.timeline_events),
                progress=payload.progress,
                updated_at=payload.updated_at,
            )
            await client.routed_task_status(payload.routed_task_id, update)
            return ControlReply(command_id=command.command_id, status="completed")
        return ControlReply(
            command_id=command.command_id,
            status="failed",
            error=f"unsupported task_routing operation {command.operation!r}",
        )

    async def _process_agent_directory(self, command: ControlCommand, client, registry_id: str) -> ControlReply:
        if command.operation == "search_agents":
            request = SearchAgentsRequest.model_validate_json(command.payload_json)
            query = AgentDiscoveryQuery(
                role=request.role,
                capabilities=tuple(request.capabilities),
                tags=tuple(request.tags),
                free_text=request.free_text,
                exclude_agent_ids=tuple(request.exclude_agent_ids),
                required_state=request.required_state,
            )
            rows = await client.search(query)
            agents = [
                DiscoveredAgentRef(
                    authority_ref=command.authority_ref,
                    agent_id=str(row.get("agent_id", "")),
                    display_name=str(row.get("display_name", "")),
                    slug=str(row.get("slug", "")),
                    role=str(row.get("role", "")),
                    capabilities=tuple(
                        str(item)
                        for item in row.get("capabilities", row.get("skills", []))
                        if item
                    ),
                    tags=tuple(str(item) for item in row.get("tags", []) if item),
                    description=str(row.get("description", "")),
                    connectivity_state=str(row.get("connectivity_state", "")),
                    current_capacity=int(row.get("current_capacity", 0) or 0),
                    max_capacity=int(row.get("max_capacity", 1) or 1),
                )
                for row in rows
            ]
            return ControlReply(
                command_id=command.command_id,
                status="completed",
                result_json=AgentSearchResult(status="complete", agents=agents).model_dump_json(),
            )
        if command.operation == "resolve_target_authority":
            request = ResolveTargetAuthorityRequest.model_validate_json(command.payload_json)
            local_agent_id = self._runtime.origin_agent_id(registry_id)
            query = AgentDiscoveryQuery(
                required_state="connected",
                exclude_agent_ids=(local_agent_id,) if local_agent_id else (),
            )
            rows = await client.search(query)
            for row in rows:
                if str(row.get("agent_id", "")) == request.target_agent_id:
                    return ControlReply(
                        command_id=command.command_id,
                        status="completed",
                        result_json=AuthorityResolution(
                            status="resolved",
                            authority_ref=command.authority_ref,
                        ).model_dump_json(),
                    )
            return ControlReply(
                command_id=command.command_id,
                status="completed",
                result_json=AuthorityResolution(status="not_found").model_dump_json(),
            )
        return ControlReply(
            command_id=command.command_id,
            status="failed",
            error=f"unsupported agent_directory operation {command.operation!r}",
        )

    async def _process_health_publication(self, command: ControlCommand, client) -> ControlReply:
        if command.operation != "publish_health":
            return ControlReply(
                command_id=command.command_id,
                status="failed",
                error=f"unsupported health_publication operation {command.operation!r}",
            )
        request = PublishHealthRequest.model_validate_json(command.payload_json)
        runtime_health: dict[str, Any] | None = None
        if request.runtime_health_json:
            runtime_health = json.loads(request.runtime_health_json)
        await client.heartbeat(
            connectivity_state=request.connectivity_state,
            current_capacity=request.current_capacity,
            max_capacity=request.max_capacity,
            runtime_health=runtime_health,
        )
        return ControlReply(command_id=command.command_id, status="completed")
