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
    echo "Telegram webhook registration failed:" >&2
    echo "$response" >&2
    exit 1
  fi
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

echo "Registering Telegram webhook..."
telegram_set_webhook "$telegram_token" "$webhook_url" "$webhook_secret"

echo "Starting shared runtime services..."
bot_shared_compose --profile bot up -d --remove-orphans --scale "bot-worker=${worker_replicas}" bot-webhook bot-worker

echo "Waiting a few seconds to confirm shared services stayed up..."
sleep 5
if bot_shared_compose ps -a --format '{{.Service}} {{.Status}}' bot-webhook bot-worker 2>/dev/null | grep -q "Exited"; then
  print_shared_startup_failure_help
  exit 1
fi

echo ""
echo "Shared Runtime started."
echo "Ingress:   bot-webhook"
echo "Workers:   bot-worker x${worker_replicas}"
echo "Logs:      $(printf 'BOT_ENV_FILE=%s docker compose --project-directory . -f infra/compose/docker-compose.yml -f infra/compose/docker-compose.shared.yml --profile bot logs -f bot-webhook bot-worker' "$BOT_ENV_FILE")"
echo "Stop:      $(printf 'BOT_ENV_FILE=%s docker compose --project-directory . -f infra/compose/docker-compose.yml -f infra/compose/docker-compose.shared.yml --profile bot down -v --remove-orphans' "$BOT_ENV_FILE")"
