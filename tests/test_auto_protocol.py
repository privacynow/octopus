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


def test_auto_protocol_generates_requirement_specific_protocol_without_template_classifier():
    session = generate_auto_protocol_session(
        ProtocolAutoDesignRequestRecord(
            surface="registry",
            requirement_text=(
                "Build a compact browser-runnable 2D historical platform fighter prototype "
                "with planning, review, implementation, playtest, UX review, and release evidence. "
                "Keep the scope small enough for a smoke run, but include Local Versus, visible "
                "controls, and a final playable artifact."
            ),
            available_agents=[
                {
                    "agent_id": "agent-1",
                    "display_name": "General Builder",
                    "routing_skills": ["planning", "testing"],
                }
            ],
        )
    )

    assert session.status == "ready"
    assert session.analysis.domain == "requirement-specific"
    assert "experience design" in session.analysis.capabilities
    assert session.validation.ok is True
    stage_names = [stage.display_name.lower() for stage in session.plan.stages]
    assert any("coverage" in name for name in stage_names)
    assert any("experience" in name for name in stage_names)
    assert any("verify" in name for name in stage_names)
    assert any("release evidence" in name for name in stage_names)
    assert len(session.plan.stages) >= 8
    assert session.draft_definition_json.as_dict()["metadata"]["run_inputs"]
    plan_text = " ".join(stage.purpose.lower() for stage in session.plan.stages)
    assert "platform" in plan_text
    assert "fighter" in plan_text
    assert "local" in plan_text
    assert "versus" in plan_text
    assert "playable" in plan_text
    document = session.draft_definition_json.as_dict()
    verify_stage = next(stage for stage in document["stages"] if stage["stage_key"] == "verify_outcome")
    assert "only valid protocol decision is completed" in verify_stage["instructions"]
    assert "When this stage is a review" not in verify_stage["instructions"]
    assert "Do not leave foreground servers" in verify_stage["instructions"]


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
    assert "design_experience" in stage_keys
    assert "review_experience" in stage_keys
    assert "verify_outcome" in stage_keys
    assert "final_evidence" in stage_keys
    assert revised.target_protocol_id == "protocol-1"
    assert revised.draft_definition_json.as_dict()["metadata"]["auto_protocol"]["revision_requests"]


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
