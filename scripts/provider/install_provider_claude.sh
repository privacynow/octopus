#!/usr/bin/env bash
# Install Claude CLI into the container. Used by infra/docker/Dockerfile.bot when BOT_PROVIDER=claude.
# Defaults to Anthropic's documented npm install path. The native installer remains available via
# CLAUDE_INSTALL_METHOD=native for environments that specifically require it.
set -euo pipefail

CLAUDE_INSTALL_METHOD="${CLAUDE_INSTALL_METHOD:-npm}"
CLAUDE_CLI_NPM_PACKAGE="${CLAUDE_CLI_NPM_PACKAGE:-@anthropic-ai/claude-code@2.1.201}"
CLAUDE_INSTALL_URL="${CLAUDE_INSTALL_URL:-https://claude.ai/install.sh}"
INSTALL_RETRY_ATTEMPTS="${INSTALL_RETRY_ATTEMPTS:-3}"
INSTALL_RETRY_DELAY_SECONDS="${INSTALL_RETRY_DELAY_SECONDS:-5}"

retry() {
  local attempt=1
  until "$@"; do
    if [ "$attempt" -ge "$INSTALL_RETRY_ATTEMPTS" ]; then
      return 1
    fi
    sleep "$INSTALL_RETRY_DELAY_SECONDS"
    attempt=$((attempt + 1))
  done
}

install_from_npm() {
  apt-get update
  apt-get install -y --no-install-recommends ca-certificates nodejs npm
  if ! retry npm install -g "$CLAUDE_CLI_NPM_PACKAGE"; then
    echo "Claude CLI npm install failed for package $CLAUDE_CLI_NPM_PACKAGE." >&2
    echo "Set CLAUDE_CLI_NPM_PACKAGE to pin a version, or CLAUDE_INSTALL_METHOD=native to try Anthropic's native installer." >&2
    return 1
  fi
}

install_from_native() {
  local installer_path=""
  apt-get update
  apt-get install -y --no-install-recommends curl ca-certificates
  installer_path="$(mktemp "${TMPDIR:-/tmp}/claude-install.XXXXXX.sh")"
  if ! retry curl -fsSL "$CLAUDE_INSTALL_URL" -o "$installer_path"; then
    rm -f "$installer_path"
    echo "Claude native installer download failed (URL: $CLAUDE_INSTALL_URL)." >&2
    echo "The native installer is optional; unset CLAUDE_INSTALL_METHOD or set CLAUDE_INSTALL_METHOD=npm to use the npm package instead." >&2
    return 1
  fi
  if ! bash "$installer_path"; then
    rm -f "$installer_path"
    echo "Claude native installer failed after download (URL: $CLAUDE_INSTALL_URL)." >&2
    return 1
  fi
  rm -f "$installer_path"
}

case "$CLAUDE_INSTALL_METHOD" in
  npm)
    install_from_npm
    ;;
  native)
    install_from_native
    ;;
  *)
    echo "CLAUDE_INSTALL_METHOD must be 'npm' or 'native', got: $CLAUDE_INSTALL_METHOD" >&2
    exit 1
    ;;
esac

apt-get autoremove -y --purge 2>/dev/null || true
rm -rf /var/lib/apt/lists/* /root/.npm

claude --version >/dev/null 2>&1 || /root/.local/bin/claude --version >/dev/null 2>&1 || true
