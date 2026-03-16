#!/usr/bin/env bash
# Instance-aware guided Docker path: create env file if needed, ensure provider
# auth, optionally start the registry, then start the bot.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_DIR"
# shellcheck source=scripts/lib_env.sh
. "$REPO_DIR/scripts/lib_env.sh"

INSTANCE="${1:-default}"
if [ "$INSTANCE" = "default" ]; then
  BOT_ENV_FILE=".env.bot"
else
  BOT_ENV_FILE=".env.bot.$INSTANCE"
fi
export BOT_ENV_FILE

echo "=== Guided setup and start ==="
echo "Instance: $INSTANCE"
echo "Config:   $BOT_ENV_FILE"

prompt_with_default() {
  local prompt="$1" default="${2:-}" value=""
  if [ -n "$default" ]; then
    read -r -p "$prompt [$default]: " value || true
    echo "${value:-$default}"
    return
  fi
  read -r -p "$prompt: " value || true
  echo "$value"
}

escape_env() {
  printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'
}

create_env_file_if_missing() {
  if [ -f "$BOT_ENV_FILE" ]; then
    return
  fi

  local default_name="$INSTANCE"
  [ "$default_name" = "default" ] && default_name="product"

  local display_name token provider mode registry_url registry_token role tags description skills allowed_users working_dir timeout
  display_name="$(prompt_with_default "Bot name" "$default_name")"
  while true; do
    token="$(prompt_with_default "Telegram bot token" "")"
    if [ -n "$token" ]; then
      break
    fi
    echo "Telegram bot token is required."
  done
  provider="$(prompt_with_default "Provider (claude or codex)" "claude")"
  case "$provider" in
    claude|codex) ;;
    *) echo "Invalid provider '$provider'. Use claude or codex." >&2; exit 1 ;;
  esac
  mode="$(prompt_with_default "Mode (registry or standalone)" "registry")"
  case "$mode" in
    registry|standalone) ;;
    *) echo "Invalid mode '$mode'. Use registry or standalone." >&2; exit 1 ;;
  esac
  registry_url=""
  registry_token=""
  if [ "$mode" = "registry" ]; then
    registry_url="$(prompt_with_default "Registry URL" "http://host.docker.internal:8787")"
    registry_token="$(prompt_with_default "Registry enrollment token" "")"
  fi
  role="$(prompt_with_default "Role" "")"
  tags="$(prompt_with_default "Tags (comma-separated)" "")"
  description="$(prompt_with_default "Short description" "")"
  skills="$(prompt_with_default "Agent skills (comma-separated)" "")"
  allowed_users="$(prompt_with_default "Allowed users (blank = open)" "")"
  working_dir="$(prompt_with_default "Working dir" "/home/bot")"
  timeout="$(prompt_with_default "Timeout seconds" "3600")"

  {
    echo "BOT_INSTANCE=$INSTANCE"
    echo "TELEGRAM_BOT_TOKEN=$token"
    echo "BOT_PROVIDER=$provider"
    echo "BOT_TIMEOUT_SECONDS=$timeout"
    echo "BOT_WORKING_DIR=$working_dir"
    echo "BOT_COMPACT_MODE=1"
    if [ -n "$allowed_users" ]; then
      echo "BOT_ALLOWED_USERS=$allowed_users"
    else
      echo "BOT_ALLOW_OPEN=1"
    fi
    if [ -n "$role" ]; then
      echo "BOT_ROLE=\"$(escape_env "$role")\""
    fi
    if [ -n "$skills" ]; then
      echo "BOT_SKILLS=$skills"
    fi
    echo "BOT_AGENT_MODE=$mode"
    echo "BOT_AGENT_DISPLAY_NAME=\"$(escape_env "$display_name")\""
    if [ -n "$role" ]; then
      echo "BOT_AGENT_ROLE=\"$(escape_env "$role")\""
    fi
    if [ -n "$tags" ]; then
      echo "BOT_AGENT_TAGS=$tags"
    fi
    if [ -n "$description" ]; then
      echo "BOT_AGENT_DESCRIPTION=\"$(escape_env "$description")\""
    fi
    if [ -n "$skills" ]; then
      echo "BOT_AGENT_SKILLS=$skills"
    fi
    echo "BOT_AGENT_POLL_INTERVAL_SECONDS=5"
    if [ "$mode" = "registry" ]; then
      echo "BOT_AGENT_REGISTRY_URL=$registry_url"
      if [ -n "$registry_token" ]; then
        echo "BOT_AGENT_REGISTRY_ENROLL_TOKEN=$registry_token"
      fi
    fi
  } > "$BOT_ENV_FILE"

  echo "Created $BOT_ENV_FILE"
}

auto_start_local_registry_if_needed() {
  local mode url
  mode="$(grep -E '^\s*BOT_AGENT_MODE=' "$BOT_ENV_FILE" 2>/dev/null | sed 's/.*=\s*//' | tr -d '\r' | tr -d '"' | tr -d "'" || true)"
  url="$(grep -E '^\s*BOT_AGENT_REGISTRY_URL=' "$BOT_ENV_FILE" 2>/dev/null | sed 's/.*=\s*//' | tr -d '\r' | tr -d '"' | tr -d "'" || true)"
  if [ "$mode" != "registry" ]; then
    return
  fi
  case "$url" in
    http://host.docker.internal:8787|http://localhost:8787)
      "$REPO_DIR/scripts/registry/start.sh"
      ;;
  esac
}

create_env_file_if_missing
check_env_bot_required "$BOT_ENV_FILE"

env_provider="$(get_bot_provider "$BOT_ENV_FILE")"

auto_start_local_registry_if_needed

if grep -qE '^\s*BOT_DATABASE_URL=.*postgres' "$BOT_ENV_FILE" 2>/dev/null; then
  if ! ./scripts/db/dev_up_postgres.sh; then
    echo "Postgres setup failed. Fix the issue above, then run ./scripts/app/guided_start.sh again." >&2
    exit 1
  fi
fi

echo ""
echo "Step 1/3: Bot image for $env_provider..."
need_build=0
if ! docker image inspect "telegram-agent-bot:$env_provider" >/dev/null 2>&1; then
  need_build=1
elif [ -f .bot-image-build-rev ]; then
  current_rev="$(git rev-parse HEAD 2>/dev/null || true)"
  built_rev="$(cat .bot-image-build-rev 2>/dev/null || true)"
  if [ -n "$current_rev" ] && [ -n "$built_rev" ] && [ "$current_rev" != "$built_rev" ]; then
    need_build=1
    echo "Repo revision changed since image was built; rebuilding."
  fi
fi
if [ "$need_build" -eq 1 ]; then
  ./scripts/provider/build_bot_image.sh "$env_provider"
else
  echo "Image telegram-agent-bot:$env_provider already present and up to date."
fi

echo ""
echo "Step 2/3: Provider auth..."
if ./scripts/provider/provider_status.sh >/dev/null 2>&1; then
  echo "Provider already authenticated."
else
  echo "Provider not authenticated. Running one-time interactive login..."
  ./scripts/provider/provider_login.sh "$env_provider"
  echo "Verifying provider auth..."
  if ! ./scripts/provider/provider_status.sh; then
    echo "Provider health check still failed after login (see above)." >&2
    exit 1
  fi
fi

echo ""
echo "Step 3/3: Starting bot (background service)..."
./scripts/app/start_instance.sh "$INSTANCE"

echo "Waiting a few seconds to confirm the bot stayed up..."
sleep 5
if bot_compose ps -a --format '{{.Status}}' bot 2>/dev/null | grep -q Exited; then
  echo "Bot failed to start (container exited). Last logs:" >&2
  bot_compose logs --tail=40 bot >&2
  exit 1
fi

echo ""
echo "Bot started. Message it in Telegram to use it."
echo "Logs: ./scripts/app/logs_instance.sh $INSTANCE"
echo "Stop: ./scripts/app/stop_instance.sh $INSTANCE"
