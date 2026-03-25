"""Local persisted registry connection state and stable bot identity."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import uuid4

from app.registry_errors import normalize_registry_error_state

log = logging.getLogger(__name__)


@dataclass
class RegistryConnectionState:
    registry_id: str
    registry_scope: str = "full"
    agent_id: str = ""
    agent_token: str = ""
    poll_cursor: str = "0"
    registered_slug: str = ""
    registered_card_hash: str = ""
    last_successful_contact_at: str = ""
    connectivity_state: str = "standalone"
    last_error: str = ""
    last_error_detail: str = ""


def registry_state_dir(data_dir: Path) -> Path:
    return data_dir / "agent" / "registries"


def registry_connection_state_path(data_dir: Path, registry_id: str) -> Path:
    return registry_state_dir(data_dir) / f"{registry_id}.json"


def _atomic_write_private_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.parent / f".{path.name}.{uuid4().hex}.tmp"
    try:
        tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True))
        tmp_path.chmod(0o600)
        os.replace(tmp_path, path)
    except Exception:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise


def load_registry_connection_state(
    data_dir: Path,
    registry_id: str,
    *,
    default_scope: str = "full",
) -> RegistryConnectionState:
    path = registry_connection_state_path(data_dir, registry_id)
    if not path.exists():
        return RegistryConnectionState(registry_id=registry_id, registry_scope=default_scope)
    try:
        raw = json.loads(path.read_text())
    except Exception:
        log.warning("Registry connection state load failed, using defaults", exc_info=True)
        return RegistryConnectionState(registry_id=registry_id, registry_scope=default_scope)
    last_error, last_error_detail = normalize_registry_error_state(
        str(raw.get("last_error", "")),
        str(raw.get("last_error_detail", "")),
    )
    return RegistryConnectionState(
        registry_id=str(raw.get("registry_id", registry_id)) or registry_id,
        registry_scope=str(raw.get("registry_scope", default_scope)) or default_scope,
        agent_id=raw.get("agent_id", ""),
        agent_token=raw.get("agent_token", ""),
        poll_cursor=str(raw.get("poll_cursor", "0")),
        registered_slug=raw.get("registered_slug", ""),
        registered_card_hash=str(raw.get("registered_card_hash", "")),
        last_successful_contact_at=raw.get("last_successful_contact_at", ""),
        connectivity_state=raw.get("connectivity_state", "standalone"),
        last_error=last_error,
        last_error_detail=last_error_detail,
    )


def load_runtime_registry_connection_state(
    data_dir: Path,
    registry_id: str,
    *,
    registry_scope: str = "full",
) -> RegistryConnectionState:
    path = registry_connection_state_path(data_dir, registry_id)
    if not path.exists():
        return RegistryConnectionState(
            registry_id=registry_id,
            registry_scope=registry_scope,
        )
    state = load_registry_connection_state(
        data_dir,
        registry_id,
        default_scope=registry_scope,
    )
    if not state.registry_scope:
        state.registry_scope = registry_scope
    return state


def runtime_registry_agent_id(
    data_dir: Path,
    registry_id: str,
    *,
    registry_scope: str = "full",
) -> str:
    return load_runtime_registry_connection_state(
        data_dir,
        registry_id,
        registry_scope=registry_scope,
    ).agent_id


def save_registry_connection_state(data_dir: Path, state: RegistryConnectionState) -> None:
    path = registry_connection_state_path(data_dir, state.registry_id)
    _atomic_write_private_json(path, asdict(state))
