"""Agent registration types for the registry SDK."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AgentCard(BaseModel):
    """Agent identity and capability declaration sent during enrollment/registration."""

    model_config = ConfigDict(extra="forbid")

    bot_key: str = Field(..., min_length=1)
    display_name: str = ""
    slug: str = ""
    role: str = ""
    registry_scope: str = "full"
    capabilities: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    description: str = ""
    provider: str = ""
    mode: str = "standalone"
    connectivity_state: str = "standalone"
    current_capacity: int = 0
    max_capacity: int = 1
    channel_capabilities: list[str] = Field(default_factory=lambda: ["telegram"])
    version: str = "dev"
