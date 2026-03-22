#!/usr/bin/env bash
# Compose wrappers and image checks.

check_provider_image() {
  local provider="${1:-}"
  if [ -z "$provider" ]; then
    provider=$(get_bot_provider)
  fi
  if ! docker image inspect "octopus-agent:$provider" >/dev/null 2>&1; then
    echo "Image octopus-agent:$provider not found." >&2
    echo "Run: ./scripts/provider/build_bot_image.sh $provider" >&2
    exit 1
  fi
  echo "$provider"
}

ensure_network() {
  if ! docker network inspect octopus-net >/dev/null 2>&1; then
    docker network create octopus-net
  fi
}

bot_compose() {
  local slug="${1:-}"
  [ -n "$slug" ] || {
    echo "bot_compose requires a bot slug." >&2
    return 1
  }
  shift
  local env_file=".deploy/bots/$slug/.env"
  [ -f "$env_file" ] || { echo "No env file for bot '$slug'" >&2; return 1; }
  local provider
  provider="$(read_bot_env_value BOT_PROVIDER "$env_file")"
  local provider_auth_dir=".deploy/provider-auth/${provider:-claude}"
  mkdir -p "$provider_auth_dir"
  chmod 700 "$provider_auth_dir" 2>/dev/null || true
  # Workspace compose override: volumes + env_file for workspace-member bots.
  # Must be last in the -f chain so workspace env_file entries are appended
  # after the bot .env (last-wins for duplicate keys like BOT_PROJECTS).
  local workspace_compose=".deploy/bots/$slug/docker-compose.workspace.yml"
  local workspace_flags=""
  if [ -f "$workspace_compose" ]; then
    workspace_flags="-f $workspace_compose"
  fi
  ensure_network
  OCTOPUS_NETWORK="octopus-net" \
  PROVIDER_AUTH_DIR="$provider_auth_dir" \
  BOT_ENV_FILE="$env_file" \
  REGISTRY_ENROLL_TOKEN="${REGISTRY_ENROLL_TOKEN:-placeholder-registry-enroll}" \
  REGISTRY_UI_TOKEN="${REGISTRY_UI_TOKEN:-placeholder-registry-ui}" \
  docker compose \
    --project-directory . \
    -p "octopus-${slug}" \
    -f infra/compose/docker-compose.yml \
    $workspace_flags \
    --profile bot \
    --env-file "$env_file" \
    "$@"
}

bot_shared_compose() {
  local slug="${1:-}"
  [ -n "$slug" ] || {
    echo "bot_shared_compose requires a bot slug." >&2
    return 1
  }
  shift
  local env_file=".deploy/bots/$slug/.env"
  [ -f "$env_file" ] || { echo "No env file for bot '$slug'" >&2; return 1; }
  local provider
  provider="$(read_bot_env_value BOT_PROVIDER "$env_file")"
  local provider_auth_dir=".deploy/provider-auth/${provider:-claude}"
  mkdir -p "$provider_auth_dir"
  chmod 700 "$provider_auth_dir" 2>/dev/null || true
  # Workspace override is LAST: base → shared → workspace
  local workspace_compose=".deploy/bots/$slug/docker-compose.workspace.yml"
  local workspace_flags=""
  if [ -f "$workspace_compose" ]; then
    workspace_flags="-f $workspace_compose"
  fi
  ensure_network
  OCTOPUS_NETWORK="octopus-net" \
  PROVIDER_AUTH_DIR="$provider_auth_dir" \
  BOT_ENV_FILE="$env_file" \
  REGISTRY_ENROLL_TOKEN="${REGISTRY_ENROLL_TOKEN:-placeholder-registry-enroll}" \
  REGISTRY_UI_TOKEN="${REGISTRY_UI_TOKEN:-placeholder-registry-ui}" \
  docker compose --project-directory . \
    -p "octopus-${slug}" \
    -f infra/compose/docker-compose.yml \
    -f infra/compose/docker-compose.shared.yml \
    $workspace_flags \
    --env-file "$env_file" \
    "$@"
}

registry_compose() {
  ensure_network
  OCTOPUS_NETWORK="octopus-net" \
  docker compose \
    --project-directory . \
    -p "octopus-registry" \
    -f infra/compose/docker-compose.yml \
    --profile registry \
    --env-file .deploy/registry/.env \
    "$@"
}

provider_compose() {
  local provider="$1"; shift
  local auth_dir=".deploy/provider-auth/$provider"
  mkdir -p "$auth_dir"
  chmod 700 "$auth_dir"
  ensure_network
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
    "$@"
}
