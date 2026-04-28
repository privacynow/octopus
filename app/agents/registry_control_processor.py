"""Registry-backed control-plane command processor."""

from __future__ import annotations

import json
import uuid
from typing import Any, Protocol

from app.agents.registry_projection_interfaces import (
    registry_projection_interfaces_by_implementation_ref,
    registry_id_from_implementation_ref,
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

class RegistryControlAccess(Protocol):
    @property
    def registries(self) -> tuple[RegistryConnectionConfig, ...]: ...

    def client_for_registry(self, registry_id: str): ...

    def origin_agent_id(self, registry_id: str) -> str: ...


class RegistryControlProcessor(ControlProcessor):
    def __init__(self, registry_access: RegistryControlAccess) -> None:
        self._access = registry_access

    def implemented_admin_interfaces(self) -> dict[str, set[str]]:
        return registry_projection_interfaces_by_implementation_ref(self._access.registries)

    async def process(self, command: ControlCommand) -> ControlReply:
        try:
            registry_id = registry_id_from_implementation_ref(command.implementation_ref)
        except ValueError as exc:
            return ControlReply(command_id=command.command_id, status="failed", error=str(exc))
        client = self._access.client_for_registry(registry_id)
        if client is None:
            return ControlReply(
                command_id=command.command_id,
                status="failed",
                error=f"no registry client for {command.implementation_ref}",
            )

        try:
            if command.admin_interface == "conversation_projection":
                return await self._process_conversation_projection(command, client)
            if command.admin_interface == "task_routing":
                return await self._process_task_routing(command, client)
            if command.admin_interface == "agent_directory":
                return await self._process_agent_directory(command, client, registry_id)
            if command.admin_interface == "health_publication":
                return await self._process_health_publication(command, client)
            if command.admin_interface == "registry_inspection":
                return await self._process_registry_inspection(command, client)
            return ControlReply(
                command_id=command.command_id,
                status="failed",
                error=f"unsupported control-plane admin_interface {command.admin_interface!r}",
            )
        except RegistryClientError as exc:
            return ControlReply(
                command_id=command.command_id,
                status="failed",
                error=exc.operator_detail or str(exc),
            )

    async def _process_conversation_projection(self, command: ControlCommand, client) -> ControlReply:
        if command.admin_operation == "create_conversation":
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
        if command.admin_operation == "get_conversation":
            payload = json.loads(command.payload_json)
            response = await client.get_conversation(payload["conversation_id"])
            return ControlReply(
                command_id=command.command_id,
                status="completed",
                result_json=response.model_dump_json(),
            )
        if command.admin_operation == "publish_events":
            payload = json.loads(command.payload_json)
            conversation_id = payload["conversation_id"]
            from octopus_sdk.events import ConversationEvent as SdkConversationEvent
            events = [SdkConversationEvent.model_validate(e) for e in payload["events"]]
            await client.publish_events(conversation_id, events)
            return ControlReply(command_id=command.command_id, status="completed")
        if command.admin_operation == "add_message":
            payload = AddConversationMessagePayload.model_validate_json(command.payload_json)
            response = await client.add_message(payload.conversation_id, payload.text)
            return ControlReply(
                command_id=command.command_id,
                status="completed",
                result_json=response.model_dump_json(),
            )
        if command.admin_operation == "submit_action":
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
            error=f"unsupported conversation_projection admin_operation {command.admin_operation!r}",
        )

    async def _process_task_routing(self, command: ControlCommand, client) -> ControlReply:
        if command.admin_operation == "submit_routed_task":
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
        if command.admin_operation == "report_routed_task_result":
            payload = ReportTaskResultPayload.model_validate_json(command.payload_json)
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
        if command.admin_operation == "update_routed_task_status":
            payload = UpdateRoutedTaskStatusPayload.model_validate_json(command.payload_json)
            update = RoutedTaskUpdate.model_validate(payload.model_dump(mode="json"))
            await client.routed_task_status(payload.routed_task_id, update)
            return ControlReply(command_id=command.command_id, status="completed")
        return ControlReply(
            command_id=command.command_id,
            status="failed",
            error=f"unsupported task_routing admin_operation {command.admin_operation!r}",
        )

    async def _process_agent_directory(self, command: ControlCommand, client, registry_id: str) -> ControlReply:
        if command.admin_operation == "search_agents":
            request = SearchAgentsRequest.model_validate_json(command.payload_json)
            query = AgentDiscoveryQuery.model_validate(request.model_dump(mode="json"))
            rows = await client.search(query)
            agents = [
                DiscoveredAgentRef.model_validate(
                    {
                        "authority_ref": command.implementation_ref,
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
        if command.admin_operation == "resolve_target_authority":
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
                            authority_ref=command.implementation_ref,
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
            error=f"unsupported agent_directory admin_operation {command.admin_operation!r}",
        )

    async def _process_health_publication(self, command: ControlCommand, client) -> ControlReply:
        if command.admin_operation != "publish_health":
            return ControlReply(
                command_id=command.command_id,
                status="failed",
                error=f"unsupported health_publication admin_operation {command.admin_operation!r}",
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
        if command.admin_operation == "get_conversation":
            request = GetConversationRequest.model_validate_json(command.payload_json)
            record = await client.get_conversation(request.conversation_id)
            return ControlReply(
                command_id=command.command_id,
                status="completed",
                result_json=record.model_dump_json(),
            )
        if command.admin_operation == "get_task":
            request = GetTaskRequest.model_validate_json(command.payload_json)
            record = await client.get_task(request.routed_task_id)
            return ControlReply(
                command_id=command.command_id,
                status="completed",
                result_json=record.model_dump_json(),
            )
        if command.admin_operation == "list_events":
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
            error=f"unsupported registry_inspection admin_operation {command.admin_operation!r}",
        )
