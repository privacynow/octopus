"""Processor contracts for control-plane command execution."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.control_plane.models import ControlCommand, ControlReply


@runtime_checkable
class ControlProcessor(Protocol):
    def authority_capabilities(self) -> dict[str, set[str]]:
        """Return the owned authority/capability map for this processor."""

    async def process(self, command: ControlCommand) -> ControlReply:
        """Process one claimed control-plane command."""
