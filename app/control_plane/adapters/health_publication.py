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
        for implementation_ref in sorted(
            self._directory.implementations_for_admin_interface("health_publication")
        ):
            await self._bus.submit(
                ControlCommand(
                    command_id=uuid4().hex,
                    admin_interface="health_publication",
                    admin_operation="publish_health",
                    payload_json=report.model_dump_json(),
                    implementation_ref=implementation_ref,
                )
            )

    def connection_summary(self) -> ConnectionSummary:
        authorities = [
            AuthorityStatus(
                implementation_ref=implementation_ref,
                connectivity_state=self._connectivity_state_for_authority(implementation_ref),
                admin_interfaces=sorted(
                    self._directory.admin_interfaces_for_implementation(implementation_ref)
                ),
            )
            for implementation_ref in sorted(self._directory.all_implementations())
        ]
        return ConnectionSummary(authorities=authorities)
