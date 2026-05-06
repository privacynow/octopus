"""Tests for the registry management protocol and delivery persistence."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from octopus_registry.management_client import ManagementClientError, RegistryManagementClient
import octopus_registry.ingress as registry_ingress
from octopus_registry.store_postgres import RegistryPostgresStore
from octopus_sdk.registry.management import (
    ALL_MANAGEMENT_OPERATIONS,
    ArtifactRuntimeFetchRequest,
    ArtifactRuntimeFetchResult,
    ConversationSkillListingRecord,
    ConversationSkillStateResult,
    InstallCatalogSkillResult,
    ListCatalogSkillsRequest,
    ListCatalogSkillsResult,
    ManagementRequest,
    ManagementResult,
    ProviderGuidanceDetailResult,
    ProviderGuidanceLifecycleDetailRecord,
    RuntimeSkillCatalogItemRecord,
    StartArtifactRuntimeRequest,
    StartArtifactRuntimeResult,
    WorkspaceCleanupEntryRecord,
    WorkspaceCleanupPlanRecord,
    WorkspaceCleanupRequest,
    WorkspaceCleanupResult,
    WorkspaceUsageRequest,
    WorkspaceUsageResult,
)
from octopus_sdk.protocols import (
    ProtocolArtifactRuntimeActionResultRecord,
    ProtocolArtifactRuntimeEndpointRecord,
    ProtocolArtifactRuntimeManifestRecord,
)
from octopus_sdk.identity import conversation_key_for_ref

_FULL_MANAGEMENT_OPERATIONS = list(ALL_MANAGEMENT_OPERATIONS)


def _register_agent(
    store: RegistryPostgresStore,
    *,
    slug: str = "bot-under-test",
    connectivity_state: str = "connected",
    supported_admin_operations: list[str] | None = None,
) -> tuple[str, str]:
    advertised_supported_admin_operations = supported_admin_operations or list(_FULL_MANAGEMENT_OPERATIONS)
    enroll = store.enroll(
        {
            "bot_key": f"bot:{slug}",
            "display_name": slug.replace("-", " ").title(),
            "slug": slug,
            "role": "developer",
            "registry_scope": "full",
            "routing_skills": ["python"],
            "tags": ["backend"],
            "description": "Bot under test",
            "provider": "codex",
            "mode": "registry",
            "connectivity_state": connectivity_state,
            "transport_implementations": ["registry"],
            "supported_admin_operations": advertised_supported_admin_operations,
            "version": "test",
        }
    )
    store.register(
        enroll.agent_token,
        {
            "agent_card": {
                "bot_key": f"bot:{slug}",
                "display_name": slug.replace("-", " ").title(),
                "slug": slug,
                "role": "developer",
                "registry_scope": "full",
                "routing_skills": ["python"],
                "tags": ["backend"],
                "description": "Bot under test",
                "provider": "codex",
                "mode": "registry",
                "transport_implementations": ["registry"],
                "supported_admin_operations": advertised_supported_admin_operations,
                "version": "test",
            },
            "connectivity_state": connectivity_state,
            "current_capacity": 0,
            "max_capacity": 1,
        },
    )
    return enroll.agent_id, enroll.agent_token


def test_management_request_round_trip_polls_delivery_and_persists_result(postgres_db_url: str) -> None:
    store = RegistryPostgresStore(postgres_db_url)
    agent_id, agent_token = _register_agent(store)

    request = store.create_management_request(
        ManagementRequest(
            agent_id=agent_id,
            payload=ListCatalogSkillsRequest(query="github"),
            timeout_seconds=5,
        )
    )

    status = store.get_agent_status(agent_id)
    assert status is not None
    assert list(status.supported_admin_operations) == _FULL_MANAGEMENT_OPERATIONS

    polled = store.poll(agent_token, cursor=0, limit=10)
    assert len(polled.deliveries) == 1
    delivery = polled.deliveries[0]
    assert delivery.kind == "management_request"
    assert delivery.payload["request_id"] == request.request_id
    assert delivery.payload["payload"]["operation"] == "list_catalog_skills"

    reported = store.report_management_result(
        agent_token,
        request.request_id,
        ManagementResult(
            request_id=request.request_id,
            agent_id=agent_id,
            success=True,
            payload=ListCatalogSkillsResult(
                items=(
                    RuntimeSkillCatalogItemRecord(
                        name="github-integration",
                        display_name="GitHub Integration",
                        description="GitHub helper",
                        source_kind="builtin",
                        has_custom_override=False,
                        requires_credentials=True,
                        requirement_keys=["GITHUB_TOKEN"],
                        providers=["codex"],
                        can_activate=True,
                        can_update=False,
                        can_uninstall=False,
                        lifecycle_status="published",
                    ),
                ),
            ),
        ),
    )

    assert reported.success is True
    loaded = store.get_management_result(request.request_id)
    assert loaded is not None
    assert loaded.request_id == request.request_id
    assert loaded.payload is not None
    assert loaded.payload.operation == "list_catalog_skills"


def test_artifact_runtime_management_payloads_round_trip() -> None:
    manifest = ProtocolArtifactRuntimeManifestRecord(
        runtime_kind="java",
        start_command="mvn spring-boot:run",
        ui_path="/",
        health_path="/health",
        api_base_path="/api",
        endpoints=[
            ProtocolArtifactRuntimeEndpointRecord(label="API docs", path="/docs", endpoint_kind="docs"),
        ],
        smoke_test=["GET /health", "GET /docs"],
    )
    request = ManagementRequest(
        agent_id="agent-1",
        payload=StartArtifactRuntimeRequest(
            runtime_instance_id="runtime-1",
            protocol_run_id="run-1",
            artifact_key="risk_engine",
            artifact_path="/workspace/run/risk-engine",
            manifest=manifest,
        ),
    )

    decoded = ManagementRequest.model_validate(request.model_dump(mode="json"))

    assert decoded.payload.operation == "start_artifact_runtime"
    assert isinstance(decoded.payload, StartArtifactRuntimeRequest)
    assert decoded.payload.manifest.runtime_kind == "java"

    result = ManagementResult(
        request_id=request.request_id,
        agent_id="agent-1",
        success=True,
        payload=StartArtifactRuntimeResult(
            result=ProtocolArtifactRuntimeActionResultRecord(
                ok=True,
                status="running",
                message="started",
            )
        ),
    )
    decoded_result = ManagementResult.model_validate(result.model_dump(mode="json"))
    assert isinstance(decoded_result.payload, StartArtifactRuntimeResult)
    assert decoded_result.payload.result.status == "running"

    fetch = ManagementRequest(
        agent_id="agent-1",
        payload=ArtifactRuntimeFetchRequest(
            runtime_instance_id="runtime-1",
            protocol_run_id="run-1",
            artifact_key="risk_engine",
            path="/api/decisions",
        ),
    )
    decoded_fetch = ManagementRequest.model_validate(fetch.model_dump(mode="json"))
    assert isinstance(decoded_fetch.payload, ArtifactRuntimeFetchRequest)
    fetch_result = ManagementResult(
        request_id=fetch.request_id,
        agent_id="agent-1",
        success=True,
        payload=ArtifactRuntimeFetchResult(status_code=200, body_base64="e30="),
    )
    decoded_fetch_result = ManagementResult.model_validate(fetch_result.model_dump(mode="json"))
    assert isinstance(decoded_fetch_result.payload, ArtifactRuntimeFetchResult)


def test_workspace_cleanup_management_payloads_round_trip() -> None:
    usage = ManagementRequest(
        agent_id="agent-1",
        payload=WorkspaceUsageRequest(categories=["runtime_logs"], max_entries=10),
    )
    decoded_usage = ManagementRequest.model_validate(usage.model_dump(mode="json"))
    assert isinstance(decoded_usage.payload, WorkspaceUsageRequest)
    assert decoded_usage.payload.operation == "workspace_usage"

    plan = WorkspaceCleanupPlanRecord(
        agent_id="agent-1",
        categories=["runtime_logs"],
        entries=[
            WorkspaceCleanupEntryRecord(
                path="/tmp/octopus/artifact-runtimes/run-1",
                category="runtime_logs",
                size_bytes=120,
                file_count=2,
                safe_to_delete=True,
            )
        ],
        total_bytes=120,
        deletable_bytes=120,
        file_count=2,
    )
    usage_result = ManagementResult(
        request_id=usage.request_id,
        agent_id="agent-1",
        success=True,
        payload=WorkspaceUsageResult(plan=plan),
    )
    decoded_usage_result = ManagementResult.model_validate(usage_result.model_dump(mode="json"))
    assert isinstance(decoded_usage_result.payload, WorkspaceUsageResult)
    assert decoded_usage_result.payload.plan.deletable_bytes == 120

    cleanup = ManagementRequest(
        agent_id="agent-1",
        payload=WorkspaceCleanupRequest(plan=plan, confirm="CLEAN"),
    )
    decoded_cleanup = ManagementRequest.model_validate(cleanup.model_dump(mode="json"))
    assert isinstance(decoded_cleanup.payload, WorkspaceCleanupRequest)
    cleanup_result = ManagementResult(
        request_id=cleanup.request_id,
        agent_id="agent-1",
        success=True,
        payload=WorkspaceCleanupResult(
            plan=plan,
            removed_paths=["/tmp/octopus/artifact-runtimes/run-1"],
            removed_bytes=120,
        ),
    )
    decoded_cleanup_result = ManagementResult.model_validate(cleanup_result.model_dump(mode="json"))
    assert isinstance(decoded_cleanup_result.payload, WorkspaceCleanupResult)
    assert decoded_cleanup_result.payload.removed_bytes == 120


@pytest.mark.asyncio
async def test_registry_management_client_requires_connected_agent(postgres_db_url: str) -> None:
    store = RegistryPostgresStore(postgres_db_url)
    agent_id, _agent_token = _register_agent(store, connectivity_state="disconnected")

    client = RegistryManagementClient(store)
    with pytest.raises(ManagementClientError) as excinfo:
        await client.send(
            agent_id=agent_id,
            payload=ListCatalogSkillsRequest(query="github"),
        )

    assert excinfo.value.status_code == 503
    assert excinfo.value.error_code == "agent_not_connected"


@pytest.mark.asyncio
async def test_registry_management_client_requires_advertised_admin_operation(postgres_db_url: str) -> None:
    store = RegistryPostgresStore(postgres_db_url)
    agent_id, _agent_token = _register_agent(store, supported_admin_operations=["preview_provider_guidance"])

    client = RegistryManagementClient(store)
    with pytest.raises(ManagementClientError) as excinfo:
        await client.send(
            agent_id=agent_id,
            payload=ListCatalogSkillsRequest(query="github"),
    )

    assert excinfo.value.status_code == 409
    assert excinfo.value.error_code == "admin_operation_not_implemented"


@pytest.mark.asyncio
async def test_registry_management_client_times_out_without_result(postgres_db_url: str) -> None:
    store = RegistryPostgresStore(postgres_db_url)
    agent_id, _agent_token = _register_agent(store)

    client = RegistryManagementClient(store)
    with pytest.raises(ManagementClientError) as excinfo:
        await client.send(
            agent_id=agent_id,
            payload=ListCatalogSkillsRequest(query="github"),
            timeout_seconds=1,
        )

    assert excinfo.value.status_code == 504
    assert excinfo.value.error_code == "request_timeout"


@pytest.mark.asyncio
async def test_registry_ingress_conversation_skill_state_uses_origin_transport_key(
    tmp_path: Path,
    postgres_db_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del tmp_path
    store = RegistryPostgresStore(postgres_db_url)
    agent_id, _agent_token = _register_agent(store)
    conversation = store.create_conversation(
        target_agent_id=agent_id,
        origin_channel="telegram",
        external_conversation_ref="telegram:test-bot:12345",
        title="Managed conversation",
    )
    seen: dict[str, object] = {}

    class _StubClient:
        async def send(self, *, agent_id: str, payload, timeout_seconds: int = 30) -> ManagementResult:
            seen["agent_id"] = agent_id
            seen["payload"] = payload
            seen["timeout_seconds"] = timeout_seconds
            return ManagementResult(
                request_id="request-1",
                agent_id=agent_id,
                success=True,
                payload=ConversationSkillStateResult(
                    conversation_id=conversation.conversation_id,
                    conversation_key=str(payload.conversation_key),
                    listing=ConversationSkillListingRecord(),
                ),
            )

    monkeypatch.setattr(registry_ingress, "_client", lambda _store: _StubClient())

    result = await registry_ingress.conversation_skill_state(
        store,
        agent_id,
        conversation.conversation_id,
    )

    payload = seen["payload"]
    assert seen["agent_id"] == agent_id
    assert payload.conversation_id == conversation.conversation_id
    assert payload.conversation_key == conversation_key_for_ref("telegram:test-bot:12345")
    assert result["conversation_key"] == conversation_key_for_ref("telegram:test-bot:12345")


@pytest.mark.asyncio
async def test_registry_ingress_caches_management_reads_and_dedupes_inflight(
    tmp_path: Path,
    postgres_db_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry_ingress.reset_for_test()
    del tmp_path
    store = RegistryPostgresStore(postgres_db_url)
    agent_id, _agent_token = _register_agent(store)
    calls = {"count": 0}
    release = asyncio.Event()

    class _StubClient:
        async def send(self, *, agent_id: str, payload, timeout_seconds: int = 30) -> ManagementResult:
            calls["count"] += 1
            await release.wait()
            return ManagementResult(
                request_id="request-1",
                agent_id=agent_id,
                success=True,
                payload=ListCatalogSkillsResult(
                    items=(
                        RuntimeSkillCatalogItemRecord(
                            name="cached-skill",
                            display_name="Cached Skill",
                            description="cache hit",
                            source_kind="builtin",
                            has_custom_override=False,
                            requires_credentials=False,
                            requirement_keys=[],
                            providers=["codex"],
                            can_activate=True,
                            can_update=False,
                            can_uninstall=False,
                            lifecycle_status="published",
                        ),
                    ),
                ),
            )

    monkeypatch.setattr(registry_ingress, "_client", lambda _store: _StubClient())

    first = asyncio.create_task(registry_ingress.list_catalog_skills(store, agent_id))
    second = asyncio.create_task(registry_ingress.list_catalog_skills(store, agent_id))
    await asyncio.sleep(0)
    release.set()
    first_result, second_result = await asyncio.gather(first, second)
    third_result = await registry_ingress.list_catalog_skills(store, agent_id)

    assert calls["count"] == 1
    assert first_result["skills"][0]["name"] == "cached-skill"
    assert second_result["skills"][0]["name"] == "cached-skill"
    assert third_result["skills"][0]["name"] == "cached-skill"


@pytest.mark.asyncio
async def test_registry_ingress_invalidates_skill_cache_after_mutation(
    tmp_path: Path,
    postgres_db_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry_ingress.reset_for_test()
    del tmp_path
    store = RegistryPostgresStore(postgres_db_url)
    agent_id, _agent_token = _register_agent(store)
    calls: list[str] = []

    class _StubClient:
        async def send(self, *, agent_id: str, payload, timeout_seconds: int = 30) -> ManagementResult:
            operation = str(payload.operation)
            calls.append(operation)
            if operation == "list_catalog_skills":
                return ManagementResult(
                    request_id=f"request-{len(calls)}",
                    agent_id=agent_id,
                    success=True,
                    payload=ListCatalogSkillsResult(items=()),
                )
            return ManagementResult(
                request_id=f"request-{len(calls)}",
                agent_id=agent_id,
                success=True,
                payload=InstallCatalogSkillResult.model_validate(
                    {
                        "operation": "install_catalog_skill",
                        "result": {
                            "name": payload.skill_name,
                            "ok": True,
                            "message": "installed",
                            "prompt_size_warnings": [],
                        },
                    }
                ),
            )

    monkeypatch.setattr(registry_ingress, "_client", lambda _store: _StubClient())

    await registry_ingress.list_catalog_skills(store, agent_id)
    await registry_ingress.list_catalog_skills(store, agent_id)
    await registry_ingress.install_catalog_skill(store, agent_id, "cached-skill")
    await registry_ingress.list_catalog_skills(store, agent_id)

    assert calls == [
        "list_catalog_skills",
        "install_catalog_skill",
        "list_catalog_skills",
    ]


@pytest.mark.asyncio
async def test_registry_ingress_caches_guidance_detail_reads(
    tmp_path: Path,
    postgres_db_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry_ingress.reset_for_test()
    del tmp_path
    store = RegistryPostgresStore(postgres_db_url)
    agent_id, _agent_token = _register_agent(store)
    calls = {"count": 0}

    class _StubClient:
        async def send(self, *, agent_id: str, payload, timeout_seconds: int = 30) -> ManagementResult:
            calls["count"] += 1
            return ManagementResult(
                request_id=f"request-{calls['count']}",
                agent_id=agent_id,
                success=True,
                payload=ProviderGuidanceDetailResult(
                    detail=ProviderGuidanceLifecycleDetailRecord(
                        provider="codex",
                        scope_kind="system",
                        scope_key="",
                        draft_body="Be precise.",
                        published_body="Be precise.",
                        lifecycle_status="draft",
                        active_revision_id="rev-1",
                        published_revision_id="rev-1",
                        runtime_available=True,
                    ),
                ),
            )

    monkeypatch.setattr(registry_ingress, "_client", lambda _store: _StubClient())

    first = await registry_ingress.provider_guidance_detail(store, agent_id, "codex")
    second = await registry_ingress.provider_guidance_detail(store, agent_id, "codex")

    assert calls["count"] == 1
    assert first["draft_body"] == "Be precise."
    assert first["published_body"] == "Be precise."
    assert second["draft_body"] == "Be precise."
    assert second["published_body"] == "Be precise."
