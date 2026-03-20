"""Bus-backed health-publication adapter."""

from __future__ import annotations

from uuid import uuid4

from app.control_plane.bus import ControlPlaneBus
from app.control_plane.directory import ControlPlaneDirectory
from app.control_plane.models import ControlCommand
from app.ports.health_publication import AuthorityStatus, ConnectionSummary, HealthReport


def _registry_scope_for_capabilities(capabilities: set[str]) -> str:
    has_projection = "conversation_projection" in capabilities
    has_coordination = bool({"task_routing", "agent_directory"} & capabilities)
    if has_projection and has_coordination:
        return "full"
    if has_projection:
        return "channel"
    if has_coordination:
        return "coordination"
    return "full"


class BusHealthPublication:
    def __init__(self, bus: ControlPlaneBus, directory: ControlPlaneDirectory) -> None:
        self._bus = bus
        self._directory = directory

    async def publish_health(self, *, report: HealthReport) -> None:
        for authority_ref in sorted(
            self._directory.authorities_for_capability("health_publication")
        ):
            await self._bus.submit(
                ControlCommand(
                    command_id=uuid4().hex,
                    capability="health_publication",
                    operation="publish_health",
                    payload_json=report.model_dump_json(),
                    authority_ref=authority_ref,
                )
            )

    def connection_summary(self) -> ConnectionSummary:
        authorities = [
            AuthorityStatus(
                authority_ref=authority_ref,
                connectivity_state="configured",
                registry_scope=_registry_scope_for_capabilities(
                    self._directory.capabilities_for_authority(authority_ref)
                ),
            )
            for authority_ref in sorted(self._directory.all_authorities())
        ]
        return ConnectionSummary(authorities=authorities)
