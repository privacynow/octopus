from __future__ import annotations

from octopus_sdk.agent_awareness import (
    AgentAwarenessRequestRecord,
    AgentToolCapabilityRecord,
    ProtocolAgentAwarenessService,
)
from octopus_sdk.protocols.models import (
    ProtocolArtifactRecord,
    ProtocolArtifactRuntimeInstanceRecord,
    ProtocolDefinitionRecord,
    ProtocolDefinitionVersionRecord,
    ProtocolRunDetailRecord,
    ProtocolRunRecord,
    ProtocolStageExecutionRecord,
)


class _AwarenessSource:
    async def list_launchable(self, *, cursor: int = 0, limit: int = 100):
        del cursor, limit
        return [
            ProtocolDefinitionRecord(
                protocol_id="protocol-risk",
                slug="risk-engine",
                display_name="Payments Risk Engine",
                description="Build and operate a risk decision system.",
                lifecycle_state="published",
                current_version_id="version-risk-1",
            )
        ]

    async def list_runs(self, **kwargs):
        del kwargs
        return [
            ProtocolRunRecord(
                protocol_run_id="run-risk-123456",
                protocol_id="protocol-risk",
                status="completed",
                current_stage_key="final_acceptance",
                problem_statement="Build a Java risk engine with UI and APIs.",
                origin_channel="telegram",
                workspace_ref="workspace",
            )
        ]

    async def get_run_status(self, run_id: str):
        assert run_id == "run-risk-123456"
        return ProtocolRunDetailRecord(
            run=(await self.list_runs())[0],
            definition=(await self.list_launchable())[0],
            version=ProtocolDefinitionVersionRecord(
                protocol_definition_version_id="version-risk-1",
                protocol_id="protocol-risk",
                version=1,
            ),
            stage_executions=[
                ProtocolStageExecutionRecord(
                    protocol_stage_execution_id="stage-1",
                    protocol_run_id=run_id,
                    stage_key="final_review",
                    status="completed",
                    decision="accept",
                    decision_summary="Runtime smoke evidence passed for the primary API and UI.",
                    attempt=2,
                )
            ],
            artifacts=[
                ProtocolArtifactRecord(
                    protocol_artifact_id="artifact-outcome",
                    protocol_run_id=run_id,
                    artifact_key="primary_outcome",
                    workspace_path="protocol/auto/run-risk/output",
                    exists=True,
                    verification_state="verified",
                    size_bytes=4096,
                )
            ],
            runtime_instances=[
                ProtocolArtifactRuntimeInstanceRecord(
                    runtime_instance_id="runtime-1",
                    protocol_run_id=run_id,
                    artifact_key="primary_outcome",
                    status="running",
                    ui_url="/runtime/protocol-runs/run-risk-123456/artifacts/primary_outcome/app",
                    api_url="/runtime/protocol-runs/run-risk-123456/artifacts/primary_outcome/api",
                    health_url="/runtime/protocol-runs/run-risk-123456/artifacts/primary_outcome/api/health",
                )
            ],
        )


async def test_agent_awareness_renders_protocols_runs_artifacts_and_telegram_actions():
    service = ProtocolAgentAwarenessService(_AwarenessSource())

    awareness = await service.build_awareness(
        AgentAwarenessRequestRecord(
            origin_channel="telegram",
            agent_slug="m2",
            agent_display_name="M2",
            provider_name="codex",
            working_dir="/workspace/workspace",
            workspace_ref="workspace",
            file_policy="edit",
            active_skills=["risk-analysis"],
            available_skills=["risk-analysis", "java-builds"],
            tool_capabilities=[
                AgentToolCapabilityRecord(
                    name="sudo",
                    available=True,
                    path="/usr/bin/sudo",
                    detail="passwordless root inside the bot container",
                )
            ],
        )
    )

    prompt = awareness.to_prompt_block()

    assert "Octopus Agent Awareness" in prompt
    assert "Payments Risk Engine" in prompt
    assert "run-risk" in prompt
    assert "primary_outcome" in prompt
    assert "final_review" in prompt
    assert "Runtime smoke evidence passed" in prompt
    assert "Runtimes: primary_outcome (running)" in prompt
    assert "passwordless root inside the bot container" in prompt
    assert "/protocol improve-run" in prompt
