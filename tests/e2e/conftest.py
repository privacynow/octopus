"""E2E test configuration: auto-enable E2E_COMPOSE when Docker is available.

The e2e_skip fixture in test_compose_flows.py checks E2E_COMPOSE=1 before
probing Docker. This conftest sets it automatically when Docker is reachable
so the e2e suite runs on any machine that has Docker — no manual env-var
required. CI or developer machines without Docker skip cleanly via the
_docker_probe() guard that follows.
"""

import os


def pytest_configure(config):
    """Set E2E_COMPOSE=1 when Docker is available, so e2e tests run automatically.

    Set E2E_COMPOSE_NO_AUTODETECT=1 to suppress auto-detection (used by meta-tests
    that verify the explicit opt-in skip message still works when the var is unset).
    """
    if os.environ.get("E2E_COMPOSE") is None and not os.environ.get("E2E_COMPOSE_NO_AUTODETECT"):
        try:
            import subprocess
            r = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                timeout=5,
                check=False,
            )
            if r.returncode == 0:
                os.environ["E2E_COMPOSE"] = "1"
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
