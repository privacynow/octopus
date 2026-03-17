"""Shared service layer for runtime provider guidance and prompt assembly.

This service keeps surface code away from direct prompt-building helpers in
``app.skills`` so later content-store migration can replace the backing model
without rewriting Telegram, registry, or runtime orchestration code again.
"""

from __future__ import annotations

from pathlib import Path

from app.content_models import ProviderGuidanceTrackRecord
from app.content_seed import default_provider_guidance_tracks
from app.providers.base import PreflightContext, RunContext
from app.skills import (
    build_capability_summary,
    build_preflight_context as _build_preflight_context,
    build_provider_config,
    build_run_context as _build_run_context,
    build_system_prompt,
    check_prompt_size,
    check_prompt_size_cross_chat as _check_prompt_size_cross_chat,
    estimate_prompt_size as _estimate_prompt_size,
    stage_codex_scripts as _stage_codex_scripts,
)

_COMPACT_RESPONSE_SUFFIX = (
    "Structure your response with a 2-4 line summary first, "
    "then provide detailed explanation below. Lead with the answer."
)


class ProviderGuidanceService:
    """Surface-neutral provider guidance and prompt assembly service."""

    def system_prompt(self, role: str, active_skills: list[str]) -> str:
        return build_system_prompt(role, active_skills)

    def prompt_weight(self, role: str, active_skills: list[str]) -> int:
        return len(self.system_prompt(role, active_skills))

    def provider_config(
        self,
        provider_name: str,
        active_skills: list[str],
        credential_env: dict[str, str] | None = None,
    ) -> dict:
        return build_provider_config(provider_name, active_skills, credential_env or {})

    def capability_summary(self, provider_name: str, active_skills: list[str]) -> str:
        return build_capability_summary(provider_name, active_skills)

    def prompt_size_warning(self, role: str, active_skills: list[str]) -> str | None:
        return check_prompt_size(role, active_skills)

    def estimate_prompt_size(
        self,
        role: str,
        current_skills: list[str],
        new_skill: str,
    ) -> tuple[int, bool]:
        return _estimate_prompt_size(role, current_skills, new_skill)

    def check_prompt_size_cross_chat(
        self,
        data_dir: Path,
        skill_name: str,
        provider_name: str,
        provider_state_factory,
        approval_mode: str,
    ) -> list[str]:
        return _check_prompt_size_cross_chat(
            data_dir,
            skill_name,
            provider_name,
            provider_state_factory,
            approval_mode,
        )

    def build_run_context(
        self,
        role: str,
        active_skills: list[str],
        extra_dirs: list[str],
        *,
        provider_name: str = "",
        credential_env: dict[str, str] | None = None,
        working_dir: str = "",
        file_policy: str = "",
        effective_model: str = "",
    ) -> RunContext:
        return _build_run_context(
            role,
            active_skills,
            extra_dirs,
            provider_name=provider_name,
            credential_env=credential_env,
            working_dir=working_dir,
            file_policy=file_policy,
            effective_model=effective_model,
        )

    def build_preflight_context(
        self,
        role: str,
        active_skills: list[str],
        extra_dirs: list[str],
        *,
        provider_name: str = "",
        working_dir: str = "",
        file_policy: str = "",
        effective_model: str = "",
    ) -> PreflightContext:
        return _build_preflight_context(
            role,
            active_skills,
            extra_dirs,
            provider_name=provider_name,
            working_dir=working_dir,
            file_policy=file_policy,
            effective_model=effective_model,
        )

    def apply_compact_mode(self, system_prompt: str, compact: bool) -> str:
        if not compact:
            return system_prompt
        if system_prompt:
            return system_prompt + "\n\nIMPORTANT: " + _COMPACT_RESPONSE_SUFFIX
        return _COMPACT_RESPONSE_SUFFIX

    def stage_codex_scripts(
        self,
        data_dir: Path,
        conversation_key: str,
        active_skills: list[str],
    ) -> Path | None:
        return _stage_codex_scripts(data_dir, conversation_key, active_skills)

    def default_seed_tracks(self) -> list[ProviderGuidanceTrackRecord]:
        return default_provider_guidance_tracks()


_SERVICE = ProviderGuidanceService()


def get_provider_guidance_service() -> ProviderGuidanceService:
    return _SERVICE
