#!/usr/bin/env bash
# Bot env I/O and token helpers.

resolve_bot_env_file() {
  local env_file="${1:-${BOT_ENV_FILE:-}}"
  if [ -n "$env_file" ]; then
    printf '%s\n' "$env_file"
    return 0
  fi
  echo "No bot configuration is selected." >&2
  echo "Run ./octopus to create or choose a bot first." >&2
  return 1
}

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

escape_env_value() {
  printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'
}

write_env_assignment_line() {
  local key="$1" value="${2:-}"
  case "$value" in
    *[[:space:]]*|*\#*|"")
      printf '%s="%s"\n' "$key" "$(escape_env_value "$value")"
      ;;
    *)
      printf '%s=%s\n' "$key" "$value"
      ;;
  esac
}

upsert_env_file_value() {
  local key="$1" value="${2:-}" env_file=""
  env_file="$(resolve_bot_env_file "${3:-}")" || return 1
  local tmp_file found=0 line=""
  tmp_file="$(mktemp "${TMPDIR:-/tmp}/octopus-env.XXXXXX")"
  if [ -f "$env_file" ]; then
    while IFS= read -r line || [ -n "$line" ]; do
      case "$line" in
        "$key="*|[[:space:]]"$key="*)
          write_env_assignment_line "$key" "$value" >> "$tmp_file"
          found=1
          ;;
        *)
          printf '%s\n' "$line" >> "$tmp_file"
          ;;
      esac
    done < "$env_file"
  fi
  if [ "$found" -eq 0 ]; then
    write_env_assignment_line "$key" "$value" >> "$tmp_file"
  fi
  mv "$tmp_file" "$env_file"
  restrict_secret_file_permissions "$env_file"
}

remove_env_file_value() {
  local key="$1" env_file=""
  env_file="$(resolve_bot_env_file "${2:-}")" || return 1
  local tmp_file line=""
  tmp_file="$(mktemp "${TMPDIR:-/tmp}/octopus-env.XXXXXX")"
  if [ -f "$env_file" ]; then
    while IFS= read -r line || [ -n "$line" ]; do
      case "$line" in
        "$key="*|[[:space:]]"$key="*)
          ;;
        *)
          printf '%s\n' "$line" >> "$tmp_file"
          ;;
      esac
    done < "$env_file"
    mv "$tmp_file" "$env_file"
  else
    rm -f "$tmp_file"
  fi
  restrict_secret_file_permissions "$env_file"
}

redact_value_for_prompt() {
  local channel="${1:-telegram}" value="${2:-}" visible=""
  case "$channel" in
    telegram)
      if [ -z "$value" ]; then
        echo ""
        return
      fi
      if telegram_token_is_placeholder "$value"; then
        echo "$value"
        return
      fi
      if [ "${#value}" -le 16 ]; then
        echo "<set>"
        return
      fi
      visible="$(printf '%s' "$value" | cut -c1-10)"
      printf '%s…%s' "$visible" "${value: -4}"
      ;;
    *)
      if [ -n "$value" ]; then
        echo "<set>"
      fi
      ;;
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
      telegram_token_format_valid "$value"
      ;;
    *)
      return 1
      ;;
  esac
}

telegram_token_format_valid() {
  [[ "${1:-}" =~ ^[0-9]+:[A-Za-z0-9_-]+$ ]]
}

prompt_channel_token_with_help() {
  local channel="${1:-telegram}" prompt_label="${2:-Paste your bot token here}"
  local current_value="${3:-}" current_note="${4:-}" allow_current_default="${5:-1}"
  local token="" prompt_suffix="" current_display=""
  print_channel_setup_help "$channel"
  if [ -n "$current_note" ]; then
    echo "$current_note" >&2
  fi
  current_display="$(redact_value_for_prompt "$channel" "$current_value")"
  if [ -n "$current_display" ]; then
    prompt_suffix=" [default: $current_display]"
    echo "Current value [default: $current_display]" >&2
  fi
  while true; do
    read -r -p "${prompt_label}${prompt_suffix}: " token || {
      if [ "$allow_current_default" = "1" ] && [ -n "$current_value" ]; then
        printf '%s' "$current_value"
        return 0
      fi
      return 1
    }
    if [ -z "$token" ] && [ "$allow_current_default" = "1" ] && [ -n "$current_value" ]; then
      token="$current_value"
    fi
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
    http://registry:*|http://localhost:*|http://127.0.0.1:*|http://[::1]:*)
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
  local env_file="${1:-}" slug=""
  env_file="$(resolve_bot_env_file "$env_file")" || exit 1
  if [ ! -f "$env_file" ]; then
    slug="$(basename "$(dirname "$env_file")" 2>/dev/null || true)"
    if [ -n "$slug" ] && [ "$slug" != "." ] && [ "$slug" != ".." ]; then
      echo "Bot '$slug' is not configured." >&2
    else
      echo "Bot configuration is missing." >&2
    fi
    echo "Run ./octopus to create or repair the bot." >&2
    exit 1
  fi
}

read_bot_env_value() {
  local key="$1" env_file="${2:-${BOT_ENV_FILE:-}}"
  [ -n "$env_file" ] || return 0
  grep -E "^[[:space:]]*${key}=" "$env_file" 2>/dev/null | sed 's/^[^=]*=[[:space:]]*//' | tr -d '\r' | tr -d '"' | tr -d "'" || true
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
  local value="${1:-}" env_file="${2:-${BOT_ENV_FILE:-bot env file}}"
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

get_bot_provider() {
  local env_file="${1:-${BOT_ENV_FILE:-}}"
  local p
  [ -n "$env_file" ] || {
    echo "claude"
    return 0
  }
  p=$(grep -E '^[[:space:]]*BOT_PROVIDER=' "$env_file" 2>/dev/null | sed 's/^[^=]*=[[:space:]]*//' | tr -d '\r' | tr -d '"' | tr -d "'" || true)
  echo "${p:-claude}"
}

normalize_slug() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9-' '-' | sed 's/^-//;s/-$//' | cut -c1-32
}

validate_telegram_token() {
  local token="$1"
  printf '%s' "$token" | python3 -c "
import json
import sys
import urllib.request

token = sys.stdin.read().strip()
url = f'https://api.telegram.org/bot{token}/getMe'
try:
    with urllib.request.urlopen(url, timeout=10) as resp:
        data = json.loads(resp.read())
    if data.get('ok'):
        result = data['result']
        print(result.get('id', ''))
        print(result.get('username', ''))
        print(result.get('first_name', ''))
        sys.exit(0)
except Exception:
    pass
sys.exit(1)
"
}
