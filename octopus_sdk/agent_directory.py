"""Shared control-plane port for agent discovery and authority resolution."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

from octopus_sdk.registry.models import AgentDiscoveryQuery, DiscoveredAgentRef


class AgentSearchResult(BaseModel):
    agents: list[DiscoveredAgentRef] = Field(default_factory=list)
    status: str
    responding_authorities: list[str] = Field(default_factory=list)
    timed_out_authorities: list[str] = Field(default_factory=list)


class AuthorityResolution(BaseModel):
    authority_ref: str = ""
    status: str
    error: str = ""


@runtime_checkable
class AgentDirectoryPort(Protocol):
    async def search_agents(
        self,
        *,
        query: AgentDiscoveryQuery,
    ) -> AgentSearchResult: ...

    async def resolve_target_authority(
        self,
        *,
        target_agent_id: str,
    ) -> AuthorityResolution: ...


class NoOpAgentDirectory:
    async def search_agents(
        self,
        *,
        query: AgentDiscoveryQuery,
    ) -> AgentSearchResult:
        del query
        return AgentSearchResult(status="unavailable")

    async def resolve_target_authority(
        self,
        *,
        target_agent_id: str,
    ) -> AuthorityResolution:
        del target_agent_id
        return AuthorityResolution(status="unavailable", error="no control plane")
