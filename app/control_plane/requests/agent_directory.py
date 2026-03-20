"""Agent-directory control-plane payloads."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SearchAgentsRequest(BaseModel):
    role: str = ""
    capabilities: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    free_text: str = ""
    exclude_agent_ids: list[str] = Field(default_factory=list)
    required_state: str = "connected"


class ResolveTargetAuthorityRequest(BaseModel):
    target_agent_id: str = Field(..., min_length=1)
