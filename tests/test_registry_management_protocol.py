"""Tests for the registry management protocol and delivery persistence."""

from __future__ import annotations

from pathlib import Path

import pytest

from octopus_registry.management_client import ManagementClientError, RegistryManagementClient
import octopus_registry.ingress as registry_ingress
from octopus_registry.store import RegistrySQLiteStore
from octopus_sdk.registry.management import (
    ConversationSkillListingRecord,
    ConversationSkillStateResult,
    ListCatalogSkillsRequest,
    ListCatalogSkillsResult,
    ManagementRequest,
    ManagementResult,
    RuntimeSkillCatalogItemRecord,
)
from octopus_sdk.identity import conversation_key_for_ref

_FULL_MANAGEMENT_CAPABILITIES = [
    "skill_catalog",
    "skill_lifecycle",
    "provider_guidance",
    "conversation_skills",
]


def _register_agent(
    store: RegistrySQLiteStore,
    *,
    slug: str = "bot-under-test",
    connectivity_state: str = "connected",
    management_capabilities: list[str] | None = None,
) -> tuple[str, str]:
    advertised_management_capabilities = management_capabilities or list(_FULL_MANAGEMENT_CAPABILITIES)
    enroll = store.enroll(
        {
            "bot_key": f"bot:{slug}",
            "display_name": slug.replace("-", " ").title(),
            "slug": slug,
            "role": "developer",
            "registry_scope": "full",
            "capabilities": ["python"],
            "tags": ["backend"],
            "description": "Bot under test",
            "provider": "codex",
            "mode": "registry",
            "connectivity_state": connectivity_state,
            "channel_capabilities": ["registry"],
            "management_capabilities": advertised_management_capabilities,
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
                "capabilities": ["python"],
                "tags": ["backend"],
                "description": "Bot under test",
                "provider": "codex",
                "mode": "registry",
                "channel_capabilities": ["registry"],
                "management_capabilities": advertised_management_capabilities,
                "version": "test",
            },
            "connectivity_state": connectivity_state,
            "current_capacity": 0,
            "max_capacity": 1,
        },
    )
    return enroll.agent_id, enroll.agent_token


def test_management_request_round_trip_polls_delivery_and_persists_result(tmp_path: Path) -> None:
    store = RegistrySQLiteStore(tmp_path / "registry.sqlite3")
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
    assert list(status.management_capabilities) == _FULL_MANAGEMENT_CAPABILITIES

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


@pytest.mark.asyncio
async def test_registry_management_client_requires_connected_agent(tmp_path: Path) -> None:
    store = RegistrySQLiteStore(tmp_path / "registry.sqlite3")
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
async def test_registry_management_client_requires_advertised_capability(tmp_path: Path) -> None:
    store = RegistrySQLiteStore(tmp_path / "registry.sqlite3")
    agent_id, _agent_token = _register_agent(store, management_capabilities=["provider_guidance"])

    client = RegistryManagementClient(store)
    with pytest.raises(ManagementClientError) as excinfo:
        await client.send(
            agent_id=agent_id,
            payload=ListCatalogSkillsRequest(query="github"),
        )

    assert excinfo.value.status_code == 409
    assert excinfo.value.error_code == "capability_not_available"


@pytest.mark.asyncio
async def test_registry_management_client_times_out_without_result(tmp_path: Path) -> None:
    store = RegistrySQLiteStore(tmp_path / "registry.sqlite3")
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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = RegistrySQLiteStore(tmp_path / "registry.sqlite3")
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
