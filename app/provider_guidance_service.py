"""Shared service layer for runtime provider guidance and prompt assembly."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from app.content_models import ProviderGuidanceTrackRecord, RuntimeSkillTrackRecord
from app.content_seed import default_provider_guidance_tracks
from app.identity import filesystem_component_for_key
from app.providers.base import PreflightContext, RunContext
from app.skill_catalog_service import get_skill_catalog_service

_COMPACT_RESPONSE_SUFFIX = (
    "Structure your response with a 2-4 line summary first, "
    "then provide detailed explanation below. Lead with the answer."
)
_PROMPT_SIZE_WARNING_THRESHOLD = 8000


def _resolve_placeholders(obj, env: dict[str, str]):
    if isinstance(obj, str):
        def replacer(match):
            return env.get(match.group(1), match.group(0))

        return re.sub(r"\$\{(\w+)\}", replacer, obj)
    if isinstance(obj, dict):
        return {key: _resolve_placeholders(value, env) for key, value in obj.items()}
    if isinstance(obj, list):
        return [_resolve_placeholders(item, env) for item in obj]
    return obj


class ProviderGuidanceService:
    """Surface-neutral provider guidance and prompt assembly service."""

    def __init__(self) -> None:
        self._catalog = get_skill_catalog_service()

    def _tracks(self, active_skills: list[str]) -> list[RuntimeSkillTrackRecord]:
        tracks: list[RuntimeSkillTrackRecord] = []
        for name in active_skills:
            if (record := self._catalog.resolve_track(name)) is not None:
                tracks.append(record)
        return tracks

    def system_prompt(self, role: str, active_skills: list[str]) -> str:
        parts: list[str] = []
        if role:
            stripped = role.strip()
            lower = stripped.lower()
            is_sentence = any(lower.startswith(prefix) for prefix in ("you are", "you're", "act as", "as a"))
            if "\n" in stripped or is_sentence:
                parts.append(stripped + "\n")
            else:
                parts.append(f"You are a {stripped}.\n")
        for record in self._tracks(active_skills):
            parts.append(f"## {record.display_name}\n\n{record.revision.instruction_body}\n")
        return "\n".join(parts) if parts else ""

    def prompt_weight(self, role: str, active_skills: list[str]) -> int:
        return len(self.system_prompt(role, active_skills))

    def provider_config(
        self,
        provider_name: str,
        active_skills: list[str],
        credential_env: dict[str, str] | None = None,
    ) -> dict:
        credential_env = credential_env or {}
        if provider_name == "claude":
            mcp_servers: dict = {}
            allowed_tools: list[str] = []
            disallowed_tools: list[str] = []
            for record in self._tracks(active_skills):
                raw = record.revision.provider_config.get("claude", {})
                if not isinstance(raw, dict):
                    continue
                if isinstance(raw.get("mcp_servers"), dict):
                    mcp_servers.update(raw["mcp_servers"])
                if isinstance(raw.get("allowed_tools"), list):
                    allowed_tools.extend(raw["allowed_tools"])
                if isinstance(raw.get("disallowed_tools"), list):
                    disallowed_tools.extend(raw["disallowed_tools"])
            config: dict = {}
            if mcp_servers:
                config["mcp_servers"] = mcp_servers
            if allowed_tools:
                config["allowed_tools"] = allowed_tools
            if disallowed_tools:
                config["disallowed_tools"] = disallowed_tools
            return _resolve_placeholders(config, credential_env) if config else {}

        if provider_name == "codex":
            sandbox = ""
            scripts: list = []
            config_overrides: list[str] = []
            for record in self._tracks(active_skills):
                raw = record.revision.provider_config.get("codex", {})
                if not isinstance(raw, dict):
                    continue
                if raw.get("sandbox") and not sandbox:
                    sandbox = str(raw["sandbox"])
                if isinstance(raw.get("scripts"), list):
                    scripts.extend(raw["scripts"])
                if isinstance(raw.get("config_overrides"), list):
                    config_overrides.extend(raw["config_overrides"])
            config: dict = {}
            if sandbox:
                config["sandbox"] = sandbox
            if scripts:
                config["scripts"] = scripts
            if config_overrides:
                config["config_overrides"] = config_overrides
            return _resolve_placeholders(config, credential_env) if config else {}

        return {}

    def capability_summary(self, provider_name: str, active_skills: list[str]) -> str:
        lines: list[str] = []
        for record in self._tracks(active_skills):
            raw = record.revision.provider_config.get(provider_name, {})
            if not isinstance(raw, dict):
                continue
            if provider_name == "claude":
                servers = raw.get("mcp_servers")
                if isinstance(servers, dict):
                    for server_name in servers:
                        lines.append(f"MCP server: {server_name} (from {record.slug})")
                tools = raw.get("allowed_tools")
                if isinstance(tools, list):
                    for tool_name in tools:
                        lines.append(f"Allowed tool: {tool_name}")
            elif provider_name == "codex":
                scripts = raw.get("scripts")
                if isinstance(scripts, list):
                    for item in scripts:
                        if isinstance(item, dict):
                            script_name = str(item.get("name", item.get("source", "?")))
                        else:
                            script_name = str(item)
                        lines.append(f"Script: {script_name} (from {record.slug})")
        return "\n".join(lines)

    def prompt_size_warning(self, role: str, active_skills: list[str]) -> str | None:
        prompt = self.system_prompt(role, active_skills)
        if len(prompt) > _PROMPT_SIZE_WARNING_THRESHOLD:
            return (
                f"Composed prompt is {len(prompt):,} chars "
                f"(threshold: {_PROMPT_SIZE_WARNING_THRESHOLD:,}). "
                f"Quality may degrade. Consider removing some skills."
            )
        return None

    def estimate_prompt_size(
        self,
        role: str,
        current_skills: list[str],
        new_skill: str,
    ) -> tuple[int, bool]:
        projected = current_skills + ([new_skill] if new_skill not in current_skills else [])
        prompt = self.system_prompt(role, projected)
        return len(prompt), len(prompt) > _PROMPT_SIZE_WARNING_THRESHOLD

    def check_prompt_size_cross_chat(
        self,
        data_dir: Path,
        skill_name: str,
        provider_name: str,
        provider_state_factory,
        approval_mode: str,
    ) -> list[str]:
        from app.storage import list_sessions, load_session

        warnings: list[str] = []
        for info in list_sessions(data_dir):
            active = self._catalog.filter_resolvable(info.get("active_skills", []))
            if skill_name not in active:
                continue
            session_data = load_session(
                data_dir,
                info["conversation_key"],
                provider_name,
                provider_state_factory,
                approval_mode,
            )
            role = session_data.get("role", "")
            warning = self.prompt_size_warning(role, active)
            if warning:
                warnings.append(f"  Conversation {info['conversation_key']}: {warning}")
        return warnings

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
        credential_env = credential_env or {}
        provider_config = self.provider_config(provider_name, active_skills, credential_env) if provider_name else {}
        capability_summary = self.capability_summary(provider_name, active_skills) if provider_name else ""
        return RunContext(
            extra_dirs=extra_dirs,
            system_prompt=self.system_prompt(role, active_skills),
            capability_summary=capability_summary,
            provider_config=provider_config,
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
        capability_summary = self.capability_summary(provider_name, active_skills) if provider_name else ""
        return PreflightContext(
            extra_dirs=extra_dirs,
            system_prompt=self.system_prompt(role, active_skills),
            capability_summary=capability_summary,
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
        scripts_dir = data_dir / "scripts" / filesystem_component_for_key(conversation_key)
        tracks = {record.slug: record for record in self._tracks(active_skills)}
        if not tracks:
            if scripts_dir.is_dir():
                shutil.rmtree(scripts_dir, ignore_errors=True)
            return None
        all_scripts: dict[str, list] = {}
        for record in tracks.values():
            raw = record.revision.provider_config.get("codex", {})
            if isinstance(raw, dict) and isinstance(raw.get("scripts"), list):
                all_scripts[record.slug] = raw["scripts"]
        if not all_scripts:
            if scripts_dir.is_dir():
                shutil.rmtree(scripts_dir, ignore_errors=True)
            return None
        scripts_dir.mkdir(parents=True, exist_ok=True)
        for existing in scripts_dir.iterdir():
            if existing.is_dir() and existing.name not in all_scripts:
                shutil.rmtree(existing, ignore_errors=True)
        for skill_name, script_defs in all_scripts.items():
            record = tracks.get(skill_name)
            if record is None:
                continue
            skill_scripts_dir = scripts_dir / skill_name
            if skill_scripts_dir.is_dir():
                shutil.rmtree(skill_scripts_dir, ignore_errors=True)
            skill_scripts_dir.mkdir(parents=True, exist_ok=True)
            files_by_path = {item.relative_path: item for item in record.revision.files}
            for script_def in script_defs:
                if isinstance(script_def, dict):
                    source = str(script_def.get("source", "") or "")
                    script_name = str(script_def.get("name", Path(source).name if source else "") or "")
                elif isinstance(script_def, str):
                    source = script_def
                    script_name = Path(script_def).name
                else:
                    continue
                if not source or not script_name:
                    continue
                file_record = files_by_path.get(source)
                if file_record is None:
                    continue
                target = skill_scripts_dir / script_name
                target.write_text(file_record.content_text, encoding="utf-8")
                if file_record.executable:
                    target.chmod(0o755)
        return scripts_dir

    def default_seed_tracks(self) -> list[ProviderGuidanceTrackRecord]:
        return default_provider_guidance_tracks()

    def effective_guidance(self, provider_name: str, *, instance_key: str = "") -> ProviderGuidanceTrackRecord | None:
        from app.content_store import get_content_store

        return get_content_store().resolve_provider_guidance(provider_name, instance_key=instance_key)

    def effective_guidance_preview(self, provider_name: str, *, instance_key: str = "") -> str:
        track = self.effective_guidance(provider_name, instance_key=instance_key)
        return track.revision.content if track is not None else ""


_SERVICE = ProviderGuidanceService()


def get_provider_guidance_service() -> ProviderGuidanceService:
    return _SERVICE
