from __future__ import annotations

import base64

from app.runtime import artifact_runtime
from octopus_sdk.protocols import ProtocolArtifactRuntimeManifestRecord
from octopus_sdk.registry.management import (
    ArtifactRuntimeFetchRequest,
    ArtifactRuntimeHealthRequest,
    ArtifactRuntimeLogsRequest,
    StartArtifactRuntimeRequest,
    StopArtifactRuntimeRequest,
)
from tests.support.config_support import make_config


async def test_static_artifact_runtime_starts_fetches_and_stops(tmp_path):
    package_dir = tmp_path / "package"
    package_dir.mkdir()
    (package_dir / "index.html").write_text("<!doctype html><title>Runtime App</title>", encoding="utf-8")
    config = make_config(data_dir=tmp_path / "data")
    runtime_id = "runtime-test-static"
    start = StartArtifactRuntimeRequest(
        runtime_instance_id=runtime_id,
        protocol_run_id="run-1",
        artifact_key="package",
        artifact_path=str(package_dir),
        manifest=ProtocolArtifactRuntimeManifestRecord(runtime_kind="static", ui_path="/", health_path="/"),
        actor_ref="operator",
    )

    started = await artifact_runtime.start_artifact_runtime(start, config=config)
    try:
        assert started.result.ok is True
        assert started.result.runtime is not None
        assert started.result.runtime.status == "running"

        fetched = await artifact_runtime.artifact_runtime_fetch(
            ArtifactRuntimeFetchRequest(
                runtime_instance_id=runtime_id,
                protocol_run_id="run-1",
                artifact_key="package",
                path="/",
            )
        )
        body = base64.b64decode(fetched.body_base64.encode("ascii")).decode("utf-8")
        assert fetched.status_code == 200
        assert "<title>Runtime App</title>" in body

        health = await artifact_runtime.artifact_runtime_health(
            ArtifactRuntimeHealthRequest(
                runtime_instance_id=runtime_id,
                protocol_run_id="run-1",
                artifact_key="package",
            )
        )
        assert health.health.ok is True

        logs = await artifact_runtime.artifact_runtime_logs(
            ArtifactRuntimeLogsRequest(
                runtime_instance_id=runtime_id,
                protocol_run_id="run-1",
                artifact_key="package",
            )
        )
        assert "starting:" in logs.log_tail
    finally:
        stopped = await artifact_runtime.stop_artifact_runtime(
            StopArtifactRuntimeRequest(
                runtime_instance_id=runtime_id,
                protocol_run_id="run-1",
                artifact_key="package",
                actor_ref="operator",
            )
        )
        assert stopped.result.status == "stopped"


async def test_artifact_runtime_health_marks_missing_process_stopped():
    health = await artifact_runtime.artifact_runtime_health(
        ArtifactRuntimeHealthRequest(
            runtime_instance_id="missing-runtime",
            protocol_run_id="run-1",
            artifact_key="package",
        )
    )

    assert health.health.ok is False
    assert health.health.status == "stopped"
    assert health.health.runtime is not None
    assert health.health.runtime.status == "stopped"
    assert health.health.runtime.failure_code == "runtime_not_running"
