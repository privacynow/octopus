"""Shared Compose E2E harness helpers."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_DOCKER_PROBE_DETAIL_MAX = 200


def docker_probe() -> tuple[bool, str, str]:
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=5,
            check=False,
            text=True,
        )
    except FileNotFoundError:
        return (False, "missing_cli", "docker CLI not found in PATH")
    except subprocess.TimeoutExpired:
        return (False, "timeout", "docker info timed out")

    if result.returncode == 0:
        return (True, "ok", "")

    err = (result.stderr or "").strip()
    out = (result.stdout or "").strip()
    excerpt = err or out
    if len(excerpt) > _DOCKER_PROBE_DETAIL_MAX:
        excerpt = excerpt[:_DOCKER_PROBE_DETAIL_MAX].rsplit(maxsplit=1)[0] or excerpt[:_DOCKER_PROBE_DETAIL_MAX]

    err_lower = err.lower()
    if "permission denied" in err_lower or "operation not permitted" in err_lower:
        return (False, "daemon_permission_denied", excerpt or "permission denied")
    if (
        "cannot connect to the docker daemon" in err_lower
        or "is the docker daemon running" in err_lower
        or "dial unix" in err_lower
        or "connection refused" in err_lower
    ):
        return (False, "daemon_unreachable", excerpt or "daemon not reachable")
    return (False, "unknown_failure", excerpt or f"docker info exited {result.returncode}")


def docker_skip_message(reason: str, detail: str) -> str:
    if reason == "missing_cli":
        return "Docker CLI not found"
    if reason == "timeout":
        return "docker info timed out"
    if reason == "daemon_permission_denied":
        return "Docker daemon not accessible this test process: " + (detail or "permission denied")
    if reason == "daemon_unreachable":
        return "Docker daemon not reachable: " + (detail or "daemon not running or not reachable")
    return "Docker not available: " + (detail or reason)


@pytest.fixture(scope="module")
def e2e_skip():
    if os.environ.get("E2E_COMPOSE") != "1":
        pytest.skip("E2E_COMPOSE=1 not set")
    ok, reason, detail = docker_probe()
    if not ok:
        pytest.skip(docker_skip_message(reason, detail))


def compose(ctx: dict[str, object], *args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    cmd = ["docker", "compose"]
    project_dir = ctx.get("project_dir")
    if project_dir:
        cmd.extend(["--project-directory", str(project_dir)])
    cmd.extend([*ctx["compose_files"], *args])
    return subprocess.run(
        cmd,
        cwd=ctx.get("cwd", REPO_ROOT),
        env=ctx["env"],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def compose_logs(ctx: dict[str, object], name: str, *services: str, timeout: int = 120) -> tuple[Path, str]:
    result = compose(ctx, "logs", "--no-color", *services, timeout=timeout)
    body = []
    if result.stdout:
        body.append(result.stdout)
    if result.stderr:
        body.append(result.stderr)
    log_text = "\n".join(body).strip()
    log_path = Path(ctx["artifacts_dir"]) / f"{name}.compose.log"
    log_path.write_text(log_text + ("\n" if log_text else ""), encoding="utf-8")
    return log_path, log_text


def fail_with_logs(ctx: dict[str, object], name: str, message: str, *services: str) -> None:
    log_path, log_text = compose_logs(ctx, name, *services)
    details = f"{message}\n\nCompose logs saved to: {log_path}"
    if log_text:
        details += f"\n\n{log_text}"
    pytest.fail(details)


def remove_image(tag: str, artifacts_dir: Path | None = None) -> None:
    result = subprocess.run(
        ["docker", "image", "rm", tag],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0 and artifacts_dir is not None:
        cleanup_log = artifacts_dir / "teardown-image-rm.log"
        cleanup_log.write_text(
            f"tag={tag} returncode={result.returncode}\nstdout={result.stdout or ''}\nstderr={result.stderr or ''}",
            encoding="utf-8",
        )


def compose_down(ctx: dict[str, object], name: str = "teardown") -> tuple[subprocess.CompletedProcess, Path | None]:
    result = compose(
        ctx,
        "--profile",
        "tools",
        "--profile",
        "registry",
        "--profile",
        "bot",
        "--profile",
        "stub",
        "down",
        "-v",
        "--remove-orphans",
        "-t",
        "2",
        timeout=120,
    )
    if result.returncode == 0:
        return result, None
    log_path = Path(ctx["artifacts_dir"]) / f"{name}.compose-down.log"
    body = []
    if result.stdout:
        body.append(result.stdout)
    if result.stderr:
        body.append(result.stderr)
    log_text = "\n".join(body).strip()
    log_path.write_text(log_text + ("\n" if log_text else ""), encoding="utf-8")
    return result, log_path


def free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def build_image(
    *,
    dockerfile: str,
    tag: str,
    artifacts_dir: Path,
    build_args: dict[str, str] | None = None,
    timeout: int = 600,
) -> None:
    log_path = artifacts_dir / "docker-build.log"
    print(f"Building Docker image; output in {log_path}. Use pytest -s to see this notice.", file=sys.stderr)
    sys.stderr.flush()
    cmd = ["docker", "build", "-f", dockerfile, "-t", tag]
    for key, value in (build_args or {}).items():
        cmd.extend(["--build-arg", f"{key}={value}"])
    cmd.append(".")
    with open(log_path, "w", encoding="utf-8") as log_file:
        log_file.write(f"Docker build log for {tag}\n")
        log_file.flush()
        try:
            result = subprocess.run(
                cmd,
                cwd=REPO_ROOT,
                timeout=timeout,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                check=False,
            )
        except subprocess.TimeoutExpired:
            pytest.fail(f"docker build timed out after {timeout}s; see {log_path}")
        if result.returncode != 0:
            pytest.fail(f"docker build failed; see {log_path}")
