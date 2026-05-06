"""Bot-side supervisor for runnable protocol artifacts."""

from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import http.client
import os
from pathlib import Path
import shlex
import signal
import socket
import sys

from app.config import BotConfig
from octopus_sdk.protocols.models import (
    ProtocolArtifactRuntimeActionResultRecord,
    ProtocolArtifactRuntimeHealthRecord,
    ProtocolArtifactRuntimeInstanceRecord,
    ProtocolArtifactRuntimeManifestRecord,
    RegistryJsonRecord,
    utcnow_iso,
)
from octopus_sdk.registry.management import (
    ArtifactRuntimeFetchRequest,
    ArtifactRuntimeFetchResult,
    ArtifactRuntimeHealthRequest,
    ArtifactRuntimeHealthResult,
    ArtifactRuntimeLogsRequest,
    ArtifactRuntimeLogsResult,
    StartArtifactRuntimeRequest,
    StartArtifactRuntimeResult,
    StopArtifactRuntimeRequest,
    StopArtifactRuntimeResult,
)


@dataclass
class _RuntimeProcess:
    process: asyncio.subprocess.Process
    runtime: ProtocolArtifactRuntimeInstanceRecord
    log_path: Path


_RUNTIMES: dict[str, _RuntimeProcess] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _safe_runtime_path(path: str) -> str:
    text = str(path or "/").strip() or "/"
    if not text.startswith("/"):
        text = f"/{text}"
    return text


def _local_url(port: int, path: str = "/") -> str:
    return f"http://127.0.0.1:{port}{_safe_runtime_path(path)}"


def _artifact_root(path: str) -> Path:
    root = Path(str(path or "").strip()).expanduser().resolve()
    if not root.exists():
        raise RuntimeError(f"Artifact path is not available in the bot container: {root}")
    return root if root.is_dir() else root.parent


def _working_dir(root: Path, manifest: ProtocolArtifactRuntimeManifestRecord) -> Path:
    if not manifest.working_directory:
        return root
    candidate = (root / manifest.working_directory).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise RuntimeError("Runtime working_directory must stay inside the artifact package.") from exc
    if not candidate.is_dir():
        raise RuntimeError(f"Runtime working_directory does not exist: {manifest.working_directory}")
    return candidate


def _command_for(manifest: ProtocolArtifactRuntimeManifestRecord, port: int) -> str:
    if manifest.runtime_kind == "static":
        return f"{shlex.quote(sys.executable)} -m http.server {port} --bind 127.0.0.1"
    command = str(manifest.start_command or "").strip()
    if not command:
        raise RuntimeError("Runnable artifact manifest is missing start_command.")
    return command


def _runtime_record(
    request: StartArtifactRuntimeRequest,
    *,
    port: int,
    status: str,
    pid: int = 0,
    failure_code: str = "",
    failure_detail: str = "",
    log_tail: str = "",
) -> ProtocolArtifactRuntimeInstanceRecord:
    base_path = (
        f"/runtime/protocol-runs/{request.protocol_run_id}"
        f"/artifacts/{request.artifact_key}"
    )
    manifest = request.manifest
    return ProtocolArtifactRuntimeInstanceRecord(
        runtime_instance_id=request.runtime_instance_id,
        protocol_run_id=request.protocol_run_id,
        artifact_key=request.artifact_key,
        agent_id="",
        status=status,
        manifest=manifest,
        manifest_path=request.manifest_path,
        artifact_path=request.artifact_path,
        runtime_url=f"{base_path}/app/",
        ui_url=f"{base_path}/app{_safe_runtime_path(manifest.ui_path)}",
        api_url=f"{base_path}/api/",
        health_url=f"{base_path}/health",
        internal_url=_local_url(port, "/"),
        pid=pid,
        port=port,
        started_by=request.actor_ref,
        failure_code=failure_code,
        failure_detail=failure_detail,
        log_tail=log_tail,
        created_at=_now(),
        updated_at=_now(),
        started_at=_now() if status == "running" else "",
    )


def _tail(path: Path, max_bytes: int = 12000) -> str:
    try:
        raw = path.read_bytes()
    except OSError:
        return ""
    if len(raw) > max_bytes:
        raw = raw[-max_bytes:]
    return raw.decode("utf-8", errors="replace")


async def _http_probe(port: int, path: str, timeout: float = 3.0) -> tuple[bool, int, str]:
    def _request() -> tuple[bool, int, str]:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
        try:
            conn.request("GET", _safe_runtime_path(path), headers={"User-Agent": "Octopus-Runtime-Health"})
            response = conn.getresponse()
            body = response.read(2048).decode("utf-8", errors="replace")
            return 200 <= int(response.status) < 500, int(response.status), body
        except OSError as exc:
            return False, 0, str(exc)
        finally:
            conn.close()

    return await asyncio.to_thread(_request)


async def start_artifact_runtime(
    request: StartArtifactRuntimeRequest,
    *,
    config: BotConfig,
) -> StartArtifactRuntimeResult:
    existing = _RUNTIMES.get(request.runtime_instance_id)
    if existing is not None and existing.process.returncode is None:
        return StartArtifactRuntimeResult(
            result=ProtocolArtifactRuntimeActionResultRecord(
                ok=True,
                status="running",
                message="Runtime is already running.",
                runtime=existing.runtime,
            )
        )

    root = _artifact_root(request.artifact_path)
    workdir = _working_dir(root, request.manifest)
    port = _free_port()
    log_dir = Path(config.data_dir) / "artifact-runtimes"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{request.runtime_instance_id}.log"
    command = _command_for(request.manifest, port)
    env = dict(os.environ)
    env[str(request.manifest.port_env or "PORT")] = str(port)
    env.setdefault("HOST", "127.0.0.1")
    try:
        with log_path.open("ab") as log_file:
            log_file.write(f"\n[{_now()}] starting: {command}\n".encode("utf-8"))
            process = await asyncio.create_subprocess_shell(
                command,
                cwd=str(workdir),
                env=env,
                stdout=log_file,
                stderr=log_file,
                start_new_session=True,
            )
        runtime = _runtime_record(
            request,
            port=port,
            status="running",
            pid=int(process.pid or 0),
        )
        _RUNTIMES[request.runtime_instance_id] = _RuntimeProcess(process=process, runtime=runtime, log_path=log_path)
        deadline = asyncio.get_running_loop().time() + min(30, int(request.manifest.startup_timeout_seconds or 30))
        last_status = 0
        while asyncio.get_running_loop().time() < deadline:
            if process.returncode is not None:
                raise RuntimeError(f"Runtime exited during startup with code {process.returncode}.")
            ok, status_code, _body = await _http_probe(port, request.manifest.health_path)
            last_status = status_code
            if ok:
                return StartArtifactRuntimeResult(
                    result=ProtocolArtifactRuntimeActionResultRecord(
                        ok=True,
                        status="running",
                        message=f"Runtime started on bot port {port}.",
                        runtime=runtime.model_copy(update={"updated_at": _now()}),
                    )
                )
            await asyncio.sleep(0.5)
        return StartArtifactRuntimeResult(
            result=ProtocolArtifactRuntimeActionResultRecord(
                ok=True,
                status="running",
                message=f"Runtime started, but health path has not responded yet (last status {last_status}).",
                runtime=runtime.model_copy(update={"updated_at": _now(), "log_tail": _tail(log_path)}),
            )
        )
    except Exception as exc:
        failed = _runtime_record(
            request,
            port=port,
            status="failed",
            failure_code="runtime_start_failed",
            failure_detail=str(exc),
            log_tail=_tail(log_path),
        )
        return StartArtifactRuntimeResult(
            result=ProtocolArtifactRuntimeActionResultRecord(
                ok=False,
                status="failed",
                message=str(exc),
                runtime=failed,
            )
        )


async def stop_artifact_runtime(request: StopArtifactRuntimeRequest) -> StopArtifactRuntimeResult:
    entry = _RUNTIMES.get(request.runtime_instance_id)
    if entry is None or entry.process.returncode is not None:
        runtime = ProtocolArtifactRuntimeInstanceRecord(
            runtime_instance_id=request.runtime_instance_id,
            protocol_run_id=request.protocol_run_id,
            artifact_key=request.artifact_key,
            status="stopped",
            stopped_by=request.actor_ref,
            updated_at=_now(),
            stopped_at=_now(),
        )
        return StopArtifactRuntimeResult(
            result=ProtocolArtifactRuntimeActionResultRecord(
                ok=True,
                status="stopped",
                message="Runtime is already stopped.",
                runtime=runtime,
            )
        )
    try:
        try:
            os.killpg(entry.process.pid, signal.SIGTERM)
        except Exception:
            entry.process.terminate()
        try:
            await asyncio.wait_for(entry.process.wait(), timeout=5)
        except asyncio.TimeoutError:
            try:
                os.killpg(entry.process.pid, signal.SIGKILL)
            except Exception:
                entry.process.kill()
            await entry.process.wait()
        runtime = entry.runtime.model_copy(
            update={
                "status": "stopped",
                "stopped_by": request.actor_ref,
                "updated_at": _now(),
                "stopped_at": _now(),
                "log_tail": _tail(entry.log_path),
            }
        )
        _RUNTIMES.pop(request.runtime_instance_id, None)
        return StopArtifactRuntimeResult(
            result=ProtocolArtifactRuntimeActionResultRecord(
                ok=True,
                status="stopped",
                message="Runtime stopped.",
                runtime=runtime,
            )
        )
    except Exception as exc:
        runtime = entry.runtime.model_copy(
            update={
                "status": "failed",
                "failure_code": "runtime_stop_failed",
                "failure_detail": str(exc),
                "updated_at": _now(),
                "log_tail": _tail(entry.log_path),
            }
        )
        return StopArtifactRuntimeResult(
            result=ProtocolArtifactRuntimeActionResultRecord(
                ok=False,
                status="failed",
                message=str(exc),
                runtime=runtime,
            )
        )


async def artifact_runtime_health(request: ArtifactRuntimeHealthRequest) -> ArtifactRuntimeHealthResult:
    entry = _RUNTIMES.get(request.runtime_instance_id)
    if entry is None or entry.process.returncode is not None:
        return ArtifactRuntimeHealthResult(
            health=ProtocolArtifactRuntimeHealthRecord(
                ok=False,
                status="stopped",
                message="Runtime is not running.",
                checked_at=utcnow_iso(),
            )
        )
    health_path = entry.runtime.manifest.health_path if entry.runtime.manifest else "/"
    ok, status_code, body = await _http_probe(entry.runtime.port, health_path)
    runtime = entry.runtime.model_copy(update={"updated_at": _now(), "log_tail": _tail(entry.log_path)})
    return ArtifactRuntimeHealthResult(
        health=ProtocolArtifactRuntimeHealthRecord(
            ok=ok,
            status="running" if ok else "failed",
            status_code=status_code,
            message=body[:500] or ("Runtime is healthy." if ok else "Runtime health check failed."),
            checked_at=utcnow_iso(),
            runtime=runtime,
        )
    )


async def artifact_runtime_logs(request: ArtifactRuntimeLogsRequest) -> ArtifactRuntimeLogsResult:
    entry = _RUNTIMES.get(request.runtime_instance_id)
    runtime = entry.runtime if entry is not None else ProtocolArtifactRuntimeInstanceRecord(
        runtime_instance_id=request.runtime_instance_id,
        protocol_run_id=request.protocol_run_id,
        artifact_key=request.artifact_key,
        status="stopped",
    )
    log_tail = _tail(entry.log_path, request.max_bytes) if entry is not None else ""
    return ArtifactRuntimeLogsResult(runtime=runtime.model_copy(update={"log_tail": log_tail}), log_tail=log_tail)


async def artifact_runtime_fetch(request: ArtifactRuntimeFetchRequest) -> ArtifactRuntimeFetchResult:
    entry = _RUNTIMES.get(request.runtime_instance_id)
    if entry is None or entry.process.returncode is not None:
        raise RuntimeError("Runtime is not running.")
    method = str(request.method or "GET").strip().upper() or "GET"
    path = _safe_runtime_path(request.path)
    if request.query_string:
        path = f"{path}?{request.query_string.lstrip('?')}"
    body = base64.b64decode(request.body_base64.encode("utf-8")) if request.body_base64 else None
    header_map = {
        str(key): str(value)
        for key, value in request.headers.as_dict().items()
        if str(key).lower() not in {"host", "connection", "content-length"}
    }

    def _request() -> tuple[int, dict[str, str], bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", entry.runtime.port, timeout=30)
        try:
            conn.request(method, path, body=body, headers=header_map)
            response = conn.getresponse()
            raw = response.read()
            headers = {
                key: value
                for key, value in response.getheaders()
                if key.lower() in {
                    "content-type",
                    "cache-control",
                    "etag",
                    "last-modified",
                    "location",
                }
            }
            return int(response.status), headers, raw
        finally:
            conn.close()

    status_code, headers, raw = await asyncio.to_thread(_request)
    return ArtifactRuntimeFetchResult(
        runtime=entry.runtime.model_copy(update={"updated_at": _now()}),
        status_code=status_code,
        headers=RegistryJsonRecord(headers),
        body_base64=base64.b64encode(raw).decode("ascii"),
    )
