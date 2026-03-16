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

_LOCAL_REGISTRY_ENROLL_TOKEN=""
_USED_QUICK_SETUP=0

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

  local display_name token setup_mode provider mode default_registry_url registry_url registry_token
  local role tags description skills allowed_users working_dir timeout
  display_name="$(prompt_with_default "Bot name" "$default_name")"
  while true; do
    token="$(prompt_with_default "Telegram bot token" "")"
    if [ -n "$token" ]; then
      break
    fi
    echo "Telegram bot token is required."
  done
  setup_mode="$(prompt_with_default "Setup mode (quick/full)" "quick")"
  case "$setup_mode" in
    quick|full) ;;
    *) echo "Invalid setup mode '$setup_mode'. Use quick or full." >&2; exit 1 ;;
  esac
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
    default_registry_url="http://host.docker.internal:8787"
    if [ "$(uname -s)" = "Linux" ]; then
      default_registry_url="http://172.17.0.1:8787"
    fi
    registry_url="$(prompt_with_default "Registry URL" "$default_registry_url")"
  fi

  {
    echo "BOT_INSTANCE=$INSTANCE"
    echo "TELEGRAM_BOT_TOKEN=$token"
    echo "BOT_PROVIDER=$provider"
    echo "BOT_COMPACT_MODE=1"
    echo "BOT_AGENT_MODE=$mode"
    echo "BOT_AGENT_DISPLAY_NAME=\"$(escape_env "$display_name")\""
    if [ "$mode" = "registry" ]; then
      echo "BOT_AGENT_REGISTRY_URL=$registry_url"
    fi
  } > "$BOT_ENV_FILE"

  auto_start_local_registry_if_needed

  if [ "$mode" = "registry" ]; then
    if [ -n "$_LOCAL_REGISTRY_ENROLL_TOKEN" ]; then
      registry_token="$_LOCAL_REGISTRY_ENROLL_TOKEN"
      echo "Using local registry enrollment token from $REPO_DIR/.env.registry"
    else
      while true; do
        registry_token="$(prompt_with_default "Registry enrollment token (check your registry's .env.registry or admin panel)" "")"
        if [ -n "$registry_token" ]; then
          break
        fi
        echo "Registry enrollment token is required for registry mode."
      done
    fi
  fi

  if [ "$setup_mode" = "full" ]; then
    role="$(prompt_with_default "Role" "")"
    tags="$(prompt_with_default "Tags (comma-separated)" "")"
    description="$(prompt_with_default "Short description" "")"
    skills="$(prompt_with_default "Agent skills (comma-separated)" "")"
    allowed_users="$(prompt_with_default "Allowed users (blank = open)" "")"
    working_dir="$(prompt_with_default "Working dir" "/home/bot")"
    timeout="$(prompt_with_default "Timeout seconds" "3600")"
  else
    _USED_QUICK_SETUP=1
    role=""
    tags=""
    description=""
    skills=""
    allowed_users=""
    working_dir="/home/bot"
    timeout="3600"
  fi

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
      echo "# Registry URL: use host.docker.internal on macOS/Windows, 172.17.0.1 on Linux."
      echo "BOT_AGENT_REGISTRY_URL=$registry_url"
      echo "BOT_AGENT_REGISTRY_ENROLL_TOKEN=$registry_token"
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
    http://host.docker.internal:8787|http://localhost:8787|http://172.17.0.1:8787)
      "$REPO_DIR/scripts/registry/start.sh"
      _LOCAL_REGISTRY_ENROLL_TOKEN="$(grep -E '^\s*REGISTRY_ENROLL_TOKEN=' "$REPO_DIR/.env.registry" 2>/dev/null | sed 's/.*=//' | tr -d '\r' || true)"
      ;;
  esac
}

read_registry_env_value() {
  local key="$1"
  grep -E "^\s*${key}=" "$REPO_DIR/.env.registry" 2>/dev/null | sed 's/.*=//' | tr -d '\r' || true
}

build_registry_ui_display_url() {
  local registry_url="$1" browser_base="" ui_token="" registry_port=""
  if [ -z "$registry_url" ]; then
    return
  fi

  case "$registry_url" in
    http://host.docker.internal:*|http://localhost:*|http://172.17.0.1:*)
      registry_port="${registry_url##*:}"
      browser_base="http://localhost:${registry_port}"
      if [ -n "$_LOCAL_REGISTRY_ENROLL_TOKEN" ]; then
        registry_port="$(read_registry_env_value REGISTRY_PORT)"
        ui_token="$(read_registry_env_value REGISTRY_UI_TOKEN)"
        if [ -n "$registry_port" ]; then
          browser_base="http://localhost:${registry_port}"
        fi
      fi
      ;;
    *)
      browser_base="${registry_url%/}"
      ;;
  esac

  browser_base="${browser_base%/}/ui"
  if [ -n "$ui_token" ]; then
    printf '%s?token=%s' "$browser_base" "$ui_token"
  else
    printf '%s' "$browser_base"
  fi
}

print_box_wrapped_line() {
  local text="$1"
  while IFS= read -r line; do
    printf "║    %-58s║\n" "$line"
  done < <(printf '%s\n' "$text" | fold -w 58)
}

create_env_file_if_missing
check_env_bot_required "$BOT_ENV_FILE"

env_provider="$(get_bot_provider "$BOT_ENV_FILE")"

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

mode_display="$(grep -E '^\s*BOT_AGENT_MODE=' "$BOT_ENV_FILE" 2>/dev/null | sed 's/.*=\s*//' | tr -d '\r' | tr -d '"' | tr -d "'" || true)"
registry_url_display="$(grep -E '^\s*BOT_AGENT_REGISTRY_URL=' "$BOT_ENV_FILE" 2>/dev/null | sed 's/.*=\s*//' | tr -d '\r' | tr -d '"' | tr -d "'" || true)"
registry_ui_display="$(build_registry_ui_display_url "$registry_url_display")"

echo ""
if [ "$_USED_QUICK_SETUP" -eq 1 ]; then
  echo "Advanced settings (role, tags, description, skills) can be set"
  echo "by editing $BOT_ENV_FILE after setup."
  echo ""
fi
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  Bot is running!                                            ║"
echo "║                                                              ║"
echo "║  • Open Telegram and message your bot to start.             ║"
if [ "$mode_display" = "registry" ] && [ -n "$registry_ui_display" ]; then
  printf "║  • Registry UI:%-46s║\n" ""
  print_box_wrapped_line "$registry_ui_display"
fi
printf "║  • Logs:  %-48s║\n" "./scripts/app/logs_instance.sh $INSTANCE"
printf "║  • Stop:  %-48s║\n" "./scripts/app/stop_instance.sh $INSTANCE"
echo "╚══════════════════════════════════════════════════════════════╝"
