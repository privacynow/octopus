"""Local persisted agent runtime state (registry-issued identity and cursors)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class AgentRuntimeState:
    agent_id: str = ""
    agent_token: str = ""
    poll_cursor: str = "0"
    registered_slug: str = ""
    last_successful_contact_at: str = ""
    connectivity_state: str = "standalone"
    last_error: str = ""


def agent_state_path(data_dir: Path) -> Path:
    return data_dir / "agent" / "registry_state.json"


def load_agent_runtime_state(data_dir: Path) -> AgentRuntimeState:
    path = agent_state_path(data_dir)
    if not path.exists():
        return AgentRuntimeState()
    try:
        raw = json.loads(path.read_text())
    except Exception:
        return AgentRuntimeState()
    return AgentRuntimeState(
        agent_id=raw.get("agent_id", ""),
        agent_token=raw.get("agent_token", ""),
        poll_cursor=str(raw.get("poll_cursor", "0")),
        registered_slug=raw.get("registered_slug", ""),
        last_successful_contact_at=raw.get("last_successful_contact_at", ""),
        connectivity_state=raw.get("connectivity_state", "standalone"),
        last_error=raw.get("last_error", ""),
    )


def save_agent_runtime_state(data_dir: Path, state: AgentRuntimeState) -> None:
    path = agent_state_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(state), indent=2, sort_keys=True))
