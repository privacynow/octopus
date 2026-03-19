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

print_channel_setup_help() {
  local channel="${1:-telegram}"
  case "$channel" in
    telegram)
      cat >&2 <<'EOF'
You need a Telegram bot token before the bot can start.

  Step 1: Open BotFather in Telegram:
          https://t.me/BotFather

  Step 2: Send:    /newbot
  Step 3: Pick a display name, e.g.  My Product Bot
  Step 4: Pick a username ending in 'bot', e.g.  my_product_bot
  Step 5: BotFather replies with your token. Copy the full token here.

If you already created the bot, paste the token now.
EOF
      ;;
    *)
      echo "Unsupported channel '$channel' in print_channel_setup_help" >&2
      return 1
      ;;
  esac
}

channel_token_looks_plausible() {
  local channel="${1:-telegram}" value="${2:-}"
  case "$channel" in
    telegram)
      [[ "$value" =~ ^[0-9]+:[A-Za-z0-9_-]+$ ]]
      ;;
    *)
      return 1
      ;;
  esac
}

prompt_channel_token_with_help() {
  local channel="${1:-telegram}" prompt_label="${2:-Paste your bot token here}" token=""
  print_channel_setup_help "$channel"
  while true; do
    read -r -p "$prompt_label: " token || true
    if [ -z "$token" ]; then
      echo "Token is required. Try again." >&2
      continue
    fi
    if telegram_token_is_placeholder "$token"; then
      echo "That still looks like a placeholder token." >&2
      echo "Copy the full token from BotFather and try again." >&2
      continue
    fi
    if ! channel_token_looks_plausible "$channel" "$token"; then
      echo "Token format looks wrong." >&2
      echo "Telegram tokens look like digits:letters from BotFather." >&2
      continue
    fi
    printf '%s' "$token"
    return 0
  done
}

registry_url_is_local() {
  local value="${1:-}"
  case "$value" in
    http://localhost:*|http://127.0.0.1:*|http://[::1]:*|http://host.docker.internal:*|http://172.17.0.1:*)
      return 0
      ;;
  esac
  return 1
}

restrict_secret_file_permissions() {
  local path="${1:-}"
  [ -n "$path" ] || return 1
  chmod 600 "$path"
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

read_bot_env_value() {
  local key="$1" env_file="${2:-$(current_bot_env_file)}"
  grep -E "^\s*${key}=" "$env_file" 2>/dev/null | sed 's/.*=\s*//' | tr -d '\r' | tr -d '"' | tr -d "'" || true
}

telegram_token_is_placeholder() {
  local value="${1:-}" normalized
  normalized="$(printf '%s' "$value" | tr '[:upper:]' '[:lower:]')"
  case "$normalized" in
    ""|123:fake|fake|fake-token|changeme|replace-me|your-bot-token|your-telegram-bot-token|"<telegram-bot-token>"|"<botfather-token>")
      return 0
      ;;
  esac
  return 1
}

require_real_telegram_token() {
  local value="${1:-}" env_file="${2:-$(current_bot_env_file)}"
  if [ -z "$value" ]; then
    echo "TELEGRAM_BOT_TOKEN must be set in $env_file" >&2
    exit 1
  fi
  if telegram_token_is_placeholder "$value"; then
    echo "TELEGRAM_BOT_TOKEN in $env_file is still a placeholder." >&2
    echo "Set a real token from @BotFather before running startup scripts." >&2
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
