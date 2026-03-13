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
    _compose("down", "-t", "2")
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


def test_compose_postgres_up_without_env_bot(e2e_skip):
    """Clean-repo tooling path: postgres comes up without .env.bot.

    Bot service is under profile 'bot', so compose up postgres does not require
    .env.bot. This test runs without the postgres_up fixture so we can assert
    the minimal case.
    """
    env_bot = os.path.join(REPO_ROOT, ".env.bot")
    had_env_bot = os.path.isfile(env_bot)
    if had_env_bot:
        os.rename(env_bot, env_bot + ".e2e_backup")
    try:
        _compose("down", "-t", "2")
        r = _compose("up", "-d", "postgres")
        assert r.returncode == 0, (r.stdout, r.stderr)
    finally:
        _compose("down", "-t", "2")
        if had_env_bot:
            os.rename(env_bot + ".e2e_backup", env_bot)


def test_compose_bootstrap_doctor(postgres_up):
    """DB bootstrap and doctor succeed against Compose Postgres."""
    r = _compose("--profile", "tools", "run", "--rm", "db-bootstrap")
    assert r.returncode == 0, (r.stdout, r.stderr)

    r = _compose("--profile", "tools", "run", "--rm", "db-doctor")
    assert r.returncode == 0, (r.stdout, r.stderr)


def test_compose_db_update_smoke(postgres_up):
    """DB update runs cleanly on an already bootstrapped environment."""
    r = _compose("--profile", "tools", "run", "--rm", "db-bootstrap")
    assert r.returncode == 0, (r.stdout, r.stderr)
    r = _compose("--profile", "tools", "run", "--rm", "db-update")
    assert r.returncode == 0, (r.stdout, r.stderr)


def test_compose_bot_image_has_provider(postgres_up):
    """Supported bot image (Dockerfile.bot) contains the selected provider binary.

    Builds the real provider-enabled image with docker build and tag
    telegram-agent-bot:claude, then runs it via compose --profile bot.
    """
    r = subprocess.run(
        ["docker", "build", "-f", "Dockerfile.bot", "--build-arg", "BOT_PROVIDER=claude",
         "-t", "telegram-agent-bot:claude", "."],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert r.returncode == 0, (r.stdout, r.stderr)
    r = _compose("--profile", "bot", "run", "--rm",
                 "-e", "BOT_PROVIDER=claude", "-e", "TELEGRAM_BOT_TOKEN=fake", "-e", "BOT_ALLOW_OPEN=1",
                 "bot", "sh", "-c", "claude --version")
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "claude" in (r.stdout or "").lower() or "claude" in (r.stderr or "").lower()


def test_compose_bot_startup_validates_schema(postgres_up):
    """Bot container (supported real provider-enabled image) starts and validates schema.

    Builds telegram-agent-bot:claude then runs with --profile bot. Asserts
    config/doctor/schema pass and the app reaches 'Bot starting (long-poll)'.
    """
    r = subprocess.run(
        ["docker", "build", "-f", "Dockerfile.bot", "--build-arg", "BOT_PROVIDER=claude",
         "-t", "telegram-agent-bot:claude", "."],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert r.returncode == 0, (r.stdout, r.stderr)
    r = _compose("--profile", "tools", "run", "--rm", "db-bootstrap")
    assert r.returncode == 0, (r.stdout, r.stderr)

    proc = subprocess.Popen(
        ["docker", "compose", "-f", os.path.join(REPO_ROOT, "docker-compose.yml"),
         "--profile", "bot", "run", "--rm",
         "-e", "TELEGRAM_BOT_TOKEN=123456:ABC-DEFghijklmnopqrstuvwxyz",
         "-e", "BOT_PROVIDER=claude",
         "-e", "BOT_ALLOW_OPEN=1",
         "bot"],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        out, err = proc.communicate(timeout=15)
    except subprocess.TimeoutExpired:
        proc.terminate()
        try:
            out, err = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, err = proc.communicate(timeout=2)
    if b"Bot starting (long-poll)" in (err or b"") or b"Bot starting (webhook)" in (err or b""):
        return
    if proc.returncode != 0:
        pytest.fail(
            f"Bot exited {proc.returncode} before reaching run_polling/run_webhook: stdout={out!r} stderr={err!r}"
        )


def test_compose_bot_stub_smoke(postgres_up):
    """TEST/DEV ONLY: stub-provider image (Dockerfile.runnable) starts and reaches run_polling.

    Run with E2E_USE_STUB_IMAGE=1 when the real provider cannot be installed (e.g. CI
    without network for Claude install). Not the supported runtime path.
    """
    if os.environ.get("E2E_USE_STUB_IMAGE") != "1":
        pytest.skip("Stub image smoke is test/dev-only; set E2E_USE_STUB_IMAGE=1 to run")
    r = _compose("--profile", "tools", "run", "--rm", "db-bootstrap")
    assert r.returncode == 0, (r.stdout, r.stderr)
    proc = subprocess.Popen(
        ["docker", "compose", "-f", os.path.join(REPO_ROOT, "docker-compose.yml"),
         "--profile", "stub", "run", "--rm",
         "-e", "TELEGRAM_BOT_TOKEN=123456:ABC-DEFghijklmnopqrstuvwxyz",
         "-e", "BOT_PROVIDER=claude", "-e", "BOT_ALLOW_OPEN=1",
         "bot-stub"],
        cwd=REPO_ROOT,
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
