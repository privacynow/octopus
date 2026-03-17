"""Contracts for provider guidance preview workflows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ProviderGuidancePreview:
    provider: str
    effective_guidance: str
    system_prompt: str
    capability_summary: str
    provider_config: dict[str, Any]
    prompt_weight: int


class ProviderGuidancePort(Protocol):
    def preview(
        self,
        provider_name: str,
        *,
        role: str,
        active_skills: list[str],
        compact_mode: bool,
    ) -> ProviderGuidancePreview: ...
