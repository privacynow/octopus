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
  case "$slug" in
    ""|-*|up|down|start|stop|restart|logs|ps|run|exec|config|pull|build)
      # Temporary compatibility path while remaining legacy scripts still exist.
      local env_file="${BOT_ENV_FILE:-$(current_bot_env_file)}"
      local project="${BOT_COMPOSE_PROJECT:-}"
      if [ -z "$project" ] && [ "$env_file" != ".env.bot" ]; then
        project="octopus-agent-$(current_bot_instance "$env_file")"
      fi
      ensure_network
      if [ -n "$project" ]; then
        OCTOPUS_NETWORK="octopus-net" \
          REGISTRY_ENROLL_TOKEN="${REGISTRY_ENROLL_TOKEN:-placeholder-registry-enroll}" \
          REGISTRY_UI_TOKEN="${REGISTRY_UI_TOKEN:-placeholder-registry-ui}" \
          docker compose --project-directory . -p "$project" -f infra/compose/docker-compose.yml --profile bot --env-file "$env_file" "$@"
        return
      fi
      OCTOPUS_NETWORK="octopus-net" \
        REGISTRY_ENROLL_TOKEN="${REGISTRY_ENROLL_TOKEN:-placeholder-registry-enroll}" \
        REGISTRY_UI_TOKEN="${REGISTRY_UI_TOKEN:-placeholder-registry-ui}" \
        docker compose --project-directory . -f infra/compose/docker-compose.yml --profile bot --env-file "$env_file" "$@"
      return
      ;;
  esac

  shift
  local env_file=".deploy/bots/$slug/.env"
  [ -f "$env_file" ] || { echo "No env file for bot '$slug'" >&2; return 1; }
  local provider
  provider="$(read_bot_env_value BOT_PROVIDER "$env_file")"
  local provider_auth_dir=".deploy/provider-auth/${provider:-claude}"
  mkdir -p "$provider_auth_dir"
  chmod 700 "$provider_auth_dir" 2>/dev/null || true
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
    --profile bot \
    --env-file "$env_file" \
    "$@"
}

bot_shared_compose() {
  local env_file="${BOT_ENV_FILE:-$(current_bot_env_file)}"
  local project="${BOT_COMPOSE_PROJECT:-}"
  if [ -z "$project" ] && [ "$env_file" != ".env.bot" ]; then
    project="octopus-agent-$(current_bot_instance "$env_file")"
  fi
  if [ -n "$project" ]; then
    OCTOPUS_NETWORK="octopus-net" \
    REGISTRY_ENROLL_TOKEN="${REGISTRY_ENROLL_TOKEN:-placeholder-registry-enroll}" \
    REGISTRY_UI_TOKEN="${REGISTRY_UI_TOKEN:-placeholder-registry-ui}" \
    docker compose --project-directory . -p "$project" \
      -f infra/compose/docker-compose.yml \
      -f infra/compose/docker-compose.shared.yml \
      --env-file "$env_file" \
      "$@"
    return
  fi
  REGISTRY_ENROLL_TOKEN="${REGISTRY_ENROLL_TOKEN:-placeholder-registry-enroll}" \
  REGISTRY_UI_TOKEN="${REGISTRY_UI_TOKEN:-placeholder-registry-ui}" \
  docker compose --project-directory . \
    -f infra/compose/docker-compose.yml \
    -f infra/compose/docker-compose.shared.yml \
    --env-file "$env_file" "$@"
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
    -p "octopus-provider-${provider}" \
    -f infra/compose/docker-compose.yml \
    --profile bot \
    "$@"
}
