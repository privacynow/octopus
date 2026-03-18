"""Runtime-skill setup workflow ownership."""

from __future__ import annotations

from app.credential_service import get_credential_service
from app.credential_types import CredentialValidator
from app.credential_validation import validate_credential
from app.session_state import SessionState
from app.workflows.runtime_skills.contracts import (
    RuntimeSkillSetupState,
    RuntimeSkillSetupCancellationOutcome,
    RuntimeSkillSetupAdvanceOutcome,
    RuntimeSkillCredentialSatisfactionOutcome,
    RuntimeSkillCredentialClearOutcome,
    RuntimeSkillSetupPort,
)
from app.skill_activation_service import get_skill_activation_service
from app.skill_types import SkillRequirement
from app.workflows.runtime_skills.catalog import get_runtime_skill_catalog_use_cases
from app.workflows.runtime_skills.setup_machine import (
    AdvanceSetupAction,
    CancelSetupAction,
    ClearSkillSetupAction,
    InspectForeignSetupAction,
    SetupDecision,
    SetupSnapshot,
    StartSetupAction,
    decide_setup_action,
)


class RuntimeSkillSetupUseCases(RuntimeSkillSetupPort):
    """Canonical setup workflows shared by Telegram and other surfaces."""

    def _activation(self):
        return get_skill_activation_service()

    def _catalog(self):
        return get_runtime_skill_catalog_use_cases()

    def _credentials(self):
        return get_credential_service()

    def _snapshot(self, session: SessionState) -> SetupSnapshot:
        return SetupSnapshot(setup=session.awaiting_skill_setup)

    def _apply_machine_decision(self, session: SessionState, decision: SetupDecision) -> bool:
        mutated = False
        if decision.effects.clear_setup and session.awaiting_skill_setup is not None:
            session.awaiting_skill_setup = None
            mutated = True
        if decision.effects.set_setup is not None:
            session.awaiting_skill_setup = decision.effects.set_setup
            mutated = True
        if decision.effects.activate_skill:
            mutated = self._activation().activate(session, decision.effects.activate_skill) or mutated
        return mutated

    def begin_setup(
        self,
        session: SessionState,
        *,
        user_id: str,
        skill_name: str,
        requirements: list[SkillRequirement | dict[str, object]],
    ) -> RuntimeSkillCredentialSatisfactionOutcome:
        decision = decide_setup_action(
            self._snapshot(session),
            StartSetupAction(
                user_id=user_id,
                skill_name=skill_name,
                requirements=tuple(requirements),
            ),
        )
        mutated = self._apply_machine_decision(session, decision)
        return RuntimeSkillCredentialSatisfactionOutcome(
            status=("needs_setup" if decision.status == "started" else decision.status),
            mutated=mutated,
            foreign_setup=decision.foreign_setup,
            setup_state=decision.setup_state,
            missing_skill=skill_name,
            first_requirement=decision.next_requirement,
        )

    def foreign_setup(
        self,
        session: SessionState,
        *,
        user_id: str,
        skill_name: str | None = None,
    ) -> RuntimeSkillSetupState:
        decision = decide_setup_action(
            self._snapshot(session),
            InspectForeignSetupAction(user_id=user_id, skill_name=skill_name),
        )
        self._apply_machine_decision(session, decision)
        if decision.status != "foreign_setup":
            return RuntimeSkillSetupState(status="none")
        return RuntimeSkillSetupState(status="foreign_setup", setup=decision.foreign_setup)

    def cancel(
        self,
        session: SessionState,
        *,
        user_id: str,
        allow_override: bool = False,
    ) -> RuntimeSkillSetupCancellationOutcome:
        decision = decide_setup_action(
            self._snapshot(session),
            CancelSetupAction(
                user_id=user_id,
                allow_override=allow_override,
            ),
        )
        mutated = self._apply_machine_decision(session, decision)
        return RuntimeSkillSetupCancellationOutcome(
            status=decision.status,
            mutated=mutated,
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

        skill_name, missing = all_missing[0]
        return self.begin_setup(
            session,
            user_id=user_id,
            skill_name=skill_name,
            requirements=list(missing),
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
        decision = decide_setup_action(
            self._snapshot(session),
            AdvanceSetupAction(user_id=user_id),
        )
        mutated = self._apply_machine_decision(session, decision)
        if decision.status == "next_requirement":
            return RuntimeSkillSetupAdvanceOutcome(
                status="next_requirement",
                mutated=mutated,
                next_requirement=decision.next_requirement,
                skill_name=decision.skill_name,
            )
        if decision.status == "ready":
            return RuntimeSkillSetupAdvanceOutcome(
                status="ready",
                mutated=mutated,
                skill_name=decision.skill_name or setup.skill,
            )
        return RuntimeSkillSetupAdvanceOutcome(status=decision.status, mutated=mutated)

    def apply_cleared_credentials(
        self,
        session: SessionState,
        *,
        user_id: str,
        removed_skills: list[str],
        skill_name: str | None,
    ) -> RuntimeSkillCredentialClearOutcome:
        decision = decide_setup_action(
            self._snapshot(session),
            ClearSkillSetupAction(user_id=user_id, skill_name=skill_name),
        )
        setup_cleared = self._apply_machine_decision(session, decision)

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
