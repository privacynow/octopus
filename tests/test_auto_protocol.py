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
    assert "experience design" in session.analysis.skills
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
    review_stage = next(stage for stage in document["stages"] if stage["stage_key"] == "review_outcome")
    assert "Critically review Produced Outcome" in review_stage["instructions"]
    assert "choose revise" in review_stage["instructions"].lower()
    assert "Do not accept merely because the stage produced something" in review_stage["instructions"]
    assert session.analysis.work_packages
    assert any(package.package_key == "implementation" for package in session.analysis.work_packages)


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


def test_auto_protocol_adds_direct_review_after_every_generated_work_stage():
    session = generate_auto_protocol_session(
        ProtocolAutoDesignRequestRecord(
            requirement_text=(
                "Build a beautiful browser-runnable historical interactive training demo with "
                "accurate content, polished UX, generated visuals, data loading, security notes, "
                "verification, and release evidence."
            ),
            available_agents=[{"agent_id": "agent-1", "display_name": "Builder"}],
        )
    )

    assert session.status == "ready"
    stages = session.draft_definition_json.as_dict()["stages"]
    review_by_target = {
        str(stage.get("transitions", {}).get("revise") or ""): stage
        for stage in stages
        if stage.get("stage_kind") == "review"
    }
    work_stages = [stage for stage in stages if stage.get("stage_kind") == "work" and stage.get("outputs")]

    assert work_stages
    assert all(stage["stage_key"] in review_by_target for stage in work_stages)
    assert "review_verification" in {stage["stage_key"] for stage in stages}
    assert all("choose revise" in review_by_target[stage["stage_key"]]["instructions"].lower() for stage in work_stages)


def test_auto_protocol_uses_distinct_reviewer_participants_for_review_domains():
    session = generate_auto_protocol_session(
        ProtocolAutoDesignRequestRecord(
            requirement_text=(
                "Create a browser-based customer-facing analytics workflow with data modeling, "
                "domain research, polished UX, supporting content, implementation, verification, "
                "and final evidence."
            ),
            available_agents=[{"agent_id": "agent-1", "display_name": "Builder"}],
        )
    )

    review_roles = [
        stage.role_key
        for stage in session.plan.stages
        if stage.stage_kind == "review"
    ]

    assert len(review_roles) >= 5
    assert len(review_roles) == len(set(review_roles))
    assert not any(item.code == "semantic.review_context_not_isolated" for item in session.unresolved_decisions)


def test_auto_protocol_infers_reviews_without_user_prompting_review_stages():
    session = generate_auto_protocol_session(
        ProtocolAutoDesignRequestRecord(
            requirement_text=(
                "I want to make a beautiful 2D browser game about historical figures with "
                "smooth controls, visuals, sound, accurate references, and a playable result."
            ),
            available_agents=[{"agent_id": "agent-1", "display_name": "Builder"}],
        )
    )

    stage_keys = [stage.stage_key for stage in session.plan.stages]
    review_keys = [stage.stage_key for stage in session.plan.stages if stage.stage_kind == "review"]

    assert "review_requirements" in stage_keys
    assert "review_experience" in stage_keys
    assert "review_outcome" in stage_keys
    assert "review_verification" in stage_keys
    assert len(review_keys) >= 4
    assert "review" not in session.requirement_text.lower()
