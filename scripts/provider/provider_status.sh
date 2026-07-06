#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_DIR"

provider="${1:-${BOT_PROVIDER:-}}"
case "$provider" in
  claude|codex) ;;
  *)
    echo "Usage: ./scripts/provider/provider_status.sh <claude|codex>" >&2
    exit 1
    ;;
esac

auth_dir=".deploy/provider-auth/$provider"
mkdir -p "$auth_dir"
chmod 700 "$auth_dir"

if ! docker image inspect "octopus-agent:$provider" >/dev/null 2>&1; then
  echo "Image octopus-agent:$provider not found. Run ./octopus redeploy bots or ./scripts/provider/build_bot_image.sh $provider first." >&2
  exit 1
fi

if ! docker network inspect octopus-net >/dev/null 2>&1; then
  docker network create octopus-net >/dev/null
fi

echo "Provider auth and runtime only (no DB/Telegram checks)."
if OCTOPUS_NETWORK="octopus-net" \
  BOT_PROVIDER="$provider" \
  OCTOPUS_RUNTIME_IMAGE="octopus-agent:$provider" \
  PROVIDER_AUTH_DIR="$auth_dir" \
  BOT_ENV_FILE="/dev/null" \
  REGISTRY_ENROLL_TOKEN="${REGISTRY_ENROLL_TOKEN:-placeholder-registry-enroll}" \
  REGISTRY_UI_TOKEN="${REGISTRY_UI_TOKEN:-placeholder-registry-ui}" \
  docker compose \
    --project-directory . \
    -p "octopus-auth-${provider}" \
    -f infra/compose/docker-compose.yml \
    --profile bot \
    run --rm bot-provider; then
  touch "$auth_dir/.authed"
  echo "Success here does NOT prove a bot can start."
  echo "For full bot health run: ./octopus doctor <bot>."
else
  rm -f "$auth_dir/.authed"
  exit 1
fi
