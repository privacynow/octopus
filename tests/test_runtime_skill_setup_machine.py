"""Machine tests for runtime-skill setup progression."""

from app.session_state import AwaitingSkillSetup
from app.workflows.runtime_skills.setup_machine import (
    AdvanceSetupAction,
    CancelSetupAction,
    ClearSkillSetupAction,
    InspectForeignSetupAction,
    SetupSnapshot,
    StartSetupAction,
    decide_setup_action,
)
from app.skill_types import SkillRequirement


def _requirement(key: str) -> SkillRequirement:
    return SkillRequirement(key=key, prompt=f"Enter {key}", help_url=None, validate=None)


def test_setup_machine_start_creates_setup_state() -> None:
    decision = decide_setup_action(
        SetupSnapshot(setup=None),
        StartSetupAction(
            actor_key="tg:42",
            skill_name="github-integration",
            requirements=(_requirement("GITHUB_TOKEN"),),
        ),
    )

    assert decision.status == "started"
    assert decision.ok is True
    assert decision.effects.set_setup is not None
    assert decision.setup_state is not None
    assert decision.next_requirement == {"key": "GITHUB_TOKEN", "prompt": "Enter GITHUB_TOKEN", "help_url": None, "validate": None}


def test_setup_machine_advance_moves_to_next_requirement() -> None:
    setup = AwaitingSkillSetup(
        actor_key="tg:42",
        skill="alpha",
        started_at=1.0,
        remaining=[
            {"key": "TOKEN_A", "prompt": "Enter A", "help_url": None, "validate": None},
            {"key": "TOKEN_B", "prompt": "Enter B", "help_url": None, "validate": None},
        ],
    )

    decision = decide_setup_action(
        SetupSnapshot(setup=setup),
        AdvanceSetupAction(actor_key="tg:42"),
    )

    assert decision.status == "next_requirement"
    assert decision.ok is True
    assert decision.effects.set_setup is not None
    assert decision.effects.activate_skill == ""
    assert decision.next_requirement == {"key": "TOKEN_B", "prompt": "Enter B", "help_url": None, "validate": None}


def test_setup_machine_advance_last_requirement_becomes_ready() -> None:
    setup = AwaitingSkillSetup(
        actor_key="tg:42",
        skill="alpha",
        started_at=1.0,
        remaining=[{"key": "TOKEN_A", "prompt": "Enter A", "help_url": None, "validate": None}],
    )

    decision = decide_setup_action(
        SetupSnapshot(setup=setup),
        AdvanceSetupAction(actor_key="tg:42"),
    )

    assert decision.status == "ready"
    assert decision.ok is True
    assert decision.effects.clear_setup is True
    assert decision.effects.activate_skill == "alpha"


def test_setup_machine_cancel_clears_current_user_setup() -> None:
    setup = AwaitingSkillSetup(
        actor_key="tg:42",
        skill="alpha",
        started_at=1.0,
        remaining=[{"key": "TOKEN_A", "prompt": "Enter A"}],
    )

    decision = decide_setup_action(
        SetupSnapshot(setup=setup),
        CancelSetupAction(actor_key="tg:42"),
    )

    assert decision.status == "cancelled"
    assert decision.effects.clear_setup is True


def test_setup_machine_reports_foreign_setup_for_active_other_user() -> None:
    setup = AwaitingSkillSetup(
        actor_key="tg:99",
        skill="alpha",
        started_at=9999999999.0,
        remaining=[{"key": "TOKEN_A", "prompt": "Enter A"}],
    )

    decision = decide_setup_action(
        SetupSnapshot(setup=setup),
        InspectForeignSetupAction(actor_key="tg:42", skill_name="alpha"),
    )

    assert decision.status == "foreign_setup"
    assert decision.foreign_setup == setup


def test_setup_machine_start_blocks_active_foreign_setup_for_other_skill() -> None:
    setup = AwaitingSkillSetup(
        actor_key="tg:99",
        skill="beta",
        started_at=9999999999.0,
        remaining=[{"key": "TOKEN_B", "prompt": "Enter B"}],
    )

    decision = decide_setup_action(
        SetupSnapshot(setup=setup),
        StartSetupAction(
            actor_key="tg:42",
            skill_name="alpha",
            requirements=(_requirement("TOKEN_A"),),
        ),
    )

    assert decision.status == "foreign_setup"
    assert decision.effects.set_setup is None
    assert decision.foreign_setup == setup


def test_setup_machine_start_replaces_stale_foreign_setup() -> None:
    setup = AwaitingSkillSetup(
        actor_key="tg:99",
        skill="alpha",
        started_at=0.0,
        remaining=[{"key": "TOKEN_OLD", "prompt": "Enter old"}],
    )

    decision = decide_setup_action(
        SetupSnapshot(setup=setup),
        StartSetupAction(
            actor_key="tg:42",
            skill_name="alpha",
            requirements=(_requirement("TOKEN_NEW"),),
        ),
    )

    assert decision.status == "started"
    assert decision.effects.set_setup is not None
    assert decision.setup_state is not None
    assert decision.setup_state.actor_key == "tg:42"
    assert decision.next_requirement == {"key": "TOKEN_NEW", "prompt": "Enter TOKEN_NEW", "help_url": None, "validate": None}


def test_setup_machine_clear_skill_clears_stale_foreign_setup() -> None:
    setup = AwaitingSkillSetup(
        actor_key="tg:99",
        skill="alpha",
        started_at=0.0,
        remaining=[{"key": "TOKEN_A", "prompt": "Enter A"}],
    )

    decision = decide_setup_action(
        SetupSnapshot(setup=setup),
        ClearSkillSetupAction(actor_key="tg:42", skill_name="alpha"),
    )

    assert decision.status == "cleared"
    assert decision.ok is True
    assert decision.effects.clear_setup is True


def test_setup_machine_clear_skill_leaves_other_users_other_skill_setup_unchanged() -> None:
    setup = AwaitingSkillSetup(
        actor_key="tg:99",
        skill="beta",
        started_at=9999999999.0,
        remaining=[{"key": "TOKEN_B", "prompt": "Enter B"}],
    )

    decision = decide_setup_action(
        SetupSnapshot(setup=setup),
        ClearSkillSetupAction(actor_key="tg:42", skill_name="alpha"),
    )

    assert decision.status == "unchanged"
    assert decision.effects.clear_setup is False
