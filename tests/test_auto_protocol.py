from octopus_sdk.protocols import (
    ProtocolDefinitionDocumentRecord,
    ProtocolAutoDesignModelResponseRecord,
    ProtocolAutoDesignPlanRecord,
    ProtocolAutoDesignRequestRecord,
    ProtocolAutoDesignRolePlanRecord,
    ProtocolAutoDesignStagePlanRecord,
    ProtocolAutoDesignWorkPackageRecord,
    ProtocolRunRecord,
    compile_auto_protocol_plan,
    generate_auto_protocol_session,
    protocol_stage_runtime_contract,
    render_protocol_stage_prompt,
    revise_auto_protocol_session,
)
from octopus_sdk.protocols.auto_design import _validate_and_repair_protocol_document, auto_protocol_event_summary
from octopus_sdk.protocols.models import ProtocolRunMutationRecord


def _planner_response(*package_keys: str) -> ProtocolAutoDesignModelResponseRecord:
    packages = [
        ProtocolAutoDesignWorkPackageRecord(
            package_key=key,
            display_name=key.replace("_", " ").title(),
            rationale=f"{key} is required by the semantic planner.",
            purpose=f"Produce {key.replace('_', ' ')} for the requested outcome.",
            quality_bar="The artifact is specific, actionable, inspectable, and ready for downstream use.",
            required_skills=[key.replace("_", " ")],
        )
        for key in package_keys
    ]
    return ProtocolAutoDesignModelResponseRecord(
        requirement_summary="Create the requested outcome.",
        domain="requirement-specific",
        work_packages=packages or [
            ProtocolAutoDesignWorkPackageRecord(
                package_key="implementation",
                display_name="Integrated Outcome",
                rationale="The user asked for a produced outcome.",
                purpose="Produce the final integrated outcome.",
                quality_bar="The outcome is usable and inspectable.",
                required_skills=["implementation"],
            )
        ],
        acceptance_criteria=["The primary artifact is produced, inspectable, reviewed, and supported by release evidence."],
    )


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
            model_response=_planner_response(
                "experience_design",
                "domain_grounding",
                "supporting_assets",
            ),
        )
    )

    assert session.status == "ready"
    assert session.analysis.domain == "requirement-specific"
    assert "experience design" in session.analysis.skills
    assert session.validation.ok is True
    stage_names = [stage.display_name.lower() for stage in session.plan.stages]
    assert any("coverage" in name for name in stage_names)
    assert any("experience" in name for name in stage_names)
    assert any("accept" in name for name in stage_names)
    assert len(session.plan.stages) >= 8
    assert len(session.plan.stages) <= 18
    assert session.plan.primary_artifact.artifact_key == "produced_outcome"
    run_input_keys = [
        str(field.get("key") or "")
        for field in session.draft_definition_json.as_dict()["metadata"]["run_inputs"]
    ]
    assert "problem_statement" in run_input_keys
    assert "goal" not in run_input_keys
    plan_text = " ".join(stage.purpose.lower() for stage in session.plan.stages)
    assert "platform" in plan_text
    assert "fighter" in plan_text
    assert "local" in plan_text
    assert "versus" in plan_text
    assert "playable" in plan_text
    document = session.draft_definition_json.as_dict()
    produce_stage = next(stage for stage in document["stages"] if stage["stage_key"] == "produce_outcome")
    assert "only valid protocol decision is completed" in produce_stage["instructions"]
    assert "Do not leave foreground servers" in produce_stage["instructions"]
    acceptance_stage = next(stage for stage in document["stages"] if stage["stage_key"] == "final_evidence")
    assert acceptance_stage["transitions"]["revise"] == "produce_outcome"
    assert "Adversarially" in acceptance_stage["instructions"]
    assert "exercise" in acceptance_stage["instructions"]
    assert "octopus-runtime.json" in acceptance_stage["instructions"]
    assert "choose revise" in acceptance_stage["instructions"].lower()
    assert document["metadata"]["auto_protocol"]["primary_artifact"]["open_behavior"] == "runtime"
    assert any(
        "root octopus-runtime.json" in item
        for item in document["metadata"]["auto_protocol"]["primary_artifact"]["evidence_requirements"]
    )
    assert session.analysis.work_packages
    assert any(package.package_key == "implementation" for package in session.analysis.work_packages)


def test_auto_protocol_normalizes_and_surfaces_planner_warning_strings():
    response = _planner_response("experience_design").model_copy(update={
        "warnings": [
            "Keep this scoped to a first delivery tranche.",
        ],
    })
    session = generate_auto_protocol_session(
        ProtocolAutoDesignRequestRecord(
            requirement_text="Build a browser-runnable risk decision engine demo with Java verification.",
            available_agents=[{"agent_id": "agent-1", "display_name": "Builder"}],
            model_response=response,
        )
    )

    planner_warning = next(item for item in session.warnings if item.code == "planner.warning_1")
    assert planner_warning.message == "Keep this scoped to a first delivery tranche."
    assert planner_warning.severity == "warning"
    assert session.status == "ready"


def test_auto_protocol_accepts_model_run_inputs_with_display_keys():
    response = _planner_response("implementation").model_copy(update={
        "run_inputs": [
            {
                "key": "Goal",
                "label": "Delivery goal",
                "kind": "textarea",
                "required": False,
                "default_value": "Build the first delivery tranche.",
            },
            {
                "key": "Risk Domain",
                "label": "Risk domain",
                "kind": "text",
                "required": False,
            },
        ],
    })
    session = generate_auto_protocol_session(
        ProtocolAutoDesignRequestRecord(
            requirement_text="Build a browser-runnable risk decision engine demo with Java verification.",
            constraints_text="Keep it bounded.",
            available_agents=[{"agent_id": "agent-1", "display_name": "Builder"}],
            model_response=response,
        )
    )

    run_inputs = session.draft_definition_json.as_dict()["metadata"]["run_inputs"]
    keys = [field["key"] for field in run_inputs]
    assert keys[:2] == ["problem_statement", "risk_domain"]
    assert "Goal" not in keys
    assert "constraints" in keys
    assert run_inputs[0]["required"] is True


def test_auto_protocol_event_summary_uses_existing_run_id_field_from_protocol_run_record():
    session = generate_auto_protocol_session(
        ProtocolAutoDesignRequestRecord(
            requirement_text="Build a browser-runnable risk decision engine demo with Java verification.",
            available_agents=[{"agent_id": "agent-1", "display_name": "Builder"}],
            model_response=_planner_response("implementation"),
        )
    )
    run_result = ProtocolRunMutationRecord.model_validate({
        "ok": True,
        "status": "created",
        "run": {
            "protocol_run_id": "run-auto",
            "protocol_id": "protocol-auto",
            "protocol_definition_version_id": "version-1",
            "status": "running",
        },
    })

    summary = auto_protocol_event_summary(session.model_copy(update={"run_result": run_result}), event_kind="run_started")

    assert summary.event_kind == "run_started"
    assert summary.run_id == "run-auto"
    assert "protocol_run_id" not in summary.model_dump(mode="json")


def test_auto_protocol_revision_updates_existing_canonical_document():
    original = generate_auto_protocol_session(
        ProtocolAutoDesignRequestRecord(
            requirement_text="Build a browser analytics dashboard.",
            available_agents=[{"agent_id": "agent-1", "display_name": "Builder"}],
            model_response=_planner_response("experience_design", "input_model"),
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
            model_response=_planner_response("experience_design", "input_model"),
        ),
        session_id=original.session_id,
        created_at=original.created_at,
        updated_at=original.updated_at,
    )

    assert revised.validation.ok is True
    stage_keys = [stage["stage_key"] for stage in revised.draft_definition_json.as_dict()["stages"]]
    assert "design_experience" in stage_keys
    assert "review_experience" in stage_keys
    assert "produce_outcome" in stage_keys
    assert "final_evidence" in stage_keys
    assert revised.target_protocol_id == "protocol-1"
    assert revised.draft_definition_json.as_dict()["metadata"]["auto_protocol"]["revision_requests"]


def test_auto_protocol_revision_preserves_planner_blockers_after_second_validation():
    original = generate_auto_protocol_session(
        ProtocolAutoDesignRequestRecord(
            requirement_text="Build a browser analytics dashboard.",
            available_agents=[{"agent_id": "agent-1", "display_name": "Builder"}],
            model_response=_planner_response("experience_design", "input_model"),
        )
    )
    blocking_response = _planner_response("experience_design", "input_model").model_copy(update={
        "open_questions": ["Which source system owns the risk decision audit trail?"],
    })

    revised = revise_auto_protocol_session(
        ProtocolAutoDesignRequestRecord(
            mode="revise",
            requirement_text="Add audit-trail requirements.",
            source_document=original.draft_definition_json,
            target_protocol_id="protocol-1",
            available_agents=[{"agent_id": "agent-1", "display_name": "Builder"}],
            model_response=blocking_response,
        )
    )

    blocker_codes = {item.code for item in revised.unresolved_decisions}
    assert "planner.open_questions" in blocker_codes
    assert revised.status == "blocked"


def test_auto_protocol_session_preserves_raw_planner_response_for_audit():
    response = _planner_response("experience_design", "input_model").model_copy(update={
        "planner_ref": "test-planner",
    })

    session = generate_auto_protocol_session(
        ProtocolAutoDesignRequestRecord(
            requirement_text="Build a browser analytics dashboard.",
            available_agents=[{"agent_id": "agent-1", "display_name": "Builder"}],
            model_response=response,
        )
    )

    assert session.model_response is not None
    assert session.model_response.planner_ref == "test-planner"
    assert [item.package_key for item in session.model_response.work_packages] == ["experience_design", "input_model"]


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
            model_response=_planner_response(
                "domain_grounding",
                "experience_design",
                "supporting_assets",
                "input_model",
                "risk_assessment",
            ),
        )
    )

    assert session.status == "ready"
    stages = session.draft_definition_json.as_dict()["stages"]
    gate_by_target = {
        str(stage.get("transitions", {}).get("revise") or ""): stage
        for stage in stages
        if stage.get("stage_kind") in {"review", "acceptance"}
    }
    work_stages = [stage for stage in stages if stage.get("stage_kind") == "work" and stage.get("outputs")]

    assert work_stages
    assert all(stage["stage_key"] in gate_by_target for stage in work_stages)
    assert "review_verification" not in {stage["stage_key"] for stage in stages}
    assert all("choose revise" in gate_by_target[stage["stage_key"]]["instructions"].lower() for stage in work_stages)
    assert stages[-2]["stage_key"] == "produce_outcome"
    assert stages[-1]["stage_key"] == "final_evidence"


def test_auto_protocol_uses_distinct_reviewer_participants_for_review_domains():
    session = generate_auto_protocol_session(
        ProtocolAutoDesignRequestRecord(
            requirement_text=(
                "Create a browser-based customer-facing analytics workflow with data modeling, "
                "domain research, polished UX, supporting content, implementation, verification, "
                "and final evidence."
            ),
            available_agents=[{"agent_id": "agent-1", "display_name": "Builder"}],
            model_response=_planner_response(
                "input_model",
                "domain_grounding",
                "experience_design",
                "supporting_assets",
                "risk_assessment",
            ),
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


def test_auto_protocol_repairs_duplicate_planner_review_roles_before_surface():
    response = _planner_response("input_model", "experience_design", "supporting_assets")
    response = response.model_copy(update={
        "work_packages": [
            package.model_copy(update={
                "review_role_key": "requirements_reviewer",
                "review_display_name": "Requirement Coverage Reviewer",
                "review_artifact_key": "requirements_review",
            })
            for package in response.work_packages
        ],
    })
    session = generate_auto_protocol_session(
        ProtocolAutoDesignRequestRecord(
            requirement_text=(
                "Create a browser-runnable onboarding risk checklist with a polished HTML "
                "artifact, concise support-manager guidance, and final release evidence."
            ),
            available_agents=[{"agent_id": "agent-1", "display_name": "Builder"}],
            model_response=response,
        )
    )

    review_roles = [
        stage.role_key
        for stage in session.plan.stages
        if stage.stage_kind == "review"
    ]

    assert session.status == "ready"
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
            model_response=_planner_response("experience_design", "domain_grounding", "supporting_assets"),
        )
    )

    stage_keys = [stage.stage_key for stage in session.plan.stages]
    review_keys = [stage.stage_key for stage in session.plan.stages if stage.stage_kind == "review"]

    assert "review_requirements" in stage_keys
    assert "review_experience" in stage_keys
    assert "review_outcome" not in stage_keys
    assert "review_verification" not in stage_keys
    assert stage_keys[-2] == "produce_outcome"
    assert stage_keys[-1] == "final_evidence"
    assert len(review_keys) >= 4
    assert "review" not in session.requirement_text.lower()


def test_auto_protocol_splits_complex_human_facing_work_into_production_layers():
    session = generate_auto_protocol_session(
        ProtocolAutoDesignRequestRecord(
            requirement_text=(
                "Build a beautiful browser-runnable interactive product with accurate references, "
                "smooth controls, polished visuals, animated backgrounds, character variety, "
                "multiple levels, sound, playtesting, and release evidence."
            ),
            available_agents=[{"agent_id": "agent-1", "display_name": "Builder"}],
            model_response=_planner_response(
                "production_foundation",
                "interaction_layer",
                "visual_media_layer",
                "content_variation_layer",
                "domain_content_layer",
            ),
        )
    )

    package_keys = [package.package_key for package in session.analysis.work_packages]
    stage_keys = [stage.stage_key for stage in session.plan.stages]

    assert session.status == "ready"
    assert len(session.plan.stages) <= 18
    assert "production_foundation" in package_keys
    assert "interaction_layer" in package_keys
    assert "visual_media_layer" in package_keys
    assert "content_variation_layer" in package_keys
    assert "domain_content_layer" in package_keys
    assert stage_keys.index("build_production_foundation") < stage_keys.index("produce_outcome")
    assert stage_keys.index("build_visual_media_layer") < stage_keys.index("produce_outcome")
    assert "review_visual_media_layer" in stage_keys
    assert "review_content_variation_layer" in stage_keys


def test_auto_protocol_applies_same_production_slicing_to_analytics_requirements():
    session = generate_auto_protocol_session(
        ProtocolAutoDesignRequestRecord(
            requirement_text=(
                "Build a browser-runnable manufacturing analytics command center for plant leaders. "
                "It should load or generate realistic operations data, guide users from data readiness "
                "to executive insights, include dashboards, charts, drill-down dimensions, bottleneck "
                "and quality analytics, what-if views, clear explanations, review evidence, and "
                "release-ready artifacts."
            ),
            available_agents=[{"agent_id": "agent-1", "display_name": "Builder"}],
            model_response=_planner_response(
                "input_model",
                "production_foundation",
                "data_behavior_layer",
                "interaction_layer",
                "visual_media_layer",
                "content_variation_layer",
            ),
        )
    )

    package_keys = [package.package_key for package in session.analysis.work_packages]

    assert session.status == "ready"
    assert "input_model" in package_keys
    assert "production_foundation" in package_keys
    assert "data_behavior_layer" in package_keys
    assert "interaction_layer" in package_keys
    assert "visual_media_layer" in package_keys
    assert "content_variation_layer" in package_keys
    assert not any(item.code == "semantic.work_review_missing" for item in session.unresolved_decisions)


def test_auto_protocol_uses_run_scoped_artifact_paths():
    session = generate_auto_protocol_session(
        ProtocolAutoDesignRequestRecord(
            requirement_text="Build a browser-runnable analytics dashboard with charts and review evidence.",
            available_agents=[{"agent_id": "agent-1", "display_name": "Builder"}],
            model_response=_planner_response("input_model", "visual_media_layer"),
        )
    )

    artifacts = session.draft_definition_json.as_dict()["artifacts"]

    assert artifacts
    assert all(str(artifact["path"]).startswith("protocol/auto/{protocol_run_id}/") for artifact in artifacts)


def test_protocol_stage_prompts_materialize_run_scoped_artifact_paths():
    session = generate_auto_protocol_session(
        ProtocolAutoDesignRequestRecord(
            requirement_text="Build a browser-runnable analytics dashboard with charts and review evidence.",
            available_agents=[{"agent_id": "agent-1", "display_name": "Builder"}],
            model_response=_planner_response("input_model", "visual_media_layer"),
        )
    )
    document = ProtocolDefinitionDocumentRecord.model_validate(session.draft_definition_json.as_dict())
    run = ProtocolRunRecord(
        protocol_run_id="run-abc",
        protocol_id="protocol-1",
        protocol_definition_version_id="version-1",
        problem_statement="Build a browser-runnable analytics dashboard.",
    )
    stage = document.stage("plan_requirements")

    prompt = render_protocol_stage_prompt(document=document, run=run, stage=stage, artifacts=[])
    contract = protocol_stage_runtime_contract(
        document=document,
        run=run,
        stage_execution_id="stage-1",
        stage=stage,
    )

    assert "protocol/auto/run-abc/requirements-plan.md" in prompt
    assert contract.output_artifacts[0].path == "protocol/auto/run-abc/requirements-plan.md"
