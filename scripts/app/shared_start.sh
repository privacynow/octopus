#!/usr/bin/env bash
# Shared Runtime startup: one webhook ingress service plus scaled worker services.
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

read_bot_env_value() {
  local key="$1" env_file="${2:-$BOT_ENV_FILE}"
  grep -E "^\s*${key}=" "$env_file" 2>/dev/null | sed 's/.*=\s*//' | tr -d '\r' | tr -d '"' | tr -d "'" || true
}

require_bot_env_value() {
  local key="$1" value="${2:-}"
  if [ -z "$value" ]; then
    echo "$key must be set in $BOT_ENV_FILE" >&2
    exit 1
  fi
}

create_env_file_if_missing() {
  if [ -f "$BOT_ENV_FILE" ]; then
    return
  fi

  local default_name="$INSTANCE"
  [ "$default_name" = "default" ] && default_name="product-shared"

  local display_name token provider mode webhook_url webhook_secret default_registry_url registry_url registry_token
  echo "No $BOT_ENV_FILE found. Running Shared Runtime first-time setup."
  display_name="$(prompt_with_default "Bot name" "$default_name")"
  token="$(prompt_channel_token_with_help telegram "Paste your bot token here")"
  provider="$(prompt_with_default "Provider (claude or codex)" "claude")"
  case "$provider" in
    claude|codex) ;;
    *) echo "Invalid provider '$provider'. Use claude or codex." >&2; exit 1 ;;
  esac
  mode="$(prompt_with_default "Mode (registry or standalone)" "standalone")"
  case "$mode" in
    registry|standalone) ;;
    *) echo "Invalid mode '$mode'. Use registry or standalone." >&2; exit 1 ;;
  esac
  while true; do
    webhook_url="$(prompt_with_default "Public webhook URL (must end in /webhook)" "")"
    if [ -n "$webhook_url" ]; then
      break
    fi
    echo "Webhook URL is required for Shared Runtime." >&2
  done
  webhook_secret="$(prompt_with_default "Webhook secret (optional)" "")"

  registry_url=""
  registry_token=""
  if [ "$mode" = "registry" ]; then
    default_registry_url="http://host.docker.internal:8787"
    if [ "$(uname -s)" = "Linux" ]; then
      default_registry_url="http://172.17.0.1:8787"
    fi
    registry_url="$(prompt_with_default "Registry URL" "$default_registry_url")"
    while true; do
      registry_token="$(prompt_with_default "Registry enrollment token" "")"
      if [ -n "$registry_token" ]; then
        break
      fi
      echo "Registry enrollment token is required for registry mode." >&2
    done
  fi

  {
    echo "BOT_INSTANCE=$INSTANCE"
    echo "TELEGRAM_BOT_TOKEN=$token"
    echo "BOT_PROVIDER=$provider"
    echo "BOT_COMPACT_MODE=1"
    echo "BOT_ALLOW_OPEN=1"
    echo "BOT_TIMEOUT_SECONDS=3600"
    echo "BOT_WORKING_DIR=/home/bot"
    echo "BOT_AGENT_MODE=$mode"
    echo "BOT_AGENT_DISPLAY_NAME=\"$(escape_env "$display_name")\""
    echo "BOT_WEBHOOK_URL=$webhook_url"
    if [ -n "$webhook_secret" ]; then
      echo "BOT_WEBHOOK_SECRET=$(escape_env "$webhook_secret")"
    fi
    if [ "$mode" = "registry" ]; then
      echo "BOT_AGENT_REGISTRY_URL=$registry_url"
      echo "BOT_AGENT_REGISTRY_ENROLL_TOKEN=$registry_token"
    fi
  } > "$BOT_ENV_FILE"

  echo "Created $BOT_ENV_FILE"
}

telegram_set_webhook() {
  local token="$1" webhook_url="$2" secret="$3" response payload

  payload="{\"url\":\"${webhook_url}\",\"drop_pending_updates\":false"
  if [ -n "$secret" ]; then
    payload="${payload},\"secret_token\":\"${secret}\""
  fi
  payload="${payload}}"

  response="$(curl -fsS \
    -H 'Content-Type: application/json' \
    -d "$payload" \
    "https://api.telegram.org/bot${token}/setWebhook")"

  if ! python3 -c 'import json,sys; data=json.loads(sys.argv[1]); raise SystemExit(0 if data.get("ok") else 1)' "$response"; then
    if python3 -c 'import json,sys; data=json.loads(sys.argv[1]); desc=str(data.get("description","")).lower(); raise SystemExit(0 if "unauthorized" in desc else 1)' "$response"; then
      echo "Telegram webhook registration failed: Telegram rejected TELEGRAM_BOT_TOKEN." >&2
      echo "Update TELEGRAM_BOT_TOKEN in $BOT_ENV_FILE with a valid token from @BotFather, then start again." >&2
      exit 1
    fi
    echo "Telegram webhook registration failed." >&2
    echo "$response" >&2
    exit 1
  fi
}

run_full_health_check_or_exit() {
  echo "Running full app health check before Shared Runtime startup..."
  if ! bot_shared_compose --profile bot run --rm bot-webhook python -m app.main --doctor; then
    echo "" >&2
    echo "Full app health check failed. Fix the issue above, then run ./scripts/app/shared_start.sh again." >&2
    exit 1
  fi
}

shared_services_are_running() {
  local statuses="" line="" status=""
  statuses="$(bot_shared_compose ps -a --format '{{.Service}} {{.Status}}' bot-webhook bot-worker 2>/dev/null | tr -d '\r' || true)"
  [ -n "$statuses" ] || return 1
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    status="${line#* }"
    case "$status" in
      Up*|running*|Running*)
        ;;
      *)
        return 1
        ;;
    esac
  done <<EOF
$statuses
EOF
  return 0
}

print_shared_startup_failure_help() {
  echo "Shared Runtime failed to stay up after startup." >&2
  echo "Running full app health check for a clearer diagnosis..." >&2
  if ! bot_shared_compose --profile bot run --rm bot-webhook python -m app.main --doctor >&2; then
    :
  fi
  echo "" >&2
  echo "If you need raw container logs:" >&2
  echo "  $(printf 'BOT_ENV_FILE=%s docker compose --project-directory . -f infra/compose/docker-compose.yml -f infra/compose/docker-compose.shared.yml --profile bot logs -f bot-webhook bot-worker' "$BOT_ENV_FILE")" >&2
}

create_env_file_if_missing
check_env_bot_required "$BOT_ENV_FILE"

agent_mode="$(read_bot_env_value BOT_AGENT_MODE)"
agent_mode="${agent_mode:-standalone}"

telegram_token="$(read_bot_env_value TELEGRAM_BOT_TOKEN)"
webhook_url="$(read_bot_env_value BOT_WEBHOOK_URL)"
webhook_secret="$(read_bot_env_value BOT_WEBHOOK_SECRET)"
database_url="$(read_bot_env_value BOT_DATABASE_URL)"
agent_registry_url="$(read_bot_env_value BOT_AGENT_REGISTRY_URL)"
agent_registry_enroll_token="$(read_bot_env_value BOT_AGENT_REGISTRY_ENROLL_TOKEN)"
worker_replicas="${BOT_WORKER_REPLICAS:-2}"
provider="$(get_bot_provider "$BOT_ENV_FILE")"

require_bot_env_value "TELEGRAM_BOT_TOKEN" "$telegram_token"
require_real_telegram_token "$telegram_token" "$BOT_ENV_FILE"
require_bot_env_value "BOT_WEBHOOK_URL" "$webhook_url"
if [ "$agent_mode" = "registry" ]; then
  require_bot_env_value "BOT_AGENT_REGISTRY_URL" "$agent_registry_url"
fi
check_provider_image "$provider" >/dev/null

echo "=== Shared Runtime start ==="
echo "Instance:      $INSTANCE"
echo "Config:        $BOT_ENV_FILE"
echo "Provider:      $provider"
echo "Agent mode:    $agent_mode"
echo "Webhook URL:   $webhook_url"
echo "Workers:       $worker_replicas"

if [ "$agent_mode" = "registry" ]; then
  echo "Registry URL:  $agent_registry_url"
  echo "Publisher:     bot-webhook (singleton registry sync + health mirror)"
  if [ -z "$agent_registry_enroll_token" ]; then
    echo "Note: BOT_AGENT_REGISTRY_ENROLL_TOKEN is empty. Existing enrollment may still work, but first-time enrollment will fail until a token is provided." >&2
  fi
fi

if [ -n "$database_url" ]; then
  echo "Backend:       Postgres"
  if ! bot_shared_compose up -d postgres; then
    echo "Failed to start postgres service." >&2
    exit 1
  fi
  bot_shared_compose --profile tools run --rm db-bootstrap
  bot_shared_compose --profile tools run --rm db-update
else
  echo "Backend:       SQLite (same host shared volume)"
fi

run_full_health_check_or_exit

echo "Registering Telegram webhook..."
telegram_set_webhook "$telegram_token" "$webhook_url" "$webhook_secret"

echo "Starting shared runtime services..."
bot_shared_compose --profile bot up -d --remove-orphans --scale "bot-worker=${worker_replicas}" bot-webhook bot-worker

echo "Waiting a few seconds to confirm shared services stayed up..."
sleep 5
if ! shared_services_are_running; then
  print_shared_startup_failure_help
  exit 1
fi

echo ""
echo "Shared Runtime started."
echo "Ingress:   bot-webhook"
echo "Workers:   bot-worker x${worker_replicas}"
echo "Logs:      $(printf 'BOT_ENV_FILE=%s docker compose --project-directory . -f infra/compose/docker-compose.yml -f infra/compose/docker-compose.shared.yml --profile bot logs -f bot-webhook bot-worker' "$BOT_ENV_FILE")"
echo "Stop:      $(printf 'BOT_ENV_FILE=%s docker compose --project-directory . -f infra/compose/docker-compose.yml -f infra/compose/docker-compose.shared.yml --profile bot down -v --remove-orphans' "$BOT_ENV_FILE")"
