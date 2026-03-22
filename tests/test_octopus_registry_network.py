from __future__ import annotations

import socket
import stat
import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent


def _run_bash(script: str, *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-lc", script],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=True,
    )


def test_pick_available_port_skips_bound_port(tmp_path: Path) -> None:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    port = sock.getsockname()[1]
    try:
        script = f"""
set -euo pipefail
source "{REPO}/scripts/lib/registry.sh"
pick_available_port {port}
"""
        result = _run_bash(script, cwd=tmp_path)
    finally:
        sock.close()

    picked = int(result.stdout.strip())
    assert picked > port


def test_ensure_local_registry_bootstraps_env_and_starts_registry(tmp_path: Path) -> None:
    script = f"""
set -euo pipefail
source "{REPO}/scripts/lib/state.sh"
source "{REPO}/scripts/lib/registry.sh"
cd "{tmp_path}"
ensure_deploy_dirs
registry_is_running() {{ return 1; }}
has_local_registry() {{ return 1; }}
registry_compose() {{ printf '%s\\n' "$*" > registry-call.txt; }}
ensure_local_registry
test -f .deploy/registry/.env
grep -q '^REGISTRY_BIND_HOST=127.0.0.1$' .deploy/registry/.env
grep -q '^REGISTRY_ALLOW_HTTP=1$' .deploy/registry/.env
grep -q '^REGISTRY_PORT=' .deploy/registry/.env
grep -q '^REGISTRY_ENROLL_TOKEN=' .deploy/registry/.env
grep -q '^REGISTRY_UI_TOKEN=' .deploy/registry/.env
test "$REGISTRY_WAS_CREATED" = "1"
test "$(cat registry-call.txt)" = 'up -d --remove-orphans service'
"""
    _run_bash(script, cwd=tmp_path)

    env_file = tmp_path / ".deploy" / "registry" / ".env"
    mode = stat.S_IMODE(env_file.stat().st_mode)
    assert mode == 0o600


def test_ensure_local_registry_reuses_existing_env(tmp_path: Path) -> None:
    env_file = tmp_path / ".deploy" / "registry" / ".env"
    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_text(
        "REGISTRY_BIND_HOST=127.0.0.1\n"
        "REGISTRY_PORT=9005\n"
        "REGISTRY_ALLOW_HTTP=1\n"
        "REGISTRY_ENROLL_TOKEN=keep-me\n"
        "REGISTRY_UI_TOKEN=keep-ui\n"
    )
    env_file.chmod(0o600)

    script = f"""
set -euo pipefail
source "{REPO}/scripts/lib/state.sh"
source "{REPO}/scripts/lib/registry.sh"
cd "{tmp_path}"
registry_is_running() {{ return 1; }}
has_local_registry() {{ return 0; }}
registry_compose() {{ printf '%s\\n' "$*" > registry-call.txt; }}
ensure_local_registry
test "$REGISTRY_WAS_CREATED" = "0"
test "$(cat registry-call.txt)" = 'up -d --remove-orphans service'
"""
    _run_bash(script, cwd=tmp_path)

    assert "keep-me" in env_file.read_text()


def test_compose_uses_external_network_and_registry_alias() -> None:
    text = (REPO / "infra" / "compose" / "docker-compose.yml").read_text()
    assert "name: ${OCTOPUS_NETWORK:-octopus-net}" in text
    assert "external: true" in text
    assert "  data:" in text
    assert "aliases:" in text
    assert "- registry" in text
    assert "container_name:" not in text
    assert "  service:" in text


def test_registry_wrappers_use_octopus_project_and_deploy_env() -> None:
    docker_lib = (REPO / "scripts" / "lib" / "docker.sh").read_text()
    state_lib = (REPO / "scripts" / "lib" / "state.sh").read_text()
    start_script = (REPO / "scripts" / "registry" / "start.sh").read_text()
    stop_script = (REPO / "scripts" / "registry" / "stop.sh").read_text()

    assert '-p "octopus-registry"' in docker_lib
    assert '-p "octopus-auth-${provider}"' in docker_lib
    assert "--env-file .deploy/registry/.env" in docker_lib
    assert 'ps --status running service' in state_lib
    assert "ensure_local_registry" in start_script
    assert 'ENV_FILE=".deploy/registry/.env"' in start_script
    assert "registry_compose down --remove-orphans" in stop_script
