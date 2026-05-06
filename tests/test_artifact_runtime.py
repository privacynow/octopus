from __future__ import annotations

import base64

from app.runtime import artifact_runtime, workspace_hygiene
from octopus_sdk.protocols import ProtocolArtifactRuntimeManifestRecord
from octopus_sdk.registry.management import (
    ArtifactRuntimeFetchRequest,
    ArtifactRuntimeHealthRequest,
    ArtifactRuntimeLogsRequest,
    StartArtifactRuntimeRequest,
    StopArtifactRuntimeRequest,
    WorkspaceCleanupRequest,
    WorkspaceUsageRequest,
)
from tests.support.config_support import make_config


def test_artifact_runtime_expands_manifest_port_placeholders():
    manifest = ProtocolArtifactRuntimeManifestRecord(
        runtime_kind="java",
        start_command=(
            "mvn spring-boot:run "
            "-Dserver.port=${PORT:8080} "
            "-Dalt.port=${PORT:-8080} "
            "-Dplain=${PORT} "
            "-Dbare=$PORT"
        ),
        port_env="PORT",
        endpoints=[{"endpoint_kind": "docs", "path": "/api/docs", "label": "API docs"}],
        smoke_test=["GET /health returns 200"],
    )

    command = artifact_runtime._command_for(manifest, 49152)

    assert "${PORT" not in command
    assert "$PORT" not in command
    assert "-Dserver.port=49152" in command
    assert "-Dalt.port=49152" in command
    assert "-Dplain=49152" in command
    assert "-Dbare=49152" in command


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


async def test_workspace_hygiene_dry_run_and_cleanup(tmp_path):
    working_dir = tmp_path / "workspace"
    data_dir = tmp_path / "data"
    cache_dir = working_dir / "project" / "target"
    cache_dir.mkdir(parents=True)
    (cache_dir / "build.log").write_text("temporary build output", encoding="utf-8")
    runtime_log_dir = data_dir / "artifact-runtimes" / "run-1"
    runtime_log_dir.mkdir(parents=True)
    (runtime_log_dir / "runtime.log").write_text("runtime log", encoding="utf-8")
    config = make_config(data_dir=data_dir, working_dir=working_dir)

    usage = await workspace_hygiene.workspace_usage(
        WorkspaceUsageRequest(categories=["build_caches", "runtime_logs"]),
        config=config,
    )

    categories = {entry.category for entry in usage.plan.entries}
    assert {"build_caches", "runtime_logs"}.issubset(categories)
    assert usage.plan.deletable_bytes > 0
    assert cache_dir.exists()

    cleaned = await workspace_hygiene.workspace_cleanup(
        WorkspaceCleanupRequest(plan=usage.plan, confirm="CLEAN"),
        config=config,
    )

    assert cleaned.removed_bytes > 0
    assert str(cache_dir.resolve()) in cleaned.removed_paths
    assert not cache_dir.exists()


async def test_workspace_hygiene_blocks_symlink_escape(tmp_path):
    working_dir = tmp_path / "workspace"
    outside_dir = tmp_path / "outside"
    working_dir.mkdir()
    outside_dir.mkdir()
    escaped = working_dir / "target"
    escaped.symlink_to(outside_dir, target_is_directory=True)
    config = make_config(data_dir=tmp_path / "data", working_dir=working_dir)

    usage = await workspace_hygiene.workspace_usage(
        WorkspaceUsageRequest(categories=["build_caches"]),
        config=config,
    )
    cleaned = await workspace_hygiene.workspace_cleanup(
        WorkspaceCleanupRequest(plan=usage.plan, confirm="CLEAN"),
        config=config,
    )

    assert cleaned.removed_paths == []
    assert cleaned.failures
    assert outside_dir.exists()
