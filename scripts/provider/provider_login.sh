#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_DIR"

provider="${1:-${BOT_PROVIDER:-}}"
case "$provider" in
  claude|codex) ;;
  *)
    echo "Usage: ./scripts/provider/provider_login.sh <claude|codex>" >&2
    exit 1
    ;;
esac

auth_dir=".deploy/provider-auth/$provider"
mkdir -p "$auth_dir"
chmod 700 "$auth_dir"
if [ "$provider" = "claude" ]; then
  mkdir -p "$auth_dir/.claude"
  [ -f "$auth_dir/.claude.json" ] || : > "$auth_dir/.claude.json"
else
  mkdir -p "$auth_dir/.codex"
fi

if ! docker image inspect "octopus-agent:$provider" >/dev/null 2>&1; then
  echo "Image octopus-agent:$provider not found. Run ./octopus redeploy bots or ./scripts/provider/build_bot_image.sh $provider first." >&2
  exit 1
fi

if ! docker network inspect octopus-net >/dev/null 2>&1; then
  docker network create octopus-net >/dev/null
fi

echo "Provider login (BOT_PROVIDER=$provider). Uses shared provider auth under .deploy/provider-auth/$provider."
OCTOPUS_NETWORK="octopus-net" \
BOT_PROVIDER="$provider" \
PROVIDER_AUTH_DIR="$auth_dir" \
BOT_ENV_FILE="/dev/null" \
REGISTRY_ENROLL_TOKEN="${REGISTRY_ENROLL_TOKEN:-placeholder-registry-enroll}" \
REGISTRY_UI_TOKEN="${REGISTRY_UI_TOKEN:-placeholder-registry-ui}" \
docker compose \
  --project-directory . \
  -p "octopus-auth-${provider}" \
  -f infra/compose/docker-compose.yml \
  --profile bot \
  run --rm bot-provider sh /app/scripts/provider/container_provider_login.sh

