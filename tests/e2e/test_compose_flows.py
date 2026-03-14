"""Compose-based E2E tests for the Docker-first operator path.

Run only when E2E_COMPOSE=1 and Docker is available. Skipped in normal pytest runs.
See README.md for the operator path and docs/ARCHITECTURE.md for the runtime/testing contract.

The harness isolates each worker/run with:
- a unique COMPOSE_PROJECT_NAME
- a generated override file for worker-local bot env and image tags
- no host Postgres port publication

That lets these tests run safely alongside a local dev stack and across concurrent test runs.
"""

import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

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
    return subprocess.run(
        ["docker", "compose", *ctx["compose_files"], *args],
        cwd=ctx.get("cwd", REPO_ROOT),
        env=ctx["env"],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _compose_logs(ctx: dict[str, object], name: str, *services: str) -> tuple[Path, str]:
    result = _compose(ctx, "logs", "--no-color", *services, timeout=120)
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


@pytest.fixture(scope="module")
def compose_ctx(e2e_skip, tmp_path_factory):
    worker = _worker_id()
    run_id = uuid.uuid4().hex[:10]
    project = f"telegram-agent-bot-e2e-{worker}-{run_id}"
    artifacts_dir = tmp_path_factory.mktemp(f"compose-e2e-{worker}")
    env_file = Path(artifacts_dir) / ".env.bot"
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
    bot_image = f"telegram-agent-bot-e2e:{worker}-{run_id}-claude"
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
            "-f", os.path.join(REPO_ROOT, "docker-compose.yml"),
            "-f", os.path.join(REPO_ROOT, "docker-compose.e2e.yml"),
            "-f", str(generated_override),
        ],
        "cwd": REPO_ROOT,
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


@pytest.fixture(scope="module")
def postgres_up(compose_ctx):
    """Bring up Postgres and wait for healthy. Module teardown is handled by compose_ctx."""
    r = _compose(compose_ctx, "up", "-d", "postgres")
    assert r.returncode == 0, (r.stdout, r.stderr)
    for _ in range(30):
        r = _compose(compose_ctx, "exec", "postgres", "pg_isready", "-U", "bot", "-d", "bot")
        if r.returncode == 0:
            break
        time.sleep(1)
    else:
        _fail_with_logs(compose_ctx, "postgres-not-ready", "Postgres did not become ready", "postgres")
    return compose_ctx


@pytest.fixture(scope="module")
def bot_image_built(postgres_up):
    """Build the bot image once for all tests that need it. Avoids a second ~5 min build."""
    r = subprocess.run(
        ["docker", "build", "-f", "Dockerfile.bot", "--build-arg", "BOT_PROVIDER=claude",
         "-t", str(postgres_up["bot_image"]), "."],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert r.returncode == 0, (r.stdout, r.stderr)
    return postgres_up


def test_compose_postgres_up_without_env_bot(e2e_skip, tmp_path):
    """Clean-repo tooling path: postgres comes up without .env.bot.

    This uses a temp copied Compose stack with no .env.bot at all, proving that
    postgres-only tooling does not depend on bot runtime config.
    """
    compose_base = tmp_path / "docker-compose.yml"
    compose_e2e = tmp_path / "docker-compose.e2e.yml"
    shutil.copy2(os.path.join(REPO_ROOT, "docker-compose.yml"), compose_base)
    shutil.copy2(os.path.join(REPO_ROOT, "docker-compose.e2e.yml"), compose_e2e)
    env = {
        **os.environ,
        "COMPOSE_PROJECT_NAME": f"telegram-agent-bot-e2e-clean-{_worker_id()}-{uuid.uuid4().hex[:8]}",
    }
    cleanup_ctx = {
        "compose_files": ["-f", str(compose_base), "-f", str(compose_e2e)],
        "cwd": tmp_path,
        "env": env,
        "artifacts_dir": tmp_path,
    }
    try:
        r = subprocess.run(
            [
                "docker",
                "compose",
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


def test_compose_bot_startup_validates_schema(bot_image_built):
    """Supported bot image validates DB/schema, then fails clearly without provider auth.

    In CI/local E2E we do not perform an interactive provider login, so the real
    provider-enabled image should reach DB/schema validation and then emit the
    operator-facing provider-auth failure message rather than hanging or failing
    obscurely.

    Uses the image built by bot_image_built (single shared build for bot-image tests).
    The bot runs provider.check_runtime_health() before printing that message; we
    wait up to 35s for the message (health check has its own timeouts).
    """
    r = _compose(bot_image_built, "--profile", "tools", "run", "--rm", "db-bootstrap")
    assert r.returncode == 0, (r.stdout, r.stderr)
    r = _compose(bot_image_built, "--profile", "bot", "up", "-d", "bot")
    assert r.returncode == 0, (r.stdout, r.stderr)
    for _ in range(35):
        _, logs = _compose_logs(bot_image_built, "bot-startup", "bot", "postgres")
        if "Bot starting (long-poll)" in logs or "Bot starting (webhook)" in logs:
            return
        if "Provider not authenticated or unavailable." in logs and "Run ./scripts/provider_login.sh" in logs:
            return
        time.sleep(1)
    _fail_with_logs(
        bot_image_built,
        "bot-startup-timeout",
        "Bot did not reach startup or emit the expected provider-auth failure within 35 seconds (provider health check may block on interactive auth).",
        "bot",
        "postgres",
    )


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
