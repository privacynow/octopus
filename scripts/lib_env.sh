# Shared env and image checks for scripts that require .env.bot.
# Source after: REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)" and cd "$REPO_DIR".
# Usage: source "$(dirname "$0")/lib_env.sh"  (from a script in scripts/).

current_bot_env_file() {
  if [ -n "${BOT_ENV_FILE:-}" ]; then
    echo "$BOT_ENV_FILE"
    return
  fi
  if [ -n "${1:-}" ] && [ -f ".env.bot.$1" ]; then
    echo ".env.bot.$1"
    return
  fi
  echo ".env.bot"
}

current_bot_instance() {
  local env_file="${1:-$(current_bot_env_file)}"
  case "$env_file" in
    .env.bot.*) echo "${env_file#.env.bot.}" ;;
    *) echo "default" ;;
  esac
}

check_env_bot_required() {
  local env_file="${1:-$(current_bot_env_file)}"
  if [ ! -f "$env_file" ]; then
    if [ "$env_file" = ".env.bot" ]; then
      echo "Create .env.bot first (TELEGRAM_BOT_TOKEN, BOT_PROVIDER, BOT_ALLOWED_USERS or BOT_ALLOW_OPEN=1)." >&2
    else
      echo "Create .env.bot first for the default bot, or create $env_file for this instance (TELEGRAM_BOT_TOKEN, BOT_PROVIDER, BOT_ALLOWED_USERS or BOT_ALLOW_OPEN=1)." >&2
    fi
    exit 1
  fi
}

# Echo BOT_PROVIDER from the selected env file (claude or codex), default claude.
get_bot_provider() {
  local env_file="${1:-$(current_bot_env_file)}"
  local p
  p=$(grep -E '^\s*BOT_PROVIDER=' "$env_file" 2>/dev/null | sed 's/.*=\s*//' | tr -d '\r' | tr -d '"' | tr -d "'" || true)
  echo "${p:-claude}"
}

# Exit with message if image octopus-agent:$1 is missing. Call with provider from get_bot_provider or arg.
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
