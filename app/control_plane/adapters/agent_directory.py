"""Bus-backed agent-directory adapter."""

from __future__ import annotations

from uuid import uuid4

from octopus_sdk.registry.models import AgentDiscoveryQuery
from app.control_plane.bus import ControlPlaneBus
from app.control_plane.directory import ControlPlaneDirectory
from app.control_plane.models import ControlCommand
from app.control_plane.requests import ResolveTargetAuthorityRequest, SearchAgentsRequest
from octopus_sdk.agent_directory import AgentSearchResult, AuthorityResolution


class BusAgentDirectory:
    def __init__(self, bus: ControlPlaneBus, directory: ControlPlaneDirectory) -> None:
        self._bus = bus
        self._directory = directory

    async def search_agents(self, *, query: AgentDiscoveryQuery) -> AgentSearchResult:
        authorities = sorted(self._directory.implementations_for_admin_interface("agent_directory"))
        if not authorities:
            return AgentSearchResult(status="unavailable")
        request = SearchAgentsRequest.model_validate(query.model_dump(mode="json"))

        aggregated = AgentSearchResult(status="complete")
        for implementation_ref in authorities:
            try:
                reply = await self._bus.request(
                    ControlCommand(
                        command_id=uuid4().hex,
                        admin_interface="agent_directory",
                        admin_operation="search_agents",
                        payload_json=request.model_dump_json(),
                        implementation_ref=implementation_ref,
                    )
                )
            except TimeoutError:
                aggregated.status = "partial"
                aggregated.timed_out_authorities.append(implementation_ref)
                continue
            if reply.status == "failed":
                aggregated.status = "partial"
                aggregated.timed_out_authorities.append(implementation_ref)
                continue
            result = AgentSearchResult.model_validate_json(reply.result_json or '{"agents":[],"status":"complete"}')
            aggregated.agents.extend(result.agents)
            aggregated.responding_authorities.append(implementation_ref)
            if result.status == "partial":
                aggregated.status = "partial"
        if not aggregated.responding_authorities and aggregated.timed_out_authorities:
            aggregated.status = "unavailable"
        return aggregated

    async def resolve_target_authority(
        self,
        *,
        target_agent_id: str,
    ) -> AuthorityResolution:
        authorities = sorted(self._directory.implementations_for_admin_interface("agent_directory"))
        if not authorities:
            return AuthorityResolution(status="unavailable", error="no control plane")
        request = ResolveTargetAuthorityRequest(target_agent_id=target_agent_id)
        matches: list[str] = []
        failures = 0
        for implementation_ref in authorities:
            try:
                reply = await self._bus.request(
                    ControlCommand(
                        command_id=uuid4().hex,
                        admin_interface="agent_directory",
                        admin_operation="resolve_target_authority",
                        payload_json=request.model_dump_json(),
                        implementation_ref=implementation_ref,
                    )
                )
            except TimeoutError:
                failures += 1
                continue
            if reply.status == "failed":
                failures += 1
                continue
            result = AuthorityResolution.model_validate_json(reply.result_json or '{"status":"not_found"}')
            if result.status == "resolved" and result.authority_ref:
                matches.append(result.authority_ref)
        unique = sorted(set(matches))
        if len(unique) == 1:
            return AuthorityResolution(status="resolved", authority_ref=unique[0])
        if len(unique) > 1:
            return AuthorityResolution(
                status="ambiguous",
                error=f"multiple authorities resolved target {target_agent_id}",
            )
        if failures and failures == len(authorities):
            return AuthorityResolution(status="unavailable", error="control-plane request timed out")
        return AuthorityResolution(status="not_found")
