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

bot_compose() {
  local env_file="${BOT_ENV_FILE:-$(current_bot_env_file)}"
  local project="${BOT_COMPOSE_PROJECT:-}"
  if [ -z "$project" ] && [ "$env_file" != ".env.bot" ]; then
    project="octopus-agent-$(current_bot_instance "$env_file")"
  fi
  if [ -n "$project" ]; then
    docker compose --project-directory . -p "$project" -f infra/compose/docker-compose.yml --profile bot --env-file "$env_file" "$@"
    return
  fi
  docker compose --project-directory . -f infra/compose/docker-compose.yml --profile bot --env-file "$env_file" "$@"
}

bot_shared_compose() {
  local env_file="${BOT_ENV_FILE:-$(current_bot_env_file)}"
  local project="${BOT_COMPOSE_PROJECT:-}"
  if [ -z "$project" ] && [ "$env_file" != ".env.bot" ]; then
    project="octopus-agent-$(current_bot_instance "$env_file")"
  fi
  if [ -n "$project" ]; then
    docker compose --project-directory . -p "$project" \
      -f infra/compose/docker-compose.yml \
      -f infra/compose/docker-compose.shared.yml \
      --env-file "$env_file" "$@"
    return
  fi
  docker compose --project-directory . \
    -f infra/compose/docker-compose.yml \
    -f infra/compose/docker-compose.shared.yml \
    --env-file "$env_file" "$@"
}
