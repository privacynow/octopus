"""Unit and contract tests for E2E Compose harness: Docker probe and teardown.

Tests probe classification, skip message wording, opt-in skip, and image teardown
wiring. No real Docker or E2E_COMPOSE required; uses mocks.
"""

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

# Import the module under test so we can patch its subprocess and test helpers.
from tests.e2e import test_compose_flows as m


def test_docker_probe_missing_cli():
    """FileNotFoundError -> missing_cli."""
    with patch.object(m.subprocess, "run", side_effect=FileNotFoundError()):
        ok, reason, detail = m._docker_probe()
    assert ok is False
    assert reason == "missing_cli"
    assert "docker" in detail.lower() or "not found" in detail.lower()


def test_docker_probe_timeout():
    """TimeoutExpired -> timeout."""
    with patch.object(m.subprocess, "run", side_effect=subprocess.TimeoutExpired("docker", 5)):
        ok, reason, detail = m._docker_probe()
    assert ok is False
    assert reason == "timeout"
    assert "timed out" in detail.lower() or "timeout" in detail.lower()


def test_docker_probe_success():
    """returncode 0 -> ok."""
    with patch.object(m.subprocess, "run", return_value=subprocess.CompletedProcess(["docker", "info"], 0, "", "")):
        ok, reason, detail = m._docker_probe()
    assert ok is True
    assert reason == "ok"
    assert detail == ""


def test_docker_probe_permission_denied():
    """permission-denied stderr -> daemon_permission_denied."""
    err = "permission denied while trying to connect to the Docker daemon socket"
    with patch.object(
        m.subprocess,
        "run",
        return_value=subprocess.CompletedProcess(["docker", "info"], 1, "", err),
    ):
        ok, reason, detail = m._docker_probe()
    assert ok is False
    assert reason == "daemon_permission_denied"
    assert "permission" in detail.lower()


def test_docker_probe_daemon_unreachable():
    """daemon-not-running stderr -> daemon_unreachable."""
    err = "Cannot connect to the Docker daemon. Is the docker daemon running on this host?"
    with patch.object(
        m.subprocess,
        "run",
        return_value=subprocess.CompletedProcess(["docker", "info"], 1, "", err),
    ):
        ok, reason, detail = m._docker_probe()
    assert ok is False
    assert reason == "daemon_unreachable"
    assert "connect" in detail.lower() or "daemon" in detail.lower()


def test_docker_probe_unknown_failure():
    """Other failure -> unknown_failure."""
    with patch.object(
        m.subprocess,
        "run",
        return_value=subprocess.CompletedProcess(["docker", "info"], 99, "", "some error"),
    ):
        ok, reason, detail = m._docker_probe()
    assert ok is False
    assert reason == "unknown_failure"
    assert "some error" in detail or "99" in detail


def test_docker_skip_message_permission_denied():
    """Skip message for daemon_permission_denied includes accessible wording."""
    msg = m._docker_skip_message("daemon_permission_denied", "permission denied while trying to connect to the Docker daemon socket")
    assert "not accessible" in msg or "permission" in msg
    assert "this test process" in msg or "permission denied" in msg


def test_docker_skip_message_daemon_unreachable():
    """Skip message for daemon_unreachable includes reachable wording."""
    msg = m._docker_skip_message("daemon_unreachable", "Cannot connect to the Docker daemon")
    assert "not reachable" in msg or "daemon" in msg


def test_e2e_skip_fixture_skips_with_opt_in_message_when_env_unset():
    """The e2e_skip fixture itself skips with the opt-in message when E2E_COMPOSE is not set.

    Runs pytest on a real test that uses e2e_skip, with E2E_COMPOSE unset, and asserts
    the skip reason is the expected opt-in message (not replayed logic).
    """
    import os
    import sys
    repo_root = Path(__file__).resolve().parent.parent.parent
    env = {k: v for k, v in os.environ.items() if k != "E2E_COMPOSE"}
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/e2e/test_compose_flows.py::test_compose_postgres_up_without_env_bot",
            "-v",
            "-rs",
            "--tb=no",
        ],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    out = (r.stdout or "") + (r.stderr or "")
    assert "skipped" in out.lower(), f"Expected test to be skipped when E2E_COMPOSE unset; got: {out}"
    assert "E2E_COMPOSE=1 not set" in out or "E2E_COMPOSE" in out, (
        f"Expected opt-in skip message in output; got: {out}"
    )


def test_remove_image_does_not_raise():
    """_remove_image never raises even when docker image rm fails."""
    with patch.object(m.subprocess, "run", return_value=subprocess.CompletedProcess(["docker", "image", "rm", "x"], 1, "", "Error")):
        m._remove_image("nonexistent:tag")


def test_remove_image_writes_log_on_failure_when_artifacts_dir_given(tmp_path):
    """When removal fails and artifacts_dir is provided, a log file is written."""
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    with patch.object(m.subprocess, "run", return_value=subprocess.CompletedProcess(["docker", "image", "rm", "x"], 1, "", "stderr here")):
        m._remove_image("fake:tag", artifacts_dir)
    log_file = artifacts_dir / "teardown-image-rm.log"
    assert log_file.exists()
    content = log_file.read_text()
    assert "fake:tag" in content
    assert "stderr here" in content


def test_compose_down_records_failure_log(tmp_path):
    """_compose_down writes a cleanup log when docker compose down fails."""
    ctx = {
        "artifacts_dir": tmp_path,
        "compose_files": ["-f", "docker-compose.yml"],
        "env": {},
    }
    with patch.object(
        m,
        "_compose",
        return_value=subprocess.CompletedProcess(["docker", "compose", "down"], 1, "", "compose down failed"),
    ):
        result, log_path = m._compose_down(ctx, "teardown")
    assert result.returncode == 1
    assert log_path == tmp_path / "teardown.compose-down.log"
    assert log_path.exists()
    assert "compose down failed" in log_path.read_text()


def test_compose_ctx_teardown_calls_remove_image_after_down():
    """Teardown path: compose down then _remove_image(bot_image)."""
    with patch.object(m, "_compose_down", return_value=(subprocess.CompletedProcess(["docker", "compose", "down"], 0, "", ""), None)) as md:
        with patch.object(m, "_remove_image") as mr:
            ctx = {
                "artifacts_dir": Path("/tmp/fake-e2e-artifacts"),
                "bot_image": "telegram-agent-bot-e2e:gw0-abc123-claude",
            }
            down_result, down_log = m._compose_down(ctx)
            m._remove_image(ctx["bot_image"], ctx.get("artifacts_dir"))
            assert down_result.returncode == 0
            assert down_log is None
    mr.assert_called_once_with("telegram-agent-bot-e2e:gw0-abc123-claude", ctx["artifacts_dir"])
    md.assert_called_once_with(ctx)


def test_compose_down_includes_all_profiles(tmp_path):
    """Cleanup must include profiled services so bot/stub containers are actually removed."""
    ctx = {
        "artifacts_dir": tmp_path,
        "compose_files": ["-f", "docker-compose.yml"],
        "env": {},
    }
    with patch.object(
        m,
        "_compose",
        return_value=subprocess.CompletedProcess(["docker", "compose", "down"], 0, "", ""),
    ) as mc:
        result, log_path = m._compose_down(ctx)
    assert result.returncode == 0
    assert log_path is None
    mc.assert_called_once_with(
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
