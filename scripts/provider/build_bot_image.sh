#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_DIR"

provider="${1:-${BOT_PROVIDER:-claude}}"
case "$provider" in
  claude|codex) ;;
  *)
    echo "BOT_PROVIDER must be 'claude' or 'codex', got: $provider" >&2
    echo "Usage: $0 [claude|codex]" >&2
    exit 1
    ;;
esac

mkdir -p "$REPO_DIR/.deploy/logs"
build_log="$REPO_DIR/.deploy/logs/docker-build-$provider.log"

build_args=(
  --build-arg "BOT_PROVIDER=$provider"
  --build-arg "CLAUDE_INSTALL_METHOD=${CLAUDE_INSTALL_METHOD:-npm}"
  --build-arg "CLAUDE_CLI_NPM_PACKAGE=${CLAUDE_CLI_NPM_PACKAGE:-@anthropic-ai/claude-code}"
  --build-arg "CLAUDE_INSTALL_URL=${CLAUDE_INSTALL_URL:-https://claude.ai/install.sh}"
)

print_build_failure_summary() {
  local provider="$1" log_path="$2"

  if grep -Eqi 'registry-1\.docker\.io|failed to resolve source metadata|python:3\.12-slim|TLS handshake timeout|Client\.Timeout exceeded while awaiting headers|no route to host' "$log_path"; then
    cat >&2 <<EOF
Base image fetch failed while pulling python:3.12-slim from Docker Hub.
This is usually a Docker/Desktop network or proxy issue, not a bot configuration problem.
Try: docker pull python:3.12-slim
EOF
  elif [ "$provider" = "claude" ] && grep -Eqi 'Claude CLI npm install failed|npm ERR!|@anthropic-ai/claude-code' "$log_path"; then
    cat >&2 <<EOF
Claude image build failed while installing the Claude CLI from npm.
Set CLAUDE_CLI_NPM_PACKAGE to pin a version, or set CLAUDE_INSTALL_METHOD=native to try Anthropic's native installer instead.
EOF
  elif [ "$provider" = "claude" ] && grep -Eqi 'Claude native installer download failed|Claude native installer failed after download|claude\.ai/install\.sh' "$log_path"; then
    cat >&2 <<EOF
Claude image build failed while running Anthropic's native installer.
Unset CLAUDE_INSTALL_METHOD or set CLAUDE_INSTALL_METHOD=npm to use the default npm install path instead.
EOF
  else
    echo "Bot image build failed for provider '$provider'." >&2
  fi

  echo "Full docker build log: $log_path" >&2
}

echo "Building bot image for provider: $provider"
echo "Build log: $build_log"

set +e
docker build -f infra/docker/Dockerfile.bot "${build_args[@]}" -t "octopus-agent:$provider" "$REPO_DIR" 2>&1 | tee "$build_log"
build_rc=${PIPESTATUS[0]}
set -e

if [ "$build_rc" -ne 0 ]; then
  print_build_failure_summary "$provider" "$build_log"
  exit "$build_rc"
fi

