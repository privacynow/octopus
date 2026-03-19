"""Conversation settings workflow ownership."""

from __future__ import annotations

from app import user_messages as _msg
from app.config import BotConfig
from app.workflows.conversation.contracts import (
    ModelProfileState,
    SettingMutationOutcome,
    ConversationSettingsPort,
    ProviderStateFactory,
)
from app.execution_context import resolve_execution_context
from app.session_state import SessionState


class ConversationSettingsUseCases(ConversationSettingsPort):
    """Canonical conversation settings flows shared by Telegram and registry actions."""

    def model_profile_state(
        self,
        session: SessionState,
        cfg: BotConfig,
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
            return SettingMutationOutcome(status="invalid", message=_msg.approval_usage())
        if session.approval_mode == value and session.approval_mode_explicit:
            return SettingMutationOutcome(
                status="unchanged",
                message=f"Approval mode set to {value} for this chat.",
            )
        session.approval_mode = value
        session.approval_mode_explicit = True
        return SettingMutationOutcome(
            status="updated",
            mutated=True,
            message=f"Approval mode set to {value} for this chat.",
        )

    def set_compact_mode(self, session: SessionState, value: bool) -> SettingMutationOutcome:
        if session.compact_mode == value:
            label = _msg.settings_compact_on_label() if value else _msg.settings_compact_off_label()
            return SettingMutationOutcome(
                status="unchanged",
                message=f"Compact mode set to <b>{label}</b>.",
                compact_enabled=value,
            )
        session.compact_mode = value
        label = _msg.settings_compact_on_label() if value else _msg.settings_compact_off_label()
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
            return SettingMutationOutcome(
                status="cleared",
                mutated=True,
                message="Role reset to instance default.",
            )
        if session.role == value:
            return SettingMutationOutcome(
                status="unchanged",
                message=f"Role set to: <code>{value}</code>",
            )
        session.role = value
        return SettingMutationOutcome(
            status="updated",
            mutated=True,
            message=f"Role set to: <code>{value}</code>",
        )

    def set_model_profile(
        self,
        session: SessionState,
        profile: str,
        *,
        cfg: BotConfig,
        provider_name: str,
        trust_tier: str,
    ) -> SettingMutationOutcome:
        if profile == "":
            if not session.model_profile:
                return SettingMutationOutcome(
                    status="already_inherited",
                    message="Model profile is already inherited.",
                )
            session.model_profile = ""
            resolved = resolve_execution_context(session, cfg, provider_name, trust_tier=trust_tier)
            effective = resolved.effective_model or cfg.model
            state = self.model_profile_state(session, cfg, trust_tier, effective or "")
            if effective and state.current_profile != "(default)":
                text = (
                    "Model profile cleared. Effective: "
                    f"<code>{state.current_profile}</code> ({effective})"
                )
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
            return SettingMutationOutcome(status="no_profiles", message=_msg.trust_no_model_profiles())
        resolved = resolve_execution_context(session, cfg, provider_name, trust_tier=trust_tier)
        effective = resolved.effective_model or ""
        state = self.model_profile_state(session, cfg, trust_tier, effective)
        available = set(state.available_profiles)
        if profile not in available:
            return SettingMutationOutcome(
                status="not_available",
                message=_msg.trust_model_profile_not_available(profile, list(state.available_profiles)),
            )
        if session.model_profile == profile:
            return SettingMutationOutcome(
                status="unchanged",
                message=_msg.trust_model_profile_set(profile, cfg.model_profiles[profile]),
                effective_model=cfg.model_profiles[profile],
                current_profile=profile,
            )
        session.model_profile = profile
        return SettingMutationOutcome(
            status="updated",
            mutated=True,
            message=_msg.trust_model_profile_set(profile, cfg.model_profiles[profile]),
            effective_model=cfg.model_profiles[profile],
            current_profile=profile,
        )

    def set_project(
        self,
        session: SessionState,
        value: str,
        *,
        cfg: BotConfig,
        provider_state_factory: ProviderStateFactory,
    ) -> SettingMutationOutcome:
        if not cfg.projects:
            return SettingMutationOutcome(status="no_projects", message=_msg.no_projects_configured())
        if value == "clear":
            if not session.project_id:
                return SettingMutationOutcome(status="no_project", message=_msg.trust_no_project_active())
            session.project_id = ""
            session.provider_state = provider_state_factory()
            session.clear_pending()
            return SettingMutationOutcome(
                status="cleared",
                mutated=True,
                message=_msg.trust_project_cleared(str(cfg.working_dir)),
            )
        found = next((proj for proj in cfg.projects if proj.name == value), None)
        if found is None:
            return SettingMutationOutcome(status="unknown", message=_msg.trust_unknown_project(value))
        if session.project_id == value:
            return SettingMutationOutcome(status="unchanged", message=_msg.trust_already_using_project(value))
        session.project_id = value
        session.provider_state = provider_state_factory()
        session.clear_pending()
        return SettingMutationOutcome(
            status="updated",
            mutated=True,
            message=_msg.trust_switched_project(
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
        cfg: BotConfig,
        provider_name: str,
        trust_tier: str,
        provider_state_factory: ProviderStateFactory,
    ) -> SettingMutationOutcome:
        if value == "":
            if not session.file_policy:
                return SettingMutationOutcome(
                    status="already_inherited",
                    message="File policy is already inherited.",
                )
            session.file_policy = ""
            session.provider_state = provider_state_factory()
            session.clear_pending()
            resolved = resolve_execution_context(session, cfg, provider_name, trust_tier=trust_tier)
            effective = resolved.file_policy or "edit"
            return SettingMutationOutcome(
                status="cleared",
                mutated=True,
                message=f"File policy cleared. Effective policy: <code>{effective}</code>",
                effective_policy=effective,
            )
        if value not in {"inspect", "edit"}:
            return SettingMutationOutcome(status="invalid", message="")
        resolved = resolve_execution_context(session, cfg, provider_name, trust_tier=trust_tier)
        effective = resolved.file_policy or "edit"
        if effective == value:
            return SettingMutationOutcome(
                status="unchanged",
                message=f"File policy is already <code>{value}</code>.",
                effective_policy=effective,
            )
        session.file_policy = value
        session.provider_state = provider_state_factory()
        session.clear_pending()
        return SettingMutationOutcome(
            status="updated",
            mutated=True,
            message=_msg.trust_file_policy_set(value),
            effective_policy=value,
        )


_USE_CASES = ConversationSettingsUseCases()


def get_conversation_settings_use_cases() -> ConversationSettingsUseCases:
    return _USE_CASES
