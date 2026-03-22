"""Async facade over the selected control-plane store."""

from __future__ import annotations

import asyncio
from pathlib import Path
from time import monotonic

from app import runtime_backend
from app.control_plane.models import ControlCommand, ControlReply


class ControlPlaneBus:
    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir

    def _store(self):
        return runtime_backend.control_plane_store()

    def debug_connection(self):
        return self._store().debug_connection(self._data_dir)

    def reset_for_test(self) -> None:
        self._store().reset_db_for_test(self._data_dir)

    def validate_backend(self) -> None:
        self._store().validate_backend(self._data_dir)

    async def submit(self, command: ControlCommand) -> str:
        return self._store().submit(self._data_dir, command)

    async def request(
        self,
        command: ControlCommand,
        *,
        timeout_seconds: float = 10.0,
    ) -> ControlReply:
        if not command.correlation_id:
            command = command.model_copy(update={"correlation_id": command.command_id})
        command_id = self._store().submit(self._data_dir, command)
        deadline = monotonic() + timeout_seconds
        while True:
            reply = self._store().get_reply(self._data_dir, command_id)
            if reply is not None:
                return reply
            if monotonic() >= deadline:
                raise TimeoutError(f"Timed out waiting for control-plane reply for {command_id}")
            await asyncio.sleep(0.05)

    async def poll_commands(
        self,
        *,
        allowed_pairs: set[tuple[str, str]],
        limit: int = 20,
    ) -> list[ControlCommand]:
        return self._store().poll_commands(
            self._data_dir,
            allowed_pairs=allowed_pairs,
            limit=limit,
        )

    async def complete(
        self,
        command_id: str,
        *,
        claimed_at: str,
        result_json: str | None = None,
    ) -> None:
        self._store().complete(
            self._data_dir,
            command_id,
            claimed_at=claimed_at,
            result_json=result_json,
        )

    async def fail(self, command_id: str, *, claimed_at: str, error: str) -> None:
        self._store().fail(self._data_dir, command_id, claimed_at=claimed_at, error=error)

    async def dead_letter(self, command_id: str, *, claimed_at: str, reason: str) -> None:
        self._store().dead_letter(
            self._data_dir,
            command_id,
            claimed_at=claimed_at,
            reason=reason,
        )

    async def renew_lease(
        self,
        command_id: str,
        *,
        claimed_at: str,
        extension_seconds: float = 30.0,
    ) -> bool:
        return self._store().renew_lease(
            self._data_dir,
            command_id,
            claimed_at=claimed_at,
            extension_seconds=extension_seconds,
        )

    async def reclaim_expired(self) -> int:
        return self._store().reclaim_expired(self._data_dir)

    async def purge_old_commands(self, older_than_hours: int = 72) -> int:
        return self._store().purge_old_commands(
            self._data_dir,
            older_than_hours=older_than_hours,
        )

    async def reconcile_orphans(
        self,
        *,
        allowed_pairs: set[tuple[str, str]],
    ) -> int:
        return self._store().reconcile_orphans(
            self._data_dir,
            allowed_pairs=allowed_pairs,
        )
