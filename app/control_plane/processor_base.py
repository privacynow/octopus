"""Processor contracts for control-plane command execution."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.control_plane.models import ControlCommand, ControlReply


@runtime_checkable
class ControlProcessor(Protocol):
    def implemented_admin_interfaces(self) -> dict[str, set[str]]:
        """Return the owned authority/admin_interface map for this processor."""

    async def process(self, command: ControlCommand) -> ControlReply:
        """Process one claimed control-plane command."""
