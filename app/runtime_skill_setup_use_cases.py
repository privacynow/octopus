"""Concern-owned use cases for runtime skill credential-setup workflows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from app.request_flow import check_credential_satisfaction, foreign_skill_setup
from app.session_state import AwaitingSkillSetup, SessionState
from app.skill_activation_service import get_skill_activation_service
from app.skill_lifecycle_service import get_skill_lifecycle_service
from app.skills import SkillRequirement, save_user_credential, validate_credential
from app.runtime_skill_catalog_use_cases import get_runtime_skill_catalog_use_cases


Validator = Callable[[SkillRequirement, str], Awaitable[tuple[bool, str]]]


@dataclass(frozen=True)
class RuntimeSkillSetupState:
    status: str
    setup: AwaitingSkillSetup | None = None


@dataclass(frozen=True)
class RuntimeSkillSetupCancellationOutcome:
    status: str
    mutated: bool = False
    foreign_setup: AwaitingSkillSetup | None = None


@dataclass(frozen=True)
class RuntimeSkillSetupAdvanceOutcome:
    status: str
    mutated: bool = False
    validation_key: str = ""
    validation_error: str = ""
    next_requirement: dict[str, object] | None = None
    skill_name: str = ""


@dataclass(frozen=True)
class RuntimeSkillCredentialSatisfactionOutcome:
    status: str
    mutated: bool = False
    credential_env: dict[str, str] | None = None
    foreign_setup: AwaitingSkillSetup | None = None
    setup_state: AwaitingSkillSetup | None = None
    missing_skill: str = ""
    first_requirement: dict[str, object] | None = None


@dataclass(frozen=True)
class RuntimeSkillCredentialClearOutcome:
    mutated: bool
    setup_cleared: bool
    deactivated_skills: tuple[str, ...]


class RuntimeSkillSetupUseCases:
    """Canonical setup workflows shared by Telegram and other surfaces."""

    def _lifecycle(self):
        return get_skill_lifecycle_service()

    def _activation(self):
        return get_skill_activation_service()

    def _catalog(self):
        return get_runtime_skill_catalog_use_cases()

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
        data_dir: Path,
        encryption_key: bytes,
    ) -> RuntimeSkillCredentialSatisfactionOutcome:
        result = check_credential_satisfaction(
            active_skills,
            session,
            user_id,
            data_dir,
            encryption_key,
        )
        if result.satisfied:
            return RuntimeSkillCredentialSatisfactionOutcome(
                status="satisfied",
                credential_env=result.credential_env,
            )
        if result.foreign_setup is not None:
            return RuntimeSkillCredentialSatisfactionOutcome(
                status="foreign_setup",
                foreign_setup=result.foreign_setup,
            )
        if result.setup_state is None:
            return RuntimeSkillCredentialSatisfactionOutcome(status="unsatisfied")
        session.awaiting_skill_setup = result.setup_state
        first_requirement = result.setup_state.remaining[0] if result.setup_state.remaining else None
        return RuntimeSkillCredentialSatisfactionOutcome(
            status="needs_setup",
            mutated=True,
            setup_state=result.setup_state,
            missing_skill=result.missing_skill,
            first_requirement=first_requirement,
        )

    async def submit_credential_value(
        self,
        session: SessionState,
        *,
        user_id: str,
        raw_value: str,
        data_dir: Path,
        encryption_key: bytes,
        validator: Validator = validate_credential,
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
            ok, detail = await validator(
                SkillRequirement(
                    key=str(req["key"]),
                    prompt=str(req["prompt"]),
                    help_url=str(req.get("help_url")) if req.get("help_url") else None,
                    validate=validate_spec if isinstance(validate_spec, dict) else None,
                ),
                value,
            )
            if not ok:
                return RuntimeSkillSetupAdvanceOutcome(
                    status="validation_failed",
                    validation_key=str(req["key"]),
                    validation_error=detail,
                )

        save_user_credential(
            data_dir,
            user_id,
            setup.skill,
            str(req["key"]),
            value,
            encryption_key,
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
