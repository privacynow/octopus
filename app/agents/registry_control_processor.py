"""Registry-backed control-plane command processor."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Protocol

from app.agents.registry_capabilities import (
    registry_authority_capabilities,
    registry_id_from_authority_ref,
)
from app.control_plane.models import ControlCommand, ControlReply
from app.control_plane.processor_base import ControlProcessor
from octopus_sdk.exact_aliases import matches_exact_alias
from octopus_sdk.registry.client import RegistryClientError
from app.control_plane.requests import (
    AddConversationMessagePayload,
    GetConversationRequest,
    GetTaskRequest,
    ListConversationEventsRequest,
    PublishHealthRequest,
    ReportTaskResultPayload,
    ResolveTargetAuthorityRequest,
    SearchAgentsRequest,
    SubmitRoutedTaskPayload,
    SubmitConversationActionPayload,
    TimelineEventPayload,
    UpdateRoutedTaskStatusPayload,
)
from octopus_sdk.agent_directory import AgentSearchResult, AuthorityResolution
from octopus_sdk.registry.models import (
    AgentDiscoveryQuery,
    DiscoveredAgentRef,
    CoordinationActionEnvelope,
    RoutedTaskRequest,
    RoutedTaskResult,
    RoutedTaskUpdate,
)
from octopus_sdk.task_routing import TaskResultReport, TaskSubmissionResult
from octopus_sdk.config import RegistryConnectionConfig

log = logging.getLogger(__name__)


class RegistryControlAccess(Protocol):
    @property
    def registries(self) -> tuple[RegistryConnectionConfig, ...]: ...

    def client_for_registry(self, registry_id: str): ...

    def origin_agent_id(self, registry_id: str) -> str: ...


class RegistryControlProcessor(ControlProcessor):
    def __init__(self, registry_access: RegistryControlAccess) -> None:
        self._access = registry_access

    def authority_capabilities(self) -> dict[str, set[str]]:
        return registry_authority_capabilities(self._access.registries)

    async def process(self, command: ControlCommand) -> ControlReply:
        try:
            registry_id = registry_id_from_authority_ref(command.authority_ref)
        except ValueError as exc:
            return ControlReply(command_id=command.command_id, status="failed", error=str(exc))
        client = self._access.client_for_registry(registry_id)
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
            if command.capability == "registry_inspection":
                return await self._process_registry_inspection(command, client)
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
                result_json=response.model_dump_json(),
            )
        if command.operation == "get_conversation":
            payload = json.loads(command.payload_json)
            response = await client.get_conversation(payload["conversation_id"])
            return ControlReply(
                command_id=command.command_id,
                status="completed",
                result_json=response.model_dump_json(),
            )
        if command.operation == "publish_events":
            payload = json.loads(command.payload_json)
            conversation_id = payload["conversation_id"]
            from octopus_sdk.events import ConversationEvent as SdkConversationEvent
            events = [SdkConversationEvent.model_validate(e) for e in payload["events"]]
            await client.publish_events(conversation_id, events)
            return ControlReply(command_id=command.command_id, status="completed")
        if command.operation == "add_message":
            payload = AddConversationMessagePayload.model_validate_json(command.payload_json)
            response = await client.add_message(payload.conversation_id, payload.text)
            return ControlReply(
                command_id=command.command_id,
                status="completed",
                result_json=response.model_dump_json(),
            )
        if command.operation == "submit_action":
            payload = SubmitConversationActionPayload.model_validate_json(command.payload_json)
            response = await client.submit_action(
                payload.conversation_id,
                payload.envelope,
            )
            return ControlReply(
                command_id=command.command_id,
                status="completed",
                result_json=response.model_dump_json(),
            )
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
                result_json=response.model_dump_json(),
            )
        if command.operation == "publish_events":
            payload = json.loads(command.payload_json)
            conversation_id = payload["conversation_id"]
            from octopus_sdk.events import ConversationEvent as SdkConversationEvent
            events = [SdkConversationEvent.model_validate(e) for e in payload["events"]]
            await client.publish_events(conversation_id, events)
            return ControlReply(command_id=command.command_id, status="completed")
        if command.operation == "add_message":
            payload = AddConversationMessagePayload.model_validate_json(command.payload_json)
            response = await client.add_message(payload.conversation_id, payload.text)
            return ControlReply(
                command_id=command.command_id,
                status="completed",
                result_json=response.model_dump_json(),
            )
        if command.operation == "submit_action":
            payload = SubmitConversationActionPayload.model_validate_json(command.payload_json)
            response = await client.submit_action(
                payload.conversation_id,
                payload.envelope,
            )
            return ControlReply(
                command_id=command.command_id,
                status="completed",
                result_json=response.model_dump_json(),
            )
        return ControlReply(
            command_id=command.command_id,
            status="failed",
            error=f"unsupported mirror_retry operation {command.operation!r}",
        )

    async def _process_task_routing(self, command: ControlCommand, client) -> ControlReply:
        if command.operation == "submit_routed_task":
            payload = SubmitRoutedTaskPayload.model_validate_json(command.payload_json)
            request = RoutedTaskRequest.model_validate(payload.model_dump(mode="json"))
            response = await client.submit_routed_task(request)
            return ControlReply(
                command_id=command.command_id,
                status="completed",
                result_json=TaskSubmissionResult(
                    status="accepted",
                    routed_task_id=response.routed_task_id or payload.routed_task_id,
                    delivery_id=response.delivery_id,
                ).model_dump_json(),
            )
        if command.operation == "report_routed_task_result":
            payload = ReportTaskResultPayload.model_validate_json(command.payload_json)
            log.warning(
                "control.report_routed_task_result routed_task_id=%s status=%s provider=%s working_dir=%r artifact_count=%d",
                payload.routed_task_id,
                payload.status,
                payload.provider,
                payload.working_dir,
                len(payload.artifacts),
            )
            result = RoutedTaskResult.model_validate(payload.model_dump(mode="json"))
            response = await client.routed_task_result(payload.routed_task_id, result)
            return ControlReply(
                command_id=command.command_id,
                status="completed",
                result_json=TaskResultReport(
                    status="reported",
                    routed_task_id=response.routed_task_id or payload.routed_task_id,
                ).model_dump_json(),
            )
        if command.operation == "update_routed_task_status":
            payload = UpdateRoutedTaskStatusPayload.model_validate_json(command.payload_json)
            update = RoutedTaskUpdate.model_validate(payload.model_dump(mode="json"))
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
            query = AgentDiscoveryQuery.model_validate(request.model_dump(mode="json"))
            rows = await client.search(query)
            agents = [
                DiscoveredAgentRef.model_validate(
                    {
                        "authority_ref": command.authority_ref,
                        **row.model_dump(
                            mode="json",
                            include={
                                "agent_id",
                                "display_name",
                                "slug",
                                "role",
                                "routing_skills",
                                "tags",
                                "description",
                                "connectivity_state",
                                "current_capacity",
                                "max_capacity",
                            },
                        ),
                    }
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
            local_agent_id = self._access.origin_agent_id(registry_id)
            query = AgentDiscoveryQuery(
                required_state="connected",
                exclude_agent_ids=[local_agent_id] if local_agent_id else [],
            )
            rows = await client.search(query)
            for row in rows:
                if matches_exact_alias(
                    request.target_agent_id,
                    identifier=row.agent_id,
                    slug=row.slug,
                    display_name=row.display_name,
                ):
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

    async def _process_registry_inspection(self, command: ControlCommand, client) -> ControlReply:
        if command.operation == "get_conversation":
            request = GetConversationRequest.model_validate_json(command.payload_json)
            record = await client.get_conversation(request.conversation_id)
            return ControlReply(
                command_id=command.command_id,
                status="completed",
                result_json=record.model_dump_json(),
            )
        if command.operation == "get_task":
            request = GetTaskRequest.model_validate_json(command.payload_json)
            record = await client.get_task(request.routed_task_id)
            return ControlReply(
                command_id=command.command_id,
                status="completed",
                result_json=record.model_dump_json(),
            )
        if command.operation == "list_events":
            request = ListConversationEventsRequest.model_validate_json(command.payload_json)
            record = await client.list_events(
                request.conversation_id,
                kind=request.kind,
                before_seq=request.before_seq,
                after_seq=request.after_seq,
                limit=request.limit,
            )
            return ControlReply(
                command_id=command.command_id,
                status="completed",
                result_json=record.model_dump_json(),
            )
        return ControlReply(
            command_id=command.command_id,
            status="failed",
            error=f"unsupported registry_inspection operation {command.operation!r}",
        )
