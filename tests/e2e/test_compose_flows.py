"""Compose-based E2E tests for Phase 12: bootstrap, doctor, optional bot startup.

Run only when E2E_COMPOSE=1 and Docker is available. Skipped in normal pytest runs.
See README.md for the operator path and docs/ARCHITECTURE.md for the runtime/testing contract.
"""

import os
import subprocess
import time

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _docker_available() -> bool:
    try:
        subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=5,
            check=False,
        )
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _compose(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", "compose", "-f", os.path.join(REPO_ROOT, "docker-compose.yml"), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )


@pytest.fixture(scope="module")
def e2e_skip():
    """Skip entire module unless E2E_COMPOSE=1 and Docker available."""
    if os.environ.get("E2E_COMPOSE") != "1":
        pytest.skip("E2E_COMPOSE=1 not set")
    if not _docker_available():
        pytest.skip("Docker not available")


@pytest.fixture(scope="module")
def postgres_up(e2e_skip):
    """Bring up Postgres and wait for healthy. Tear down at module end."""
    r = _compose("up", "-d", "postgres")
    assert r.returncode == 0, (r.stdout, r.stderr)
    for _ in range(30):
        r = _compose("exec", "postgres", "pg_isready", "-U", "bot", "-d", "bot")
        if r.returncode == 0:
            break
        time.sleep(1)
    else:
        _compose("down", "-t", "2")
        pytest.fail("Postgres did not become ready")
    yield
    _compose("down", "-t", "2")


def test_compose_bootstrap_doctor(postgres_up):
    """DB bootstrap and doctor succeed against Compose Postgres."""
    r = _compose("--profile", "tools", "run", "--rm", "db-bootstrap")
    assert r.returncode == 0, (r.stdout, r.stderr)

    r = _compose("--profile", "tools", "run", "--rm", "db-doctor")
    assert r.returncode == 0, (r.stdout, r.stderr)


def test_compose_bot_startup_validates_schema(postgres_up):
    """Bot container starts and validates Postgres schema (runs 5s without exit 1).

    Skipped unless E2E_BOT_IMAGE_RUNNABLE=1: the default image does not include
    the provider CLI (claude/codex), so the bot would exit 1 on config/startup.
    Run this only when using a customized image that includes the provider.
    """
    if os.environ.get("E2E_BOT_IMAGE_RUNNABLE") != "1":
        pytest.skip(
            "Default image has no provider CLI; set E2E_BOT_IMAGE_RUNNABLE=1 "
            "when using a customized image to run this test."
        )
    r = _compose("--profile", "tools", "run", "--rm", "db-bootstrap")
    assert r.returncode == 0, (r.stdout, r.stderr)

    # Minimal env required by config: token, provider, and allow-open or allowed-users
    proc = subprocess.Popen(
        ["docker", "compose", "-f", os.path.join(REPO_ROOT, "docker-compose.yml"),
         "run", "--rm",
         "-e", "TELEGRAM_BOT_TOKEN=123456:ABC-DEFghijklmnopqrstuvwxyz",
         "-e", "BOT_PROVIDER=claude",
         "-e", "BOT_ALLOW_OPEN=1",
         "bot"],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        for _ in range(5):
            time.sleep(1)
            if proc.poll() is not None and proc.returncode == 1:
                out, err = proc.communicate(timeout=2)
                pytest.fail(f"Bot exited 1 (schema validation?): stdout={out!r} stderr={err!r}")
        # Still running after 5s => schema validated and app entered main loop or polling
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
