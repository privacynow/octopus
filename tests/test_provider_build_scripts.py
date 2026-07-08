from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _make_fake_install_bin(tmp_path: Path) -> tuple[Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    command_log = tmp_path / "commands.log"

    _write_executable(
        bin_dir / "apt-get",
        """#!/usr/bin/env bash
set -euo pipefail
printf 'apt-get:%s\\n' "$*" >> "$TEST_COMMAND_LOG"
exit 0
""",
    )
    _write_executable(
        bin_dir / "npm",
        """#!/usr/bin/env bash
set -euo pipefail
printf 'npm:%s\\n' "$*" >> "$TEST_COMMAND_LOG"
exit 0
""",
    )
    _write_executable(
        bin_dir / "curl",
        """#!/usr/bin/env bash
set -euo pipefail
printf 'curl:%s\\n' "$*" >> "$TEST_COMMAND_LOG"
output=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    -o)
      output="$2"
      shift 2
      ;;
    *)
      shift
      ;;
  esac
done
if [ -n "$output" ]; then
  cat > "$output" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
fi
exit 0
""",
    )
    _write_executable(
        bin_dir / "claude",
        """#!/usr/bin/env bash
set -euo pipefail
printf 'claude-test 1.0.0\\n'
""",
    )

    return bin_dir, command_log


def _install_env(bin_dir: Path, command_log: Path, tmp_path: Path, **extra: str) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(tmp_path / "home"),
            "PATH": f"{bin_dir}:{env['PATH']}",
            "TEST_COMMAND_LOG": str(command_log),
        }
    )
    env.update(extra)
    return env


def _make_temp_build_repo(tmp_path: Path) -> Path:
    repo_root = tmp_path / "repo"
    for relative_path in ("scripts/provider/build_bot_image.sh",):
        dest = repo_root / relative_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / relative_path, dest)
    (repo_root / "infra/docker").mkdir(parents=True, exist_ok=True)
    (repo_root / "infra/docker/Dockerfile.bot").write_text("# fake\n", encoding="utf-8")
    return repo_root


def _make_fake_build_bin(tmp_path: Path, docker_output: str, docker_exit: int = 1) -> tuple[Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker_output_path = tmp_path / "docker-output.log"
    docker_output_path.write_text(docker_output, encoding="utf-8")
    command_log = tmp_path / "docker-commands.log"

    _write_executable(
        bin_dir / "docker",
        """#!/usr/bin/env bash
set -euo pipefail
printf 'docker:%s\\n' "$*" >> "$TEST_COMMAND_LOG"
cat "$TEST_DOCKER_OUTPUT"
exit "${TEST_DOCKER_EXIT:-1}"
""",
    )
    _write_executable(
        bin_dir / "git",
        """#!/usr/bin/env bash
set -euo pipefail
if [ "${1:-}" = "rev-parse" ]; then
  printf 'deadbeef\\n'
  exit 0
fi
exit 1
""",
    )

    env = tmp_path / "env"
    env.write_text("", encoding="utf-8")
    return bin_dir, command_log


def test_bot_dockerfile_installs_common_stage_toolchain() -> None:
    dockerfile = (REPO_ROOT / "infra/docker/Dockerfile.bot").read_text(encoding="utf-8")
    expected_packages = {
        "bind9-dnsutils",
        "build-essential",
        "chromium",
        "cmake",
        "curl",
        "fonts-liberation",
        "git",
        "gosu",
        "iproute2",
        "iputils-ping",
        "jq",
        "libasound2t64",
        "libatk-bridge2.0-0t64",
        "libatk1.0-0t64",
        "libatspi2.0-0t64",
        "libcairo2",
        "libcups2t64",
        "libdbus-1-3",
        "libdrm2",
        "libfontconfig1",
        "libfreetype6",
        "libgbm1",
        "libglib2.0-0t64",
        "libgtk-3-0t64",
        "libharfbuzz0b",
        "libnspr4",
        "libnss3",
        "libpango-1.0-0",
        "libx11-6",
        "libx11-xcb1",
        "libxcb1",
        "libxcomposite1",
        "libxdamage1",
        "libxext6",
        "libxfixes3",
        "libxkbcommon0",
        "libxrandr2",
        "libxrender1",
        "libxshmfence1",
        "libxtst6",
        "maven",
        "netcat-openbsd",
        "nodejs",
        "npm",
        "openjdk-21-jdk-headless",
        "pkg-config",
        "ripgrep",
        "sudo",
        "unzip",
        "xvfb",
        "zip",
    }

    for package in expected_packages:
        assert package in dockerfile

    assert dockerfile.count("apt-get install") == 1
    assert "pip install --no-cache-dir playwright==1.56.0" in dockerfile
    assert "bot ALL=(root) NOPASSWD:ALL" in dockerfile


def test_install_provider_claude_defaults_to_npm(tmp_path: Path) -> None:
    script = REPO_ROOT / "scripts/provider/install_provider_claude.sh"
    bin_dir, command_log = _make_fake_install_bin(tmp_path)

    result = subprocess.run(
        ["bash", str(script)],
        capture_output=True,
        text=True,
        env=_install_env(bin_dir, command_log, tmp_path),
    )

    assert result.returncode == 0, result.stderr
    logged = command_log.read_text(encoding="utf-8")
    assert "npm:install -g @anthropic-ai/claude-code" in logged
    assert "curl:" not in logged


def test_install_provider_claude_supports_native_override(tmp_path: Path) -> None:
    script = REPO_ROOT / "scripts/provider/install_provider_claude.sh"
    bin_dir, command_log = _make_fake_install_bin(tmp_path)

    result = subprocess.run(
        ["bash", str(script)],
        capture_output=True,
        text=True,
        env=_install_env(bin_dir, command_log, tmp_path, CLAUDE_INSTALL_METHOD="native"),
    )

    assert result.returncode == 0, result.stderr
    logged = command_log.read_text(encoding="utf-8")
    assert "curl:-fsSL https://claude.ai/install.sh -o " in logged
    assert "npm:" not in logged


def test_build_bot_image_classifies_docker_hub_failures(tmp_path: Path) -> None:
    repo_root = _make_temp_build_repo(tmp_path)
    docker_output = """
ERROR: failed to build: failed to solve: python:3.12-slim: failed to resolve source metadata for docker.io/library/python:3.12-slim
failed to do request: Head "https://registry-1.docker.io/v2/library/python/manifests/3.12-slim": dial tcp [2600:1f18::1]:443: connect: no route to host
"""
    bin_dir, command_log = _make_fake_build_bin(tmp_path, docker_output)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "TEST_COMMAND_LOG": str(command_log),
            "TEST_DOCKER_OUTPUT": str(tmp_path / "docker-output.log"),
            "TEST_DOCKER_EXIT": "1",
        }
    )

    result = subprocess.run(
        ["bash", str(repo_root / "scripts/provider/build_bot_image.sh"), "claude"],
        capture_output=True,
        text=True,
        cwd=repo_root,
        env=env,
    )

    combined = result.stdout + result.stderr
    log_path = repo_root / ".deploy/logs/docker-build-claude.log"
    assert result.returncode == 1
    assert "Base image fetch failed while pulling python:3.12-slim from Docker Hub." in combined
    assert f"Full docker build log: {log_path}" in combined
    assert log_path.read_text(encoding="utf-8") == docker_output


def test_build_bot_image_classifies_claude_npm_failures(tmp_path: Path) -> None:
    repo_root = _make_temp_build_repo(tmp_path)
    docker_output = """
npm ERR! code ECONNRESET
npm ERR! request to https://registry.npmjs.org/@anthropic-ai/claude-code failed, reason: socket hang up
Claude CLI npm install failed for package @anthropic-ai/claude-code.
"""
    bin_dir, command_log = _make_fake_build_bin(tmp_path, docker_output)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "TEST_COMMAND_LOG": str(command_log),
            "TEST_DOCKER_OUTPUT": str(tmp_path / "docker-output.log"),
            "TEST_DOCKER_EXIT": "1",
            "CLAUDE_CLI_NPM_PACKAGE": "@anthropic-ai/claude-code@1.2.3",
        }
    )

    result = subprocess.run(
        ["bash", str(repo_root / "scripts/provider/build_bot_image.sh"), "claude"],
        capture_output=True,
        text=True,
        cwd=repo_root,
        env=env,
    )

    combined = result.stdout + result.stderr
    logged = command_log.read_text(encoding="utf-8")
    assert result.returncode == 1
    assert "Claude image build failed while installing the Claude CLI from npm." in combined
    assert "--build-arg CLAUDE_CLI_NPM_PACKAGE=@anthropic-ai/claude-code@1.2.3" in logged


def test_build_bot_image_passes_no_provider_cli_overrides_by_default(tmp_path: Path) -> None:
    """Without explicit env overrides, the Dockerfile ARG defaults (including
    the pinned CLI version) must govern: no CLAUDE_*/CODEX_* build args."""
    repo_root = _make_temp_build_repo(tmp_path)
    bin_dir, command_log = _make_fake_build_bin(tmp_path, "ok", docker_exit=0)
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"CLAUDE_INSTALL_METHOD", "CLAUDE_CLI_NPM_PACKAGE", "CLAUDE_INSTALL_URL", "CODEX_CLI_NPM_PACKAGE"}
    }
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "TEST_COMMAND_LOG": str(command_log),
            "TEST_DOCKER_OUTPUT": str(tmp_path / "docker-output.log"),
            "TEST_DOCKER_EXIT": "0",
        }
    )

    result = subprocess.run(
        ["bash", str(repo_root / "scripts/provider/build_bot_image.sh"), "claude"],
        capture_output=True,
        text=True,
        cwd=repo_root,
        env=env,
    )

    logged = command_log.read_text(encoding="utf-8")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "--build-arg BOT_PROVIDER=claude" in logged
    for key in ("CLAUDE_INSTALL_METHOD", "CLAUDE_CLI_NPM_PACKAGE", "CLAUDE_INSTALL_URL", "CODEX_CLI_NPM_PACKAGE"):
        assert key not in logged, f"{key} must not be forwarded when unset: {logged}"
