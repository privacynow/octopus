"""Runtime-skill activation workflow ownership."""

from __future__ import annotations

from app.credential_service import get_credential_service
from app.provider_guidance_service import (
    PROMPT_SIZE_WARNING_THRESHOLD,
    get_provider_guidance_service,
)
from octopus_sdk.sessions import SessionState
from app.skill_activation_service import get_skill_activation_service
from octopus_sdk.workflows.skills import (
    ConversationSkillItem,
    ConversationSkillListing,
    ConversationSkillMutationOutcome,
    RuntimeSkillActivationPort,
)
from app.workflows.runtime_skills.catalog import get_runtime_skill_catalog_use_cases
from app.workflows.runtime_skills.setup import get_runtime_skill_setup_use_cases


class RuntimeSkillActivationUseCases(RuntimeSkillActivationPort):
    """Canonical activation flows shared across channel entrypoints."""

    def _catalog(self):
        return get_runtime_skill_catalog_use_cases()

    def _activation(self):
        return get_skill_activation_service()

    def _credentials(self):
        return get_credential_service()

    def _guidance(self):
        return get_provider_guidance_service()

    def _setup(self):
        return get_runtime_skill_setup_use_cases()

    def list_conversation_skills(self, active_skills: list[str]) -> ConversationSkillListing:
        active = tuple(active_skills)
        details: list[ConversationSkillItem] = []
        for skill_name in active:
            summary = self._catalog().get_skill(skill_name)
            if summary is None:
                details.append(
                    ConversationSkillItem(
                        name=skill_name,
                        display_name=skill_name,
                        description="",
                        source_kind="unknown",
                        has_custom_override=False,
                    )
                )
                continue
            details.append(
                ConversationSkillItem(
                    name=summary.name,
                    display_name=summary.display_name,
                    description=summary.description,
                    source_kind=summary.source_kind,
                    has_custom_override=summary.has_custom_override,
                )
            )
        return ConversationSkillListing(active_skills=active, active_skill_details=tuple(details))

    def begin_activate(
        self,
        session: SessionState,
        *,
        actor_key: str,
        skill_name: str,
        confirm: bool = False,
    ) -> ConversationSkillMutationOutcome:
        detail = self._catalog().get_skill(skill_name)
        if detail is None:
            return ConversationSkillMutationOutcome(status="unknown")
        if not detail.can_activate:
            return ConversationSkillMutationOutcome(status="not_published")

        requirements = self._catalog().requirements(skill_name)
        if requirements:
            user_creds = self._credentials().load_for_skills(actor_key, [skill_name])
            missing = self._credentials().missing_requirements(
                requirements,
                user_creds.get(skill_name, {}),
            )
            if missing:
                setup_outcome = self._setup().begin_setup(
                    session,
                    actor_key=actor_key,
                    skill_name=skill_name,
                    requirements=list(missing),
                )
                return ConversationSkillMutationOutcome(
                    status=setup_outcome.status,
                    mutated=setup_outcome.mutated,
                    first_requirement=setup_outcome.first_requirement,
                    foreign_setup_user=setup_outcome.foreign_setup.actor_key if setup_outcome.foreign_setup else "",
                    foreign_setup=setup_outcome.foreign_setup,
                )

        if skill_name in self._activation().list_active(session):
            return ConversationSkillMutationOutcome(status="already_active")

        projected_size, over = self._guidance().estimate_prompt_size(
            session.role,
            self._activation().list_active(session),
            skill_name,
        )
        if over and not confirm:
            return ConversationSkillMutationOutcome(
                status="needs_confirmation",
                projected_size=projected_size,
                prompt_size_threshold=PROMPT_SIZE_WARNING_THRESHOLD,
            )

        mutated = self._activation().activate(session, skill_name)
        return ConversationSkillMutationOutcome(
            status="activated" if mutated else "already_active",
            mutated=mutated,
        )

    def confirm_activate(self, session: SessionState, skill_name: str) -> ConversationSkillMutationOutcome:
        mutated = self._activation().activate(session, skill_name)
        return ConversationSkillMutationOutcome(
            status="activated" if mutated else "already_active",
            mutated=mutated,
        )

    def begin_setup(
        self,
        session: SessionState,
        *,
        actor_key: str,
        skill_name: str,
    ) -> ConversationSkillMutationOutcome:
        detail = self._catalog().get_skill(skill_name)
        if detail is None:
            return ConversationSkillMutationOutcome(status="unknown")
        if not detail.can_activate:
            return ConversationSkillMutationOutcome(status="not_published")
        requirements = self._catalog().requirements(skill_name)
        if not requirements:
            return ConversationSkillMutationOutcome(status="no_requirements")
        decision = self._setup().begin_setup(
            session,
            actor_key=actor_key,
            skill_name=skill_name,
            requirements=list(requirements),
        )
        return ConversationSkillMutationOutcome(
            status=decision.status,
            mutated=decision.mutated,
            first_requirement=decision.first_requirement,
            foreign_setup_user=decision.foreign_setup.actor_key if decision.foreign_setup else "",
            foreign_setup=decision.foreign_setup,
        )

    def deactivate(
        self,
        session: SessionState,
        *,
        actor_key: str,
        skill_name: str,
    ) -> ConversationSkillMutationOutcome:
        setup = self._setup().apply_cleared_credentials(
            session,
            actor_key=actor_key,
            removed_skills=[],
            skill_name=skill_name,
        )
        if session.awaiting_skill_setup is not None and setup.setup_cleared is False:
            foreign = self._setup().foreign_setup(session, actor_key=actor_key, skill_name=skill_name)
            if foreign.status == "foreign_setup":
                return ConversationSkillMutationOutcome(
                    status="foreign_setup",
                    mutated=False,
                    foreign_setup_user=foreign.setup.actor_key if foreign.setup else "",
                    foreign_setup=foreign.setup,
                )
        removed = self._activation().deactivate(session, skill_name)
        return ConversationSkillMutationOutcome(
            status="removed" if removed else "not_active",
            mutated=setup.mutated or removed,
        )

    def clear(
        self,
        session: SessionState,
        *,
        actor_key: str,
    ) -> ConversationSkillMutationOutcome:
        foreign = self._setup().foreign_setup(session, actor_key=actor_key)
        if foreign.status == "foreign_setup":
            return ConversationSkillMutationOutcome(
                status="foreign_setup",
                mutated=False,
                foreign_setup_user=foreign.setup.actor_key if foreign.setup else "",
                foreign_setup=foreign.setup,
            )
        setup_cancel = self._setup().cancel(session, actor_key=actor_key)
        had_active = bool(self._activation().list_active(session))
        self._activation().clear(session)
        return ConversationSkillMutationOutcome(
            status="cleared",
            mutated=setup_cancel.mutated or had_active,
        )


_USE_CASES = RuntimeSkillActivationUseCases()


def get_runtime_skill_activation_use_cases() -> RuntimeSkillActivationUseCases:
    return _USE_CASES
