"""Functional decision machine for runtime-skill setup progression."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.session_state import AwaitingSkillSetup
from app.skill_types import SkillRequirement
from app.time_utils import age_seconds, utc_now, utc_now_timestamp

SETUP_TIMEOUT_SECONDS = 300


def build_setup_state(
    user_id: str,
    skill_name: str,
    missing: list[SkillRequirement | dict[str, object]],
) -> AwaitingSkillSetup:
    remaining: list[dict[str, object]] = []
    for item in missing:
        if isinstance(item, dict):
            key = str(item.get("key", "") or "")
            if not key:
                continue
            remaining.append(
                {
                    "key": key,
                    "prompt": str(item.get("prompt", "") or ""),
                    "help_url": item.get("help_url"),
                    "validate": item.get("validate"),
                }
            )
            continue
        remaining.append(
            {
                "key": item.key,
                "prompt": item.prompt,
                "help_url": item.help_url,
                "validate": item.validate,
            }
        )
    return AwaitingSkillSetup(
        user_id=user_id,
        skill=skill_name,
        started_at=utc_now_timestamp(),
        remaining=remaining,
    )


@dataclass(frozen=True)
class SetupSnapshot:
    setup: AwaitingSkillSetup | None


@dataclass(frozen=True)
class SetupEffects:
    set_setup: AwaitingSkillSetup | None = None
    clear_setup: bool = False
    activate_skill: str = ""


@dataclass(frozen=True)
class SetupDecision:
    status: str
    ok: bool
    effects: SetupEffects = SetupEffects()
    foreign_setup: AwaitingSkillSetup | None = None
    setup_state: AwaitingSkillSetup | None = None
    next_requirement: dict[str, object] | None = None
    skill_name: str = ""


@dataclass(frozen=True)
class InspectForeignSetupAction:
    user_id: str
    skill_name: str | None = None


@dataclass(frozen=True)
class StartSetupAction:
    user_id: str
    skill_name: str
    requirements: tuple[SkillRequirement | dict[str, object], ...]


@dataclass(frozen=True)
class CancelSetupAction:
    user_id: str
    allow_override: bool = False


@dataclass(frozen=True)
class AdvanceSetupAction:
    user_id: str


@dataclass(frozen=True)
class ClearSkillSetupAction:
    user_id: str
    skill_name: str | None = None


SetupAction = (
    InspectForeignSetupAction
    | StartSetupAction
    | CancelSetupAction
    | AdvanceSetupAction
    | ClearSkillSetupAction
)


def _is_stale_foreign(setup: AwaitingSkillSetup, user_id: str) -> bool:
    if setup.user_id == user_id:
        return False
    age = age_seconds(setup.started_at, now=utc_now())
    return age is not None and age > SETUP_TIMEOUT_SECONDS


def decide_setup_action(snapshot: SetupSnapshot, action: SetupAction) -> SetupDecision:
    setup = snapshot.setup

    if isinstance(action, InspectForeignSetupAction):
        if setup is None or setup.user_id == action.user_id:
            return SetupDecision(status="none", ok=True)
        if action.skill_name is not None and setup.skill != action.skill_name:
            return SetupDecision(status="none", ok=True)
        if _is_stale_foreign(setup, action.user_id):
            return SetupDecision(status="none", ok=True, effects=SetupEffects(clear_setup=True))
        return SetupDecision(status="foreign_setup", ok=True, foreign_setup=setup)

    if isinstance(action, StartSetupAction):
        if not action.requirements:
            return SetupDecision(status="no_requirements", ok=True)
        if setup is not None and setup.user_id != action.user_id:
            if _is_stale_foreign(setup, action.user_id):
                new_setup = build_setup_state(action.user_id, action.skill_name, list(action.requirements))
                return SetupDecision(
                    status="started",
                    ok=True,
                    effects=SetupEffects(set_setup=new_setup),
                    setup_state=new_setup,
                    next_requirement=new_setup.remaining[0] if new_setup.remaining else None,
                    skill_name=action.skill_name,
                )
            return SetupDecision(status="foreign_setup", ok=True, foreign_setup=setup)
        new_setup = build_setup_state(action.user_id, action.skill_name, list(action.requirements))
        return SetupDecision(
            status="started",
            ok=True,
            effects=SetupEffects(set_setup=new_setup),
            setup_state=new_setup,
            next_requirement=new_setup.remaining[0] if new_setup.remaining else None,
            skill_name=action.skill_name,
        )

    if isinstance(action, CancelSetupAction):
        if setup is None:
            return SetupDecision(status="no_setup", ok=True)
        if setup.user_id != action.user_id and not action.allow_override:
            return SetupDecision(status="foreign_setup", ok=True, foreign_setup=setup)
        return SetupDecision(status="cancelled", ok=True, effects=SetupEffects(clear_setup=True))

    if isinstance(action, AdvanceSetupAction):
        if setup is None or setup.user_id != action.user_id or not setup.remaining:
            return SetupDecision(status="no_setup", ok=True)
        if len(setup.remaining) == 1:
            return SetupDecision(
                status="ready",
                ok=True,
                effects=SetupEffects(clear_setup=True, activate_skill=setup.skill),
                skill_name=setup.skill,
            )
        next_setup = AwaitingSkillSetup(
            user_id=setup.user_id,
            skill=setup.skill,
            started_at=setup.started_at,
            remaining=list(setup.remaining[1:]),
        )
        return SetupDecision(
            status="next_requirement",
            ok=True,
            effects=SetupEffects(set_setup=next_setup),
            setup_state=next_setup,
            next_requirement=next_setup.remaining[0],
            skill_name=setup.skill,
        )

    if isinstance(action, ClearSkillSetupAction):
        if setup is None:
            return SetupDecision(status="unchanged", ok=True)
        if setup.user_id != action.user_id:
            if action.skill_name is not None and setup.skill != action.skill_name:
                return SetupDecision(status="unchanged", ok=True)
            if _is_stale_foreign(setup, action.user_id):
                return SetupDecision(status="cleared", ok=True, effects=SetupEffects(clear_setup=True))
            return SetupDecision(status="foreign_setup", ok=True, foreign_setup=setup)
        if action.skill_name is not None and setup.skill != action.skill_name:
            return SetupDecision(status="unchanged", ok=True)
        return SetupDecision(status="cleared", ok=True, effects=SetupEffects(clear_setup=True))

    raise ValueError(f"Unknown setup action: {action!r}")
