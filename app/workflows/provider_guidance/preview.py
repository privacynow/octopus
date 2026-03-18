"""Provider-guidance preview workflow ownership."""

from __future__ import annotations

from app.provider_guidance_service import get_provider_guidance_service
from app.workflows.provider_guidance.contracts import ProviderGuidancePreview, ProviderGuidancePort


class ProviderGuidanceUseCases(ProviderGuidancePort):
    """Canonical provider-guidance preview operations."""

    def _guidance(self):
        return get_provider_guidance_service()

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
        guidance = self._guidance()
        system_prompt = guidance.system_prompt(role, active_skills)
        system_prompt = guidance.apply_compact_mode(system_prompt, compact_mode)
        return ProviderGuidancePreview(
            provider=provider_name,
            effective_guidance=guidance.effective_guidance_preview(provider_name),
            system_prompt=system_prompt,
            capability_summary=guidance.capability_summary(provider_name, active_skills),
            provider_config=guidance.provider_config(provider_name, active_skills),
            prompt_weight=len(system_prompt),
        )


_USE_CASES = ProviderGuidanceUseCases()


def get_provider_guidance_use_cases() -> ProviderGuidanceUseCases:
    return _USE_CASES
