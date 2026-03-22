"""Control-plane store protocol shared by SQLite and Postgres backends."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from app.control_plane.models import ControlCommand, ControlReply


class AbstractControlPlaneStore(Protocol):
    def close_control_plane_db(self, data_dir: Path) -> None: ...

    def close_all_control_plane_db(self) -> None: ...

    def debug_connection(self, data_dir: Path) -> Any: ...

    def reset_db_for_test(self, data_dir: Path) -> None: ...

    def validate_backend(self, data_dir: Path) -> None: ...

    def submit(self, data_dir: Path, command: ControlCommand) -> str: ...

    def get_reply(self, data_dir: Path, command_id: str) -> ControlReply | None: ...

    def poll_commands(
        self,
        data_dir: Path,
        *,
        allowed_pairs: set[tuple[str, str]],
        limit: int = 20,
        lease_seconds: float = 30.0,
    ) -> list[ControlCommand]: ...

    def complete(
        self,
        data_dir: Path,
        command_id: str,
        *,
        claimed_at: str,
        result_json: str | None = None,
    ) -> None: ...

    def fail(self, data_dir: Path, command_id: str, *, claimed_at: str, error: str) -> None: ...

    def dead_letter(self, data_dir: Path, command_id: str, *, claimed_at: str, reason: str) -> None: ...

    def renew_lease(
        self,
        data_dir: Path,
        command_id: str,
        *,
        claimed_at: str,
        extension_seconds: float = 30.0,
    ) -> bool: ...

    def reclaim_expired(self, data_dir: Path) -> int: ...

    def purge_old_commands(self, data_dir: Path, older_than_hours: int = 72) -> int: ...

    def reconcile_orphans(
        self,
        data_dir: Path,
        *,
        allowed_pairs: set[tuple[str, str]],
    ) -> int: ...
