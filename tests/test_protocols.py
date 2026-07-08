from __future__ import annotations

import json
import random
from pathlib import Path
import string
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from octopus_sdk.protocols import (
    ProtocolArtifactObservationRecord,
    ProtocolAccessContextRecord,
    ProtocolAutoDesignModelRequestRecord,
    ProtocolAutoDesignModelResponseRecord,
    ProtocolAutoDesignRequestRecord,
    ProtocolAutoDesignSessionRecord,
    ProtocolAutoDesignWorkPackageRecord,
    ProtocolArtifactSnapshotRecord,
    ProtocolArtifactRuntimeEventRecord,
    ProtocolArtifactRuntimeInstanceRecord,
    ProtocolArtifactRuntimeManifestRecord,
    ProtocolDraftCreateRecord,
    ProtocolRunRecord,
    ProtocolRunForkRequestRecord,
    ProtocolStageExecutionRecord,
    ProtocolStageDefinitionRecord,
    TargetSelector,
    build_conversation_protocol_run_request,
    build_protocol_run_request_from_inputs,
    canonical_protocol_document,
    filter_launchable_protocols,
    launch_protocol_from_conversation,
    list_launchable_protocols,
    parse_protocol_stage_decision,
    protocol_run_launch_form,
    protocol_document_to_text,
    protocol_review_edge_key,
    render_protocol_stage_prompt,
    resolve_launchable_protocol,
    runtime_manifest_run_ready_blockers,
    validate_protocol_document,
    generate_auto_protocol_session,
)
from octopus_sdk.protocols.engine import ProtocolRunEngine
from octopus_sdk.protocols.launch import ProtocolConversationLaunchRequestRecord
from octopus_sdk.protocols.models import ProtocolDefinitionRecord, ProtocolRunMutationRecord
from octopus_sdk.registry.management import DesignAutoProtocolRequest, DesignAutoProtocolResult, ManagementRequest, ManagementResult
from octopus_sdk.registry.models import RegistryJsonRecord, RoutedTaskRequest, RoutedTaskResult, RoutedTaskUpdate
from octopus_registry.protocol_runtime import evaluate_protocol_dispatch, runtime_protocol_selector
from octopus_registry.protocol_store import ProtocolPostgresAdapter
from octopus_registry.postgres import get_connection
from octopus_registry.store_postgres import RegistryPostgresStore
from psycopg.types.json import Jsonb
from tests.support.protocol_support import (
    agent_card,
    operator_access,
    protocol_document,
    published_protocol,
    running_protocol_run,
)


def _generated_linear_protocol(seed: int) -> dict[str, object]:
    rng = random.Random(seed)
    stage_count = rng.randint(2, 6)
    artifacts: list[dict[str, object]] = []
    stages: list[dict[str, object]] = []
    previous_artifact_key = ""
    for index in range(stage_count):
        artifact_key = f"artifact-{index}"
        stage_key = f"stage-{index}"
        artifacts.append(
            {
                "artifact_key": artifact_key,
                "kind": "workspace_file",
                "path": f"protocol/{artifact_key}.md",
            }
        )
        transitions: dict[str, str] = {
            "completed": "__complete__" if index == stage_count - 1 else f"stage-{index + 1}",
            "fail": "__failed__",
        }
        stages.append(
            {
                "stage_key": stage_key,
                "participant_key": "worker",
                "selector": {"kind": "skill", "value": "planning"},
                "stage_kind": "work",
                "write_capable": True,
                "strict_completion": bool(rng.getrandbits(1)),
                "timeout_seconds": rng.choice((0, 30, 120)),
                "inputs": [previous_artifact_key] if previous_artifact_key else [],
                "outputs": [artifact_key],
                "transitions": transitions,
                "instructions": f"Write {artifact_key}.",
            }
        )
        previous_artifact_key = artifact_key
    return {
        "schema_version": 1,
        "metadata": {
            "slug": f"generated-{seed}",
            "display_name": f"Generated {seed}",
            "description": "Generated protocol for validator coverage.",
        },
        "participants": [{"participant_key": "worker", "display_name": "Worker"}],
        "artifacts": artifacts,
        "stages": stages,
        "policies": {
            "single_active_writer": True,
            "max_review_rounds": rng.randint(1, 5),
        },
    }


def _launchable_definition(**overrides) -> ProtocolDefinitionRecord:
    base = {
        "protocol_id": "protocol-1",
        "slug": "software-engineering",
        "display_name": "Software Engineering",
        "lifecycle_state": "published",
        "current_version_id": "version-1",
    }
    base.update(overrides)
    return ProtocolDefinitionRecord.model_validate(base)


def _latest_transition_metadata(detail, transition_kind: str) -> dict[str, object]:
    kind = str(transition_kind or "").strip().lower()
    for item in detail.transitions:
        if str(item.transition_kind or "").strip().lower() != kind:
            continue
        metadata = item.metadata_json
        if isinstance(metadata, RegistryJsonRecord):
            return metadata.as_dict()
        if isinstance(metadata, dict):
            return dict(metadata)
    return {}


def test_runtime_manifest_run_ready_policy_is_generic() -> None:
    assert runtime_manifest_run_ready_blockers(None) == []
    assert runtime_manifest_run_ready_blockers(
        ProtocolArtifactRuntimeManifestRecord(runtime_kind="static", ui_path="/", health_path="/health")
    ) == []
    assert runtime_manifest_run_ready_blockers(
        ProtocolArtifactRuntimeManifestRecord(
            runtime_kind="java",
            start_command="java -jar target/risk-engine.jar --server.port=${PORT}",
            ui_path="/",
            health_path="/health",
            endpoints=[{"label": "Docs", "path": "/api/docs", "endpoint_kind": "docs", "method": "GET"}],
            smoke_test=["GET /health"],
        )
    ) == []

    node_blockers = runtime_manifest_run_ready_blockers(
        ProtocolArtifactRuntimeManifestRecord(
            runtime_kind="node",
            start_command="npm run build && node dist/server.js",
            ui_path="/",
            health_path="/health",
            endpoints=[{"label": "Docs", "path": "/api/docs", "endpoint_kind": "docs", "method": "GET"}],
            smoke_test=["GET /health"],
        )
    )

    assert node_blockers == ["Node dependency, build, or test commands must run before acceptance"]


@pytest.mark.asyncio
async def test_conversation_protocol_launch_helpers_filter_resolve_and_build_requests():
    protocols = [
        _launchable_definition(protocol_id="protocol-b", slug="b", display_name="Beta"),
        _launchable_definition(protocol_id="protocol-a", slug="a", display_name="Alpha"),
        _launchable_definition(
            protocol_id="protocol-draft",
            slug="draft",
            display_name="Draft",
            lifecycle_state="draft",
        ),
        _launchable_definition(
            protocol_id="protocol-archived",
            slug="archived",
            display_name="Archived",
            current_version_id="",
        ),
    ]

    filtered = filter_launchable_protocols(protocols)
    assert [item.protocol_id for item in filtered] == ["protocol-a", "protocol-b"]

    class _Catalog:
        async def list_protocols(self, **kwargs):
            assert kwargs["lifecycle_state"] == "published"
            return protocols

    listed = await list_launchable_protocols(_Catalog())
    assert [item.protocol_id for item in listed] == ["protocol-a", "protocol-b"]

    resolved = await resolve_launchable_protocol(_Catalog(), "b")
    assert resolved.protocol_id == "protocol-b"

    request = build_conversation_protocol_run_request(
        resolved,
        {
            "protocol_ref": "b",
            "entry_agent_id": "agent-1",
            "root_conversation_id": "conv-1",
            "origin_channel": "registry",
            "workspace_ref": "workspace-a",
            "problem_statement": "Ship the thing",
            "constraints_json": {"priority": "high"},
        },
    )
    assert request.protocol_id == "protocol-b"
    assert request.root_conversation_id == "conv-1"
    assert request.workspace_ref == "workspace-a"
    assert request.constraints_json == {"priority": "high"}


def test_protocol_launch_form_and_input_request_are_transport_neutral():
    definition = _launchable_definition()

    default_form = protocol_run_launch_form(definition, canonical_protocol_document(protocol_document()))
    assert [field.key for field in default_form.fields] == [
        "problem_statement",
        "workspace_ref",
        "context",
        "constraints",
    ]
    default_text = " ".join(
        " ".join(
            [
                field.label,
                field.help,
                field.default_value,
                field.placeholder,
            ]
        )
        for field in default_form.fields
    ).lower()
    assert "analytics" not in default_text
    assert "manufacturing" not in default_text
    assert "raw private data" not in default_text

    document = protocol_document()
    document["metadata"]["run_inputs"] = [
        {
            "key": "problem_statement",
            "label": "Goal",
            "kind": "textarea",
            "required": True,
        },
        {
            "key": "privacy_constraints",
            "label": "Privacy",
            "kind": "textarea",
            "default_value": "Keep raw data local.",
        },
    ]

    form = protocol_run_launch_form(definition, canonical_protocol_document(document))

    assert form.protocol_id == "protocol-1"
    assert [field.key for field in form.fields] == ["problem_statement", "privacy_constraints"]
    assert form.fields[1].default_value == "Keep raw data local."

    document = protocol_document()
    document["metadata"]["run_inputs"] = [
        {
            "key": "goal",
            "label": "Goal",
            "kind": "textarea",
            "required": True,
            "default_value": "Build the requested artifact.",
        },
        {
            "key": "privacy_constraints",
            "label": "Privacy",
            "kind": "textarea",
        },
    ]
    form = protocol_run_launch_form(definition, canonical_protocol_document(document))
    assert [field.key for field in form.fields] == ["problem_statement", "privacy_constraints"]
    assert form.fields[0].label == "Goal"
    assert form.fields[0].default_value == "Build the requested artifact."

    request = build_protocol_run_request_from_inputs(
        definition,
        {
            "problem_statement": "Prepare a release review.",
            "workspace_ref": "workspace-a",
            "context": "Review the repository changes and release notes.",
            "constraints": "Keep the review focused on release blockers.",
        },
        entry_agent_id="agent-1",
        origin_channel="registry",
    )

    assert request.protocol_id == "protocol-1"
    assert request.entry_agent_id == "agent-1"
    assert request.workspace_ref == "workspace-a"
    assert request.problem_statement == "Prepare a release review."
    assert request.constraints_json["context"] == "Review the repository changes and release notes."
    assert request.constraints_json["constraints"] == "Keep the review focused on release blockers."


def test_protocol_stage_prompt_includes_typed_run_context_without_special_surface_logic():
    document = canonical_protocol_document(protocol_document())
    run = ProtocolRunRecord.model_validate(
        {
            "protocol_run_id": "run-1",
            "protocol_id": "protocol-1",
            "protocol_definition_version_id": "version-1",
            "entry_agent_id": "agent-1",
            "status": "running",
            "current_stage_key": "planning",
            "problem_statement": "Prepare the release review.",
            "constraints_json": {
                "context": "Review the repository changes and release notes.",
                "constraints": "Keep the review focused on release blockers.",
                "acceptance_criteria": "Summarize only release-blocking findings.",
            },
        }
    )

    prompt = render_protocol_stage_prompt(
        document=document,
        run=run,
        stage=document.stage("planning"),
        artifacts=[],
    )

    assert "Launch context and constraints:" in prompt
    assert "Context:\nReview the repository changes and release notes." in prompt
    assert "Constraints:\nKeep the review focused on release blockers." in prompt
    assert "Acceptance Criteria:\nSummarize only release-blocking findings." in prompt


def test_protocol_stage_prompt_limits_artifact_work_to_stage_outputs():
    payload = protocol_document()
    planning = next(stage for stage in payload["stages"] if stage["stage_key"] == "planning")
    planning["outputs"] = []
    document = canonical_protocol_document(payload)
    run = ProtocolRunRecord.model_validate(
        {
            "protocol_run_id": "run-1",
            "protocol_id": "protocol-1",
            "protocol_definition_version_id": "version-1",
            "entry_agent_id": "agent-1",
            "status": "running",
            "current_stage_key": "planning",
            "problem_statement": "Create the local analytics app.",
            "constraints_json": {
                "desired_outputs": "index.html and findings report",
            },
        }
    )

    prompt = render_protocol_stage_prompt(
        document=document,
        run=run,
        stage=document.stage("planning"),
        artifacts=[],
    )

    assert "do not create or update protocol artifacts for this stage" in prompt
    assert "update the required artifacts" not in prompt
    assert "Launch context parameterizes this run" in prompt
    assert "Do not create, overwrite, or pre-fill artifacts assigned to later stages." in prompt
    assert "treat this stage's input and output artifact lists as authoritative" in prompt
    assert "PROTOCOL_DECISION: completed" in prompt
    assert "do not use review decisions such as accept, revise, or fail" in prompt
    assert "Do not leave long-running commands, servers, watchers, or development processes running" in prompt


def test_protocol_review_prompt_mentions_assigned_output_artifacts():
    payload = protocol_document()
    payload["artifacts"].append(
        {
            "artifact_key": "review_report",
            "kind": "workspace_file",
            "path": "protocol/review.md",
        }
    )
    review = next(stage for stage in payload["stages"] if stage["stage_key"] == "review")
    review["outputs"] = ["review_report"]
    document = canonical_protocol_document(payload)
    run = ProtocolRunRecord.model_validate(
        {
            "protocol_run_id": "run-1",
            "protocol_id": "protocol-1",
            "protocol_definition_version_id": "version-1",
            "entry_agent_id": "agent-1",
            "status": "running",
            "current_stage_key": "review",
            "problem_statement": "Review the local analytics app.",
        }
    )

    prompt = render_protocol_stage_prompt(
        document=document,
        run=run,
        stage=document.stage("review"),
        artifacts=[],
    )

    assert "Output artifacts for this stage (write scope):" in prompt
    assert "- review_report: protocol/review.md" in prompt
    assert "Complete the review, update only the assigned output artifacts in the workspace" in prompt
    assert "Do not revise or fail the stage because a later-stage artifact is not produced yet" in prompt
    assert "Decision semantics: accept means the reviewed work has no material unresolved gap" in prompt
    assert "choose revise unless the issue cannot be corrected by another attempt" in prompt


@pytest.mark.asyncio
async def test_launch_protocol_from_conversation_invokes_shared_protocol_pipeline():
    definition = _launchable_definition()
    captured: dict[str, object] = {}

    class _Catalog:
        async def list_protocols(self, **kwargs):
            assert kwargs["lifecycle_state"] == "published"
            return [definition]

    class _Invoker:
        async def invoke_protocol(self, payload, *, idempotency_key="", origin=""):
            captured["payload"] = payload
            captured["idempotency_key"] = idempotency_key
            captured["origin"] = origin
            return ProtocolRunMutationRecord.model_validate(
                {
                    "ok": True,
                    "status": "created",
                    "run": {
                        "protocol_run_id": "run-1",
                        "protocol_id": "protocol-1",
                        "protocol_definition_version_id": "version-1",
                        "entry_agent_id": "agent-1",
                        "root_conversation_id": "conv-1",
                        "origin_channel": "registry",
                        "workspace_ref": "workspace-a",
                        "run_org_id": "local",
                        "status": "running",
                        "problem_statement": "Build the feature",
                        "constraints_json": {},
                        "created_at": "2026-04-23T00:00:00+00:00",
                        "updated_at": "2026-04-23T00:00:00+00:00",
                    },
                }
            )

    launch = await launch_protocol_from_conversation(
        _Catalog(),
        _Invoker(),
        ProtocolConversationLaunchRequestRecord(
            protocol_ref="software-engineering",
            entry_agent_id="agent-1",
            root_conversation_id="conv-1",
            origin_channel="registry",
            workspace_ref="workspace-a",
            problem_statement="Build the feature",
            constraints_json=RegistryJsonRecord(root={}),
        ),
        idempotency_key="abc-123",
        origin="registry-ui",
    )

    payload = captured["payload"]
    assert payload.protocol_id == "protocol-1"
    assert payload.entry_agent_id == "agent-1"
    assert payload.root_conversation_id == "conv-1"
    assert captured["idempotency_key"] == "abc-123"
    assert captured["origin"] == "registry-ui"
    assert launch.definition.protocol_id == "protocol-1"
    assert launch.mutation.run.protocol_run_id == "run-1"


def _random_jsonish(rng: random.Random, *, depth: int) -> object:
    if depth <= 0:
        return rng.choice(
            (
                None,
                True,
                False,
                rng.randint(-10, 10),
                "".join(rng.choice(string.ascii_lowercase) for _ in range(rng.randint(0, 8))),
            )
        )
    kind = rng.choice(("dict", "list", "scalar"))
    if kind == "dict":
        return {
            "".join(rng.choice(string.ascii_lowercase) for _ in range(rng.randint(1, 6))): _random_jsonish(
                rng,
                depth=depth - 1,
            )
            for _ in range(rng.randint(0, 4))
        }
    if kind == "list":
        return [_random_jsonish(rng, depth=depth - 1) for _ in range(rng.randint(0, 4))]
    return _random_jsonish(rng, depth=0)


def test_validate_protocol_document_accepts_minimal_protocol() -> None:
    result = validate_protocol_document(protocol_document())
    assert result.ok is True
    assert result.normalized_document is not None
    assert result.normalized_document.first_stage_key == "planning"


def test_canonical_protocol_document_synthesizes_selector_from_legacy_required_skill() -> None:
    legacy = protocol_document()
    legacy["stages"][0].pop("selector", None)
    legacy["participants"][0]["required_skills"] = ["planning"]

    document = canonical_protocol_document(legacy)

    stage = document.stage("planning")
    assert stage.selector is not None
    assert stage.selector.kind == "skill"
    assert stage.selector.value == "planning"
    assert "required_skills" not in document.model_dump(mode="json")["participants"][0]
    assert "selector" not in document.model_dump(mode="json")["participants"][0]


def test_canonical_protocol_document_marks_output_stage_write_capable_when_unspecified() -> None:
    source = protocol_document()
    source["stages"][0].pop("write_capable", None)
    source["stages"][0]["outputs"] = ["plan"]

    document = canonical_protocol_document(source)

    assert document.stage("planning").write_capable is True


def test_canonical_protocol_document_migrates_participant_selector_to_stage_selector() -> None:
    legacy = protocol_document()
    legacy["stages"][0].pop("selector", None)
    legacy["participants"][0]["selector"] = {"kind": "skill", "value": "planning"}

    document = canonical_protocol_document(legacy)

    stage = document.stage("planning")
    assert stage.selector is not None
    assert stage.selector.kind == "skill"
    assert stage.selector.value == "planning"
    assert "selector" not in document.model_dump(mode="json")["participants"][0]


def test_validate_protocol_document_requires_assignment_rule_for_stages() -> None:
    invalid = protocol_document()
    invalid["stages"][0]["display_name"] = "Planning stage"
    invalid["stages"][0].pop("selector", None)

    result = validate_protocol_document(invalid)

    assert result.ok is False
    assert result.issues
    issue = next(item for item in result.issues if item.code == "stage.selector_required")
    assert "Planning stage" in issue.message
    assert "planning" not in issue.message


def test_validate_protocol_document_warns_when_legacy_required_skills_has_multiple_values() -> None:
    legacy = protocol_document()
    legacy["participants"][0].pop("selector", None)
    legacy["participants"][0]["required_skills"] = ["planning", "review"]

    result = validate_protocol_document(legacy, mode="draft")

    assert result.ok is True
    assert any(item.code == "participant.legacy_multi_skill" and item.blocking is False for item in result.issues)


def test_runtime_protocol_selector_prefers_entry_agent_for_skill_selectors() -> None:
    selector = runtime_protocol_selector(
        selector=TargetSelector(kind="skill", value="planning"),
        entry_agent_id="agent-1",
    )

    assert selector.kind == "skill"
    assert selector.value == "planning"
    assert selector.preferred_agent_id == "agent-1"


def test_runtime_dispatch_reports_missing_stage_selector_as_stage_error() -> None:
    document = canonical_protocol_document({
        **protocol_document(),
        "stages": [
            {**stage, "selector": None} if stage["stage_key"] == "planning" else stage
            for stage in protocol_document()["stages"]
        ],
    })

    decision = evaluate_protocol_dispatch(
        protocol_engine=ProtocolRunEngine(),
        document=document,
        run=ProtocolRunRecord(
            protocol_run_id="run-1",
            created_at="2026-04-19T00:00:00+00:00",
            current_stage_execution_id="planning-exec",
        ),
        stage_execution=ProtocolStageExecutionRecord(
            protocol_stage_execution_id="planning-exec",
            protocol_run_id="run-1",
            stage_key="planning",
            participant_key="worker",
            status="queued",
        ),
        stage_executions=[],
        artifacts=[],
        previous_feedback="",
        now="2026-04-19T00:00:00+00:00",
        resolve_selector=lambda selector: {"agent_id": "agent-1", "authority_ref": "registry:local"},
    )

    assert decision.run_status == "blocked"
    assert decision.failure_code == "stage_selector_required"


def test_parse_protocol_stage_decision_requires_explicit_review_decision() -> None:
    stage = ProtocolStageDefinitionRecord(
        stage_key="review",
        participant_key="reviewer",
        stage_kind="review",
        transitions={"accept": "__complete__", "revise": "planning", "fail": "__failed__"},
    )
    decision = parse_protocol_stage_decision(
        stage=stage,
        full_text="PROTOCOL_DECISION: accept\nPROTOCOL_SUMMARY: Looks good.",
    )
    assert decision.decision == "accept"
    assert decision.summary == "Looks good."


def test_validate_protocol_document_migrates_legacy_schema_value() -> None:
    legacy = protocol_document()
    legacy["schema_version"] = 0

    result = validate_protocol_document(legacy)

    assert result.ok is True
    assert result.normalized_document is not None
    assert result.normalized_document.schema_version == 1


def test_validate_protocol_document_rejects_workspace_path_traversal() -> None:
    invalid = protocol_document()
    invalid["artifacts"] = [
        {
            "artifact_key": "plan",
            "kind": "workspace_file",
            "path": "../secret/plan.md",
        }
    ]

    result = validate_protocol_document(invalid)

    assert result.ok is False
    assert result.errors
    assert "escape the workspace root" in result.errors[0]


def test_validate_protocol_document_accepts_generated_reachable_linear_graphs() -> None:
    for seed in range(25):
        result = validate_protocol_document(_generated_linear_protocol(seed))
        assert result.ok is True, f"generated protocol failed validation for seed={seed}: {result.errors}"


def test_validate_protocol_document_fuzz_does_not_raise_uncaught_exceptions() -> None:
    for seed in range(100):
        payload = _random_jsonish(random.Random(seed), depth=3)
        if not isinstance(payload, dict):
            payload = {"payload": payload}
        result = validate_protocol_document(payload)
        assert isinstance(result.ok, bool), f"validator returned invalid result for seed={seed}"


def test_protocol_artifact_observation_rejects_absolute_or_traversing_paths() -> None:
    with pytest.raises(ValueError, match="relative to the workspace root"):
        ProtocolArtifactObservationRecord.model_validate(
            {
                "artifact_key": "plan",
                "artifact_kind": "workspace_file",
                "path": "/tmp/plan.md",
            }
        )

    with pytest.raises(ValueError, match="escape the workspace root"):
        ProtocolArtifactObservationRecord.model_validate(
            {
                "artifact_key": "plan",
                "artifact_kind": "workspace_file",
                "path": "../secret/plan.md",
            }
        )


def test_registry_store_preserves_invalid_protocol_draft(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    saved = store.save_protocol_draft(
        access=operator_access(),
        protocol_id="",
        slug="broken-protocol",
        display_name="Broken Protocol",
        description="Invalid draft",
        definition_json=RegistryJsonRecord.model_validate(
            {
                "metadata": {"slug": "broken-protocol"},
                "participants": [],
                "artifacts": [],
                "stages": [],
                "policies": {"single_active_writer": True, "max_review_rounds": 3},
            }
        ),
    )
    assert saved.ok is True
    assert saved.protocol is not None

    loaded = store.get_protocol(saved.protocol.protocol_id, access=operator_access())
    assert loaded.ok is True
    assert loaded.validation is not None
    assert loaded.validation.ok is False
    assert loaded.draft_document is None
    assert loaded.draft_definition_json.as_dict()["metadata"]["slug"] == "broken-protocol"
    assert loaded.protocol.draft_revision == 1


def test_registry_store_protocol_draft_conflict_requires_matching_revision(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    created = store.create_protocol_draft(
        ProtocolDraftCreateRecord.model_validate({"source_kind": "blank"}),
        access=operator_access(),
    )
    assert created.ok is True
    assert created.protocol is not None
    protocol_id = created.protocol.protocol_id
    initial_revision = created.protocol.draft_revision
    assert initial_revision == 1

    first_save = store.save_protocol_draft(
        access=operator_access(),
        protocol_id=protocol_id,
        slug="conflict-protocol",
        display_name="Conflict Protocol",
        description="First writer",
        definition_json=RegistryJsonRecord.model_validate(
            {
                **created.draft_definition_json.as_dict(),
                "metadata": {
                    "slug": "conflict-protocol",
                    "display_name": "Conflict Protocol",
                    "description": "First writer",
                },
            }
        ),
        expected_revision=initial_revision,
    )
    assert first_save.ok is True
    assert first_save.protocol is not None
    assert first_save.protocol.draft_revision == 2

    stale_save = store.save_protocol_draft(
        access=operator_access(),
        protocol_id=protocol_id,
        slug="conflict-protocol",
        display_name="Conflict Protocol",
        description="Stale writer",
        definition_json=RegistryJsonRecord.model_validate(
            {
                **created.draft_definition_json.as_dict(),
                "metadata": {
                    "slug": "conflict-protocol",
                    "display_name": "Conflict Protocol",
                    "description": "Stale writer",
                },
            }
        ),
        expected_revision=initial_revision,
    )
    assert stale_save.ok is False
    assert stale_save.status == "conflict"
    assert stale_save.protocol is not None
    assert stale_save.protocol.draft_revision == 2
    assert stale_save.draft_definition_json.as_dict()["metadata"]["description"] == "First writer"


def test_registry_store_protocol_run_advances_from_work_to_review(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    enroll, _published, created, detail = running_protocol_run(store)
    token = enroll.agent_token
    assert detail.run.current_stage_key == "planning"
    assert detail.stage_executions
    first_stage = detail.stage_executions[0]
    assert first_stage.routed_task_id.startswith("protocol-stage:")

    store.update_routed_task_result(
        token,
        first_stage.routed_task_id,
        {
            "status": "completed",
            "transition_id": "done-1",
            "summary": "Plan updated.",
            "full_text": "Updated protocol/plan.md.\nPROTOCOL_SUMMARY: Plan updated.",
            "artifacts": [
                {
                    "artifact_key": "plan",
                    "artifact_kind": "workspace_file",
                    "path": "protocol/plan.md",
                    "exists": True,
                    "size_bytes": 128,
                    "content_hash": "abc123",
                    "modified_at": "2026-04-16T00:00:00+00:00",
                    "verification_state": "verified",
                }
            ],
        },
    )

    detail = store.get_protocol_run(created.run.protocol_run_id, access=operator_access())
    assert detail.run.current_stage_key == "review"
    review_stage = detail.stage_executions[0]
    assert detail.run.current_stage_execution_id == review_stage.protocol_stage_execution_id
    assert review_stage.stage_key == "review"
    assert review_stage.status == "running"

    store.update_routed_task_result(
        token,
        review_stage.routed_task_id,
        {
            "status": "completed",
            "transition_id": "done-2",
            "summary": "Accepted.",
            "full_text": "Everything is complete.\nPROTOCOL_DECISION: accept\nPROTOCOL_SUMMARY: Accepted.",
        },
    )

    detail = store.get_protocol_run(created.run.protocol_run_id, access=operator_access())
    assert detail.run.status == "completed"
    assert detail.run.termination_summary == "Accepted."


def test_registry_store_protocol_run_completes_single_work_stage_without_transition(
    postgres_registry_truncated: str,
) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    document = {
        **protocol_document(),
        "artifacts": [],
        "stages": [
            {
                **protocol_document()["stages"][0],
                "stage_key": "release-readiness",
                "display_name": "Release readiness",
                "inputs": [],
                "outputs": [],
                "transitions": {},
            }
        ],
    }
    enroll, _published, created, detail = running_protocol_run(store, document=document)
    token = enroll.agent_token
    first_stage = detail.stage_executions[0]

    store.update_routed_task_result(
        token,
        first_stage.routed_task_id,
        {
            "status": "completed",
            "transition_id": "single-stage-complete",
            "summary": "Ready.",
            "full_text": "Ready to proceed.\nPROTOCOL_SUMMARY: Ready.",
        },
    )

    detail = store.get_protocol_run(created.run.protocol_run_id, access=operator_access())
    assert detail.run.status == "completed"
    assert detail.run.blocked_code == ""
    assert detail.run.termination_summary == "Ready."
    assert any(item.transition_kind == "terminal" for item in detail.transitions)


def test_registry_store_protocol_run_detail_projects_latest_artifact_once(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    document = {
        **protocol_document(),
        "stages": [
            {
                **protocol_document()["stages"][0],
                "transitions": {"completed": "architecture"},
            },
            {
                "stage_key": "architecture",
                "participant_key": "worker",
                "selector": {"kind": "skill", "value": "architecture"},
                "stage_kind": "work",
                "write_capable": True,
                "inputs": ["plan"],
                "outputs": ["plan"],
                "transitions": {"completed": "review"},
                "instructions": "Refine protocol/plan.md.",
            },
            protocol_document()["stages"][1],
        ],
    }
    enroll, _published, created, detail = running_protocol_run(store, document=document)
    token = enroll.agent_token

    first_stage = detail.stage_executions[0]
    store.update_routed_task_result(
        token,
        first_stage.routed_task_id,
        {
            "status": "completed",
            "transition_id": "done-1",
            "summary": "Plan created.",
            "full_text": "Created protocol/plan.md.\nPROTOCOL_SUMMARY: Plan created.",
            "artifacts": [
                {
                    "artifact_key": "plan",
                    "artifact_kind": "workspace_file",
                    "path": "protocol/plan.md",
                    "exists": True,
                    "size_bytes": 128,
                    "content_hash": "initial",
                    "modified_at": "2026-04-16T00:00:00+00:00",
                    "verification_state": "verified",
                }
            ],
        },
    )

    detail = store.get_protocol_run(created.run.protocol_run_id, access=operator_access())
    architecture_stage = detail.stage_executions[0]
    assert architecture_stage.stage_key == "architecture"
    store.update_routed_task_result(
        token,
        architecture_stage.routed_task_id,
        {
            "status": "completed",
            "transition_id": "done-2",
            "summary": "Plan refined.",
            "full_text": "Refined protocol/plan.md.\nPROTOCOL_SUMMARY: Plan refined.",
            "artifacts": [
                {
                    "artifact_key": "plan",
                    "artifact_kind": "workspace_file",
                    "path": "protocol/plan.md",
                    "exists": True,
                    "size_bytes": 256,
                    "content_hash": "refined",
                    "modified_at": "2026-04-16T00:05:00+00:00",
                    "verification_state": "verified",
                }
            ],
        },
    )

    detail = store.get_protocol_run(created.run.protocol_run_id, access=operator_access())
    assert [artifact.artifact_key for artifact in detail.artifacts] == ["plan"]
    assert detail.artifacts[0].content_hash == "refined"
    assert detail.artifacts[0].size_bytes == 256
    assert detail.artifacts[0].supersedes_protocol_artifact_id
    assert detail.artifacts[0].produced_by_stage_execution_id == architecture_stage.protocol_stage_execution_id


def test_registry_store_run_participants_project_stage_owned_selectors(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    _enroll, _published, created, _detail = running_protocol_run(store)

    participants = store.get_protocol_run_participants(created.run.protocol_run_id, access=operator_access())
    by_key = {item.participant_key: item for item in participants}

    assert by_key["worker"].target_selector.as_dict() == {
        "kind": "skill",
        "value": "planning",
        "preferred_agent_id": "",
    }
    assert by_key["worker"].required_skills == ["planning"]
    assert by_key["reviewer"].target_selector.as_dict() == {
        "kind": "skill",
        "value": "review",
        "preferred_agent_id": "",
    }
    assert by_key["reviewer"].required_skills == ["review"]


def test_registry_store_duplicate_routed_task_result_is_idempotent(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    enroll, _published, created, detail = running_protocol_run(store)
    token = enroll.agent_token
    stage = detail.stage_executions[0]
    payload = {
        "status": "completed",
        "transition_id": "done-dup",
        "summary": "Plan updated.",
        "full_text": "Updated protocol/plan.md.\nPROTOCOL_SUMMARY: Plan updated.",
        "artifacts": [
            {
                "artifact_key": "plan",
                "artifact_kind": "workspace_file",
                "path": "protocol/plan.md",
                "exists": True,
                "size_bytes": 128,
                "content_hash": "abc123",
                "modified_at": "2026-04-16T00:00:00+00:00",
                "verification_state": "verified",
            }
        ],
    }

    store.update_routed_task_result(token, stage.routed_task_id, payload)
    first = store.get_protocol_run(created.run.protocol_run_id, access=operator_access())
    first_stage_ids = [item.protocol_stage_execution_id for item in first.stage_executions]
    first_transition_ids = [item.protocol_transition_id for item in first.transitions]

    store.update_routed_task_result(token, stage.routed_task_id, payload)
    second = store.get_protocol_run(created.run.protocol_run_id, access=operator_access())

    assert second.run.current_stage_execution_id == first.run.current_stage_execution_id
    assert [item.protocol_stage_execution_id for item in second.stage_executions] == first_stage_ids
    assert [item.protocol_transition_id for item in second.transitions] == first_transition_ids


def test_registry_store_running_status_renews_protocol_write_lease(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    enroll, _published, created, detail = running_protocol_run(store)
    stage = detail.stage_executions[0]
    expired = "2000-01-01T00:00:00+00:00"
    with get_connection(postgres_registry_truncated) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE agent_registry.protocol_stage_executions
                SET lease_expires_at = %s
                WHERE protocol_stage_execution_id = %s
                """,
                (expired, stage.protocol_stage_execution_id),
            )
        conn.commit()

    store.update_routed_task_status(
        enroll.agent_token,
        stage.routed_task_id,
        RoutedTaskUpdate(
            routed_task_id=stage.routed_task_id,
            status="leased",
            transition_id="lease-renew-lease",
            summary="Leased.",
            timeline_events=[],
        ),
    )
    store.update_routed_task_status(
        enroll.agent_token,
        stage.routed_task_id,
        RoutedTaskUpdate(
            routed_task_id=stage.routed_task_id,
            status="running",
            transition_id="lease-renew-1",
            summary="Still working.",
            timeline_events=[],
        ),
    )

    refreshed = store.get_protocol_run(created.run.protocol_run_id, access=operator_access())
    renewed = next(
        item for item in refreshed.stage_executions if item.protocol_stage_execution_id == stage.protocol_stage_execution_id
    )
    assert renewed.status == "running"
    assert renewed.lease_expires_at > expired


def test_registry_store_list_protocols_accepts_default_include_drafts(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    published = published_protocol(store)

    listed = store.list_protocols(access=operator_access(), limit=10)

    assert any(item.protocol_id == published.protocol.protocol_id for item in listed)


def test_registry_store_exposes_review_loop_count_and_cap(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    enroll, _published, created, detail = running_protocol_run(store)
    planning_stage = detail.stage_executions[0]

    store.update_routed_task_result(
        enroll.agent_token,
        planning_stage.routed_task_id,
        {
            "status": "completed",
            "transition_id": "plan-complete",
            "summary": "Plan updated.",
            "full_text": "Updated protocol/plan.md.\nPROTOCOL_SUMMARY: Plan updated.",
            "artifacts": [
                {
                    "artifact_key": "plan",
                    "artifact_kind": "workspace_file",
                    "path": "protocol/plan.md",
                    "exists": True,
                    "size_bytes": 128,
                    "content_hash": "plan123",
                    "modified_at": "2026-04-16T00:00:00+00:00",
                    "verification_state": "verified",
                }
            ],
        },
    )

    review_detail = store.get_protocol_run(created.run.protocol_run_id, access=operator_access())
    review_stage = next(item for item in review_detail.stage_executions if item.stage_key == "review")
    store.update_routed_task_result(
        enroll.agent_token,
        review_stage.routed_task_id,
        {
            "status": "completed",
            "transition_id": "review-revise",
            "summary": "Needs changes.",
            "full_text": "Needs more work.\nPROTOCOL_DECISION: revise\nPROTOCOL_SUMMARY: Needs changes.",
        },
    )

    revised = store.get_protocol_run(created.run.protocol_run_id, access=operator_access())
    listed = store.list_protocol_runs(access=operator_access())
    run_summary = next(item for item in listed if item.protocol_run_id == created.run.protocol_run_id)

    assert revised.run.current_review_rounds == 1
    assert revised.run.max_review_rounds == 3
    assert revised.run.current_review_edge_key == protocol_review_edge_key("review", "planning")
    assert run_summary.current_review_rounds == 1
    assert run_summary.max_review_rounds == 3


def test_registry_store_late_result_after_timeout_does_not_reopen_run(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    enroll, _published, created, detail = running_protocol_run(
        store,
        document={
            **protocol_document(),
            "stages": [
                {
                    **protocol_document()["stages"][0],
                    "timeout_seconds": 1,
                },
                protocol_document()["stages"][1],
            ],
        },
    )
    stage = detail.stage_executions[0]
    expired = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    with get_connection(postgres_registry_truncated) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE agent_registry.protocol_stage_executions
                SET timeout_at = %s
                WHERE protocol_stage_execution_id = %s
                """,
                (expired, stage.protocol_stage_execution_id),
            )
        conn.commit()

    maintenance = store.run_protocol_maintenance()
    timed_out = store.get_protocol_run(created.run.protocol_run_id, access=operator_access())
    transition_ids = [item.protocol_transition_id for item in timed_out.transitions]
    stage_ids = [item.protocol_stage_execution_id for item in timed_out.stage_executions]

    store.update_routed_task_result(
        enroll.agent_token,
        stage.routed_task_id,
        {
            "status": "completed",
            "transition_id": "late-1",
            "summary": "Late completion.",
            "full_text": "Updated protocol/plan.md.\nPROTOCOL_SUMMARY: Late completion.",
            "artifacts": [
                {
                    "artifact_key": "plan",
                    "artifact_kind": "workspace_file",
                    "path": "protocol/plan.md",
                    "exists": True,
                    "size_bytes": 128,
                    "content_hash": "late123",
                    "modified_at": "2026-04-16T00:00:00+00:00",
                    "verification_state": "verified",
                }
            ],
        },
    )

    refreshed = store.get_protocol_run(created.run.protocol_run_id, access=operator_access())
    task = store.get_task(stage.routed_task_id)
    task_result = task.result.as_dict() if task.result is not None else {}
    assert maintenance.swept_count == 1
    assert refreshed.run.status == "failed"
    assert [
        item.protocol_transition_id for item in refreshed.transitions
        if item.transition_kind != "late_result"
    ] == transition_ids
    late_transitions = [item for item in refreshed.transitions if item.transition_kind == "late_result"]
    assert len(late_transitions) == 1
    assert late_transitions[0].error_code == "LATE_RESULT_PRESERVED"
    assert task_result.get("late_delivery", {}).get("status") == "late_result_preserved"
    assert [item.protocol_stage_execution_id for item in refreshed.stage_executions] == stage_ids


def test_registry_store_protocol_timeline_scales_for_large_transition_history(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    _enroll, _published, created, detail = running_protocol_run(store)
    run_id = created.run.protocol_run_id
    stage_id = detail.stage_executions[0].protocol_stage_execution_id
    inserted = 400
    now = datetime.now(timezone.utc).isoformat()

    with get_connection(postgres_registry_truncated) as conn:
        with conn.cursor() as cur:
            for index in range(inserted):
                cur.execute(
                    """
                    INSERT INTO agent_registry.protocol_transitions (
                        protocol_transition_id, protocol_run_id, from_stage_execution_id,
                        to_stage_execution_id, transition_kind, decision, reason, error_code,
                        metadata_json, actor_type, actor_ref, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        uuid.uuid4().hex,
                        run_id,
                        stage_id,
                        stage_id,
                        "progress",
                        "",
                        f"perf-{index}",
                        "",
                        Jsonb({}),
                        "protocol_engine",
                        stage_id,
                        now,
                    ),
                )
        conn.commit()

    store.get_protocol_run_timeline(run_id, access=operator_access())
    started = time.perf_counter()
    timeline = store.get_protocol_run_timeline(run_id, access=operator_access())
    elapsed = time.perf_counter() - started

    assert len(timeline) >= inserted
    # Generous local threshold to catch regressions in the hot-path timeline query without flaking on CI noise.
    assert elapsed < 2.0


def test_registry_store_loads_legacy_published_protocol_versions_via_in_memory_migration(
    postgres_registry_truncated: str,
) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    published = published_protocol(store)
    assert published.version is not None

    legacy_payload = protocol_document()
    legacy_payload["schema_version"] = 0

    with get_connection(postgres_registry_truncated) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE agent_registry.protocol_definition_versions
                SET definition_json = %s
                WHERE protocol_definition_version_id = %s
                """,
                (
                    Jsonb(legacy_payload),
                    published.version.protocol_definition_version_id,
                ),
            )
        conn.commit()

    version = store.get_protocol_version(
        published.protocol.protocol_id,
        published.version.protocol_definition_version_id,
        access=operator_access(),
    )
    migrated = canonical_protocol_document(version.definition_json)
    assert migrated.schema_version == 1
    assert migrated.stage("planning").strict_completion is False
    assert migrated.stage("planning").timeout_seconds == 0

    enroll = store.enroll(agent_card(bot_key="m1"))
    created = store.create_protocol_run(
        {
            "protocol_id": published.protocol.protocol_id,
            "entry_agent_id": enroll.agent_id,
            "origin_channel": "registry",
            "workspace_ref": "default",
            "problem_statement": "Build the feature.",
            "constraints_json": {},
        },
        access=operator_access(),
    )
    assert created.ok is True


def test_registry_store_protocol_timeout_sweeps_without_task_result(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    enroll, _published, created, detail = running_protocol_run(
        store,
        document={
            **protocol_document(),
            "stages": [
                {
                    **protocol_document()["stages"][0],
                    "timeout_seconds": 1,
                },
                protocol_document()["stages"][1],
            ],
        },
    )
    stage = detail.stage_executions[0]
    expired = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    with get_connection(postgres_registry_truncated) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE agent_registry.protocol_stage_executions
                SET timeout_at = %s
                WHERE protocol_stage_execution_id = %s
                """,
                (expired, stage.protocol_stage_execution_id),
            )
        conn.commit()

    maintenance = store.run_protocol_maintenance()

    refreshed = store.get_protocol_run(created.run.protocol_run_id, access=operator_access())
    assert maintenance.swept_count == 1
    assert created.run.protocol_run_id in maintenance.affected_run_ids
    assert refreshed.run.status == "failed"
    assert refreshed.run.blocked_code == ""
    assert refreshed.run.termination_summary == ""
    assert refreshed.stage_executions[0].failure_code == "stage_timeout"


def test_registry_store_protocol_issues_report_timeout_stuck_blocked_and_contract_runs(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    enroll, _published, created, detail = running_protocol_run(
        store,
        document={
            **protocol_document(),
            "stages": [
                {
                    **protocol_document()["stages"][0],
                    "timeout_seconds": 1,
                },
                protocol_document()["stages"][1],
            ],
        },
    )
    stage = detail.stage_executions[0]
    expired = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    with get_connection(postgres_registry_truncated) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE agent_registry.protocol_stage_executions
                SET timeout_at = %s
                WHERE protocol_stage_execution_id = %s
                """,
                (expired, stage.protocol_stage_execution_id),
            )
        conn.commit()

    timeout_issues = store.list_protocol_issues(
        access=operator_access(),
        issue_kind="expired_timeout",
    )
    assert any(item.protocol_run_id == created.run.protocol_run_id for item in timeout_issues)

    maintenance = store.run_protocol_maintenance()

    refreshed = store.get_protocol_run(created.run.protocol_run_id, access=operator_access())
    assert maintenance.swept_count == 1
    assert refreshed.run.status == "failed"

    stuck_enroll = store.enroll(agent_card(bot_key="m-stuck"))
    stuck_published = published_protocol(
        store,
        slug="mini-protocol-stuck",
        document={
            **protocol_document(),
            "metadata": {
                **protocol_document()["metadata"],
                "slug": "mini-protocol-stuck",
                "display_name": "Mini Protocol Stuck",
            },
        },
    )
    stuck_created = store.create_protocol_run(
        {
            "protocol_id": stuck_published.protocol.protocol_id,
            "entry_agent_id": stuck_enroll.agent_id,
            "origin_channel": "registry",
            "workspace_ref": "default",
            "problem_statement": "Build the stuck feature.",
            "constraints_json": {},
        },
        access=operator_access(),
    )
    stuck_detail = store.get_protocol_run(stuck_created.run.protocol_run_id, access=operator_access())
    stuck_stage = stuck_detail.stage_executions[0]
    with get_connection(postgres_registry_truncated) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE agent_registry.protocol_stage_executions
                SET lease_expires_at = %s
                WHERE protocol_stage_execution_id = %s
                """,
                (expired, stuck_stage.protocol_stage_execution_id),
            )
        conn.commit()

    stuck_issues = store.list_protocol_issues(
        access=operator_access(),
        issue_kind="stuck_lease",
    )
    assert any(item.protocol_run_id == stuck_created.run.protocol_run_id for item in stuck_issues)
    stuck_issue = next(item for item in stuck_issues if item.protocol_run_id == stuck_created.run.protocol_run_id)
    assert stuck_issue.task_updated_at

    blocked_enroll = store.enroll(agent_card(bot_key="m2"))
    blocked_published = published_protocol(
        store,
        slug="mini-protocol-blocked",
        document={
            **protocol_document(),
            "metadata": {
                **protocol_document()["metadata"],
                "slug": "mini-protocol-blocked",
                "display_name": "Mini Protocol Blocked",
            },
        },
    )
    blocked_created = store.create_protocol_run(
        {
            "protocol_id": blocked_published.protocol.protocol_id,
            "entry_agent_id": blocked_enroll.agent_id,
            "origin_channel": "registry",
            "workspace_ref": "default",
            "problem_statement": "Build the blocked feature.",
            "constraints_json": {},
        },
        access=operator_access(),
    )
    blocked_detail = store.get_protocol_run(blocked_created.run.protocol_run_id, access=operator_access())
    blocked_stage = blocked_detail.stage_executions[0]
    store.update_routed_task_result(
        blocked_enroll.agent_token,
        blocked_stage.routed_task_id,
        {
            "status": "completed",
            "transition_id": "blocked-1",
            "summary": "Missing artifact.",
            "full_text": "Updated plan.\nPROTOCOL_SUMMARY: Missing artifact.",
            "artifacts": [],
        },
    )
    blocked_issues = store.list_protocol_issues(
        access=operator_access(),
        issue_kind="blocked_run",
    )
    assert any(item.protocol_run_id == blocked_created.run.protocol_run_id for item in blocked_issues)
    filtered_issues = store.list_protocol_issues(
        access=operator_access(),
        protocol_run_id=blocked_created.run.protocol_run_id,
    )
    assert filtered_issues
    assert all(item.protocol_run_id == blocked_created.run.protocol_run_id for item in filtered_issues)

    contract_enroll = store.enroll(agent_card(bot_key="m-contract"))
    contract_published = published_protocol(
        store,
        slug="mini-protocol-contract",
        document={
            **protocol_document(),
            "metadata": {
                **protocol_document()["metadata"],
                "slug": "mini-protocol-contract",
                "display_name": "Mini Protocol Contract",
            },
        },
    )
    contract_created = store.create_protocol_run(
        {
            "protocol_id": contract_published.protocol.protocol_id,
            "entry_agent_id": contract_enroll.agent_id,
            "origin_channel": "registry",
            "workspace_ref": "default",
            "problem_statement": "Build the contract feature.",
            "constraints_json": {},
        },
        access=operator_access(),
    )
    contract_detail = store.get_protocol_run(contract_created.run.protocol_run_id, access=operator_access())
    contract_stage = contract_detail.stage_executions[0]
    store.update_routed_task_result(
        contract_enroll.agent_token,
        contract_stage.routed_task_id,
        {
            "status": "completed",
            "transition_id": "contract-plan",
            "summary": "Plan updated.",
            "full_text": "Updated protocol/plan.md.\nPROTOCOL_SUMMARY: Plan updated.",
            "artifacts": [
                {
                    "artifact_key": "plan",
                    "artifact_kind": "workspace_file",
                    "path": "protocol/plan.md",
                    "exists": True,
                    "size_bytes": 128,
                    "content_hash": "plan-contract",
                    "modified_at": "2026-04-16T00:00:00+00:00",
                    "verification_state": "verified",
                }
            ],
        },
    )
    review_detail = store.get_protocol_run(contract_created.run.protocol_run_id, access=operator_access())
    review_stage = review_detail.stage_executions[0]
    store.update_routed_task_result(
        contract_enroll.agent_token,
        review_stage.routed_task_id,
        {
            "status": "completed",
            "transition_id": "contract-invalid-review",
            "summary": "Review omitted the decision marker.",
            "full_text": "Review omitted the required protocol decision.",
        },
    )
    contract_issues = store.list_protocol_issues(
        access=operator_access(),
        issue_kind="invalid_contract",
    )
    assert any(item.protocol_run_id == contract_created.run.protocol_run_id for item in contract_issues)
    assert store.list_protocol_issues(access=operator_access(), issue_kind="not-a-real-issue-kind") == []


def test_registry_store_interrupted_result_blocks_run_and_retry_records_timeline(
    postgres_registry_truncated: str,
) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    enroll, _published, created, detail = running_protocol_run(store)
    stage = detail.stage_executions[0]

    task = store.update_routed_task_result(
        enroll.agent_token,
        stage.routed_task_id,
        {
            "status": "interrupted",
            "transition_id": "interrupted-recovery",
            "summary": "Work was interrupted; retry this stage to continue.",
            "full_text": "Recovered a routed task after the worker restarted before the result was durable.",
        },
    )

    blocked = store.get_protocol_run(created.run.protocol_run_id, access=operator_access())
    assert task.status == "failed"
    assert blocked.run.status == "blocked"
    assert blocked.run.blocked_code == "interrupted"
    assert blocked.stage_executions[0].failure_code == "interrupted"
    assert any(
        item.transition_kind == "blocked" and item.error_code == "TASK_INTERRUPTED"
        for item in blocked.transitions
    )

    retried = store.act_on_protocol_run(
        created.run.protocol_run_id,
        access=operator_access(),
        action="retry",
        reason="Retry interrupted disposable run.",
    )
    refreshed = store.get_protocol_run(created.run.protocol_run_id, access=operator_access())

    assert retried.ok is True
    assert retried.run is not None
    assert retried.run.status == "running"
    assert refreshed.run.current_stage_key == "planning"
    assert refreshed.run.current_stage_execution_id != stage.protocol_stage_execution_id
    previous_stage = next(
        item
        for item in refreshed.stage_executions
        if item.protocol_stage_execution_id == stage.protocol_stage_execution_id
    )
    assert previous_stage.stage_key == "planning"
    assert previous_stage.status == "blocked"
    assert previous_stage.failure_code == "interrupted"
    assert previous_stage.failure_detail == "Work was interrupted; retry this stage to continue."
    assert any(item.transition_kind == "retry" for item in refreshed.transitions)


def test_registry_store_operator_interrupt_blocks_stage_and_queues_cancel_request(
    postgres_registry_truncated: str,
) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    _enroll, _published, created, detail = running_protocol_run(store)
    stage = detail.stage_executions[0]

    interrupted = store.act_on_protocol_run(
        created.run.protocol_run_id,
        access=operator_access(),
        action="interrupt",
        reason="Stop the provider process before retrying.",
    )

    refreshed = store.get_protocol_run(created.run.protocol_run_id, access=operator_access())
    assert interrupted.ok is True
    assert interrupted.run is not None
    assert interrupted.run.status == "blocked"
    assert interrupted.run.blocked_code == "operator_interrupted"
    assert refreshed.stage_executions[0].status == "blocked"
    assert refreshed.stage_executions[0].failure_code == "operator_interrupted"
    assert any(item.transition_kind == "task_cancel_requested" for item in refreshed.transitions)
    assert any(item.transition_kind == "blocked" and item.error_code == "OPERATOR_INTERRUPTED" for item in refreshed.transitions)

    with get_connection(postgres_registry_truncated) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT target_agent_id, operation, payload_json, status
                FROM agent_registry.management_requests
                WHERE operation = 'cancel_routed_task'
                """
            )
            rows = cur.fetchall()
    assert len(rows) == 1
    target_agent_id, _operation, payload, status = rows[0]
    assert target_agent_id
    assert status == "queued"
    assert payload["routed_task_id"] == stage.routed_task_id
    assert payload["protocol_run_id"] == created.run.protocol_run_id
    assert payload["protocol_stage_execution_id"] == stage.protocol_stage_execution_id


def test_registry_store_operator_interrupt_rejects_terminal_run(
    postgres_registry_truncated: str,
) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    enroll, _published, created, detail = running_protocol_run(store)
    first_stage = detail.stage_executions[0]

    store.update_routed_task_result(
        enroll.agent_token,
        first_stage.routed_task_id,
        {
            "status": "completed",
            "transition_id": "terminal-interrupt-plan",
            "summary": "Plan updated.",
            "full_text": "Updated protocol/plan.md.\nPROTOCOL_SUMMARY: Plan updated.",
            "artifacts": [
                {
                    "artifact_key": "plan",
                    "artifact_kind": "workspace_file",
                    "path": "protocol/plan.md",
                    "exists": True,
                    "content_hash": "terminal-interrupt-plan",
                }
            ],
        },
    )
    review_detail = store.get_protocol_run(created.run.protocol_run_id, access=operator_access())
    review_stage = next(item for item in review_detail.stage_executions if item.stage_key == "review")
    store.update_routed_task_result(
        enroll.agent_token,
        review_stage.routed_task_id,
        {
            "status": "completed",
            "transition_id": "terminal-interrupt-review",
            "summary": "Accepted.",
            "full_text": "Looks good.\nPROTOCOL_DECISION: accept\nPROTOCOL_SUMMARY: Accepted.",
        },
    )
    completed = store.get_protocol_run(created.run.protocol_run_id, access=operator_access())
    assert completed.run.status == "completed"

    interrupted = store.act_on_protocol_run(
        created.run.protocol_run_id,
        access=operator_access(),
        action="interrupt",
        reason="Should not reopen.",
    )
    refreshed = store.get_protocol_run(created.run.protocol_run_id, access=operator_access())

    assert interrupted.ok is False
    assert interrupted.status == "concurrent_modification"
    assert refreshed.run.status == "completed"
    assert refreshed.run.blocked_code == ""
    assert refreshed.stage_executions[0].status == "completed"


def test_registry_store_operator_interrupt_cancel_delivery_reaches_coordination_agent(
    postgres_registry_truncated: str,
) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    enroll = store.enroll(agent_card(bot_key="coordination-m1").model_copy(update={"registry_scope": "coordination"}))
    published = published_protocol(store)
    created = store.create_protocol_run(
        {
            "protocol_id": published.protocol.protocol_id,
            "entry_agent_id": enroll.agent_id,
            "origin_channel": "registry",
            "workspace_ref": "default",
            "problem_statement": "Build the feature.",
            "constraints_json": {},
        },
        access=operator_access(),
    )
    detail = store.get_protocol_run(created.run.protocol_run_id, access=operator_access())
    stage = detail.stage_executions[0]

    store.act_on_protocol_run(
        created.run.protocol_run_id,
        access=operator_access(),
        action="interrupt",
        reason="Stop the provider process.",
    )

    poll = store.poll(enroll.agent_token, cursor=0, limit=10)
    delivery = next(item for item in poll.deliveries if item.kind == "management_request")
    assert delivery.payload["payload"]["operation"] == "cancel_routed_task"
    assert delivery.payload["payload"]["routed_task_id"] == stage.routed_task_id


def test_registry_store_late_result_after_operator_interrupt_is_preserved_without_advancing(
    postgres_registry_truncated: str,
) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    enroll, _published, created, detail = running_protocol_run(store)
    stage = detail.stage_executions[0]

    store.act_on_protocol_run(
        created.run.protocol_run_id,
        access=operator_access(),
        action="interrupt",
        reason="Stop before retrying.",
    )

    store.update_routed_task_result(
        enroll.agent_token,
        stage.routed_task_id,
        {
            "status": "completed",
            "transition_id": "late-after-interrupt",
            "summary": "Late completion after interrupt.",
            "full_text": "Updated protocol/plan.md.\nPROTOCOL_SUMMARY: Late completion.",
            "artifacts": [
                {
                    "artifact_key": "plan",
                    "artifact_kind": "workspace_file",
                    "path": "protocol/plan.md",
                    "exists": True,
                    "size_bytes": 128,
                    "content_hash": "late-interrupt-content",
                    "modified_at": "2026-04-16T00:00:00+00:00",
                    "verification_state": "verified",
                }
            ],
        },
    )

    refreshed = store.get_protocol_run(created.run.protocol_run_id, access=operator_access())
    task = store.get_task(stage.routed_task_id)
    task_result = task.result.as_dict() if task.result is not None else {}

    assert refreshed.run.status == "blocked"
    assert refreshed.run.blocked_code == "operator_interrupted"
    assert refreshed.run.current_stage_execution_id == stage.protocol_stage_execution_id
    assert refreshed.stage_executions[0].status == "blocked"
    assert refreshed.stage_executions[0].failure_code == "operator_interrupted"
    assert task_result.get("late_delivery", {}).get("status") == "late_result_preserved"
    assert task_result.get("late_delivery", {}).get("stage_status") == "blocked"
    assert any(item.transition_kind == "late_result" for item in refreshed.transitions)
    assert all(item.content_hash != "late-interrupt-content" for item in refreshed.artifacts)


def test_registry_store_stale_operator_send_back_does_not_block_next_stage(
    postgres_registry_truncated: str,
) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    document = protocol_document()
    document["artifacts"] = [
        *document["artifacts"],
        {
            "artifact_key": "outcome",
            "kind": "workspace_file",
            "path": "protocol/outcome.md",
        },
    ]
    document["stages"][1]["transitions"]["accept"] = "produce"
    document["stages"].append(
        {
            "stage_key": "produce",
            "participant_key": "worker",
            "selector": {"kind": "skill", "value": "writing"},
            "stage_kind": "work",
            "write_capable": True,
            "inputs": ["plan"],
            "outputs": ["outcome"],
            "transitions": {"completed": "__complete__"},
            "instructions": "Write protocol/outcome.md.",
        }
    )
    enroll, _published, created, detail = running_protocol_run(store, document=document)
    planning_stage = detail.stage_executions[0]

    store.update_routed_task_result(
        enroll.agent_token,
        planning_stage.routed_task_id,
        {
            "status": "completed",
            "transition_id": "plan-complete",
            "summary": "Plan updated.",
            "full_text": "Updated protocol/plan.md.\nPROTOCOL_SUMMARY: Plan updated.",
            "artifacts": [
                {
                    "artifact_key": "plan",
                    "artifact_kind": "workspace_file",
                    "path": "protocol/plan.md",
                    "exists": True,
                    "size_bytes": 128,
                    "content_hash": "plan123",
                    "modified_at": "2026-04-16T00:00:00+00:00",
                    "verification_state": "verified",
                }
            ],
        },
    )
    review_detail = store.get_protocol_run(created.run.protocol_run_id, access=operator_access())
    review_stage = next(item for item in review_detail.stage_executions if item.stage_key == "review")
    store.update_routed_task_result(
        enroll.agent_token,
        review_stage.routed_task_id,
        {
            "status": "completed",
            "transition_id": "review-accept",
            "summary": "Accepted.",
            "full_text": "Looks ready.\nPROTOCOL_DECISION: accept\nPROTOCOL_SUMMARY: Accepted.",
        },
    )
    produce_detail = store.get_protocol_run(created.run.protocol_run_id, access=operator_access())
    assert produce_detail.run.status == "running"
    assert produce_detail.run.current_stage_key == "produce"
    assert produce_detail.run.blocked_code == ""

    stale_send_back = store.act_on_protocol_run(
        created.run.protocol_run_id,
        access=operator_access(),
        action="send-back",
        reason="The previous review-stage button was stale.",
        expected_version=produce_detail.run.version,
    )
    refreshed = store.get_protocol_run(created.run.protocol_run_id, access=operator_access())

    assert stale_send_back.ok is False
    assert stale_send_back.status == "concurrent_modification"
    assert "does not allow operator decision 'revise'" in stale_send_back.message
    assert refreshed.run.status == "running"
    assert refreshed.run.current_stage_key == "produce"
    assert refreshed.run.blocked_code == ""
    assert all(item.error_code != "INVALID_OPERATOR_DECISION" for item in refreshed.transitions)


def test_registry_store_does_not_seed_protocol_templates_from_code(postgres_registry_truncated: str) -> None:
    from app.db.postgres_init import run_init

    store = RegistryPostgresStore(postgres_registry_truncated)
    with get_connection(postgres_registry_truncated) as conn:
        assert run_init(conn) == []
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT pd.current_version_id
                FROM agent_registry.protocol_definitions pd
                WHERE pd.slug = 'software-engineering'
                """,
            )
            row = cur.fetchone()
            assert row is None

    assert store.list_protocol_templates(access=operator_access()) == []
    with pytest.raises(KeyError):
        store.get_protocol_template("software-engineering", access=operator_access())


def test_registry_store_authoring_options_and_templates_are_separate_resources(postgres_registry_truncated: str) -> None:
    from app.db.postgres_init import run_init

    store = RegistryPostgresStore(postgres_registry_truncated)
    with get_connection(postgres_registry_truncated) as conn:
        assert run_init(conn) == []
        conn.commit()

    options = store.get_protocol_authoring_options(access=operator_access())
    templates = store.list_protocol_templates(access=operator_access())

    assert templates == []
    assert "design" in options.sections
    assert "advanced" not in options.sections
    assert "review" in options.stage_kind_options
    assert options.default_surface == "standard"
    assert options.operator_surface_available is True


def test_registry_store_publishes_protocol_template_as_snapshot(postgres_registry_truncated: str) -> None:
    from app.db.postgres_init import run_init

    store = RegistryPostgresStore(postgres_registry_truncated)
    with get_connection(postgres_registry_truncated) as conn:
        assert run_init(conn) == []
        conn.commit()

    published = published_protocol(store, slug="template-source")
    assert published.protocol is not None
    template_result = store.publish_protocol_template(
        published.protocol.protocol_id,
        access=operator_access(),
    )

    assert template_result.ok is True
    assert template_result.status == "template_published"
    assert template_result.protocol is not None
    assert template_result.protocol.visibility == "registry_template"
    assert template_result.protocol.lifecycle_state == "published"

    authored_protocols = store.list_protocols(access=operator_access(), limit=100)
    assert all(item.protocol_id != template_result.protocol.protocol_id for item in authored_protocols)
    templates = store.list_protocol_templates(access=operator_access())
    assert any(item.slug == template_result.protocol.slug for item in templates)

    template_document = store.get_protocol_template(template_result.protocol.slug, access=operator_access())
    assert template_document.metadata.as_dict().get("display_name") == "Mini Protocol Template"
    assert template_document.stages[0].instructions == "Write protocol/plan.md."

    changed_document = protocol_document()
    changed_document["metadata"]["slug"] = "template-source"
    changed_document["metadata"]["display_name"] = "Changed Source"
    changed_document["stages"][0]["instructions"] = "Changed after the template snapshot."
    saved = store.save_protocol_draft(
        access=operator_access(),
        protocol_id=published.protocol.protocol_id,
        slug="template-source",
        display_name="Changed Source",
        description="Changed after template publish.",
        definition_json=RegistryJsonRecord.model_validate(changed_document),
    )
    assert saved.ok is True
    republished = store.publish_protocol(published.protocol.protocol_id, access=operator_access())
    assert republished.ok is True

    reloaded_template = store.get_protocol_template(template_result.protocol.slug, access=operator_access())
    assert reloaded_template.metadata.as_dict().get("display_name") == "Mini Protocol Template"
    assert reloaded_template.stages[0].instructions == "Write protocol/plan.md."

    draft_from_template = store.create_protocol_draft(
        ProtocolDraftCreateRecord(
            source_kind="template",
            template_slug=template_result.protocol.slug,
        ),
        access=operator_access(),
    )
    assert draft_from_template.ok is True
    assert draft_from_template.protocol is not None
    assert draft_from_template.protocol.visibility == "org_private"
    assert draft_from_template.protocol.lifecycle_state == "draft"


def test_registry_store_standard_surface_rejects_new_operator_only_selector(
    postgres_registry_truncated: str,
) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    author_access = ProtocolAccessContextRecord(
        actor_ref="author-session",
        org_id="local",
        roles=["author"],
    )
    document = protocol_document()
    document["stages"][0]["selector"] = {"kind": "role", "value": "platform-review"}

    saved = store.save_protocol_draft(
        access=author_access,
        protocol_id="",
        slug="standard-surface-rejects-role-selector",
        display_name="Standard Surface Rejects Role Selector",
        description="Reject advanced selector kinds on the standard surface.",
        definition_json=RegistryJsonRecord.model_validate(document),
        authoring_surface="standard",
    )

    assert saved.ok is False
    assert saved.status == "forbidden"
    assert "runtime selector kind" in (saved.message or "")


def test_registry_store_standard_surface_preserves_existing_operator_only_fields_when_unchanged(
    postgres_registry_truncated: str,
) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    base = protocol_document()
    base["stages"][0]["selector"] = {"kind": "role", "value": "platform-review"}
    base["stages"][0]["timeout_seconds"] = 300

    created = store.save_protocol_draft(
        access=operator_access(),
        protocol_id="",
        slug="operator-managed-selector",
        display_name="Operator Managed Selector",
        description="Created through the operator surface.",
        definition_json=RegistryJsonRecord.model_validate(base),
        authoring_surface="operator",
    )
    assert created.ok is True


    author_access = ProtocolAccessContextRecord(
        actor_ref="author-session",
        org_id="local",
        roles=["author"],
    )
    updated = {
        **base,
        "metadata": {
            **base["metadata"],
            "description": "Normal authors can still edit surrounding protocol metadata.",
        },
    }
    saved = store.save_protocol_draft(
        access=author_access,
        protocol_id=created.protocol.protocol_id,
        slug="operator-managed-selector",
        display_name="Operator Managed Selector",
        description="Normal authors can still edit surrounding protocol metadata.",
        definition_json=RegistryJsonRecord.model_validate(updated),
        authoring_surface="standard",
        expected_revision=created.protocol.draft_revision,
    )

    assert saved.ok is True
    assert saved.protocol is not None
    assert saved.protocol.draft_revision > created.protocol.draft_revision
    assert saved.draft_definition_json["stages"][0]["selector"]["kind"] == "role"
    assert saved.draft_definition_json["stages"][0]["timeout_seconds"] == 300


def test_registry_store_generated_auto_protocol_dispatch_uses_derived_timeout(
    postgres_registry_truncated: str,
) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    enroll = store.enroll(agent_card(bot_key="m1"))
    session = generate_auto_protocol_session(
        ProtocolAutoDesignRequestRecord(
            surface="registry",
            requirement_text=(
                "Build a browser-runnable trading education app with a backend API, "
                "persistent paper-trading state, provider adapters, and acceptance evidence."
            ),
            available_agents=[
                {
                    "agent_id": enroll.agent_id,
                    "display_name": "Builder",
                    "routing_skills": [
                        "architecture",
                        "backend",
                        "domain",
                        "implementation",
                        "product",
                        "review",
                        "testing",
                    ],
                }
            ],
            model_response=ProtocolAutoDesignModelResponseRecord(
                requirement_summary="Build the requested serious product.",
                domain="software product",
                work_packages=[
                    ProtocolAutoDesignWorkPackageRecord(
                        package_key="backend_api",
                        display_name="Backend API",
                        rationale="The product requires a backend and provider adapters.",
                        purpose="Implement API, persistence, and provider abstractions.",
                        quality_bar="The backend behavior is testable and verified.",
                        required_skills=["implementation"],
                    )
                ],
            ),
        ),
        session_id="auto-timeout-session",
        created_at="2026-04-16T00:00:00+00:00",
        updated_at="2026-04-16T00:00:00+00:00",
    )
    document = session.draft_definition_json.as_dict()
    assert {int(stage.get("timeout_seconds") or 0) for stage in document["stages"]} == {0}
    assert any(str(stage.get("stage_key") or "").startswith("produce_") for stage in document["stages"])

    published = published_protocol(store, document=document)
    created = store.create_protocol_run(
        {
            "protocol_id": published.protocol.protocol_id,
            "entry_agent_id": enroll.agent_id,
            "origin_channel": "registry",
            "workspace_ref": "default",
            "problem_statement": "Build the generated product.",
            "constraints_json": {},
        },
        access=operator_access(),
    )
    assert created.ok is True
    assert created.run is not None
    detail = store.get_protocol_run(created.run.protocol_run_id, access=operator_access())
    loaded = store.get_protocol(published.protocol.protocol_id, access=operator_access())
    assert loaded.draft_definition_json.as_dict()["stages"] == document["stages"]
    stage_execution = next(
        item for item in detail.stage_executions
        if item.protocol_stage_execution_id == detail.run.current_stage_execution_id
    )
    assert stage_execution.timeout_at
    created_at = datetime.fromisoformat(stage_execution.started_at)
    timeout_at = datetime.fromisoformat(stage_execution.timeout_at)
    assert (timeout_at - created_at).total_seconds() >= 14_400

    with get_connection(postgres_registry_truncated) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT request_json
                FROM agent_registry.routed_tasks
                WHERE routed_task_id = %s
                """,
                (stage_execution.routed_task_id,),
            )
            task_row = cur.fetchone()
    assert task_row is not None
    request_json = task_row[0]
    contract = request_json["internal_context"]["protocol_stage_contract"]
    assert contract["timeout_seconds"] >= 14_400


def test_registry_store_persists_protocol_artifact_runtime(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    _enroll, _published, _created, detail = running_protocol_run(store)
    runtime = ProtocolArtifactRuntimeInstanceRecord(
        runtime_instance_id="runtime-store-test",
        protocol_run_id=detail.run.protocol_run_id,
        artifact_key="produced_outcome",
        agent_id=detail.run.entry_agent_id,
        status="starting",
        manifest=ProtocolArtifactRuntimeManifestRecord(runtime_kind="static", ui_path="/", health_path="/"),
        artifact_path="/workspace/workspace/protocol/auto/run/output",
        runtime_url=f"/runtime/protocol-runs/{detail.run.protocol_run_id}/artifacts/produced_outcome/app/",
    )

    saved = store.save_protocol_artifact_runtime(runtime, access=operator_access())
    fetched = store.get_protocol_artifact_runtime(
        detail.run.protocol_run_id,
        "produced_outcome",
        access=operator_access(),
    )
    event = store.append_protocol_artifact_runtime_event(
        ProtocolArtifactRuntimeEventRecord(
            runtime_instance_id=saved.runtime_instance_id,
            protocol_run_id=detail.run.protocol_run_id,
            artifact_key="produced_outcome",
            event_kind="starting",
            actor_ref="test",
            summary="Runtime start requested.",
        ),
        access=operator_access(),
    )
    events = store.list_protocol_artifact_runtime_events(
        detail.run.protocol_run_id,
        "produced_outcome",
        access=operator_access(),
    )

    assert saved.runtime_instance_id == "runtime-store-test"
    assert fetched is not None
    assert fetched.manifest is not None
    assert fetched.manifest.runtime_kind == "static"
    assert event.event_kind == "starting"
    assert [item.runtime_event_id for item in events] == [event.runtime_event_id]

    next_runtime = store.save_protocol_artifact_runtime(
        runtime.model_copy(
            update={
                "runtime_instance_id": "runtime-store-test-next",
                "status": "running",
                "updated_at": "2099-01-01T00:00:00Z",
            }
        ),
        access=operator_access(),
    )
    next_event = store.append_protocol_artifact_runtime_event(
        ProtocolArtifactRuntimeEventRecord(
            runtime_instance_id=next_runtime.runtime_instance_id,
            protocol_run_id=detail.run.protocol_run_id,
            artifact_key="produced_outcome",
            event_kind="started",
            actor_ref="test",
            summary="Runtime started.",
        ),
        access=operator_access(),
    )
    current_events = store.list_protocol_artifact_runtime_events(
        detail.run.protocol_run_id,
        "produced_outcome",
        access=operator_access(),
    )

    assert [item.runtime_event_id for item in current_events] == [next_event.runtime_event_id]


def test_registry_store_persists_protocol_artifact_snapshot(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    _enroll, _published, _created, detail = running_protocol_run(store)
    snapshot = ProtocolArtifactSnapshotRecord(
        artifact_snapshot_id="snapshot-store-test",
        protocol_artifact_id=detail.artifacts[0].protocol_artifact_id,
        protocol_run_id=detail.run.protocol_run_id,
        artifact_key=detail.artifacts[0].artifact_key,
        snapshot_kind="directory",
        storage_uri="registry-artifact://snapshots/snapshot-store-test",
        content_hash="sha256:test",
        size_bytes=42,
        created_by="operator:test",
    )

    saved = store.save_protocol_artifact_snapshot(snapshot, access=operator_access())
    fetched = store.get_protocol_artifact_snapshot(
        detail.run.protocol_run_id,
        detail.artifacts[0].artifact_key,
        access=operator_access(),
    )
    exported = store.export_protocol_run(detail.run.protocol_run_id, access=operator_access())

    assert saved.artifact_snapshot_id == "snapshot-store-test"
    assert fetched is not None
    assert fetched.content_hash == "sha256:test"
    assert exported.artifact_snapshots[0].artifact_snapshot_id == "snapshot-store-test"


def test_registry_store_protocol_run_archive_delete_lifecycle(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    _enroll, _published, _created, detail = running_protocol_run(store)

    running_archive = store.archive_protocol_run(detail.run.protocol_run_id, access=operator_access())
    assert running_archive.ok is False
    assert "finish" in running_archive.message.lower()

    with get_connection(postgres_registry_truncated) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE agent_registry.protocol_runs
                SET status = 'completed', completed_at = updated_at
                WHERE protocol_run_id = %s
                """,
                (detail.run.protocol_run_id,),
            )
        conn.commit()

    runtime = store.save_protocol_artifact_runtime(
        ProtocolArtifactRuntimeInstanceRecord(
            runtime_instance_id="runtime-run-lifecycle-test",
            protocol_run_id=detail.run.protocol_run_id,
            artifact_key="produced_outcome",
            agent_id=detail.run.entry_agent_id,
            status="running",
            manifest=ProtocolArtifactRuntimeManifestRecord(runtime_kind="static", ui_path="/", health_path="/"),
            artifact_path="/workspace/workspace/protocol/auto/run/output",
        ),
        access=operator_access(),
    )
    blocked_archive = store.archive_protocol_run(detail.run.protocol_run_id, access=operator_access())
    assert blocked_archive.ok is False
    assert "runtimes" in blocked_archive.message.lower()

    store.save_protocol_artifact_runtime(runtime.model_copy(update={"status": "stopped"}), access=operator_access())
    archived = store.archive_protocol_run(detail.run.protocol_run_id, access=operator_access(), reason="retention test")
    assert archived.ok is True
    assert archived.run is not None
    assert archived.run.status == "archived"
    assert all(item.protocol_run_id != detail.run.protocol_run_id for item in store.list_protocol_runs(access=operator_access()))
    archived_runs = store.list_protocol_runs(access=operator_access(), status="archived")
    assert [item.protocol_run_id for item in archived_runs] == [detail.run.protocol_run_id]

    restored = store.restore_protocol_run(detail.run.protocol_run_id, access=operator_access())
    assert restored.ok is True
    assert restored.run is not None
    assert restored.run.status == "completed"

    deleted = store.delete_protocol_run(detail.run.protocol_run_id, access=operator_access(), reason="retention delete test")
    assert deleted.ok is True
    assert deleted.run is not None
    assert deleted.run.status == "deleted"
    assert all(item.protocol_run_id != detail.run.protocol_run_id for item in store.list_protocol_runs(access=operator_access()))


def test_registry_store_protocol_maintenance_expires_artifact_runtimes(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    _enroll, _published, _created, detail = running_protocol_run(store)
    expired = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    runtime = store.save_protocol_artifact_runtime(
        ProtocolArtifactRuntimeInstanceRecord(
            runtime_instance_id="runtime-expired-test",
            protocol_run_id=detail.run.protocol_run_id,
            artifact_key="produced_outcome",
            agent_id=detail.run.entry_agent_id,
            status="running",
            manifest=ProtocolArtifactRuntimeManifestRecord(runtime_kind="static", ui_path="/", health_path="/"),
            artifact_path="/workspace/workspace/protocol/auto/run/output",
            expires_at=expired,
        ),
        access=operator_access(),
    )

    maintenance = store.run_protocol_maintenance()
    refreshed = store.get_protocol_artifact_runtime(
        detail.run.protocol_run_id,
        "produced_outcome",
        access=operator_access(),
    )
    events = store.list_protocol_artifact_runtime_events(
        detail.run.protocol_run_id,
        "produced_outcome",
        access=operator_access(),
    )

    assert runtime.status == "running"
    assert maintenance.swept_count == 1
    assert refreshed is not None
    assert refreshed.status == "stopped"
    assert refreshed.failure_code == "runtime_expired"
    assert any(item.event_kind == "stopped" for item in events)


def test_registry_store_revises_final_accept_when_expected_runtime_manifest_is_missing_or_invalid(postgres_registry_truncated: str, tmp_path: Path) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    artifact_root = tmp_path / "output"
    artifact_root.mkdir()
    (artifact_root / "README.md").write_text("Run this service with a routed UI.\n", encoding="utf-8")
    document = {
        "metadata": {
            "slug": "runtime-manifest-required",
            "display_name": "Runtime Manifest Required",
            "auto_protocol": {
                "primary_artifact_key": "produced_outcome",
                "primary_artifact": {
                    "artifact_key": "produced_outcome",
                    "open_behavior": "runtime",
                },
                "requirement": "Build a browser-runnable service with a user-facing UI and API.",
            },
        },
        "participants": [
            {"participant_key": "worker", "display_name": "Worker"},
            {"participant_key": "acceptor", "display_name": "Acceptor"},
        ],
        "artifacts": [
            {"artifact_key": "produced_outcome", "kind": "workspace_file", "path": "output"},
            {"artifact_key": "release_evidence", "kind": "workspace_file", "path": "release.md"},
        ],
        "stages": [
            {
                "stage_key": "produce",
                "participant_key": "worker",
                "selector": {"kind": "skill", "value": "implementation"},
                "stage_kind": "work",
                "write_capable": True,
                "outputs": ["produced_outcome"],
                "transitions": {"completed": "final"},
                "instructions": "Produce the runtime artifact.",
            },
            {
                "stage_key": "final",
                "participant_key": "acceptor",
                "selector": {"kind": "skill", "value": "review"},
                "stage_kind": "acceptance",
                "inputs": ["produced_outcome"],
                "outputs": ["release_evidence"],
                "transitions": {"accept": "__complete__", "revise": "produce", "fail": "__failed__"},
                "instructions": "Accept only after runtime evidence exists.",
            },
        ],
        "policies": {"single_active_writer": True, "max_review_rounds": 2},
    }
    enroll, _published, created, detail = running_protocol_run(store, document=document)
    with get_connection(postgres_registry_truncated) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE agent_registry.protocol_runs SET workspace_ref = %s WHERE protocol_run_id = %s",
                (str(tmp_path), created.run.protocol_run_id),
            )
        conn.commit()

    produce = detail.stage_executions[0]
    store.update_routed_task_result(
        enroll.agent_token,
        produce.routed_task_id,
        {
            "status": "completed",
            "transition_id": "runtime-manifest-produce",
            "summary": "Produced package without manifest.",
            "full_text": "Produced output.\nPROTOCOL_SUMMARY: Produced package.",
            "artifacts": [
                {
                    "artifact_key": "produced_outcome",
                    "artifact_kind": "workspace_file",
                    "path": "output",
                    "exists": True,
                    "size_bytes": 100,
                    "content_hash": "runtime-no-manifest",
                    "modified_at": "2026-04-16T00:00:00+00:00",
                    "verification_state": "verified",
                }
            ],
        },
    )
    final_detail = store.get_protocol_run(created.run.protocol_run_id, access=operator_access())
    final_stage = next(item for item in final_detail.stage_executions if item.stage_key == "final")
    store.update_routed_task_result(
        enroll.agent_token,
        final_stage.routed_task_id,
        {
            "status": "completed",
            "transition_id": "runtime-manifest-final",
            "summary": "Accepted.",
            "full_text": "Looks good.\nPROTOCOL_DECISION: accept\nPROTOCOL_SUMMARY: Accepted.",
            "artifacts": [
                {
                    "artifact_key": "release_evidence",
                    "artifact_kind": "workspace_file",
                    "path": "release.md",
                    "exists": True,
                    "size_bytes": 10,
                    "content_hash": "release-no-manifest",
                    "modified_at": "2026-04-16T00:00:00+00:00",
                    "verification_state": "verified",
                }
            ],
        },
    )

    revised = store.get_protocol_run(created.run.protocol_run_id, access=operator_access())
    assert revised.run.status == "running"
    assert revised.run.blocked_code == ""
    assert revised.run.current_stage_key == "produce"
    assert revised.run.current_review_rounds == 1
    assert revised.run.current_review_edge_key == "final:produce"
    missing_transition = next(
        item
        for item in revised.transitions
        if item.transition_kind == "advance" and item.error_code == "RUNTIME_MANIFEST_REQUIRED"
    )
    assert missing_transition.decision == "revise"
    assert missing_transition.metadata_json.as_dict()["runtime_gate_auto_revise"] is True

    (artifact_root / "octopus-runtime.json").write_text(
        json.dumps({"runtime_kind": "java21-maven-spring-service", "endpoints": {"health": "/health"}}),
        encoding="utf-8",
    )
    second_produce = next(
        item
        for item in revised.stage_executions
        if item.stage_key == "produce" and item.status == "running"
    )
    store.update_routed_task_result(
        enroll.agent_token,
        second_produce.routed_task_id,
        {
            "status": "completed",
            "transition_id": "runtime-invalid-manifest-produce",
            "summary": "Produced package with invalid manifest.",
            "full_text": "Produced output.\nPROTOCOL_SUMMARY: Produced package.",
            "artifacts": [
                {
                    "artifact_key": "produced_outcome",
                    "artifact_kind": "workspace_file",
                    "path": "output",
                    "exists": True,
                    "size_bytes": 110,
                    "content_hash": "runtime-invalid-manifest",
                    "modified_at": "2026-04-16T00:00:00+00:00",
                    "verification_state": "verified",
                }
            ],
        },
    )
    second_final_detail = store.get_protocol_run(created.run.protocol_run_id, access=operator_access())
    second_final_stage = next(
        item
        for item in second_final_detail.stage_executions
        if item.stage_key == "final" and item.status == "running"
    )
    store.update_routed_task_result(
        enroll.agent_token,
        second_final_stage.routed_task_id,
        {
            "status": "completed",
            "transition_id": "runtime-invalid-manifest-final",
            "summary": "Accepted.",
            "full_text": "Looks good.\nPROTOCOL_DECISION: accept\nPROTOCOL_SUMMARY: Accepted.",
            "artifacts": [
                {
                    "artifact_key": "release_evidence",
                    "artifact_kind": "workspace_file",
                    "path": "release.md",
                    "exists": True,
                    "size_bytes": 12,
                    "content_hash": "release-invalid-manifest",
                    "modified_at": "2026-04-16T00:00:00+00:00",
                    "verification_state": "verified",
                }
            ],
        },
    )
    invalid = store.get_protocol_run(created.run.protocol_run_id, access=operator_access())
    assert invalid.run.status == "running"
    assert invalid.run.blocked_code == ""
    assert invalid.run.current_stage_key == "produce"
    assert invalid.run.current_review_rounds == 2
    invalid_transition = next(
        item
        for item in invalid.transitions
        if item.transition_kind == "advance" and item.error_code == "RUNTIME_MANIFEST_INVALID"
    )
    assert invalid_transition.decision == "revise"
    assert invalid_transition.metadata_json.as_dict()["runtime_gate_auto_revise"] is True
    third_produce = next(
        item
        for item in invalid.stage_executions
        if item.stage_key == "produce" and item.status == "running"
    )
    assert third_produce.input_snapshot_json["runtime_gate_code"] == "runtime_manifest_invalid"


def test_registry_store_blocks_final_accept_until_runtime_evidence_exists(postgres_registry_truncated: str, tmp_path: Path) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    artifact_root = tmp_path / "output"
    artifact_root.mkdir()
    (artifact_root / "octopus-runtime.json").write_text(
        json.dumps({"runtime_kind": "static", "ui_path": "/", "health_path": "/"}),
        encoding="utf-8",
    )
    document = {
        "metadata": {
            "slug": "runtime-proof",
            "display_name": "Runtime Proof",
            "auto_protocol": {"primary_artifact_key": "produced_outcome"},
        },
        "participants": [
            {"participant_key": "worker", "display_name": "Worker"},
            {"participant_key": "acceptor", "display_name": "Acceptor"},
        ],
        "artifacts": [
            {"artifact_key": "produced_outcome", "kind": "workspace_file", "path": "output"},
            {"artifact_key": "release_evidence", "kind": "workspace_file", "path": "release.md"},
        ],
        "stages": [
            {
                "stage_key": "produce",
                "participant_key": "worker",
                "selector": {"kind": "skill", "value": "implementation"},
                "stage_kind": "work",
                "write_capable": True,
                "outputs": ["produced_outcome"],
                "transitions": {"completed": "final"},
                "instructions": "Produce the runtime artifact.",
            },
            {
                "stage_key": "final",
                "participant_key": "acceptor",
                "selector": {"kind": "skill", "value": "review"},
                "stage_kind": "acceptance",
                "inputs": ["produced_outcome"],
                "outputs": ["release_evidence"],
                "transitions": {"accept": "__complete__", "revise": "produce", "fail": "__failed__"},
                "instructions": "Accept only after runtime evidence exists.",
            },
        ],
        "policies": {"single_active_writer": True, "max_review_rounds": 2},
    }
    enroll, _published, created, detail = running_protocol_run(store, document=document)
    with get_connection(postgres_registry_truncated) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE agent_registry.protocol_runs SET workspace_ref = %s WHERE protocol_run_id = %s",
                (str(tmp_path), created.run.protocol_run_id),
            )
        conn.commit()

    produce = detail.stage_executions[0]
    store.update_routed_task_result(
        enroll.agent_token,
        produce.routed_task_id,
        {
            "status": "completed",
            "transition_id": "runtime-produce",
            "summary": "Produced runtime package.",
            "full_text": "Produced output.\nPROTOCOL_SUMMARY: Produced runtime package.",
            "artifacts": [
                {
                    "artifact_key": "produced_outcome",
                    "artifact_kind": "workspace_file",
                    "path": "output",
                    "exists": True,
                    "size_bytes": 100,
                    "content_hash": "runtime123",
                    "modified_at": "2026-04-16T00:00:00+00:00",
                    "verification_state": "verified",
                }
            ],
        },
    )
    final_detail = store.get_protocol_run(created.run.protocol_run_id, access=operator_access())
    final_stage = next(item for item in final_detail.stage_executions if item.stage_key == "final")
    store.update_routed_task_result(
        enroll.agent_token,
        final_stage.routed_task_id,
        {
            "status": "completed",
            "transition_id": "runtime-final",
            "summary": "Accepted.",
            "full_text": "Looks good.\nPROTOCOL_DECISION: accept\nPROTOCOL_SUMMARY: Accepted.",
            "artifacts": [
                {
                    "artifact_key": "release_evidence",
                    "artifact_kind": "workspace_file",
                    "path": "release.md",
                    "exists": True,
                    "size_bytes": 10,
                    "content_hash": "release123",
                    "modified_at": "2026-04-16T00:00:00+00:00",
                    "verification_state": "verified",
                }
            ],
        },
    )

    blocked = store.get_protocol_run(created.run.protocol_run_id, access=operator_access())
    assert blocked.run.status == "blocked"
    assert blocked.run.blocked_code == "runtime_evidence_required"

    runtime = store.save_protocol_artifact_runtime(
        ProtocolArtifactRuntimeInstanceRecord(
            runtime_instance_id="runtime-evidence-test",
            protocol_run_id=created.run.protocol_run_id,
            artifact_key="produced_outcome",
            agent_id=created.run.entry_agent_id,
            status="running",
            manifest=ProtocolArtifactRuntimeManifestRecord(runtime_kind="static", ui_path="/", health_path="/"),
            artifact_path=str(artifact_root),
            runtime_url=f"/runtime/protocol-runs/{created.run.protocol_run_id}/artifacts/produced_outcome/app/",
        ),
        access=operator_access(),
    )
    for event_kind, metadata in (
        ("started", {}),
        ("health_checked", {"ok": True, "status_code": 200}),
        ("fetch", {"status_code": 200, "method": "GET", "path": "/", "is_api": False}),
        ("client_interaction", {"event_type": "click", "tag": "button", "text": "Run scenario"}),
    ):
        store.append_protocol_artifact_runtime_event(
            ProtocolArtifactRuntimeEventRecord(
                runtime_instance_id=runtime.runtime_instance_id,
                protocol_run_id=created.run.protocol_run_id,
                artifact_key="produced_outcome",
                event_kind=event_kind,
                actor_ref="operator-session",
                summary=event_kind,
                metadata_json=RegistryJsonRecord.model_validate(metadata),
            ),
            access=operator_access(),
        )

    still_blocked = store.act_on_protocol_run(
        created.run.protocol_run_id,
        access=operator_access(),
        action="accept",
        reason="Opened the app and clicked Run scenario, but no visible result was displayed.",
    )
    assert still_blocked.ok is True
    assert still_blocked.run is not None
    assert still_blocked.run.status == "blocked"
    assert still_blocked.run.blocked_code == "runtime_evidence_required"

    store.append_protocol_artifact_runtime_event(
        ProtocolArtifactRuntimeEventRecord(
            runtime_instance_id=runtime.runtime_instance_id,
            protocol_run_id=created.run.protocol_run_id,
            artifact_key="produced_outcome",
            event_kind="fetch",
            actor_ref="operator-session",
            summary="POST /decisions -> 200",
            metadata_json=RegistryJsonRecord.model_validate({
                "status_code": 200,
                "method": "POST",
                "path": "/decisions",
                "is_api": True,
            }),
        ),
        access=operator_access(),
    )
    matrix_blocked = store.act_on_protocol_run(
        created.run.protocol_run_id,
        access=operator_access(),
        action="accept",
        reason="Clicked Run scenario and the decision result was displayed in the app.",
    )
    assert matrix_blocked.ok is True
    assert matrix_blocked.run is not None
    assert matrix_blocked.run.status == "blocked"
    assert matrix_blocked.run.blocked_code == "runtime_evidence_required"
    assert "outcome-readiness matrix" in matrix_blocked.run.blocked_detail

    accepted = store.act_on_protocol_run(
        created.run.protocol_run_id,
        access=operator_access(),
        action="accept",
        reason=(
            "Outcome-readiness matrix:\n"
            "PASS journey 1: clicked Run scenario and the decision result was displayed in the app.\n"
            "Branding check: no Octopus branding appears in customer-facing UI/API copy; Octopus is only internal runtime evidence."
        ),
    )
    exported = store.export_protocol_run(created.run.protocol_run_id, access=operator_access())

    assert accepted.ok is True
    assert accepted.run is not None
    assert accepted.run.status == "completed"
    assert [item.runtime_instance_id for item in exported.runtime_instances] == [runtime.runtime_instance_id]
    assert {item.event_kind for item in exported.runtime_events} >= {
        "started",
        "health_checked",
        "fetch",
        "client_interaction",
    }


def test_registry_store_contract_runtime_gate_requires_hooks_and_structured_journeys(postgres_registry_truncated: str, tmp_path: Path) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    artifact_root = tmp_path / "output"
    artifact_root.mkdir()
    (artifact_root / "index.html").write_text(
        '<button data-testid="primary-action">Run</button><section data-testid="primary-result">Ready</section>',
        encoding="utf-8",
    )
    (artifact_root / "octopus-runtime.json").write_text(
        json.dumps({
            "runtime_kind": "static",
            "ui_path": "/",
            "health_path": "/health",
            "test_hooks": [
                {"hook": "primary_action", "selector": "[data-testid='primary-action']", "kind": "button"},
            ],
        }),
        encoding="utf-8",
    )
    release_evidence = tmp_path / "release.md"
    release_evidence.write_text("Release evidence.\n", encoding="utf-8")
    reviewer_manifest = tmp_path / "reviewer.json"
    reviewer_manifest.write_text(json.dumps({"checks": [{"id": "primary_happy_path", "status": "passed"}]}), encoding="utf-8")
    document = {
        "metadata": {
            "slug": "structured-runtime-proof",
            "display_name": "Structured Runtime Proof",
            "auto_protocol": {
                "primary_artifact_key": "produced_outcome",
                "primary_artifact": {
                    "artifact_key": "produced_outcome",
                    "open_behavior": "runtime",
                },
                "acceptance_contract": {
                    "schema_version": 1,
                    "primary_artifact_key": "produced_outcome",
                    "reviewer_manifest_artifact_key": "reviewer_evidence_manifest",
                    "required_journeys": [
                        {
                            "journey_key": "primary_happy_path",
                            "required_hooks": ["primary_action", "primary_result"],
                            "steps": [{"action": "click", "hook": "primary_action"}],
                            "assertions": [{"action": "assert_visible", "hook": "primary_result"}],
                        }
                    ],
                },
            },
        },
        "participants": [
            {"participant_key": "worker", "display_name": "Worker"},
            {"participant_key": "acceptor", "display_name": "Acceptor"},
        ],
        "artifacts": [
            {"artifact_key": "produced_outcome", "kind": "workspace_file", "path": "output"},
            {"artifact_key": "release_evidence", "kind": "workspace_file", "path": "release.md"},
            {"artifact_key": "reviewer_evidence_manifest", "kind": "workspace_file", "path": "reviewer.json"},
        ],
        "stages": [
            {
                "stage_key": "produce",
                "participant_key": "worker",
                "selector": {"kind": "skill", "value": "implementation"},
                "stage_kind": "work",
                "write_capable": True,
                "outputs": ["produced_outcome"],
                "transitions": {"completed": "final"},
                "instructions": "Produce the runtime artifact.",
            },
            {
                "stage_key": "final",
                "participant_key": "acceptor",
                "selector": {"kind": "skill", "value": "review"},
                "stage_kind": "acceptance",
                "inputs": ["produced_outcome"],
                "outputs": ["release_evidence", "reviewer_evidence_manifest"],
                "strict_completion": False,
                "require_output_verification": False,
                "transitions": {"accept": "__complete__", "revise": "produce", "fail": "__failed__"},
                "instructions": "Accept only after structured runtime evidence exists.",
            },
        ],
        "policies": {"single_active_writer": True, "max_review_rounds": 2},
    }
    enroll, _published, created, detail = running_protocol_run(store, document=document)
    with get_connection(postgres_registry_truncated) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE agent_registry.protocol_runs SET workspace_ref = %s WHERE protocol_run_id = %s",
                (str(tmp_path), created.run.protocol_run_id),
            )
        conn.commit()

    produce = detail.stage_executions[0]
    store.update_routed_task_result(
        enroll.agent_token,
        produce.routed_task_id,
        {
            "status": "completed",
            "transition_id": "structured-runtime-produce",
            "summary": "Produced runtime package.",
            "full_text": "Produced output.\nPROTOCOL_SUMMARY: Produced runtime package.",
            "artifacts": [
                {
                    "artifact_key": "produced_outcome",
                    "artifact_kind": "workspace_file",
                    "path": "output",
                    "exists": True,
                    "size_bytes": 100,
                    "content_hash": "structured-runtime",
                    "modified_at": "2026-04-16T00:00:00+00:00",
                    "verification_state": "verified",
                }
            ],
        },
    )
    final_detail = store.get_protocol_run(created.run.protocol_run_id, access=operator_access())
    final_stage = next(item for item in final_detail.stage_executions if item.stage_key == "final")
    store.update_routed_task_result(
        enroll.agent_token,
        final_stage.routed_task_id,
        {
            "status": "completed",
            "transition_id": "structured-runtime-final-missing-hook",
            "summary": "Accepted.",
            "full_text": "Looks good.\nPROTOCOL_DECISION: accept\nPROTOCOL_SUMMARY: Accepted.",
            "artifacts": [
                {
                    "artifact_key": "release_evidence",
                    "artifact_kind": "workspace_file",
                    "path": str(release_evidence),
                    "exists": True,
                    "size_bytes": release_evidence.stat().st_size,
                    "content_hash": "release-structured-1",
                    "modified_at": "2026-04-16T00:00:00+00:00",
                    "verification_state": "verified",
                },
                {
                    "artifact_key": "reviewer_evidence_manifest",
                    "artifact_kind": "workspace_file",
                    "path": str(reviewer_manifest),
                    "exists": True,
                    "size_bytes": reviewer_manifest.stat().st_size,
                    "content_hash": "reviewer-structured-1",
                    "modified_at": "2026-04-16T00:00:00+00:00",
                    "verification_state": "verified",
                },
            ],
        },
    )
    revised = store.get_protocol_run(created.run.protocol_run_id, access=operator_access())
    assert revised.run.status == "running"
    assert revised.run.current_stage_key == "produce"
    assert any(
        item.error_code == "RUNTIME_MANIFEST_HOOKS_MISSING"
        for item in revised.transitions
    )

    (artifact_root / "octopus-runtime.json").write_text(
        json.dumps({
            "runtime_kind": "static",
            "ui_path": "/",
            "health_path": "/health",
            "test_hooks": [
                {"hook": "primary_action", "selector": "[data-testid='primary-action']", "kind": "button"},
                {"hook": "primary_result", "selector": "[data-testid='primary-result']", "kind": "region"},
            ],
        }),
        encoding="utf-8",
    )
    clean_document = json.loads(json.dumps(document))
    clean_document["metadata"]["slug"] = "structured-runtime-proof-clean"
    enroll_2 = store.enroll(agent_card(bot_key="m2"))
    published_2 = published_protocol(store, slug="mini-protocol-clean", document=clean_document)
    created_2 = store.create_protocol_run(
        {
            "protocol_id": published_2.protocol.protocol_id,
            "entry_agent_id": enroll_2.agent_id,
            "origin_channel": "registry",
            "workspace_ref": "default",
            "problem_statement": "Build the feature.",
            "constraints_json": {},
        },
        access=operator_access(),
    )
    assert created_2.ok is True
    assert created_2.run is not None
    detail_2 = store.get_protocol_run(created_2.run.protocol_run_id, access=operator_access())
    with get_connection(postgres_registry_truncated) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE agent_registry.protocol_runs SET workspace_ref = %s WHERE protocol_run_id = %s",
                (str(tmp_path), created_2.run.protocol_run_id),
            )
        conn.commit()

    second_produce = detail_2.stage_executions[0]
    store.update_routed_task_result(
        enroll_2.agent_token,
        second_produce.routed_task_id,
        {
            "status": "completed",
            "transition_id": "structured-runtime-produce-fixed",
            "summary": "Produced runtime package with hooks.",
            "full_text": "Produced output.\nPROTOCOL_SUMMARY: Produced runtime package.",
            "artifacts": [
                {
                    "artifact_key": "produced_outcome",
                    "artifact_kind": "workspace_file",
                    "path": "output",
                    "exists": True,
                    "size_bytes": 110,
                    "content_hash": "structured-runtime-fixed",
                    "modified_at": "2026-04-16T00:00:00+00:00",
                    "verification_state": "verified",
                }
            ],
        },
    )
    second_final_detail = store.get_protocol_run(created_2.run.protocol_run_id, access=operator_access())
    second_final = next(item for item in second_final_detail.stage_executions if item.stage_key == "final" and item.status == "running")
    runtime = store.save_protocol_artifact_runtime(
        ProtocolArtifactRuntimeInstanceRecord(
            runtime_instance_id="structured-runtime-instance",
            protocol_run_id=created_2.run.protocol_run_id,
            artifact_key="produced_outcome",
            agent_id=created_2.run.entry_agent_id,
            status="running",
            manifest=ProtocolArtifactRuntimeManifestRecord.model_validate(json.loads((artifact_root / "octopus-runtime.json").read_text(encoding="utf-8"))),
            artifact_path=str(artifact_root),
            runtime_url=f"/runtime/protocol-runs/{created_2.run.protocol_run_id}/artifacts/produced_outcome/app/",
        ),
        access=operator_access(),
    )
    for event_kind, metadata in (
        ("started", {}),
        ("health_checked", {"ok": True, "status_code": 200}),
    ):
        store.append_protocol_artifact_runtime_event(
            ProtocolArtifactRuntimeEventRecord(
                runtime_instance_id=runtime.runtime_instance_id,
                protocol_run_id=created_2.run.protocol_run_id,
                artifact_key="produced_outcome",
                event_kind=event_kind,
                actor_ref="operator-session",
                summary=event_kind,
                metadata_json=RegistryJsonRecord.model_validate(metadata),
            ),
            access=operator_access(),
    )
    store.update_routed_task_result(
        enroll_2.agent_token,
        second_final.routed_task_id,
        {
            "status": "completed",
            "transition_id": "structured-runtime-final-no-journey",
            "summary": "Accepted.",
            "full_text": "Looks good.\nPROTOCOL_DECISION: accept\nPROTOCOL_SUMMARY: Accepted.",
            "artifacts": [
                {
                    "artifact_key": "release_evidence",
                    "artifact_kind": "workspace_file",
                    "path": str(release_evidence),
                    "exists": True,
                    "size_bytes": release_evidence.stat().st_size,
                    "content_hash": "release-structured-2",
                    "modified_at": "2026-04-16T00:00:00+00:00",
                    "verification_state": "verified",
                },
                {
                    "artifact_key": "reviewer_evidence_manifest",
                    "artifact_kind": "workspace_file",
                    "path": str(reviewer_manifest),
                    "exists": True,
                    "size_bytes": reviewer_manifest.stat().st_size,
                    "content_hash": "reviewer-structured-2",
                    "modified_at": "2026-04-16T00:00:00+00:00",
                    "verification_state": "verified",
                },
            ],
        },
    )
    blocked = store.get_protocol_run(created_2.run.protocol_run_id, access=operator_access())
    assert blocked.run.status == "blocked"
    assert blocked.run.blocked_code == "runtime_evidence_required"
    assert "structured journey result: primary_happy_path" in blocked.run.blocked_detail
    reviewer_artifact = next(item for item in blocked.artifacts if item.artifact_key == "reviewer_evidence_manifest")
    store.save_protocol_artifact_snapshot(
        ProtocolArtifactSnapshotRecord(
            artifact_snapshot_id="reviewer-structured-snapshot",
            protocol_artifact_id=reviewer_artifact.protocol_artifact_id,
            protocol_run_id=created_2.run.protocol_run_id,
            artifact_key="reviewer_evidence_manifest",
            snapshot_kind="file",
            storage_uri=str(reviewer_manifest),
            content_hash="reviewer-structured-2",
            size_bytes=reviewer_manifest.stat().st_size,
        ),
        access=operator_access(),
    )

    store.append_protocol_artifact_runtime_event(
        ProtocolArtifactRuntimeEventRecord(
            runtime_instance_id=runtime.runtime_instance_id,
            protocol_run_id=created_2.run.protocol_run_id,
            artifact_key="produced_outcome",
            event_kind="journey_completed",
            actor_ref="runtime-capability:cap-1:stage-1:acceptor",
            summary="Forged journey completed.",
            metadata_json=RegistryJsonRecord.model_validate({
                "journey_key": "primary_happy_path",
                "journey_run_id": "forged-journey-1",
                "ok": True,
                "status": "passed",
            }),
        ),
        access=operator_access(),
    )
    still_blocked = store.act_on_protocol_run(
        created_2.run.protocol_run_id,
        access=operator_access(),
        action="accept",
        reason="Forged structured journey evidence should not count.",
    )
    assert still_blocked.ok is True
    assert still_blocked.run is not None
    assert still_blocked.run.status == "blocked"
    assert "structured journey result: primary_happy_path" in still_blocked.run.blocked_detail

    requested_event = store.append_protocol_artifact_runtime_event(
        ProtocolArtifactRuntimeEventRecord(
            runtime_instance_id=runtime.runtime_instance_id,
            protocol_run_id=created_2.run.protocol_run_id,
            artifact_key="produced_outcome",
            event_kind="journey_requested",
            actor_ref="operator-session",
            summary="Journey requested.",
            metadata_json=RegistryJsonRecord.model_validate({
                "journey_key": "primary_happy_path",
                "journey_run_id": "journey-1",
                "source": "operator_journey_run",
                "runtime_instance_id": runtime.runtime_instance_id,
                "artifact_content_hash": "structured-runtime-fixed",
            }),
        ),
        access=operator_access(),
    )
    store.append_protocol_artifact_runtime_event(
        ProtocolArtifactRuntimeEventRecord(
            runtime_instance_id=runtime.runtime_instance_id,
            protocol_run_id=created_2.run.protocol_run_id,
            artifact_key="produced_outcome",
            event_kind="journey_completed",
            actor_ref=f"runtime-capability:cap-1:{second_final.protocol_stage_execution_id}:acceptor",
            summary="Journey completed.",
            metadata_json=RegistryJsonRecord.model_validate({
                "journey_key": "primary_happy_path",
                "journey_run_id": "journey-1",
                "ok": True,
                "status": "passed",
                "source": "registry_journey_runner",
                "requested_event_id": requested_event.runtime_event_id,
                "runtime_instance_id": runtime.runtime_instance_id,
                "artifact_content_hash": "structured-runtime-fixed",
                "actor_stage_execution_id": second_final.protocol_stage_execution_id,
            }),
        ),
        access=operator_access(),
    )
    accepted = store.get_protocol_run(created_2.run.protocol_run_id, access=operator_access())
    assert accepted.run.status == "completed", accepted.run.blocked_detail


def test_registry_store_v2_contract_gate_requires_reviewed_contract_and_corroborated_evidence(
    postgres_registry_truncated: str,
    tmp_path: Path,
) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    now = "2026-04-16T00:00:00+00:00"
    artifact_root = tmp_path / "output"
    artifact_root.mkdir()
    (artifact_root / "index.html").write_text(
        '<button data-testid="primary-action">Run</button><section data-testid="primary-result">Ready</section>',
        encoding="utf-8",
    )
    (artifact_root / "octopus-runtime.json").write_text(
        json.dumps({
            "runtime_kind": "static",
            "ui_path": "/",
            "health_path": "/health",
            "test_hooks": [
                {"hook": "primary_action", "selector": "[data-testid='primary-action']", "kind": "button"},
                {"hook": "primary_result", "selector": "[data-testid='primary-result']", "kind": "region"},
            ],
        }),
        encoding="utf-8",
    )

    contract_file = tmp_path / "auto_protocol_contract.json"
    product_domain_file = tmp_path / "product_domain_contract.json"
    product_domain_review_file = tmp_path / "product_domain_review.md"
    contract_review_file = tmp_path / "auto_protocol_contract_review.md"
    release_file = tmp_path / "release.md"
    producer_manifest_file = tmp_path / "producer_manifest.json"
    reviewer_manifest_file = tmp_path / "reviewer_manifest.json"
    product_domain_document = {
        "product_contract": {
            "users": ["operator"],
            "workflows": ["research a symbol and see a visible result"],
            "success_criteria": ["the UI and API both update for a new symbol"],
            "unsafe_actions": ["placing live orders"],
            "visible_outcomes": ["primary result is visible"],
            "non_goals": ["profit promises"],
        },
        "domain_contract": {
            "domain_terms": ["quote"],
            "expert_assumptions": ["market data may be delayed"],
            "required_sources": ["fixture provider"],
            "caveats": ["educational only"],
            "operator_decisions_required": [],
            "do_not_claim": ["guaranteed profit"],
        },
    }
    product_domain_file.write_text(json.dumps(product_domain_document), encoding="utf-8")
    product_domain_review_file.write_text("Product/domain contract accepted.\n", encoding="utf-8")
    contract_review_file.write_text("System/verification contract accepted.\n", encoding="utf-8")
    release_file.write_text("Release evidence.\n", encoding="utf-8")
    contract_document = {
        "product_contract": {
            "users": ["operator"],
            "workflows": ["research a symbol and see a visible result"],
            "success_criteria": ["the UI and API both update for a new symbol"],
            "unsafe_actions": ["placing live orders"],
            "visible_outcomes": ["primary result is visible"],
            "non_goals": ["profit promises"],
        },
        "domain_contract": {
            "domain_terms": ["quote"],
            "expert_assumptions": ["market data may be delayed"],
            "required_sources": ["fixture provider"],
            "caveats": ["educational only"],
            "operator_decisions_required": [],
            "do_not_claim": ["guaranteed profit"],
        },
        "system_contract": {
            "api_surface": [{"method": "GET", "path": "/api/quote"}],
            "persistence_invariants": ["failed validation does not mutate state"],
            "provider_ports": ["MarketDataProvider"],
            "external_callouts": ["fixture market data"],
            "secrets_auth_boundaries": ["no frontend secrets"],
            "failure_behavior": ["provider unavailable returns status payload, not 500"],
        },
        "verification_contract": {
            "required_journeys": [
                {
                    "journey_key": "primary_happy_path",
                    "required_hooks": ["primary_action", "primary_result"],
                    "steps": [{"action": "click", "hook": "primary_action"}],
                    "assertions": [{"action": "assert_visible", "hook": "primary_result"}],
                }
            ],
            "required_evidence": [
                {"evidence_id": "runtime_started", "kind": "runtime_start", "trust_tier": "tier_1"},
                {"evidence_id": "runtime_healthy", "kind": "runtime_health", "trust_tier": "tier_1"},
                {
                    "evidence_id": "quote_api_probe",
                    "kind": "api_probe",
                    "trust_tier": "tier_1",
                    "command_or_probe": {"method": "GET", "path": "/api/quote", "status_code": 200},
                },
                {
                    "evidence_id": "primary_happy_path",
                    "kind": "browser_journey",
                    "trust_tier": "tier_1",
                    "journey_key": "primary_happy_path",
                },
                {"evidence_id": "no_failed_mutation", "kind": "db_invariant", "trust_tier": "tier_2"},
                {"evidence_id": "unsafe_trade_rejected", "kind": "negative_case", "trust_tier": "tier_2"},
                {"evidence_id": "domain_sources", "kind": "domain_source", "trust_tier": "tier_3"},
            ],
        },
    }

    def document(slug: str) -> dict[str, object]:
        return {
            "metadata": {
                "slug": slug,
                "display_name": "V2 Contract Proof",
                "auto_protocol": {
                    "primary_artifact_key": "produced_outcome",
                    "primary_artifact": {
                        "artifact_key": "produced_outcome",
                        "open_behavior": "runtime",
                    },
                    "acceptance_contract": {
                        "schema_version": 2,
                        "contract_required": True,
                        "product_class": "app",
                        "primary_artifact_key": "produced_outcome",
                        "contract_artifact_key": "auto_protocol_contract",
                        "contract_producer_stage_key": "produce_system_verification_contract",
                        "contract_review_stage_key": "review_system_verification_contract",
                        "product_domain_contract_artifact_key": "product_domain_contract",
                        "product_domain_contract_producer_stage_key": "produce_product_domain_contract",
                        "product_domain_contract_review_stage_key": "review_product_domain_contract",
                        "producer_manifest_artifact_key": "producer_evidence_manifest",
                        "reviewer_manifest_artifact_key": "reviewer_evidence_manifest",
                    },
                },
            },
            "participants": [
                {"participant_key": "worker", "display_name": "Worker"},
                {"participant_key": "reviewer", "display_name": "Reviewer"},
                {"participant_key": "acceptor", "display_name": "Acceptor"},
            ],
            "artifacts": [
                {"artifact_key": "product_domain_contract", "kind": "workspace_file", "path": "product-domain.json"},
                {"artifact_key": "product_domain_contract_review", "kind": "workspace_file", "path": "product-domain-review.md"},
                {"artifact_key": "auto_protocol_contract", "kind": "workspace_file", "path": "auto_protocol_contract.json"},
                {"artifact_key": "auto_protocol_contract_review", "kind": "workspace_file", "path": "auto-contract-review.md"},
                {"artifact_key": "produced_outcome", "kind": "workspace_file", "path": "output"},
                {"artifact_key": "producer_evidence_manifest", "kind": "workspace_file", "path": "producer_manifest.json"},
                {"artifact_key": "release_evidence", "kind": "workspace_file", "path": "release.md"},
                {"artifact_key": "reviewer_evidence_manifest", "kind": "workspace_file", "path": "reviewer_manifest.json"},
            ],
            "stages": [
                {
                    "stage_key": "produce_product_domain_contract",
                    "participant_key": "worker",
                    "selector": {"kind": "skill", "value": "planning"},
                    "stage_kind": "work",
                    "write_capable": True,
                    "outputs": ["product_domain_contract"],
                    "transitions": {"completed": "review_product_domain_contract"},
                    "instructions": "Produce the product/domain contract.",
                },
                {
                    "stage_key": "review_product_domain_contract",
                    "participant_key": "reviewer",
                    "selector": {"kind": "skill", "value": "review"},
                    "stage_kind": "review",
                    "inputs": ["product_domain_contract"],
                    "outputs": ["product_domain_contract_review"],
                    "review_of_stage_key": "produce_product_domain_contract",
                    "transitions": {"accept": "produce_system_verification_contract", "revise": "produce_product_domain_contract"},
                    "instructions": "Review the product/domain contract.",
                },
                {
                    "stage_key": "produce_system_verification_contract",
                    "participant_key": "worker",
                    "selector": {"kind": "skill", "value": "architecture"},
                    "stage_kind": "work",
                    "write_capable": True,
                    "inputs": ["product_domain_contract", "product_domain_contract_review"],
                    "outputs": ["auto_protocol_contract"],
                    "transitions": {"completed": "review_system_verification_contract"},
                    "instructions": "Produce the authoritative contract.",
                },
                {
                    "stage_key": "review_system_verification_contract",
                    "participant_key": "reviewer",
                    "selector": {"kind": "skill", "value": "review"},
                    "stage_kind": "review",
                    "inputs": ["auto_protocol_contract"],
                    "outputs": ["auto_protocol_contract_review"],
                    "review_of_stage_key": "produce_system_verification_contract",
                    "transitions": {"accept": "produce_outcome", "revise": "produce_system_verification_contract"},
                    "instructions": "Review the authoritative contract.",
                },
                {
                    "stage_key": "produce_outcome",
                    "participant_key": "worker",
                    "selector": {"kind": "skill", "value": "implementation"},
                    "stage_kind": "work",
                    "write_capable": True,
                    "inputs": ["auto_protocol_contract"],
                    "outputs": ["produced_outcome", "producer_evidence_manifest"],
                    "transitions": {"completed": "final_evidence"},
                    "instructions": "Produce the runtime artifact.",
                },
                {
                    "stage_key": "final_evidence",
                    "participant_key": "acceptor",
                    "selector": {"kind": "skill", "value": "review"},
                    "stage_kind": "acceptance",
                    "inputs": ["produced_outcome", "auto_protocol_contract"],
                    "outputs": ["release_evidence", "reviewer_evidence_manifest"],
                    "review_of_stage_key": "produce_outcome",
                    "strict_completion": False,
                    "require_output_verification": False,
                    "transitions": {"accept": "__complete__", "revise": "produce_outcome", "fail": "__failed__"},
                    "instructions": "Accept only after v2 contract evidence exists.",
                },
            ],
            "policies": {"single_active_writer": True, "max_review_rounds": 2},
        }

    def artifact_id(detail, key: str) -> str:
        return next(item.protocol_artifact_id for item in detail.artifacts if item.artifact_key == key)

    def save_snapshot(run_id: str, detail, key: str, path: Path, content_hash: str, stage_execution_id: str) -> None:
        store.save_protocol_artifact_snapshot(
            ProtocolArtifactSnapshotRecord(
                artifact_snapshot_id=f"{run_id}-{key}-{stage_execution_id}",
                protocol_artifact_id=artifact_id(detail, key),
                protocol_run_id=run_id,
                artifact_key=key,
                snapshot_kind="file",
                storage_uri=str(path),
                content_hash=content_hash,
                size_bytes=path.stat().st_size,
                produced_by_stage_execution_id=stage_execution_id,
            ),
            access=operator_access(),
        )

    def update_stage(enroll, stage, transition_id: str, artifacts: list[dict[str, object]] | None = None, decision: str = "") -> None:
        full_text = f"{stage.stage_key} complete.\nPROTOCOL_SUMMARY: done."
        if decision:
            full_text += f"\nPROTOCOL_DECISION: {decision}"
        store.update_routed_task_result(
            enroll.agent_token,
            stage.routed_task_id,
            {
                "status": "completed",
                "transition_id": transition_id,
                "summary": "Done.",
                "full_text": full_text,
                "artifacts": artifacts or [],
            },
        )

    def running_stage(detail, stage_key: str):
        stage = next(
            (item for item in detail.stage_executions if item.stage_key == stage_key and item.status == "running"),
            None,
        )
        assert stage is not None, [
            (item.stage_key, item.status, item.failure_code, item.failure_detail)
            for item in detail.stage_executions
        ]
        return stage

    def run_to_final(
        slug: str,
        *,
        contract_snapshot_stage: str = "correct",
        product_domain_snapshot_stage: str = "correct",
        include_api_fetch: bool = True,
        reviewer_source: str = "final",
        stale_product_domain_ref: bool = False,
        unresolved_operator_decision: bool = False,
        unsupported_tier1_kind: bool = False,
        tier3_substitution: bool = False,
        malformed_product_domain: bool = False,
    ):
        enroll = store.enroll(agent_card(bot_key=f"m-{uuid.uuid4().hex[:8]}"))
        published = published_protocol(store, slug=slug, document=document(slug))
        created = store.create_protocol_run(
            {
                "protocol_id": published.protocol.protocol_id,
                "entry_agent_id": enroll.agent_id,
                "origin_channel": "registry",
                "workspace_ref": "default",
                "problem_statement": "Build the feature.",
                "constraints_json": {},
            },
            access=operator_access(),
        )
        assert created.ok is True
        assert created.run is not None
        detail = store.get_protocol_run(created.run.protocol_run_id, access=operator_access())
        run_id = created.run.protocol_run_id
        with get_connection(postgres_registry_truncated) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE agent_registry.protocol_runs SET workspace_ref = %s WHERE protocol_run_id = %s",
                    (str(tmp_path), run_id),
                )
            conn.commit()

        product_stage = next(item for item in detail.stage_executions if item.stage_key == "produce_product_domain_contract")
        product_domain_file.write_text(
            json.dumps({"product_contract": {}, "domain_contract": {}} if malformed_product_domain else product_domain_document),
            encoding="utf-8",
        )
        update_stage(
            enroll,
            product_stage,
            f"{slug}-product",
            artifacts=[
                {
                    "artifact_key": "product_domain_contract",
                    "artifact_kind": "workspace_file",
                    "path": product_domain_file.name,
                    "exists": True,
                    "size_bytes": product_domain_file.stat().st_size,
                    "content_hash": "product-domain-hash",
                    "modified_at": now,
                    "verification_state": "verified",
                }
            ],
        )
        detail = store.get_protocol_run(run_id, access=operator_access())
        product_domain_snapshot_stage_id = product_stage.protocol_stage_execution_id
        if product_domain_snapshot_stage == "wrong":
            product_domain_snapshot_stage_id = next(item for item in detail.stage_executions if item.stage_key == "review_product_domain_contract").protocol_stage_execution_id
        if product_domain_snapshot_stage != "missing":
            save_snapshot(run_id, detail, "product_domain_contract", product_domain_file, "product-domain-hash", product_domain_snapshot_stage_id)
        product_review = running_stage(detail, "review_product_domain_contract")
        update_stage(
            enroll,
            product_review,
            f"{slug}-product-review",
            artifacts=[
                {
                    "artifact_key": "product_domain_contract_review",
                    "artifact_kind": "workspace_file",
                    "path": product_domain_review_file.name,
                    "exists": True,
                    "size_bytes": product_domain_review_file.stat().st_size,
                    "content_hash": "product-domain-review-hash",
                    "modified_at": now,
                    "verification_state": "verified",
                }
            ],
            decision="accept",
        )
        detail = store.get_protocol_run(run_id, access=operator_access())
        contract_stage = running_stage(detail, "produce_system_verification_contract")
        local_contract_document = json.loads(json.dumps(contract_document))
        local_contract_document["metadata_json"] = {
            "product_domain_contract_ref": {
                "artifact_key": "product_domain_contract",
                "content_hash": "stale-product-domain-hash" if stale_product_domain_ref else "product-domain-hash",
                "produced_by_stage_execution_id": "stale-stage" if stale_product_domain_ref else product_stage.protocol_stage_execution_id,
            }
        }
        if unresolved_operator_decision:
            local_contract_document["operator_decisions_required"] = [
                {"decision_id": "choose_provider", "question": "Which provider should own the data?", "required": True}
            ]
        if unsupported_tier1_kind:
            local_contract_document["verification_contract"]["required_evidence"].append({
                "evidence_id": "db_claimed_machine_proof",
                "kind": "db_invariant",
                "trust_tier": "tier_1",
            })
        contract_file.write_text(json.dumps(local_contract_document), encoding="utf-8")
        update_stage(
            enroll,
            contract_stage,
            f"{slug}-contract",
            artifacts=[
                {
                    "artifact_key": "auto_protocol_contract",
                    "artifact_kind": "workspace_file",
                    "path": contract_file.name,
                    "exists": True,
                    "size_bytes": contract_file.stat().st_size,
                    "content_hash": "contract-hash",
                    "modified_at": now,
                    "verification_state": "verified",
                }
            ],
        )
        detail = store.get_protocol_run(run_id, access=operator_access())
        contract_snapshot_stage_id = contract_stage.protocol_stage_execution_id
        if contract_snapshot_stage == "wrong":
            contract_snapshot_stage_id = product_stage.protocol_stage_execution_id
        if contract_snapshot_stage != "missing":
            save_snapshot(run_id, detail, "auto_protocol_contract", contract_file, "contract-hash", contract_snapshot_stage_id)
        contract_review = running_stage(detail, "review_system_verification_contract")
        update_stage(
            enroll,
            contract_review,
            f"{slug}-contract-review",
            artifacts=[
                {
                    "artifact_key": "auto_protocol_contract_review",
                    "artifact_kind": "workspace_file",
                    "path": contract_review_file.name,
                    "exists": True,
                    "size_bytes": contract_review_file.stat().st_size,
                    "content_hash": "contract-review-hash",
                    "modified_at": now,
                    "verification_state": "verified",
                }
            ],
            decision="accept",
        )
        detail = store.get_protocol_run(run_id, access=operator_access())
        outcome_stage = running_stage(detail, "produce_outcome")
        producer_manifest_file.write_text(
            json.dumps({
                "evidence_items": [
                    {
                        "evidence_id": "producer_smoke",
                        "kind": "unit_test",
                        "trust_tier": "tier_2",
                        "status": "passed",
                        "observed_at": now,
                        "artifact_content_hash": "outcome-hash",
                        "source_stage_execution_id": outcome_stage.protocol_stage_execution_id,
                        "source_artifact_key": "producer_evidence_manifest",
                    }
                ]
            }),
            encoding="utf-8",
        )
        update_stage(
            enroll,
            outcome_stage,
            f"{slug}-outcome",
            artifacts=[
                {
                    "artifact_key": "produced_outcome",
                    "artifact_kind": "workspace_file",
                    "path": "output",
                    "exists": True,
                    "size_bytes": 100,
                    "content_hash": "outcome-hash",
                    "modified_at": now,
                    "verification_state": "verified",
                },
                {
                    "artifact_key": "producer_evidence_manifest",
                    "artifact_kind": "workspace_file",
                    "path": producer_manifest_file.name,
                    "exists": True,
                    "size_bytes": producer_manifest_file.stat().st_size,
                    "content_hash": "producer-hash",
                    "modified_at": now,
                    "verification_state": "verified",
                },
            ],
        )
        detail = store.get_protocol_run(run_id, access=operator_access())
        save_snapshot(run_id, detail, "producer_evidence_manifest", producer_manifest_file, "producer-hash", outcome_stage.protocol_stage_execution_id)
        final_stage = running_stage(detail, "final_evidence")
        reviewer_stage_id = final_stage.protocol_stage_execution_id if reviewer_source == "final" else outcome_stage.protocol_stage_execution_id
        runtime = store.save_protocol_artifact_runtime(
            ProtocolArtifactRuntimeInstanceRecord(
                runtime_instance_id=f"{run_id}-runtime",
                protocol_run_id=run_id,
                artifact_key="produced_outcome",
                agent_id=created.run.entry_agent_id,
                status="running",
                manifest=ProtocolArtifactRuntimeManifestRecord.model_validate(
                    json.loads((artifact_root / "octopus-runtime.json").read_text(encoding="utf-8"))
                ),
                artifact_path=str(artifact_root),
                runtime_url=f"/runtime/protocol-runs/{run_id}/artifacts/produced_outcome/app/",
            ),
            access=operator_access(),
        )
        for event_kind, metadata in (
            ("started", {}),
            ("health_checked", {"ok": True, "status_code": 200}),
        ):
            store.append_protocol_artifact_runtime_event(
                ProtocolArtifactRuntimeEventRecord(
                    runtime_instance_id=runtime.runtime_instance_id,
                    protocol_run_id=run_id,
                    artifact_key="produced_outcome",
                    event_kind=event_kind,
                    actor_ref="operator-session",
                    summary=event_kind,
                    metadata_json=RegistryJsonRecord.model_validate(metadata),
                ),
                access=operator_access(),
            )
        if include_api_fetch:
            store.append_protocol_artifact_runtime_event(
                ProtocolArtifactRuntimeEventRecord(
                    runtime_instance_id=runtime.runtime_instance_id,
                    protocol_run_id=run_id,
                    artifact_key="produced_outcome",
                    event_kind="fetch",
                    actor_ref="operator-session",
                    summary="GET /api/quote -> 200",
                    metadata_json=RegistryJsonRecord.model_validate({
                        "method": "GET",
                        "path": "/api/quote",
                        "status_code": 200,
                        "is_api": True,
                    }),
                ),
                access=operator_access(),
            )
        requested_event = store.append_protocol_artifact_runtime_event(
            ProtocolArtifactRuntimeEventRecord(
                runtime_instance_id=runtime.runtime_instance_id,
                protocol_run_id=run_id,
                artifact_key="produced_outcome",
                event_kind="journey_requested",
                actor_ref="operator-session",
                summary="Journey requested.",
                metadata_json=RegistryJsonRecord.model_validate({
                    "journey_key": "primary_happy_path",
                    "journey_run_id": f"{run_id}-journey",
                    "source": "operator_journey_run",
                    "runtime_instance_id": runtime.runtime_instance_id,
                    "artifact_content_hash": "outcome-hash",
                }),
            ),
            access=operator_access(),
        )
        store.append_protocol_artifact_runtime_event(
            ProtocolArtifactRuntimeEventRecord(
                runtime_instance_id=runtime.runtime_instance_id,
                protocol_run_id=run_id,
                artifact_key="produced_outcome",
                event_kind="journey_completed",
                actor_ref=f"runtime-capability:cap-1:{final_stage.protocol_stage_execution_id}:acceptor",
                summary="Journey completed.",
                metadata_json=RegistryJsonRecord.model_validate({
                    "journey_key": "primary_happy_path",
                    "journey_run_id": f"{run_id}-journey",
                    "ok": True,
                    "status": "passed",
                    "source": "registry_journey_runner",
                    "requested_event_id": requested_event.runtime_event_id,
                    "runtime_instance_id": runtime.runtime_instance_id,
                    "artifact_content_hash": "outcome-hash",
                    "actor_stage_execution_id": final_stage.protocol_stage_execution_id,
                }),
            ),
            access=operator_access(),
        )
        reviewer_items = []
        for evidence_id, kind, tier in (
            ("runtime_started", "runtime_start", "tier_1"),
            ("runtime_healthy", "runtime_health", "tier_1"),
            ("quote_api_probe", "api_probe", "tier_1"),
            ("primary_happy_path", "browser_journey", "tier_1"),
            ("no_failed_mutation", "db_invariant", "tier_2"),
            ("unsafe_trade_rejected", "negative_case", "tier_2"),
            ("domain_sources", "domain_source", "tier_3"),
        ):
            if tier3_substitution and evidence_id == "no_failed_mutation":
                tier = "tier_3"
            item = {
                "evidence_id": evidence_id,
                "kind": kind,
                "trust_tier": tier,
                "status": "passed",
                "observed_at": now,
                "artifact_content_hash": "outcome-hash",
                "runtime_instance_id": runtime.runtime_instance_id,
                "source_stage_execution_id": reviewer_stage_id,
                "source_artifact_key": "reviewer_evidence_manifest",
                "observed_result": "passed",
                "corroboration_refs": [runtime.runtime_instance_id],
            }
            if evidence_id == "quote_api_probe":
                item["command_or_probe"] = {"method": "GET", "path": "/api/quote", "status_code": 200}
            if evidence_id == "primary_happy_path":
                item["journey_key"] = "primary_happy_path"
            reviewer_items.append(item)
        reviewer_manifest_file.write_text(json.dumps({"evidence_items": reviewer_items}), encoding="utf-8")
        detail = store.get_protocol_run(run_id, access=operator_access())
        save_snapshot(run_id, detail, "reviewer_evidence_manifest", reviewer_manifest_file, "reviewer-hash", final_stage.protocol_stage_execution_id)
        update_stage(
            enroll,
            final_stage,
            f"{slug}-final",
            artifacts=[
                {
                    "artifact_key": "release_evidence",
                    "artifact_kind": "workspace_file",
                    "path": release_file.name,
                    "exists": True,
                    "size_bytes": release_file.stat().st_size,
                    "content_hash": "release-hash",
                    "modified_at": now,
                    "verification_state": "verified",
                },
                {
                    "artifact_key": "reviewer_evidence_manifest",
                    "artifact_kind": "workspace_file",
                    "path": reviewer_manifest_file.name,
                    "exists": True,
                    "size_bytes": reviewer_manifest_file.stat().st_size,
                    "content_hash": "reviewer-hash",
                    "modified_at": now,
                    "verification_state": "verified",
                },
            ],
            decision="accept",
        )
        return store.get_protocol_run(run_id, access=operator_access())

    missing_contract = run_to_final("v2-contract-missing", contract_snapshot_stage="missing")
    assert missing_contract.run.status == "blocked"
    assert "latest auto_protocol_contract artifact snapshot" in missing_contract.run.blocked_detail

    wrong_contract = run_to_final("v2-contract-wrong-stage", contract_snapshot_stage="wrong")
    assert wrong_contract.run.status == "blocked"
    assert "auto_protocol_contract snapshot from expected stage" in wrong_contract.run.blocked_detail

    missing_product_domain = run_to_final("v2-product-domain-missing", product_domain_snapshot_stage="missing")
    assert missing_product_domain.run.status == "blocked"
    assert "latest product_domain_contract artifact snapshot" in missing_product_domain.run.blocked_detail

    wrong_product_domain = run_to_final("v2-product-domain-wrong-stage", product_domain_snapshot_stage="wrong")
    assert wrong_product_domain.run.status == "blocked"
    assert "product_domain_contract snapshot from expected stage" in wrong_product_domain.run.blocked_detail

    malformed_product_domain = run_to_final("v2-product-domain-malformed", malformed_product_domain=True)
    assert malformed_product_domain.run.status == "blocked"
    assert "product_domain_contract.product_contract" in malformed_product_domain.run.blocked_detail

    stale_product_domain_ref = run_to_final("v2-contract-stale-product-domain-ref", stale_product_domain_ref=True)
    assert stale_product_domain_ref.run.status == "blocked"
    assert "auto_protocol_contract current product/domain contract reference" in stale_product_domain_ref.run.blocked_detail

    unresolved_decision = run_to_final("v2-contract-unresolved-decision", unresolved_operator_decision=True)
    assert unresolved_decision.run.status == "blocked"
    assert "operator decision unresolved: choose_provider" in unresolved_decision.run.blocked_detail

    producer_only = run_to_final("v2-contract-producer-evidence", reviewer_source="producer")
    assert producer_only.run.status == "blocked"
    assert "reviewer-stage provenance on evidence: runtime_started" in producer_only.run.blocked_detail

    unsupported_tier1 = run_to_final("v2-contract-unsupported-tier1-kind", unsupported_tier1_kind=True)
    assert unsupported_tier1.run.status == "blocked"
    assert "machine corroboration unsupported for Tier 1 evidence: db_claimed_machine_proof" in unsupported_tier1.run.blocked_detail

    tier3_substitution = run_to_final("v2-contract-tier3-substitution", tier3_substitution=True)
    assert tier3_substitution.run.status == "blocked"
    assert "trust tier on evidence: no_failed_mutation" in tier3_substitution.run.blocked_detail

    missing_fetch = run_to_final("v2-contract-missing-fetch", include_api_fetch=False)
    assert missing_fetch.run.status == "blocked"
    assert "Registry fetch event for API probe: quote_api_probe" in missing_fetch.run.blocked_detail
    metadata = _latest_transition_metadata(missing_fetch, "blocked")
    assert any(
        item.get("reason_code") == "api_probe_fetch_event_missing"
        for item in metadata.get("evidence_status", [])
    )

    accepted = run_to_final("v2-contract-accepted")
    assert accepted.run.status == "completed", accepted.run.blocked_detail


def test_registry_store_auto_completes_blocked_final_accept_when_runtime_events_satisfy_gate(postgres_registry_truncated: str, tmp_path: Path) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    artifact_root = tmp_path / "output"
    artifact_root.mkdir()
    release_evidence = tmp_path / "release.md"
    release_evidence.write_text(
        "Clicked Run scenario through the Registry route and the decision result was displayed in the app.\n"
        "Automated tests: 5 run, 0 failures, 0 errors, and 0 skipped.\n"
        "Outcome-readiness matrix:\n"
        "PASS journey 1: Registry-routed scenario run displayed the decision result and audit id.\n"
        "A post-stop health check failed as expected, proving the temporary runtime was stopped.\n"
        "Branding check: no Octopus branding appears in customer-facing UI/API copy; "
        "Octopus is only internal runtime evidence.\n",
        encoding="utf-8",
    )
    (artifact_root / "octopus-runtime.json").write_text(
        json.dumps(
            {
                "runtime_kind": "static",
                "ui_path": "/",
                "health_path": "/health",
                "metadata": {"minimum_core_journeys": 1},
            }
        ),
        encoding="utf-8",
    )
    document = {
        "metadata": {
            "slug": "runtime-proof-auto-complete",
            "display_name": "Runtime Proof Auto Complete",
            "auto_protocol": {"primary_artifact_key": "produced_outcome"},
        },
        "participants": [
            {"participant_key": "worker", "display_name": "Worker"},
            {"participant_key": "acceptor", "display_name": "Acceptor"},
        ],
        "artifacts": [
            {"artifact_key": "produced_outcome", "kind": "workspace_file", "path": "output"},
            {"artifact_key": "release_evidence", "kind": "workspace_file", "path": "release.md"},
        ],
        "stages": [
            {
                "stage_key": "produce",
                "participant_key": "worker",
                "selector": {"kind": "skill", "value": "implementation"},
                "stage_kind": "work",
                "write_capable": True,
                "outputs": ["produced_outcome"],
                "transitions": {"completed": "final"},
                "instructions": "Produce the runtime artifact.",
            },
            {
                "stage_key": "final",
                "participant_key": "acceptor",
                "selector": {"kind": "skill", "value": "review"},
                "stage_kind": "acceptance",
                "inputs": ["produced_outcome"],
                "outputs": ["release_evidence"],
                "transitions": {"accept": "__complete__", "revise": "produce", "fail": "__failed__"},
                "instructions": "Accept only after runtime evidence exists.",
            },
        ],
        "policies": {"single_active_writer": True, "max_review_rounds": 2},
    }
    enroll, _published, created, detail = running_protocol_run(store, document=document)
    with get_connection(postgres_registry_truncated) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE agent_registry.protocol_runs SET workspace_ref = %s WHERE protocol_run_id = %s",
                (str(tmp_path), created.run.protocol_run_id),
            )
        conn.commit()

    produce = detail.stage_executions[0]
    store.update_routed_task_result(
        enroll.agent_token,
        produce.routed_task_id,
        {
            "status": "completed",
            "transition_id": "runtime-produce",
            "summary": "Produced runtime package.",
            "full_text": "Produced output.\nPROTOCOL_SUMMARY: Produced runtime package.",
            "artifacts": [
                {
                    "artifact_key": "produced_outcome",
                    "artifact_kind": "workspace_file",
                    "path": "output",
                    "exists": True,
                    "size_bytes": 100,
                    "content_hash": "runtime123",
                    "modified_at": "2026-04-16T00:00:00+00:00",
                    "verification_state": "verified",
                }
            ],
        },
    )
    final_detail = store.get_protocol_run(created.run.protocol_run_id, access=operator_access())
    final_stage = next(item for item in final_detail.stage_executions if item.stage_key == "final")
    store.update_routed_task_result(
        enroll.agent_token,
        final_stage.routed_task_id,
        {
            "status": "completed",
            "transition_id": "runtime-final",
            "summary": "Accepted after review.",
            "full_text": (
                "Accepted after review. Detailed runtime and outcome-readiness evidence is in release.md.\n"
                "PROTOCOL_DECISION: accept\n"
                "PROTOCOL_SUMMARY: Accepted."
            ),
            "working_dir": str(tmp_path),
            "artifacts": [
                {
                    "artifact_key": "release_evidence",
                    "artifact_kind": "workspace_file",
                    "path": "release.md",
                    "exists": True,
                    "size_bytes": 10,
                    "content_hash": "release123",
                    "modified_at": "2026-04-16T00:00:00+00:00",
                    "verification_state": "verified",
                }
            ],
        },
    )

    blocked = store.get_protocol_run(created.run.protocol_run_id, access=operator_access())
    assert blocked.run.status == "blocked"
    assert blocked.run.blocked_code == "runtime_evidence_required"

    runtime = store.save_protocol_artifact_runtime(
        ProtocolArtifactRuntimeInstanceRecord(
            runtime_instance_id="runtime-evidence-auto-complete",
            protocol_run_id=created.run.protocol_run_id,
            artifact_key="produced_outcome",
            agent_id=created.run.entry_agent_id,
            status="running",
            manifest=ProtocolArtifactRuntimeManifestRecord(runtime_kind="static", ui_path="/", health_path="/health"),
            artifact_path=str(artifact_root),
            runtime_url=f"/runtime/protocol-runs/{created.run.protocol_run_id}/artifacts/produced_outcome/app/",
        ),
        access=operator_access(),
    )
    for event_kind, metadata in (
        ("started", {}),
        ("health_checked", {"ok": True, "status_code": 200}),
        ("client_interaction", {"event_type": "click", "tag": "button", "text": "Run scenario"}),
    ):
        store.append_protocol_artifact_runtime_event(
            ProtocolArtifactRuntimeEventRecord(
                runtime_instance_id=runtime.runtime_instance_id,
                protocol_run_id=created.run.protocol_run_id,
                artifact_key="produced_outcome",
                event_kind=event_kind,
                actor_ref="operator-session",
                summary=event_kind,
                metadata_json=RegistryJsonRecord.model_validate(metadata),
            ),
            access=operator_access(),
        )
    still_blocked = store.get_protocol_run(created.run.protocol_run_id, access=operator_access())
    assert still_blocked.run.status == "blocked"

    store.append_protocol_artifact_runtime_event(
        ProtocolArtifactRuntimeEventRecord(
            runtime_instance_id=runtime.runtime_instance_id,
            protocol_run_id=created.run.protocol_run_id,
            artifact_key="produced_outcome",
            event_kind="fetch",
            actor_ref="operator-session",
            summary="POST /decisions -> 200",
            metadata_json=RegistryJsonRecord.model_validate(
                {"status_code": 200, "method": "POST", "path": "/decisions", "is_api": True}
            ),
        ),
        access=operator_access(),
    )

    completed = store.get_protocol_run(created.run.protocol_run_id, access=operator_access())
    final_stage = next(item for item in completed.stage_executions if item.stage_key == "final")
    assert completed.run.status == "completed"
    assert completed.run.blocked_code == ""
    assert final_stage.status == "completed"
    assert final_stage.failure_code == ""


def test_runtime_acceptance_matrix_allows_clean_skipped_test_counts() -> None:
    evidence = (
        "Automated test evidence: 5 tests ran with 0 failures, 0 errors, and 0 skipped.\n"
        "Outcome-readiness matrix:\n"
        "PASS journey 1: health and UI load returned the visible dashboard.\n"
        "PASS journey 2: API docs listed service-backed workflows.\n"
        "PASS journey 3: scenarios returned six domains.\n"
        "PASS journey 4: policy DSL validation returned valid true.\n"
        "PASS journey 5: model curation approved and activated a version.\n"
        "PASS journey 6: replay provenance produced an audit id.\n"
    )

    assert ProtocolPostgresAdapter._runtime_acceptance_text_has_outcome_readiness_matrix(
        evidence,
        minimum_core_journeys=6,
    )


def test_runtime_visible_result_evidence_allows_unrelated_tool_failure_note() -> None:
    evidence = (
        "Clicked Run scenario through the Registry route and the decision result was displayed in the app.\n"
        "The scenario returned a review outcome, medium band, and visible audit id.\n"
        "Note: git status could not run because /workspace/workspace is not a git repository.\n"
    )

    assert ProtocolPostgresAdapter._runtime_acceptance_text_has_visible_result_evidence(evidence)


def test_registry_store_revises_final_accept_when_runtime_start_command_is_not_run_ready(postgres_registry_truncated: str, tmp_path: Path) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    artifact_root = tmp_path / "output"
    artifact_root.mkdir()
    bad_manifest = {
        "runtime_kind": "java",
        "start_command": "mvn spring-boot:run",
        "ui_path": "/",
        "health_path": "/health",
        "api_base_path": "/api",
        "endpoints": [
            {"label": "Operator UI", "path": "/", "endpoint_kind": "ui", "method": "GET"},
            {"label": "Health", "path": "/health", "endpoint_kind": "health", "method": "GET"},
            {"label": "API docs", "path": "/api/docs", "endpoint_kind": "docs", "method": "GET"},
        ],
        "smoke_test": ["GET /health", "GET /", "GET /api/docs"],
    }
    (artifact_root / "octopus-runtime.json").write_text(json.dumps(bad_manifest), encoding="utf-8")
    document = {
        "metadata": {
            "slug": "runtime-run-ready-proof",
            "display_name": "Runtime Run Ready Proof",
            "auto_protocol": {
                "primary_artifact": {
                    "artifact_key": "produced_outcome",
                    "produced_by_stage_key": "produce",
                    "open_behavior": "runtime",
                }
            },
        },
        "participants": [
            {"participant_key": "worker", "display_name": "Worker"},
            {"participant_key": "acceptor", "display_name": "Acceptor"},
        ],
        "artifacts": [
            {"artifact_key": "produced_outcome", "kind": "workspace_file", "path": "output"},
            {"artifact_key": "release_evidence", "kind": "workspace_file", "path": "release.md"},
        ],
        "stages": [
            {
                "stage_key": "produce",
                "participant_key": "worker",
                "selector": {"kind": "skill", "value": "implementation"},
                "stage_kind": "work",
                "write_capable": True,
                "outputs": ["produced_outcome"],
                "transitions": {"completed": "final"},
                "instructions": "Produce the runtime artifact.",
            },
            {
                "stage_key": "final",
                "participant_key": "acceptor",
                "selector": {"kind": "skill", "value": "review"},
                "stage_kind": "acceptance",
                "inputs": ["produced_outcome"],
                "outputs": ["release_evidence"],
                "transitions": {"accept": "__complete__", "revise": "produce", "fail": "__failed__"},
                "instructions": "Accept only after runtime evidence exists and the package is run-ready.",
            },
        ],
        "policies": {"single_active_writer": True, "max_review_rounds": 2},
    }
    enroll, _published, created, detail = running_protocol_run(store, document=document)
    with get_connection(postgres_registry_truncated) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE agent_registry.protocol_runs SET workspace_ref = %s WHERE protocol_run_id = %s",
                (str(tmp_path), created.run.protocol_run_id),
            )
        conn.commit()

    produce = detail.stage_executions[0]
    store.update_routed_task_result(
        enroll.agent_token,
        produce.routed_task_id,
        {
            "status": "completed",
            "transition_id": "runtime-run-ready-produce",
            "summary": "Produced runtime package.",
            "full_text": "Produced output.\nPROTOCOL_SUMMARY: Produced runtime package.",
            "artifacts": [
                {
                    "artifact_key": "produced_outcome",
                    "artifact_kind": "workspace_file",
                    "path": "output",
                    "exists": True,
                    "size_bytes": 100,
                    "content_hash": "runtime-run-ready",
                    "modified_at": "2026-04-16T00:00:00+00:00",
                    "verification_state": "verified",
                }
            ],
        },
    )
    final_detail = store.get_protocol_run(created.run.protocol_run_id, access=operator_access())
    runtime = store.save_protocol_artifact_runtime(
        ProtocolArtifactRuntimeInstanceRecord(
            runtime_instance_id="runtime-run-ready-test",
            protocol_run_id=created.run.protocol_run_id,
            artifact_key="produced_outcome",
            agent_id=created.run.entry_agent_id,
            status="running",
            manifest=ProtocolArtifactRuntimeManifestRecord.model_validate(bad_manifest),
            artifact_path=str(artifact_root),
            runtime_url=f"/runtime/protocol-runs/{created.run.protocol_run_id}/artifacts/produced_outcome/app/",
        ),
        access=operator_access(),
    )
    for event_kind, metadata in (
        ("started", {}),
        ("health_checked", {"ok": True, "status_code": 200}),
        ("fetch", {"status_code": 200}),
    ):
        store.append_protocol_artifact_runtime_event(
            ProtocolArtifactRuntimeEventRecord(
                runtime_instance_id=runtime.runtime_instance_id,
                protocol_run_id=created.run.protocol_run_id,
                artifact_key="produced_outcome",
                event_kind=event_kind,
                actor_ref="operator-session",
                summary=event_kind,
                metadata_json=RegistryJsonRecord.model_validate(metadata),
            ),
            access=operator_access(),
        )
    final_stage = next(item for item in final_detail.stage_executions if item.stage_key == "final")
    store.update_routed_task_result(
        enroll.agent_token,
        final_stage.routed_task_id,
        {
            "status": "completed",
            "transition_id": "runtime-run-ready-final",
            "summary": "Accepted.",
            "full_text": "Looks good.\nPROTOCOL_DECISION: accept\nPROTOCOL_SUMMARY: Accepted.",
            "artifacts": [
                {
                    "artifact_key": "release_evidence",
                    "artifact_kind": "workspace_file",
                    "path": "release.md",
                    "exists": True,
                    "size_bytes": 10,
                    "content_hash": "release-run-ready",
                    "modified_at": "2026-04-16T00:00:00+00:00",
                    "verification_state": "verified",
                }
            ],
        },
    )

    revised = store.get_protocol_run(created.run.protocol_run_id, access=operator_access())
    assert revised.run.status == "running"
    assert revised.run.blocked_code == ""
    assert revised.run.current_stage_key == "produce"
    assert revised.run.current_review_rounds == 1
    assert revised.run.current_review_edge_key == "final:produce"
    next_produce = next(
        item
        for item in revised.stage_executions
        if item.stage_key == "produce" and item.status == "running"
    )
    assert next_produce.input_snapshot_json["decision"] == "revise"
    assert next_produce.input_snapshot_json["runtime_gate_code"] == "runtime_manifest_not_run_ready"
    assert next_produce.input_snapshot_json["runtime_manifest_start_command"] == "mvn spring-boot:run"
    assert "Maven commands build or resolve dependencies" in next_produce.input_snapshot_json["runtime_manifest_blockers"][0]
    revise_transition = next(
        item
        for item in revised.transitions
        if item.transition_kind == "advance" and item.error_code == "RUNTIME_MANIFEST_NOT_RUN_READY"
    )
    assert revise_transition.transition_kind == "advance"
    assert revise_transition.decision == "revise"
    assert revise_transition.error_code == "RUNTIME_MANIFEST_NOT_RUN_READY"
    assert revise_transition.metadata_json.as_dict()["runtime_gate_auto_revise"] is True


def test_registry_store_create_blank_protocol_draft_creates_persisted_invalid_draft(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)

    created = store.create_protocol_draft(
        ProtocolDraftCreateRecord.model_validate({"source_kind": "blank"}),
        access=operator_access(),
    )

    assert created.ok is True
    assert created.protocol is not None
    assert created.protocol.lifecycle_state == "draft"
    assert created.protocol.slug
    assert created.draft_definition_json["metadata"]["slug"] == ""
    assert created.draft_definition_json["metadata"]["display_name"] == ""
    assert created.draft_definition_json["stages"] == []
    assert created.validation is not None
    assert created.validation.mode == "draft"
    assert created.validation.ok is False
    assert "Add at least one stage before review or publish." in created.validation.errors


def test_registry_store_create_template_protocol_draft_requires_user_published_template(postgres_registry_truncated: str) -> None:
    from app.db.postgres_init import run_init

    store = RegistryPostgresStore(postgres_registry_truncated)
    with get_connection(postgres_registry_truncated) as conn:
        assert run_init(conn) == []
        conn.commit()

    missing = store.create_protocol_draft(
        ProtocolDraftCreateRecord.model_validate({"source_kind": "template", "template_slug": "software-engineering"}),
        access=operator_access(),
    )

    assert missing.ok is False
    assert missing.status == "not_found"

    published = published_protocol(store, slug="template-source-for-draft")
    assert published.protocol is not None
    template_result = store.publish_protocol_template(published.protocol.protocol_id, access=operator_access())
    assert template_result.ok is True
    assert template_result.protocol is not None

    created = store.create_protocol_draft(
        ProtocolDraftCreateRecord.model_validate({"source_kind": "template", "template_slug": template_result.protocol.slug}),
        access=operator_access(),
    )

    assert created.ok is True
    assert created.protocol is not None
    assert created.protocol.slug != template_result.protocol.slug
    assert created.draft_definition_json["metadata"]["display_name"].endswith("Draft")
    assert created.draft_definition_json["stages"]
    assert created.validation is not None
    assert created.validation.ok is True


def test_registry_store_create_protocol_draft_clones_existing_protocol(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    published = published_protocol(store, slug="clone-source")

    cloned = store.create_protocol_draft(
        ProtocolDraftCreateRecord.model_validate(
            {"source_kind": "protocol", "source_protocol_id": published.protocol.protocol_id}
        ),
        access=operator_access(),
    )

    assert cloned.ok is True
    assert cloned.protocol is not None
    assert cloned.protocol.protocol_id != published.protocol.protocol_id
    assert cloned.protocol.slug != published.protocol.slug
    assert cloned.draft_definition_json["metadata"]["display_name"].endswith("Draft")
    assert cloned.draft_definition_json["stages"]
    assert cloned.validation is not None
    assert cloned.validation.ok is True


def test_registry_store_cleanup_workspace_data_removes_authored_work_records(postgres_registry_truncated: str) -> None:
    from app.db.postgres_init import run_init

    store = RegistryPostgresStore(postgres_registry_truncated)
    with get_connection(postgres_registry_truncated) as conn:
        assert run_init(conn) == []
        conn.commit()

    created = store.create_protocol_draft(ProtocolDraftCreateRecord.model_validate({"source_kind": "blank"}), access=operator_access())
    assert created.protocol is not None
    assert store.list_protocols(access=operator_access())

    result = store.cleanup_workspace_data()

    assert result["cleaned"] is True
    assert store.list_protocols(access=operator_access()) == []
    assert store.list_protocol_templates(access=operator_access()) == []


def test_registry_store_delete_protocol_discards_unpublished_draft(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    created = store.create_protocol_draft(
        ProtocolDraftCreateRecord.model_validate({"source_kind": "blank"}),
        access=operator_access(),
    )

    deleted = store.delete_protocol(created.protocol.protocol_id, access=operator_access())

    assert deleted.ok is True
    assert deleted.status == "deleted"
    listed = store.list_protocols(access=operator_access(), limit=50)
    assert all(item.protocol_id != created.protocol.protocol_id for item in listed)


def test_registry_store_create_run_returns_not_visible_for_foreign_org(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    published = published_protocol(store)
    enroll = store.enroll(agent_card(bot_key="m1"))

    result = store.create_protocol_run(
        {
            "protocol_id": published.protocol.protocol_id,
            "entry_agent_id": enroll.agent_id,
            "origin_channel": "registry",
            "workspace_ref": "default",
            "problem_statement": "Build the feature.",
            "constraints_json": {},
        },
        access=ProtocolAccessContextRecord(
            actor_ref="foreign-operator",
            org_id="foreign-org",
            roles=["author", "publisher", "operator", "auditor"],
        ),
    )

    assert result.ok is False
    assert result.status == "not_visible"


def test_registry_store_create_run_requires_entry_agent_id(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    published = published_protocol(store)

    result = store.create_protocol_run(
        {
            "protocol_id": published.protocol.protocol_id,
            "entry_agent_id": "",
            "origin_channel": "registry",
            "workspace_ref": "default",
            "problem_statement": "Build the feature.",
            "constraints_json": {},
        },
        access=operator_access(),
    )

    assert result.ok is False
    assert result.status == "invalid"
    assert "entry_agent_id is required" in result.message


def test_registry_store_create_run_rejects_unknown_entry_agent_id(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    published = published_protocol(store)

    result = store.create_protocol_run(
        {
            "protocol_id": published.protocol.protocol_id,
            "entry_agent_id": "agent-missing",
            "origin_channel": "registry",
            "workspace_ref": "default",
            "problem_statement": "Build the feature.",
            "constraints_json": {},
        },
        access=operator_access(),
    )

    assert result.ok is False
    assert result.status == "invalid"
    assert "entry_agent_id does not reference a known managed bot" in result.message


def test_registry_store_get_run_raises_permission_error_for_foreign_org(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    _enroll, _published, created, _detail = running_protocol_run(store)

    with pytest.raises(PermissionError):
        store.get_protocol_run(
            created.run.protocol_run_id,
            access=ProtocolAccessContextRecord(
                actor_ref="foreign-operator",
                org_id="foreign-org",
                roles=["operator"],
            ),
        )


def test_registry_store_archive_protocol_marks_definition_archived(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    published = published_protocol(store)

    archived = store.archive_protocol(published.protocol.protocol_id, access=operator_access())

    assert archived.ok is True
    assert archived.protocol is not None
    assert archived.protocol.lifecycle_state == "archived"


def test_registry_store_protocol_export_requires_operator_auditor_or_agent_role(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    _enroll, _published, created, _detail = running_protocol_run(store)

    with pytest.raises(PermissionError, match="operator, auditor, or agent access"):
        store.export_protocol_run(
            created.run.protocol_run_id,
            access=ProtocolAccessContextRecord(
                actor_ref="author-only",
                org_id="local",
                roles=["author"],
            ),
        )

    exported = store.export_protocol_run(
        created.run.protocol_run_id,
        access=ProtocolAccessContextRecord(
            actor_ref="auditor-session",
            org_id="local",
            roles=["auditor"],
        ),
    )
    assert exported.run.protocol_run_id == created.run.protocol_run_id
    assert exported.definition_document.slug == "mini-protocol"
    assert [artifact.artifact_key for artifact in exported.artifacts] == ["plan"]
    assert exported.artifacts[0].verification_state == "declared"

    agent_exported = store.export_protocol_run(
        created.run.protocol_run_id,
        access=ProtocolAccessContextRecord(
            actor_ref="agent:planner",
            org_id="local",
            roles=["agent"],
        ),
    )
    assert agent_exported.run.protocol_run_id == created.run.protocol_run_id


def test_registry_store_protocol_text_routes_round_trip_json_yaml_and_diff(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    published = published_protocol(store)
    protocol_id = published.protocol.protocol_id

    parsed = store.parse_protocol_document_text(
        access=operator_access(),
        definition_text=protocol_document_to_text(protocol_document(), format="yaml"),
        format="yaml",
    )
    assert parsed.format == "yaml"
    assert parsed.validation is not None
    assert parsed.validation.ok is True
    assert parsed.document is not None
    assert parsed.text.strip().startswith("schema_version:")

    exported = store.export_protocol_draft(
        protocol_id,
        access=operator_access(),
        format="yaml",
    )
    assert exported.format == "yaml"
    assert "display_name: Mini Protocol" in exported.text

    saved = store.save_protocol_draft(
        access=operator_access(),
        protocol_id=protocol_id,
        slug="mini-protocol",
        display_name="Mini Protocol",
        description="Updated draft description",
        definition_json=RegistryJsonRecord.model_validate(
            {
                **protocol_document(),
                "metadata": {
                    **protocol_document()["metadata"],
                    "description": "Updated draft description",
                },
            }
        ),
    )
    assert saved.ok is True

    diff = store.diff_protocol_draft(
        protocol_id,
        access=operator_access(),
        format="json",
    )
    assert diff.protocol_id == protocol_id
    assert diff.protocol_definition_version_id == published.version.protocol_definition_version_id
    assert "--- draft" in diff.diff
    assert "+++ published" in diff.diff
    assert "Updated draft description" in diff.diff


def test_registry_store_parse_draft_mode_accepts_incomplete_protocols(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)

    parsed = store.parse_protocol_document_text(
        access=operator_access(),
        definition_text=json.dumps(
            {
                "schema_version": 1,
                "metadata": {"slug": "draft-protocol", "display_name": "Draft Protocol"},
                "participants": [],
                "artifacts": [],
                "stages": [],
                "policies": {"single_active_writer": True, "max_review_rounds": 5},
            }
        ),
        format="json",
        validation_mode="draft",
    )

    assert parsed.format == "json"
    assert parsed.document is not None
    assert parsed.validation is not None
    assert parsed.validation.mode == "draft"
    assert parsed.validation.ok is False
    assert parsed.validation.next_required_actions == ["participants.add_first", "stages.add_first"]
    assert "Add at least one stage before review or publish." in parsed.validation.errors


def test_registry_store_validate_protocol_returns_friendly_strict_issues_for_incomplete_drafts(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    created = store.create_protocol_draft(
        ProtocolDraftCreateRecord.model_validate({"source_kind": "blank"}),
        access=operator_access(),
    )

    validated = store.validate_protocol(created.protocol.protocol_id, access=operator_access())

    assert validated.ok is True
    assert validated.validation is not None
    assert validated.validation.mode == "strict"
    assert validated.validation.ok is False
    assert "Add at least one stage before review or publish." in validated.validation.errors


def test_registry_store_list_protocol_runs_filters_by_entry_agent_and_origin_channel(
    postgres_registry_truncated: str,
) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    m1 = store.enroll(agent_card(bot_key="m1"))
    m2 = store.enroll(agent_card(bot_key="m2"))
    published = published_protocol(store)

    registry_run = store.create_protocol_run(
        {
            "protocol_id": published.protocol.protocol_id,
            "entry_agent_id": m1.agent_id,
            "origin_channel": "registry",
            "workspace_ref": "workspace-registry",
            "problem_statement": "Registry initiated run.",
            "constraints_json": {},
        },
        access=operator_access(),
    )
    telegram_run = store.create_protocol_run(
        {
            "protocol_id": published.protocol.protocol_id,
            "entry_agent_id": m2.agent_id,
            "origin_channel": "telegram",
            "workspace_ref": "workspace-telegram",
            "problem_statement": "Telegram initiated run.",
            "constraints_json": {},
        },
        access=operator_access(),
    )

    assert registry_run.ok is True
    assert telegram_run.ok is True
    paged = store.list_protocol_runs(access=operator_access(), limit=1)
    assert len(paged) == 2

    filtered = store.list_protocol_runs(
        access=operator_access(),
        entry_agent_id=m2.agent_id,
        origin_channel="telegram",
        limit=10,
    )
    assert len(filtered) == 1
    assert filtered[0].protocol_run_id == telegram_run.run.protocol_run_id
    assert filtered[0].entry_agent_id == m2.agent_id
    assert filtered[0].origin_channel == "telegram"


# ---------------------------------------------------------------------------
# Participation hardening (protocol_kit_plan Step 2)
#
# These guard the invariant that protocol stages ride the task framework and
# that the substrate stays coherent end-to-end: dispatch writes to recipient,
# completion transitions the execution, and the recipient conversation carries
# enough context for UI navigation back to the run.
# ---------------------------------------------------------------------------


def _recipient_conversation_id_for_task(store: RegistryPostgresStore, routed_task_id: str, target_agent_id: str) -> str:
    conversations = store.list_conversations(for_agent_id=target_agent_id, limit=50)
    expected_ref = f"routed-task:{routed_task_id}"
    recipient = next(
        (conv for conv in conversations if conv.external_conversation_ref == expected_ref),
        None,
    )
    assert recipient is not None, f"No recipient task-thread conversation for {routed_task_id}"
    return str(recipient.conversation_id)


def test_protocol_stage_dispatch_writes_events_to_recipient_conversation(
    postgres_registry_truncated: str,
) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    enroll, _published, _created, detail = running_protocol_run(store)
    first_stage = detail.stage_executions[0]
    assert first_stage.routed_task_id.startswith("protocol-stage:")

    recipient_conversation_id = _recipient_conversation_id_for_task(
        store, first_stage.routed_task_id, enroll.agent_id
    )

    recipient_events = store.list_events(recipient_conversation_id).events
    stage_events = [event for event in recipient_events if str(event.kind or "") == "task.status"]
    assert stage_events, "Recipient conversation must receive at least one task.status event"

    queued_event = stage_events[0]
    metadata = queued_event.metadata.as_dict() if queued_event.metadata is not None else {}
    assert metadata.get("routed_task_id") == first_stage.routed_task_id
    assert str(metadata.get("status") or "") == "queued"


def test_protocol_stage_runtime_capability_exchange_is_scoped_and_revoked(
    postgres_registry_truncated: str,
) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    enroll, _published, _created, detail = running_protocol_run(store)
    first_stage = detail.stage_executions[0]

    with get_connection(postgres_registry_truncated) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT request_json
                FROM agent_registry.routed_tasks
                WHERE routed_task_id = %s
                """,
                (first_stage.routed_task_id,),
            )
            row = cur.fetchone()
    request_json = dict(row[0])
    context = request_json["context"]
    capability = context["runtime_capability"]
    capability_ref = capability["capability_ref"]

    assert capability_ref.startswith("oct-cap-")
    assert "OCTOPUS_CAPABILITY_TOKEN" in request_json["instructions"]
    assert "oct-rt-" not in json.dumps(request_json)

    exchanged = store.exchange_runtime_capability_token(
        capability_ref=capability_ref,
        target_agent_id=enroll.agent_id,
    )
    assert exchanged.ok
    assert exchanged.bearer_token.startswith("oct-rt-")
    assert store.validate_runtime_capability_token(
        bearer_token=exchanged.bearer_token,
        protocol_run_id=detail.run.protocol_run_id,
        artifact_key="plan",
        action="runtime:read",
    )
    assert store.validate_runtime_capability_token(
        bearer_token=exchanged.bearer_token,
        protocol_run_id="wrong-run",
        artifact_key="plan",
        action="runtime:read",
    ) is None
    assert store.validate_runtime_capability_token(
        bearer_token=exchanged.bearer_token,
        protocol_run_id=detail.run.protocol_run_id,
        artifact_key="plan",
        action="runtime:delete",
    ) is None
    assert store.validate_runtime_capability_token(
        bearer_token=exchanged.bearer_token,
        protocol_run_id=detail.run.protocol_run_id,
        artifact_key="plan",
        action="journey:result",
    ) is None

    store.update_routed_task_result(
        enroll.agent_token,
        first_stage.routed_task_id,
        {
            "status": "completed",
            "transition_id": "done-capability-1",
            "summary": "Plan updated.",
            "full_text": "Updated protocol/plan.md.\nPROTOCOL_SUMMARY: Plan updated.",
            "artifacts": [
                {
                    "artifact_key": "plan",
                    "artifact_kind": "workspace_file",
                    "path": "protocol/plan.md",
                    "exists": False,
                }
            ],
        },
    )
    assert store.validate_runtime_capability_token(
        bearer_token=exchanged.bearer_token,
        protocol_run_id=detail.run.protocol_run_id,
        artifact_key="plan",
        action="runtime:read",
    ) is None


def test_routed_protocol_result_redacts_runtime_tokens(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    enroll, _published, _created, detail = running_protocol_run(store)
    first_stage = detail.stage_executions[0]

    store.update_routed_task_result(
        enroll.agent_token,
        first_stage.routed_task_id,
        {
            "status": "completed",
            "transition_id": "redact-runtime-token",
            "summary": "Leaked oct-rt-secret-token in summary.",
            "full_text": "Provider echoed oct-cap-secret-ref and oct-rt-secret-token.\nPROTOCOL_SUMMARY: Done.",
            "artifacts": [
                {
                    "artifact_key": "plan",
                    "artifact_kind": "workspace_file",
                    "path": "protocol/plan.md",
                    "exists": False,
                }
            ],
        },
    )

    task = store.get_task(first_stage.routed_task_id)
    result = task.result.as_dict() if task.result is not None else {}
    assert "oct-rt-secret-token" not in json.dumps(result)
    assert "oct-cap-secret-ref" not in json.dumps(result)
    assert "<runtime-token>" in json.dumps(result)


def test_protocol_stage_completion_via_routed_task_result_updates_both_sides(
    postgres_registry_truncated: str,
) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    enroll, _published, created, detail = running_protocol_run(store)
    first_stage = detail.stage_executions[0]

    origin_conv_id = str(created.run.root_conversation_id or "")
    recipient_conv_id = _recipient_conversation_id_for_task(
        store, first_stage.routed_task_id, enroll.agent_id
    )
    assert origin_conv_id and recipient_conv_id

    origin_before = len(store.list_events(origin_conv_id).events)
    recipient_before = len(store.list_events(recipient_conv_id).events)

    result = store.update_routed_task_result(
        enroll.agent_token,
        first_stage.routed_task_id,
        {
            "status": "completed",
            "transition_id": "done-harden-1",
            "summary": "Plan updated.",
            "full_text": "Updated protocol/plan.md.\nPROTOCOL_SUMMARY: Plan updated.",
            "artifacts": [
                {
                    "artifact_key": "plan",
                    "artifact_kind": "workspace_file",
                    "path": "protocol/plan.md",
                    "exists": True,
                    "size_bytes": 42,
                    "content_hash": "hash-harden",
                    "modified_at": "2026-04-16T00:00:00+00:00",
                    "verification_state": "verified",
                }
            ],
        },
    )
    assert result.events_written is True
    assert result.recipient_conversation_id == recipient_conv_id
    assert result.recipient_inserted_events, "Completion must write to the recipient conversation"

    origin_after = store.list_events(origin_conv_id).events
    recipient_after = store.list_events(recipient_conv_id).events
    assert len(origin_after) > origin_before
    assert len(recipient_after) > recipient_before

    newest_recipient = recipient_after[-1]
    metadata = newest_recipient.metadata.as_dict() if newest_recipient.metadata is not None else {}
    assert metadata.get("status") == "completed"
    assert metadata.get("routed_task_id") == first_stage.routed_task_id

    refreshed = store.get_protocol_run(created.run.protocol_run_id, access=operator_access())
    assert refreshed.run.current_stage_key == "review"
    assert refreshed.stage_executions[0].stage_key == "review"


def test_recipient_conversation_event_carries_protocol_stage_navigation_context(
    postgres_registry_truncated: str,
) -> None:
    """UI navigation from recipient conversation back to the run must not rely on
    out-of-band state. The routed_task_id embedded in each recipient event is
    the link: it is a ``protocol-stage:<stage_execution_id>`` key that the
    registry already resolves to a run via ``_protocol_run_id_from_task_record``.
    """
    store = RegistryPostgresStore(postgres_registry_truncated)
    enroll, _published, created, detail = running_protocol_run(store)
    first_stage = detail.stage_executions[0]

    recipient_conv_id = _recipient_conversation_id_for_task(
        store, first_stage.routed_task_id, enroll.agent_id
    )

    events = store.list_events(recipient_conv_id).events
    task_events = [event for event in events if str(event.kind or "") == "task.status"]
    assert task_events

    for event in task_events:
        metadata = event.metadata.as_dict() if event.metadata is not None else {}
        routed_task_id = str(metadata.get("routed_task_id") or "")
        assert routed_task_id.startswith("protocol-stage:"), (
            "Recipient events must carry the protocol-stage routed task id so the UI "
            "can navigate to the owning run"
        )

    task = store.get_task(first_stage.routed_task_id)
    task_request = task.request.as_dict() if task.request is not None else {}
    context = task_request.get("context") if isinstance(task_request, dict) else None
    assert isinstance(context, dict)
    assert context.get("protocol_run_id") == created.run.protocol_run_id
    assert context.get("stage_key") == "planning"


def test_protocol_run_detail_and_task_payloads_include_lineage_and_artifact_location(
    postgres_registry_truncated: str,
) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    enroll, _published, created, detail = running_protocol_run(store)
    first_stage = detail.stage_executions[0]
    working_dir = "/tmp/protocol-run-artifacts"
    scoped_plan_path = f"protocol-runs/{created.run.protocol_run_id}/protocol/plan.md"

    store.update_routed_task_result(
        enroll.agent_token,
        first_stage.routed_task_id,
        {
            "status": "completed",
            "transition_id": "lineage-1",
            "summary": "Plan updated.",
            "full_text": "Updated protocol/plan.md.\nPROTOCOL_SUMMARY: Plan updated.",
            "working_dir": working_dir,
            "artifacts": [
                {
                    "artifact_key": "plan",
                    "artifact_kind": "workspace_file",
                    "path": scoped_plan_path,
                    "exists": True,
                    "size_bytes": 128,
                    "content_hash": "abc123",
                    "modified_at": "2026-04-16T00:00:00+00:00",
                    "verification_state": "verified",
                }
            ],
        },
    )

    task = store.get_task(first_stage.routed_task_id)
    assert task.protocol_run_id == created.run.protocol_run_id
    assert task.protocol_stage_execution_id == first_stage.protocol_stage_execution_id
    assert task.protocol_definition_version_id == created.run.protocol_definition_version_id
    assert task.stage_key == "planning"
    assert task.participant_key == "worker"
    assert task.working_dir == working_dir
    assert task.artifact_count == 1
    assert task.request is not None
    assert task.result is not None

    listed = next(
        item for item in store.list_tasks(protocol_run_id=created.run.protocol_run_id)
        if item.routed_task_id == first_stage.routed_task_id
    )
    assert listed.protocol_run_id == created.run.protocol_run_id
    assert listed.stage_key == "planning"
    assert listed.participant_key == "worker"
    assert listed.working_dir == working_dir
    assert listed.artifact_count == 1
    assert listed.request is not None
    assert listed.result is not None

    refreshed = store.get_protocol_run(created.run.protocol_run_id, access=operator_access())
    assert refreshed.tasks, "Run detail should include linked routed tasks for operational lineage"
    linked = next(item for item in refreshed.tasks if item.routed_task_id == first_stage.routed_task_id)
    assert linked.stage_key == "planning"
    artifact = next(item for item in refreshed.artifacts if item.artifact_key == "plan")
    assert artifact.workspace_path == scoped_plan_path
    assert Path(artifact.location).resolve() == (Path(working_dir) / scoped_plan_path).resolve()


def test_protocol_run_declared_artifacts_are_run_scoped(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    _enroll, _published, created, detail = running_protocol_run(store)

    artifact = next(item for item in detail.artifacts if item.artifact_key == "plan")
    assert artifact.workspace_path == f"protocol-runs/{created.run.protocol_run_id}/protocol/plan.md"
    assert artifact.location == artifact.workspace_path


def test_protocol_fork_continue_after_materializes_snapshots_and_lineage(
    postgres_registry_truncated: str,
    tmp_path: Path,
) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    enroll, _published, created, detail = running_protocol_run(store)
    parent_workspace = tmp_path / "parent-workspace"
    parent_workspace.mkdir()
    with get_connection(postgres_registry_truncated) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE agent_registry.protocol_runs SET workspace_ref = %s WHERE protocol_run_id = %s",
                (str(parent_workspace), created.run.protocol_run_id),
            )
        conn.commit()
    first_stage = detail.stage_executions[0]
    parent_scoped_path = f"protocol-runs/{created.run.protocol_run_id}/protocol/plan.md"
    parent_file = parent_workspace / parent_scoped_path
    parent_file.parent.mkdir(parents=True)
    parent_file.write_text("parent plan", encoding="utf-8")

    store.update_routed_task_result(
        enroll.agent_token,
        first_stage.routed_task_id,
        {
            "status": "completed",
            "transition_id": "fork-parent-plan",
            "summary": "Plan updated.",
            "full_text": "Updated protocol/plan.md.\nPROTOCOL_SUMMARY: Plan updated.",
            "working_dir": str(parent_workspace),
            "artifacts": [
                {
                    "artifact_key": "plan",
                    "artifact_kind": "workspace_file",
                    "path": parent_scoped_path,
                    "exists": True,
                    "size_bytes": parent_file.stat().st_size,
                    "content_hash": "parent-plan-hash",
                    "modified_at": "2026-04-16T00:00:00+00:00",
                    "verification_state": "verified",
                }
            ],
        },
    )
    parent_detail = store.get_protocol_run(created.run.protocol_run_id, access=operator_access())
    parent_stage = next(item for item in parent_detail.stage_executions if item.stage_key == "planning")
    parent_snapshot = next(item for item in parent_detail.artifact_snapshots if item.artifact_key == "plan")
    assert parent_snapshot.produced_by_stage_execution_id == parent_stage.protocol_stage_execution_id

    forked = store.fork_protocol_run_from_stage(
        created.run.protocol_run_id,
        ProtocolRunForkRequestRecord(
            stage_execution_id=parent_stage.protocol_stage_execution_id,
            fork_mode="continue_after",
            fork_reason="Continue with the parent plan as a new run.",
        ),
        access=operator_access(),
    )

    assert forked.ok is True
    assert forked.run is not None
    child_detail = store.get_protocol_run(forked.run.protocol_run_id, access=operator_access())
    assert child_detail.run.parent_protocol_run_id == created.run.protocol_run_id
    assert child_detail.run.parent_stage_execution_id == parent_stage.protocol_stage_execution_id
    assert child_detail.run.fork_mode == "continue_after"
    assert child_detail.run.current_stage_key == "review"
    seeded_stage = next(item for item in child_detail.stage_executions if item.stage_key == "planning")
    assert seeded_stage.status == "completed"
    assert seeded_stage.routed_task_id == ""
    child_artifact = next(item for item in child_detail.artifacts if item.artifact_key == "plan")
    assert child_artifact.workspace_path == f"protocol-runs/{child_detail.run.protocol_run_id}/protocol/plan.md"
    assert Path(child_artifact.location).read_text(encoding="utf-8") == "parent plan"
    assert Path(child_artifact.location).resolve() != parent_file.resolve()
    assert parent_file.read_text(encoding="utf-8") == "parent plan"
    child_snapshot = next(item for item in child_detail.artifact_snapshots if item.artifact_key == "plan")
    assert child_snapshot.produced_by_stage_execution_id == seeded_stage.protocol_stage_execution_id


def test_protocol_fork_missing_snapshot_blocks_with_actionable_list(
    postgres_registry_truncated: str,
    tmp_path: Path,
) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    enroll, _published, created, detail = running_protocol_run(store)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    first_stage = detail.stage_executions[0]
    scoped_path = f"protocol-runs/{created.run.protocol_run_id}/protocol/plan.md"

    store.update_routed_task_result(
        enroll.agent_token,
        first_stage.routed_task_id,
        {
            "status": "completed",
            "transition_id": "fork-missing-snapshot",
            "summary": "Plan reported but file was absent.",
            "full_text": "Updated protocol/plan.md.\nPROTOCOL_SUMMARY: Plan reported.",
            "working_dir": str(workspace),
            "artifacts": [
                {
                    "artifact_key": "plan",
                    "artifact_kind": "workspace_file",
                    "path": scoped_path,
                    "exists": True,
                    "size_bytes": 128,
                    "content_hash": "missing-snapshot-hash",
                    "modified_at": "2026-04-16T00:00:00+00:00",
                    "verification_state": "verified",
                }
            ],
        },
    )
    parent_detail = store.get_protocol_run(created.run.protocol_run_id, access=operator_access())
    parent_stage = next(item for item in parent_detail.stage_executions if item.stage_key == "planning")

    forked = store.fork_protocol_run_from_stage(
        created.run.protocol_run_id,
        ProtocolRunForkRequestRecord(
            stage_execution_id=parent_stage.protocol_stage_execution_id,
            fork_mode="continue_after",
        ),
        access=operator_access(),
    )

    assert forked.ok is False
    assert forked.status == "missing_snapshots"
    assert any("plan" in item for item in forked.missing_snapshots)


def test_auto_protocol_planner_task_progress_and_result_finalize_session(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    enroll = store.enroll(
        agent_card(bot_key="planner").model_copy(update={
            "supported_admin_operations": ["design_auto_protocol"],
        })
    )
    conversation = store.create_conversation(
        target_agent_id=enroll.agent_id,
        title="Auto Protocol planner",
        origin_channel="registry",
        external_conversation_ref="protocol-auto-session:auto-task-session",
        source_kind="auto_design",
        hidden_from_default_views=True,
    )
    model_request = ProtocolAutoDesignModelRequestRecord(
        requirement_text="Build a small browser app with runtime evidence.",
        available_agents=[
            {
                "agent_id": enroll.agent_id,
                "display_name": "Planner",
                "routing_skills": ["architecture", "testing"],
            }
        ],
    )
    request_payload = ProtocolAutoDesignRequestRecord(
        surface="registry",
        requirement_text=model_request.requirement_text,
        target_protocol_id="protocol-source",
        source_run_id="run-source-1",
        available_agents=model_request.available_agents,
    )
    routed_task_id = "auto-design:auto-task-session:task"
    store.create_routed_task(
        RoutedTaskRequest(
            routed_task_id=routed_task_id,
            parent_conversation_id=conversation.conversation_id,
            origin_transport_ref="protocol-auto-session:auto-task-session",
            origin_agent_id=enroll.agent_id,
            target_agent_id=enroll.agent_id,
            title="Design Auto Protocol",
            instructions="Run the Auto Protocol planner.",
            context=RegistryJsonRecord.model_validate({
                "task_source_kind": "auto_design",
                "auto_design": {
                    "session_id": "auto-task-session",
                    "request": model_request.model_dump(mode="json"),
                    "request_payload": request_payload.model_dump(mode="json"),
                },
            }),
            constraints=RegistryJsonRecord.model_validate({"timeout_seconds": 3600, "source": "auto_protocol"}),
            requested_skills=["architecture", "testing"],
            priority="high",
        )
    )
    planning = ProtocolAutoDesignSessionRecord(
        session_id="auto-task-session",
        status="planning",
        surface="registry",
        actor_ref=operator_access().actor_ref,
        requirement_text=request_payload.requirement_text,
        source_protocol_id=request_payload.target_protocol_id,
        source_run_id=request_payload.source_run_id,
        target_protocol_id=request_payload.target_protocol_id,
        planner_task_id=routed_task_id,
        planner_policy="auto_select",
        planner_agent_id=enroll.agent_id,
        planner_state=RegistryJsonRecord.model_validate({"planner_status": "queued"}),
    )
    store.update_protocol_auto_design_session(planning, access=operator_access(), event_kind="planning_started")

    poll = store.poll(enroll.agent_token, cursor=0, limit=10)
    assert any(item.kind == "routed_task" and item.payload.get("routed_task_id") == routed_task_id for item in poll.deliveries)

    store.update_routed_task_status(
        enroll.agent_token,
        routed_task_id,
        RoutedTaskUpdate(
            routed_task_id=routed_task_id,
            status="running",
            transition_id="auto-progress-1",
            summary="Planner is analyzing the requirement.",
            progress=20,
        ),
    )
    progressed = store.get_protocol_auto_design_session("auto-task-session", access=operator_access())
    assert progressed.status == "planning"
    assert progressed.planner_state["planner_status"] == "running"
    assert progressed.planner_state["progress_summary"] == "Planner is analyzing the requirement."
    assert progressed.planner_state["progress"] == 20

    response = ProtocolAutoDesignModelResponseRecord(
        requirement_summary="Build a small browser app.",
        domain="browser app",
        risk_assessment="medium",
        work_packages=[
            ProtocolAutoDesignWorkPackageRecord(
                package_key="implementation",
                display_name="Implementation",
                rationale="Build the app and its evidence.",
                role_key="builder",
                role_display_name="Builder",
                role_responsibility="Build the requested app.",
                required_skills=["implementation", "testing"],
                purpose="Create a runnable app.",
                quality_bar="Runtime evidence is captured.",
                artifact_key="app",
                artifact_display_name="Runnable app",
                artifact_description="Browser app package.",
                artifact_path="artifacts/app",
            )
        ],
    )
    store.update_routed_task_result(
        enroll.agent_token,
        routed_task_id,
        RoutedTaskResult(
            routed_task_id=routed_task_id,
            status="completed",
            transition_id="auto-complete-1",
            summary="Planner completed.",
            full_text=response.model_dump_json(),
            provider="codex",
        ),
    )

    completed = store.get_protocol_auto_design_session("auto-task-session", access=operator_access())
    assert completed.status in {"ready", "blocked"}
    assert completed.planner_task_id == routed_task_id
    assert completed.source_run_id == "run-source-1"
    assert completed.target_protocol_id == "protocol-source"
    assert completed.analysis.domain == "browser app"
    assert completed.model_response is not None
    assert completed.model_response.domain == "browser app"
    assert completed.draft_definition_json.as_dict()["metadata"]["auto_protocol"]["requirement"] == request_payload.requirement_text


def test_auto_protocol_legacy_management_request_is_not_finalized_during_maintenance(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    enroll = store.enroll(
        agent_card(bot_key="legacy-planner").model_copy(update={
            "supported_admin_operations": ["design_auto_protocol"],
        })
    )
    response = ProtocolAutoDesignModelResponseRecord(
        requirement_summary="Build a small browser app.",
        domain="legacy browser app",
        risk_assessment="medium",
        work_packages=[
            ProtocolAutoDesignWorkPackageRecord(
                package_key="implementation",
                display_name="Implementation",
                rationale="Build the app and evidence.",
                role_key="builder",
                role_display_name="Builder",
                role_responsibility="Build the requested app.",
                required_skills=["implementation"],
                purpose="Create a runnable app.",
                quality_bar="Runtime evidence is captured.",
                artifact_key="app",
                artifact_display_name="Runnable app",
                artifact_description="Browser app package.",
                artifact_path="artifacts/app",
            )
        ],
    )
    request = store.create_management_request(
        ManagementRequest(
            agent_id=enroll.agent_id,
            payload=DesignAutoProtocolRequest(
                request=ProtocolAutoDesignModelRequestRecord(
                    requirement_text="Build a legacy-routed browser app.",
                ),
            ),
            timeout_seconds=3600,
        )
    )
    planning = ProtocolAutoDesignSessionRecord(
        session_id="auto-legacy-session",
        status="planning",
        surface="registry",
        actor_ref=operator_access().actor_ref,
        requirement_text="Build a legacy-routed browser app.",
        planner_request_id=request.request_id,
        planner_agent_id=enroll.agent_id,
        planner_state=RegistryJsonRecord.model_validate({"planner_status": "queued"}),
    )
    store.update_protocol_auto_design_session(planning, access=operator_access(), event_kind="planning_started")
    store.report_management_result(
        enroll.agent_token,
        request.request_id,
        ManagementResult(
            request_id=request.request_id,
            agent_id=enroll.agent_id,
            success=True,
            payload=DesignAutoProtocolResult(response=response),
        ),
    )

    maintenance = store.run_protocol_maintenance(now="2026-04-16T00:00:00+00:00")

    assert "auto-legacy-session" not in maintenance.affected_auto_session_ids
    completed = store.get_protocol_auto_design_session("auto-legacy-session", access=operator_access())
    assert completed.status == "planning"
    assert completed.model_response is None


def test_auto_protocol_planner_task_timeout_fails_session_during_maintenance(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    enroll = store.enroll(
        agent_card(bot_key="timeout-planner").model_copy(update={
            "supported_admin_operations": ["design_auto_protocol"],
        })
    )
    conversation = store.create_conversation(
        target_agent_id=enroll.agent_id,
        title="Auto Protocol planner",
        origin_channel="registry",
        external_conversation_ref="protocol-auto-session:auto-timeout-session",
        source_kind="auto_design",
        hidden_from_default_views=True,
    )
    routed_task_id = "auto-design:auto-timeout-session:task"
    request_payload = ProtocolAutoDesignRequestRecord(
        surface="registry",
        requirement_text="Build an app that should time out.",
    )
    store.create_routed_task(
        RoutedTaskRequest(
            routed_task_id=routed_task_id,
            parent_conversation_id=conversation.conversation_id,
            origin_transport_ref="protocol-auto-session:auto-timeout-session",
            origin_agent_id=enroll.agent_id,
            target_agent_id=enroll.agent_id,
            title="Design Auto Protocol",
            instructions="Run the Auto Protocol planner.",
            context=RegistryJsonRecord.model_validate({
                "task_source_kind": "auto_design",
                "auto_design": {
                    "session_id": "auto-timeout-session",
                    "request": ProtocolAutoDesignModelRequestRecord(requirement_text=request_payload.requirement_text).model_dump(mode="json"),
                    "request_payload": request_payload.model_dump(mode="json"),
                },
            }),
            constraints=RegistryJsonRecord.model_validate({"timeout_seconds": 1, "source": "auto_protocol"}),
            requested_skills=["architecture"],
            priority="high",
            created_at="2026-04-16T00:00:00+00:00",
        )
    )
    store.update_protocol_auto_design_session(
        ProtocolAutoDesignSessionRecord(
            session_id="auto-timeout-session",
            status="planning",
            surface="registry",
            actor_ref=operator_access().actor_ref,
            requirement_text=request_payload.requirement_text,
            planner_task_id=routed_task_id,
            planner_policy="auto_select",
            planner_agent_id=enroll.agent_id,
            planner_state=RegistryJsonRecord.model_validate({"planner_status": "queued"}),
        ),
        access=operator_access(),
        event_kind="planning_started",
    )

    maintenance = store.run_protocol_maintenance(now="2036-07-08T00:00:03+00:00")

    assert "auto-timeout-session" in maintenance.affected_auto_session_ids
    failed = store.get_protocol_auto_design_session("auto-timeout-session", access=operator_access())
    assert failed.status == "failed"
    assert failed.warnings[0].code == "planner.task_timeout"
    assert failed.planner_state["planner_status"] == "timed_out"


def test_auto_protocol_run_lessons_round_trip(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    generated = generate_auto_protocol_session(
        ProtocolAutoDesignRequestRecord.model_validate(
            {
                "mode": "create",
                "surface": "registry",
                "requirement_text": "Build a small workflow that records evidence.",
                "run_lessons": [
                    {
                        "category": "journey_failure",
                        "lesson_type": "browser_journey",
                        "summary": "The prior run missed a visible result assertion.",
                        "applies_when": "the product has a user-visible workflow",
                        "contract_section": "verification_contract",
                        "requirement_id": "visible_result_assertion",
                        "required_evidence": ["browser_journey", "negative_case"],
                        "source_ref": "runtime-event:abc",
                        "source_run_id": "run-prior",
                        "source_failure": "journey_failed",
                    }
                ],
            }
        ),
        session_id="auto-run-lessons",
        created_at="2026-04-16T00:00:00+00:00",
        updated_at="2026-04-16T00:00:00+00:00",
    )
    session = store.update_protocol_auto_design_session(generated, access=operator_access(), event_kind="generated")

    fetched = store.get_protocol_auto_design_session(session.session_id, access=operator_access())
    assert fetched.run_lessons[0].category == "journey_failure"
    assert fetched.run_lessons[0].lesson_type == "browser_journey"
    assert fetched.run_lessons[0].applies_when == "the product has a user-visible workflow"
    assert fetched.run_lessons[0].required_evidence == ["browser_journey", "negative_case"]
    assert fetched.run_lessons[0].source_run_id == "run-prior"
    assert fetched.draft_definition_json.as_dict()["metadata"]["auto_protocol"]["run_lessons"][0]["summary"] == (
        "The prior run missed a visible result assertion."
    )
