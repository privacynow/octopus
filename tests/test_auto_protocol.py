from octopus_sdk.protocols import (
    ProtocolAutoDesignPlanRecord,
    ProtocolAutoDesignRequestRecord,
    ProtocolAutoDesignRolePlanRecord,
    ProtocolAutoDesignStagePlanRecord,
    compile_auto_protocol_plan,
    generate_auto_protocol_session,
    revise_auto_protocol_session,
)
from octopus_sdk.protocols.auto_design import _validate_and_repair_protocol_document


def test_auto_protocol_generates_domain_specific_game_protocol():
    session = generate_auto_protocol_session(
        ProtocolAutoDesignRequestRecord(
            surface="registry",
            requirement_text=(
                "Build a beautiful 2D browser platformer and fighting game with "
                "historical figures, accurate character abilities, humor, sprites, "
                "backgrounds, sound, playtesting, and browser delivery."
            ),
            available_agents=[
                {
                    "agent_id": "agent-1",
                    "display_name": "General Builder",
                    "routing_skills": ["game", "testing"],
                }
            ],
        )
    )

    assert session.status == "ready"
    assert session.analysis.domain == "game-development"
    assert session.validation.ok is True
    stage_names = [stage.display_name.lower() for stage in session.plan.stages]
    assert any("histor" in name for name in stage_names)
    assert any("playtest" in name for name in stage_names)
    assert any("implement playable" in name for name in stage_names)
    assert len(session.plan.stages) >= 8
    assert session.draft_definition_json.as_dict()["metadata"]["run_inputs"]
    document = session.draft_definition_json.as_dict()
    playtest_stage = next(stage for stage in document["stages"] if stage["stage_key"] == "playtest")
    assert "only valid protocol decision is completed" in playtest_stage["instructions"]
    assert "When this stage is a review" not in playtest_stage["instructions"]
    assert "Do not leave foreground servers" in playtest_stage["instructions"]


def test_auto_protocol_revision_updates_existing_canonical_document():
    original = generate_auto_protocol_session(
        ProtocolAutoDesignRequestRecord(
            requirement_text="Build a browser analytics dashboard.",
            available_agents=[{"agent_id": "agent-1", "display_name": "Builder"}],
        )
    )

    revised = revise_auto_protocol_session(
        ProtocolAutoDesignRequestRecord(
            mode="revise",
            surface="telegram",
            requirement_text="Add a UX reviewer and test evidence before final acceptance.",
            source_document=original.draft_definition_json,
            target_protocol_id="protocol-1",
            available_agents=[{"agent_id": "agent-1", "display_name": "Builder"}],
        ),
        session_id=original.session_id,
        created_at=original.created_at,
        updated_at=original.updated_at,
    )

    assert revised.validation.ok is True
    stage_keys = [stage["stage_key"] for stage in revised.draft_definition_json.as_dict()["stages"]]
    assert "ux_review" in stage_keys
    assert "test_evidence" in stage_keys
    assert revised.target_protocol_id == "protocol-1"


def test_auto_protocol_repairs_structural_validation_errors_before_surface():
    invalid_plan = ProtocolAutoDesignPlanRecord(
        protocol_name="Broken Generated Protocol",
        protocol_slug="",
        description="Broken generated protocol.",
        roles=[
            ProtocolAutoDesignRolePlanRecord(
                role_key="worker",
                display_name="Worker",
                responsibility="Produce the work.",
            )
        ],
        stages=[
            ProtocolAutoDesignStagePlanRecord(
                stage_key="build",
                display_name="Build",
                stage_kind="work",
                role_key="missing_participant",
                purpose="Build the output.",
                outputs=["missing_artifact"],
            ),
            ProtocolAutoDesignStagePlanRecord(
                stage_key="review",
                display_name="Review",
                stage_kind="review",
                role_key="worker",
                purpose="Review the output.",
                inputs=["missing_artifact"],
                review_of_stage_key="not_a_stage",
            ),
        ],
    )
    compiled = compile_auto_protocol_plan(invalid_plan)
    compiled["metadata"]["slug"] = ""
    compiled["participants"] = []
    compiled["artifacts"] = []
    compiled["stages"][0].pop("selector", None)
    compiled["stages"][1]["transitions"] = {"accept": "does_not_exist"}

    repaired, validation, notes = _validate_and_repair_protocol_document(
        compiled,
        ProtocolAutoDesignRequestRecord(
            requirement_text="Build a usable output.",
            available_agents=[{"agent_id": "agent-1", "display_name": "Builder"}],
        ),
    )

    assert validation.ok is True
    assert notes
    assert repaired["metadata"]["slug"]
    assert repaired["participants"]
    assert repaired["artifacts"]
    assert repaired["stages"][0]["selector"] == {"kind": "agent", "value": "agent-1"}
