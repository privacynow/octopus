from octopus_sdk.protocols import ProtocolService
from octopus_sdk.protocols.models import (
    ProtocolArtifactRecord,
    ProtocolDefinitionRecord,
    ProtocolDefinitionVersionRecord,
    ProtocolRunDetailRecord,
    ProtocolRunMutationRecord,
    ProtocolRunRecord,
)


def _protocol(**overrides):
    base = {
        "protocol_id": "protocol-1",
        "slug": "software-engineering",
        "display_name": "Software Engineering",
        "lifecycle_state": "published",
        "current_version_id": "version-1",
    }
    base.update(overrides)
    return ProtocolDefinitionRecord.model_validate(base)


def _run_detail(**overrides):
    run_payload = {
        "protocol_run_id": "run-1",
        "protocol_id": "protocol-1",
        "protocol_definition_version_id": "version-1",
        "entry_agent_id": "agent-1",
        "root_conversation_id": "conv-1",
        "origin_channel": "telegram",
        "workspace_ref": "",
        "run_org_id": "local",
        "status": "running",
        "problem_statement": "Build the feature",
        "constraints_json": {},
        "current_stage_key": "planning",
        "version": 1,
    }
    run_payload.update(overrides)
    return ProtocolRunDetailRecord(
        run=ProtocolRunRecord.model_validate(run_payload),
        definition=_protocol(),
        version=ProtocolDefinitionVersionRecord.model_validate(
            {
                "protocol_definition_version_id": "version-1",
                "protocol_id": "protocol-1",
                "version": 1,
            }
        ),
        artifacts=[
            ProtocolArtifactRecord.model_validate(
                {
                    "protocol_artifact_id": "artifact-1",
                    "protocol_run_id": "run-1",
                    "artifact_key": "plan",
                    "workspace_path": "plan.md",
                    "exists": True,
                    "verification_state": "verified",
                }
            )
        ],
    )


class _Registry:
    def __init__(self):
        self.invocations = []
        self.actions = []

    async def list_protocols(self, **kwargs):
        return [
            _protocol(),
            _protocol(
                protocol_id="draft-1",
                slug="draft",
                lifecycle_state="draft",
                current_version_id="",
            ),
        ]

    async def invoke_protocol(self, payload, *, idempotency_key="", origin=""):
        self.invocations.append((payload, idempotency_key, origin))
        return ProtocolRunMutationRecord.model_validate(
            {
                "ok": True,
                "status": "created",
                "run": {
                    "protocol_run_id": "run-1",
                    "protocol_id": payload.protocol_id,
                    "protocol_definition_version_id": "version-1",
                    "entry_agent_id": payload.entry_agent_id,
                    "root_conversation_id": payload.root_conversation_id,
                    "origin_channel": payload.origin_channel,
                    "workspace_ref": payload.workspace_ref,
                    "run_org_id": "local",
                    "status": "running",
                    "problem_statement": payload.problem_statement,
                    "constraints_json": {},
                    "current_stage_key": "planning",
                    "version": 1,
                },
            }
        )

    async def get_run(self, run_id):
        assert run_id == "run-1"
        return _run_detail()

    async def list_run_artifacts(self, run_id):
        return (await self.get_run(run_id)).artifacts

    async def get_run_artifact_content(self, run_id, artifact_key, *, download=False):
        assert run_id == "run-1"
        assert artifact_key == "plan"
        assert download is True
        return b"# Plan\n"

    async def act_on_protocol_run(self, run_id, *, action, reason="", idempotency_key="", expected_version=None):
        self.actions.append((run_id, action, reason, idempotency_key, expected_version))
        return ProtocolRunMutationRecord.model_validate(
            {
                "ok": True,
                "status": "updated",
                "run": {
                    **_run_detail().run.model_dump(mode="json"),
                    "status": "cancelled",
                    "version": 2,
                },
            }
        )

    async def export_run(self, run_id):
        return _run_detail()


async def test_protocol_service_lists_only_launchable_protocols():
    service = ProtocolService(_Registry())

    rows = await service.list_launchable()

    assert [item.slug for item in rows] == ["software-engineering"]


async def test_protocol_service_launches_from_conversation_through_registry_client():
    registry = _Registry()
    service = ProtocolService(registry)

    result = await service.launch_from_conversation(
        {
            "protocol_ref": "software-engineering",
            "entry_agent_id": "agent-1",
            "root_conversation_id": "conv-1",
            "origin_channel": "telegram",
            "problem_statement": "Build the feature",
        },
        idempotency_key="idem-1",
        origin="telegram",
    )

    assert result.mutation.run is not None
    assert result.mutation.run.protocol_run_id == "run-1"
    assert registry.invocations[0][1:] == ("idem-1", "telegram")


async def test_protocol_service_observes_artifacts_and_controls_runs():
    registry = _Registry()
    service = ProtocolService(registry)

    detail = await service.get_run_status("run-1")
    artifacts = await service.list_run_artifacts("run-1")
    result = await service.act_on_run(
        "run-1",
        action="cancel",
        reason="wrong output",
        idempotency_key="idem-2",
        expected_version=1,
    )

    assert detail.run.protocol_run_id == "run-1"
    assert artifacts[0].artifact_key == "plan"
    assert result.run is not None
    assert result.run.status == "cancelled"
    assert registry.actions == [("run-1", "cancel", "wrong output", "idem-2", 1)]


async def test_protocol_service_downloads_artifact_content_through_shared_port():
    service = ProtocolService(_Registry())

    content = await service.get_run_artifact_content("run-1", "plan", download=True)

    assert content == b"# Plan\n"
