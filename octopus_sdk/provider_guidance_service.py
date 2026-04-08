"""Default SDK implementation for provider guidance and runtime-skill prompt composition."""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Callable

from octopus_sdk.content_models import ProviderGuidanceTrackRecord, RuntimeSkillTrackRecord
from octopus_sdk.content_store import ContentStorePort
from octopus_sdk.identity import filesystem_component_for_key
from octopus_sdk.providers import CredentialEnvRecord, PreflightContext, ProviderConfigRecord, RunContext
from octopus_sdk.registry.models import DiscoveredAgentRef
from octopus_sdk.runtime.skills import normalize_skill_kind
from octopus_sdk.workflows.skills import SkillCatalogServicePort

_COMPACT_RESPONSE_SUFFIX = (
    "Structure your response with a 2-4 line summary first, "
    "then provide detailed explanation below. Lead with the answer."
)
PROMPT_SIZE_WARNING_THRESHOLD = 8000


def _resolve_placeholders(obj, env: Mapping[str, str]):
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
    """SDK-owned provider guidance implementation with injected dependencies."""

    def __init__(
        self,
        *,
        catalog_service: SkillCatalogServicePort | None = None,
        catalog_factory: Callable[[], SkillCatalogServicePort] | None = None,
        content_store: ContentStorePort | None = None,
        content_store_factory: Callable[[], ContentStorePort] | None = None,
        list_sessions=None,
        load_session=None,
    ) -> None:
        if catalog_service is None and catalog_factory is None:
            raise ValueError("ProviderGuidanceService requires a catalog service or catalog factory")
        if content_store is None and content_store_factory is None:
            raise ValueError("ProviderGuidanceService requires a content store or content-store factory")
        self._catalog_service = catalog_service
        self._catalog_factory = catalog_factory
        self._content_store = content_store
        self._content_store_factory = content_store_factory
        self._list_sessions = list_sessions
        self._load_session = load_session

    def _catalog(self) -> SkillCatalogServicePort:
        if self._catalog_service is not None:
            return self._catalog_service
        assert self._catalog_factory is not None
        return self._catalog_factory()

    def _store(self) -> ContentStorePort:
        if self._content_store is not None:
            return self._content_store
        assert self._content_store_factory is not None
        return self._content_store_factory()

    def _tracks(self, active_skills: list[str]) -> list[RuntimeSkillTrackRecord]:
        catalog = self._catalog()
        tracks: list[RuntimeSkillTrackRecord] = []
        for name in active_skills:
            if (record := catalog.resolve_runtime_track(name)) is not None:
                tracks.append(record)
        return tracks

    def _available_runtime_tracks(self) -> list[RuntimeSkillTrackRecord]:
        catalog = self._catalog()
        tracks: list[RuntimeSkillTrackRecord] = []
        for skill_name in sorted(catalog.catalog()):
            if (record := catalog.resolve_runtime_track(skill_name)) is not None:
                tracks.append(record)
        return tracks

    @staticmethod
    def _skill_kind(record: RuntimeSkillTrackRecord) -> str:
        return normalize_skill_kind(str(record.revision.skill_kind or "prompt"))

    @staticmethod
    def _skill_label(record: RuntimeSkillTrackRecord) -> str:
        display_name = str(record.display_name or "").strip()
        slug = str(record.slug or "").strip()
        if not display_name or display_name.lower() == slug.lower():
            return slug or display_name
        return f"{display_name} ({slug})"

    def _runtime_skill_state_block(
        self,
        *,
        available_tracks: list[RuntimeSkillTrackRecord],
        active_tracks: list[RuntimeSkillTrackRecord],
    ) -> str:
        available_labels = ", ".join(record.slug for record in available_tracks) or "none"
        active_labels = ", ".join(record.slug for record in active_tracks) or "none"
        lines = [
            "## Octopus Runtime Skill State",
            "",
            "This state is authoritative for the current bot and conversation.",
            f"Available on this bot: {available_labels}.",
            f"Active in this conversation: {active_labels}.",
        ]
        prompt_tracks = [record for record in active_tracks if self._skill_kind(record) == "prompt"]
        executable_tracks = [record for record in active_tracks if self._skill_kind(record) == "executable"]
        if prompt_tracks:
            lines.append(
                "Prompt skills listed as active below are operator-selected conversation instructions. "
                "Apply them in this conversation until they are deactivated."
            )
        if executable_tracks:
            lines.append(
                "Executable skills listed as active below are enabled through Octopus runtime orchestration. "
                "Treat that activation as real conversation state, not a hypothetical suggestion."
            )
        lines.append("")
        return "\n".join(lines)

    def _active_skill_prompt_sections(self, tracks: list[RuntimeSkillTrackRecord]) -> list[str]:
        sections: list[str] = []
        for record in tracks:
            kind = self._skill_kind(record)
            heading = f"## ACTIVE {kind.upper()} SKILL: {self._skill_label(record)}"
            semantics = (
                "Apply the following instructions throughout this conversation until the skill is deactivated."
                if kind == "prompt"
                else "This skill is enabled through Octopus runtime orchestration. Follow any instructions below and "
                "treat its activation as real conversation state."
            )
            body = str(record.revision.instruction_body or "").strip()
            section = [
                heading,
                "",
                "Status: active in this conversation",
                "Authority: operator-selected conversation state",
                f"Skill kind: {kind}",
                f"Semantics: {semantics}",
            ]
            if body:
                section.extend(["", body])
            sections.append("\n".join(section) + "\n")
        return sections

    def system_prompt(
        self,
        role: str,
        active_skills: list[str],
        *,
        provider_name: str = "",
        instance_key: str = "",
        guidance_override: str = "",
        available_agents: list[DiscoveredAgentRef] | None = None,
    ) -> str:
        parts: list[str] = []
        if role:
            stripped = role.strip()
            lower = stripped.lower()
            is_sentence = any(lower.startswith(prefix) for prefix in ("you are", "you're", "act as", "as a"))
            if "\n" in stripped or is_sentence:
                parts.append(stripped + "\n")
            else:
                parts.append(f"You are a {stripped}.\n")
        guidance_text = (guidance_override or "").strip()
        if not guidance_text and provider_name:
            guidance_text = self.published_guidance_text(provider_name, instance_key=instance_key)
        if guidance_text:
            parts.append(guidance_text + "\n")
        available_tracks = self._available_runtime_tracks()
        tracks = self._tracks(active_skills)
        if available_tracks or tracks:
            parts.append(
                self._runtime_skill_state_block(
                    available_tracks=available_tracks,
                    active_tracks=tracks,
                )
            )
        parts.extend(self._active_skill_prompt_sections(tracks))
        if available_agents:
            parts.append(self._format_agent_discovery_section(available_agents))
        return "\n".join(parts) if parts else ""

    @staticmethod
    def _format_agent_discovery_section(agents: list[DiscoveredAgentRef]) -> str:
        lines = [
            "## Other Reachable Bots (routing only)\n",
            "These are other bots currently reachable through the coordination layer.",
            "You are answering as the current bot in this conversation. Do not describe yourself as the main assistant, primary assistant, or coordinator.",
            "Reference other bots naturally if needed, but do not emit coordination protocol text.",
            "Treat routing skills below as delegation hints only. They are not evidence that a skill is active in this conversation or installed on the current bot.",
            "",
            "| Agent | Slug | Role | Routing Skills | Status |",
            "|-------|------|------|----------------|--------|",
        ]
        for agent in agents:
            name = agent.display_name
            slug = agent.slug
            a_role = agent.role
            caps = ", ".join(agent.routing_skills)
            state = agent.connectivity_state or "connected"
            lines.append(f"| {name} | {slug} | {a_role} | {caps} | {state} |")
        lines.append("")
        return "\n".join(lines)

    def preflight_prompt(
        self,
        role: str,
        active_skills: list[str],
        *,
        provider_name: str = "",
        instance_key: str = "",
        guidance_override: str = "",
    ) -> str:
        parts: list[str] = []
        if role:
            stripped = role.strip()
            lower = stripped.lower()
            is_sentence = any(lower.startswith(prefix) for prefix in ("you are", "you're", "act as", "as a"))
            if "\n" in stripped or is_sentence:
                parts.append(stripped + "\n")
            else:
                parts.append(f"You are a {stripped}.\n")
        guidance_text = (guidance_override or "").strip()
        if not guidance_text and provider_name:
            guidance_text = self.published_guidance_text(provider_name, instance_key=instance_key)
        if guidance_text:
            parts.append(guidance_text + "\n")
        tracks = self._tracks(active_skills)
        if tracks:
            labels = ", ".join(
                f"{record.display_name} ({self._skill_kind(record)})"
                for record in tracks
            )
            parts.append(f"Active runtime skills: {labels}.\n")
            if any(self._skill_kind(record) == "prompt" for record in tracks):
                parts.append("Prompt skills will be applied as operator-selected conversation instructions.\n")
            if any(self._skill_kind(record) == "executable" for record in tracks):
                parts.append("Executable skills are enabled through Octopus runtime orchestration.\n")
        return "\n".join(parts) if parts else ""

    @staticmethod
    def _provider_semantics_note(provider_name: str) -> str:
        if provider_name != "codex":
            return ""
        return (
            "## Octopus Skill Semantics\n\n"
            "In Octopus, 'skills' means Octopus runtime skills managed through the bot catalog, "
            "default-for-new-conversations settings, and per-conversation activation. Use the "
            "canonical terms 'available on this bot', 'active in this conversation', and "
            "'advertised for routing' precisely. Use the runtime skill state section in this prompt "
            "as authoritative for the current bot and conversation. Treat active prompt skills as "
            "operator-selected conversation instructions, and active executable skills as runtime-"
            "orchestrated conversation state. "
            "Do not answer in terms of Codex-native skills, session-local SKILL.md files, or any "
            "other non-Octopus skill system. Do not infer factual skill availability, current "
            "conversation activation, or prior skill usage from routing tables alone. If a user "
            "asks who is answering, say the current bot in this conversation is answering; do not "
            "describe yourself as a main assistant, primary assistant, or coordinator."
        )

    def _apply_provider_semantics(self, system_prompt: str, provider_name: str) -> str:
        note = self._provider_semantics_note(provider_name)
        if not note:
            return system_prompt
        if system_prompt:
            return f"{system_prompt}\n\n{note}"
        return note

    def prompt_weight(
        self,
        role: str,
        active_skills: list[str],
        *,
        provider_name: str = "",
        instance_key: str = "",
        guidance_override: str = "",
        available_agents: list[DiscoveredAgentRef] | None = None,
    ) -> int:
        return len(
            self.system_prompt(
                role,
                active_skills,
                provider_name=provider_name,
                instance_key=instance_key,
                guidance_override=guidance_override,
                available_agents=available_agents,
            )
        )

    def provider_config(
        self,
        provider_name: str,
        active_skills: list[str],
        credential_env: CredentialEnvRecord | None = None,
    ) -> ProviderConfigRecord:
        credential_env = credential_env or CredentialEnvRecord()
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
            return ProviderConfigRecord(_resolve_placeholders(config, credential_env)) if config else ProviderConfigRecord()

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
            return ProviderConfigRecord(_resolve_placeholders(config, credential_env)) if config else ProviderConfigRecord()

        return ProviderConfigRecord()

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
                        lines.append(f"MCP server: {server_name} ({record.slug})")
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
                        lines.append(f"Script: {script_name} ({record.slug})")
        return "\n".join(lines)

    def prompt_size_warning(self, role: str, active_skills: list[str]) -> str | None:
        prompt = self.system_prompt(role, active_skills)
        if len(prompt) > PROMPT_SIZE_WARNING_THRESHOLD:
            return (
                f"Composed prompt is {len(prompt):,} chars "
                f"(threshold: {PROMPT_SIZE_WARNING_THRESHOLD:,}). "
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
        return len(prompt), len(prompt) > PROMPT_SIZE_WARNING_THRESHOLD

    def check_prompt_size_cross_chat(
        self,
        data_dir: Path,
        skill_name: str,
        provider_name: str,
        provider_state_factory,
        approval_mode: str,
    ) -> list[str]:
        if self._list_sessions is None or self._load_session is None:
            return []
        warnings: list[str] = []
        catalog = self._catalog()
        for info in self._list_sessions(data_dir):
            active = catalog.filter_resolvable(list(info.get("active_skills", [])))
            if skill_name not in active:
                continue
            session_data = self._load_session(
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
        credential_env: CredentialEnvRecord | None = None,
        working_dir: str = "",
        file_policy: str = "",
        effective_model: str = "",
        guidance_override: str = "",
        available_agents: list[DiscoveredAgentRef] | None = None,
    ) -> RunContext:
        credential_env = credential_env or CredentialEnvRecord()
        provider_config = self.provider_config(provider_name, active_skills, credential_env) if provider_name else ProviderConfigRecord()
        capability_summary = self.capability_summary(provider_name, active_skills) if provider_name else ""
        return RunContext(
            extra_dirs=extra_dirs,
            system_prompt=self._apply_provider_semantics(
                self.system_prompt(
                    role,
                    active_skills,
                    provider_name=provider_name,
                    guidance_override=guidance_override,
                    available_agents=available_agents,
                ),
                provider_name,
            ),
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
        guidance_override: str = "",
    ) -> PreflightContext:
        capability_summary = self.capability_summary(provider_name, active_skills) if provider_name else ""
        return PreflightContext(
            extra_dirs=extra_dirs,
            system_prompt=self._apply_provider_semantics(
                self.preflight_prompt(
                    role,
                    active_skills,
                    provider_name=provider_name,
                    guidance_override=guidance_override,
                ),
                provider_name,
            ),
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

    def cleanup_codex_scripts(self, data_dir: Path, conversation_key: str) -> None:
        scripts_dir = data_dir / "scripts" / filesystem_component_for_key(conversation_key)
        if scripts_dir.is_dir():
            shutil.rmtree(scripts_dir, ignore_errors=True)

    def effective_guidance(self, provider_name: str, *, instance_key: str = "") -> ProviderGuidanceTrackRecord | None:
        return self._store().resolve_provider_guidance(provider_name, instance_key=instance_key)

    def published_guidance_text(self, provider_name: str, *, instance_key: str = "") -> str:
        track = self.effective_guidance(provider_name, instance_key=instance_key)
        return track.revision.content if track is not None else ""

    def draft_guidance_text(
        self,
        provider_name: str,
        *,
        scope_kind: str = "system",
        scope_key: str = "",
    ) -> str:
        track = self._store().get_provider_guidance(
            provider_name,
            scope_kind=scope_kind,
            scope_key=scope_key,
        )
        return track.revision.content if track is not None else ""
