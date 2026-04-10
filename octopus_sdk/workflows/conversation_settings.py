"""SDK-owned conversation settings workflows."""

from __future__ import annotations

from octopus_sdk.config import BotConfigBase
from octopus_sdk.execution_context import resolve_execution_context
from octopus_sdk.messages import MessageTemplatePort
from octopus_sdk.sessions import SessionState
from octopus_sdk.workflows.conversation import (
    ApprovalModeGuard,
    ConversationSettingsPort,
    ModelProfileState,
    ProviderStateFactory,
    SettingMutationOutcome,
)
from octopus_sdk.workflows.skills import RuntimeSkillCatalogPort


class ConversationSettingsUseCases(ConversationSettingsPort):
    """Canonical conversation settings flows shared across channel entrypoints."""

    def __init__(
        self,
        *,
        messages: MessageTemplatePort,
        catalog: RuntimeSkillCatalogPort,
        approval_mode_guard: ApprovalModeGuard | None = None,
    ) -> None:
        self._messages = messages
        self._catalog = catalog
        self._approval_mode_guard = approval_mode_guard

    def _resolve_context(
        self,
        session: SessionState,
        cfg: BotConfigBase,
        provider_name: str,
        trust_tier: str,
    ):
        return resolve_execution_context(
            session,
            cfg,
            provider_name,
            trust_tier=trust_tier,
            catalog=self._catalog,
        )

    def model_profile_state(
        self,
        session: SessionState,
        cfg: BotConfigBase,
        trust_tier: str,
        effective_model: str,
    ) -> ModelProfileState:
        if trust_tier == "public" and cfg.public_model_profiles and cfg.model_profiles:
            available = sorted(cfg.public_model_profiles & cfg.model_profiles.keys())
            current = "(default)"
            for profile in available:
                if cfg.model_profiles.get(profile) == effective_model:
                    current = profile
                    break
            return ModelProfileState(tuple(available), current)
        available = sorted(cfg.model_profiles.keys()) if cfg.model_profiles else []
        if not available:
            return ModelProfileState((), "(default)")
        project_profile = ""
        if session.project_id:
            for proj in cfg.projects:
                if proj.name == session.project_id:
                    project_profile = proj.model_profile
                    break
        current = session.model_profile or project_profile or cfg.default_model_profile or "(default)"
        return ModelProfileState(tuple(available), current)

    def set_approval_mode(self, session: SessionState, value: str) -> SettingMutationOutcome:
        if value not in {"on", "off"}:
            return SettingMutationOutcome(status="invalid", message=self._messages.approval_usage())
        if self._approval_mode_guard is not None:
            guard_error = self._approval_mode_guard(value)
            if guard_error:
                return SettingMutationOutcome(status="blocked", message=guard_error)
        if session.approval_mode == value and session.approval_mode_explicit:
            return SettingMutationOutcome(
                status="unchanged",
                message=f"Approval mode set to {value} for this chat.",
            )
        session.approval_mode = value
        session.approval_mode_explicit = True
        session.clear_pending()
        return SettingMutationOutcome(
            status="updated",
            mutated=True,
            message=f"Approval mode set to {value} for this chat.",
        )

    def set_compact_mode(self, session: SessionState, value: bool) -> SettingMutationOutcome:
        if session.compact_mode == value:
            label = self._messages.settings_compact_on_label() if value else self._messages.settings_compact_off_label()
            return SettingMutationOutcome(
                status="unchanged",
                message=f"Compact mode set to <b>{label}</b>.",
                compact_enabled=value,
            )
        session.compact_mode = value
        label = self._messages.settings_compact_on_label() if value else self._messages.settings_compact_off_label()
        return SettingMutationOutcome(
            status="updated",
            mutated=True,
            message=f"Compact mode set to <b>{label}</b>.",
            compact_enabled=value,
        )

    def set_role(self, session: SessionState, value: str, *, default_role: str) -> SettingMutationOutcome:
        if not value:
            if session.role == default_role:
                return SettingMutationOutcome(status="unchanged", message="Role reset to instance default.")
            session.role = default_role
            return SettingMutationOutcome(status="cleared", mutated=True, message="Role reset to instance default.")
        if session.role == value:
            return SettingMutationOutcome(status="unchanged", message=f"Role set to: <code>{value}</code>")
        session.role = value
        return SettingMutationOutcome(status="updated", mutated=True, message=f"Role set to: <code>{value}</code>")

    def set_model_profile(
        self,
        session: SessionState,
        profile: str,
        *,
        cfg: BotConfigBase,
        provider_name: str,
        trust_tier: str,
    ) -> SettingMutationOutcome:
        if profile == "":
            if not session.model_profile:
                return SettingMutationOutcome(status="already_inherited", message="Model profile is already inherited.")
            session.model_profile = ""
            resolved = self._resolve_context(session, cfg, provider_name, trust_tier)
            effective = resolved.effective_model or cfg.model
            state = self.model_profile_state(session, cfg, trust_tier, effective or "")
            if effective and state.current_profile != "(default)":
                text = f"Model profile cleared. Effective: <code>{state.current_profile}</code> ({effective})"
            else:
                text = "Model profile cleared. Using default model."
            return SettingMutationOutcome(
                status="cleared",
                mutated=True,
                message=text,
                effective_model=effective,
                current_profile=state.current_profile,
            )
        if not cfg.model_profiles:
            if session.model_profile:
                return SettingMutationOutcome(
                    status="no_profiles_stale_override",
                    message=(
                        "No model profiles configured, but this chat has a stale override "
                        f"(<code>{session.model_profile}</code>). Use /model inherit to clear it."
                    ),
                )
            return SettingMutationOutcome(status="no_profiles", message=self._messages.trust_no_model_profiles())
        resolved = self._resolve_context(session, cfg, provider_name, trust_tier)
        effective = resolved.effective_model or ""
        state = self.model_profile_state(session, cfg, trust_tier, effective)
        available = set(state.available_profiles)
        if profile not in available:
            return SettingMutationOutcome(
                status="not_available",
                message=self._messages.trust_model_profile_not_available(profile, list(state.available_profiles)),
            )
        if session.model_profile == profile:
            return SettingMutationOutcome(
                status="unchanged",
                message=self._messages.trust_model_profile_set(profile, cfg.model_profiles[profile]),
                effective_model=cfg.model_profiles[profile],
                current_profile=profile,
            )
        session.model_profile = profile
        return SettingMutationOutcome(
            status="updated",
            mutated=True,
            message=self._messages.trust_model_profile_set(profile, cfg.model_profiles[profile]),
            effective_model=cfg.model_profiles[profile],
            current_profile=profile,
        )

    def set_project(
        self,
        session: SessionState,
        value: str,
        *,
        cfg: BotConfigBase,
        provider_state_factory: ProviderStateFactory,
        conversation_key: str,
    ) -> SettingMutationOutcome:
        if not cfg.projects:
            return SettingMutationOutcome(status="no_projects", message=self._messages.no_projects_configured())
        if value == "clear" and len(cfg.projects) == 1:
            value = cfg.projects[0].name
        if value == "clear":
            if not session.project_id:
                return SettingMutationOutcome(status="no_project", message=self._messages.trust_no_project_active())
            session.project_id = ""
            session.provider_state = provider_state_factory(conversation_key)
            session.clear_pending()
            return SettingMutationOutcome(
                status="cleared",
                mutated=True,
                message=self._messages.trust_project_cleared(str(cfg.working_dir)),
            )
        found = next((proj for proj in cfg.projects if proj.name == value), None)
        if found is None:
            return SettingMutationOutcome(status="unknown", message=self._messages.trust_unknown_project(value))
        if session.project_id == value:
            return SettingMutationOutcome(status="unchanged", message=self._messages.trust_already_using_project(value))
        session.project_id = value
        session.provider_state = provider_state_factory(conversation_key)
        session.clear_pending()
        return SettingMutationOutcome(
            status="updated",
            mutated=True,
            message=self._messages.trust_switched_project(
                value,
                str(found.root_dir),
                file_policy=found.file_policy,
                model_profile=found.model_profile,
            ),
        )

    def set_file_policy(
        self,
        session: SessionState,
        value: str,
        *,
        cfg: BotConfigBase,
        provider_name: str,
        trust_tier: str,
        provider_state_factory: ProviderStateFactory,
        conversation_key: str,
    ) -> SettingMutationOutcome:
        if value == "":
            if not session.file_policy:
                return SettingMutationOutcome(status="already_inherited", message="File policy is already inherited.")
            session.file_policy = ""
            session.provider_state = provider_state_factory(conversation_key)
            session.clear_pending()
            resolved = self._resolve_context(session, cfg, provider_name, trust_tier)
            effective = resolved.file_policy or "edit"
            return SettingMutationOutcome(
                status="cleared",
                mutated=True,
                message=f"File policy cleared. Effective policy: <code>{effective}</code>",
                effective_policy=effective,
            )
        if value not in {"inspect", "edit"}:
            return SettingMutationOutcome(status="invalid", message="")
        resolved = self._resolve_context(session, cfg, provider_name, trust_tier)
        effective = resolved.file_policy or "edit"
        if effective == value:
            return SettingMutationOutcome(
                status="unchanged",
                message=f"File policy is already <code>{value}</code>.",
                effective_policy=effective,
            )
        session.file_policy = value
        session.provider_state = provider_state_factory(conversation_key)
        session.clear_pending()
        return SettingMutationOutcome(
            status="updated",
            mutated=True,
            message=self._messages.trust_file_policy_set(value),
            effective_policy=value,
        )
