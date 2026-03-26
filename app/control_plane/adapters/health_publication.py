"""Bus-backed health-publication adapter."""

from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

from app.control_plane.bus import ControlPlaneBus
from app.control_plane.directory import ControlPlaneDirectory
from app.control_plane.models import ControlCommand
from octopus_sdk.health_publication import AuthorityStatus, ConnectionSummary, HealthReport

class BusHealthPublication:
    def __init__(
        self,
        bus: ControlPlaneBus,
        directory: ControlPlaneDirectory,
        *,
        connectivity_state_for_authority: Callable[[str], str],
    ) -> None:
        self._bus = bus
        self._directory = directory
        self._connectivity_state_for_authority = connectivity_state_for_authority

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
                connectivity_state=self._connectivity_state_for_authority(authority_ref),
                capabilities=sorted(
                    self._directory.capabilities_for_authority(authority_ref)
                ),
            )
            for authority_ref in sorted(self._directory.all_authorities())
        ]
        return ConnectionSummary(authorities=authorities)
