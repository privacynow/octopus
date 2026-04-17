"""Protocol document parsing, validation, prompts, and review helpers."""

from __future__ import annotations

import difflib
import hashlib
import json
from datetime import datetime, timedelta, timezone
from collections.abc import Sequence

import yaml

from .models import *  # noqa: F401,F403
from .models import _DECISION_RE, _SUMMARY_RE, _TERMINAL_STAGE_TARGETS

def migrate_protocol_document_data(value: object) -> dict[str, object]:
    raw = dict(value) if isinstance(value, dict) else (
        value.model_dump(mode="json")
        if hasattr(value, "model_dump")
        else {}
    )
    if not raw:
        return {}
    migrated = json.loads(json.dumps(raw))
    raw_schema_version = migrated.get("schema_version", PROTOCOL_LEGACY_SCHEMA_VERSION)
    try:
        schema_version = int(raw_schema_version or PROTOCOL_LEGACY_SCHEMA_VERSION)
    except (TypeError, ValueError) as exc:
        raise ValueError("protocol definition schema_version must be an integer") from exc
    if schema_version < PROTOCOL_LEGACY_SCHEMA_VERSION:
        schema_version = PROTOCOL_LEGACY_SCHEMA_VERSION
    if schema_version > PROTOCOL_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported protocol schema_version {schema_version}; expected at most {PROTOCOL_SCHEMA_VERSION}"
        )
    while schema_version < PROTOCOL_SCHEMA_VERSION:
        if schema_version == PROTOCOL_LEGACY_SCHEMA_VERSION:
            migrated.setdefault("metadata", {})
            migrated.setdefault("participants", [])
            migrated.setdefault("artifacts", [])
            migrated.setdefault("stages", [])
            migrated.setdefault("policies", {})
            for artifact in migrated.get("artifacts", []) or []:
                if isinstance(artifact, dict):
                    artifact.setdefault("verify", True)
            for stage in migrated.get("stages", []) or []:
                if isinstance(stage, dict):
                    stage.setdefault("strict_completion", False)
                    stage.setdefault("require_output_verification", None)
                    stage.setdefault("timeout_seconds", 0)
            policies = migrated.get("policies")
            if isinstance(policies, dict):
                policies.setdefault("single_active_writer", True)
                policies.setdefault("max_review_rounds", 5)
            schema_version = 1
            migrated["schema_version"] = schema_version
            continue
        raise ValueError(
            f"Unsupported protocol schema_version migration path {schema_version} -> {PROTOCOL_SCHEMA_VERSION}"
        )
    migrated["schema_version"] = PROTOCOL_SCHEMA_VERSION
    return migrated


def canonical_protocol_document(value: object) -> ProtocolDefinitionDocumentRecord:
    if isinstance(value, ProtocolDefinitionDocumentRecord):
        return value
    return ProtocolDefinitionDocumentRecord.model_validate(migrate_protocol_document_data(value))


def protocol_definition_content_hash(document: ProtocolDefinitionDocumentRecord) -> str:
    payload = json.dumps(document.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_protocol_document(value: object) -> ProtocolValidationResultRecord:
    try:
        document = canonical_protocol_document(value)
    except Exception as exc:
        return ProtocolValidationResultRecord(ok=False, errors=[str(exc)])
    return ProtocolValidationResultRecord(
        ok=True,
        errors=[],
        normalized_document=document,
        content_hash=protocol_definition_content_hash(document),
    )


def normalize_protocol_document_format(value: object, *, default: ProtocolDocumentTextFormat = "json") -> ProtocolDocumentTextFormat:
    token = str(value or "").strip().lower()
    if not token:
        return default
    if token not in {"json", "yaml"}:
        raise ValueError("Protocol document format must be json or yaml")
    return token  # type: ignore[return-value]


def protocol_document_from_text(text: str, *, format: ProtocolDocumentTextFormat = "json") -> ProtocolDefinitionDocumentRecord:
    normalized = normalize_protocol_document_format(format)
    source = str(text or "").strip()
    if not source:
        raise ValueError("Protocol document text must not be empty")
    try:
        loaded = json.loads(source) if normalized == "json" else yaml.safe_load(source)
    except Exception as exc:
        raise ValueError(f"Protocol {normalized} parse failed: {exc}") from exc
    return canonical_protocol_document(loaded)


def protocol_document_to_text(
    value: object,
    *,
    format: ProtocolDocumentTextFormat = "json",
) -> str:
    normalized = normalize_protocol_document_format(format)
    document = canonical_protocol_document(value)
    payload = document.model_dump(mode="json")
    if normalized == "yaml":
        return str(yaml.safe_dump(payload, sort_keys=False, allow_unicode=False))
    return json.dumps(payload, indent=2, sort_keys=False)


def protocol_document_unified_diff(
    left: object,
    right: object,
    *,
    left_label: str = "draft",
    right_label: str = "published",
    format: ProtocolDocumentTextFormat = "json",
) -> str:
    left_text = protocol_document_to_text(left, format=format).splitlines()
    right_text = protocol_document_to_text(right, format=format).splitlines()
    diff = difflib.unified_diff(
        left_text,
        right_text,
        fromfile=left_label,
        tofile=right_label,
        lineterm="",
    )
    return "\n".join(diff)


def protocol_participant_session_key(run_id: str, participant_key: str) -> str:
    return f"protocol:{str(run_id or '').strip()}:participant:{str(participant_key or '').strip()}"


def protocol_stage_instruction_contract(stage: ProtocolStageDefinitionRecord) -> str:
    if stage.stage_kind == "work":
        if stage.strict_completion:
            return (
                "Complete the work for this stage, update the required artifacts in the workspace, "
                "and end your final response with explicit protocol control lines:\n"
                "PROTOCOL_DECISION: completed\n"
                "PROTOCOL_SUMMARY: one short sentence describing the completed work"
            )
        return (
            "Complete the work for this stage, update the required artifacts in the workspace, "
            "and end your final response with a short `PROTOCOL_SUMMARY:` line."
        )
    allowed = ", ".join(stage.allowed_decisions())
    return (
        "You must end your final response with explicit protocol control lines:\n"
        f"PROTOCOL_DECISION: one of [{allowed}]\n"
        "PROTOCOL_SUMMARY: one short sentence explaining the decision\n"
        "Keep the rest of the response as the detailed review or acceptance rationale."
    )


def render_protocol_stage_prompt(
    *,
    document: ProtocolDefinitionDocumentRecord,
    run: ProtocolRunRecord,
    stage: ProtocolStageDefinitionRecord,
    artifacts: list[ProtocolArtifactRecord],
    previous_feedback: str = "",
) -> str:
    participant = document.participant(stage.participant_key)
    artifact_lines: list[str] = []
    artifact_by_key = {item.artifact_key: item for item in artifacts}
    for artifact_key in dict.fromkeys([*stage.inputs, *stage.outputs]):
        definition = document.artifact(artifact_key)
        artifact = artifact_by_key.get(artifact_key)
        location = str(
            (
                artifact.workspace_path
                if artifact is not None and artifact.workspace_path
                else artifact.location
                if artifact is not None and artifact.location
                else definition.path
            )
            or ""
        ).strip()
        detail = f"{artifact_key}: {location}" if location else artifact_key
        artifact_lines.append(f"- {detail}")
    lines = [
        f"Protocol: {document.display_name or document.slug}",
        f"Run id: {run.protocol_run_id}",
        f"Stage: {stage.stage_key}",
        f"Participant: {participant.display_name or participant.participant_key}",
        f"Problem statement:\n{run.problem_statement.strip()}",
    ]
    if run.workspace_ref:
        lines.append(f"Workspace/project: {run.workspace_ref}")
    if artifact_lines:
        lines.append("Artifacts for this stage:\n" + "\n".join(artifact_lines))
    if participant.instructions:
        lines.append("Participant guidance:\n" + participant.instructions.strip())
    if stage.instructions:
        lines.append("Stage instructions:\n" + stage.instructions.strip())
    if previous_feedback.strip():
        lines.append("Feedback from the previous review stage:\n" + previous_feedback.strip())
    lines.append(protocol_stage_instruction_contract(stage))
    return "\n\n".join(part for part in lines if part.strip())


def parse_protocol_stage_decision(
    *,
    stage: ProtocolStageDefinitionRecord,
    full_text: str,
    summary_fallback: str = "",
) -> ProtocolStageDecisionRecord:
    text = str(full_text or "").strip()
    decision_match = _DECISION_RE.search(text)
    summary_match = _SUMMARY_RE.search(text)
    allowed = set(stage.allowed_decisions())
    if stage.stage_kind == "work":
        require_explicit_decision = len(allowed) > 1
        if decision_match is not None:
            decision = str(decision_match.group(1) or "").strip().lower()
        elif require_explicit_decision:
            raise ValueError(f"Stage {stage.stage_key} result is missing PROTOCOL_DECISION")
        else:
            decision = "completed"
        if decision not in allowed:
            raise ValueError(
                f"Stage {stage.stage_key} returned unsupported decision {decision!r}; expected one of {sorted(allowed)}"
            )
        if stage.strict_completion and summary_match is None:
            raise ValueError(f"Stage {stage.stage_key} result is missing PROTOCOL_SUMMARY")
        summary = (
            str(summary_match.group(1) or "").strip()
            if summary_match is not None
            else summary_fallback or _first_nonempty_line(text) or "Stage completed."
        )
        return ProtocolStageDecisionRecord(decision=decision, summary=summary)
    if decision_match is None:
        raise ValueError(f"Stage {stage.stage_key} result is missing PROTOCOL_DECISION")
    decision = str(decision_match.group(1) or "").strip().lower()
    if decision not in allowed:
        raise ValueError(
            f"Stage {stage.stage_key} returned unsupported decision {decision!r}; expected one of {sorted(allowed)}"
        )
    if summary_match is None:
        raise ValueError(f"Stage {stage.stage_key} result is missing PROTOCOL_SUMMARY")
    summary = str(summary_match.group(1) or "").strip()
    return ProtocolStageDecisionRecord(decision=decision, summary=summary)


def stage_target_for_decision(stage: ProtocolStageDefinitionRecord, decision: str) -> str:
    normalized = str(decision or "").strip().lower()
    if stage.stage_kind == "work" and not stage.transitions.as_dict():
        return ""
    target = stage.transition_target(normalized)
    if not target and stage.stage_kind == "work" and normalized == "completed":
        return ""
    return target


def is_protocol_terminal_target(target: str) -> bool:
    return str(target or "").strip() in _TERMINAL_STAGE_TARGETS


def protocol_review_edge_key(from_stage_key: str, to_stage_key: str) -> str:
    left = str(from_stage_key or "").strip()
    right = str(to_stage_key or "").strip()
    if not left or not right:
        return ""
    return f"{left}:{right}"


def protocol_review_edge_counts(transitions: Sequence[ProtocolTransitionRecord]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in transitions:
        metadata = item.metadata_json.as_dict()
        edge_key = str(metadata.get("review_edge_key", "") or "").strip()
        if not edge_key:
            continue
        try:
            rounds = int(metadata.get("current_review_rounds", 0) or 0)
        except (TypeError, ValueError):
            rounds = 0
        if rounds > counts.get(edge_key, 0):
            counts[edge_key] = rounds
    return counts


def protocol_current_review_state(
    transitions: Sequence[ProtocolTransitionRecord],
    *,
    max_review_rounds: int,
) -> tuple[int, int, str]:
    current_rounds = 0
    current_edge_key = ""
    for item in transitions:
        metadata = item.metadata_json.as_dict()
        if "current_review_rounds" not in metadata and "review_edge_key" not in metadata:
            continue
        try:
            current_rounds = int(metadata.get("current_review_rounds", 0) or 0)
        except (TypeError, ValueError):
            current_rounds = 0
        current_edge_key = str(metadata.get("review_edge_key", "") or "").strip()
        break
    return current_rounds, int(max_review_rounds or 0), current_edge_key


def default_protocol_document_slug(document: ProtocolDefinitionDocumentRecord) -> str:
    slug = document.slug
    if slug:
        return slug
    display = document.display_name.lower().strip().replace(" ", "-")
    return display or "protocol"


def protocol_stage_runtime_contract(
    *,
    document: ProtocolDefinitionDocumentRecord,
    run: ProtocolRunRecord,
    stage_execution_id: str,
    stage: ProtocolStageDefinitionRecord,
) -> ProtocolStageRuntimeContractRecord:
    outputs = [
        ProtocolStageArtifactContractRecord(
            artifact_key=artifact.artifact_key,
            artifact_kind=artifact.kind,
            path=artifact.path,
            verify=artifact.verify if stage.require_output_verification is not False else False,
        )
        for artifact in (document.artifact(artifact_key) for artifact_key in stage.outputs)
    ]
    require_verification = bool(
        stage.require_output_verification
        if stage.require_output_verification is not None
        else any(item.verify for item in outputs)
    )
    return ProtocolStageRuntimeContractRecord(
        protocol_run_id=run.protocol_run_id,
        protocol_definition_version_id=run.protocol_definition_version_id,
        protocol_stage_execution_id=stage_execution_id,
        participant_key=stage.participant_key,
        stage_key=stage.stage_key,
        stage_kind=stage.stage_kind,
        strict_completion=stage.strict_completion,
        require_output_verification=require_verification,
        output_artifacts=outputs,
    )


def protocol_stage_internal_context(
    *,
    document: ProtocolDefinitionDocumentRecord,
    run: ProtocolRunRecord,
    stage_execution_id: str,
    stage: ProtocolStageDefinitionRecord,
) -> dict[str, object]:
    contract = protocol_stage_runtime_contract(
        document=document,
        run=run,
        stage_execution_id=stage_execution_id,
        stage=stage,
    )
    return {
        "protocol_stage_contract": contract.model_dump(mode="json"),
    }


def protocol_artifact_contract_error(
    *,
    document: ProtocolDefinitionDocumentRecord,
    stage: ProtocolStageDefinitionRecord,
    observations: Sequence[ProtocolArtifactObservationRecord],
) -> tuple[str, str] | None:
    if stage.require_output_verification is False:
        return None
    observed_by_key = {item.artifact_key: item for item in observations}
    for artifact_key in stage.outputs:
        artifact = document.artifact(artifact_key)
        verify_required = bool(stage.require_output_verification) if stage.require_output_verification is not None else artifact.verify
        if not verify_required:
            continue
        observed = observed_by_key.get(artifact_key)
        if observed is None or not observed.exists:
            return ("artifact_missing", f"Required artifact {artifact_key} was not produced.")
        if not str(observed.content_hash or "").strip():
            return ("artifact_integrity_failed", f"Required artifact {artifact_key} is missing a content hash.")
    return None


def _iso_plus_seconds(base: str, seconds: int) -> str:
    if seconds <= 0:
        return ""
    parsed = datetime.fromisoformat(base)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return (parsed + timedelta(seconds=seconds)).isoformat()


def _iso_expired(value: str, *, reference: str) -> bool:
    if not value:
        return False
    expiry = datetime.fromisoformat(value)
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    ref = datetime.fromisoformat(reference)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    return expiry <= ref


__all__ = [
    name
    for name in globals()
    if name.startswith("protocol_")
    or name in {
        "migrate_protocol_document_data",
        "canonical_protocol_document",
        "validate_protocol_document",
        "normalize_protocol_document_format",
        "render_protocol_stage_prompt",
        "parse_protocol_stage_decision",
        "stage_target_for_decision",
        "is_protocol_terminal_target",
        "default_protocol_document_slug",
        "_iso_plus_seconds",
        "_iso_expired",
    }
]
