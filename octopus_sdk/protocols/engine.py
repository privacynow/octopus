"""Named SDK protocol engine for lifecycle evaluation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .core import (
    ProtocolArtifactRecord,
    ProtocolDefinitionDocumentRecord,
    ProtocolDispatchDecisionRecord,
    ProtocolEngineDecisionRecord,
    ProtocolOperatorAction,
    ProtocolParticipantResolutionRecord,
    ProtocolRunRecord,
    ProtocolStageExecutionRecord,
    ProtocolStageTaskResultRecord,
    TargetSelector,
    RegistryJsonRecord,
    _iso_expired,
    _iso_plus_seconds,
    is_protocol_terminal_target,
    parse_protocol_stage_decision,
    protocol_artifact_contract_error,
    protocol_review_edge_key,
    protocol_participant_session_key,
    protocol_retention_until,
    protocol_stage_internal_context,
    render_protocol_stage_prompt,
    stage_target_for_decision,
    utcnow_iso,
)
from octopus_sdk.registry.models import RoutedTaskRequest, normalized_requested_skills


class ProtocolRunEngine:
    """Pure protocol lifecycle evaluator used by the registry store."""

    def evaluate_dispatch_resolution(
        self,
        *,
        document: ProtocolDefinitionDocumentRecord,
        run: ProtocolRunRecord,
        stage_execution: ProtocolStageExecutionRecord,
        artifacts: Sequence[ProtocolArtifactRecord],
        previous_feedback: str,
        now: str,
        resolution: ProtocolParticipantResolutionRecord,
        timeout_at: str = "",
        lease_owner: str = "",
        lease_expires_at: str = "",
    ) -> ProtocolEngineDecisionRecord:
        stage = document.stage(stage_execution.stage_key)
        participant = document.participant(stage.participant_key)
        if not resolution.ok:
            return self.dispatch_resolution_failed(
                run=run,
                stage_execution=stage_execution,
                resolution=resolution,
            )
        request = self.build_dispatch_request(
            document=document,
            run=run,
            stage=stage,
            participant=participant,
            stage_execution_id=stage_execution.protocol_stage_execution_id,
            target_agent_id=resolution.resolved_agent_id,
            artifacts=artifacts,
            previous_feedback=previous_feedback,
            now=now,
        )
        return self.dispatch_started(
            run=run,
            stage_execution=stage_execution,
            routed_task_id=request.routed_task_id,
            timeout_at=timeout_at,
            lease_owner=lease_owner,
            lease_expires_at=lease_expires_at,
            selector=resolution.selector,
            resolved_agent_id=resolution.resolved_agent_id,
            resolved_authority_ref=resolution.resolved_authority_ref,
            now=now,
        ).model_copy(update={"routed_task_request": request})

    def dispatch_target_selector(
        self,
        *,
        run: ProtocolRunRecord,
        participant,
    ) -> TargetSelector:
        if run.is_rehearsal:
            return TargetSelector(kind="role", value="rehearsal")
        if participant.selector is not None:
            if participant.selector.kind == "skill" and not str(participant.selector.preferred_agent_id or "").strip():
                return participant.selector.model_copy(update={"preferred_agent_id": str(run.entry_agent_id or "").strip()})
            return participant.selector
        return TargetSelector(kind="agent", value=run.entry_agent_id)

    def build_dispatch_request(
        self,
        *,
        document: ProtocolDefinitionDocumentRecord,
        run: ProtocolRunRecord,
        stage,
        participant,
        stage_execution_id: str,
        target_agent_id: str,
        artifacts: Sequence[ProtocolArtifactRecord],
        previous_feedback: str,
        now: str,
    ) -> RoutedTaskRequest:
        routed_task_id = f"protocol-stage:{stage_execution_id}"
        instructions = render_protocol_stage_prompt(
            document=document,
            run=run,
            stage=stage,
            artifacts=list(artifacts),
            previous_feedback=previous_feedback,
        )
        return RoutedTaskRequest(
            routed_task_id=routed_task_id,
            parent_conversation_id=run.root_conversation_id,
            origin_transport_ref=str(run.root_conversation_id or ""),
            authorized_actor_key="",
            origin_agent_id=run.entry_agent_id,
            target_agent_id=str(target_agent_id or "").strip(),
            title=stage.display_name or stage.stage_key,
            instructions=instructions,
            context=RegistryJsonRecord.model_validate(
                {
                    "protocol_run_id": run.protocol_run_id,
                    "protocol_stage_execution_id": stage_execution_id,
                    "protocol_definition_version_id": run.protocol_definition_version_id,
                    "participant_key": participant.participant_key,
                    "stage_key": stage.stage_key,
                    "artifact_manifest": [item.model_dump(mode="json") for item in artifacts],
                }
            ),
            internal_context=protocol_stage_internal_context(
                document=document,
                run=run,
                stage_execution_id=stage_execution_id,
                stage=stage,
            ),
            constraints=run.constraints_json,
            requested_skills=normalized_requested_skills(selector=participant.selector),
            session_key_override=protocol_participant_session_key(run.protocol_run_id, participant.participant_key),
            project_id_override=run.workspace_ref,
            file_policy_override="edit" if stage.write_capable else "",
            priority="normal",
            created_at=now,
        )

    def dispatch_preflight(
        self,
        *,
        document: ProtocolDefinitionDocumentRecord,
        run: ProtocolRunRecord,
        stage,
        stage_executions: Sequence[ProtocolStageExecutionRecord],
        now: str,
        lease_owner: str,
        lease_ttl_seconds: int,
    ) -> ProtocolDispatchDecisionRecord:
        timeout_at = ""
        if stage.timeout_seconds > 0:
            timeout_at = _iso_plus_seconds(now, stage.timeout_seconds)
        if not stage.write_capable or not document.policies.single_active_writer:
            return ProtocolDispatchDecisionRecord(
                ok=True,
                timeout_at=timeout_at,
            )
        active_leases = [
            item
            for item in stage_executions
            if item.status == "running"
            and item.lease_owner
            and item.protocol_stage_execution_id != run.current_stage_execution_id
            and not _iso_expired(item.lease_expires_at, reference=now)
        ]
        if active_leases:
            active = active_leases[0]
            return ProtocolDispatchDecisionRecord(
                ok=False,
                error_code="LEASE_HELD",
                error_detail=f"Write lease held by stage execution {active.protocol_stage_execution_id}",
                timeout_at=timeout_at,
            )
        lease_expires_at = _iso_plus_seconds(now, lease_ttl_seconds) if lease_ttl_seconds > 0 else ""
        return ProtocolDispatchDecisionRecord(
            ok=True,
            lease_owner=lease_owner,
            lease_expires_at=lease_expires_at,
            timeout_at=timeout_at,
        )

    def dispatch_blocked(
        self,
        *,
        run: ProtocolRunRecord,
        stage_execution: ProtocolStageExecutionRecord,
        error_code: str,
        error_detail: str,
    ) -> ProtocolEngineDecisionRecord:
        retention_until = run.retention_until or protocol_retention_until(run.created_at or utcnow_iso())
        return ProtocolEngineDecisionRecord(
            run_status="blocked",
            stage_status="blocked",
            failure_code=str(error_code or "").strip().lower() or "lease_held",
            failure_detail=str(error_detail or "").strip() or "Protocol dispatch blocked.",
            transition_kind="blocked",
            transition_reason=str(error_detail or "").strip() or "Protocol dispatch blocked.",
            transition_error_code=str(error_code or "").strip().upper() or "LEASE_HELD",
            run_blocked_code=str(error_code or "").strip().lower() or "lease_held",
            run_blocked_detail=str(error_detail or "").strip() or "Protocol dispatch blocked.",
            participant_key=stage_execution.participant_key,
            retention_until=retention_until,
        )

    def dispatch_resolution_failed(
        self,
        *,
        run: ProtocolRunRecord,
        stage_execution: ProtocolStageExecutionRecord,
        resolution: ProtocolParticipantResolutionRecord,
    ) -> ProtocolEngineDecisionRecord:
        detail = str(resolution.reason or "").strip() or "Participant resolution failed."
        retention_until = run.retention_until or protocol_retention_until(run.created_at or utcnow_iso())
        return ProtocolEngineDecisionRecord(
            run_status="blocked",
            stage_status="blocked",
            failure_code="participant_resolution_failed",
            failure_detail=detail,
            transition_kind="blocked",
            transition_reason=detail,
            transition_error_code="PARTICIPANT_RESOLUTION_FAILED",
            run_blocked_code="participant_resolution_failed",
            run_blocked_detail=detail,
            participant_key=stage_execution.participant_key,
            participant_state="error",
            participant_resolution_outcome="error",
            participant_resolution_reason=detail,
            participant_selector_snapshot=RegistryJsonRecord.model_validate(resolution.selector.model_dump(mode="json")),
            transition_metadata=RegistryJsonRecord.model_validate(
                {"selector": resolution.selector.model_dump(mode="json")}
            ),
            retention_until=retention_until,
        )

    def dispatch_started(
        self,
        *,
        run: ProtocolRunRecord,
        stage_execution: ProtocolStageExecutionRecord,
        routed_task_id: str,
        timeout_at: str,
        lease_owner: str,
        lease_expires_at: str,
        selector: TargetSelector,
        resolved_agent_id: str,
        resolved_authority_ref: str,
        now: str,
    ) -> ProtocolEngineDecisionRecord:
        retention_until = run.retention_until or protocol_retention_until(run.created_at or now)
        return ProtocolEngineDecisionRecord(
            run_status="running",
            stage_status="running",
            transition_kind="dispatch",
            transition_reason=f"Dispatched stage {stage_execution.stage_key}.",
            routed_task_id=str(routed_task_id or "").strip(),
            timeout_at=str(timeout_at or "").strip(),
            lease_owner=str(lease_owner or "").strip(),
            lease_expires_at=str(lease_expires_at or "").strip(),
            started_at=str(now or "").strip(),
            participant_key=stage_execution.participant_key,
            participant_state="running",
            participant_resolution_outcome="ok",
            participant_resolution_reason="",
            participant_resolved_agent_id=str(resolved_agent_id or "").strip(),
            participant_resolved_authority_ref=str(resolved_authority_ref or "").strip(),
            participant_selector_snapshot=RegistryJsonRecord.model_validate(selector.model_dump(mode="json")),
            transition_metadata=RegistryJsonRecord.model_validate(
                {
                    "target_agent_id": str(resolved_agent_id or "").strip(),
                    "routed_task_id": str(routed_task_id or "").strip(),
                    "selector": selector.model_dump(mode="json"),
                }
            ),
            retention_until=retention_until,
        )

    def evaluate_stage_timeout(
        self,
        *,
        document: ProtocolDefinitionDocumentRecord,
        run: ProtocolRunRecord,
        stage_execution: ProtocolStageExecutionRecord,
        now: str,
    ) -> ProtocolEngineDecisionRecord:
        stage = document.stage(stage_execution.stage_key)
        detail = f"Stage {stage.stage_key} exceeded timeout."
        retention_until = run.retention_until or protocol_retention_until(run.created_at or now)
        return ProtocolEngineDecisionRecord(
            run_status="failed",
            stage_status="failed",
            failure_code="stage_timeout",
            failure_detail=detail,
            transition_kind="terminal",
            transition_reason=detail,
            transition_error_code="STAGE_TIMEOUT",
            terminal_status="failed",
            participant_key=stage_execution.participant_key,
            retention_until=retention_until,
        )

    def evaluate_task_result(
        self,
        *,
        document: ProtocolDefinitionDocumentRecord,
        run: ProtocolRunRecord,
        stage_execution: ProtocolStageExecutionRecord,
        stage_executions: Sequence[ProtocolStageExecutionRecord],
        result: ProtocolStageTaskResultRecord,
        review_edge_counts: Mapping[str, int] | None = None,
    ) -> ProtocolEngineDecisionRecord:
        review_edge_counts = dict(review_edge_counts or {})
        stage = document.stage(stage_execution.stage_key)
        if stage_execution.timeout_at and _iso_expired(stage_execution.timeout_at, reference=result.completed_at):
            return self.evaluate_stage_timeout(
                document=document,
                run=run,
                stage_execution=stage_execution,
                now=result.completed_at,
            )
        retention_until = run.retention_until or protocol_retention_until(run.created_at or result.completed_at)
        if result.status != "completed":
            detail = result.summary or result.status or "Stage failed"
            return ProtocolEngineDecisionRecord(
                run_status="failed",
                stage_status="failed",
                failure_code=result.status or "failed",
                failure_detail=detail,
                transition_kind="terminal",
                transition_reason=detail,
                transition_error_code=result.status.upper() if result.status else "TASK_FAILED",
                terminal_status="failed",
                retention_until=retention_until,
            )
        try:
            decision = parse_protocol_stage_decision(
                stage=stage,
                full_text=result.full_text,
                summary_fallback=result.summary,
            )
        except Exception as exc:
            detail = str(exc)
            return ProtocolEngineDecisionRecord(
                run_status="blocked",
                stage_status="blocked",
                failure_code="protocol_contract_invalid",
                failure_detail=detail,
                transition_kind="blocked",
                transition_reason=detail,
                transition_error_code="PROTOCOL_CONTRACT_INVALID",
                run_blocked_code="protocol_contract_invalid",
                run_blocked_detail=detail,
                retention_until=retention_until,
            )
        artifact_error = protocol_artifact_contract_error(
            document=document,
            stage=stage,
            observations=result.artifacts,
        )
        if artifact_error:
            return ProtocolEngineDecisionRecord(
                run_status="blocked",
                stage_status="blocked",
                decision=decision.decision,
                summary=decision.summary,
                failure_code=artifact_error[0],
                failure_detail=artifact_error[1],
                transition_kind="blocked",
                transition_reason=artifact_error[1],
                transition_error_code=artifact_error[0].upper(),
                run_blocked_code=artifact_error[0],
                run_blocked_detail=artifact_error[1],
                artifact_observations=list(result.artifacts),
                retention_until=retention_until,
            )
        transition_metadata = RegistryJsonRecord.model_validate(
            {
                "review_edge_key": "",
                "current_review_rounds": 0,
                "max_review_rounds": document.policies.max_review_rounds,
            }
        )
        target = stage_target_for_decision(stage, decision.decision)
        revise_edge_key = ""
        revise_count = 0
        if decision.decision == "revise":
            revise_edge_key = protocol_review_edge_key(stage.stage_key, target)
            revise_count = review_edge_counts.get(revise_edge_key, 0) + 1
            transition_metadata = RegistryJsonRecord.model_validate(
                {
                    "review_edge_key": revise_edge_key,
                    "current_review_rounds": revise_count,
                    "max_review_rounds": document.policies.max_review_rounds,
                }
            )
            if revise_count > document.policies.max_review_rounds:
                detail = (
                    f"Review edge {revise_edge_key or stage.stage_key} exceeded max review rounds "
                    f"({revise_count} > {document.policies.max_review_rounds})."
                )
                return ProtocolEngineDecisionRecord(
                    run_status="blocked",
                    stage_status="blocked",
                    decision=decision.decision,
                    summary=decision.summary,
                    failure_code="max_review_rounds_exceeded",
                    failure_detail=detail,
                    transition_kind="blocked",
                    transition_reason=detail,
                    transition_error_code="MAX_REVIEW_ROUNDS_EXCEEDED",
                    run_blocked_code="max_review_rounds_exceeded",
                    run_blocked_detail=detail,
                    artifact_observations=list(result.artifacts),
                    transition_metadata=transition_metadata,
                    retention_until=retention_until,
                )
        if not target:
            detail = f"Stage {stage.stage_key} has no transition for {decision.decision}"
            return ProtocolEngineDecisionRecord(
                run_status="blocked",
                stage_status="blocked",
                decision=decision.decision,
                summary=decision.summary,
                failure_code="protocol_invalid_transition",
                failure_detail=detail,
                transition_kind="blocked",
                transition_reason=detail,
                transition_error_code="PROTOCOL_INVALID_TRANSITION",
                run_blocked_code="protocol_invalid_transition",
                run_blocked_detail=detail,
                artifact_observations=list(result.artifacts),
                transition_metadata=transition_metadata,
                retention_until=retention_until,
            )
        if is_protocol_terminal_target(target):
            terminal_status = {
                "__complete__": "completed",
                "__failed__": "failed",
                "__cancelled__": "cancelled",
            }[target]
            return ProtocolEngineDecisionRecord(
                run_status=terminal_status,
                stage_status="completed",
                decision=decision.decision,
                summary=decision.summary,
                transition_kind="terminal",
                transition_reason=decision.summary,
                terminal_status=terminal_status,
                artifact_observations=list(result.artifacts),
                transition_metadata=transition_metadata,
                retention_until=retention_until,
            )
        return ProtocolEngineDecisionRecord(
            run_status="running",
            stage_status="completed",
            decision=decision.decision,
            summary=decision.summary,
            transition_kind="advance",
            transition_reason=decision.summary,
            next_stage_key=target,
            create_next_execution=True,
            artifact_observations=list(result.artifacts),
            transition_metadata=transition_metadata,
            input_snapshot=RegistryJsonRecord.model_validate(
                {
                    "previous_stage_key": stage.stage_key,
                    "previous_stage_execution_id": stage_execution.protocol_stage_execution_id,
                    "decision": decision.decision,
                    "decision_summary": decision.summary,
                }
            ),
            retention_until=retention_until,
        )

    def evaluate_operator_action(
        self,
        *,
        document: ProtocolDefinitionDocumentRecord,
        run: ProtocolRunRecord,
        stage_execution: ProtocolStageExecutionRecord,
        stage_executions: Sequence[ProtocolStageExecutionRecord],
        action: ProtocolOperatorAction,
        reason: str,
        now: str,
        review_edge_counts: Mapping[str, int] | None = None,
    ) -> ProtocolEngineDecisionRecord:
        del stage_executions
        review_edge_counts = dict(review_edge_counts or {})
        stage = document.stage(stage_execution.stage_key)
        summary = str(reason or "").strip() or f"Operator {action.replace('_', ' ')}."
        retention_until = run.retention_until or protocol_retention_until(run.created_at or now)
        transition_metadata = RegistryJsonRecord.model_validate(
            {
                "review_edge_key": "",
                "current_review_rounds": 0,
                "max_review_rounds": document.policies.max_review_rounds,
            }
        )
        if action == "cancel":
            return ProtocolEngineDecisionRecord(
                run_status="cancelled",
                stage_status="cancelled",
                summary=summary,
                transition_kind="terminal",
                transition_reason=summary,
                terminal_status="cancelled",
                transition_metadata=transition_metadata,
                retention_until=retention_until,
            )
        if action == "retry":
            if stage_execution.status not in {"blocked", "failed", "cancelled"}:
                detail = f"Stage {stage.stage_key} cannot be retried from status {stage_execution.status}."
                return ProtocolEngineDecisionRecord(
                    run_status="blocked",
                    stage_status=stage_execution.status,
                    failure_code="invalid_retry_state",
                    failure_detail=detail,
                    transition_kind="blocked",
                    transition_reason=detail,
                    transition_error_code="INVALID_RETRY_STATE",
                    run_blocked_code="invalid_retry_state",
                    run_blocked_detail=detail,
                    retention_until=retention_until,
                )
            return ProtocolEngineDecisionRecord(
                run_status="running",
                stage_status=stage_execution.status,
                summary=summary,
            transition_kind="retry",
            transition_reason=summary,
            next_stage_key=stage.stage_key,
            create_next_execution=True,
            input_snapshot=RegistryJsonRecord.model_validate(
                {
                    "previous_stage_key": stage.stage_key,
                        "previous_stage_execution_id": stage_execution.protocol_stage_execution_id,
                        "decision": "retry",
                        "decision_summary": summary,
                    }
                ),
                retention_until=retention_until,
            )
        forced_decision = "accept" if action == "accept" else "revise"
        allowed = set(stage.allowed_decisions())
        if forced_decision not in allowed:
            detail = f"Stage {stage.stage_key} does not allow operator decision {forced_decision!r}."
            return ProtocolEngineDecisionRecord(
                run_status="blocked",
                stage_status=stage_execution.status,
                failure_code="invalid_operator_decision",
                failure_detail=detail,
                transition_kind="blocked",
                transition_reason=detail,
                transition_error_code="INVALID_OPERATOR_DECISION",
                run_blocked_code="invalid_operator_decision",
                run_blocked_detail=detail,
                retention_until=retention_until,
            )
        target = stage_target_for_decision(stage, forced_decision)
        if forced_decision == "revise":
            revise_edge_key = protocol_review_edge_key(stage.stage_key, target)
            revise_count = review_edge_counts.get(revise_edge_key, 0) + 1
            transition_metadata = RegistryJsonRecord.model_validate(
                {
                    "review_edge_key": revise_edge_key,
                    "current_review_rounds": revise_count,
                    "max_review_rounds": document.policies.max_review_rounds,
                }
            )
            if revise_count > document.policies.max_review_rounds:
                detail = (
                    f"Review edge {revise_edge_key or stage.stage_key} exceeded max review rounds "
                    f"({revise_count} > {document.policies.max_review_rounds})."
                )
                return ProtocolEngineDecisionRecord(
                    run_status="blocked",
                    stage_status="blocked",
                    decision=forced_decision,
                    summary=summary,
                    failure_code="max_review_rounds_exceeded",
                    failure_detail=detail,
                    transition_kind="blocked",
                    transition_reason=detail,
                    transition_error_code="MAX_REVIEW_ROUNDS_EXCEEDED",
                    run_blocked_code="max_review_rounds_exceeded",
                    run_blocked_detail=detail,
                    transition_metadata=transition_metadata,
                    retention_until=retention_until,
                )
        if is_protocol_terminal_target(target):
            terminal_status = {
                "__complete__": "completed",
                "__failed__": "failed",
                "__cancelled__": "cancelled",
            }[target]
            return ProtocolEngineDecisionRecord(
                run_status=terminal_status,
                stage_status="completed",
                decision=forced_decision,
                summary=summary,
                transition_kind="terminal",
                transition_reason=summary,
                terminal_status=terminal_status,
                transition_metadata=transition_metadata,
                retention_until=retention_until,
            )
        return ProtocolEngineDecisionRecord(
            run_status="running",
            stage_status="completed",
            decision=forced_decision,
            summary=summary,
            transition_kind="advance",
            transition_reason=summary,
            next_stage_key=target,
            create_next_execution=True,
            transition_metadata=transition_metadata,
            input_snapshot=RegistryJsonRecord.model_validate(
                {
                    "previous_stage_key": stage.stage_key,
                    "previous_stage_execution_id": stage_execution.protocol_stage_execution_id,
                    "decision": forced_decision,
                    "decision_summary": summary,
                }
            ),
            retention_until=retention_until,
        )


DEFAULT_PROTOCOL_RUN_ENGINE = ProtocolRunEngine()
