"""Local persisted registry connection state and stable bot identity."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.agents.types import RegistryConnectionState
from app.registry_errors import normalize_registry_error_state

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class BotIdentityState:
    bot_id: str
    created_at: str


def bot_identity_path(data_dir: Path) -> Path:
    return data_dir / "agent" / "bot_identity.json"


def _new_bot_identity() -> BotIdentityState:
    return BotIdentityState(
        bot_id=uuid4().hex,
        created_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    )


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


def _save_bot_identity_state(path: Path, state: BotIdentityState) -> None:
    _atomic_write_private_json(path, asdict(state))


def load_bot_identity_state(data_dir: Path) -> BotIdentityState:
    path = bot_identity_path(data_dir)
    if not path.exists():
        state = _new_bot_identity()
        _save_bot_identity_state(path, state)
        return state
    try:
        raw = json.loads(path.read_text())
        bot_id = str(raw.get("bot_id", "")).strip()
        created_at = str(raw.get("created_at", "")).strip()
        if bot_id and created_at:
            return BotIdentityState(bot_id=bot_id, created_at=created_at)
        raise ValueError("missing required bot identity fields")
    except Exception:
        log.warning("Bot identity load failed, regenerating", exc_info=True)
        state = _new_bot_identity()
        _save_bot_identity_state(path, state)
        return state


def bot_identity(data_dir: Path) -> str:
    return load_bot_identity_state(data_dir).bot_id


def registry_state_dir(data_dir: Path) -> Path:
    return data_dir / "agent" / "registries"


def registry_connection_state_path(data_dir: Path, registry_id: str) -> Path:
    return registry_state_dir(data_dir) / f"{registry_id}.json"


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


def save_registry_connection_state(data_dir: Path, state: RegistryConnectionState) -> None:
    path = registry_connection_state_path(data_dir, state.registry_id)
    _atomic_write_private_json(path, asdict(state))
