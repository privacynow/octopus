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


def _coerce_mapping(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return {str(key): item for key, item in value.items()}
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="json")
        if isinstance(dumped, dict):
            return {str(key): item for key, item in dumped.items()}
    return {}


def _coerce_sequence(value: object) -> list[object]:
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    return []


def _coerce_string_list(value: object) -> list[str]:
    if isinstance(value, str):
        items = value.split(",")
    else:
        items = _coerce_sequence(value)
    return [str(item or "").strip() for item in items if str(item or "").strip()]


def _coerce_slug_list(value: object) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in _coerce_string_list(value):
        slug = item.lower().strip()
        if not slug or slug in seen:
            continue
        seen.add(slug)
        ordered.append(slug)
    return ordered


def _coerce_bool(value: object, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    token = str(value or "").strip().lower()
    if token in {"true", "1", "yes", "on"}:
        return True
    if token in {"false", "0", "no", "off"}:
        return False
    return default


def _coerce_int(value: object, *, default: int = 0, minimum: int = 0) -> int:
    try:
        parsed = int(value or default)
    except (TypeError, ValueError):
        parsed = default
    return max(parsed, minimum)


def _coerce_selector(value: object) -> dict[str, object] | None:
    raw = _coerce_mapping(value)
    if not raw:
        return None
    selector: dict[str, object] = {
        key: item
        for key, item in raw.items()
        if key not in {"kind", "value"}
    }
    kind = str(raw.get("kind", "") or "").strip()
    selector_value = str(raw.get("value", "") or "").strip()
    if kind:
        selector["kind"] = kind
    if selector_value:
        selector["value"] = selector_value
    return selector or None


def _participant_selector_from_source(raw: dict[str, object]) -> dict[str, object] | None:
    selector = _coerce_selector(raw.get("selector"))
    if selector is not None:
        return selector
    required_skills = _coerce_slug_list(raw.get("required_skills"))
    if required_skills:
        return {
            "kind": "skill",
            "value": required_skills[0],
        }
    return None


def _stage_selector_from_source(
    raw_stage: dict[str, object],
    *,
    participant_selectors: dict[str, dict[str, object] | None] | None = None,
) -> dict[str, object] | None:
    selector = _coerce_selector(raw_stage.get("selector"))
    if selector is not None:
        return selector
    participant_key = str(raw_stage.get("participant_key", "") or "").strip()
    if not participant_key:
        return None
    inherited = dict((participant_selectors or {}).get(participant_key) or {})
    return inherited or None


def _source_selector_parts(raw: dict[str, object]) -> tuple[bool, str, str]:
    selector = _coerce_mapping(raw.get("selector"))
    if not selector:
        return False, "", ""
    return (
        True,
        str(selector.get("kind", "") or "").strip().lower(),
        str(selector.get("value", "") or "").strip(),
    )


def _normalized_participant_records(items: Sequence[object]) -> list[dict[str, object]]:
    participants: list[dict[str, object]] = []
    for item in items:
        raw = _coerce_mapping(item)
        participants.append({
            "participant_key": str(raw.get("participant_key", "") or "").strip(),
            "display_name": str(raw.get("display_name", "") or "").strip(),
            "instructions": str(raw.get("instructions", "") or ""),
        })
    return participants


def draft_protocol_document_data(value: object) -> dict[str, object]:
    migrated = migrate_protocol_document_data(value)
    metadata = _coerce_mapping(migrated.get("metadata"))
    metadata["slug"] = str(metadata.get("slug", "") or "").strip()
    metadata["display_name"] = str(metadata.get("display_name", "") or "").strip()
    metadata["description"] = str(metadata.get("description", "") or "").strip()

    participant_sources = [_coerce_mapping(item) for item in _coerce_sequence(migrated.get("participants"))]
    participants = _normalized_participant_records(participant_sources)
    participant_selectors = {
        str(item.get("participant_key", "") or "").strip(): _participant_selector_from_source(item)
        for item in participant_sources
    }

    artifacts: list[dict[str, object]] = []
    for item in _coerce_sequence(migrated.get("artifacts")):
        raw = _coerce_mapping(item)
        artifacts.append({
            "artifact_key": str(raw.get("artifact_key", "") or "").strip(),
            "display_name": str(raw.get("display_name", "") or "").strip(),
            "description": str(raw.get("description", "") or ""),
            "kind": str(raw.get("kind", "") or "workspace_file").strip() or "workspace_file",
            "path": str(raw.get("path", "") or "").strip(),
            "verify": _coerce_bool(raw.get("verify"), default=True),
        })

    stages: list[dict[str, object]] = []
    for item in _coerce_sequence(migrated.get("stages")):
        raw = _coerce_mapping(item)
        transitions = {
            str(decision or "").strip(): str(target or "").strip()
            for decision, target in _coerce_mapping(raw.get("transitions")).items()
        }
        outputs = _coerce_string_list(raw.get("outputs"))
        stages.append({
            "stage_key": str(raw.get("stage_key", "") or "").strip(),
            "display_name": str(raw.get("display_name", "") or "").strip(),
            "participant_key": str(raw.get("participant_key", "") or "").strip(),
            "selector": _stage_selector_from_source(raw, participant_selectors=participant_selectors),
            "stage_kind": str(raw.get("stage_kind", "") or "work").strip() or "work",
            "instructions": str(raw.get("instructions", "") or ""),
            "inputs": _coerce_string_list(raw.get("inputs")),
            "outputs": outputs,
            "transitions": transitions,
            "write_capable": _coerce_bool(raw.get("write_capable"), default=bool(outputs)),
            "max_rounds": _coerce_int(raw.get("max_rounds"), default=0, minimum=0),
            "strict_completion": _coerce_bool(raw.get("strict_completion"), default=False),
            "require_output_verification": None if raw.get("require_output_verification", None) is None else _coerce_bool(raw.get("require_output_verification"), default=False),
            "timeout_seconds": _coerce_int(raw.get("timeout_seconds"), default=0, minimum=0),
        })

    policies = _coerce_mapping(migrated.get("policies"))
    return {
        "schema_version": _coerce_int(migrated.get("schema_version"), default=PROTOCOL_SCHEMA_VERSION, minimum=PROTOCOL_MIN_SCHEMA_VERSION),
        "metadata": metadata,
        "participants": participants,
        "artifacts": artifacts,
        "stages": stages,
        "policies": {
            "single_active_writer": _coerce_bool(policies.get("single_active_writer"), default=True),
            "max_review_rounds": _coerce_int(policies.get("max_review_rounds"), default=5, minimum=1),
        },
    }


def _validation_issue(
    code: str,
    message: str,
    *,
    section: str,
    entity_kind: str = "",
    entity_key: str = "",
    path: str = "",
    blocking: bool = True,
) -> ProtocolValidationIssueRecord:
    return ProtocolValidationIssueRecord(
        code=code,
        message=message,
        section=section,
        entity_kind=entity_kind,
        entity_key=entity_key,
        path=path,
        blocking=blocking,
    )


def _draft_validation_issues(
    document: dict[str, object],
    *,
    source_document: dict[str, object] | None = None,
) -> list[ProtocolValidationIssueRecord]:
    issues: list[ProtocolValidationIssueRecord] = []
    metadata = _coerce_mapping(document.get("metadata"))
    participants = [_coerce_mapping(item) for item in _coerce_sequence(document.get("participants"))]
    source_participants = [_coerce_mapping(item) for item in _coerce_sequence((source_document or document).get("participants"))]
    artifacts = [_coerce_mapping(item) for item in _coerce_sequence(document.get("artifacts"))]
    stages = [_coerce_mapping(item) for item in _coerce_sequence(document.get("stages"))]
    source_stages = [_coerce_mapping(item) for item in _coerce_sequence((source_document or document).get("stages"))]

    if not str(metadata.get("slug", "") or "").strip():
        issues.append(_validation_issue(
            "metadata.slug_required",
            "Add a protocol slug before review or publish.",
            section="overview",
            path="metadata.slug",
        ))

    participant_keys = [str(item.get("participant_key", "") or "").strip() for item in participants]
    artifact_keys = [str(item.get("artifact_key", "") or "").strip() for item in artifacts]
    stage_keys = [str(item.get("stage_key", "") or "").strip() for item in stages]

    if not participants:
        issues.append(_validation_issue(
            "participants.required",
            "Add at least one participant before defining workflow stages.",
            section="participants",
            path="participants",
        ))
    if not stages:
        issues.append(_validation_issue(
            "stages.required",
            "Add at least one stage before review or publish.",
            section="stages",
            path="stages",
        ))

    for values, entity_kind, section in (
        (participant_keys, "participant", "participants"),
        (artifact_keys, "artifact", "artifacts"),
        (stage_keys, "stage", "stages"),
    ):
        seen: set[str] = set()
        for index, key in enumerate(values):
            if not key:
                issues.append(_validation_issue(
                    f"{entity_kind}.key_required",
                    f"Each {entity_kind} needs a key.",
                    section=section,
                    entity_kind=entity_kind,
                    path=f"{section}.{index}",
                ))
                continue
            if key in seen:
                issues.append(_validation_issue(
                    f"{entity_kind}.key_duplicate",
                    f"{entity_kind.capitalize()} key {key} is duplicated.",
                    section=section,
                    entity_kind=entity_kind,
                    entity_key=key,
                    path=f"{section}.{index}",
                ))
                continue
            seen.add(key)

    participant_set = {item for item in participant_keys if item}
    artifact_set = {item for item in artifact_keys if item}
    stage_set = {item for item in stage_keys if item}
    participant_selector_sources = {
        str(item.get("participant_key", "") or "").strip(): _participant_selector_from_source(item)
        for item in source_participants
    }
    participant_raw_sources = {
        str(item.get("participant_key", "") or "").strip(): item
        for item in source_participants
    }

    for index, participant in enumerate(participants):
        participant_key = str(participant.get("participant_key", "") or "").strip()
        participant_label = participant_key or f"participant {index + 1}"
        source_participant = participant_raw_sources.get(participant_key) or (source_participants[index] if index < len(source_participants) else participant)
        required_skills = _coerce_slug_list(source_participant.get("required_skills"))
        has_raw_selector, _, _ = _source_selector_parts(source_participant)

        if not has_raw_selector and len(required_skills) > 1:
            issues.append(_validation_issue(
                "participant.legacy_multi_skill",
                f"{participant_label} declares multiple legacy skills. Only the first skill can be migrated into one assignment rule.",
                section="participants",
                entity_kind="participant",
                entity_key=participant_key,
                path=f"participants.{index}.required_skills",
                blocking=False,
            ))

    for index, artifact in enumerate(artifacts):
        artifact_key = str(artifact.get("artifact_key", "") or "").strip()
        if str(artifact.get("kind", "") or "").strip() == "workspace_file" and not str(artifact.get("path", "") or "").strip():
            issues.append(_validation_issue(
                "artifact.path_required",
                f"Artifact {artifact_key or index + 1} needs a workspace path.",
                section="artifacts",
                entity_kind="artifact",
                entity_key=artifact_key,
                path=f"artifacts.{index}.path",
            ))

    for index, stage in enumerate(stages):
        stage_key = str(stage.get("stage_key", "") or "").strip()
        participant_key = str(stage.get("participant_key", "") or "").strip()
        stage_label = stage_key or f"stage {index + 1}"
        source_stage = source_stages[index] if index < len(source_stages) else stage
        has_raw_selector, selector_kind, selector_value = _source_selector_parts(source_stage)
        effective_selector = _stage_selector_from_source(source_stage, participant_selectors=participant_selector_sources)
        if not participant_key:
            issues.append(_validation_issue(
                "stage.participant_required",
                f"Assign a participant to {stage_label}.",
                section="stages",
                entity_kind="stage",
                entity_key=stage_key,
                path=f"stages.{index}.participant_key",
            ))
        elif participant_key not in participant_set:
            issues.append(_validation_issue(
                "stage.participant_missing",
                f"{stage_label} references participant {participant_key}, which does not exist yet.",
                section="stages",
                entity_kind="stage",
                entity_key=stage_key,
                path=f"stages.{index}.participant_key",
            ))
        if has_raw_selector and not selector_kind:
            issues.append(_validation_issue(
                "stage.selector_kind_required",
                f"Add an assignment strategy for {stage_label}.",
                section="stages",
                entity_kind="stage",
                entity_key=stage_key,
                path=f"stages.{index}.selector.kind",
            ))
        elif selector_kind and selector_kind not in PROTOCOL_SELECTOR_KIND_OPTIONS:
            issues.append(_validation_issue(
                "stage.selector_kind_invalid",
                f"{stage_label} uses unsupported assignment strategy {selector_kind!r}.",
                section="stages",
                entity_kind="stage",
                entity_key=stage_key,
                path=f"stages.{index}.selector.kind",
            ))
        if has_raw_selector and not selector_value:
            issues.append(_validation_issue(
                "stage.selector_value_required",
                f"Add an assignment value for {stage_label}.",
                section="stages",
                entity_kind="stage",
                entity_key=stage_key,
                path=f"stages.{index}.selector.value",
            ))
        if effective_selector is None and not has_raw_selector:
            issues.append(_validation_issue(
                "stage.selector_required",
                f"Add an assignment rule for {stage_label} before review or publish.",
                section="stages",
                entity_kind="stage",
                entity_key=stage_key,
                path=f"stages.{index}.selector",
            ))
        for artifact_key in [*(_coerce_sequence(stage.get("inputs"))), *(_coerce_sequence(stage.get("outputs")))]:
            normalized_key = str(artifact_key or "").strip()
            if normalized_key and normalized_key not in artifact_set:
                issues.append(_validation_issue(
                    "stage.artifact_missing",
                    f"{stage_label} references artifact {normalized_key}, which does not exist yet.",
                    section="stages",
                    entity_kind="stage",
                    entity_key=stage_key,
                    path=f"stages.{index}",
                ))
        transitions = _coerce_mapping(stage.get("transitions"))
        stage_kind = str(stage.get("stage_kind", "") or "work").strip() or "work"
        if stage_kind != "work" and not transitions:
            issues.append(_validation_issue(
                "stage.transitions_required",
                f"{stage_label} needs at least one transition.",
                section="stages",
                entity_kind="stage",
                entity_key=stage_key,
                path=f"stages.{index}.transitions",
            ))
        for decision, target in transitions.items():
            decision_key = str(decision or "").strip().lower()
            target_key = str(target or "").strip()
            if not decision_key:
                issues.append(_validation_issue(
                    "stage.transition_decision_required",
                    f"{stage_label} has a transition with no decision label.",
                    section="stages",
                    entity_kind="stage",
                    entity_key=stage_key,
                    path=f"stages.{index}.transitions",
                ))
                continue
            if not target_key:
                issues.append(_validation_issue(
                    "stage.transition_target_required",
                    f"{stage_label} transition {decision_key} needs a target.",
                    section="stages",
                    entity_kind="stage",
                    entity_key=stage_key,
                    path=f"stages.{index}.transitions.{decision_key}",
                ))
                continue
            if target_key not in stage_set and target_key not in _TERMINAL_STAGE_TARGETS:
                issues.append(_validation_issue(
                    "stage.transition_target_missing",
                    f"{stage_label} transition {decision_key} points to {target_key}, which does not exist.",
                    section="stages",
                    entity_kind="stage",
                    entity_key=stage_key,
                    path=f"stages.{index}.transitions.{decision_key}",
                ))
    return issues


def _next_required_actions(issues: Sequence[ProtocolValidationIssueRecord]) -> list[str]:
    actions: list[str] = []
    for issue in issues:
        if issue.code == "metadata.slug_required" and "overview.complete_slug" not in actions:
            actions.append("overview.complete_slug")
        elif issue.code == "participants.required" and "participants.add_first" not in actions:
            actions.append("participants.add_first")
        elif issue.code == "stages.required" and "stages.add_first" not in actions:
            actions.append("stages.add_first")
        elif issue.code.startswith("stage.selector_") and "stages.assign_selector" not in actions:
            actions.append("stages.assign_selector")
        elif issue.code in {"stage.participant_required", "stage.participant_missing"} and "stages.assign_participant" not in actions:
            actions.append("stages.assign_participant")
    return actions

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
    return ProtocolDefinitionDocumentRecord.model_validate(draft_protocol_document_data(value))


def protocol_definition_content_hash(document: ProtocolDefinitionDocumentRecord) -> str:
    payload = json.dumps(document.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_protocol_document(
    value: object,
    *,
    mode: ProtocolValidationMode = "strict",
) -> ProtocolValidationResultRecord:
    try:
        migrated = migrate_protocol_document_data(value)
    except Exception as exc:
        migrated = {}
        if mode == "strict":
            return ProtocolValidationResultRecord(mode="strict", ok=False, errors=[str(exc)])
    if mode == "draft":
        try:
            document = draft_protocol_document_data(migrated or value)
        except Exception as exc:
            return ProtocolValidationResultRecord(mode="draft", ok=False, errors=[str(exc)])
        issues = _draft_validation_issues(document, source_document=migrated or document)
        blocking = [item for item in issues if item.blocking]
        payload = json.dumps(document, sort_keys=True, separators=(",", ":"))
        return ProtocolValidationResultRecord(
            mode="draft",
            ok=not blocking,
            errors=[item.message for item in blocking],
            issues=issues,
            next_required_actions=_next_required_actions(blocking or issues),
            normalized_document=None,
            content_hash=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        )
    try:
        draft_document = draft_protocol_document_data(migrated or value)
    except Exception as exc:
        try:
            draft_document = draft_protocol_document_data(migrated or value)
        except Exception:
            return ProtocolValidationResultRecord(mode="strict", ok=False, errors=[str(exc)])
        issues = _draft_validation_issues(draft_document, source_document=migrated or draft_document)
        if issues:
            return ProtocolValidationResultRecord(
                mode="strict",
                ok=False,
                errors=[item.message for item in issues if item.blocking],
                issues=issues,
                next_required_actions=_next_required_actions(issues),
            )
        return ProtocolValidationResultRecord(mode="strict", ok=False, errors=[str(exc)])
    issues = _draft_validation_issues(draft_document, source_document=migrated or draft_document)
    blocking = [item for item in issues if item.blocking]
    if blocking:
        return ProtocolValidationResultRecord(
            mode="strict",
            ok=False,
            errors=[item.message for item in blocking],
            issues=issues,
            next_required_actions=_next_required_actions(blocking),
        )
    try:
        document = ProtocolDefinitionDocumentRecord.model_validate(draft_document)
    except Exception as exc:
        return ProtocolValidationResultRecord(
            mode="strict",
            ok=False,
            errors=[str(exc)],
            issues=issues,
            next_required_actions=_next_required_actions(issues),
        )
    return ProtocolValidationResultRecord(
        mode="strict",
        ok=True,
        errors=[],
        issues=issues,
        next_required_actions=_next_required_actions(issues),
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


def protocol_document_from_text(
    text: str,
    *,
    format: ProtocolDocumentTextFormat = "json",
    mode: ProtocolValidationMode = "strict",
) -> ProtocolDefinitionDocumentRecord | dict[str, object]:
    normalized = normalize_protocol_document_format(format)
    source = str(text or "").strip()
    if not source:
        raise ValueError("Protocol document text must not be empty")
    try:
        loaded = json.loads(source) if normalized == "json" else yaml.safe_load(source)
    except Exception as exc:
        raise ValueError(f"Protocol {normalized} parse failed: {exc}") from exc
    if mode == "draft":
        return draft_protocol_document_data(loaded)
    return canonical_protocol_document(loaded)


def protocol_document_to_text(
    value: object,
    *,
    format: ProtocolDocumentTextFormat = "json",
    mode: ProtocolValidationMode = "strict",
) -> str:
    normalized = normalize_protocol_document_format(format)
    if mode == "draft":
        payload = draft_protocol_document_data(value)
    else:
        payload = canonical_protocol_document(value).model_dump(mode="json")
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
    mode: ProtocolValidationMode = "strict",
) -> str:
    left_text = protocol_document_to_text(left, format=format, mode=mode).splitlines()
    right_text = protocol_document_to_text(right, format=format, mode=mode).splitlines()
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
