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
        use_draft: bool = False,
        body_override: str = "",
        scope_kind: str = "system",
        scope_key: str = "",
    ) -> ProviderGuidancePreview:
        if provider_name not in {"claude", "codex"}:
            raise ValueError(f"Unknown provider: {provider_name}")
        published_guidance = self._guidance.published_guidance_text(provider_name)
        preview_guidance = published_guidance
        preview_source = "published"
        override = str(body_override or "").strip()
        if override:
            preview_guidance = override
            preview_source = "draft"
        elif use_draft:
            draft_guidance = self._guidance.draft_guidance_text(
                provider_name,
                scope_kind=scope_kind,
                scope_key=scope_key,
            )
            if draft_guidance and draft_guidance != published_guidance:
                preview_guidance = draft_guidance
                preview_source = "draft"
        run_context = self._guidance.build_run_context(
            role,
            active_skills,
            [],
            provider_name=provider_name,
            guidance_override=preview_guidance,
        )
        composed_prompt = self._guidance.apply_compact_mode(run_context.system_prompt, compact_mode)
        return ProviderGuidancePreview(
            provider=provider_name,
            published_guidance=published_guidance,
            preview_guidance=preview_guidance,
            preview_source=preview_source,
            composed_prompt=composed_prompt,
            active_skill_tools_summary=self._guidance.active_skill_tools_summary(provider_name, active_skills),
            provider_config=self._guidance.provider_config(provider_name, active_skills),
            prompt_weight=len(composed_prompt),
        )
