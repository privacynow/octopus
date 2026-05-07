"""Runtime adapter for SDK-backed Octopus agent awareness."""

from __future__ import annotations

import shutil
import subprocess

from app.agents.state import load_runtime_registry_connection_state
from app.config import BotConfig
from octopus_sdk.agent_awareness import (
    AgentAwarenessRecord,
    AgentAwarenessRequestRecord,
    AgentToolCapabilityRecord,
    AgentWorkspaceAwarenessRecord,
    ProtocolAgentAwarenessService,
)
from octopus_sdk.protocols import ProtocolService
from octopus_sdk.registry.client import RegistryClient
from octopus_sdk.workflows.skills import RuntimeSkillCatalogPort


_TOOL_PURPOSES: dict[str, str] = {
    "sudo": "passwordless root inside the bot container when configured",
    "apt-get": "Debian package installation when sudo policy allows it",
    "git": "source control",
    "python": "Python runtime",
    "python3": "Python 3 runtime",
    "pip": "Python package installation",
    "pip3": "Python 3 package installation",
    "node": "Node.js runtime",
    "npm": "Node package installation",
    "mvn": "Maven Java builds",
    "javac": "Java compiler",
    "java": "Java runtime",
    "gcc": "C compiler",
    "g++": "C++ compiler",
    "rg": "fast search",
    "curl": "HTTP client",
    "jq": "JSON inspection",
    "zip": "archive creation",
    "unzip": "archive extraction",
}


def _tool_capabilities() -> list[AgentToolCapabilityRecord]:
    records: list[AgentToolCapabilityRecord] = []
    for name, detail in _TOOL_PURPOSES.items():
        path = shutil.which(name) or ""
        available = bool(path)
        tool_detail = detail
        if name == "sudo" and available:
            try:
                result = subprocess.run(
                    ["sudo", "-n", "true"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=2,
                    check=False,
                )
                available = result.returncode == 0
                tool_detail = "passwordless root inside the bot container" if available else "installed but passwordless sudo is not available"
            except Exception:
                available = False
                tool_detail = "installed but sudo availability could not be verified"
        records.append(
            AgentToolCapabilityRecord(
                name=name,
                available=available,
                path=path,
                detail=tool_detail,
            )
        )
    return records


class RuntimeAgentAwarenessService:
    """Bind SDK awareness records to the current bot runtime implementation."""

    def __init__(
        self,
        *,
        config: BotConfig,
        runtime_skill_catalog: RuntimeSkillCatalogPort,
    ) -> None:
        self._config = config
        self._runtime_skill_catalog = runtime_skill_catalog
        self._tool_capability_cache: list[AgentToolCapabilityRecord] | None = None

    def _protocol_source(self) -> ProtocolService | None:
        for registry in self._config.agent_registries:
            if registry.registry_scope not in {"full", "coordination"}:
                continue
            state = load_runtime_registry_connection_state(
                self._config.data_dir,
                registry.registry_id,
                registry_scope=registry.registry_scope,
            )
            if not state.agent_token:
                continue
            return ProtocolService(RegistryClient(registry.url, agent_token=state.agent_token))
        return None

    def _available_skills(self) -> list[str]:
        try:
            items = self._runtime_skill_catalog.list_skills()
        except Exception:
            return []
        names = [
            str(getattr(item, "name", "") or "").strip()
            for item in items
            if str(getattr(item, "name", "") or "").strip()
        ]
        return sorted(dict.fromkeys(names))

    def _workspace_records(self, active_workspace_ref: str) -> list[AgentWorkspaceAwarenessRecord]:
        records: list[AgentWorkspaceAwarenessRecord] = []
        for project in self._config.projects:
            records.append(
                AgentWorkspaceAwarenessRecord(
                    name=project.name,
                    root_dir=project.root_dir,
                    file_policy=project.file_policy,
                    active=bool(active_workspace_ref and project.name == active_workspace_ref),
                )
            )
        if not records and self._config.working_dir:
            records.append(
                AgentWorkspaceAwarenessRecord(
                    name="default",
                    root_dir=str(self._config.working_dir),
                    file_policy="edit",
                    active=True,
                )
            )
        return records

    def _tool_capabilities(self) -> list[AgentToolCapabilityRecord]:
        if self._tool_capability_cache is None:
            self._tool_capability_cache = _tool_capabilities()
        return list(self._tool_capability_cache)

    async def build_awareness(self, request: AgentAwarenessRequestRecord) -> AgentAwarenessRecord:
        active_workspace_ref = str(request.workspace_ref or "").strip()
        enriched = request.model_copy(
            update={
                "available_skills": self._available_skills(),
                "workspaces": self._workspace_records(active_workspace_ref),
                "tool_capabilities": self._tool_capabilities(),
            }
        )
        return await ProtocolAgentAwarenessService(self._protocol_source()).build_awareness(enriched)
