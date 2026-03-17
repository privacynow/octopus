"""Concern-owned use cases for runtime skill credential-setup workflows."""

from __future__ import annotations

from app.credential_flow import build_setup_state, foreign_skill_setup
from app.credential_service import get_credential_service
from app.session_state import SessionState
from app.runtime_skill_setup_port import (
    RuntimeSkillSetupState,
    RuntimeSkillSetupCancellationOutcome,
    RuntimeSkillSetupAdvanceOutcome,
    RuntimeSkillCredentialSatisfactionOutcome,
    RuntimeSkillCredentialClearOutcome,
    CredentialValidator,
    RuntimeSkillSetupPort,
)
from app.skill_activation_service import get_skill_activation_service
from app.skill_lifecycle_service import get_skill_lifecycle_service
from app.skill_types import SkillRequirement
from app.credential_validation import validate_credential
from app.runtime_skill_catalog_use_cases import get_runtime_skill_catalog_use_cases


class RuntimeSkillSetupUseCases(RuntimeSkillSetupPort):
    """Canonical setup workflows shared by Telegram and other surfaces."""

    def _lifecycle(self):
        return get_skill_lifecycle_service()

    def _activation(self):
        return get_skill_activation_service()

    def _catalog(self):
        return get_runtime_skill_catalog_use_cases()

    def _credentials(self):
        return get_credential_service()

    def foreign_setup(
        self,
        session: SessionState,
        *,
        user_id: str,
        skill_name: str | None = None,
    ) -> RuntimeSkillSetupState:
        setup = foreign_skill_setup(session, user_id, skill_name=skill_name)
        if setup is None:
            return RuntimeSkillSetupState(status="none")
        return RuntimeSkillSetupState(status="foreign_setup", setup=setup)

    def cancel(
        self,
        session: SessionState,
        *,
        user_id: str,
        allow_override: bool = False,
    ) -> RuntimeSkillSetupCancellationOutcome:
        decision = self._lifecycle().cancel_setup(
            session,
            user_id=user_id,
            allow_override=allow_override,
        )
        return RuntimeSkillSetupCancellationOutcome(
            status=decision.status,
            mutated=decision.mutated,
            foreign_setup=decision.foreign_setup,
        )

    def check_satisfaction(
        self,
        session: SessionState,
        *,
        user_id: str,
        active_skills: list[str],
    ) -> RuntimeSkillCredentialSatisfactionOutcome:
        if not active_skills:
            return RuntimeSkillCredentialSatisfactionOutcome(
                status="satisfied",
                credential_env={},
            )

        user_creds = self._credentials().load(user_id)
        all_missing: list[tuple[str, list[SkillRequirement]]] = []
        for skill_name in active_skills:
            requirements = self._catalog().requirements(skill_name)
            missing = self._credentials().missing_requirements(
                requirements,
                user_creds.get(skill_name, {}),
            )
            if missing:
                all_missing.append((skill_name, missing))

        if not all_missing:
            return RuntimeSkillCredentialSatisfactionOutcome(
                status="satisfied",
                credential_env=self._credentials().build_env(active_skills, user_creds),
            )

        foreign = foreign_skill_setup(session, user_id)
        if foreign is not None:
            return RuntimeSkillCredentialSatisfactionOutcome(
                status="foreign_setup",
                foreign_setup=foreign,
            )

        skill_name, missing = all_missing[0]
        setup_state = build_setup_state(user_id, skill_name, missing)
        session.awaiting_skill_setup = setup_state
        first_requirement = setup_state.remaining[0] if setup_state.remaining else None
        return RuntimeSkillCredentialSatisfactionOutcome(
            status="needs_setup",
            mutated=True,
            setup_state=setup_state,
            missing_skill=skill_name,
            first_requirement=first_requirement,
        )

    async def submit_credential_value(
        self,
        session: SessionState,
        *,
        user_id: str,
        raw_value: str,
        validator: CredentialValidator = validate_credential,
    ) -> RuntimeSkillSetupAdvanceOutcome:
        setup = session.awaiting_skill_setup
        if not setup or setup.user_id != user_id or not setup.remaining:
            return RuntimeSkillSetupAdvanceOutcome(status="no_setup")

        value = raw_value.strip()
        if not value:
            return RuntimeSkillSetupAdvanceOutcome(status="empty_value")

        req = setup.remaining[0]
        validate_spec = req.get("validate")
        if validate_spec:
            ok, detail = await self._credentials().validate_value(
                SkillRequirement(
                    key=str(req["key"]),
                    prompt=str(req["prompt"]),
                    help_url=str(req.get("help_url")) if req.get("help_url") else None,
                    validate=validate_spec if isinstance(validate_spec, dict) else None,
                ),
                value,
                validator=validator,
            )
            if not ok:
                return RuntimeSkillSetupAdvanceOutcome(
                    status="validation_failed",
                    validation_key=str(req["key"]),
                    validation_error=detail,
                )

        self._credentials().save(
            user_id,
            setup.skill,
            str(req["key"]),
            value,
        )
        decision = self._lifecycle().complete_current_requirement(session, user_id=user_id)
        if decision.status == "next_requirement":
            return RuntimeSkillSetupAdvanceOutcome(
                status="next_requirement",
                mutated=decision.mutated,
                next_requirement=decision.next_requirement,
                skill_name=decision.skill_name,
            )
        if decision.status == "ready":
            return RuntimeSkillSetupAdvanceOutcome(
                status="ready",
                mutated=decision.mutated,
                skill_name=decision.skill_name or setup.skill,
            )
        return RuntimeSkillSetupAdvanceOutcome(status=decision.status, mutated=decision.mutated)

    def apply_cleared_credentials(
        self,
        session: SessionState,
        *,
        user_id: str,
        removed_skills: list[str],
        skill_name: str | None,
    ) -> RuntimeSkillCredentialClearOutcome:
        setup_cleared = False
        setup = session.awaiting_skill_setup
        if setup and setup.user_id == user_id and (skill_name is None or setup.skill == skill_name):
            session.awaiting_skill_setup = None
            setup_cleared = True

        deactivated: list[str] = []
        for name in removed_skills:
            if name in self._activation().list_active(session) and self._catalog().requirements(name):
                if self._activation().deactivate(session, name):
                    deactivated.append(name)

        return RuntimeSkillCredentialClearOutcome(
            mutated=setup_cleared or bool(deactivated),
            setup_cleared=setup_cleared,
            deactivated_skills=tuple(deactivated),
        )


_USE_CASES = RuntimeSkillSetupUseCases()


def get_runtime_skill_setup_use_cases() -> RuntimeSkillSetupUseCases:
    return _USE_CASES
