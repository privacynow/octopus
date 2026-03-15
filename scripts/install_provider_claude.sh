#!/usr/bin/env bash
# Install Claude CLI into the container. Used by Dockerfile.bot when BOT_PROVIDER=claude.
# Official method: install script from Claude (see https://claude.ai). Set CLAUDE_INSTALL_URL
# if the default is unavailable. Requires network.
set -euo pipefail
CLAUDE_INSTALL_URL="${CLAUDE_INSTALL_URL:-https://claude.ai/install.sh}"
apt-get update
apt-get install -y --no-install-recommends curl ca-certificates
if ! curl -fsSL "$CLAUDE_INSTALL_URL" | bash; then
  echo "Claude CLI install failed (URL: $CLAUDE_INSTALL_URL). Set CLAUDE_INSTALL_URL or install manually." >&2
  exit 1
fi
apt-get purge -y curl 2>/dev/null || true
apt-get autoremove -y --purge 2>/dev/null || true
rm -rf /var/lib/apt/lists/*
echo 'export PATH="${HOME}/.local/bin:${PATH}"' >> /root/.bashrc
export PATH="${HOME}/.local/bin:${PATH}"
claude --version || true
