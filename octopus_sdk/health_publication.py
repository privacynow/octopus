"""Shared control-plane port for publishing backend health summaries."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field


class HealthReport(BaseModel):
    connectivity_state: str
    current_capacity: int = 0
    max_capacity: int = 1
    runtime_health_json: str = ""


class AuthorityStatus(BaseModel):
    authority_ref: str
    connectivity_state: str
    capabilities: list[str] = Field(default_factory=list)


class ConnectionSummary(BaseModel):
    authorities: list[AuthorityStatus] = Field(default_factory=list)


@runtime_checkable
class HealthPublicationPort(Protocol):
    async def publish_health(self, *, report: HealthReport) -> None: ...

    def connection_summary(self) -> ConnectionSummary: ...


class NoOpHealthPublication:
    async def publish_health(self, *, report: HealthReport) -> None:
        del report
        return None

    def connection_summary(self) -> ConnectionSummary:
        return ConnectionSummary()
