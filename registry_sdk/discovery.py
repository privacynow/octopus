"""Agent discovery types for the registry SDK."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AgentDiscoveryQuery(BaseModel):
    role: str = ""
    capabilities: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    free_text: str = ""
    exclude_agent_ids: list[str] = Field(default_factory=list)
    required_state: str = "connected"


class DiscoveredAgentRef(BaseModel):
    authority_ref: str
    agent_id: str
    display_name: str = ""
    slug: str = ""
    role: str = ""
    capabilities: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    description: str = ""
    connectivity_state: str = ""
    current_capacity: int = 0
    max_capacity: int = 1
