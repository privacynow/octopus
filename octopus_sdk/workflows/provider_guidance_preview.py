"""SDK-owned provider-guidance preview workflows."""

from __future__ import annotations

from octopus_sdk.workflows.provider_guidance import (
    ProviderGuidancePort,
    ProviderGuidancePreview,
    ProviderGuidanceServicePort,
)


class ProviderGuidanceUseCases(ProviderGuidancePort):
    """Canonical provider-guidance preview operations."""

    def __init__(self, *, guidance_service: ProviderGuidanceServicePort) -> None:
        self._guidance = guidance_service

    def preview(
        self,
        provider_name: str,
        *,
        role: str,
        active_skills: list[str],
        compact_mode: bool,
    ) -> ProviderGuidancePreview:
        if provider_name not in {"claude", "codex"}:
            raise ValueError(f"Unknown provider: {provider_name}")
        system_prompt = self._guidance.system_prompt(role, active_skills)
        system_prompt = self._guidance.apply_compact_mode(system_prompt, compact_mode)
        return ProviderGuidancePreview(
            provider=provider_name,
            effective_guidance=self._guidance.effective_guidance_preview(provider_name),
            system_prompt=system_prompt,
            capability_summary=self._guidance.capability_summary(provider_name, active_skills),
            provider_config=self._guidance.provider_config(provider_name, active_skills),
            prompt_weight=len(system_prompt),
        )
