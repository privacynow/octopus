"""HTTP client for bot -> registry communication.

Methods are async (HTTP I/O). This does not imply the registry store should be
async — the client and store run in different processes.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, TypeVar

import httpx
from pydantic import BaseModel

from octopus_sdk.events import ConversationEvent, validate_event_metadata
from octopus_sdk.protocols import (
    ProtocolAuthoringManifestRecord,
    ProtocolDefinitionDiffRecord,
    ProtocolDefinitionDocumentRecord,
    ProtocolDefinitionRecord,
    ProtocolDefinitionVersionRecord,
    ProtocolDraftCreateRecord,
    ProtocolMutationRecord,
    ProtocolIssueRecord,
    ProtocolTextDocumentRecord,
    ProtocolRunExportRecord,
    ProtocolRunCreateRecord,
    ProtocolRunDetailRecord,
    ProtocolRunMutationRecord,
    ProtocolRunParticipantRecord,
    ProtocolRunRecord,
    ProtocolTransitionRecord,
    ProtocolArtifactRecord,
    ProtocolInvocationPort,
    ProtocolObservationPort,
)
from octopus_sdk.registry.management import ManagementResult
from octopus_sdk.registry.models import (
    AckResult,
    AgentCard,
    AgentDiscoveryQuery,
    AgentRecord,
    CoordinationActionEnvelope,
    CoordinationActionResult,
    ConversationCreate,
    ConversationRecord,
    ConversationProgressUpdate,
    DeliveryPollResult,
    EnrollmentResult,
    EventPageRecord,
    HealthSummary,
    MessageRecord,
    RuntimeHealthPayload,
    RoutedTaskRequest,
    RoutedTaskResult,
    TaskRecord,
    RoutedTaskUpdate,
)

ModelT = TypeVar("ModelT", bound=BaseModel)
ProtocolRegistryErrorCode = Literal[
    "PROTOCOL_NOT_FOUND",
    "PROTOCOL_NOT_VISIBLE",
    "PROTOCOL_FORBIDDEN",
    "PROTOCOL_DUPLICATE_SLUG",
    "PROTOCOL_INVALID_ACTION",
    "PROTOCOL_INVALID",
    "PROTOCOL_INVALID_FILTER",
    "PROTOCOL_INVALID_FORMAT",
    "PROTOCOL_INVALID_IF_MATCH",
    "PROTOCOL_RUN_NOT_FOUND",
    "PROTOCOL_VERSION_NOT_FOUND",
    "PROTOCOL_EXPORT_FORBIDDEN",
    "PROTOCOL_INVALID_TRANSITION",
    "LEASE_HELD",
    "MAX_REVIEW_ROUNDS_EXCEEDED",
    "ARTIFACT_VERIFICATION_FAILED",
    "CONCURRENT_MODIFICATION",
    "IDEMPOTENCY_REPLAY",
    "PROTOCOL_REQUEST_FAILED",
]
PROTOCOL_REGISTRY_ERROR_CODES = frozenset[str]({
    "PROTOCOL_NOT_FOUND",
    "PROTOCOL_NOT_VISIBLE",
    "PROTOCOL_FORBIDDEN",
    "PROTOCOL_DUPLICATE_SLUG",
    "PROTOCOL_INVALID_ACTION",
    "PROTOCOL_INVALID",
    "PROTOCOL_INVALID_FILTER",
    "PROTOCOL_INVALID_FORMAT",
    "PROTOCOL_INVALID_IF_MATCH",
    "PROTOCOL_RUN_NOT_FOUND",
    "PROTOCOL_VERSION_NOT_FOUND",
    "PROTOCOL_EXPORT_FORBIDDEN",
    "PROTOCOL_INVALID_TRANSITION",
    "LEASE_HELD",
    "MAX_REVIEW_ROUNDS_EXCEEDED",
    "ARTIFACT_VERIFICATION_FAILED",
    "CONCURRENT_MODIFICATION",
    "IDEMPOTENCY_REPLAY",
    "PROTOCOL_REQUEST_FAILED",
})


class RegistryClientError(RuntimeError):
    """Raised when the registry returns a non-success response."""

    def __init__(
        self,
        message: str,
        *,
        error_code: str = "registry_request_failed",
        operator_detail: str = "",
        details: object | None = None,
        status_code: int | None = None,
    ) -> None:
        self.error_code = error_code
        self.operator_detail = operator_detail or message
        self.details = details
        self.status_code = status_code
        super().__init__(message)

    @property
    def is_protocol_error(self) -> bool:
        return str(self.error_code or "").upper() in PROTOCOL_REGISTRY_ERROR_CODES


def _registry_http_error_code(status_code: int) -> str:
    if status_code in {401, 403}:
        return "registry_auth_failed"
    if status_code in {408, 504}:
        return "registry_timeout"
    if status_code >= 500:
        return "registry_server_error"
    return "registry_request_failed"


def _detail_error_payload(value: object) -> tuple[str, str, object | None]:
    if isinstance(value, dict):
        error_code = str(value.get("error_code", "") or "").strip()
        message = str(value.get("message", "") or "").strip()
        if error_code or message:
            return error_code or "registry_request_failed", message or "Registry request failed.", value.get("details")
    return "", "", None


def _validated_model(
    value: ModelT | Mapping[str, object],
    schema: type[ModelT],
) -> ModelT:
    if isinstance(value, schema):
        return value
    return schema.model_validate(dict(value))


class RegistryClient(ProtocolInvocationPort, ProtocolObservationPort):
    """Async HTTP client wrapping the registry's /v1/ endpoints."""

    def __init__(
        self,
        base_url: str,
        agent_token: str = "",
        *,
        timeout_seconds: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._agent_token = agent_token
        self._timeout_seconds = timeout_seconds
        self._client = client

    def _headers(self, *, require_auth: bool) -> dict[str, str]:
        headers: dict[str, str] = {}
        if require_auth:
            if not self._agent_token:
                raise RegistryClientError(
                    "Missing agent token for authenticated registry call",
                    error_code="registry_auth_failed",
                    operator_detail="Authenticated registry call attempted without an agent token.",
                )
            headers["Authorization"] = f"Bearer {self._agent_token}"
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        *,
        require_auth: bool = True,
        extra_headers: Mapping[str, str] | None = None,
        **kwargs: object,
    ) -> object:
        headers = self._headers(require_auth=require_auth)
        if extra_headers:
            headers.update({str(key): str(value) for key, value in extra_headers.items() if str(value or "").strip()})

        async def _do(client: httpx.AsyncClient) -> object:
            try:
                response = await client.request(
                    method,
                    f"{self._base_url}{path}",
                    headers=headers,
                    **kwargs,
                )
            except httpx.TimeoutException as exc:
                raise RegistryClientError(
                    f"Registry {method} {path} timed out",
                    error_code="registry_timeout",
                    operator_detail=f"Registry {method} {path} timed out ({exc.__class__.__name__}).",
                ) from exc
            except httpx.RequestError as exc:
                raise RegistryClientError(
                    f"Registry {method} {path} failed",
                    error_code="registry_unreachable",
                    operator_detail=(
                        f"Registry {method} {path} failed with {exc.__class__.__name__}."
                    ),
                ) from exc
            if response.status_code >= 400:
                payload: object = {}
                if response.headers.get("content-type", "").startswith("application/json"):
                    try:
                        payload = response.json().get("detail", response.json())
                    except Exception:
                        payload = {}
                error_code, message, details = _detail_error_payload(payload)
                raise RegistryClientError(
                    message or f"Registry {method} {path} failed: HTTP {response.status_code}",
                    error_code=error_code or _registry_http_error_code(response.status_code),
                    operator_detail=(
                        message
                        or f"Registry {method} {path} failed with HTTP {response.status_code}."
                    ),
                    details=details,
                    status_code=response.status_code,
                )
            if response.status_code == 204 or not response.content:
                return {}
            if response.headers.get("content-type", "").startswith("application/json"):
                return response.json()
            return response.text

        if self._client is not None:
            return await _do(self._client)
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            return await _do(client)

    async def create_conversation(
        self,
        *,
        target_agent_id: str,
        origin_channel: str,
        external_conversation_ref: str,
        title: str = "",
    ) -> ConversationRecord:
        """Idempotent get-or-create. Returns { conversation_id, ... }."""
        payload = ConversationCreate(
            target_agent_id=target_agent_id,
            origin_channel=origin_channel,
            external_conversation_ref=external_conversation_ref,
            title=title,
        )
        result = await self._request("POST", "/v1/conversations", json=payload.model_dump())
        return ConversationRecord.model_validate(result)

    async def get_conversation(self, conversation_id: str) -> ConversationRecord:
        result = await self._request("GET", f"/v1/conversations/{conversation_id}")
        return ConversationRecord.model_validate(result)

    async def list_events(
        self,
        conversation_id: str,
        *,
        kind: str = "",
        before_seq: int = 0,
        after_seq: int = 0,
        limit: int = 50,
    ) -> EventPageRecord:
        result = await self._request(
            "GET",
            f"/v1/conversations/{conversation_id}/events",
            params={
                "kind": kind,
                "before_seq": before_seq,
                "after_seq": after_seq,
                "limit": limit,
            },
        )
        return EventPageRecord.model_validate(result)

    async def add_message(self, conversation_id: str, text: str) -> MessageRecord:
        result = await self._request(
            "POST",
            f"/v1/conversations/{conversation_id}/messages",
            json={"text": text},
        )
        return MessageRecord.model_validate(result)

    async def submit_action(
        self,
        conversation_id: str,
        envelope: CoordinationActionEnvelope,
    ) -> CoordinationActionResult:
        payload = _validated_model(envelope, CoordinationActionEnvelope)
        result = await self._request(
            "POST",
            f"/v1/conversations/{conversation_id}/actions",
            json=payload.model_dump(exclude_unset=True),
        )
        return CoordinationActionResult.model_validate(result)

    async def get_agent_status(self, agent_id: str) -> AgentRecord:
        result = await self._request("GET", f"/v1/agents/{agent_id}/status")
        return AgentRecord.model_validate(result)

    async def list_protocols(
        self,
        *,
        cursor: int = 0,
        limit: int = 50,
        lifecycle_state: str = "",
        slug: str = "",
        created_after: str = "",
    ) -> list[ProtocolDefinitionRecord]:
        result = await self._request(
            "GET",
            "/v1/protocols",
            params={
                "cursor": cursor,
                "limit": limit,
                "lifecycle_state": lifecycle_state,
                "slug": slug,
                "created_after": created_after,
            },
        )
        return [ProtocolDefinitionRecord.model_validate(item) for item in result]

    async def get_protocol_template(self, slug: str) -> ProtocolDefinitionDocumentRecord:
        result = await self._request("GET", f"/v1/protocol-templates/{slug}")
        return ProtocolDefinitionDocumentRecord.model_validate(result)

    async def get_protocol_authoring_manifest(self) -> ProtocolAuthoringManifestRecord:
        result = await self._request("GET", "/v1/protocol-authoring/manifest")
        return ProtocolAuthoringManifestRecord.model_validate(result)

    async def get_protocol(self, protocol_id: str) -> ProtocolMutationRecord:
        result = await self._request("GET", f"/v1/protocols/{protocol_id}")
        return ProtocolMutationRecord.model_validate(result)

    async def get_protocol_version(self, protocol_id: str, version_id: str) -> ProtocolDefinitionVersionRecord:
        result = await self._request("GET", f"/v1/protocols/{protocol_id}/versions/{version_id}")
        return ProtocolDefinitionVersionRecord.model_validate(result)

    async def save_protocol(
        self,
        *,
        protocol_id: str = "",
        slug: str,
        display_name: str,
        description: str,
        definition_json: dict[str, object],
    ) -> ProtocolMutationRecord:
        payload = {
            "protocol_id": protocol_id,
            "slug": slug,
            "display_name": display_name,
            "description": description,
            "definition_json": definition_json,
        }
        if protocol_id:
            result = await self._request("PUT", f"/v1/protocols/{protocol_id}/draft", json=payload)
        else:
            result = await self._request("POST", "/v1/protocols", json=payload)
        return ProtocolMutationRecord.model_validate(result)

    async def create_protocol_draft(
        self,
        payload: ProtocolDraftCreateRecord,
    ) -> ProtocolMutationRecord:
        result = await self._request(
            "POST",
            "/v1/protocol-drafts",
            json=payload.model_dump(exclude_unset=True),
        )
        return ProtocolMutationRecord.model_validate(result)

    async def delete_protocol(self, protocol_id: str) -> ProtocolMutationRecord:
        result = await self._request("DELETE", f"/v1/protocols/{protocol_id}")
        return ProtocolMutationRecord.model_validate(result)

    async def validate_protocol(self, protocol_id: str) -> ProtocolMutationRecord:
        result = await self._request("POST", f"/v1/protocols/{protocol_id}/validate", json={})
        return ProtocolMutationRecord.model_validate(result)

    async def publish_protocol(self, protocol_id: str) -> ProtocolMutationRecord:
        result = await self._request("POST", f"/v1/protocols/{protocol_id}/publish", json={})
        return ProtocolMutationRecord.model_validate(result)

    async def archive_protocol(self, protocol_id: str) -> ProtocolMutationRecord:
        result = await self._request("POST", f"/v1/protocols/{protocol_id}/archive", json={})
        return ProtocolMutationRecord.model_validate(result)

    async def parse_protocol_document_text(
        self,
        *,
        definition_text: str,
        format: str = "json",
        validation_mode: str = "strict",
    ) -> ProtocolTextDocumentRecord:
        result = await self._request(
            "POST",
            "/v1/protocols/parse",
            json={
                "definition_text": definition_text,
                "format": format,
                "validation_mode": validation_mode,
            },
        )
        return ProtocolTextDocumentRecord.model_validate(result)

    async def export_protocol_draft(
        self,
        protocol_id: str,
        *,
        format: str = "json",
    ) -> ProtocolTextDocumentRecord:
        result = await self._request(
            "GET",
            f"/v1/protocols/{protocol_id}/draft/export",
            params={"format": format},
        )
        return ProtocolTextDocumentRecord.model_validate(result)

    async def diff_protocol_draft(
        self,
        protocol_id: str,
        *,
        format: str = "json",
    ) -> ProtocolDefinitionDiffRecord:
        result = await self._request(
            "GET",
            f"/v1/protocols/{protocol_id}/diff",
            params={"format": format},
        )
        return ProtocolDefinitionDiffRecord.model_validate(result)

    async def list_runs(
        self,
        *,
        cursor: int = 0,
        limit: int = 25,
        status: str = "",
        protocol_id: str = "",
        entry_agent_id: str = "",
        origin_channel: str = "",
    ) -> list[ProtocolRunRecord]:
        result = await self._request(
            "GET",
            "/v1/protocol-runs",
            params={
                "cursor": cursor,
                "limit": limit,
                "status": status,
                "protocol_id": protocol_id,
                "entry_agent_id": entry_agent_id,
                "origin_channel": origin_channel,
            },
        )
        rows = result.get("runs", result)
        return [ProtocolRunRecord.model_validate(item) for item in rows]

    async def invoke_protocol(
        self,
        payload: ProtocolRunCreateRecord | dict[str, object],
        *,
        idempotency_key: str = "",
        origin: str = "",
    ) -> ProtocolRunMutationRecord:
        del origin
        body = _validated_model(payload, ProtocolRunCreateRecord).model_dump(mode="json")
        result = await self._request(
            "POST",
            "/v1/protocol-runs",
            json=body,
            extra_headers={"Idempotency-Key": idempotency_key} if idempotency_key else None,
        )
        return ProtocolRunMutationRecord.model_validate(result)

    async def list_run_issues(
        self,
        *,
        cursor: int = 0,
        limit: int = 25,
        issue_kind: str = "",
        protocol_run_id: str = "",
        protocol_id: str = "",
    ) -> list[ProtocolIssueRecord]:
        result = await self._request(
            "GET",
            "/v1/protocol-runs/issues",
            params={
                "cursor": cursor,
                "limit": limit,
                "issue_kind": issue_kind,
                "protocol_run_id": protocol_run_id,
                "protocol_id": protocol_id,
            },
        )
        rows = result.get("issues", result)
        return [ProtocolIssueRecord.model_validate(item) for item in rows]

    async def get_run(self, run_id: str) -> ProtocolRunDetailRecord:
        result = await self._request("GET", f"/v1/protocol-runs/{run_id}")
        return ProtocolRunDetailRecord.model_validate(result)

    async def list_run_participants(self, run_id: str) -> list[ProtocolRunParticipantRecord]:
        result = await self._request("GET", f"/v1/protocol-runs/{run_id}/participants")
        rows = result.get("participants", result)
        return [ProtocolRunParticipantRecord.model_validate(item) for item in rows]

    async def list_run_artifacts(self, run_id: str) -> list[ProtocolArtifactRecord]:
        result = await self._request("GET", f"/v1/protocol-runs/{run_id}/artifacts")
        rows = result.get("artifacts", result)
        return [ProtocolArtifactRecord.model_validate(item) for item in rows]

    async def list_run_timeline(self, run_id: str) -> list[ProtocolTransitionRecord]:
        result = await self._request("GET", f"/v1/protocol-runs/{run_id}/timeline")
        rows = result.get("transitions", result)
        return [ProtocolTransitionRecord.model_validate(item) for item in rows]

    async def export_run(self, run_id: str) -> ProtocolRunExportRecord:
        result = await self._request("GET", f"/v1/protocol-runs/{run_id}/export")
        return ProtocolRunExportRecord.model_validate(result)

    async def act_on_protocol_run(
        self,
        run_id: str,
        *,
        action: str,
        reason: str = "",
        idempotency_key: str = "",
        expected_version: int | None = None,
    ) -> ProtocolRunMutationRecord:
        headers: dict[str, str] = {}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        if expected_version is not None:
            headers["If-Match"] = str(expected_version)
        result = await self._request(
            "POST",
            f"/v1/protocol-runs/{run_id}/actions/{action}",
            json={"reason": reason},
            extra_headers=headers or None,
        )
        return ProtocolRunMutationRecord.model_validate(result)

    async def publish_events(
        self,
        conversation_id: str,
        events: list[ConversationEvent],
    ) -> None:
        """Publish events to a conversation. Idempotent on event_id."""
        validated_events = [
            event.model_copy(update={"metadata": validate_event_metadata(event)})
            for event in events
        ]
        await self._request(
            "POST",
            f"/v1/conversations/{conversation_id}/events",
            json={"events": [event.model_dump() for event in validated_events]},
        )

    async def publish_progress(
        self,
        conversation_id: str,
        progress: ConversationProgressUpdate,
    ) -> None:
        payload = _validated_model(progress, ConversationProgressUpdate)
        await self._request(
            "POST",
            f"/v1/conversations/{conversation_id}/progress",
            json=payload.model_dump(),
        )

    async def enroll(
        self,
        enrollment_token: str,
        card: AgentCard,
    ) -> EnrollmentResult:
        """Enroll a new agent. No bearer token needed — uses enrollment_token in body."""
        agent_card = _validated_model(card, AgentCard)
        result = await self._request(
            "POST",
            "/v1/agents/enroll",
            json={
                "enrollment_token": enrollment_token,
                "agent_card": agent_card.model_dump(exclude_unset=True),
            },
            require_auth=False,
        )
        return EnrollmentResult.model_validate(result)

    async def register(
        self,
        card: AgentCard,
        *,
        connectivity_state: str,
        current_capacity: int,
        max_capacity: int,
    ) -> HealthSummary:
        agent_card = _validated_model(card, AgentCard)
        payload = {
            "agent_card": agent_card.model_dump(exclude_unset=True),
            "connectivity_state": connectivity_state,
            "current_capacity": current_capacity,
            "max_capacity": max_capacity,
        }
        result = await self._request("POST", "/v1/agents/register", json=payload)
        return HealthSummary.model_validate(result)

    async def heartbeat(
        self,
        *,
        connectivity_state: str,
        current_capacity: int,
        max_capacity: int,
        runtime_health: RuntimeHealthPayload | None = None,
    ) -> HealthSummary:
        payload: dict[str, object] = {
            "connectivity_state": connectivity_state,
            "current_capacity": current_capacity,
            "max_capacity": max_capacity,
        }
        if runtime_health is not None:
            payload["runtime_health"] = _validated_model(
                runtime_health,
                RuntimeHealthPayload,
            ).model_dump(exclude_unset=True)
        result = await self._request("POST", "/v1/agents/heartbeat", json=payload)
        return HealthSummary.model_validate(result)

    async def search(
        self,
        query: AgentDiscoveryQuery,
    ) -> list[AgentRecord]:
        payload = _validated_model(query, AgentDiscoveryQuery)
        result = await self._request(
            "POST",
            "/v1/agents/discovery/search",
            json=payload.model_dump(exclude_unset=True),
        )
        return [AgentRecord.model_validate(item) for item in list(result.get("agents", []))]

    async def get_task(self, routed_task_id: str) -> TaskRecord:
        result = await self._request("GET", f"/v1/tasks/{routed_task_id}")
        return TaskRecord.model_validate(result)

    async def submit_routed_task(
        self,
        request: RoutedTaskRequest,
    ) -> TaskRecord:
        payload = _validated_model(request, RoutedTaskRequest)
        body = payload.model_dump(exclude_unset=True)
        # created_at is server-visible request identity and must survive the client dump
        # even when populated by the model default.
        body["created_at"] = payload.created_at
        result = await self._request(
            "POST",
            "/v1/agents/routed-tasks",
            json=body,
        )
        return TaskRecord.model_validate(result)

    async def routed_task_status(
        self,
        routed_task_id: str,
        update: RoutedTaskUpdate,
    ) -> TaskRecord:
        payload = _validated_model(update, RoutedTaskUpdate)
        body = payload.model_dump(exclude_unset=True)
        # The routed task id is carried in the URL path; the registry rejects it in the body.
        body.pop("routed_task_id", None)
        body["updated_at"] = payload.updated_at
        body["transition_id"] = payload.transition_id
        result = await self._request(
            "POST",
            f"/v1/agents/routed-tasks/{routed_task_id}/status",
            json=body,
        )
        return TaskRecord.model_validate(result)

    async def routed_task_result(
        self,
        routed_task_id: str,
        result: RoutedTaskResult,
    ) -> TaskRecord:
        payload = _validated_model(result, RoutedTaskResult)
        body = payload.model_dump(exclude_unset=True)
        # The routed task id is carried in the URL path; the registry rejects it in the body.
        body.pop("routed_task_id", None)
        body["completed_at"] = payload.completed_at
        body["transition_id"] = payload.transition_id
        response = await self._request(
            "POST",
            f"/v1/agents/routed-tasks/{routed_task_id}/result",
            json=body,
        )
        return TaskRecord.model_validate(response)

    async def management_result(
        self,
        request_id: str,
        result: ManagementResult,
    ) -> ManagementResult:
        payload = _validated_model(result, ManagementResult)
        body = payload.model_dump(by_alias=True)
        response = await self._request(
            "POST",
            f"/v1/agents/management-requests/{request_id}/result",
            json=body,
        )
        return ManagementResult.model_validate(response)

    async def poll(
        self,
        *,
        cursor: str = "0",
        limit: int = 20,
        wait_seconds: int = 1,
        kind_filter: list[str] | tuple[str, ...] | None = None,
    ) -> DeliveryPollResult:
        params: dict[str, object] = {
            "cursor": cursor,
            "limit": limit,
            "wait_seconds": wait_seconds,
        }
        if kind_filter is not None:
            params["kind_filter"] = list(kind_filter)
        result = await self._request("GET", "/v1/agents/poll", params=params)
        return DeliveryPollResult.model_validate(result)

    async def ack(self, delivery_ids: list[str], classification: str = "accepted") -> AckResult:
        result = await self._request("POST", "/v1/agents/ack", json={
            "delivery_ids": delivery_ids,
            "classification": classification,
        })
        return AckResult.model_validate(result)

    async def deregister(self) -> AgentRecord:
        result = await self._request("POST", "/v1/agents/deregister", json={})
        return AgentRecord.model_validate(result)

    async def renew_enrollment(
        self,
        agent_id: str,
        card: AgentCard,
    ) -> EnrollmentResult:
        del agent_id
        agent_card = _validated_model(card, AgentCard)
        summary = await self.register(
            agent_card,
            connectivity_state=agent_card.connectivity_state or "connected",
            current_capacity=agent_card.current_capacity,
            max_capacity=agent_card.max_capacity,
        )
        agent = summary.agent
        return EnrollmentResult(
            agent_id=agent.agent_id if agent is not None else "",
            agent_token=self._agent_token,
            slug=agent.slug if agent is not None else agent_card.slug,
            poll_cursor="0",
        )

    async def disconnect_agent(self, agent_id: str) -> AgentRecord:
        return await self.deregister()

    async def fail_delivery(self, delivery_id: str, reason: str = "") -> AckResult:
        return await self.ack([delivery_id], classification="rejected")
