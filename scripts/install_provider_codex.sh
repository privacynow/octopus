#!/usr/bin/env bash
# Install Codex CLI into the container. Used by Dockerfile.bot when BOT_PROVIDER=codex.
# Uses npm @openai/codex (Node 18+). May require network.
set -euo pipefail
apt-get update
apt-get install -y --no-install-recommends curl ca-certificates
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt-get install -y nodejs
npm install -g @openai/codex
apt-get purge -y curl 2>/dev/null || true
apt-get autoremove -y --purge 2>/dev/null || true
rm -rf /var/lib/apt/lists/* /root/.npm
codex --version || true
