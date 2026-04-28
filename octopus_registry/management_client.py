"""Registry-side management client for connected bots."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from .store_base import AbstractRegistryStore
from octopus_sdk.registry.management import (
    ManagementRequest,
    ManagementRequestPayload,
    ManagementResult,
    ManagementResultPayload,
    management_operation_supported,
)


class ManagementClientError(RuntimeError):
    def __init__(self, *, status_code: int, error_code: str, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.error_code = error_code
        self.detail = detail


@dataclass(frozen=True)
class RegistryManagementClient:
    store: AbstractRegistryStore

    def _agent_status(self, agent_id: str):
        status = self.store.get_agent_status(agent_id)
        if status is None:
            raise ManagementClientError(
                status_code=404,
                error_code="unknown_agent",
                detail=f"Unknown agent: {agent_id}",
            )
        return status

    def _assert_available(self, agent_id: str, operation: str) -> None:
        status = self._agent_status(agent_id)
        connectivity_state = str(status.connectivity_state or "")
        if connectivity_state not in {"connected", "degraded"}:
            raise ManagementClientError(
                status_code=503,
                error_code="agent_not_connected",
                detail=f"Agent {agent_id} is not connected.",
            )
        if not management_operation_supported(
            status.supported_admin_operations,
            operation,
        ):
            raise ManagementClientError(
                status_code=409,
                error_code="admin_operation_not_implemented",
                detail=f"Agent {agent_id} does not implement the {operation} admin operation.",
            )

    async def send(
        self,
        *,
        agent_id: str,
        payload: ManagementRequestPayload,
        timeout_seconds: int = 30,
    ) -> ManagementResult:
        self._assert_available(agent_id, str(payload.operation))
        request = self.store.create_management_request(
            ManagementRequest(
                agent_id=agent_id,
                payload=payload,
                timeout_seconds=timeout_seconds,
            )
        )
        deadline = asyncio.get_running_loop().time() + max(1, request.timeout_seconds)
        while True:
            result = self.store.get_management_result(request.request_id)
            if result is not None:
                return result
            if asyncio.get_running_loop().time() >= deadline:
                raise ManagementClientError(
                    status_code=504,
                    error_code="request_timeout",
                    detail=(
                        f"Timed out waiting for {request.operation} "
                        f"from agent {agent_id}."
                    ),
                )
            await asyncio.sleep(0.2)


def payload_to_json(payload: ManagementResultPayload) -> dict[str, object]:
    return payload.model_dump(mode="json", by_alias=True)
