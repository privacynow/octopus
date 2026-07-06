from __future__ import annotations

from app.runtime.browser_journey import _artifact_api_url, _headers_for_origin
from octopus_sdk.protocols import ProtocolRuntimeJourneySpecRecord


def test_browser_journey_api_status_uses_artifact_api_base() -> None:
    spec = ProtocolRuntimeJourneySpecRecord(
        protocol_run_id="run-1",
        artifact_key="package",
        journey_key="happy_path",
    )

    assert _artifact_api_url(
        spec,
        target_origin="http://registry:8787",
        path="/data-status",
    ) == "http://registry:8787/runtime/protocol-runs/run-1/artifacts/package/api/data-status"


def test_browser_journey_bearer_is_scoped_to_registry_origin() -> None:
    assert _headers_for_origin(
        request_origin="http://registry:8787",
        target_origin="http://registry:8787",
        bearer_token="oct-rt-secret",
    ) == {"authorization": "Bearer oct-rt-secret"}

    assert _headers_for_origin(
        request_origin="https://example.com",
        target_origin="http://registry:8787",
        bearer_token="oct-rt-secret",
    ) == {}
