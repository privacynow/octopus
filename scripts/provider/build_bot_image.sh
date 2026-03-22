#!/usr/bin/env bash
# Build the supported bot image for the chosen provider (real Claude or Codex CLI).
# Usage: ./scripts/provider/build_bot_image.sh [claude|codex]
# Usage: ./scripts/provider/build_bot_image.sh [claude|codex]
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_DIR"
# shellcheck source=scripts/lib/bot.sh
. "$REPO_DIR/scripts/lib/bot.sh"

provider="${1:-${BOT_PROVIDER:-claude}}"
case "$provider" in
  claude|codex) ;;
  *)
    echo "BOT_PROVIDER must be 'claude' or 'codex', got: $provider" >&2
    echo "Usage: $0 [claude|codex]" >&2
    exit 1
    ;;
esac

echo "Building bot image for provider: $provider"
docker build -f infra/docker/Dockerfile.bot --build-arg BOT_PROVIDER="$provider" -t "octopus-agent:$provider" "$REPO_DIR"
# Record repo rev so octopus can detect pulls/deletions and force rebuild
git rev-parse HEAD 2>/dev/null > "$REPO_DIR/.bot-image-build-rev" || true
