"""Compose-based E2E tests for the Docker-first operator path.

Run only when E2E_COMPOSE=1 and Docker is available. Skipped in normal pytest runs.
See README.md for the operator path and ARCHITECTURE.md for the runtime/testing contract.

Primary gate: test_compose_sqlite_local_runtime_primary — Docker Local Runtime with SQLite,
no BOT_DATABASE_URL, no Postgres. Bounded Postgres coverage: test_compose_bootstrap_doctor,
test_compose_db_update_smoke, test_compose_bot_startup_with_postgres.

The harness isolates each worker/run with:
- a unique COMPOSE_PROJECT_NAME
- a generated override file for worker-local bot env and image tags
- no host Postgres port publication

That lets these tests run safely alongside a local dev stack and across concurrent test runs.

Bot startup is asserted by running the bot in the foreground (compose run --rm bot) with a
single communicate(timeout=...), then checking stderr for startup or provider-auth messages.
No log-polling loops.

Docker build: output is written to artifacts_dir/docker-build.log; use pytest -s to see the
pre-build notice; check the log file for build progress/details.
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib import error as urllib_error
from urllib import request as urllib_request

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_E2E_REGISTRY_ENROLL_TOKEN = "e2e-enroll-token"
_E2E_REGISTRY_UI_TOKEN = "e2e-ui-token"

_DOCKER_PROBE_DETAIL_MAX = 200


def _docker_probe() -> tuple[bool, str, str]:
    """Probe Docker from this process. Returns (ok, reason, detail).

    reason is one of: ok, missing_cli, timeout, daemon_permission_denied,
    daemon_unreachable, unknown_failure.
    detail is a short excerpt (stderr preferred) for skip messages, trimmed.
    """
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
        excerpt = excerpt[: _DOCKER_PROBE_DETAIL_MAX].rsplit(maxsplit=1)[0] or excerpt[:_DOCKER_PROBE_DETAIL_MAX]

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


def _worker_id() -> str:
    return os.environ.get("PYTEST_XDIST_WORKER", "master")


def _compose(ctx: dict[str, object], *args: str, timeout: int = 120) -> subprocess.CompletedProcess:
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


def _compose_logs(ctx: dict[str, object], name: str, *services: str, timeout: int = 120) -> tuple[Path, str]:
    """Fetch compose logs (for teardown and failure reporting)."""
    result = _compose(ctx, "logs", "--no-color", *services, timeout=timeout)
    body = []
    if result.stdout:
        body.append(result.stdout)
    if result.stderr:
        body.append(result.stderr)
    log_text = "\n".join(body).strip()
    log_path = Path(ctx["artifacts_dir"]) / f"{name}.compose.log"
    log_path.write_text(log_text + ("\n" if log_text else ""), encoding="utf-8")
    return log_path, log_text


def _fail_with_logs(ctx: dict[str, object], name: str, message: str, *services: str) -> None:
    log_path, log_text = _compose_logs(ctx, name, *services)
    details = f"{message}\n\nCompose logs saved to: {log_path}"
    if log_text:
        details += f"\n\n{log_text}"
    pytest.fail(details)


def _remove_image(tag: str, artifacts_dir: Path | None = None) -> None:
    """Best-effort remove a single image tag. Never raises. Optionally records failure to artifacts_dir."""
    r = subprocess.run(
        ["docker", "image", "rm", tag],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if r.returncode != 0 and artifacts_dir is not None:
        cleanup_log = artifacts_dir / "teardown-image-rm.log"
        cleanup_log.write_text(
            f"tag={tag} returncode={r.returncode}\nstdout={r.stdout or ''}\nstderr={r.stderr or ''}",
            encoding="utf-8",
        )


def _compose_down(ctx: dict[str, object], name: str = "teardown") -> tuple[subprocess.CompletedProcess, Path | None]:
    """Bring the project down and record cleanup failure details if it fails."""
    r = _compose(
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
    if r.returncode == 0:
        return r, None
    log_path = Path(ctx["artifacts_dir"]) / f"{name}.compose-down.log"
    body = []
    if r.stdout:
        body.append(r.stdout)
    if r.stderr:
        body.append(r.stderr)
    log_text = "\n".join(body).strip()
    log_path.write_text(log_text + ("\n" if log_text else ""), encoding="utf-8")
    return r, log_path


def _free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _registry_ui_ctx(ctx: dict[str, object]) -> dict[str, object]:
    derived = dict(ctx)
    registry_port = _free_local_port()
    derived["registry_port"] = registry_port
    derived["env"] = {
        **ctx["env"],
        "REGISTRY_PORT": str(registry_port),
        "REGISTRY_ENROLL_TOKEN": _E2E_REGISTRY_ENROLL_TOKEN,
        "REGISTRY_UI_TOKEN": _E2E_REGISTRY_UI_TOKEN,
        "REGISTRY_ALLOW_HTTP": "1",
    }
    return derived


def _registry_url(ctx: dict[str, object]) -> str:
    return f"http://127.0.0.1:{ctx['registry_port']}"


def _http_json(
    method: str,
    url: str,
    *,
    token: str = "",
    payload: dict[str, object] | None = None,
    timeout: int = 5,
) -> dict[str, object]:
    body = None
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib_request.Request(url, data=body, headers=headers, method=method)
    with urllib_request.urlopen(req, timeout=timeout) as response:
        data = response.read().decode("utf-8")
    return json.loads(data or "{}")


def _wait_for_registry_ready(ctx: dict[str, object], timeout_seconds: int = 30) -> None:
    deadline = time.time() + timeout_seconds
    last_error = "registry not ready"
    url = _registry_url(ctx)
    while time.time() < deadline:
        try:
            health = _http_json("GET", f"{url}/healthz", timeout=2)
            if health.get("ok") is True:
                return
        except Exception as exc:
            last_error = str(exc)
        time.sleep(1)
    _fail_with_logs(ctx, "registry-not-ready", f"Registry did not become ready: {last_error}", "registry")


@pytest.fixture(scope="module")
def compose_ctx(e2e_skip, tmp_path_factory):
    worker = _worker_id()
    run_id = uuid.uuid4().hex[:10]
    project = f"octopus-agent-e2e-{worker}-{run_id}"
    artifacts_dir = tmp_path_factory.mktemp(f"compose-e2e-{worker}")
    env_file = Path(artifacts_dir) / "bot.env"
    env_file.write_text(
        "\n".join(
            [
                "BOT_PROVIDER=claude",
                "TELEGRAM_BOT_TOKEN=123456:ABC-DEFghijklmnopqrstuvwxyz",
                "BOT_ALLOW_OPEN=1",
                "",
            ]
        ),
        encoding="utf-8",
    )
    bot_image = f"octopus-agent-e2e:{worker}-{run_id}-claude"
    generated_override = Path(artifacts_dir) / "docker-compose.e2e.generated.yml"
    generated_override.write_text(
        "\n".join(
            [
                "services:",
                "  bot-provider:",
                f"    image: {bot_image}",
                "    env_file: !override",
                f"      - {env_file}",
                "  bot:",
                f"    image: {bot_image}",
                "    env_file: !override",
                f"      - {env_file}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    ctx = {
        "project": project,
        "compose_files": [
            "-f", os.path.join(REPO_ROOT, "infra/compose/docker-compose.yml"),
            "-f", os.path.join(REPO_ROOT, "infra/compose/docker-compose.e2e.yml"),
            "-f", str(generated_override),
        ],
        "cwd": REPO_ROOT,
        "project_dir": REPO_ROOT,
        "env": {**os.environ, "COMPOSE_PROJECT_NAME": project},
        "env_file": env_file,
        "artifacts_dir": artifacts_dir,
        "bot_image": bot_image,
    }
    yield ctx
    try:
        _compose_logs(ctx, "final")
    finally:
        down_result, down_log = _compose_down(ctx)
        _remove_image(ctx["bot_image"], ctx.get("artifacts_dir"))
        if down_result.returncode != 0:
            details = f"Compose cleanup failed for project {ctx['project']}."
            if down_log is not None:
                details += f"\n\nCompose cleanup log saved to: {down_log}"
                log_text = down_log.read_text(encoding="utf-8").strip()
                if log_text:
                    details += f"\n\n{log_text}"
            pytest.fail(details)


def _docker_skip_message(reason: str, detail: str) -> str:
    """Build a truthful, bounded skip message from probe result."""
    if reason == "missing_cli":
        return "Docker CLI not found"
    if reason == "timeout":
        return "docker info timed out"
    if reason == "daemon_permission_denied":
        return "Docker daemon not accessible from this test process: " + (detail or "permission denied")
    if reason == "daemon_unreachable":
        return "Docker daemon not reachable: " + (detail or "daemon not running or not reachable")
    return "Docker not available: " + (detail or reason)


@pytest.fixture(scope="module")
def e2e_skip():
    """Skip entire module unless E2E_COMPOSE=1 and Docker is usable from this process."""
    if os.environ.get("E2E_COMPOSE") != "1":
        pytest.skip("E2E_COMPOSE=1 not set")
    ok, reason, detail = _docker_probe()
    if not ok:
        pytest.skip(_docker_skip_message(reason, detail))


# Short timeout for readiness probes so loops are bounded (was 120s default → 30*120s = 1h).
_PG_ISREADY_TIMEOUT = 15


@pytest.fixture(scope="module")
def postgres_up(compose_ctx):
    """Bring up Postgres and wait for healthy. Module teardown is handled by compose_ctx."""
    r = _compose(compose_ctx, "up", "-d", "postgres")
    assert r.returncode == 0, (r.stdout, r.stderr)
    for _ in range(30):
        r = _compose(
            compose_ctx,
            "exec", "postgres", "pg_isready", "-U", "bot", "-d", "bot",
            timeout=_PG_ISREADY_TIMEOUT,
        )
        if r.returncode == 0:
            break
        time.sleep(1)
    else:
        _fail_with_logs(compose_ctx, "postgres-not-ready", "Postgres did not become ready", "postgres")
    return compose_ctx


# Build can take several minutes on first run (no cache). Output is written to an artifact
# log (docker-build.log); the pre-build notice is visible with pytest -s. Check the log for details.
_DOCKER_BUILD_TIMEOUT = 600
_DOCKER_BUILD_LOG_NAME = "docker-build.log"


def _docker_build_log_path(ctx: dict[str, object]) -> Path:
    """Path where Docker build stdout/stderr are written. Used for notice and failure message."""
    return Path(ctx["artifacts_dir"]) / _DOCKER_BUILD_LOG_NAME


def _build_bot_image(ctx: dict[str, object]) -> None:
    """Build the bot image and tag it as ctx['bot_image'].

    Build output is written to artifacts_dir/docker-build.log. The pre-build notice is
    visible with pytest -s; the log file is the source of build progress/details. On
    failure (non-zero exit or timeout), pytest.fail points to the log path.
    """
    log_path = _docker_build_log_path(ctx)
    print(f"Building bot image; output in {log_path}. Use pytest -s to see this notice.", file=sys.stderr)
    sys.stderr.flush()
    with open(log_path, "w") as log_file:
        log_file.write("Docker build (Dockerfile.bot) log\n")
        log_file.flush()
        try:
            r = subprocess.run(
                ["docker", "build", "-f", "infra/docker/Dockerfile.bot", "--build-arg", "BOT_PROVIDER=claude",
                 "-t", str(ctx["bot_image"]), "."],
                cwd=REPO_ROOT,
                timeout=_DOCKER_BUILD_TIMEOUT,
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )
        except subprocess.TimeoutExpired:
            pytest.fail(f"docker build timed out after {_DOCKER_BUILD_TIMEOUT}s; see {log_path}")
        if r.returncode != 0:
            pytest.fail(f"docker build failed; see {log_path}")


# Postgres-backed bot override: inject BOT_DATABASE_URL so the bot actually uses Postgres.
# Used only by test_compose_bot_startup_with_postgres. Probe tests assert this content.
POSTGRES_BOT_OVERRIDE_YAML = """\
services:
  bot:
    environment:
      BOT_DATABASE_URL: postgresql://bot:bot@postgres:5432/bot
"""


def _postgres_bot_override_path(ctx: dict[str, object]) -> str:
    """Write Postgres-bot override file and return its path. Used by Postgres E2E test."""
    artifacts_dir = ctx["artifacts_dir"]
    path = Path(artifacts_dir) / "docker-compose.e2e.postgres-bot.yml"
    path.write_text(POSTGRES_BOT_OVERRIDE_YAML, encoding="utf-8")
    return str(path)


def _shared_env_file_path(ctx: dict[str, object]) -> Path:
    path = Path(ctx["artifacts_dir"]) / ".env.shared.bot"
    path.write_text(
        "\n".join(
            [
                "BOT_PROVIDER=claude",
                "TELEGRAM_BOT_TOKEN=123456:ABC-DEFghijklmnopqrstuvwxyz",
                "BOT_ALLOW_OPEN=1",
                "BOT_WEBHOOK_URL=https://bot.example.com/webhook",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def _shared_runtime_override_path(ctx: dict[str, object]) -> str:
    env_file = _shared_env_file_path(ctx)
    path = Path(ctx["artifacts_dir"]) / "docker-compose.e2e.shared.generated.yml"
    path.write_text(
        "\n".join(
            [
                "services:",
                "  bot-provider:",
                f"    image: {ctx['bot_image']}",
                "    env_file: !override",
                f"      - {env_file}",
                "  bot-webhook:",
                f"    image: {ctx['bot_image']}",
                "    env_file: !override",
                f"      - {env_file}",
                "  bot-worker:",
                f"    image: {ctx['bot_image']}",
                "    env_file: !override",
                f"      - {env_file}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return str(path)


@pytest.fixture(scope="module")
def bot_image_built(compose_ctx):
    """Build the bot image once per module. Shared by SQLite-primary and Postgres-bounded tests."""
    _build_bot_image(compose_ctx)
    return compose_ctx


@pytest.fixture(scope="module")
def compose_ctx_postgres_bot(bot_image_built, postgres_up):
    """Compose context with Postgres-bot override so bot service gets BOT_DATABASE_URL."""
    ctx = dict(bot_image_built)
    override_path = _postgres_bot_override_path(ctx)
    ctx["compose_files"] = list(ctx["compose_files"]) + ["-f", override_path]
    return ctx


def test_compose_postgres_up_without_bot_env(e2e_skip, tmp_path):
    """Clean-repo tooling path: postgres comes up without a bot env file.

    This uses a temp copied Compose stack with no bot env file at all, proving that
    postgres-only tooling does not depend on bot runtime config.
    """
    compose_dir = tmp_path / "infra" / "compose"
    compose_dir.mkdir(parents=True, exist_ok=True)
    compose_base = compose_dir / "docker-compose.yml"
    compose_e2e = compose_dir / "docker-compose.e2e.yml"
    shutil.copy2(os.path.join(REPO_ROOT, "infra/compose/docker-compose.yml"), compose_base)
    shutil.copy2(os.path.join(REPO_ROOT, "infra/compose/docker-compose.e2e.yml"), compose_e2e)
    env = {
        **os.environ,
        "COMPOSE_PROJECT_NAME": f"octopus-agent-e2e-clean-{_worker_id()}-{uuid.uuid4().hex[:8]}",
    }
    cleanup_ctx = {
        "compose_files": ["-f", str(compose_base), "-f", str(compose_e2e)],
        "cwd": tmp_path,
        "project_dir": tmp_path,
        "env": env,
        "artifacts_dir": tmp_path,
    }
    try:
        r = subprocess.run(
            [
                "docker",
                "compose",
                "--project-directory",
                str(tmp_path),
                "-f",
                str(compose_base),
                "-f",
                str(compose_e2e),
                "up",
                "-d",
                "postgres",
            ],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert r.returncode == 0, (r.stdout, r.stderr)
    finally:
        down_result, down_log = _compose_down(cleanup_ctx, "clean-repo-teardown")
        if down_result.returncode != 0:
            details = "Clean-repo Compose cleanup failed."
            if down_log is not None:
                details += f"\n\nCompose cleanup log saved to: {down_log}"
                log_text = down_log.read_text(encoding="utf-8").strip()
                if log_text:
                    details += f"\n\n{log_text}"
            raise AssertionError(details)


def test_compose_bootstrap_doctor(postgres_up):
    """DB bootstrap and doctor succeed against Compose Postgres."""
    r = _compose(postgres_up, "--profile", "tools", "run", "--rm", "db-bootstrap")
    assert r.returncode == 0, (r.stdout, r.stderr)

    r = _compose(postgres_up, "--profile", "tools", "run", "--rm", "db-doctor")
    assert r.returncode == 0, (r.stdout, r.stderr)


def test_compose_db_update_smoke(postgres_up):
    """DB update runs cleanly on an already bootstrapped environment."""
    r = _compose(postgres_up, "--profile", "tools", "run", "--rm", "db-bootstrap")
    assert r.returncode == 0, (r.stdout, r.stderr)
    r = _compose(postgres_up, "--profile", "tools", "run", "--rm", "db-update")
    assert r.returncode == 0, (r.stdout, r.stderr)


def test_compose_bot_image_has_provider(bot_image_built):
    """Supported bot image (Dockerfile.bot) contains the selected provider binary.

    Uses the image built by bot_image_built fixture. Runs claude --version in
    the container with a 60s timeout so interactive auth cannot hang the run.
    """
    r = _compose(
        bot_image_built, "--profile", "bot", "run", "--rm",
        "-e", "BOT_PROVIDER=claude", "-e", "TELEGRAM_BOT_TOKEN=fake", "-e", "BOT_ALLOW_OPEN=1",
        "bot", "sh", "-c", "claude --version",
        timeout=60,
    )
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "claude" in (r.stdout or "").lower() or "claude" in (r.stderr or "").lower()


def _run_bot_foreground_and_capture(ctx: dict[str, object], timeout_seconds: int = 50) -> str:
    """Run bot once in foreground (compose run --rm bot), capture stderr, return decoded text.

    Single bounded wait — no log polling. On timeout we terminate and still capture what we got.
    """
    cmd = ["docker", "compose"]
    project_dir = ctx.get("project_dir")
    if project_dir:
        cmd.extend(["--project-directory", str(project_dir)])
    cmd.extend([*ctx["compose_files"], "--profile", "bot", "run", "--rm", "bot"])
    proc = subprocess.Popen(
        cmd,
        cwd=ctx.get("cwd", REPO_ROOT),
        env=ctx["env"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        out, err = proc.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        proc.terminate()
        try:
            out, err = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, err = proc.communicate(timeout=2)
    return (err or b"").decode("utf-8", errors="replace")


def _run_service_foreground_and_capture(
    ctx: dict[str, object],
    service: str,
    *,
    timeout_seconds: int = 30,
) -> str:
    cmd = ["docker", "compose"]
    project_dir = ctx.get("project_dir")
    if project_dir:
        cmd.extend(["--project-directory", str(project_dir)])
    cmd.extend([*ctx["compose_files"], "--profile", "bot", "run", "--rm", service])
    proc = subprocess.Popen(
        cmd,
        cwd=ctx.get("cwd", REPO_ROOT),
        env=ctx["env"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        out, err = proc.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        proc.terminate()
        try:
            out, err = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, err = proc.communicate(timeout=2)
    return ((out or b"") + (err or b"")).decode("utf-8", errors="replace")


def test_compose_sqlite_local_runtime_primary(bot_image_built):
    """Primary E2E gate: Docker Local Runtime with SQLite (no BOT_DATABASE_URL, no Postgres).

    Bot runs in foreground with one bounded wait. Verifies either successful startup
    (long-poll) or the expected provider-auth failure message.
    """
    stderr = _run_bot_foreground_and_capture(bot_image_built, timeout_seconds=50)
    if "Bot starting (long-poll)" in stderr or "Bot starting (webhook)" in stderr:
        return
    if "Provider not authenticated or unavailable." in stderr and "Run ./scripts/provider/provider_login.sh" in stderr:
        return
    pytest.fail(
        "Bot (SQLite Local Runtime) did not reach startup or emit provider-auth failure. Stderr:\n" + stderr
    )


def test_compose_bot_startup_with_postgres(compose_ctx_postgres_bot):
    """Bounded Postgres path: bot runs with BOT_DATABASE_URL so runtime uses Postgres backend.

    Override injects BOT_DATABASE_URL=postgresql://bot:bot@postgres:5432/bot into the bot
    service. Bootstrap runs first; then bot runs in foreground with one bounded wait.
    """
    ctx = compose_ctx_postgres_bot
    r = _compose(ctx, "--profile", "tools", "run", "--rm", "db-bootstrap")
    assert r.returncode == 0, (r.stdout, r.stderr)
    stderr = _run_bot_foreground_and_capture(ctx, timeout_seconds=50)
    if "Bot starting (long-poll)" in stderr or "Bot starting (webhook)" in stderr:
        return
    if "Provider not authenticated or unavailable." in stderr and "Run ./scripts/provider/provider_login.sh" in stderr:
        return
    pytest.fail(
        "Bot (Postgres backend) did not reach startup or emit provider-auth failure. Stderr:\n" + stderr
    )


def test_compose_shared_runtime_role_smoke(bot_image_built):
    """Shared Runtime override defines split roles and each role reaches its bounded startup seam."""
    ctx = dict(bot_image_built)
    shared_override = _shared_runtime_override_path(ctx)
    ctx["compose_files"] = [
        "-f", os.path.join(REPO_ROOT, "infra/compose/docker-compose.yml"),
        "-f", os.path.join(REPO_ROOT, "infra/compose/docker-compose.shared.yml"),
        "-f", os.path.join(REPO_ROOT, "infra/compose/docker-compose.e2e.yml"),
        "-f", shared_override,
    ]
    ctx["env"] = {**ctx["env"], "COMPOSE_PROJECT_NAME": f"{ctx['project']}-shared"}

    _compose_down(ctx, "shared-preclean")

    services = _compose(ctx, "--profile", "bot", "config", "--services")
    assert services.returncode == 0, (services.stdout, services.stderr)
    listed = set((services.stdout or "").split())
    assert "bot-webhook" in listed
    assert "bot-worker" in listed

    webhook_output = _run_service_foreground_and_capture(ctx, "bot-webhook", timeout_seconds=20)
    assert "Bot starting (webhook)" in webhook_output, webhook_output

    worker_output = _run_service_foreground_and_capture(ctx, "bot-worker", timeout_seconds=20)
    assert (
        "Bot starting (worker-only)" in worker_output
        or (
            "Provider not authenticated or unavailable." in worker_output
            and "Run ./scripts/provider/provider_login.sh" in worker_output
        )
    ), worker_output


def test_compose_bot_stub_smoke(postgres_up):
    """TEST/DEV ONLY: stub-provider image (Dockerfile.runnable) starts and reaches run_polling.

    Run with E2E_USE_STUB_IMAGE=1 when the real provider cannot be installed (e.g. CI
    without network for Claude install). Not the supported runtime path.
    """
    if os.environ.get("E2E_USE_STUB_IMAGE") != "1":
        pytest.skip("Stub image smoke is test/dev-only; set E2E_USE_STUB_IMAGE=1 to run")
    r = _compose(postgres_up, "--profile", "tools", "run", "--rm", "db-bootstrap")
    assert r.returncode == 0, (r.stdout, r.stderr)
    proc = subprocess.Popen(
        ["docker", "compose", *postgres_up["compose_files"], "--profile", "stub", "run", "--rm",
         "-e", "TELEGRAM_BOT_TOKEN=123456:ABC-DEFghijklmnopqrstuvwxyz",
         "-e", "BOT_PROVIDER=claude", "-e", "BOT_ALLOW_OPEN=1",
         "bot-stub"],
        cwd=REPO_ROOT,
        env=postgres_up["env"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        out, err = proc.communicate(timeout=15)
    except subprocess.TimeoutExpired:
        proc.terminate()
        try:
            proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate(timeout=2)
    if b"Bot starting (long-poll)" not in (err or b"") and b"Bot starting (webhook)" not in (err or b""):
        pytest.fail(f"Stub image did not reach run_polling: stderr={err!r}")


def test_compose_registry_ui_conversation_detail(postgres_up):
    """Registry UI can create a conversation and receive a bot-published started event.

    Uses the real Compose-hosted registry service plus the production registry
    client and RegistryChannelEgress on the host. This keeps the E2E focused on
    M7's contract: UI-created work, polled delivery, and channel-owned timeline
    publication, without depending on Telegram startup or provider auth.
    """
    import asyncio

    from app.agents.client import AgentRegistryClient
    from app.agents.state import save_registry_connection_state
    from app.agents.types import RegistryConnectionState
    from app.agents.types import AgentCard
    from app.channels.registry.egress import RegistryChannelEgress
    from app.channels.registry.refs import registry_conversation_ref
    from tests.support.config_support import make_config, make_registry_connection

    ctx = _registry_ui_ctx(postgres_up)
    registry_up = _compose(ctx, "--profile", "registry", "up", "-d", "registry")
    assert registry_up.returncode == 0, (registry_up.stdout, registry_up.stderr)
    _wait_for_registry_ready(ctx)
    base_url = _registry_url(ctx)

    async def _exercise_registry_flow() -> str:
        enroll_client = AgentRegistryClient(base_url)
        requested = AgentCard(
            display_name="Registry E2E Bot",
            slug="registry-e2e-bot",
            role="product",
            capabilities=("planning",),
            provider="claude",
            mode="registry",
            connectivity_state="connected",
            channel_capabilities=("registry",),
            version="e2e",
        )
        enrolled = await enroll_client.enroll(requested, _E2E_REGISTRY_ENROLL_TOKEN)
        agent_id = str(enrolled["agent_id"])
        agent_token = str(enrolled["agent_token"])
        cfg = make_config(
            data_dir=Path(ctx["artifacts_dir"]) / "registry-e2e-agent",
            agent_mode="registry",
            agent_registries=(
                make_registry_connection(url=base_url, enroll_token=_E2E_REGISTRY_ENROLL_TOKEN),
            ),
            agent_display_name="Registry E2E Bot",
            agent_slug=str(enrolled["slug"]),
        )
        save_registry_connection_state(
            cfg.data_dir,
            RegistryConnectionState(
                registry_id="default",
                agent_id=agent_id,
                agent_token=agent_token,
                connectivity_state="connected",
            ),
        )
        client = AgentRegistryClient(base_url, agent_token=agent_token)
        registered = AgentCard(
            agent_id=agent_id,
            display_name="Registry E2E Bot",
            slug=str(enrolled["slug"]),
            role="product",
            capabilities=("planning",),
            provider="claude",
            mode="registry",
            connectivity_state="connected",
            channel_capabilities=("registry",),
            version="e2e",
        )
        await client.register(
            registered,
            connectivity_state="connected",
            current_capacity=0,
            max_capacity=1,
        )

        conversation = _http_json(
            "POST",
            f"{base_url}/v1/ui/conversations",
            token=_E2E_REGISTRY_UI_TOKEN,
            payload={
                "target_agent_id": agent_id,
                "title": "Registry UI E2E",
                "message_text": "Start this from the registry UI.",
            },
        )
        conversation_id = str(conversation["conversation_id"])

        deliveries = await client.poll(cursor="0", limit=20, wait_seconds=0)
        assert deliveries["deliveries"], deliveries
        delivery = deliveries["deliveries"][0]
        assert delivery["kind"] == "channel_input"
        channel_egress = RegistryChannelEgress(
            cfg,
            conversation_ref=registry_conversation_ref("default", conversation_id),
        )
        await channel_egress.bind(title="Registry UI E2E", config=cfg)
        await client.ack([delivery["delivery_id"]], classification="accepted")
        return conversation_id

    conversation_id = asyncio.run(_exercise_registry_flow())
    deadline = time.time() + 30
    while time.time() < deadline:
        timeline = _http_json(
            "GET",
            f"{base_url}/v1/ui/conversations/{conversation_id}/timeline",
            token=_E2E_REGISTRY_UI_TOKEN,
        )
        if any(event.get("kind") == "started" for event in timeline.get("events", [])):
            return
        time.sleep(1)

    _fail_with_logs(
        ctx,
        "registry-ui-timeline-timeout",
        f"Registry UI conversation did not receive a started event for {conversation_id}.",
        "registry",
    )


def test_compose_registry_ui_delegation_flow(postgres_up):
    """Registry UI can approve delegation and receive the parent completion flow."""
    import asyncio

    from app.agents.client import AgentRegistryClient
    from app.agents.delivery import handle_registry_delivery
    from app.agents.state import save_registry_connection_state
    from app.agents.types import AgentCard, RoutedTaskResult
    from app.agents.types import RegistryConnectionState
    from app.providers.base import RunResult
    from tests.support.config_support import make_config, make_registry_connection
    from tests.support.handler_support import (
        FakeProvider,
        current_bot_instance,
        drain_one_worker_item,
        make_registry_delivery_runtime,
        setup_globals,
    )

    ctx = _registry_ui_ctx(postgres_up)
    registry_up = _compose(ctx, "--profile", "registry", "up", "-d", "registry")
    assert registry_up.returncode == 0, (registry_up.stdout, registry_up.stderr)
    _wait_for_registry_ready(ctx)
    base_url = _registry_url(ctx)

    async def _exercise_registry_flow() -> str:
        enroll_client = AgentRegistryClient(base_url)
        requested_parent = AgentCard(
            display_name="Registry Parent Bot",
            slug="registry-parent-bot",
            role="product",
            capabilities=("planning", "delegation"),
            provider="claude",
            mode="registry",
            connectivity_state="connected",
            channel_capabilities=("registry",),
            version="e2e",
        )
        requested_child = AgentCard(
            display_name="Registry Child Bot",
            slug="registry-child-bot",
            role="developer",
            capabilities=("implementation",),
            provider="claude",
            mode="registry",
            connectivity_state="connected",
            channel_capabilities=("registry",),
            version="e2e",
        )
        enrolled_parent = await enroll_client.enroll(requested_parent, _E2E_REGISTRY_ENROLL_TOKEN)
        enrolled_child = await enroll_client.enroll(requested_child, _E2E_REGISTRY_ENROLL_TOKEN)

        parent_id = str(enrolled_parent["agent_id"])
        parent_token = str(enrolled_parent["agent_token"])
        child_id = str(enrolled_child["agent_id"])
        child_token = str(enrolled_child["agent_token"])

        cfg = make_config(
            data_dir=Path(ctx["artifacts_dir"]) / "registry-e2e-parent",
            agent_mode="registry",
            agent_registries=(
                make_registry_connection(url=base_url, enroll_token=_E2E_REGISTRY_ENROLL_TOKEN),
            ),
            agent_display_name="Registry Parent Bot",
            agent_slug=str(enrolled_parent["slug"]),
            approval_mode="off",
        )
        save_registry_connection_state(
            cfg.data_dir,
            RegistryConnectionState(
                registry_id="default",
                agent_id=parent_id,
                agent_token=parent_token,
                connectivity_state="connected",
            ),
        )
        parent_client = AgentRegistryClient(base_url, agent_token=parent_token)
        child_client = AgentRegistryClient(base_url, agent_token=child_token)
        await parent_client.register(
            AgentCard(
                agent_id=parent_id,
                display_name="Registry Parent Bot",
                slug=str(enrolled_parent["slug"]),
                role="product",
                capabilities=("planning", "delegation"),
                provider="claude",
                mode="registry",
                connectivity_state="connected",
                channel_capabilities=("registry",),
                version="e2e",
            ),
            connectivity_state="connected",
            current_capacity=0,
            max_capacity=1,
        )
        await child_client.register(
            AgentCard(
                agent_id=child_id,
                display_name="Registry Child Bot",
                slug=str(enrolled_child["slug"]),
                role="developer",
                capabilities=("implementation",),
                provider="claude",
                mode="registry",
                connectivity_state="connected",
                channel_capabilities=("registry",),
                version="e2e",
            ),
            connectivity_state="connected",
            current_capacity=0,
            max_capacity=1,
        )

        provider = FakeProvider("claude")
        provider.run_results = [
            RunResult(
                text="",
                delegation_title="Registry UI delegation",
                delegation_resume_instruction="Synthesize the child result and answer the user.",
                delegation_tasks=[
                    {
                        "routed_task_id": "child-task-e2e",
                        "title": "Implement the feature",
                        "target_agent_id": child_id,
                        "instructions": "Build the feature and report back.",
                    }
                ],
            ),
            RunResult(text="Final parent answer from delegation."),
        ]
        setup_globals(cfg, provider)
        delivery_runtime = make_registry_delivery_runtime(
            cfg,
            provider,
            bot_instance=current_bot_instance(),
        )

        conversation = _http_json(
            "POST",
            f"{base_url}/v1/ui/conversations",
            token=_E2E_REGISTRY_UI_TOKEN,
            payload={
                "target_agent_id": parent_id,
                "title": "Registry UI delegation flow",
                "message_text": "Delegate this work and finish it.",
            },
        )
        conversation_id = str(conversation["conversation_id"])

        initial_poll = await parent_client.poll(cursor="0", limit=20, wait_seconds=0)
        initial_delivery = initial_poll["deliveries"][0]
        assert initial_delivery["kind"] == "channel_input"
        assert await handle_registry_delivery(
            cfg,
            initial_delivery,
            runtime=delivery_runtime,
        ) == "accepted"
        await parent_client.ack([initial_delivery["delivery_id"]], classification="accepted")
        assert await drain_one_worker_item(cfg.data_dir) is True

        approval_deadline = time.time() + 30
        while time.time() < approval_deadline:
            timeline = _http_json(
                "GET",
                f"{base_url}/v1/ui/conversations/{conversation_id}/timeline",
                token=_E2E_REGISTRY_UI_TOKEN,
            )
            if any(event.get("kind") == "delegation_proposed" for event in timeline.get("events", [])):
                break
            time.sleep(1)
        else:
            raise AssertionError("delegation_proposed event did not appear in the registry timeline")

        _http_json(
            "POST",
            f"{base_url}/v1/ui/conversations/{conversation_id}/actions",
            token=_E2E_REGISTRY_UI_TOKEN,
            payload={"action": "approve_delegation"},
        )

        approve_poll = await parent_client.poll(cursor=initial_poll["next_cursor"], limit=20, wait_seconds=0)
        approve_delivery = next(item for item in approve_poll["deliveries"] if item["kind"] == "channel_action")
        assert await handle_registry_delivery(
            cfg,
            approve_delivery,
            runtime=delivery_runtime,
        ) == "accepted"
        await parent_client.ack([approve_delivery["delivery_id"]], classification="accepted")
        assert await drain_one_worker_item(cfg.data_dir) is True

        child_poll = await child_client.poll(cursor="0", limit=20, wait_seconds=0)
        child_delivery = next(item for item in child_poll["deliveries"] if item["kind"] == "routed_task")
        await child_client.ack([child_delivery["delivery_id"]], classification="accepted")
        await child_client.routed_task_result(
            "child-task-e2e",
            RoutedTaskResult(
                routed_task_id="child-task-e2e",
                status="completed",
                summary="Child task complete",
                full_text="Child bot completed the delegated task.",
            ),
        )

        routed_result_poll = await parent_client.poll(cursor=approve_poll["next_cursor"], limit=20, wait_seconds=0)
        routed_result_delivery = next(item for item in routed_result_poll["deliveries"] if item["kind"] == "routed_result")
        assert await handle_registry_delivery(
            cfg,
            routed_result_delivery,
            runtime=delivery_runtime,
        ) == "accepted"
        await parent_client.ack([routed_result_delivery["delivery_id"]], classification="accepted")
        assert await drain_one_worker_item(cfg.data_dir) is True
        return conversation_id

    conversation_id = asyncio.run(_exercise_registry_flow())
    deadline = time.time() + 30
    while time.time() < deadline:
        timeline = _http_json(
            "GET",
            f"{base_url}/v1/ui/conversations/{conversation_id}/timeline",
            token=_E2E_REGISTRY_UI_TOKEN,
        )
        bodies = [event.get("body", "") for event in timeline.get("events", [])]
        if any("All delegated tasks completed." in body for body in bodies) and any(
            "Final parent answer from delegation." in body for body in bodies
        ):
            return
        time.sleep(1)

    _fail_with_logs(
        ctx,
        "registry-ui-delegation-timeout",
        f"Registry UI delegation flow did not complete for conversation {conversation_id}.",
        "registry",
    )
